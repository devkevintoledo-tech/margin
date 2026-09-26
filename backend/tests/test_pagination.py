"""Pagination tests for work-threads, genre-works, and genre-threads endpoints."""
import uuid
import pytest

from app.models.genre import Genre
from app.models.thread import Thread
from app.models.user import User, AuthProvider

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def seed_user(db_session):
    u = User(
        email=f"p{uuid.uuid4().hex[:6]}@test.com",
        username=f"p{uuid.uuid4().hex[:6]}",
        password_hash="x",
        auth_provider=AuthProvider.email,
    )
    db_session.add(u)
    await db_session.flush()
    return u


async def _seed_work_threads(db_session, user, work, n: int):
    for i in range(n):
        t = Thread(title=f"Thread {i}", user_id=user.id, series_id=work.series_id, work_id=work.id)
        db_session.add(t)
    await db_session.flush()


async def _seed_genre_works(db_session, genre, n: int):
    from app.models import Work, WorkKind, WorkProvenance, WorkSource

    works = []
    for i in range(n):
        w = Work(
            source=WorkSource.openlibrary,
            external_id=f"OL{i}{uuid.uuid4().hex[:6]}W",
            canonical_key=f"book {i}\x1fauthor",
            title=f"Book {i}",
            author="Author",
            kind=WorkKind.single,
            identity_provenance=WorkProvenance.isbn,
            genre_id=genre.id,
        )
        db_session.add(w)
        works.append(w)
    await db_session.flush()
    return works


async def _seed_genre_threads(db_session, user, genre, n: int):
    for i in range(n):
        t = Thread(title=f"Genre Thread {i}", user_id=user.id, genre_id=genre.id)
        db_session.add(t)
    await db_session.flush()


async def test_work_threads_limit_and_offset(client, db_session, seed_user, work):
    await _seed_work_threads(db_session, seed_user, work, 3)

    page1 = await client.get(f"/api/works/{work.id}/threads?limit=2&offset=0")
    assert page1.status_code == 200
    assert len(page1.json()) == 2

    page2 = await client.get(f"/api/works/{work.id}/threads?limit=2&offset=2")
    assert page2.status_code == 200
    assert len(page2.json()) == 1


async def test_genre_works_limit_and_offset(client, db_session, genre):
    await _seed_genre_works(db_session, genre, 3)

    page1 = await client.get(f"/api/genres/{genre.slug}/works?limit=2&offset=0")
    assert page1.status_code == 200
    assert len(page1.json()) == 2

    page2 = await client.get(f"/api/genres/{genre.slug}/works?limit=2&offset=2")
    assert page2.status_code == 200
    assert len(page2.json()) == 1


async def test_genre_threads_limit_and_offset(client, db_session, seed_user, genre):
    await _seed_genre_threads(db_session, seed_user, genre, 3)

    page1 = await client.get(f"/api/genres/{genre.slug}/threads?limit=2&offset=0")
    assert page1.status_code == 200
    assert len(page1.json()) == 2

    page2 = await client.get(f"/api/genres/{genre.slug}/threads?limit=2&offset=2")
    assert page2.status_code == 200
    assert len(page2.json()) == 1


async def test_limit_constraints(client, db_session, seed_user, work, genre):
    # limit > 100 rejected on all three endpoints
    r1 = await client.get(f"/api/works/{work.id}/threads?limit=999")
    assert r1.status_code == 422

    r2 = await client.get(f"/api/genres/{genre.slug}/works?limit=999")
    assert r2.status_code == 422

    r3 = await client.get(f"/api/genres/{genre.slug}/threads?limit=999")
    assert r3.status_code == 422

    # negative offset rejected
    r4 = await client.get(f"/api/works/{work.id}/threads?offset=-1")
    assert r4.status_code == 422
