"""Votes: table constraints, the set_vote service, and the vote endpoints."""

import uuid

import pytest
import pytest_asyncio
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


async def _thread(db_session, user: User, work) -> Thread:
    t = Thread(title="A thread", user_id=user.id, series_id=work.series_id, work_id=work.id)
    db_session.add(t)
    await db_session.flush()
    return t


async def test_thread_and_post_start_at_zero_score(db_session, work):
    user = await _user(db_session)
    thread = await _thread(db_session, user, work)
    post = Post(thread_id=thread.id, user_id=user.id, content="hi")
    db_session.add(post)
    await db_session.flush()

    assert thread.score == 0
    assert post.score == 0


async def test_one_vote_per_user_per_thread(db_session, work):
    user = await _user(db_session)
    thread = await _thread(db_session, user, work)
    db_session.add(Vote(user_id=user.id, thread_id=thread.id, value=1))
    await db_session.flush()

    db_session.add(Vote(user_id=user.id, thread_id=thread.id, value=-1))
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_vote_value_must_be_plus_or_minus_one(db_session, work):
    user = await _user(db_session)
    thread = await _thread(db_session, user, work)
    db_session.add(Vote(user_id=user.id, thread_id=thread.id, value=0))
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_vote_with_no_target_is_rejected(db_session):
    # The two exactly-one-target cases live in separate tests: recovering from
    # the first IntegrityError would need a rollback, which expires the
    # committed `work` fixture and makes the next `work.id` lazy-load outside
    # the greenlet.
    user = await _user(db_session)
    db_session.add(Vote(user_id=user.id, value=1))
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_vote_with_both_targets_is_rejected(db_session, work):
    user = await _user(db_session)
    thread = await _thread(db_session, user, work)
    post = Post(thread_id=thread.id, user_id=user.id, content="hi")
    db_session.add(post)
    await db_session.flush()

    db_session.add(Vote(user_id=user.id, thread_id=thread.id, post_id=post.id, value=1))
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_two_users_may_vote_the_same_thread(db_session, work):
    user_a = await _user(db_session)
    user_b = await _user(db_session)
    thread = await _thread(db_session, user_a, work)
    db_session.add(Vote(user_id=user_a.id, thread_id=thread.id, value=1))
    db_session.add(Vote(user_id=user_b.id, thread_id=thread.id, value=1))
    await db_session.flush()  # must not raise


async def test_set_vote_up_then_down_then_clear(db_session, work):
    user = await _user(db_session)
    thread = await _thread(db_session, user, work)

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


async def test_set_vote_is_idempotent(db_session, work):
    user = await _user(db_session)
    thread = await _thread(db_session, user, work)

    await set_vote(db_session, user_id=user.id, thread_id=thread.id, value=1)
    assert await set_vote(db_session, user_id=user.id, thread_id=thread.id, value=1) == 1

    rows = (
        await db_session.execute(
            select(Vote).where(Vote.user_id == user.id, Vote.thread_id == thread.id)
        )
    ).scalars().all()
    assert len(rows) == 1


async def test_set_vote_sums_across_users(db_session, work):
    user_a = await _user(db_session)
    user_b = await _user(db_session)
    thread = await _thread(db_session, user_a, work)

    await set_vote(db_session, user_id=user_a.id, thread_id=thread.id, value=1)
    assert await set_vote(db_session, user_id=user_b.id, thread_id=thread.id, value=1) == 2


async def test_set_vote_on_post(db_session, work):
    user = await _user(db_session)
    thread = await _thread(db_session, user, work)
    post = Post(thread_id=thread.id, user_id=user.id, content="hi")
    db_session.add(post)
    await db_session.flush()

    assert await set_vote(db_session, user_id=user.id, post_id=post.id, value=-1) == -1


async def test_set_vote_requires_exactly_one_target(db_session, work):
    user = await _user(db_session)
    thread = await _thread(db_session, user, work)
    with pytest.raises(ValueError):
        await set_vote(db_session, user_id=user.id, value=1)
    with pytest.raises(ValueError):
        await set_vote(
            db_session, user_id=user.id, thread_id=thread.id, post_id=thread.id, value=1
        )


async def test_deleting_a_thread_cascades_its_votes(db_session, work):
    user = await _user(db_session)
    thread = await _thread(db_session, user, work)
    await set_vote(db_session, user_id=user.id, thread_id=thread.id, value=1)

    await db_session.delete(thread)
    await db_session.flush()

    remaining = (await db_session.execute(select(Vote))).scalars().all()
    assert remaining == []


