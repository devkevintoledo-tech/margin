"""Edge cases found in review: stale undo targets, concurrent fixes, rollback,
and inputs the schema used to let through."""

import asyncio

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.models import Series, SeriesMember, SeriesProvenance, User, Work
from app.services.librarian.errors import Conflict
from app.services.librarian.identity import merge
from app.services.librarian.placement import rename_series, set_position, set_series
from app.services.librarian.undo import revert
from tests.conftest import TEST_DB_URL
from tests.librarian_factories import (
    fresh, headers_for, make_member, make_series, make_user, make_work,
)

R = "2026.10.1"


async def saga(db):
    lib = await make_user(db, librarian=True)
    a = await make_series(db, "Alpha", release=R)
    x = await make_work(db, "Book X", series=a, ol_id="OL1W")
    y = await make_work(db, "Book Y", series=a, ol_id="OL2W")
    await make_member(db, a, x, 1.0)
    await make_member(db, a, y, 2.0)
    return lib, a, x, y


async def test_undo_reorder_of_a_merged_away_book_conflicts(client, db_session):
    lib, a, x, y = await saga(db_session)
    c = await set_position(db_session, lib, a, x, 5, reason="r")
    await merge(db_session, lib, x, y, reason="dup", confirm=True)
    with pytest.raises(Conflict):
        await revert(db_session, lib, c)
    rows = (await client.get(f"/api/librarian/corrections?work_id={x.id}", headers=headers_for(lib))).json()
    assert [r["undoable"] for r in rows] == [False]


async def test_undo_rename_of_a_retired_series_conflicts(db_session):
    lib = await make_user(db_session, librarian=True)
    old = await make_series(db_session, "Old", release=R)
    new = await make_series(db_session, "New", release=R)
    c = await rename_series(db_session, lib, old, "Older", reason="r")
    old.merged_into_id = new.id
    await db_session.flush()
    with pytest.raises(Conflict):
        await revert(db_session, lib, c)


async def test_undo_conflicts_when_a_release_restored_the_membership_meanwhile(db_session):
    lib, a, x, _ = await saga(db_session)
    b = await make_series(db_session, "Beta", release=R)
    c = await set_series(db_session, lib, x, series=b, reason="r")
    await make_member(db_session, a, x, 9.0)  # a release load re-added it
    with pytest.raises(Conflict):
        await revert(db_session, lib, c)


async def test_nan_and_overlong_inputs_are_422(client, db_session):
    lib, a, x, _ = await saga(db_session)
    h = {**headers_for(lib), "content-type": "application/json"}
    nan = await client.post(f"/api/librarian/series/{a.id}/position", headers=h,
                            content=f'{{"work_id": "{x.id}", "position": NaN, "reason": "r"}}')
    assert nan.status_code == 422, nan.text
    long = await client.post(f"/api/librarian/series/{a.id}/rename", headers=headers_for(lib),
                             json={"name": "n" * 501, "reason": "r"})
    assert long.status_code == 422, long.text


async def test_a_new_series_name_finds_the_runtime_series_already_called_that(db_session):
    lib = await make_user(db_session, librarian=True)
    runtime = await make_series(db_session, "Dune Saga")  # external_id franchise:dune saga
    x = await make_work(db_session, "Dune", ol_id="OL8W")
    c = await set_series(db_session, lib, x, new_series_name="dune saga", reason="r")
    assert c.series_id == runtime.id and c.snapshot["created_series"] is None


async def test_a_second_merge_of_the_same_book_waits_then_conflicts(db_session):
    """Two librarians merging one book at once: the second waits on the first's
    row lock, then sees the tombstone, instead of splitting its threads."""
    lib, _, x, y = await saga(db_session)
    other = await make_work(db_session, "Book Z", ol_id="OL3W")
    await db_session.commit()

    engine = create_async_engine(TEST_DB_URL, poolclass=NullPool)
    sessions = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with sessions() as first, sessions() as second:
            u1, u2 = await first.get(User, lib.id), await second.get(User, lib.id)
            await merge(first, u1, await first.get(Work, x.id), await first.get(Work, y.id),
                        reason="r", confirm=True)  # holds the lock until commit
            racing = asyncio.create_task(merge(second, u2, await second.get(Work, x.id),
                                               await second.get(Work, other.id), reason="r", confirm=True))
            await asyncio.sleep(0.3)
            assert not racing.done()  # blocked on the row lock
            await first.commit()
            with pytest.raises(Conflict, match="merged"):
                await racing
    finally:
        await engine.dispose()
    x_id, y_id = x.id, y.id
    db_session.expire_all()
    assert await fresh(db_session, Work.merged_into_id, x_id) == y_id


async def test_a_fix_that_fails_after_writing_leaves_nothing_behind(db_session, monkeypatch):
    """The real get_db (not the test session pin) rolls back a failed request."""
    from httpx import ASGITransport, AsyncClient

    import app.database as database
    import app.services.librarian.placement as placement
    from app.main import app

    lib, a, x, _ = await saga(db_session)
    b = await make_series(db_session, "Beta", release=R)
    await db_session.commit()

    async def explode(*args, **kwargs):
        raise Conflict("boom after the move was written")

    engine = create_async_engine(TEST_DB_URL, poolclass=NullPool)
    monkeypatch.setattr(database, "AsyncSessionLocal",
                        async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False))
    monkeypatch.setattr(placement, "record", explode)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.post(f"/api/librarian/works/{x.id}/move", headers=headers_for(lib),
                                 json={"series_id": str(b.id), "reason": "r"})
        assert resp.status_code == 409
    finally:
        await engine.dispose()
    x_id, a_id = x.id, a.id
    db_session.expire_all()
    assert await fresh(db_session, Work.series_id, x_id) == a_id
    assert await db_session.get(SeriesMember, (a_id, x_id)) is not None
