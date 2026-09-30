# Edit and delete threads & posts — design

**Status:** implemented (plan: docs/superpowers/plans/2026-09-30-edit-delete-content.md)
**Date:** 2026-09-30
**Follows:** `ROADMAP.md` Phase 1 ("Edit/delete threads & posts — no endpoints
today; content is immutable").

## 1. Why

Content is immutable today: a reader who posts a typo, a wrong claim or an
unmarked spoiler has no way to fix or withdraw it. Authors should be able to
correct and remove their own writing, without tearing holes in other people's
conversations.

## 2. Goals and non-goals

**Goals**
- An author can edit the content of their own posts, including a thread's
  opening post, at any time. Edited posts say so.
- An author can delete their own posts and threads. A deletion leaves a
  `[deleted]` tombstone; replies beneath it stay where they are.
- Deleted text is actually erased, not merely hidden.

**Non-goals**
- **Editing thread titles.** A thread's title is fixed once posted, and so are
  its room (series or genre) and its book tag.
- **Moderation.** Nobody but the author can edit or delete — not librarians.
  Reports, removal by moderators and roles are Phase 5. The tombstone model
  below must not preclude a later "removed by moderator" state.
- **Revision history.** No previous versions are stored. The `edited` marker
  is the only record that a post changed.
- **Undelete.** A deletion is final.

## 3. Decisions

| # | Decision | Why |
|---|---|---|
| D1 | Soft delete: tombstone in place, never a row delete. | `posts.parent_id` is `ON DELETE SET NULL`; a hard delete would promote replies to top level and strip their context. Votes and the reply tree stay intact. |
| D2 | Author-only edit and delete. | Librarians curate the catalog, not discussion. Moderation needs reports, audit and appeal first (Phase 5). |
| D3 | Edit any time; visible `edited` marker; no history. | Matches Reddit. The marker makes after-the-fact edits visible; history can come with the Phase 5 audit trail. |
| D4 | Thread titles are not editable; a thread can only be deleted. | Titles are what replies and listings were written against. |
| D5 | A new `posts.edited_at` column, not `updated_at`. | `set_vote` updates `score` with a Core `update()` (`services/votes.py`), which fires `updated_at`'s `onupdate`: every voted post would look edited. |
| D6 | Deleting erases text and hides identity in the API, but keeps `user_id` in the row. | The reader's words are gone; Phase 5 moderation can still attribute abuse. `user_id` is exposed on `PostOut`/`ThreadOut`, so the API must null it too, or tombstones are not anonymous. |

## 4. Data model

One Alembic migration adds three nullable columns:

- `posts.edited_at timestamptz` — set on every successful edit.
- `posts.deleted_at timestamptz` — set once, on delete.
- `threads.deleted_at timestamptz` — set once, on delete.

On delete, `posts.content` is set to `''` (or `threads.title` to `''`). The
columns stay `NOT NULL`. No enum or status column: Phase 5 can add a `removed`
state beside `deleted_at` when moderation exists. The models declare the same
columns so `create_all` in tests matches the migration.

## 5. Backend

### 5.1 Service

A new `services/content.py` owns the rules, with no FastAPI types:

- `edit_post(db, post, user, content)` — author check, refuses a deleted post,
  refuses blank content (after strip), sets `content` and `edited_at`.
- `delete_post(db, post, user)` — author check; idempotent (an already-deleted
  post returns without change); clears `content`, sets `deleted_at`.
- `delete_thread(db, thread, user)` — author check; idempotent; clears
  `title`, sets `deleted_at`, and also tombstones the thread's opening post
  (its earliest top-level post) when the thread's author wrote it. Other
  readers' posts are untouched. There is no opener flag: a thread created
  without a body whose author later wrote the first top-level post will have
  that post tombstoned too. That is accepted — it is still the author's own
  writing in the thread they chose to delete.

Service errors are domain exceptions (not-author, deleted, blank) that the
routes map to status codes.

### 5.2 Endpoints

| Route | Success | Errors |
|---|---|---|
| `PATCH /api/posts/{id}` `{"content": "..."}` | 200, `PostOut` | 401 anonymous · 403 not the author · 404 missing · 409 deleted · 422 blank |
| `DELETE /api/posts/{id}` | 204 (also when already deleted) | 401 · 403 · 404 |
| `DELETE /api/threads/{id}` | 204 (also when already deleted) | 401 · 403 · 404 |

The ownership check runs before the idempotency shortcut, so a non-author
deleting an already-deleted post still gets 403. The `PATCH` body is a new
`PostUpdate` schema with an OpenAPI example (`tests/test_openapi.py` requires
one).

### 5.3 Writes against deleted content

All return 409 with a readable `detail`:
- `POST /api/posts/` whose `thread_id` is a deleted thread, or whose
  `parent_id` is a deleted post.
- `PUT /api/threads/{id}/vote` on a deleted thread; `PUT /api/posts/{id}/vote`
  on a deleted post.

### 5.4 Reads

- `PostOut` gains `edited_at: datetime | None` and `deleted: bool`;
  `ThreadOut` gains `deleted: bool`. `user_id` becomes `UUID | None` on both.
- A deleted post or thread serializes with `deleted: true`, `content`/`title`
  `""`, and `author` and `user_id` `null`. Score and tree position are kept.
  One helper builds each tombstone, so every route (thread page, vote,
  edit) applies the same masking.
- `GET /api/threads/{id}` still returns a deleted thread (200) with its
  remaining posts. A deleted post with no live replies is omitted from the
  tree entirely; a deleted post with live replies stays as a tombstone.
- Room listings (`services/threads.py`, the one listing query: series feed,
  its book filter, genre feed) exclude deleted threads, and `post_count`
  counts live posts only.

## 6. Frontend

### 6.1 Hooks (`api/threads.js`)

`useEditPost`, `useDeletePost`, `useDeleteThread`. Each invalidates
`['threads', id]`; `useDeleteThread` also invalidates its room listing
(`['series', slug, 'threads']` or `['genres', slug, 'threads']`), as
`useVoteThread` does. Errors are shown with `errorMessage()`.

### 6.2 Ownership

Controls render only when `user.id === post.user_id` (or `thread.user_id`).
Tombstones carry `user_id: null`, so they never show controls.

### 6.3 `components/Post.jsx`

- **Actions.** The owner sees `edit` and `delete` beside `reply`, styled
  exactly like `reply` (`text-ink-dim hover:text-accent`). They add no visual
  weight.
- **Edit.** Swaps the paragraph for a `.input` textarea prefilled with the
  content, with `save` (`.btn-primary`) and `cancel` (`.btn-ghost`). Save is
  disabled while blank or pending; a failure shows `.alert-danger` beneath.
- **Delete confirm.** Inline, never `window.confirm()` or a modal: the action
  row becomes `rm post? [y] [n]`. Focus moves to `n` so a stray Enter does
  not delete; `y` is `text-danger`; Escape cancels.
- **Edited marker.** `· edited` after the timestamp, `text-ink-dim`, wrapped in
  the same `DiagnosticFloat` as the created time, showing the absolute edit
  time.
- **Tombstone.** `[deleted]` in `text-ink-dim` in place of both the author and
  the content. The vote control shows the score but is disabled; no reply,
  edit or delete actions. Its replies render beneath with the existing rail
  and elbows.

### 6.4 `pages/Thread.jsx`

- The owner of a live thread sees `delete thread` in the header metadata row,
  with the same `rm thread? [y] [n]` confirm. On success it navigates to the
  room (series or genre page) with `replace`, so Back does not return to the
  tombstone.
- A deleted thread renders its title as `[deleted]` in `text-ink-dim` with no
  author; the `PathHeader` segment reads `[deleted]`. The composer is replaced
  by `.alert-muted`: "This thread was deleted and no longer accepts replies."
  Remaining posts stay readable.
- The status bar adds a `deleted` fact, so the state is not carried by color
  alone.

No new tokens, glyphs, component classes, radii or durations.

## 7. Testing

**Backend (pytest)**
- Edit: author succeeds and gets `edited_at`; non-author 403; anonymous 401;
  missing 404; deleted 409; blank 422.
- Voting on a post does not set `edited_at` (the D5 regression).
- Delete post/thread: author succeeds; idempotent 204; non-author 403 even
  when already deleted; anonymous 401.
- Thread delete tombstones the author's opening post, not others' posts.
- Tombstone serialization: `content`/`title` empty, `author` and `user_id`
  null — asserted on the thread page, vote and edit responses.
- Thread tree: a deleted leaf is omitted; a deleted parent with live replies
  stays and keeps them.
- Listings exclude deleted threads; `post_count` ignores deleted posts.
- 409s: reply to a deleted post, post in a deleted thread, vote on either.
- OpenAPI: `PostUpdate` carries an example.

**Frontend unit (Vitest + RTL)**
- `Post.test.jsx`: controls for owner only; edit save/cancel/error; confirm
  focuses `n`, `y` deletes, Escape cancels; tombstone rendering; edited
  marker.
- `Thread.test.jsx`: deleted thread (title, no composer, notice); owner
  delete navigates to the room.

**E2E (Playwright)** — `e2e/edit-delete.spec.js`: an author edits their reply
and sees `edited`; deletes a post that has a reply and sees `[deleted]` with
the reply still beneath; deletes the thread and lands in the room with the
thread gone from the listing.

## 8. Docs

On completion: mark the ROADMAP Phase 1 row ✅, and replace CLAUDE.md's
"Content is immutable" known gap with the tombstone model (author-only, soft
delete, `edited_at` vs `updated_at`).
