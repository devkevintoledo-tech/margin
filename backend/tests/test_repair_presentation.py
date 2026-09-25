"""The repair pass. No network: every fix is a decision about rows we hold."""

import uuid

from sqlalchemy import select

from app.models import Book, Work, WorkKind, WorkProvenance, WorkSource
from scripts.repair_presentation import repair


def make_work(**kw):
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


def make_edition(**kw):
    base = dict(
        source="google_books",
        external_id=uuid.uuid4().hex[:8],
        title="Red Rising",
        author="Pierce Brown",
    )
    base.update(kw)
    return Book(**base)


async def test_detaches_an_edition_that_is_a_different_book(db_session):
    work = make_work()
    db_session.add(work)
    await db_session.flush()
    true_edition = make_edition(language="en", work_id=work.id)
    iron_gold = make_edition(title="Iron Gold", language="en", work_id=work.id)
    db_session.add_all([true_edition, iron_gold])
    await db_session.flush()

    summary = await repair(db_session, commit=False)

    await db_session.refresh(iron_gold)
    await db_session.refresh(true_edition)
    assert iron_gold.work_id is None
    assert true_edition.work_id == work.id
    assert summary["editions_detached"] == 1


async def test_clears_a_description_inherited_from_a_detached_edition(db_session):
    work = make_work(description="From the world of the series.")
    db_session.add(work)
    await db_session.flush()
    sons_of_ares = make_edition(
        title="Pierce Brown's Red Rising: Sons of Ares",
        description="From the world of the series.",
        work_id=work.id,
    )
    db_session.add(sons_of_ares)
    await db_session.flush()

    summary = await repair(db_session, commit=False)

    await db_session.refresh(work)
    assert work.description is None
    assert summary["descriptions_cleared"] == 1


async def test_repicks_an_english_representative(db_session):
    work = make_work()
    db_session.add(work)
    await db_session.flush()
    heyne = make_edition(
        language="de",
        cover_url="https://x/de.jpg",
        description="Der fulminante Auftakt ...",
        isbn_13="9783453316355",
        page_count=560,
        ratings_count=900,
        work_id=work.id,
    )
    del_rey = make_edition(
        language="en", cover_url="https://x/en.jpg", work_id=work.id
    )
    db_session.add_all([heyne, del_rey])
    await db_session.flush()
    work.representative_book_id = heyne.id
    await db_session.flush()

    summary = await repair(db_session, commit=False)

    await db_session.refresh(work)
    assert work.representative_book_id == del_rey.id
    assert summary["representatives_changed"] == 1


async def test_nulls_a_representative_belonging_to_another_work(db_session):
    """Two works sharing one representative — seen live on the duplicate
    Red Rising rows, where a work with no editions of its own pointed at
    another work's German edition."""
    owner = make_work()
    squatter = make_work(external_id=f"OL{uuid.uuid4().hex[:8]}W")
    db_session.add_all([owner, squatter])
    await db_session.flush()
    edition = make_edition(language="de", work_id=owner.id)
    db_session.add(edition)
    await db_session.flush()
    owner.representative_book_id = edition.id
    squatter.representative_book_id = edition.id
    await db_session.flush()

    summary = await repair(db_session, commit=False)

    await db_session.refresh(squatter)
    assert squatter.representative_book_id is None
    assert summary["representatives_repointed"] == 1


async def test_is_idempotent(db_session):
    work = make_work()
    db_session.add(work)
    await db_session.flush()
    db_session.add_all(
        [
            make_edition(language="en", cover_url="https://x/en.jpg", work_id=work.id),
            make_edition(title="Iron Gold", work_id=work.id),
        ]
    )
    await db_session.flush()

    first = await repair(db_session, commit=False)
    second = await repair(db_session, commit=False)

    assert first["editions_detached"] == 1
    assert second == {
        "editions_detached": 0,
        "descriptions_cleared": 0,
        "representatives_repointed": 0,
        "representatives_changed": 0,
    }


async def test_leaves_a_work_with_no_editions_alone(db_session):
    work = make_work(ol_cover_id=7316188)
    db_session.add(work)
    await db_session.flush()

    summary = await repair(db_session, commit=False)

    await db_session.refresh(work)
    assert work.representative_book_id is None
    assert summary["representatives_changed"] == 0


async def test_detached_editions_are_not_deleted(db_session):
    """A detached volume is a real book we hold; a later search resolves it
    into its own work. Nothing here destroys a row."""
    work = make_work()
    db_session.add(work)
    await db_session.flush()
    iron_gold = make_edition(title="Iron Gold", work_id=work.id)
    db_session.add(iron_gold)
    await db_session.flush()

    await repair(db_session, commit=False)

    still_there = (
        await db_session.execute(
            select(Book).where(Book.external_id == iron_gold.external_id)
        )
    ).scalar_one_or_none()
    assert still_there is not None


async def test_keeps_an_edition_when_the_works_key_is_stale(db_session):
    """The live defect the dry run exposed: 24 works carry a `canonical_key`
    that disagrees with their own title, so comparing against the stored key
    alone detaches the work's own printings."""
    work = make_work(canonical_key="light bringer\x1fpierce brown")
    db_session.add(work)
    await db_session.flush()
    morning_star = make_edition(language="en", work_id=work.id)
    iron_gold = make_edition(title="Iron Gold", work_id=work.id)
    db_session.add_all([morning_star, iron_gold])
    await db_session.flush()

    summary = await repair(db_session, commit=False)

    await db_session.refresh(morning_star)
    await db_session.refresh(iron_gold)
    assert morning_star.work_id == work.id
    assert iron_gold.work_id is None
    assert summary["editions_detached"] == 1
