# Edit and delete threads & posts — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Authors can edit their own posts and delete their own posts and threads; deletions leave `[deleted]` tombstones that keep replies in place.

**Architecture:** Three nullable timestamp columns (`posts.edited_at`, `posts.deleted_at`, `threads.deleted_at`). A new pure-ish service `services/content.py` owns the author/idempotency rules and raises domain exceptions the thin routes map to HTTP codes. Tombstone masking lives in the two existing serializers (`post_out_from_orm`, `threads_service.thread_out`) so every route masks identically. The frontend adds three React Query mutations, a shared inline `ConfirmRemove` control, and owner-only actions in `Post.jsx` and `Thread.jsx`.

**Tech Stack:** FastAPI, async SQLAlchemy 2.0, Pydantic v2, Alembic, pytest + httpx; React 18, React Query, Zustand, Tailwind, Vitest + RTL, Playwright.

**Spec:** `docs/superpowers/specs/2026-09-30-edit-delete-content-design.md`

## Global Constraints

- Author-only: nobody but a post's/thread's author can edit or delete it — not librarians.
- Thread titles, rooms and book tags are never editable. Only post `content` is.
- No revision history, no undelete.
- On delete: `posts.content = ''` / `threads.title = ''`, set `deleted_at`, keep `user_id` in the row.
- A tombstone serializes with `deleted: true`, `content`/`title` `""`, `author: null`, `user_id: null`; score and tree position kept.
- `edited_at` is its own column; never use `posts.updated_at` for the edited marker (votes bump it).
- Status codes: `PATCH /api/posts/{id}` 200 · 401 · 403 · 404 · 409 deleted · 422 blank. `DELETE /api/posts/{id}` and `DELETE /api/threads/{id}` 204 (also when already deleted) · 401 · 403 · 404. Ownership is checked before the idempotency shortcut.
- Writes against deleted content are 409: reply to a deleted post, post in a deleted thread, vote on a deleted post or thread.
- Frontend: never `window.confirm()`; confirm is inline `rm post? [y] [n]` / `rm thread? [y] [n]`, focus lands on `n`, Escape cancels.
- Design system: no new tokens, glyphs, component classes, radii, shadows, font sizes or durations. Colors only via existing tokens (`ink-dim`, `danger`, `accent`, …). Thread-page deleted notice copy: `This thread was deleted and no longer accepts replies.`
- Never `model_validate` an ORM object whose schema has a relationship field — build schemas from scalar columns (MissingGreenlet).
- Backend tests run against `margin_test`: from `backend/`, `DATABASE_URL=postgresql+asyncpg://margin:margin@localhost:5432/margin_test pytest`.

## Review Focus

1. **A deleted thread that still has others' posts** — its page must load (200) with `[deleted]` title and readable replies, not 404 or crash on `thread.author` being null. (Task 2 test `test_deleted_thread_page_still_serves_its_replies`, Task 6 test.)
2. **A non-author hitting DELETE on something already deleted** — must be 403, never a 204 that leaks "this is gone". (Task 3 test `test_non_author_delete_of_deleted_post_is_403`.)
3. **Editing to whitespace only** (`"   "`) — must be 422, not a post with invisible content. (Task 3 test `test_edit_to_whitespace_is_422`.)
4. **Double-clicking `[y]`** — the second request hits an already-deleted row and must be a harmless 204, and the button disables while pending. (Task 3 idempotency test; Task 5 `disabled={pending}`.)
5. **A post in a thread that does not exist** — the new deleted-thread guard loads the thread; a missing one must be 404, not the current FK 500. (Task 4 test `test_post_in_missing_thread_is_404`.)

---

## File Structure

**Backend**
- Modify `backend/app/models/post.py` — `edited_at`, `deleted_at` columns.
- Modify `backend/app/models/thread.py` — `deleted_at` column.
- Create `backend/alembic/versions/a4b6c8d0e2f1_content_edit_delete.py` — adds the three columns.
- Create `backend/tests/migration_db.py` — `scratch_db` fixture + `alembic()` helper, moved out of `test_genre_migrations.py` so both migration tests share them.
- Modify `backend/tests/test_genre_migrations.py` — import from `migration_db`.
- Create `backend/tests/test_content_migration.py`.
- Modify `backend/app/schemas/thread.py` — `PostOut`/`ThreadOut` fields, `PostUpdate`, tombstone masking in `post_out_from_orm`.
- Modify `backend/app/services/threads.py` — masking in `thread_out`, listing excludes deleted threads and counts live posts.
- Modify `backend/app/api/threads.py` — `get_thread` masking + tree pruning; `DELETE /threads/{id}`; vote guard.
- Create `backend/app/services/content.py` — `edit_post`, `delete_post`, `delete_thread`, `NotAuthor`, `AlreadyDeleted`.
- Modify `backend/app/api/posts.py` — `PATCH`/`DELETE /posts/{id}`; create/vote guards.
- Create `backend/tests/test_content.py` — every backend rule.

**Frontend**
- Modify `frontend/src/api/threads.js` — `useEditPost`, `useDeletePost`, `useDeleteThread`.
- Create `frontend/src/components/ConfirmRemove.jsx` — the inline `rm <noun>? [y] [n]` control.
- Modify `frontend/src/components/Post.jsx` (+ `Post.test.jsx`).
- Modify `frontend/src/pages/Thread.jsx` (+ `Thread.test.jsx`).
- Create `frontend/e2e/edit-delete.spec.js`.

**Docs**
- Modify `ROADMAP.md`, `CLAUDE.md`, spec status line.

---

### Task 1: Schema — the three columns and their migration

**Files:**
- Modify: `backend/app/models/post.py`
- Modify: `backend/app/models/thread.py`
- Create: `backend/alembic/versions/a4b6c8d0e2f1_content_edit_delete.py`
- Create: `backend/tests/migration_db.py`
- Modify: `backend/tests/test_genre_migrations.py:1-43`
- Test: `backend/tests/test_content_migration.py`

**Interfaces:**
- Produces: `Post.edited_at: Mapped[datetime | None]`, `Post.deleted_at: Mapped[datetime | None]`, `Thread.deleted_at: Mapped[datetime | None]`. Alembic revision `a4b6c8d0e2f1`, down_revision `d8e3f5a7b9c2` (the current head).

- [x] **Step 1: Move the scratch-database helpers into a shared module**

Create `backend/tests/migration_db.py` containing, verbatim, the `_plain`, `scratch_db` fixture and `alembic` helper currently at the top of `backend/tests/test_genre_migrations.py` (lines 1–43), with `_plain` renamed `plain_url`:

