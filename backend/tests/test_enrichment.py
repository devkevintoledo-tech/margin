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


async def seed(db, **kw):
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
    work = Work(**base)
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


@respx.mock
async def test_enrich_refuses_a_different_book_from_the_same_author(db_session):
    """`intitle:"Red Rising" inauthor:"Pierce Brown"` returns Iron Gold and the
    Sons of Ares graphic novels. None of them is an edition of Red Rising."""
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
                            "description": "A boy from the mines.",
                        },
                    },
                    {
                        "id": "g9",
                        "volumeInfo": {
                            "title": "Iron Gold",
                            "authors": ["Pierce Brown"],
                            "description": "A decade after the fall.",
                        },
                    },
                    {
                        "id": "g10",
                        "volumeInfo": {
                            "title": "Pierce Brown's Red Rising: Sons of Ares",
                            "authors": ["Pierce Brown", "Rik Hoskin"],
                            "description": "From the world of the series.",
                        },
                    },
                ]
            },
        )
    )
    work = await seed(db_session)
    await enrich_work(db_session, work)

    attached = {
        b.external_id
        for b in (
            await db_session.execute(select(Book).where(Book.work_id == work.id))
        ).scalars()
    }
    assert attached == {"g1"}


@respx.mock
async def test_enrich_keeps_an_edition_whose_title_is_only_packaging(db_session):
    """"Red Rising (Deluxe Slipcase Edition)" and "Red Rising 01" are the same
    book; `clean_title` strips exactly that packaging."""
    respx.get(GOOGLE_URL).mock(
        return_value=Response(
            200,
            json={
                "items": [
                    {
                        "id": "g2",
                        "volumeInfo": {
                            "title": "Red Rising (Deluxe Slipcase Edition)",
                            "authors": ["Pierce Brown"],
                        },
                    },
                    {
                        "id": "g3",
                        "volumeInfo": {
                            "title": "Red Rising 01",
                            "authors": ["Pierce Brown"],
                        },
                    },
                ]
            },
        )
    )
    work = await seed(db_session)
    await enrich_work(db_session, work)

    attached = {
        b.external_id
        for b in (
            await db_session.execute(select(Book).where(Book.work_id == work.id))
        ).scalars()
    }
    assert attached == {"g2", "g3"}


@respx.mock
async def test_enrich_takes_its_description_only_from_its_own_editions(db_session):
    """The live symptom: the Red Rising work's stored blurb was the Sons of Ares
    graphic novel's, because the wrong edition was attached first."""
    respx.get(GOOGLE_URL).mock(
        return_value=Response(
            200,
            json={
                "items": [
                    {
                        "id": "g9",
                        "volumeInfo": {
                            "title": "Pierce Brown's Red Rising: Sons of Ares",
                            "authors": ["Pierce Brown"],
                            "description": "From the world of the series.",
                        },
                    },
                    {
                        "id": "g1",
                        "volumeInfo": {
                            "title": "Red Rising",
                            "authors": ["Pierce Brown"],
                            "description": "A boy from the mines.",
                        },
                    },
                ]
            },
        )
    )
    work = await seed(db_session)
    await enrich_work(db_session, work)
    assert work.description == "A boy from the mines."


@respx.mock
async def test_enrich_keeps_an_edition_when_the_works_key_is_stale(db_session):
    """A work whose stored `canonical_key` disagrees with its own title — 24
    such rows exist live, e.g. "Morning Star" holding "light bringer" — must
    still claim its own editions, while impostors are still refused."""
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
                            "description": "A boy from the mines.",
                        },
                    },
                    {
                        "id": "g9",
                        "volumeInfo": {
                            "title": "Iron Gold",
                            "authors": ["Pierce Brown"],
                        },
                    },
                ]
            },
        )
    )
    work = await seed(db_session, canonical_key="light bringer\x1fpierce brown")
    await enrich_work(db_session, work)

    attached = {
        b.external_id
        for b in (
            await db_session.execute(select(Book).where(Book.work_id == work.id))
        ).scalars()
    }
    assert attached == {"g1"}
