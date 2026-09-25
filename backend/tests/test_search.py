import respx
from httpx import Response
from sqlalchemy import select

from app.models import SearchQuery, Work

OL_URL = "https://openlibrary.org/search.json"
GOOGLE_URL = "https://www.googleapis.com/books/v1/volumes"

DOCS = [
    {
        "key": "/works/OL17076473W",
        "title": "Red Rising",
        "author_name": ["Pierce Brown"],
        "first_publish_year": 2014,
        "edition_count": 26,
        "cover_i": 7316188,
        "readinglog_count": 1036,
        "ratings_count": 102,
        "subject": ["franchise:Red Rising", "genre:science fiction"],
    },
    {
        "key": "/works/OL19726995W",
        "title": "Iron Gold",
        "author_name": ["Pierce Brown"],
        "first_publish_year": 2018,
        "edition_count": 14,
        "cover_i": 14511722,
        "readinglog_count": 114,
        "subject": ["franchise:Red Rising", "series:Red Rising Saga"],
    },
]


@respx.mock
async def test_cold_query_ingests_from_open_library(client, db_session):
    route = respx.get(OL_URL).mock(return_value=Response(200, json={"docs": DOCS}))
    resp = await client.get("/api/works/search", params={"q": "red rising"})
    assert resp.status_code == 200
    titles = [w["title"] for w in resp.json()]
    assert titles == ["Red Rising", "Iron Gold"]
    assert route.call_count == 1


@respx.mock
async def test_cold_query_returns_covers_from_open_library(client):
    respx.get(OL_URL).mock(return_value=Response(200, json={"docs": DOCS}))
    resp = await client.get("/api/works/search", params={"q": "red rising"})
    covers = [w["cover_url"] for w in resp.json()]
    assert covers[0] == "https://covers.openlibrary.org/b/id/7316188-L.jpg"
    assert all(covers)


@respx.mock
async def test_repeat_query_makes_zero_upstream_calls_and_keeps_order(client):
    route = respx.get(OL_URL).mock(return_value=Response(200, json={"docs": DOCS}))
    first = await client.get("/api/works/search", params={"q": "red rising"})
    second = await client.get("/api/works/search", params={"q": "Red  Rising"})
    # Normalization collapses the two spellings onto one search_queries row.
    assert route.call_count == 1
    # The series must not vanish on the second search — the regression the
    # subjects index exists to prevent.
    assert [w["title"] for w in second.json()] == [w["title"] for w in first.json()]


@respx.mock
async def test_search_records_the_resolved_query(client, db_session):
    respx.get(OL_URL).mock(return_value=Response(200, json={"docs": DOCS}))
    await client.get("/api/works/search", params={"q": "Red Rising"})
    row = (
        await db_session.execute(
            select(SearchQuery).where(SearchQuery.normalized_query == "red rising")
        )
    ).scalar_one()
    assert row.result_count == 2


@respx.mock
async def test_open_library_failure_falls_back_to_google(client, db_session):
    respx.get(OL_URL).mock(return_value=Response(503))
    respx.get(GOOGLE_URL).mock(
        return_value=Response(
            200,
            json={
                "items": [
                    {
                        "id": "g1",
                        "volumeInfo": {
                            "title": "Red Rising",
                            "authors": ["Pierce Brown"],
                        },
                    }
                ]
            },
        )
    )
    resp = await client.get("/api/works/search", params={"q": "red rising"})
    assert resp.status_code == 200
    assert [w["title"] for w in resp.json()] == ["Red Rising"]


@respx.mock
async def test_open_library_failure_does_not_record_the_query(client, db_session):
    # Not recording means the next search retries upstream rather than being
    # permanently stuck with a degraded result set.
    respx.get(OL_URL).mock(return_value=Response(503))
    respx.get(GOOGLE_URL).mock(return_value=Response(200, json={"items": []}))
    await client.get("/api/works/search", params={"q": "red rising"})
    rows = (await db_session.execute(select(SearchQuery))).scalars().all()
    assert rows == []


@respx.mock
async def test_stale_query_is_refetched(client, db_session):
    from datetime import datetime, timedelta, timezone

    route = respx.get(OL_URL).mock(return_value=Response(200, json={"docs": DOCS}))
    await client.get("/api/works/search", params={"q": "red rising"})
    row = (await db_session.execute(select(SearchQuery))).scalar_one()
    row.resolved_at = datetime.now(timezone.utc) - timedelta(days=31)
    await db_session.flush()

    await client.get("/api/works/search", params={"q": "red rising"})
    assert route.call_count == 2


@respx.mock
async def test_ingest_does_not_duplicate_works_across_queries(client, db_session):
    respx.get(OL_URL).mock(return_value=Response(200, json={"docs": DOCS}))
    await client.get("/api/works/search", params={"q": "red rising"})
    await client.get("/api/works/search", params={"q": "iron gold"})
    works = (await db_session.execute(select(Work))).scalars().all()
    assert len(works) == 2