```python
"""A throwaway database migrated by real Alembic, for migration tests (not create_all)."""

import os
import subprocess
import sys
import uuid
from pathlib import Path

import asyncpg
import pytest

BACKEND = Path(__file__).resolve().parents[1]


def plain_url(url: str) -> str:
    return url.replace("postgresql+asyncpg://", "postgresql://")


@pytest.fixture
async def scratch_db():
    base = os.environ["DATABASE_URL"].rsplit("/", 1)[0]
    name = f"margin_migrate_{uuid.uuid4().hex[:8]}"
    try:
        admin = await asyncpg.connect(plain_url(f"{base}/postgres"))
    except Exception as exc:  # pragma: no cover
        pytest.skip(f"cannot reach the postgres database: {exc}")
    try:
        await admin.execute(f'CREATE DATABASE "{name}"')
    except asyncpg.InsufficientPrivilegeError:  # pragma: no cover
        await admin.close()
        pytest.skip("role cannot CREATE DATABASE")
    try:
        yield f"{base}/{name}"
    finally:
        await admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
        await admin.close()


def alembic(url: str, *args: str) -> None:
    env = {**os.environ, "DATABASE_URL": url}
    done = subprocess.run([sys.executable, "-m", "alembic", *args], cwd=BACKEND, env=env,
                          capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
```

In `test_genre_migrations.py`, delete those definitions and replace them with:

```python
"""The genre migrations, run by Alembic against a scratch database (not create_all)."""

import asyncpg

from migration_db import alembic, plain_url as _plain, scratch_db  # noqa: F401  (fixture)
```

(keep any other imports the remaining tests use).

- [x] **Step 2: Confirm the move broke nothing**

Run: `DATABASE_URL=postgresql+asyncpg://margin:margin@localhost:5432/margin_test pytest tests/test_genre_migrations.py -v`
Expected: PASS (same count as before).

- [x] **Step 3: Write the failing migration test**

Create `backend/tests/test_content_migration.py`:

```python
"""The edit/delete columns, added and removed by real Alembic."""

import asyncpg

from migration_db import alembic, plain_url, scratch_db  # noqa: F401  (fixture)

COLUMNS = """
    SELECT table_name, column_name FROM information_schema.columns
    WHERE (table_name, column_name) IN (
        ('posts', 'edited_at'), ('posts', 'deleted_at'), ('threads', 'deleted_at'))
    ORDER BY 1, 2"""


async def test_content_columns_upgrade_and_downgrade(scratch_db):
    alembic(scratch_db, "upgrade", "head")
    conn = await asyncpg.connect(plain_url(scratch_db))
    try:
        rows = [tuple(r) for r in await conn.fetch(COLUMNS)]
        assert rows == [("posts", "deleted_at"), ("posts", "edited_at"), ("threads", "deleted_at")]
    finally:
        await conn.close()

    alembic(scratch_db, "downgrade", "d8e3f5a7b9c2")
    conn = await asyncpg.connect(plain_url(scratch_db))
    try:
        assert await conn.fetch(COLUMNS) == []
    finally:
        await conn.close()
```

- [x] **Step 4: Run it to verify it fails**

Run: `DATABASE_URL=postgresql+asyncpg://margin:margin@localhost:5432/margin_test pytest tests/test_content_migration.py -v`
Expected: FAIL — `rows == []` does not equal the three expected columns.

- [x] **Step 5: Add the model columns**

In `backend/app/models/post.py`, after `updated_at`:

```python
    # Its own column, not `updated_at`: votes change `score` with a Core
    # update, which fires `updated_at`'s onupdate — every voted post would
    # look edited.
    edited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # A deleted post is a tombstone: content erased, row and replies kept.
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
```

In `backend/app/models/thread.py`, after `created_at`:

```python
    # A deleted thread is a tombstone: title erased, other readers' posts kept.
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
```

- [x] **Step 6: Write the migration**

Create `backend/alembic/versions/a4b6c8d0e2f1_content_edit_delete.py`:

```python
"""edit and delete threads and posts: edited_at and deleted_at tombstones

Revision ID: a4b6c8d0e2f1
Revises: d8e3f5a7b9c2
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a4b6c8d0e2f1"
down_revision: Union[str, None] = "d8e3f5a7b9c2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("posts", sa.Column("edited_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("posts", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("threads", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("threads", "deleted_at")
    op.drop_column("posts", "deleted_at")
    op.drop_column("posts", "edited_at")
```

- [x] **Step 7: Run the migration test and the full suite**

Run: `DATABASE_URL=postgresql+asyncpg://margin:margin@localhost:5432/margin_test pytest -q`
Expected: all PASS, including `test_content_columns_upgrade_and_downgrade`.

- [x] **Step 8: Commit**

```bash
git add backend/app/models/post.py backend/app/models/thread.py \
  backend/alembic/versions/a4b6c8d0e2f1_content_edit_delete.py \
  backend/tests/migration_db.py backend/tests/test_genre_migrations.py backend/tests/test_content_migration.py
git commit -m "feat(content): edited_at and deleted_at columns for posts and threads"
```

---

### Task 2: Reads — tombstone masking, tree pruning, listings

**Files:**
- Modify: `backend/app/schemas/thread.py` (`ThreadOut`, `PostOut`, `post_out_from_orm`)
- Modify: `backend/app/services/threads.py` (`thread_summaries`, `thread_out`)
- Modify: `backend/app/api/threads.py` (`get_thread`)
- Test: `backend/tests/test_content.py`

**Interfaces:**
- Consumes: Task 1 columns.
- Produces:
  - `ThreadOut.user_id: UUID | None`, `ThreadOut.deleted: bool = False`.
  - `PostOut.user_id: UUID | None`, `PostOut.edited_at: datetime | None = None`, `PostOut.deleted: bool = False`.
  - `post_out_from_orm(post, my_vote=0, author=None) -> PostOut` masks a deleted post (content `""`, `user_id`/`author` `None`, `deleted=True`).
  - `threads_service.thread_out(thread, *, author, my_vote=0, score=None) -> ThreadOut` masks a deleted thread the same way (title `""`).
  - `get_thread` builds `ThreadWithPosts` from `thread_out(...)`; a deleted post with no live replies is omitted.

- [x] **Step 1: Write the failing tests**

Create `backend/tests/test_content.py`:

```python
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
```

- [x] **Step 2: Run to verify they fail**

Run: `DATABASE_URL=postgresql+asyncpg://margin:margin@localhost:5432/margin_test pytest tests/test_content.py -v`
Expected: FAIL — `KeyError: 'deleted'` / listing still returns the deleted thread.

- [x] **Step 3: Update the schemas and `post_out_from_orm`**

In `backend/app/schemas/thread.py`:

`ThreadOut` — change `user_id: UUID` to `user_id: UUID | None` and add, after `author`:

```python
    # A deleted thread keeps its URL and its replies, but not its words or its
    # author: title is "" and user_id/author are null.
    deleted: bool = False
```

