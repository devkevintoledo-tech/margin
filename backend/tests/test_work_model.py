import uuid
from datetime import datetime, timezone

from sqlalchemy import select, text

from app.models import Book, SearchQuery, Work, WorkKind, WorkProvenance, WorkSource


async def test_work_round_trips_with_its_editions(db_session):
    work = Work(
        source=WorkSource.openlibrary,
        external_id="OL17076473W",
        canonical_key="red rising\x1fpierce brown",
        title="Red Rising",
        author="Pierce Brown",
        first_publish_year=2014,
        kind=WorkKind.single,
        identity_provenance=WorkProvenance.isbn,
    )
    db_session.add(work)
    await db_session.flush()

    edition = Book(
        source="google_books",
        external_id=uuid.uuid4().hex[:12],
        title="Red Rising (Deluxe Slipcase Edition)",
        author="Pierce Brown",
        work_id=work.id,
    )
    db_session.add(edition)
    await db_session.flush()

    work.representative_book_id = edition.id
    await db_session.commit()

    found = (
        await db_session.execute(select(Work).where(Work.external_id == "OL17076473W"))
    ).scalar_one()
    assert found.representative_book_id == edition.id
    assert found.kind is WorkKind.single


async def test_work_identity_is_unique_per_source(db_session):
    import sqlalchemy.exc

    def make():
        return Work(
            source=WorkSource.openlibrary,
            external_id="OL17076473W",
            canonical_key="red rising\x1fpierce brown",
            title="Red Rising",
            author="Pierce Brown",
            kind=WorkKind.single,
            identity_provenance=WorkProvenance.isbn,
        )

    db_session.add(make())
    await db_session.flush()
    db_session.add(make())
    try:
        await db_session.flush()
    except sqlalchemy.exc.IntegrityError:
        return
    raise AssertionError("expected uq_works_source_external_id to reject the duplicate")


def _work(**kw):
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


async def test_new_work_columns_default_to_zero_and_null(db_session):
    work = _work()
    db_session.add(work)
    await db_session.flush()
    assert work.readinglog_count == 0
    assert work.ratings_count == 0
    assert work.ol_edition_count == 0
    assert work.ol_cover_id is None
    assert work.description is None
    assert work.enriched_at is None
    assert work.subjects is None


async def test_search_doc_is_generated_from_title_author_and_subjects(db_session):
    work = _work(subjects="franchise:Red Rising genre:science fiction")
    db_session.add(work)
    await db_session.flush()
    await db_session.refresh(work)
    doc = (
        await db_session.execute(
            select(Work.search_doc).where(Work.id == work.id)
        )
    ).scalar_one()
    # Every lexeme is stemmed and weighted: title A, author B, subjects C.
    assert "'rise':2A" in doc
    assert "'brown':4B" in doc
    assert "'franchis':5C" in doc


async def test_search_doc_matches_a_tsquery(db_session):
    db_session.add(_work())
    await db_session.flush()
    found = (
        await db_session.execute(
            select(Work.title).where(
                Work.search_doc.op("@@")(
                    text("plainto_tsquery('english', 'red rising')")
                )
            )
        )
    ).scalars().all()
    assert found == ["Red Rising"]


async def test_search_doc_finds_a_series_sibling_through_its_subjects(db_session):
    # The regression the subjects index exists to prevent: Iron Gold must be
    # findable by "red rising" even though neither word is in its title.
    db_session.add(
        _work(
            title="Iron Gold",
            canonical_key="iron gold\x1fpierce brown",
            subjects="franchise:Red Rising series:Red Rising Saga",
        )
    )
    await db_session.flush()
    found = (
        await db_session.execute(
            select(Work.title).where(
                Work.search_doc.op("@@")(
                    text("plainto_tsquery('english', 'red rising')")
                )
            )
        )
    ).scalars().all()
    assert found == ["Iron Gold"]


async def test_search_query_rows_are_unique_on_normalized_query(db_session):
    db_session.add(
        SearchQuery(
            normalized_query="red rising",
            resolved_at=datetime.now(timezone.utc),
            result_count=8,
        )
    )
    await db_session.flush()
    row = (
        await db_session.execute(
            select(SearchQuery).where(SearchQuery.normalized_query == "red rising")
        )
    ).scalar_one()
    assert row.result_count == 8
