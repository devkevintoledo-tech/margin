import pytest

from app.models import CorrectionOp, Series, SeriesKind, SeriesMember, SeriesProvenance, Thread, Work
from app.services.librarian.errors import Conflict, Invalid
from app.services.librarian.placement import rename_series, set_position, set_series
from app.services.series_identity import release_series_id
from tests.librarian_factories import (
    fresh, make_member, make_series, make_thread, make_user, make_work,
)

R = "2026.10.1"


async def members_of(db, work):
    return {(m.series_id, m.position, m.provenance) for m in
            (await db.execute(SeriesMember.__table__.select().where(SeriesMember.work_id == work.id))).all()}


async def test_move_into_an_existing_series_carries_tagged_threads(db_session):
    lib = await make_user(db_session, librarian=True)
    a = await make_series(db_session, "Alpha", release=R)
    b = await make_series(db_session, "Beta", release=R)
    x = await make_work(db_session, "Book X", series=a, ol_id="OL1W")
    y = await make_work(db_session, "Book Y", series=a, ol_id="OL2W")
    await make_member(db_session, a, x, 1.0)
    await make_member(db_session, a, y, 2.0)
    tagged = await make_thread(db_session, lib, a, x)
    untagged = await make_thread(db_session, lib, a)

    c = await set_series(db_session, lib, x, series=b, position=2, reason="Beta, per the author")

    assert c.op is CorrectionOp.set_series and c.work_id == x.id and c.series_id == b.id
    assert await fresh(db_session, Work.series_id, x.id) == b.id
    assert await fresh(db_session, Thread.series_id, tagged.id) == b.id
    assert await fresh(db_session, Thread.series_id, untagged.id) == a.id
    assert await members_of(db_session, x) == {(b.id, 2.0, SeriesProvenance.override)}
    assert c.override == [
        {"remove_from_series": {"work": "OL1W", "series": "ol:alpha"}},
        {"set_series": {"work": "OL1W", "series": "ol:beta", "position": 2}},
    ]
    assert c.runtime_only_reason is None
    assert c.snapshot["moved_threads"] == [str(tagged.id)] and c.snapshot["retired"] is None


async def test_move_into_a_new_series_uses_the_release_id_and_retires_the_singleton(db_session):
    lib = await make_user(db_session, librarian=True)
    x = await make_work(db_session, "The Fifth Season")  # heuristic, in its own singleton
    old_room = x.series_id
    about_it = await make_thread(db_session, lib, await db_session.get(Series, old_room))

    c = await set_series(db_session, lib, x, new_series_name="The Broken Earth", reason="trilogy")

    target = await db_session.get(Series, release_series_id("ol:the broken earth"))
    assert target is not None and target.kind is SeriesKind.series
    assert target.provenance is SeriesProvenance.override and target.external_id == "ol:the broken earth"
    assert await fresh(db_session, Work.series_id, x.id) == target.id
    # The emptied singleton follows its book; its untagged thread was about that book.
    assert await fresh(db_session, Series.merged_into_id, old_room) == target.id
    assert await fresh(db_session, Thread.series_id, about_it.id) == target.id
    assert await fresh(db_session, Thread.work_id, about_it.id) == x.id
    assert c.snapshot["created_series"] == str(target.id)
    assert c.snapshot["retired"]["tagged"] == [str(about_it.id)]
    assert c.override is None and "no Open Library id" in c.runtime_only_reason

    y = await make_work(db_session, "The Obelisk Gate")
    again = await set_series(db_session, lib, y, new_series_name="the broken earth", reason="book two")
    assert again.series_id == target.id and again.snapshot["created_series"] is None


async def test_a_move_into_a_runtime_series_exports_with_its_name(db_session):
    lib = await make_user(db_session, librarian=True)
    runtime = await make_series(db_session, "Dune Saga")  # franchise:dune saga, no release
    x = await make_work(db_session, "Dune", ol_id="OL8W")
    c = await set_series(db_session, lib, x, series=runtime, reason="it is Dune")
    assert c.override == [{"set_series": {"work": "OL8W", "series": "ol:dune saga", "name": "Dune Saga"}}]


