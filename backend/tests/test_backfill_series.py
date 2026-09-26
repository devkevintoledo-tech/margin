"""backfill_series gives every existing work and thread a room, idempotently."""

import uuid

import respx
from httpx import Response
from sqlalchemy import select, text

from app.models import (
    AuthProvider, Series, SeriesKind, Thread, User, Work, WorkKind, WorkProvenance, WorkSource,
)
from scripts.backfill_series import backfill


async def _legacy(db, title, subjects=None, external_id=None):
    w = Work(source=WorkSource.openlibrary, external_id=external_id or f"OL{uuid.uuid4().hex[:6]}W",
             canonical_key=f"{title.lower()}\x1fa", title=title, author="A", kind=WorkKind.single,
             identity_provenance=WorkProvenance.isbn, subjects=subjects)
    db.add(w)
    await db.flush()
    return w


async def _strip_series(db):
    """Make the rows look like they predate the series table."""
    await db.execute(text("ALTER TABLE works ALTER COLUMN series_id DROP NOT NULL"))
    await db.execute(text("UPDATE works SET series_id = NULL"))
    await db.execute(text("ALTER TABLE threads DROP CONSTRAINT ck_threads_one_home"))
    await db.execute(text("ALTER TABLE threads DROP CONSTRAINT ck_threads_tag_needs_series"))
    await db.execute(text("UPDATE threads SET series_id = NULL"))
    await db.execute(text("DELETE FROM series"))
    db.expire_all()


@respx.mock
async def test_backfill_assigns_rooms_and_moves_threads(db_session):
    route = respx.get("https://openlibrary.org/works/OLRRW.json").mock(
        return_value=Response(200, json={"subjects": ["franchise:Red Rising", "Fiction"]})
    )
    # Legacy space-joined blob: unparseable until re-fetched.
    red = await _legacy(db_session, "Red Rising", "Fiction franchise:Red Rising", external_id="OLRRW")
    # Already one-per-line: must not be re-fetched (and has no mocked route).
    gold = await _legacy(db_session, "Golden Son", "franchise:Red Rising\nFiction")
    hobbit = await _legacy(db_session, "The Hobbit", None)
    user = User(email="b@x.com", username="bf", password_hash="x", auth_provider=AuthProvider.email)
    db_session.add(user)
    await db_session.flush()
    thread = Thread(title="Legacy", user_id=user.id, series_id=red.series_id, work_id=red.id)
    db_session.add(thread)
    await db_session.flush()
    # Capture ids now: _strip_series expires every object, and touching an
    # expired attribute outside the greenlet raises MissingGreenlet.
    ids = (red.id, gold.id, hobbit.id, thread.id)
    await _strip_series(db_session)

    stats = await backfill(db_session, commit=False)

    assert route.called
    assert stats["refetched"] == 1
    red, gold, hobbit = [await db_session.get(Work, i) for i in ids[:3]]
    thread = await db_session.get(Thread, ids[3])
    assert red.series_id == gold.series_id
    assert (await db_session.get(Series, red.series_id)).kind is SeriesKind.series
    assert (await db_session.get(Series, hobbit.series_id)).kind is SeriesKind.singleton
    assert thread.series_id == red.series_id and thread.work_id == red.id
    assert stats["threads"] == 1


@respx.mock
async def test_backfill_is_idempotent_and_reports_orphans(db_session):
    await _legacy(db_session, "Dune")
    user = User(email="o@x.com", username="orph", password_hash="x", auth_provider=AuthProvider.email)
    db_session.add(user)
    await db_session.flush()
    user_id = user.id  # read before _strip_series expires it
    await _strip_series(db_session)
    await db_session.execute(
        text("INSERT INTO threads (id, title, user_id) VALUES (gen_random_uuid(), 'orphan', :u)"),
        {"u": user_id},
    )

    first = await backfill(db_session, fetch=False, commit=False)
    second = await backfill(db_session, fetch=False, commit=False)

    assert first["orphans"] == second["orphans"] == 1
    assert second["threads"] == 0
    # The second run reuses the singleton rather than minting another.
    assert len((await db_session.execute(select(Series))).scalars().all()) == 1
