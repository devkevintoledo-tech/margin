"""Posts: top-level post, one-level reply, and the 2-level nesting limit."""

import pytest_asyncio


@pytest_asyncio.fixture
async def thread_id(client, auth_headers, work):
    resp = await client.post(
        "/api/threads/",
        json={"title": "Discussion", "work_id": str(work.id)},
        headers=auth_headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def test_create_top_level_post(client, auth_headers, thread_id):
    resp = await client.post(
        "/api/posts/",
        json={"thread_id": thread_id, "content": "A top-level take."},
        headers=auth_headers,
    )
    assert resp.status_code == 201, resp.text
    post = resp.json()
    assert post["parent_id"] is None
    assert post["content"] == "A top-level take."


async def test_reply_to_top_level_post(client, auth_headers, thread_id):
    parent = await client.post(
        "/api/posts/",
        json={"thread_id": thread_id, "content": "Parent post."},
        headers=auth_headers,
    )
    parent_id = parent.json()["id"]

    reply = await client.post(
        "/api/posts/",
        json={"thread_id": thread_id, "content": "A reply.", "parent_id": parent_id},
        headers=auth_headers,
    )
    assert reply.status_code == 201, reply.text
    assert reply.json()["parent_id"] == parent_id


async def test_reply_to_reply_rejected(client, auth_headers, thread_id):
    parent = await client.post(
        "/api/posts/",
        json={"thread_id": thread_id, "content": "Parent."},
        headers=auth_headers,
    )
    reply = await client.post(
        "/api/posts/",
        json={"thread_id": thread_id, "content": "Reply.", "parent_id": parent.json()["id"]},
        headers=auth_headers,
    )
    reply_id = reply.json()["id"]

    # Replying to a reply must be rejected (UI enforces 2 levels; API enforces it too).
    nested = await client.post(
        "/api/posts/",
        json={"thread_id": thread_id, "content": "Too deep.", "parent_id": reply_id},
        headers=auth_headers,
    )
    assert nested.status_code == 400


async def test_thread_assembles_reply_tree(client, auth_headers, thread_id):
    parent = await client.post(
        "/api/posts/",
        json={"thread_id": thread_id, "content": "Root."},
        headers=auth_headers,
    )
    parent_id = parent.json()["id"]
    await client.post(
        "/api/posts/",
        json={"thread_id": thread_id, "content": "Child.", "parent_id": parent_id},
        headers=auth_headers,
    )

    got = await client.get(f"/api/threads/{thread_id}")
    posts = got.json()["posts"]
    assert len(posts) == 1
    assert len(posts[0]["replies"]) == 1
    assert posts[0]["replies"][0]["content"] == "Child."
