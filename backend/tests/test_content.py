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


# --- edit --------------------------------------------------------------------


async def test_author_edits_a_post(client, auth_headers, thread_id):
    post = await _post(client, auth_headers, thread_id, "Typo'd.")
    resp = await client.patch(
        f"/api/posts/{post['id']}", json={"content": "  Fixed.  "}, headers=auth_headers
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["content"] == "Fixed."
    assert body["edited_at"] is not None
    assert body["author"]


async def test_non_author_cannot_edit(client, auth_headers, other_headers, thread_id):
    post = await _post(client, auth_headers, thread_id, "Mine.")
    resp = await client.patch(
        f"/api/posts/{post['id']}", json={"content": "Yours now."}, headers=other_headers
    )
    assert resp.status_code == 403


async def test_anonymous_cannot_edit(client, auth_headers, thread_id):
    post = await _post(client, auth_headers, thread_id, "Mine.")
    resp = await client.patch(f"/api/posts/{post['id']}", json={"content": "x"})
    # HTTPBearer answers a missing header 403 on the pinned FastAPI, 401 on newer.
    assert resp.status_code in (401, 403)


async def test_edit_missing_post_is_404(client, auth_headers):
    resp = await client.patch(
        f"/api/posts/{uuid.uuid4()}", json={"content": "x"}, headers=auth_headers
    )
    assert resp.status_code == 404


async def test_edit_to_whitespace_is_422(client, auth_headers, thread_id):
    post = await _post(client, auth_headers, thread_id, "Mine.")
    resp = await client.patch(
        f"/api/posts/{post['id']}", json={"content": "   "}, headers=auth_headers
    )
    assert resp.status_code == 422


async def test_editing_a_deleted_post_is_409(client, auth_headers, thread_id):
    post = await _post(client, auth_headers, thread_id, "Mine.")
    assert (await client.delete(f"/api/posts/{post['id']}", headers=auth_headers)).status_code == 204
    resp = await client.patch(
        f"/api/posts/{post['id']}", json={"content": "Back."}, headers=auth_headers
    )
    assert resp.status_code == 409


async def test_voting_does_not_mark_a_post_edited(client, auth_headers, other_headers, thread_id):
    post = await _post(client, auth_headers, thread_id, "Upvote me.")
    resp = await client.put(f"/api/posts/{post['id']}/vote", json={"value": 1}, headers=other_headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["edited_at"] is None


# --- delete post ----------------------------------------------------------------


async def test_author_deletes_a_post_and_its_text_is_erased(
    client, auth_headers, other_headers, thread_id, db_session
):
    post = await _post(client, auth_headers, thread_id, "Regrettable.")
    await _post(client, other_headers, thread_id, "A reply.", parent_id=post["id"])

    resp = await client.delete(f"/api/posts/{post['id']}", headers=auth_headers)
    assert resp.status_code == 204

    row = await db_session.get(Post, uuid.UUID(post["id"]))
    await db_session.refresh(row)
    assert row.content == ""
    assert row.deleted_at is not None
    assert row.user_id is not None  # kept for moderation


async def test_deleting_a_post_twice_is_204(client, auth_headers, thread_id):
    post = await _post(client, auth_headers, thread_id, "Once.")
    assert (await client.delete(f"/api/posts/{post['id']}", headers=auth_headers)).status_code == 204
    assert (await client.delete(f"/api/posts/{post['id']}", headers=auth_headers)).status_code == 204


async def test_non_author_cannot_delete_a_post(client, auth_headers, other_headers, thread_id):
    post = await _post(client, auth_headers, thread_id, "Mine.")
    assert (await client.delete(f"/api/posts/{post['id']}", headers=other_headers)).status_code == 403


async def test_non_author_delete_of_deleted_post_is_403(
    client, auth_headers, other_headers, thread_id
):
    post = await _post(client, auth_headers, thread_id, "Mine.")
    await client.delete(f"/api/posts/{post['id']}", headers=auth_headers)
    assert (await client.delete(f"/api/posts/{post['id']}", headers=other_headers)).status_code == 403


async def test_anonymous_cannot_delete_a_post(client, auth_headers, thread_id):
    post = await _post(client, auth_headers, thread_id, "Mine.")
    assert (await client.delete(f"/api/posts/{post['id']}")).status_code in (401, 403)


async def test_delete_missing_post_is_404(client, auth_headers):
    assert (await client.delete(f"/api/posts/{uuid.uuid4()}", headers=auth_headers)).status_code == 404


# --- delete thread --------------------------------------------------------------


async def test_author_deletes_a_thread_and_its_opening_post(
    client, auth_headers, other_headers, thread_id
):
    await _post(client, other_headers, thread_id, "Someone else's take.")

    resp = await client.delete(f"/api/threads/{thread_id}", headers=auth_headers)
    assert resp.status_code == 204

    body = (await client.get(f"/api/threads/{thread_id}")).json()
    assert body["deleted"] is True
    contents = [p["content"] for p in body["posts"]]
    # The author's opener had no replies, so its tombstone is omitted;
    # the other reader's post survives untouched.
    assert contents == ["Someone else's take."]


async def test_thread_delete_leaves_an_opener_someone_else_wrote(
    client, auth_headers, other_headers, work
):
    bare = (await client.post(
        "/api/threads/", json={"title": "No body", "work_id": str(work.id)}, headers=auth_headers
    )).json()
    await _post(client, other_headers, bare["id"], "First word is mine.")

    assert (await client.delete(f"/api/threads/{bare['id']}", headers=auth_headers)).status_code == 204
    body = (await client.get(f"/api/threads/{bare['id']}")).json()
    assert [p["content"] for p in body["posts"]] == ["First word is mine."]


async def test_deleting_a_thread_twice_is_204(client, auth_headers, thread_id):
    assert (await client.delete(f"/api/threads/{thread_id}", headers=auth_headers)).status_code == 204
    assert (await client.delete(f"/api/threads/{thread_id}", headers=auth_headers)).status_code == 204


async def test_non_author_cannot_delete_a_thread(client, other_headers, thread_id):
    assert (await client.delete(f"/api/threads/{thread_id}", headers=other_headers)).status_code == 403


async def test_anonymous_cannot_delete_a_thread(client, thread_id):
    assert (await client.delete(f"/api/threads/{thread_id}")).status_code in (401, 403)


async def test_delete_missing_thread_is_404(client, auth_headers):
    assert (await client.delete(f"/api/threads/{uuid.uuid4()}", headers=auth_headers)).status_code == 404


# --- guards ------------------------------------------------------------------


async def test_replying_to_a_deleted_post_is_409(client, auth_headers, other_headers, thread_id):
    post = await _post(client, auth_headers, thread_id, "Soon gone.")
    await client.delete(f"/api/posts/{post['id']}", headers=auth_headers)
    resp = await client.post(
        "/api/posts/",
        json={"thread_id": thread_id, "content": "Too late.", "parent_id": post["id"]},
        headers=other_headers,
    )
    assert resp.status_code == 409


async def test_posting_in_a_deleted_thread_is_409(client, auth_headers, other_headers, thread_id):
    await client.delete(f"/api/threads/{thread_id}", headers=auth_headers)
    resp = await client.post(
        "/api/posts/", json={"thread_id": thread_id, "content": "Hello?"}, headers=other_headers
    )
    assert resp.status_code == 409


async def test_post_in_missing_thread_is_404(client, auth_headers):
    resp = await client.post(
        "/api/posts/", json={"thread_id": str(uuid.uuid4()), "content": "Anyone?"}, headers=auth_headers
    )
    assert resp.status_code == 404


async def test_voting_on_a_deleted_post_is_409(client, auth_headers, other_headers, thread_id):
    post = await _post(client, auth_headers, thread_id, "Soon gone.")
    await client.delete(f"/api/posts/{post['id']}", headers=auth_headers)
    resp = await client.put(f"/api/posts/{post['id']}/vote", json={"value": 1}, headers=other_headers)
    assert resp.status_code == 409


async def test_voting_on_a_deleted_thread_is_409(client, auth_headers, other_headers, thread_id):
    await client.delete(f"/api/threads/{thread_id}", headers=auth_headers)
    resp = await client.put(f"/api/threads/{thread_id}/vote", json={"value": 1}, headers=other_headers)
    assert resp.status_code == 409
