import uuid

import pytest
from sqlalchemy import update

from app.models import Series, SeriesMember, SeriesProvenance, Thread, Work
from app.services.librarian.errors import Conflict, Invalid
from app.services.librarian.identity import merge
from app.services.librarian.placement import (
    reject_series, remove_from_series, rename_series, set_position, set_series,
)
from app.services.librarian.undo import revert
from tests.librarian_factories import fresh, make_member, make_series, make_thread, make_user, make_work

R = "2026.10.1"


async def members_of(db, work):
    return {(m.series_id, m.position, m.provenance) for m in
            (await db.execute(SeriesMember.__table__.select().where(SeriesMember.work_id == work.id))).all()}


async def two_room_saga(db):
    lib = await make_user(db, librarian=True)
    a = await make_series(db, "Alpha", release=R)
    b = await make_series(db, "Beta", release=R)
    x = await make_work(db, "Book X", series=a, ol_id="OL1W")
    y = await make_work(db, "Book Y", series=a, ol_id="OL2W")
    await make_member(db, a, x, 1.0)
    await make_member(db, a, y, 2.0)
    return lib, a, b, x, y


async def test_undo_move_restores_room_membership_and_threads(db_session):
    lib, a, b, x, _ = await two_room_saga(db_session)
    tagged = await make_thread(db_session, lib, a, x)
    c = await set_series(db_session, lib, x, series=b, position=4, reason="r")

    undone = await revert(db_session, lib, c)

    assert undone.reverted_at is not None and undone.reverted_by_id == lib.id
    assert await fresh(db_session, Work.series_id, x.id) == a.id
    assert await fresh(db_session, Thread.series_id, tagged.id) == a.id
    assert await members_of(db_session, x) == {(a.id, 1.0, SeriesProvenance.ol_tag)}


async def test_undo_move_revives_a_retired_singleton(db_session):
    lib = await make_user(db_session, librarian=True)
    x = await make_work(db_session, "The Fifth Season")
    single = await db_session.get(Series, x.series_id)
    about_it = await make_thread(db_session, lib, single)
    c = await set_series(db_session, lib, x, new_series_name="The Broken Earth", reason="r")
    created = c.series_id

    await revert(db_session, lib, c)

    assert await fresh(db_session, Work.series_id, x.id) == single.id
    assert await fresh(db_session, Series.merged_into_id, single.id) is None
    assert await fresh(db_session, Thread.series_id, about_it.id) == single.id
    assert await fresh(db_session, Thread.work_id, about_it.id) is None  # untagged again
    assert await fresh(db_session, Series.merged_into_id, created) == single.id  # link still resolves


async def test_undo_refuses_stale_state(db_session):
    lib, a, b, x, _ = await two_room_saga(db_session)
    tagged = await make_thread(db_session, lib, a, x)
    c = await set_series(db_session, lib, x, series=b, reason="r")
    other = await make_series(db_session, "Gamma", release=R)
    await db_session.execute(update(Thread).where(Thread.id == tagged.id).values(series_id=other.id))
    with pytest.raises(Conflict, match="changed"):
        await revert(db_session, lib, c)


async def test_only_the_latest_fix_on_a_book_can_be_undone(db_session):
    lib, a, b, x, _ = await two_room_saga(db_session)
    move = await set_series(db_session, lib, x, series=b, reason="r")
    reorder = await set_position(db_session, lib, b, x, 3, reason="r")
    with pytest.raises(Conflict, match="later fix"):
        await revert(db_session, lib, move)
    await revert(db_session, lib, reorder)
    assert await members_of(db_session, x) == {(b.id, None, SeriesProvenance.override)}
    await revert(db_session, lib, move)
    with pytest.raises(Conflict, match="already undone"):
        await revert(db_session, lib, move)


