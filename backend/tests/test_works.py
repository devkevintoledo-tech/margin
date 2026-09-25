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
    "cover_i": 7316188,
    "readinglog_count": 1036,
    "subject": ["genre:science fiction"],
}
OL_RED_RISING_BUNDLE = {
    "key": "/works/OL99999W",
    "title": "Red Rising 3-Book Bundle",
    "author_name": ["Pierce Brown"],
    "edition_count": 2,
}


def mock_upstream(ol_docs=None):
    """Mock both upstreams and return their routes, so call counts stay readable.

    Re-registering a route with ``respx.get(URL)`` replaces the mocked one and
    resets its counter, so a test that wants a count must hold the route the
    mock returned.
    """
    google = respx.get(GOOGLE_URL).mock(
        return_value=Response(200, json={"items": RED_RISING_VOLUMES})
    )
    # Opening a work page enriches it, and enrichment HEADs every cover.
    for slug in ("deluxe", "plain"):
        respx.head(f"https://x/{slug}?zoom=0").mock(
            return_value=Response(200, headers={"content-type": "image/jpeg"})
        )
    ol = respx.get(OL_URL).mock(
        return_value=Response(200, json={"docs": ol_docs if ol_docs is not None else [OL_RED_RISING]})
    )
    return google, ol


@respx.mock
async def test_search_returns_one_work_per_open_library_doc(client):
    google, _ = mock_upstream()
    resp = await client.get("/api/works/search", params={"q": "red rising"})
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert len(body) == 1
    work = body[0]
    assert work["title"] == "Red Rising"
    assert work["author"] == "Pierce Brown"
    assert work["first_publish_year"] == 2014
    # OL's total, not a count of the editions we happen to hold — search
    # ingests no editions at all.
    assert work["edition_count"] == 26
    # Google Books is no longer on the search path; its blurbs and its editions
    # arrive later, when the work's own page is first opened.
    assert work["description"] is None
    assert not google.called


@respx.mock
async def test_search_hides_collections_but_keeps_them_reachable(client, db_session):
    from sqlalchemy import select
    from app.models import Work, WorkKind

    mock_upstream(ol_docs=[OL_RED_RISING, OL_RED_RISING_BUNDLE])
    body = (await client.get("/api/works/search", params={"q": "red rising"})).json()
    assert [w["title"] for w in body] == ["Red Rising"]

    collections = (
        await db_session.execute(select(Work).where(Work.kind == WorkKind.collection))
    ).scalars().all()
    assert len(collections) == 1  # stored, not dropped

    resp = await client.get(f"/api/works/{collections[0].id}")
    assert resp.status_code == 200
    assert resp.json()["kind"] == "collection"


@respx.mock
async def test_search_is_idempotent_and_costs_no_second_open_library_call(client):
    _, ol_route = mock_upstream()
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
async def test_search_degrades_rather_than_failing_when_both_upstreams_fail(client):
    # There is no 503 to return any more: search answers from the local
    # catalog, so a total upstream outage costs recall, not the request.
    respx.get(OL_URL).mock(return_value=Response(503, json={}))
    respx.get(GOOGLE_URL).mock(return_value=Response(429, json={"error": "rate limited"}))
    resp = await client.get("/api/works/search", params={"q": "red rising"})
    assert resp.status_code == 200
    assert resp.json() == []


@respx.mock
async def test_search_maps_a_genre_onto_the_work(client, db_session):
    from app.models import Genre

    db_session.add(Genre(name="Science Fiction", slug="science-fiction"))
    await db_session.flush()
    # The genre now comes from Open Library's explicit `genre:` subject tag,
    # not from guessing at Google's free-text categories.
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


