import uuid

import pytest
from sqlalchemy import func, select

from app.models import Book, CorrectionOp, Series, SeriesKind, SeriesMember, Shelf, ShelfStatus, Thread, Work
from app.models import WorkProvenance, WorkSource
from app.services.librarian.errors import Conflict, Invalid, NeedsConfirmation, NotFound
from app.services.librarian.identity import merge, split
from tests.librarian_factories import (
    fresh, make_edition, make_member, make_series, make_thread, make_user, make_work,
)

R = "2026.10.1"


async def test_merge_asks_first_with_real_counts(db_session):
    lib = await make_user(db_session, librarian=True)
    source = await make_work(db_session, "Dune", ol_id="OL2W", author="Brian Herbert")
    target = await make_work(db_session, "Dune", ol_id="OL1W", author="Frank Herbert")
    await make_edition(db_session, source, ol_id="OL5M")
    await make_edition(db_session, source)
    await make_thread(db_session, lib, await db_session.get(Series, source.series_id))  # untagged, singleton
    await make_thread(db_session, lib, await db_session.get(Series, source.series_id), source)
    db_session.add(Shelf(user_id=lib.id, work_id=source.id, status=ShelfStatus.read))
    await db_session.flush()

    with pytest.raises(NeedsConfirmation) as asked:
        await merge(db_session, lib, source, target, reason="same book")
    assert asked.value.consequences == {"threads": 2, "shelves": 1, "editions": 2}
    assert await fresh(db_session, Work.merged_into_id, source.id) is None  # nothing happened

    c = await merge(db_session, lib, source, target, reason="same book", confirm=True)
    assert await fresh(db_session, Work.merged_into_id, source.id) == target.id
    assert c.op is CorrectionOp.merge_works and c.work_id == target.id and c.snapshot is None
    assert c.override == [{"merge_works": ["OL1W", "OL2W"]}]
    assert c.payload["consequences"] == {"threads": 2, "shelves": 1, "editions": 2}


async def test_merge_refusals(db_session):
    lib = await make_user(db_session, librarian=True)
    a = await make_work(db_session, "A", ol_id="OL1W")
    b = await make_work(db_session, "B", ol_id="OL2W")
    c = await make_work(db_session, "C", ol_id="OL3W")
    with pytest.raises(Invalid, match="itself"):
        await merge(db_session, lib, a, a, reason="r", confirm=True)
    await merge(db_session, lib, a, b, reason="r", confirm=True)
    with pytest.raises(Conflict, match="merged"):
        await merge(db_session, lib, a, c, reason="r", confirm=True)
    with pytest.raises(Conflict, match="merged"):
        await merge(db_session, lib, c, a, reason="r", confirm=True)


async def test_merge_of_a_heuristic_work_is_runtime_only(db_session):
    lib = await make_user(db_session, librarian=True)
    heuristic = await make_work(db_session, "Obscure")
    target = await make_work(db_session, "Obscure (OL)", ol_id="OL1W")
    c = await merge(db_session, lib, heuristic, target, reason="r", confirm=True)
    assert c.override is None and "no Open Library id" in c.runtime_only_reason