`PostOut` — change `user_id: UUID` to `user_id: UUID | None`, and add after `updated_at`:

```python
    # When the author last changed the content. Not `updated_at`, which votes bump.
    edited_at: datetime | None = None
    # A tombstone: content "", user_id/author null, replies and score kept.
    deleted: bool = False
```

Replace `post_out_from_orm`'s body:

```python
    deleted = post.deleted_at is not None
    return PostOut(
        id=post.id,
        thread_id=post.thread_id,
        user_id=None if deleted else post.user_id,
        parent_id=post.parent_id,
        content="" if deleted else post.content,
        score=post.score,
        my_vote=my_vote,
        created_at=post.created_at,
        updated_at=post.updated_at,
        edited_at=post.edited_at,
        author=None if deleted else author,
        deleted=deleted,
        replies=[],
    )
```

Add to its docstring: "A deleted post is masked here, so every route serializes tombstones the same way."

- [x] **Step 4: Mask in `thread_out` and filter the listing**

In `backend/app/services/threads.py`, `thread_out`:

```python
def thread_out(
    thread: Thread, *, author: str | None, my_vote: int = 0, score: int | None = None
) -> ThreadOut:
    """Build from scalar columns — model_validate would lazy-load relationships.

    A deleted thread is masked here, so every route serializes it the same way.
    """
    deleted = thread.deleted_at is not None
    return ThreadOut(
        id=thread.id,
        title="" if deleted else thread.title,
        user_id=None if deleted else thread.user_id,
        series_id=thread.series_id,
        work_id=thread.work_id,
        genre_id=thread.genre_id,
        score=thread.score if score is None else score,
        my_vote=my_vote,
        created_at=thread.created_at,
        author=None if deleted else author,
        deleted=deleted,
    )
```

In `thread_summaries`, change the post join and the where clause:

```python
        # Only live posts count; a tombstone is not a contribution.
        .outerjoin(Post, (Post.thread_id == Thread.id) & Post.deleted_at.is_(None))
        # A deleted thread keeps its URL but leaves every room listing.
        .where(Thread.deleted_at.is_(None), *conditions)
```

- [x] **Step 5: Build `get_thread` from the maskers and prune the tree**

In `backend/app/api/threads.py`, `get_thread`: replace the tree assembly and the `return ThreadWithPosts(...)` (from `nodes = {` to the end of the function) with:

```python
    nodes = {
        post.id: post_out_from_orm(
            post,
            my_vote=post_votes.get(post.id, 0),
            author=usernames.get(post.user_id),
        )
        for post in all_posts
    }
    roots: list[PostOut] = []
    for post in all_posts:
        node = nodes[post.id]
        parent = nodes.get(post.parent_id) if post.parent_id else None
        if parent is not None:
            parent.replies.append(node)
        else:
            roots.append(node)

    # A tombstone is only worth showing while it holds live replies up. Replies
    # cannot nest further (2 levels), so pruning each root's replies first is
    # enough.
    for root in roots:
        root.replies = [r for r in root.replies if not r.deleted]
    roots = [r for r in roots if not r.deleted or r.replies]

    base = threads_service.thread_out(
        thread, author=usernames.get(thread.user_id), my_vote=my_vote
    )
    return ThreadWithPosts(
        **base.model_dump(),
        posts=roots,
        work=work_ref,
        genre=genre_ref,
        series=series_ref,
    )
```

- [x] **Step 6: Run the new tests and the whole suite**

Run: `DATABASE_URL=postgresql+asyncpg://margin:margin@localhost:5432/margin_test pytest -q`
Expected: all PASS (including existing `test_threads.py`, `test_posts.py`, `test_votes.py`, `test_openapi.py`).

- [x] **Step 7: Commit**

```bash
git add backend/app/schemas/thread.py backend/app/services/threads.py backend/app/api/threads.py backend/tests/test_content.py
git commit -m "feat(content): tombstones mask author and text; listings skip deleted threads"
```

---

### Task 3: Writes — edit and delete endpoints

**Files:**
- Create: `backend/app/services/content.py`
- Modify: `backend/app/schemas/thread.py` (add `PostUpdate`)
- Modify: `backend/app/api/posts.py` (`PATCH`, `DELETE /posts/{id}`)
- Modify: `backend/app/api/threads.py` (`DELETE /threads/{id}`)
- Test: `backend/tests/test_content.py`

**Interfaces:**
- Consumes: Task 2 masking (`post_out_from_orm`).
- Produces:
  - `app.services.content.NotAuthor(Exception)`, `app.services.content.AlreadyDeleted(Exception)`.
  - `async def edit_post(db: AsyncSession, post: Post, user: User, content: str) -> Post`
  - `async def delete_post(db: AsyncSession, post: Post, user: User) -> None`
  - `async def delete_thread(db: AsyncSession, thread: Thread, user: User) -> None`
  - `PostUpdate` schema: `content: str`, stripped, min length 1.
  - Routes `PATCH /api/posts/{id}` → `PostOut`; `DELETE /api/posts/{id}` → 204; `DELETE /api/threads/{id}` → 204.

- [x] **Step 1: Write the failing tests**

Append to `backend/tests/test_content.py`:

```python
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
    assert resp.status_code == 401


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
    assert (await client.delete(f"/api/posts/{post['id']}")).status_code == 401


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
    assert (await client.delete(f"/api/threads/{thread_id}")).status_code == 401


async def test_delete_missing_thread_is_404(client, auth_headers):
    assert (await client.delete(f"/api/threads/{uuid.uuid4()}", headers=auth_headers)).status_code == 404
```

- [x] **Step 2: Run to verify they fail**

Run: `DATABASE_URL=postgresql+asyncpg://margin:margin@localhost:5432/margin_test pytest tests/test_content.py -v`
Expected: the new tests FAIL — 405 for `DELETE /api/threads/{id}` (its path already has a GET), 404 for `PATCH`/`DELETE /api/posts/{id}` (no route at that path yet). Three pass already and are kept as guards: `test_voting_does_not_mark_a_post_edited` (Task 2 exposed `edited_at`), and `test_edit_missing_post_is_404` / `test_delete_missing_post_is_404` (404 either way until the routes exist).

- [x] **Step 3: Write the service**

Create `backend/app/services/content.py`:

