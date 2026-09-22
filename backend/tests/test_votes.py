"""Votes: table constraints, the set_vote service, and the vote endpoints."""

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.models import Post, Thread, User, Vote
from app.models.user import AuthProvider
from app.services.votes import set_vote


async def _user(db_session) -> User:
    u = User(
        email=f"{uuid.uuid4().hex[:8]}@example.com",
        username=f"u{uuid.uuid4().hex[:8]}",
        auth_provider=AuthProvider.email,
        password_hash="x",
    )
    db_session.add(u)
    await db_session.flush()
    return u


async def _thread(db_session, user: User, book) -> Thread:
    t = Thread(title="A thread", user_id=user.id, book_id=book.id)
    db_session.add(t)
    await db_session.flush()
    return t


async def test_thread_and_post_start_at_zero_score(db_session, book):
    user = await _user(db_session)
    thread = await _thread(db_session, user, book)
    post = Post(thread_id=thread.id, user_id=user.id, content="hi")
    db_session.add(post)
    await db_session.flush()

    assert thread.score == 0
    assert post.score == 0


async def test_one_vote_per_user_per_thread(db_session, book):
    user = await _user(db_session)
    thread = await _thread(db_session, user, book)
    db_session.add(Vote(user_id=user.id, thread_id=thread.id, value=1))
    await db_session.flush()

    db_session.add(Vote(user_id=user.id, thread_id=thread.id, value=-1))
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_vote_value_must_be_plus_or_minus_one(db_session, book):
    user = await _user(db_session)
    thread = await _thread(db_session, user, book)
    db_session.add(Vote(user_id=user.id, thread_id=thread.id, value=0))
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_vote_with_no_target_is_rejected(db_session):
    # The two exactly-one-target cases live in separate tests: recovering from
    # the first IntegrityError would need a rollback, which expires the
    # committed `book` fixture and makes the next `book.id` lazy-load outside
    # the greenlet.
    user = await _user(db_session)
    db_session.add(Vote(user_id=user.id, value=1))
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_vote_with_both_targets_is_rejected(db_session, book):
    user = await _user(db_session)
    thread = await _thread(db_session, user, book)
    post = Post(thread_id=thread.id, user_id=user.id, content="hi")
    db_session.add(post)
    await db_session.flush()

    db_session.add(Vote(user_id=user.id, thread_id=thread.id, post_id=post.id, value=1))
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_two_users_may_vote_the_same_thread(db_session, book):
    user_a = await _user(db_session)
    user_b = await _user(db_session)
    thread = await _thread(db_session, user_a, book)
    db_session.add(Vote(user_id=user_a.id, thread_id=thread.id, value=1))
    db_session.add(Vote(user_id=user_b.id, thread_id=thread.id, value=1))
    await db_session.flush()  # must not raise


async def test_set_vote_up_then_down_then_clear(db_session, book):
    user = await _user(db_session)
    thread = await _thread(db_session, user, book)

    assert await set_vote(db_session, user_id=user.id, thread_id=thread.id, value=1) == 1
    # Switching direction is a single delta of -2, not two writes.
    assert await set_vote(db_session, user_id=user.id, thread_id=thread.id, value=-1) == -1
    assert await set_vote(db_session, user_id=user.id, thread_id=thread.id, value=0) == 0

    rows = (
        await db_session.execute(
            select(Vote).where(Vote.user_id == user.id, Vote.thread_id == thread.id)
        )
    ).scalars().all()
    assert rows == []


async def test_set_vote_is_idempotent(db_session, book):
    user = await _user(db_session)
    thread = await _thread(db_session, user, book)

    await set_vote(db_session, user_id=user.id, thread_id=thread.id, value=1)
    assert await set_vote(db_session, user_id=user.id, thread_id=thread.id, value=1) == 1

    rows = (
        await db_session.execute(
            select(Vote).where(Vote.user_id == user.id, Vote.thread_id == thread.id)
        )
    ).scalars().all()
    assert len(rows) == 1


async def test_set_vote_sums_across_users(db_session, book):
    user_a = await _user(db_session)
    user_b = await _user(db_session)
    thread = await _thread(db_session, user_a, book)

    await set_vote(db_session, user_id=user_a.id, thread_id=thread.id, value=1)
    assert await set_vote(db_session, user_id=user_b.id, thread_id=thread.id, value=1) == 2


async def test_set_vote_on_post(db_session, book):
    user = await _user(db_session)
    thread = await _thread(db_session, user, book)
    post = Post(thread_id=thread.id, user_id=user.id, content="hi")
    db_session.add(post)
    await db_session.flush()

    assert await set_vote(db_session, user_id=user.id, post_id=post.id, value=-1) == -1


async def test_set_vote_requires_exactly_one_target(db_session, book):
    user = await _user(db_session)
    thread = await _thread(db_session, user, book)
    with pytest.raises(ValueError):
        await set_vote(db_session, user_id=user.id, value=1)
    with pytest.raises(ValueError):
        await set_vote(
            db_session, user_id=user.id, thread_id=thread.id, post_id=thread.id, value=1
        )


async def test_deleting_a_thread_cascades_its_votes(db_session, book):
    user = await _user(db_session)
    thread = await _thread(db_session, user, book)
    await set_vote(db_session, user_id=user.id, thread_id=thread.id, value=1)

    await db_session.delete(thread)
    await db_session.flush()

    remaining = (await db_session.execute(select(Vote))).scalars().all()
    assert remaining == []
