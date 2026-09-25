import uuid

import respx
from httpx import Response

from app.models import Book, Work, WorkKind, WorkProvenance, WorkSource
from scripts.backfill_covers import backfill

OL_URL = "https://openlibrary.org/search.json"

DOC = {
    "key": "/works/OL17076473W",
    "title": "Red Rising",
    "author_name": ["Pierce Brown"],
    "edition_count": 26,
    "cover_i": 7316188,
    "readinglog_count": 1036,
    "ratings_count": 102,
    "subject": ["franchise:Red Rising"],
}


async def seed(db, **kw):
    work = Work(
        source=WorkSource.openlibrary,
        external_id="OL17076473W",
        canonical_key="red rising\x1fpierce brown",
        title="Red Rising",
        author="Pierce Brown",
        kind=WorkKind.single,
        identity_provenance=WorkProvenance.isbn,
        **kw,
    )
    db.add(work)
    await db.flush()
    return work


@respx.mock
async def test_backfill_populates_cover_and_popularity(db_session):
    respx.get(OL_URL).mock(return_value=Response(200, json={"docs": [DOC]}))
    work = await seed(db_session)
    summary = await backfill(db_session, commit=False)
    assert work.ol_cover_id == 7316188
    assert work.readinglog_count == 1036
    assert work.ol_edition_count == 26
    assert summary["works_updated"] == 1


@respx.mock
async def test_backfill_nulls_placeholder_covers(db_session):
    respx.get(OL_URL).mock(return_value=Response(200, json={"docs": [DOC]}))
    respx.head("https://x/fake").mock(
        return_value=Response(
            200, headers={"content-type": "image/png", "content-length": "9103"}
        )
    )
    work = await seed(db_session)
    edition = Book(
        source="google_books",
        external_id="g1",
        title="Red Rising",
        author="Pierce Brown",
        work_id=work.id,
        cover_url="https://x/fake",
    )
    db_session.add(edition)
    await db_session.flush()

    summary = await backfill(db_session, commit=False)
    assert edition.cover_url is None
    assert summary["covers_nulled"] == 1


@respx.mock
async def test_backfill_moves_the_representative_to_real_art(db_session):
    respx.get(OL_URL).mock(return_value=Response(200, json={"docs": [DOC]}))
    respx.head("https://x/fake").mock(
        return_value=Response(
            200, headers={"content-type": "image/png", "content-length": "9103"}
        )
    )
    respx.head("https://x/real").mock(
        return_value=Response(200, headers={"content-type": "image/jpeg"})
    )
    work = await seed(db_session)
    fake = Book(source="google_books", external_id="g1", title="Red Rising",
                author="Pierce Brown", work_id=work.id, cover_url="https://x/fake")
    real = Book(source="google_books", external_id="g2", title="Red Rising",
                author="Pierce Brown", work_id=work.id, cover_url="https://x/real")
    db_session.add_all([fake, real])
    await db_session.flush()
    work.representative_book_id = fake.id
    await db_session.flush()

    await backfill(db_session, commit=False)
    assert work.representative_book_id == real.id


@respx.mock
async def test_backfill_is_idempotent(db_session):
    respx.get(OL_URL).mock(return_value=Response(200, json={"docs": [DOC]}))
    work = await seed(db_session)
    await backfill(db_session, commit=False)
    second = await backfill(db_session, commit=False)
    assert work.ol_cover_id == 7316188
    assert second["covers_nulled"] == 0


@respx.mock
async def test_backfill_skips_heuristic_works(db_session):
    route = respx.get(OL_URL).mock(return_value=Response(200, json={"docs": [DOC]}))
    work = Work(
        source=WorkSource.heuristic,
        external_id=uuid.uuid4().hex,
        canonical_key="red rising saga\x1fpierce brown",
        title="Red Rising Saga",
        author="Pierce Brown",
        kind=WorkKind.single,
        identity_provenance=WorkProvenance.heuristic,
    )
    db_session.add(work)
    await db_session.flush()
    await backfill(db_session, commit=False)
    # Heuristic works keep their own upgrade path: resolve_works --upgrade.
    assert route.call_count == 0
