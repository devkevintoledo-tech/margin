import uuid

from sqlalchemy import select

from app.models import Book, Work, WorkKind, WorkProvenance, WorkSource


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