```python
"""Editing and deleting readers' own threads and posts.

Author-only, with no FastAPI types: routes map `NotAuthor` to 403 and
`AlreadyDeleted` to 409. A deletion is a tombstone — the text is erased and
`deleted_at` set, but the row (and its `user_id`, for later moderation) stays,
so replies keep their place in the tree.
"""

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Post, Thread, User


class NotAuthor(Exception):
    """The caller did not write this."""


class AlreadyDeleted(Exception):
    """The target is a tombstone and cannot change."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _tombstone(post: Post, when: datetime) -> None:
    post.content = ""
    post.deleted_at = when


async def edit_post(db: AsyncSession, post: Post, user: User, content: str) -> Post:
    if post.user_id != user.id:
        raise NotAuthor
    if post.deleted_at is not None:
        raise AlreadyDeleted
    post.content = content
    post.edited_at = _now()
    await db.flush()
    await db.refresh(post)
    return post


async def delete_post(db: AsyncSession, post: Post, user: User) -> None:
    # Ownership first: a stranger learns nothing from an already-deleted post.
    if post.user_id != user.id:
        raise NotAuthor
    if post.deleted_at is not None:
        return
    _tombstone(post, _now())
    await db.flush()


async def delete_thread(db: AsyncSession, thread: Thread, user: User) -> None:
    if thread.user_id != user.id:
        raise NotAuthor
    if thread.deleted_at is not None:
        return
    when = _now()
    thread.title = ""
    thread.deleted_at = when
    # The opener is the earliest top-level post. There is no opener flag, so
    # it only goes with the thread when the thread's author wrote it.
    opener = (
        await db.execute(
            select(Post)
            .where(Post.thread_id == thread.id, Post.parent_id.is_(None))
            .order_by(Post.created_at)
            .limit(1)
        )
    ).scalar_one_or_none()
    if opener is not None and opener.user_id == user.id and opener.deleted_at is None:
        _tombstone(opener, when)
    await db.flush()
```

- [x] **Step 4: Add `PostUpdate`**

In `backend/app/schemas/thread.py`, after `PostCreate` (add `Annotated` from `typing` and `StringConstraints` from `pydantic` to the imports):

```python
class PostUpdate(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={"examples": [{"content": "The narrator is lying to himself, and to us."}]}
    )

    # Stripped before the length check, so whitespace-only content is a 422.
    content: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
```

- [x] **Step 5: Add the post routes**

In `backend/app/api/posts.py`, extend the imports:

```python
from fastapi import APIRouter, Depends, HTTPException, Response, status

from app.models.vote import Vote
from app.schemas.thread import PostCreate, PostOut, PostUpdate, VoteIn, post_out_from_orm
from app.services import content as content_service
```

Add a loader directly below `router = APIRouter(...)` (Task 4 reuses it in `vote_post`), and the two routes below `create_post`:

```python
async def _post_or_404(db: AsyncSession, id: UUID) -> Post:
    post = (await db.execute(select(Post).where(Post.id == id))).scalar_one_or_none()
    if post is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Post not found")
    return post


@router.patch("/{id}", response_model=PostOut)
async def edit_post(
    id: UUID,
    payload: PostUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PostOut:
    post = await _post_or_404(db, id)
    try:
        post = await content_service.edit_post(db, post, current_user, payload.content)
    except content_service.NotAuthor:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You can only edit your own posts.")
    except content_service.AlreadyDeleted:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This post was deleted.")
    my_vote = (
        await db.execute(
            select(Vote.value).where(Vote.post_id == id, Vote.user_id == current_user.id)
        )
    ).scalar_one_or_none() or 0
    return post_out_from_orm(post, my_vote=my_vote, author=current_user.username)


@router.delete("/{id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_post(
    id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Response:
    post = await _post_or_404(db, id)
    try:
        await content_service.delete_post(db, post, current_user)
    except content_service.NotAuthor:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You can only delete your own posts.")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
```

- [x] **Step 6: Add the thread route**

In `backend/app/api/threads.py`, add `Response` to the `fastapi` import and `from app.services import content as content_service`, then append:

```python
@router.delete("/{id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_thread(
    id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Response:
    thread = (await db.execute(select(Thread).where(Thread.id == id))).scalar_one_or_none()
    if thread is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Thread not found")
    try:
        await content_service.delete_thread(db, thread, current_user)
    except content_service.NotAuthor:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You can only delete your own threads.")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
```

- [x] **Step 7: Run the whole suite**

Run: `DATABASE_URL=postgresql+asyncpg://margin:margin@localhost:5432/margin_test pytest -q`
Expected: all PASS, including `test_openapi.py` (it requires `PostUpdate` to carry an example).

- [x] **Step 8: Commit**

```bash
git add backend/app/services/content.py backend/app/schemas/thread.py backend/app/api/posts.py backend/app/api/threads.py backend/tests/test_content.py
git commit -m "feat(content): authors edit posts and delete posts and threads"
```

---

### Task 4: Guards — no writes against deleted content

**Files:**
- Modify: `backend/app/api/posts.py` (`create_post`, `vote_post`)
- Modify: `backend/app/api/threads.py` (`vote_thread`)
- Test: `backend/tests/test_content.py`

**Interfaces:**
- Consumes: Task 3 routes (tests delete through the API).
- Produces: 409s for replying to a deleted post, posting in a deleted thread and voting on either; 404 for posting in a missing thread.

- [x] **Step 1: Write the failing tests**

Append to `backend/tests/test_content.py`:

```python
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
```

- [x] **Step 2: Run to verify they fail**

Run: `DATABASE_URL=postgresql+asyncpg://margin:margin@localhost:5432/margin_test pytest tests/test_content.py -k "409 or 404" -v`
Expected: the five new tests FAIL (201/200 returned; the missing-thread post errors with an IntegrityError/500).

- [x] **Step 3: Guard `create_post`**

In `backend/app/api/posts.py`, add `from app.models.thread import Thread` and put this at the top of `create_post`, before the parent check:

```python
    thread = await db.get(Thread, payload.thread_id)
    if thread is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Thread not found")
    if thread.deleted_at is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This thread was deleted and no longer accepts replies.",
        )
```

and inside the existing parent block, after the `parent is None` check:

```python
        if parent.deleted_at is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="That post was deleted and can't be replied to.",
            )
```

- [x] **Step 4: Guard the votes**

In `vote_post` (`backend/app/api/posts.py`), replace the lookup with the Task 3 loader and add the guard:

```python
    post = await _post_or_404(db, id)
    if post.deleted_at is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Deleted posts can't be voted on.")
```

In `vote_thread` (`backend/app/api/threads.py`), after the `thread is None` check:

```python
    if thread.deleted_at is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Deleted threads can't be voted on.")
```

- [x] **Step 5: Run the whole suite**

Run: `DATABASE_URL=postgresql+asyncpg://margin:margin@localhost:5432/margin_test pytest -q`
Expected: all PASS.

- [x] **Step 6: Commit**

```bash
git add backend/app/api/posts.py backend/app/api/threads.py backend/tests/test_content.py
git commit -m "feat(content): refuse replies and votes on deleted content"
```

---