async def test_merge_and_split_cannot_be_undone(db_session):
    lib = await make_user(db_session, librarian=True)
    a = await make_work(db_session, "A", ol_id="OL1W")
    b = await make_work(db_session, "B", ol_id="OL2W")
    c = await merge(db_session, lib, a, b, reason="r", confirm=True)
    with pytest.raises(Invalid, match="cannot be undone"):
        await revert(db_session, lib, c)


async def test_undo_rename_and_its_stale_check(db_session):
    lib = await make_user(db_session, librarian=True)
    saga = await make_series(db_session, "Old Name", release=R)
    c = await rename_series(db_session, lib, saga, "New Name", reason="r")
    await revert(db_session, lib, c)
    assert saga.name == "Old Name"

    c2 = await rename_series(db_session, lib, saga, "Newer", reason="r")
    saga.name = "Edited elsewhere"
    await db_session.flush()
    with pytest.raises(Conflict):
        await revert(db_session, lib, c2)


async def test_undo_remove_round_trip_tombstones_the_singleton(db_session):
    lib, a, _, x, _ = await two_room_saga(db_session)
    tagged = await make_thread(db_session, lib, a, x)
    c = await remove_from_series(db_session, lib, a, x, reason="r")
    single = c.snapshot["singleton"]

    await revert(db_session, lib, c)

    assert await fresh(db_session, Work.series_id, x.id) == a.id
    assert await fresh(db_session, Thread.series_id, tagged.id) == a.id
    assert await members_of(db_session, x) == {(a.id, 1.0, SeriesProvenance.ol_tag)}
    assert await fresh(db_session, Series.merged_into_id, uuid.UUID(single)) == a.id


async def test_undo_remove_refuses_when_the_singleton_gained_a_thread(db_session):
    lib, a, _, x, _ = await two_room_saga(db_session)
    c = await remove_from_series(db_session, lib, a, x, reason="r")
    own = await db_session.get(Series, await fresh(db_session, Work.series_id, x.id))
    await make_thread(db_session, lib, own)  # someone talks about it on its own page
    with pytest.raises(Conflict, match="own page"):
        await revert(db_session, lib, c)
    assert await fresh(db_session, Work.series_id, x.id) == own.id  # nothing moved


async def test_undo_reject_brings_every_book_back(db_session):
    lib, a, _, x, y = await two_room_saga(db_session)
    c = await reject_series(db_session, lib, a, reason="r")
    await revert(db_session, lib, c)
    assert a.dissolved_at is None
    for w, pos in ((x, 1.0), (y, 2.0)):
        assert await fresh(db_session, Work.series_id, w.id) == a.id
        assert await members_of(db_session, w) == {(a.id, pos, SeriesProvenance.ol_tag)}


async def test_a_series_name_reused_after_an_undo_is_a_live_series_again(db_session):
    from app.services.series_identity import release_series_id
    lib, a, _, x, y = await two_room_saga(db_session)
    first = await set_series(db_session, lib, x, new_series_name="Robots", reason="r")
    await revert(db_session, lib, first)
    robots = release_series_id("ol:robots")
    assert await fresh(db_session, Series.merged_into_id, robots) == a.id  # tombstoned by the undo

    again = await set_series(db_session, lib, y, new_series_name="Robots", reason="r")

    assert again.series_id == robots and await fresh(db_session, Work.series_id, y.id) == robots
    assert await fresh(db_session, Series.merged_into_id, robots) is None
    assert again.snapshot["created_series"] == str(robots)  # undo tombstones it again
    await revert(db_session, lib, again)
    assert await fresh(db_session, Work.series_id, y.id) == a.id


async def test_undo_move_refuses_when_the_new_room_gained_a_thread_about_the_book(db_session):
    lib, a, b, x, _ = await two_room_saga(db_session)
    c = await set_series(db_session, lib, x, series=b, reason="r")
    await make_thread(db_session, lib, b, x)  # a reader talks about it in its new room
    with pytest.raises(Conflict, match="since"):
        await revert(db_session, lib, c)
    assert await fresh(db_session, Work.series_id, x.id) == b.id
