import pytest
from sqlalchemy import func, select

from app.models import CatalogCorrection, Series, Shelf, ShelfStatus, Work
from app.services.librarian import merge_preview
from app.services.librarian.errors import Conflict, Invalid, NeedsConfirmation
from app.services.librarian.identity import merge
from app.services.open_library import cover_url as ol_cover_url
from tests.librarian_factories import (
    fresh, headers_for, make_edition, make_member, make_series, make_thread, make_user, make_work,
)

R = "2026.10.1"


async def _duplicate_pair(db):
    """Brian Herbert's *Dune* (a singleton, two editions, threads, a shelf) and
    Frank Herbert's *Dune* (in a real series, no editions: ingested from search)."""
    lib = await make_user(db, librarian=True)
    source = await make_work(db, "Dune", ol_id="OL2W", author="Brian Herbert")
    best = await make_edition(db, source, ol_id="OL5M")
    await make_edition(db, source)
    best.cover_url, best.description = "https://books.example/dune-en.jpg", "Google's richer blurb."
    source.representative_book_id = best.id
    # Present on the row, but the ladder must prefer the representative edition.
    source.ol_cover_id, source.description = 111, "OL's short blurb."
    room = await db.get(Series, source.series_id)
    await make_thread(db, lib, room)  # untagged, in the singleton: about this book
    await make_thread(db, lib, room, source)
    db.add(Shelf(user_id=lib.id, work_id=source.id, status=ShelfStatus.read))

    saga = await make_series(db, "Dune Saga", release=R)
    target = await make_work(db, "Dune", ol_id="OL1W", author="Frank Herbert", series=saga)
    await make_member(db, saga, target, 1.0)
    target.first_publish_year, target.ol_cover_id, target.ol_edition_count = 1965, 8231856, 26
    target.description = "Set on the desert planet Arrakis."
    await make_thread(db, lib, saga, target)
    await db.flush()
    return lib, source, target, room, saga


async def test_sides_use_the_page_fallback_ladder_not_raw_columns(db_session):
    _, source, target, room, saga = await _duplicate_pair(db_session)
    out = await merge_preview(db_session, source, target)

    assert out.source.id == source.id and out.target.id == target.id
    # Representative edition first, even though the row has an OL cover and blurb.
    assert out.source.cover_url == "https://books.example/dune-en.jpg"
    assert out.source.description == "Google's richer blurb."
    assert out.source.edition_count == 2  # no OL total on this row, so the local count
    # No editions at all: OL's curated cover, the work's blurb, OL's total.
    assert out.target.cover_url == ol_cover_url(8231856)
    assert out.target.description == "Set on the desert planet Arrakis."
    assert out.target.edition_count == 26
    assert (out.target.author, out.target.first_publish_year) == ("Frank Herbert", 1965)


async def test_sides_name_their_page_and_count_what_is_about_them(db_session):
    _, source, target, room, saga = await _duplicate_pair(db_session)
    out = await merge_preview(db_session, source, target)

    # A singleton is the book's own page: a slug to link, no series name to show.
    assert (out.source.series_slug, out.source.series_name) == (room.slug, None)
    assert (out.target.series_slug, out.target.series_name) == (saga.slug, "Dune Saga")
    assert (out.source.thread_count, out.source.shelf_count) == (2, 1)
    assert (out.target.thread_count, out.target.shelf_count) == (1, 0)


async def test_preview_counts_are_the_confirmation_counts_and_nothing_changes(db_session):
    lib, source, target, *_ = await _duplicate_pair(db_session)
    out = await merge_preview(db_session, source, target)
    assert (out.threads, out.shelves, out.editions) == (2, 1, 2)

    with pytest.raises(NeedsConfirmation) as asked:
        await merge(db_session, lib, source, target, reason="same book")
    assert asked.value.consequences == {"threads": out.threads, "shelves": out.shelves, "editions": out.editions}
    assert await fresh(db_session, Work.merged_into_id, source.id) is None
    assert await db_session.scalar(select(func.count()).select_from(CatalogCorrection)) == 0


async def test_swapping_the_arguments_swaps_the_sides(db_session):
    _, source, target, *_ = await _duplicate_pair(db_session)
    out = await merge_preview(db_session, target, source)
    assert (out.source.id, out.target.id) == (target.id, source.id)
    # Frank Herbert's Dune moving: its one tagged thread, no shelves, no local editions.
    assert (out.threads, out.shelves, out.editions) == (1, 0, 0)


async def test_preview_refuses_what_merge_refuses(db_session):
    lib = await make_user(db_session, librarian=True)
    a = await make_work(db_session, "A", ol_id="OL1W")
    b = await make_work(db_session, "B", ol_id="OL2W")
    c = await make_work(db_session, "C", ol_id="OL3W")
    with pytest.raises(Invalid, match="itself"):
        await merge_preview(db_session, a, a)
    await merge(db_session, lib, a, b, reason="r", confirm=True)
    with pytest.raises(Conflict, match="merged"):
        await merge_preview(db_session, a, c)
    with pytest.raises(Conflict, match="merged"):
        await merge_preview(db_session, c, a)