### Task 5: Frontend — hooks, `ConfirmRemove`, and `Post.jsx`

**Files:**
- Modify: `frontend/src/api/threads.js`
- Create: `frontend/src/components/ConfirmRemove.jsx`
- Modify: `frontend/src/components/Post.jsx`
- Test: `frontend/src/components/Post.test.jsx`

**Interfaces:**
- Consumes: Tasks 2–4 API (`PATCH /posts/{id}` → `PostOut`; `DELETE /posts/{id}`, `DELETE /threads/{id}` → 204; `PostOut.deleted`, `.edited_at`, `.user_id`).
- Produces:
  - `useEditPost()` — `mutate({ id, content })`, invalidates `['threads', String(data.thread_id)]`.
  - `useDeletePost()` — `mutate({ id, threadId })`, invalidates `['threads', String(threadId)]`.
  - `useDeleteThread()` — `mutate({ id, seriesSlug, genreSlug })`, invalidates `['threads', String(id)]` and the room listing.
  - `<ConfirmRemove noun onConfirm onCancel pending />` — renders `rm {noun}? [y] [n]`; buttons named `yes, delete {noun}` and `no, keep it`.

- [x] **Step 1: Write the failing tests**

In `frontend/src/components/Post.test.jsx`, mock the client at the top (after the vitest import) and import it, plus `userEvent`:

```jsx
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

vi.mock('../api/client', () => ({
  default: { get: vi.fn(), put: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
}))

import client from '../api/client'
```

(`@testing-library/user-event` is already a dev dependency). Add `vi.clearAllMocks()` to `beforeEach`, and add `user_id: 'u1'` to the shared `post` fixture. Then append:

```jsx
describe('Post ownership', () => {
  const mine = {
    id: 'p1',
    user_id: 'u1',
    content: 'Le Guin never lets the reader settle.',
    score: 2,
    my_vote: 0,
    author: 'kevin',
    created_at: '2026-09-23T10:00:00Z',
    edited_at: null,
    deleted: false,
    replies: [],
  }

  function signIn(id = 'u1') {
    useAuthStore.setState({ user: { id, username: 'kevin' }, token: 't' })
  }

  it('shows edit and delete only to the author', () => {
    signIn('someone-else')
    const { unmount } = renderPost(mine)
    expect(screen.queryByRole('button', { name: 'edit' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'delete' })).not.toBeInTheDocument()
    unmount()

    signIn()
    renderPost(mine)
    expect(screen.getByRole('button', { name: 'edit' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'delete' })).toBeInTheDocument()
  })

  it('edits and saves the trimmed content', async () => {
    signIn()
    client.patch.mockResolvedValue({ data: { ...mine, content: 'Fixed.', thread_id: 't1' } })
    renderPost(mine)

    await userEvent.click(screen.getByRole('button', { name: 'edit' }))
    const box = screen.getByLabelText('Edit post')
    expect(box).toHaveValue(mine.content)
    await userEvent.clear(box)
    await userEvent.type(box, '  Fixed.  ')
    await userEvent.click(screen.getByRole('button', { name: 'save' }))

    expect(client.patch).toHaveBeenCalledWith('/posts/p1', { content: 'Fixed.' })
    await waitFor(() => expect(screen.queryByLabelText('Edit post')).not.toBeInTheDocument())
  })

  it('cancel restores the post without a request', async () => {
    signIn()
    renderPost(mine)
    await userEvent.click(screen.getByRole('button', { name: 'edit' }))
    await userEvent.click(screen.getByRole('button', { name: 'cancel' }))
    expect(screen.getByText(mine.content)).toBeInTheDocument()
    expect(client.patch).not.toHaveBeenCalled()
  })

  it('shows the server error when an edit fails', async () => {
    signIn()
    client.patch.mockRejectedValue({ response: { data: { detail: 'This post was deleted.' } } })
    renderPost(mine)
    await userEvent.click(screen.getByRole('button', { name: 'edit' }))
    await userEvent.click(screen.getByRole('button', { name: 'save' }))
    expect(await screen.findByText('This post was deleted.')).toBeInTheDocument()
  })

  it('blocks saving blank content', async () => {
    signIn()
    renderPost(mine)
    await userEvent.click(screen.getByRole('button', { name: 'edit' }))
    await userEvent.clear(screen.getByLabelText('Edit post'))
    expect(screen.getByRole('button', { name: 'save' })).toBeDisabled()
  })

  it('confirms inline, focusing "no" first', async () => {
    signIn()
    client.delete.mockResolvedValue({})
    renderPost(mine)

    await userEvent.click(screen.getByRole('button', { name: 'delete' }))
    expect(screen.getByText('rm post?')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'no, keep it' })).toHaveFocus()

    await userEvent.click(screen.getByRole('button', { name: 'yes, delete post' }))
    expect(client.delete).toHaveBeenCalledWith('/posts/p1')
  })

  it('Escape cancels the confirm', async () => {
    signIn()
    renderPost(mine)
    await userEvent.click(screen.getByRole('button', { name: 'delete' }))
    await userEvent.keyboard('{Escape}')
    expect(screen.queryByText('rm post?')).not.toBeInTheDocument()
    expect(client.delete).not.toHaveBeenCalled()
  })

  it('renders a tombstone with no author, no actions and a disabled vote', () => {
    signIn()
    renderPost({ ...mine, deleted: true, content: '', author: null, user_id: null })
    expect(screen.getAllByText('[deleted]')).toHaveLength(2)
    expect(screen.queryByText('kevin')).not.toBeInTheDocument()
    for (const name of ['edit', 'delete', 'reply']) {
      expect(screen.queryByRole('button', { name })).not.toBeInTheDocument()
    }
    screen.getAllByRole('button', { name: /vote/i }).forEach((b) => expect(b).toBeDisabled())
  })

  it('keeps the replies under a tombstone', () => {
    renderPost({
      ...mine,
      deleted: true, content: '', author: null, user_id: null,
      replies: [{ ...mine, id: 'p2', author: 'mara', user_id: 'u2', content: 'Still here.' }],
    })
    expect(screen.getByText('Still here.')).toBeInTheDocument()
  })

  it('marks an edited post', () => {
    renderPost({ ...mine, edited_at: '2026-09-23T11:00:00Z' })
    expect(screen.getByText('edited')).toBeInTheDocument()
  })
})
```