async def test_move_refuses_impossible_targets(db_session):
    lib = await make_user(db_session, librarian=True)
    a = await make_series(db_session, "Alpha", release=R)
    child = await make_series(db_session, "Alpha Child", release=R, parent=a)
    gone = await make_series(db_session, "Gone")
    from datetime import datetime, timezone
    gone.dissolved_at = datetime.now(timezone.utc)
    x = await make_work(db_session, "Book X", series=a, ol_id="OL1W")
    lonely = await make_work(db_session, "Lonely")
    single = await db_session.get(Series, lonely.series_id)
    with pytest.raises(Invalid, match="already in"):
        await set_series(db_session, lib, x, series=a, reason="r")
    with pytest.raises(Invalid, match="single book"):
        await set_series(db_session, lib, x, series=single, reason="r")
    with pytest.raises(Invalid, match="sub-series"):
        await set_series(db_session, lib, x, series=child, reason="r")
    with pytest.raises(Conflict, match="dissolved"):
        await set_series(db_session, lib, x, series=gone, reason="r")
    with pytest.raises(Invalid):
        await set_series(db_session, lib, x, series=gone, new_series_name="Both", reason="r")
    with pytest.raises(Invalid, match="reason"):
        await set_series(db_session, lib, x, new_series_name="Fine", reason="   ")


async def test_ops_on_a_merged_work_conflict(db_session):
    lib = await make_user(db_session, librarian=True)
    a = await make_series(db_session, "Alpha", release=R)
    x = await make_work(db_session, "Book X", series=a, ol_id="OL1W")
    y = await make_work(db_session, "Book Y", series=a, ol_id="OL2W")
    x.merged_into_id = y.id
    await db_session.flush()
    with pytest.raises(Conflict, match="merged"):
        await set_series(db_session, lib, x, new_series_name="Elsewhere", reason="r")
    with pytest.raises(Conflict, match="merged"):
        await set_position(db_session, lib, a, x, 1, reason="r")


async def test_set_position_edits_the_membership_the_page_shows(db_session):
    lib = await make_user(db_session, librarian=True)
    cosmere = await make_series(db_session, "Cosmere", release=R)
    mistborn = await make_series(db_session, "Mistborn", release=R, parent=cosmere)
    book = await make_work(db_session, "The Well of Ascension", series=cosmere, ol_id="OL3W")
    await make_member(db_session, cosmere, book, 7.0)
    await make_member(db_session, mistborn, book, 3.0)

    c = await set_position(db_session, lib, cosmere, book, 2.0, reason="book two")

    assert await members_of(db_session, book) == {
        (cosmere.id, 7.0, SeriesProvenance.ol_tag), (mistborn.id, 2.0, SeriesProvenance.override)}
    assert c.override == [{"set_series": {"work": "OL3W", "series": "ol:mistborn", "position": 2.0}}]
    assert c.snapshot == {"member_series": str(mistborn.id),
                          "prior": {"series_id": str(mistborn.id), "work_id": str(book.id), "position": 3.0,
                                    "provenance": "ol_tag", "confidence": "medium"}}


async def test_set_position_creates_a_membership_in_a_runtime_series(db_session):
    lib = await make_user(db_session, librarian=True)
    runtime = await make_series(db_session, "Dune Saga")
    book = await make_work(db_session, "Dune Messiah", series=runtime, ol_id="OL9W")
    c = await set_position(db_session, lib, runtime, book, 2, reason="second")
    assert await members_of(db_session, book) == {(runtime.id, 2.0, SeriesProvenance.override)}
    assert c.override == [{"set_series": {"work": "OL9W", "series": "ol:dune saga", "position": 2,
                                          "name": "Dune Saga"}}]
    assert c.snapshot["prior"] is None


async def test_set_position_refuses_a_non_member_and_a_singleton(db_session):
    lib = await make_user(db_session, librarian=True)
    a = await make_series(db_session, "Alpha", release=R)
    outsider = await make_work(db_session, "Outsider", ol_id="OL4W")
    with pytest.raises(Invalid, match="not in"):
        await set_position(db_session, lib, a, outsider, 1, reason="r")
    with pytest.raises(Invalid, match="single book"):
        await set_position(db_session, lib, await db_session.get(Series, outsider.series_id), outsider, 1, reason="r")


async def test_rename_keeps_the_slug_and_exports_only_release_series(db_session):
    lib = await make_user(db_session, librarian=True)
    saga = await make_series(db_session, "Song of Ice", release=R, key="wd:Q45875")
    slug = saga.slug
    c = await rename_series(db_session, lib, saga, "  A Song of Ice and Fire ", reason="full title")
    assert (saga.name, saga.slug) == ("A Song of Ice and Fire", slug)
    assert c.override == [{"rename_series": {"series": "wd:Q45875", "name": "A Song of Ice and Fire"}}]
    assert c.snapshot == {"old_name": "Song of Ice"} and c.work_id is None

    runtime = await make_series(db_session, "Dune Saga")
    c2 = await rename_series(db_session, lib, runtime, "Dune Chronicles", reason="usual name")
    assert c2.override is None and c2.runtime_only_reason == "Dune Saga is not in a catalog release"
    with pytest.raises(Invalid):
        await rename_series(db_session, lib, runtime, " ", reason="r")
    with pytest.raises(Invalid, match="already"):
        await rename_series(db_session, lib, runtime, "Dune Chronicles", reason="r")
