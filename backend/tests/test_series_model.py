"""Every work has a series; a thread lives in exactly one room."""

import uuid

import pytest
from sqlalchemy.exc import IntegrityError

from app.models import (
    AuthProvider,
    Series,
    SeriesKind,
    SeriesSource,
    Thread,
    User,
    Work,
    WorkKind,
    WorkProvenance,
    WorkSource,
)


def _work(title="Dune", **kw) -> Work:
    return Work(
        source=WorkSource.openlibrary,
        external_id=f"OL{uuid.uuid4().hex[:8]}W",
        canonical_key=f"{title.lower()}\x1fauthor",
        title=title,
        author="Author",
        kind=WorkKind.single,
        identity_provenance=WorkProvenance.isbn,
        **kw,
    )


async def _user(db):
    u = User(
        email=f"s{uuid.uuid4().hex[:6]}@x.com",
        username=f"s{uuid.uuid4().hex[:6]}",
        password_hash="x",
        auth_provider=AuthProvider.email,
    )
    db.add(u)
    await db.flush()
    return u


async def test_a_work_flushed_without_a_series_gets_its_own_singleton(db_session):
    work = _work("Dune")
    db_session.add(work)
    await db_session.flush()

    series = await db_session.get(Series, work.series_id)
    assert series.kind is SeriesKind.singleton
    assert series.source is SeriesSource.heuristic
    assert series.name == "Dune"
    assert series.external_id == f"singleton:{work.id}"
    assert series.slug.startswith("dune-")


async def test_two_singletons_with_the_same_title_get_distinct_slugs(db_session):
    a, b = _work("Dune"), _work("Dune")
    db_session.add_all([a, b])
    await db_session.flush()
    sa = await db_session.get(Series, a.series_id)
    sb = await db_session.get(Series, b.series_id)
    assert sa.slug != sb.slug


async def test_a_work_given_a_series_keeps_it(db_session):
    series = Series(
        source=SeriesSource.openlibrary,
        external_id="franchise:red rising",
        name="Red Rising",
        slug="red-rising",
        canonical_key="red rising",
        kind=SeriesKind.series,
    )
    db_session.add(series)
    await db_session.flush()
    work = _work("Golden Son", series_id=series.id)
    db_session.add(work)
    await db_session.flush()
    assert work.series_id == series.id
    assert (await db_session.get(Series, work.series_id)).kind is SeriesKind.series


async def test_a_thread_needs_exactly_one_home(db_session):
    user = await _user(db_session)
    db_session.add(Thread(title="Homeless", user_id=user.id))
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_a_book_tag_needs_a_series(db_session, genre):
    work = _work()
    db_session.add(work)
    await db_session.flush()
    user = await _user(db_session)
    db_session.add(Thread(title="Tag in a genre", user_id=user.id, genre_id=genre.id, work_id=work.id))
    with pytest.raises(IntegrityError):
        await db_session.flush()
