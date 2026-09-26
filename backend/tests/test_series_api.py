"""The series page: its books, its description, its room."""

import uuid
from datetime import datetime, timezone

import respx
from httpx import Response

from app.models import Series, Work
from app.services.open_library import OLWork
from app.services.works import upsert_work_from_ol

# The same URL `tests/test_enrichment.py` mocks (tests/ is not a package, so
# it is repeated rather than imported).
GOOGLE_URL = "https://www.googleapis.com/books/v1/volumes"


async def _saga(db):
    books = []
    for key, title, year in [("OLA1W", "Golden Son", 2015), ("OLA0W", "Red Rising", 2014), ("OLA2W", "Morning Star", 2016)]:
        w = await upsert_work_from_ol(db, OLWork(
            key=key, title=title, author="Pierce Brown", first_publish_year=year,
            edition_count=1, isbn_13s=frozenset(), subjects=("franchise:Red Rising",)))
        w.enriched_at = datetime.now(timezone.utc)
        w.description = f"About {title}."
        books.append(w)
    await db.flush()
    # Created out of order so the page's sort is tested; returned in reading order.
    return sorted(books, key=lambda w: w.first_publish_year)


async def test_series_page_lists_books_in_publication_order(client, db_session):
    await _saga(db_session)
    resp = await client.get("/api/series/red-rising")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["kind"] == "series"
    assert body["name"] == "Red Rising"
    assert [w["title"] for w in body["works"]] == ["Red Rising", "Golden Son", "Morning Star"]
    assert body["description"] == "About Red Rising."
    assert set(body["works"][0]) == {"id", "title", "author", "first_publish_year", "cover_url", "shelf_status"}


async def test_series_page_reports_the_callers_shelf(client, db_session, auth_headers):
    red, *_ = await _saga(db_session)
    await client.post(f"/api/works/{red.id}/shelf", json={"status": "reading"}, headers=auth_headers)
    body = (await client.get("/api/series/red-rising", headers=auth_headers)).json()
    shelves = {w["title"]: w["shelf_status"] for w in body["works"]}
    assert shelves == {"Red Rising": "reading", "Golden Son": None, "Morning Star": None}


async def test_singleton_page_uses_its_books_description(client, db_session, work):
    series = await db_session.get(Series, work.series_id)
    work.description = "Just the one."
    await db_session.flush()
    body = (await client.get(f"/api/series/{series.slug}")).json()
    assert body["kind"] == "singleton"
    assert [w["id"] for w in body["works"]] == [str(work.id)]
    assert body["description"] == "Just the one."


async def test_unknown_series_is_404(client):
    assert (await client.get("/api/series/nope")).status_code == 404


async def test_series_endpoint_answers_a_tombstoned_slug_with_the_survivor(client, db_session):
    w = await upsert_work_from_ol(db_session, OLWork(
        key="OLT1W", title="Dark Age", author="Pierce Brown", first_publish_year=2019,
        edition_count=1, isbn_13s=frozenset(), subjects=()))
    w.enriched_at = datetime.now(timezone.utc)
    old_slug = (await db_session.get(Series, w.series_id)).slug
    await upsert_work_from_ol(db_session, OLWork(
        key="OLT1W", title="Dark Age", author="Pierce Brown", first_publish_year=2019,
        edition_count=1, isbn_13s=frozenset(), subjects=("franchise:Red Rising",)))
    body = (await client.get(f"/api/series/{old_slug}")).json()
    assert body["slug"] == "red-rising"


@respx.mock
async def test_first_view_of_a_series_enriches_its_books(client, db_session):
    route = respx.get(GOOGLE_URL).mock(return_value=Response(200, json={"items": []}))
    await upsert_work_from_ol(db_session, OLWork(
        key="OLE1W", title="Fresh", author="New Author", first_publish_year=2020,
        edition_count=1, isbn_13s=frozenset(), subjects=()))
    series = (await db_session.execute(Series.__table__.select())).first()
    resp = await client.get(f"/api/series/{series.slug}")
    assert resp.status_code == 200
    assert route.called


async def test_series_threads_filter_by_book_tag(client, db_session, auth_headers):
    red, gold, _ = await _saga(db_session)
    for title, work_id in [("general", None), ("about golden son", gold.id), ("about red rising", red.id)]:
        payload = {"title": title}
        if work_id:
            payload["work_id"] = str(work_id)
        resp = await client.post("/api/series/red-rising/threads", json=payload, headers=auth_headers)
        assert resp.status_code == 201, resp.text

    everything = (await client.get("/api/series/red-rising/threads")).json()
    assert {t["title"] for t in everything} == {"general", "about golden son", "about red rising"}
    only_gold = (await client.get(f"/api/series/red-rising/threads?work_id={gold.id}")).json()
    assert [t["title"] for t in only_gold] == ["about golden son"]


async def test_create_series_thread_rejects_a_book_from_another_series(client, db_session, auth_headers, work):
    await _saga(db_session)
    resp = await client.post(
        "/api/series/red-rising/threads", json={"title": "wrong room", "work_id": str(work.id)},
        headers=auth_headers,
    )
    assert resp.status_code == 422


async def test_create_series_thread_canonicalizes_a_merged_book_id(client, db_session, auth_headers):
    from app.models import WorkKind, WorkProvenance, WorkSource
    red, *_ = await _saga(db_session)
    tomb = Work(source=WorkSource.heuristic, external_id="tomb", canonical_key="x", title="Red Rising",
                author="Pierce Brown", kind=WorkKind.single, identity_provenance=WorkProvenance.heuristic,
                merged_into_id=red.id, series_id=red.series_id)
    db_session.add(tomb)
    await db_session.flush()
    resp = await client.post(
        "/api/series/red-rising/threads", json={"title": "old id", "work_id": str(tomb.id)},
        headers=auth_headers,
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["work_id"] == str(red.id)
    assert resp.json()["series_id"] == str(red.series_id)


async def test_create_series_thread_requires_auth(client, db_session):
    await _saga(db_session)
    resp = await client.post("/api/series/red-rising/threads", json={"title": "anon"})
    assert resp.status_code in (401, 403)


async def test_series_threads_pagination_limits(client, db_session):
    await _saga(db_session)
    assert (await client.get("/api/series/red-rising/threads?limit=999")).status_code == 422
    assert (await client.get("/api/series/red-rising/threads?offset=-1")).status_code == 422


async def test_work_thread_listing_is_gone(client, work):
    assert (await client.get(f"/api/works/{work.id}/threads")).status_code == 404