@pytest_asyncio.fixture
async def voted_thread_id(client, auth_headers, work):
    resp = await client.post(
        "/api/threads/",
        json={"title": "Votable", "work_id": str(work.id)},
        headers=auth_headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def test_thread_vote_down_and_toggle_off(client, auth_headers, voted_thread_id):
    down = await client.put(
        f"/api/threads/{voted_thread_id}/vote", json={"value": -1}, headers=auth_headers
    )
    assert down.json()["score"] == -1
    assert down.json()["my_vote"] == -1

    cleared = await client.put(
        f"/api/threads/{voted_thread_id}/vote", json={"value": 0}, headers=auth_headers
    )
    assert cleared.json()["score"] == 0
    assert cleared.json()["my_vote"] == 0


async def test_thread_vote_is_idempotent_over_http(client, auth_headers, voted_thread_id):
    await client.put(
        f"/api/threads/{voted_thread_id}/vote", json={"value": 1}, headers=auth_headers
    )
    again = await client.put(
        f"/api/threads/{voted_thread_id}/vote", json={"value": 1}, headers=auth_headers
    )
    assert again.json()["score"] == 1


async def test_thread_vote_rejects_out_of_range_value(client, auth_headers, voted_thread_id):
    resp = await client.put(
        f"/api/threads/{voted_thread_id}/vote", json={"value": 2}, headers=auth_headers
    )
    assert resp.status_code == 422


async def test_thread_vote_requires_auth(client, voted_thread_id):
    resp = await client.put(f"/api/threads/{voted_thread_id}/vote", json={"value": 1})
    assert resp.status_code in (401, 403)


async def test_thread_vote_unknown_id_is_404(client, auth_headers):
    resp = await client.put(
        f"/api/threads/{uuid.uuid4()}/vote", json={"value": 1}, headers=auth_headers
    )
    assert resp.status_code == 404


async def test_old_upvote_endpoint_is_gone(client, auth_headers, voted_thread_id):
    # No route matches that path any more, so Starlette 404s (405 would mean
    # the path still exists under another method).
    resp = await client.post(
        f"/api/threads/{voted_thread_id}/upvote", headers=auth_headers
    )
    assert resp.status_code == 404


@pytest_asyncio.fixture
async def voted_post_id(client, auth_headers, voted_thread_id):
    resp = await client.post(
        "/api/posts/",
        json={"thread_id": voted_thread_id, "content": "A take."},
        headers=auth_headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def test_post_vote_sets_score(client, auth_headers, voted_post_id):
    up = await client.put(
        f"/api/posts/{voted_post_id}/vote", json={"value": 1}, headers=auth_headers
    )
    assert up.status_code == 200, up.text
    assert up.json()["score"] == 1
    assert up.json()["my_vote"] == 1

    down = await client.put(
        f"/api/posts/{voted_post_id}/vote", json={"value": -1}, headers=auth_headers
    )
    assert down.json()["score"] == -1


async def test_post_vote_requires_auth(client, voted_post_id):
    resp = await client.put(f"/api/posts/{voted_post_id}/vote", json={"value": 1})
    assert resp.status_code in (401, 403)


async def test_post_vote_unknown_id_is_404(client, auth_headers):
    resp = await client.put(
        f"/api/posts/{uuid.uuid4()}/vote", json={"value": 1}, headers=auth_headers
    )
    assert resp.status_code == 404


async def test_thread_read_reports_my_vote(client, auth_headers, voted_thread_id):
    await client.put(
        f"/api/threads/{voted_thread_id}/vote", json={"value": 1}, headers=auth_headers
    )
    post = await client.post(
        "/api/posts/",
        json={"thread_id": voted_thread_id, "content": "Mine."},
        headers=auth_headers,
    )
    post_id = post.json()["id"]
    await client.put(
        f"/api/posts/{post_id}/vote", json={"value": -1}, headers=auth_headers
    )

    got = await client.get(f"/api/threads/{voted_thread_id}", headers=auth_headers)
    assert got.json()["my_vote"] == 1
    assert got.json()["posts"][0]["my_vote"] == -1


async def test_thread_read_my_vote_is_zero_when_anonymous(
    client, auth_headers, voted_thread_id
):
    await client.put(
        f"/api/threads/{voted_thread_id}/vote", json={"value": 1}, headers=auth_headers
    )
    await client.post(
        "/api/posts/",
        json={"thread_id": voted_thread_id, "content": "Mine."},
        headers=auth_headers,
    )

    got = await client.get(f"/api/threads/{voted_thread_id}")
    assert got.json()["score"] == 1
    assert got.json()["my_vote"] == 0
    assert got.json()["posts"][0]["my_vote"] == 0


async def test_work_thread_list_carries_my_vote_and_orders_by_score(
    client, auth_headers, work
):
    low = await client.post(
        "/api/threads/",
        json={"title": "Low", "work_id": str(work.id)},
        headers=auth_headers,
    )
    high = await client.post(
        "/api/threads/",
        json={"title": "High", "work_id": str(work.id)},
        headers=auth_headers,
    )
    await client.put(
        f"/api/threads/{high.json()['id']}/vote", json={"value": 1}, headers=auth_headers
    )
    await client.put(
        f"/api/threads/{low.json()['id']}/vote", json={"value": -1}, headers=auth_headers
    )

    listed = await client.get(f"/api/works/{work.id}/threads", headers=auth_headers)
    rows = listed.json()
    assert [r["title"] for r in rows] == ["High", "Low"]
    assert rows[0]["my_vote"] == 1
    assert rows[1]["my_vote"] == -1

    anon = await client.get(f"/api/works/{work.id}/threads")
    assert all(r["my_vote"] == 0 for r in anon.json())