def bare_work(**kw):
    import uuid

    from app.models import Work, WorkKind, WorkProvenance, WorkSource

    base = dict(
        source=WorkSource.openlibrary,
        external_id=f"OL{uuid.uuid4().hex[:8]}W",
        canonical_key="red rising\x1fpierce brown",
        title="Red Rising",
        author="Pierce Brown",
        kind=WorkKind.single,
        identity_provenance=WorkProvenance.isbn,
    )
    base.update(kw)
    return Work(**base)


async def test_cover_prefers_open_library_over_the_representative_edition(db_session):
    from app.models import Book
    from app.services.works import load_work_presentation

    work = bare_work(ol_cover_id=7316188)
    db_session.add(work)
    await db_session.flush()
    edition = Book(
        source="google_books",
        external_id="g1",
        title="Red Rising",
        author="Pierce Brown",
        work_id=work.id,
        cover_url="https://books.google.com/placeholder",
    )
    db_session.add(edition)
    await db_session.flush()
    work.representative_book_id = edition.id
    await db_session.flush()

    got = await load_work_presentation(db_session, [work.id])
    assert got[work.id].cover_url == "https://covers.openlibrary.org/b/id/7316188-L.jpg"


async def test_cover_falls_back_to_the_edition_when_open_library_has_none(db_session):
    from app.models import Book
    from app.services.works import load_work_presentation

    work = bare_work()
    db_session.add(work)
    await db_session.flush()
    edition = Book(
        source="google_books",
        external_id="g2",
        title="Red Rising",
        author="Pierce Brown",
        work_id=work.id,
        cover_url="https://books.google.com/real.jpg",
    )
    db_session.add(edition)
    await db_session.flush()
    work.representative_book_id = edition.id
    await db_session.flush()

    got = await load_work_presentation(db_session, [work.id])
    assert got[work.id].cover_url == "https://books.google.com/real.jpg"


async def test_a_work_with_no_editions_still_presents(db_session):
    from app.services.works import load_work_presentation

    work = bare_work(ol_cover_id=7316188, ol_edition_count=26, description="A boy.")
    db_session.add(work)
    await db_session.flush()

    got = await load_work_presentation(db_session, [work.id])
    assert got[work.id].cover_url == "https://covers.openlibrary.org/b/id/7316188-L.jpg"
    assert got[work.id].description == "A boy."
    assert got[work.id].edition_count == 26


async def test_edition_count_prefers_open_librarys_total(db_session):
    from app.models import Book
    from app.services.works import load_work_presentation

    # OL knows Red Rising has 26 editions; we have ingested one.
    work = bare_work(ol_edition_count=26)
    db_session.add(work)
    await db_session.flush()
    db_session.add(
        Book(
            source="google_books",
            external_id="g3",
            title="Red Rising",
            author="Pierce Brown",
            work_id=work.id,
        )
    )
    await db_session.flush()

    got = await load_work_presentation(db_session, [work.id])
    assert got[work.id].edition_count == 26


async def test_edition_count_falls_back_to_the_local_count(db_session):
    from app.models import Book
    from app.services.works import load_work_presentation

    work = bare_work(ol_edition_count=0)
    db_session.add(work)
    await db_session.flush()
    db_session.add(
        Book(
            source="google_books",
            external_id="g4",
            title="Red Rising",
            author="Pierce Brown",
            work_id=work.id,
        )
    )
    await db_session.flush()

    got = await load_work_presentation(db_session, [work.id])
    assert got[work.id].edition_count == 1


async def test_description_prefers_the_enriched_edition(db_session):
    from app.models import Book
    from app.services.works import load_work_presentation

    work = bare_work(description="Short OL blurb.")
    db_session.add(work)
    await db_session.flush()
    edition = Book(
        source="google_books",
        external_id="g5",
        title="Red Rising",
        author="Pierce Brown",
        work_id=work.id,
        description="A richer Google blurb.",
    )
    db_session.add(edition)
    await db_session.flush()
    work.representative_book_id = edition.id
    await db_session.flush()

    got = await load_work_presentation(db_session, [work.id])
    assert got[work.id].description == "A richer Google blurb."