async def test_split_makes_an_open_library_work_named_by_the_pipeline(db_session):
    lib = await make_user(db_session, librarian=True)
    saga = await make_series(db_session, "Dune", release=R)
    work = await make_work(db_session, "Dune", series=saga, ol_id="OL100W", author="Frank Herbert")
    await make_member(db_session, saga, work, 1.0)
    keep = await make_edition(db_session, work, ol_id="OL1M", title="Dune")
    split_a = await make_edition(db_session, work, ol_id="OL7M", title="Dune: House Atreides")
    split_b = await make_edition(db_session, work, ol_id="OL3M", title="Dune: House Atreides (Deluxe Edition)")
    thread = await make_thread(db_session, lib, saga, work)

    with pytest.raises(NeedsConfirmation) as asked:
        await split(db_session, lib, work, [split_a.id, split_b.id], reason="prequel")
    assert asked.value.consequences == {"editions": 2, "remaining": 1}

    c = await split(db_session, lib, work, [split_a.id, split_b.id], reason="prequel", confirm=True)
    new = await db_session.get(Work, uuid.UUID(c.payload["new_work"]))
    assert (new.source, new.external_id) == (WorkSource.openlibrary, "OL100W~OL3M")
    assert new.identity_provenance is WorkProvenance.override
    assert new.series_id == saga.id and new.author == "Frank Herbert"
    assert await db_session.get(SeriesMember, (saga.id, new.id)) is not None
    assert {await fresh(db_session, Book.work_id, e.id) for e in (split_a, split_b)} == {new.id}
    assert await fresh(db_session, Book.work_id, keep.id) == work.id
    assert await fresh(db_session, Thread.work_id, thread.id) == work.id  # discussion stays
    assert await fresh(db_session, Work.representative_book_id, work.id) == keep.id
    assert await fresh(db_session, Work.representative_book_id, new.id) in {split_a.id, split_b.id}
    assert c.override == [{"split_work": {"work": "OL100W", "editions": ["OL3M", "OL7M"]}}]
    assert c.snapshot is None


async def test_splitting_out_of_a_singleton_gives_the_new_work_its_own_page(db_session):
    lib = await make_user(db_session, librarian=True)
    work = await make_work(db_session, "Collected Stories", ol_id="OL5W")
    await make_edition(db_session, work, ol_id="OL1M")
    other = await make_edition(db_session, work, ol_id="OL2M", title="Selected Stories")
    c = await split(db_session, lib, work, [other.id], reason="different book", confirm=True)
    new = await db_session.get(Work, uuid.UUID(c.payload["new_work"]))
    room = await db_session.get(Series, new.series_id)
    assert room.kind is SeriesKind.singleton and room.id != work.series_id
    assert (await db_session.execute(select(func.count()).select_from(SeriesMember)
                                     .where(SeriesMember.work_id == new.id))).scalar() == 0


async def test_split_refusals(db_session):
    lib = await make_user(db_session, librarian=True)
    work = await make_work(db_session, "Dune", ol_id="OL100W")
    only = await make_edition(db_session, work, ol_id="OL1M")
    stranger = await make_edition(db_session, await make_work(db_session, "Other", ol_id="OL200W"), ol_id="OL9M")
    with pytest.raises(Invalid, match="at least one"):
        await split(db_session, lib, work, [], reason="r", confirm=True)
    with pytest.raises(Invalid, match="every edition"):
        await split(db_session, lib, work, [only.id], reason="r", confirm=True)
    with pytest.raises(Invalid, match="not an edition"):
        await split(db_session, lib, work, [stranger.id], reason="r", confirm=True)
    with pytest.raises(NotFound):
        await split(db_session, lib, work, [uuid.uuid4()], reason="r", confirm=True)


async def test_a_heuristic_split_is_runtime_only_and_refuses_a_twin_key(db_session):
    lib = await make_user(db_session, librarian=True)
    work = await make_work(db_session, "Dune", ol_id="OL100W", author="Frank Herbert")
    await make_edition(db_session, work, ol_id="OL1M")
    google = await make_edition(db_session, work, title="Dune Messiah")
    c = await split(db_session, lib, work, [google.id], reason="sequel", confirm=True)
    assert c.override is None and "Google Books volume" in c.runtime_only_reason
    new = await db_session.get(Work, uuid.UUID(c.payload["new_work"]))
    assert new.source is WorkSource.heuristic and new.title == "Dune Messiah"

    twin = await make_edition(db_session, work, title="Dune (Deluxe Edition)")
    with pytest.raises(Invalid, match="merged straight back"):
        await split(db_session, lib, work, [twin.id], reason="r", confirm=True)
