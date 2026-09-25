import uuid

import respx
from httpx import Response
from sqlalchemy import select

from app.models import Book, Work, WorkKind, WorkProvenance, WorkSource
from app.services.enrichment import enrich_work

GOOGLE_URL = "https://www.googleapis.com/books/v1/volumes"

VOLUMES = {
    "items": [
        {
            "id": "g1",
            "volumeInfo": {
                "title": "Red Rising",
                "authors": ["Pierce Brown"],
                "description": "A boy from the mines.",
                "pageCount": 400,
                "imageLinks": {"thumbnail": "http://x/real?zoom=1"},
            },
        },
        {
            "id": "g2",
            "volumeInfo": {
                "title": "Red Rising",
                "authors": ["Pierce Brown"],
                "imageLinks": {"thumbnail": "http://x/fake?zoom=1"},
            },
        },
    ]
}


async def seed(db):
    work = Work(
        source=WorkSource.openlibrary,
        external_id=f"OL{uuid.uuid4().hex[:8]}W",
        canonical_key="red rising\x1fpierce brown",
        title="Red Rising",
        author="Pierce Brown",
        kind=WorkKind.single,
        identity_provenance=WorkProvenance.isbn,
    )
    db.add(work)
    await db.flush()
    return work


def mock_google_and_covers():
    """Mock Google and the cover HEADs, returning the Google route.

    The route is returned rather than re-registered by the caller: registering
    the same pattern twice replaces the route and resets its counter.
    """
    google = respx.get(GOOGLE_URL).mock(return_value=Response(200, json=VOLUMES))
    respx.head("https://x/real?zoom=0").mock(
        return_value=Response(200, headers={"content-type": "image/jpeg"})
    )
    respx.head("https://x/fake?zoom=0").mock(
        return_value=Response(
            200, headers={"content-type": "image/png", "content-length": "9103"}
        )
    )
    return google


@respx.mock
async def test_enrich_attaches_editions_to_the_work(db_session):
    mock_google_and_covers()
    work = await seed(db_session)
    await enrich_work(db_session, work)
    editions = (
        await db_session.execute(select(Book).where(Book.work_id == work.id))
    ).scalars().all()
    assert len(editions) == 2


@respx.mock
async def test_enrich_nulls_the_placeholder_cover(db_session):
    mock_google_and_covers()
    work = await seed(db_session)
    await enrich_work(db_session, work)
    covers = {
        b.external_id: b.cover_url
        for b in (
            await db_session.execute(select(Book).where(Book.work_id == work.id))
        ).scalars()
    }
    assert covers["g1"] == "https://x/real?zoom=0"
    assert covers["g2"] is None


@respx.mock
async def test_enrich_picks_a_representative_with_real_art(db_session):
    mock_google_and_covers()
    work = await seed(db_session)
    await enrich_work(db_session, work)
    await db_session.refresh(work)
    representative = await db_session.get(Book, work.representative_book_id)
    assert representative.external_id == "g1"


@respx.mock
async def test_enrich_sets_enriched_at(db_session):
    mock_google_and_covers()
    work = await seed(db_session)
    await enrich_work(db_session, work)
    assert work.enriched_at is not None


@respx.mock
async def test_enrich_is_a_no_op_once_enriched(db_session):
    route = mock_google_and_covers()
    work = await seed(db_session)
    await enrich_work(db_session, work)
    calls_after_first = route.call_count
    await enrich_work(db_session, work)
    assert route.call_count == calls_after_first


@respx.mock
async def test_enrich_survives_a_google_outage(db_session):
    respx.get(GOOGLE_URL).mock(return_value=Response(503))
    work = await seed(db_session)
    await enrich_work(db_session, work)
    # No enriched_at, so the next open retries rather than caching a failure.
    assert work.enriched_at is None


@respx.mock
async def test_get_work_triggers_enrichment(client, db_session):
    mock_google_and_covers()
    work = await seed(db_session)
    resp = await client.get(f"/api/works/{work.id}")
    assert resp.status_code == 200
    assert resp.json()["description"] == "A boy from the mines."
