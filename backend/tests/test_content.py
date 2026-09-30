"""Editing and deleting threads and posts: author-only, tombstones, 409s."""

import uuid
from datetime import datetime, timezone

import pytest_asyncio

from app.models import Post, Series, Thread


async def _register(client, prefix="other"):
    unique = uuid.uuid4().hex[:8]
    resp = await client.post(
        "/api/auth/register",
        json={
            "email": f"{prefix}_{unique}@example.com",
            "username": f"{prefix}_{unique}",
            "password": "hunter2hunter2",
        },
    )
    assert resp.status_code == 201, resp.text
    return {"Authorization": f"Bearer {resp.json()['token']}"}


@pytest_asyncio.fixture
async def other_headers(client):
    return await _register(client)


@pytest_asyncio.fixture
async def thread_id(client, auth_headers, work):
    resp = await client.post(
        "/api/threads/",
        json={"title": "Is the ending earned?", "work_id": str(work.id), "content": "Opening."},
        headers=auth_headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _post(client, headers, thread_id, content, parent_id=None):
    resp = await client.post(
        "/api/posts/",
        json={"thread_id": thread_id, "content": content, "parent_id": parent_id},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _tombstone_post(db_session, post_id):
    post = await db_session.get(Post, uuid.UUID(post_id))
    post.content, post.deleted_at = "", datetime.now(timezone.utc)
    await db_session.commit()


async def _tombstone_thread(db_session, thread_id):
    thread = await db_session.get(Thread, uuid.UUID(thread_id))
    thread.title, thread.deleted_at = "", datetime.now(timezone.utc)
    await db_session.commit()


# --- reads -----------------------------------------------------------------


async def test_a_deleted_post_with_live_replies_is_a_tombstone(
    client, auth_headers, other_headers, thread_id, db_session
):
    parent = await _post(client, auth_headers, thread_id, "Parent.")
    await _post(client, other_headers, thread_id, "Reply.", parent_id=parent["id"])
    await _tombstone_post(db_session, parent["id"])

    posts = (await client.get(f"/api/threads/{thread_id}")).json()["posts"]
    node = next(p for p in posts if p["id"] == parent["id"])
    assert node["deleted"] is True
    assert node["content"] == ""
    assert node["author"] is None
    assert node["user_id"] is None
    assert [r["content"] for r in node["replies"]] == ["Reply."]


async def test_a_deleted_post_without_live_replies_is_omitted(
    client, auth_headers, other_headers, thread_id, db_session
):
    lone = await _post(client, auth_headers, thread_id, "Nobody answered.")
    parent = await _post(client, auth_headers, thread_id, "Parent.")
    reply = await _post(client, other_headers, thread_id, "Reply.", parent_id=parent["id"])
    await _tombstone_post(db_session, lone["id"])
    await _tombstone_post(db_session, reply["id"])
    await _tombstone_post(db_session, parent["id"])

    posts = (await client.get(f"/api/threads/{thread_id}")).json()["posts"]
    ids = {p["id"] for p in posts}
    assert lone["id"] not in ids
    # Its only reply is gone too, so nothing is left worth showing.
    assert parent["id"] not in ids


async def test_deleted_thread_page_still_serves_its_replies(
    client, other_headers, thread_id, db_session
):
    await _post(client, other_headers, thread_id, "Still worth reading.")
    await _tombstone_thread(db_session, thread_id)

    resp = await client.get(f"/api/threads/{thread_id}")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["deleted"] is True
    assert body["title"] == ""
    assert body["author"] is None
    assert body["user_id"] is None
    assert "Still worth reading." in [p["content"] for p in body["posts"]]


async def test_listings_skip_deleted_threads_and_count_live_posts(
    client, auth_headers, work, db_session
):
    kept = (await client.post(
        "/api/threads/", json={"title": "Kept", "work_id": str(work.id), "content": "One."},
        headers=auth_headers,
    )).json()
    gone = (await client.post(
        "/api/threads/", json={"title": "Gone", "work_id": str(work.id)}, headers=auth_headers,
    )).json()
    extra = await _post(client, auth_headers, kept["id"], "Two.")
    await _tombstone_post(db_session, extra["id"])
    await _tombstone_thread(db_session, gone["id"])

    slug = (await db_session.get(Series, work.series_id)).slug
    rows = (await client.get(f"/api/series/{slug}/threads")).json()
    assert [r["id"] for r in rows] == [kept["id"]]
    assert rows[0]["post_count"] == 1


async def test_a_live_post_carries_its_author_and_no_edit(client, auth_headers, thread_id):
    post = await _post(client, auth_headers, thread_id, "Fresh.")
    assert post["deleted"] is False
    assert post["edited_at"] is None
    assert post["user_id"] is not None
