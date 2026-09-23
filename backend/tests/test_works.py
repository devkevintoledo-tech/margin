import respx
from httpx import Response

GOOGLE_URL = "https://www.googleapis.com/books/v1/volumes"
OL_URL = "https://openlibrary.org/search.json"


def volume(vol_id, title, isbn=None, **info):
    data = {"title": title, "authors": ["Pierce Brown"], **info}
    if isbn:
        data["industryIdentifiers"] = [{"type": "ISBN_13", "identifier": isbn}]
    return {"id": vol_id, "volumeInfo": data}


# The motivating search: five Google volumes, one book.
RED_RISING_VOLUMES = [
    volume("g1", "Red Rising (Deluxe Slipcase Edition)", "9780345539809",
           imageLinks={"thumbnail": "http://x/deluxe?zoom=1"}),
    volume("g2", "Red Rising 01", "9781444758986"),
    volume("g3", "Red Rising", "9780345539823", description="A boy from the mines.",
           pageCount=400, imageLinks={"thumbnail": "http://x/plain?zoom=1"}),
    volume("g4", "Red Rising 3-Book Bundle"),
    volume("g5", "Red Rising 1-6 ebook collection"),
]

OL_RED_RISING = {
    "key": "/works/OL17076473W",
    "title": "Red Rising",
    "author_name": ["Pierce Brown"],
    "first_publish_year": 2014,
    "edition_count": 26,
    "isbn": ["9780345539809", "9781444758986", "9780345539823"],
}


def mock_upstream(ol_docs=None):
    respx.get(GOOGLE_URL).mock(
        return_value=Response(200, json={"items": RED_RISING_VOLUMES})
    )
    respx.get(OL_URL).mock(
        return_value=Response(200, json={"docs": ol_docs if ol_docs is not None else [OL_RED_RISING]})
    )


@respx.mock
async def test_search_collapses_editions_into_one_work(client):
    mock_upstream()
    resp = await client.get("/api/works/search", params={"q": "red rising"})
    assert resp.status_code == 200, resp.text
    body = resp.json()

    # Three single editions collapse to one work; two collections are hidden.
    assert len(body) == 1
    work = body[0]
    assert work["title"] == "Red Rising"
    assert work["author"] == "Pierce Brown"
    assert work["first_publish_year"] == 2014
    assert work["edition_count"] == 3
    # The richest edition supplies the cover and description.
    assert work["description"] == "A boy from the mines."
    assert work["cover_url"].startswith("https://")


@respx.mock
async def test_search_hides_collections_but_keeps_them_reachable(client, db_session):
    from sqlalchemy import select
    from app.models import Work, WorkKind

    mock_upstream()
    await client.get("/api/works/search", params={"q": "red rising"})

    collections = (
        await db_session.execute(select(Work).where(Work.kind == WorkKind.collection))
    ).scalars().all()
    assert len(collections) == 2  # stored, not dropped

    resp = await client.get(f"/api/works/{collections[0].id}")
    assert resp.status_code == 200
    assert resp.json()["kind"] == "collection"


@respx.mock
async def test_search_is_idempotent_and_costs_no_second_open_library_call(client):
    mock_upstream()
    ol_route = respx.get(OL_URL)
    first = (await client.get("/api/works/search", params={"q": "red rising"})).json()
    calls_after_first = ol_route.call_count
    second = (await client.get("/api/works/search", params={"q": "red rising"})).json()

    assert first[0]["id"] == second[0]["id"]
    assert ol_route.call_count == calls_after_first


@respx.mock
async def test_search_still_works_when_open_library_is_down(client):
    respx.get(GOOGLE_URL).mock(
        return_value=Response(200, json={"items": RED_RISING_VOLUMES})
    )
    respx.get(OL_URL).mock(return_value=Response(503, json={}))

    resp = await client.get("/api/works/search", params={"q": "red rising"})
    assert resp.status_code == 200
    # The heuristic still groups the three single editions by cleaned title.
    assert len(resp.json()) == 1


@respx.mock
async def test_search_returns_503_when_google_books_fails(client):
    respx.get(GOOGLE_URL).mock(return_value=Response(429, json={"error": "rate limited"}))
    resp = await client.get("/api/works/search", params={"q": "red rising"})
    assert resp.status_code == 503
    assert "unavailable" in resp.json()["detail"].lower()


@respx.mock
async def test_search_maps_a_genre_onto_the_work(client, db_session):
    from app.models import Genre

    db_session.add(Genre(name="Science Fiction", slug="science-fiction"))
    await db_session.flush()
    respx.get(GOOGLE_URL).mock(
        return_value=Response(
            200,
            json={"items": [volume("g9", "Red Rising", "9780345539809",
                                   categories=["Fiction / Science Fiction"])]},
        )
    )
    respx.get(OL_URL).mock(return_value=Response(200, json={"docs": [OL_RED_RISING]}))

    body = (await client.get("/api/works/search", params={"q": "red rising"})).json()
    assert body[0]["genre_id"] is not None


async def test_get_work_includes_shelf_status_for_owner(client, auth_headers, work):
    await client.post(
        f"/api/works/{work.id}/shelf", json={"status": "reading"}, headers=auth_headers
    )
    resp = await client.get(f"/api/works/{work.id}", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["shelf_status"] == "reading"


async def test_get_work_shelf_status_null_when_anonymous(client, work):
    resp = await client.get(f"/api/works/{work.id}")
    assert resp.status_code == 200
    assert resp.json()["shelf_status"] is None


async def test_get_work_follows_a_merge_tombstone(client, db_session, work):
    from app.models import Work, WorkKind, WorkProvenance, WorkSource

    merged = Work(
        source=WorkSource.heuristic,
        external_id="old",
        canonical_key=work.canonical_key,
        title=work.title,
        author=work.author,
        kind=WorkKind.single,
        identity_provenance=WorkProvenance.heuristic,
        merged_into_id=work.id,
    )
    db_session.add(merged)
    await db_session.flush()

    resp = await client.get(f"/api/works/{merged.id}")
    assert resp.status_code == 200
    assert resp.json()["id"] == str(work.id)


async def test_shelf_crud_is_keyed_on_the_work(client, auth_headers, work):
    created = await client.post(
        f"/api/works/{work.id}/shelf", json={"status": "want_to_read"}, headers=auth_headers
    )
    assert created.status_code == 201
    assert created.json()["work_id"] == str(work.id)

    duplicate = await client.post(
        f"/api/works/{work.id}/shelf", json={"status": "reading"}, headers=auth_headers
    )
    assert duplicate.status_code == 409

    updated = await client.put(
        f"/api/works/{work.id}/shelf", json={"status": "read"}, headers=auth_headers
    )
    assert updated.json()["status"] == "read"

    removed = await client.delete(f"/api/works/{work.id}/shelf", headers=auth_headers)
    assert removed.status_code == 204


async def test_work_threads_listing(client, auth_headers, work):
    await client.post(
        "/api/threads/",
        json={"title": "Is Darrow a hero?", "work_id": str(work.id), "content": "Discuss."},
        headers=auth_headers,
    )
    resp = await client.get(f"/api/works/{work.id}/threads")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["title"] == "Is Darrow a hero?"
    assert body[0]["post_count"] == 1