(`VoteControl`'s buttons are labelled `Upvote` and `Downvote`, which the `/vote/i` regex matches.)

- [x] **Step 2: Run to verify they fail**

Run (from `frontend/`): `npx vitest run src/components/Post.test.jsx`
Expected: the new `Post ownership` tests FAIL (no `edit` button, no `[deleted]`); the existing tests PASS.

- [x] **Step 3: Add the hooks**

Append to `frontend/src/api/threads.js`:

```js
export function useEditPost() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ id, content }) =>
      client.patch(`/posts/${id}`, { content }).then((r) => r.data),
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ['threads', String(data.thread_id)] })
    },
  })
}

export function useDeletePost() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ id }) => client.delete(`/posts/${id}`),
    onSuccess: (_, { threadId }) => {
      queryClient.invalidateQueries({ queryKey: ['threads', String(threadId)] })
    },
  })
}

export function useDeleteThread() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ id }) => client.delete(`/threads/${id}`),
    // The thread leaves its room's listing, so that list must refetch too.
    onSuccess: (_, { id, seriesSlug, genreSlug }) => {
      queryClient.invalidateQueries({ queryKey: ['threads', String(id)] })
      if (seriesSlug) queryClient.invalidateQueries({ queryKey: ['series', seriesSlug, 'threads'] })
      if (genreSlug) queryClient.invalidateQueries({ queryKey: ['genres', genreSlug, 'threads'] })
    },
  })
}
```

- [x] **Step 4: Create `ConfirmRemove`**

Create `frontend/src/components/ConfirmRemove.jsx`:

```jsx
import { useEffect, useRef } from 'react'

/**
 * Inline delete confirmation: `rm post? [y] [n]`. Never window.confirm() — a
 * browser dialog is modal chrome this UI does not have. Focus lands on "no" so
 * a stray Enter keeps the post; Escape backs out.
 */
function ConfirmRemove({ noun, onConfirm, onCancel, pending = false }) {
  const noRef = useRef(null)
  useEffect(() => {
    noRef.current?.focus()
  }, [])

  return (
    <span
      role="group"
      aria-label={`Confirm deleting this ${noun}`}
      className="inline-flex items-center gap-2 text-xs"
      onKeyDown={(e) => {
        if (e.key === 'Escape') onCancel()
      }}
    >
      <span className="text-ink-dim">rm {noun}?</span>
      <button
        type="button"
        onClick={onConfirm}
        disabled={pending}
        aria-label={`yes, delete ${noun}`}
        className="text-danger hover:underline disabled:opacity-50"
      >
        [y]
      </button>
      <button
        type="button"
        ref={noRef}
        onClick={onCancel}
        aria-label="no, keep it"
        className="text-ink-dim hover:text-accent transition-colors duration-fast"
      >
        [n]
      </button>
    </span>
  )
}

export default ConfirmRemove
```

- [x] **Step 5: Update `Post.jsx`**

Imports:

```jsx
import { useState } from 'react'
import { useDeletePost, useEditPost, useVotePost } from '../api/threads'
import { errorMessage } from '../api/errors'
import useAuthStore from '../store/auth'
import ConfirmRemove from './ConfirmRemove'
import PostComposer from './PostComposer'
import VoteControl from './VoteControl'
import DiagnosticFloat from './DiagnosticFloat'
```

Replace the top of the `Post` function (destructuring through `handleVote`) with:

```jsx
function Post({ post, threadId, depth = 0 }) {
  const {
    id, content, score = 0, my_vote = 0, author, created_at, edited_at, deleted = false,
    replies = [],
  } = post
  const [showReply, setShowReply] = useState(false)
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(content)
  const [confirming, setConfirming] = useState(false)
  const user = useAuthStore((s) => s.user)
  const voteMutation = useVotePost()
  const editMutation = useEditPost()
  const deleteMutation = useDeletePost()
  // Tombstones carry user_id null, so they never match.
  const isOwner = !!user && !deleted && user.id === post.user_id

  const handleVote = (value) => {
    if (user && !deleted) voteMutation.mutate({ id, value, threadId })
  }

  const startEdit = () => {
    setDraft(content)
    editMutation.reset()
    setEditing(true)
  }

  const saveEdit = (e) => {
    e.preventDefault()
    if (!draft.trim()) return
    editMutation.mutate({ id, content: draft.trim() }, { onSuccess: () => setEditing(false) })
  }
```

Pass `disabled={!user || deleted}` to `VoteControl`.

Replace the author/time row with:

```jsx
          <div className="flex items-center gap-2 mb-1.5 text-xs">
            {deleted ? (
              <span className="text-ink-dim">[deleted]</span>
            ) : (
              <span className="text-user font-medium">{author}</span>
            )}
            <span aria-hidden="true" className="text-ink-faint">·</span>
            <span className="text-ink-dim">
              <DiagnosticFloat
                severity="hint"
                message={absoluteTime(created_at)}
                source={`post/${id}`}
              >
                {relativeTime(created_at)}
              </DiagnosticFloat>
            </span>
            {edited_at && !deleted && (
              <>
                <span aria-hidden="true" className="text-ink-faint">·</span>
                <span className="text-ink-dim">
                  <DiagnosticFloat
                    severity="hint"
                    message={`edited ${absoluteTime(edited_at)}`}
                    source={`post/${id}`}
                  >
                    edited
                  </DiagnosticFloat>
                </span>
              </>
            )}
          </div>
```

Replace the content paragraph and the reply button with:

```jsx
          {deleted ? (
            <p className="text-ink-dim text-sm">[deleted]</p>
          ) : editing ? (
            <form onSubmit={saveEdit} className="flex flex-col gap-2 max-w-prose">
              <textarea
                aria-label="Edit post"
                className="input min-h-24"
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
              />
              {editMutation.isError && (
                <p className="alert-danger">{errorMessage(editMutation.error)}</p>
              )}
              <div className="flex gap-2">
                <button
                  type="submit"
                  className="btn-primary"
                  disabled={!draft.trim() || editMutation.isPending}
                >
                  save
                </button>
                <button type="button" className="btn-ghost" onClick={() => setEditing(false)}>
                  cancel
                </button>
              </div>
            </form>
          ) : (
            <p className="text-ink text-sm leading-relaxed whitespace-pre-wrap max-w-prose">
              {content}
            </p>
          )}

          {!deleted && !editing && (
            <div className="mt-2 flex items-center gap-3 text-xs">
              {confirming ? (
                <ConfirmRemove
                  noun="post"
                  pending={deleteMutation.isPending}
                  onCancel={() => setConfirming(false)}
                  onConfirm={() =>
                    deleteMutation.mutate(
                      { id, threadId },
                      { onSuccess: () => setConfirming(false) },
                    )
                  }
                />
              ) : (
                <>
                  {user && (
                    <button
                      onClick={() => setShowReply((v) => !v)}
                      className="text-ink-dim hover:text-accent transition-colors duration-fast"
                    >
                      {showReply ? 'cancel' : 'reply'}
                    </button>
                  )}
                  {isOwner && (
                    <>
                      <button
                        onClick={startEdit}
                        className="text-ink-dim hover:text-accent transition-colors duration-fast"
                      >
                        edit
                      </button>
                      <button
                        onClick={() => setConfirming(true)}
                        className="text-ink-dim hover:text-accent transition-colors duration-fast"
                      >
                        delete
                      </button>
                    </>
                  )}
                </>
              )}
            </div>
          )}
          {deleteMutation.isError && (
            <p className="alert-danger mt-2">{errorMessage(deleteMutation.error)}</p>
          )}
```

Keep the `showReply && <PostComposer …/>` block, and the replies list, unchanged.

Note: the reply button in the existing test uses name `reply`; the edit form's `cancel` and the reply toggle's `cancel` never render together (the action row is hidden while editing), so `getByRole('button', { name: 'cancel' })` stays unambiguous.

- [x] **Step 6: Run the frontend suite**

Run (from `frontend/`): `npm test`
Expected: all PASS.

- [x] **Step 7: Commit**

```bash
git add frontend/src/api/threads.js frontend/src/components/ConfirmRemove.jsx frontend/src/components/Post.jsx frontend/src/components/Post.test.jsx
git commit -m "feat(web): authors edit and delete their posts; tombstones keep replies"
```

---

### Task 6: Frontend — deleting a thread and the deleted thread page

**Files:**
- Modify: `frontend/src/pages/Thread.jsx`
- Test: `frontend/src/pages/Thread.test.jsx`

**Interfaces:**
- Consumes: `useDeleteThread()` and `<ConfirmRemove>` from Task 5; `ThreadOut.deleted`, `.user_id`.
- Produces: owner-only `delete thread` control; `[deleted]` thread rendering.

- [x] **Step 1: Write the failing tests**

In `frontend/src/pages/Thread.test.jsx`, extend the client mock to `{ get, put, post, patch: vi.fn(), delete: vi.fn() }`, add `user_id: 'u1'` and `deleted: false` to `THREAD`, import `userEvent`, and add a room route to `renderPage`'s `<Routes>`:

```jsx
          <Route path="/series/:slug" element={<p>room page</p>} />
```

Append:

```jsx
describe('Thread deletion', () => {
  it('lets the author delete the thread and returns to its room', async () => {
    useAuthStore.setState({ user: { id: 'u1', username: 'darrow' }, token: 't' })
    client.get.mockResolvedValue({ data: THREAD })
    client.delete.mockResolvedValue({})
    renderPage()

    await userEvent.click(await screen.findByRole('button', { name: 'delete thread' }))
    expect(screen.getByRole('button', { name: 'no, keep it' })).toHaveFocus()
    await userEvent.click(screen.getByRole('button', { name: 'yes, delete thread' }))

    expect(client.delete).toHaveBeenCalledWith('/threads/t1')
    expect(await screen.findByText('room page')).toBeInTheDocument()
  })

  it('offers no delete to other readers', async () => {
    useAuthStore.setState({ user: { id: 'u2', username: 'mustang' }, token: 't' })
    client.get.mockResolvedValue({ data: THREAD })
    renderPage()
    await screen.findByRole('heading', { name: 'Who is the real villain?' })
    expect(screen.queryByRole('button', { name: 'delete thread' })).not.toBeInTheDocument()
  })

  it('renders a deleted thread without author, composer or delete', async () => {
    useAuthStore.setState({ user: { id: 'u1', username: 'darrow' }, token: 't' })
    client.get.mockResolvedValue({
      data: { ...THREAD, deleted: true, title: '', author: null, user_id: null },
    })
    renderPage()

    expect(await screen.findByRole('heading', { name: '[deleted]' })).toBeInTheDocument()
    expect(screen.queryByText('darrow')).not.toBeInTheDocument()
    expect(
      screen.getByText('This thread was deleted and no longer accepts replies.'),
    ).toBeInTheDocument()
    expect(screen.queryByPlaceholderText('Join the discussion...')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'delete thread' })).not.toBeInTheDocument()
    // The remaining discussion stays readable.
    expect(screen.getByText('The Society, obviously.')).toBeInTheDocument()
  })

  it('does not count tombstones as posts', async () => {
    client.get.mockResolvedValue({
      data: {
        ...THREAD,
        posts: [{ ...THREAD.posts[0], deleted: true, content: '', author: null, user_id: null }],
      },
    })
    renderPage()
    expect(await screen.findByText('1 post')).toBeInTheDocument()
  })
})
```

- [x] **Step 2: Run to verify they fail**

Run (from `frontend/`): `npx vitest run src/pages/Thread.test.jsx`
Expected: the four new tests FAIL.

- [x] **Step 3: Implement**

In `frontend/src/pages/Thread.jsx`:

Imports:

```jsx
import { useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useDeleteThread, useThread } from '../api/threads'
import { errorMessage } from '../api/errors'
import useAuthStore from '../store/auth'
import ConfirmRemove from '../components/ConfirmRemove'
```

(keep the existing `Post`, `PostComposer`, `PathHeader`, `useStatusBar`, `slug` imports).

`countPosts` counts live posts only:

```jsx
function countPosts(posts) {
  return posts.reduce((n, p) => n + (p.deleted ? 0 : 1) + countPosts(p.replies || []), 0)
}
```

At the top of `Thread()` add, after `useThread`:

```jsx
  const navigate = useNavigate()
  const user = useAuthStore((s) => s.user)
  const deleteThread = useDeleteThread()
  const [confirming, setConfirming] = useState(false)
```

Status bar facts:

```jsx
    facts: [
      `${totalPosts} ${totalPosts === 1 ? 'post' : 'posts'}`,
      ...(thread?.deleted ? ['deleted'] : []),
    ],
```

After the error early-return, compute:

```jsx
  const title = thread.deleted ? '[deleted]' : thread.title
  const isOwner = !!user && !thread.deleted && user.id === thread.user_id
  const roomHref = thread.series
    ? `/series/${thread.series.slug}`
    : thread.genre
      ? `/genres/${thread.genre.slug}`
      : '/'

  const confirmDelete = () =>
    deleteThread.mutate(
      { id: resolvedId, seriesSlug: thread.series?.slug, genreSlug: thread.genre?.slug },
      // replace: Back must not land on the tombstone the reader just made.
      { onSuccess: () => navigate(roomHref, { replace: true }) },
    )
```

Use `title` for the last path segment (`segments.push({ label: title })`) and for the `<h1>`, whose class becomes
`` className={`text-xl md:text-2xl leading-snug font-medium max-w-prose ${thread.deleted ? 'text-ink-dim' : 'text-ink'}`} ``.

At the end of the header metadata row (after the posts count span) add:

```jsx
          {isOwner && (
            <>
              <span aria-hidden="true" className="text-ink-faint">·</span>
              {confirming ? (
                <ConfirmRemove
                  noun="thread"
                  pending={deleteThread.isPending}
                  onCancel={() => setConfirming(false)}
                  onConfirm={confirmDelete}
                />
              ) : (
                <button
                  onClick={() => setConfirming(true)}
                  className="text-ink-dim hover:text-accent transition-colors duration-fast"
                >
                  delete thread
                </button>
              )}
            </>
          )}
```

and below the metadata row, inside the header:

```jsx
        {deleteThread.isError && <p className="alert-danger">{errorMessage(deleteThread.error)}</p>}
```

Replace the bottom composer block with:

```jsx
      <div className="border-t border-line pt-5 flex flex-col gap-3">
        {thread.deleted ? (
          <p className="alert-muted">This thread was deleted and no longer accepts replies.</p>
        ) : (
          <>
            <h2 className="text-xs uppercase tracking-eyebrow text-ink-dim">Add a reply</h2>
            <PostComposer threadId={resolvedId} placeholder="Join the discussion..." />
          </>
        )}
      </div>
```

The author span is already guarded by `thread.author &&`, and a tombstone's author is null.

- [x] **Step 4: Run the frontend suite**

Run (from `frontend/`): `npm test`
Expected: all PASS.

- [x] **Step 5: Commit**

```bash
git add frontend/src/pages/Thread.jsx frontend/src/pages/Thread.test.jsx
git commit -m "feat(web): authors delete their threads; deleted threads stay readable"
```

---

### Task 7: E2E and docs

**Files:**
- Create: `frontend/e2e/edit-delete.spec.js`
- Modify: `ROADMAP.md:44`, `CLAUDE.md` (Known remaining gaps), `docs/superpowers/specs/2026-09-30-edit-delete-content-design.md:3`

**Interfaces:**
- Consumes: everything above, running in the full stack.

- [x] **Step 1: Write the e2e spec**

Create `frontend/e2e/edit-delete.spec.js`:

```js
import { test, expect } from '@playwright/test'
import { registerViaUi, openFirstSearchResult } from './helpers'

// An author edits a reply, deletes the post above it (the reply survives under
// a tombstone), then deletes the thread and lands back in its room. Uses live
// search like thread.spec and reply.spec, so it needs the full stack.
test.describe('editing and deleting', () => {
  test('edit a reply, delete a post, delete the thread', async ({ page }) => {
    await registerViaUi(page)
    await openFirstSearchResult(page, 'dune')

    const title = `Edit target ${Date.now()}`
    await page.getByRole('button', { name: 'Start a Thread' }).click()
    await page.getByPlaceholder('Thread title').fill(title)
    await page.getByRole('button', { name: 'Create Thread' }).click()
    await expect(page).toHaveURL(/\/threads\//)

    const parent = `Parent ${Date.now()}`
    await page.getByPlaceholder('Join the discussion...').fill(parent)
    await page.getByRole('button', { name: 'Post' }).click()
    await expect(page.getByText(parent)).toBeVisible()

    await page.getByRole('button', { name: 'reply' }).first().click()
    const reply = `Reply ${Date.now()}`
    await page.getByPlaceholder('Write a reply...').fill(reply)
    await page.getByRole('button', { name: 'Post' }).first().click()
    await expect(page.getByText(reply)).toBeVisible()

    // The reply's actions come after its parent's in document order.
    await page.getByRole('button', { name: 'edit' }).last().click()
    const fixed = `${reply} (fixed)`
    await page.getByLabel('Edit post').fill(fixed)
    await page.getByRole('button', { name: 'save' }).click()
    await expect(page.getByText(fixed)).toBeVisible()
    await expect(page.getByText('edited', { exact: true })).toBeVisible()

    await page.getByRole('button', { name: 'delete', exact: true }).first().click()
    await page.getByRole('button', { name: 'yes, delete post' }).click()
    await expect(page.getByText(parent)).toHaveCount(0)
    await expect(page.getByText('[deleted]').first()).toBeVisible()
    await expect(page.getByText(fixed)).toBeVisible()

    await page.getByRole('button', { name: 'delete thread' }).click()
    await page.getByRole('button', { name: 'yes, delete thread' }).click()
    await expect(page).toHaveURL(/\/series\/[^/]+$/)
    await expect(page.getByText(title)).toHaveCount(0)
  })
})
```

- [x] **Step 2: Run it against the full stack**

Run: `docker compose up --build -d` (repo root; it runs `alembic upgrade head`), then from `frontend/`: `npx playwright test e2e/edit-delete.spec.js`
Expected: PASS. If `Post` is ambiguous because the reply composer's button renders before the main composer's, scope with `page.locator('form').filter({ has: page.getByPlaceholder('Write a reply...') }).getByRole('button', { name: 'Post' })` instead of `.first()`.

- [x] **Step 3: Update the docs**

`ROADMAP.md` line 44 becomes:

```markdown
| ✅ | **Edit/delete threads & posts** — authors edit post content (an `edited` marker, `posts.edited_at`; no history) and delete their own posts and threads as `[deleted]` tombstones: text erased, replies kept in place, deleted threads out of room listings. Titles are fixed; moderation is Phase 5. ([spec](docs/superpowers/specs/2026-09-30-edit-delete-content-design.md), [plan](docs/superpowers/plans/2026-09-30-edit-delete-content.md)) | `backend/app/services/content.py`, `backend/app/api/{threads,posts}.py`, `frontend/src/components/{Post,ConfirmRemove}.jsx`, `frontend/src/pages/Thread.jsx` |
```

In `CLAUDE.md`, replace the Known-gaps bullet `- Content is immutable (no edit/delete for threads or posts). See \`ROADMAP.md\` for the tracked list.` with:

```markdown
- Only authors can edit or delete content (`services/content.py`); there is no moderator removal yet (Phase 5). A deletion is a tombstone: `deleted_at` set, text erased, `user_id` kept in the row but masked in the API by `post_out_from_orm` / `threads.thread_out` — build every thread/post response through those. The edited marker reads `posts.edited_at`, never `updated_at`, which votes bump. Thread titles cannot be edited. See `ROADMAP.md` for the tracked list.
```

In the spec, change `**Status:** approved design, not yet planned` to `**Status:** implemented (plan: docs/superpowers/plans/2026-09-30-edit-delete-content.md)`.

- [x] **Step 4: Run every suite one last time**

Run: from `backend/`, `DATABASE_URL=postgresql+asyncpg://margin:margin@localhost:5432/margin_test pytest -q`; from `frontend/`, `npm test`.
Expected: all PASS.

- [x] **Step 5: Commit**

```bash
git add frontend/e2e/edit-delete.spec.js ROADMAP.md CLAUDE.md docs/superpowers/specs/2026-09-30-edit-delete-content-design.md
git commit -m "test(e2e): edit and delete; docs: record the tombstone model"
```
