# Per-User Voting — Up/Down with Toggling

**Date:** 2026-09-22
**Status:** Approved (design)
**Roadmap item:** Phase 1 — "Vote toggling / downvotes" (`ROADMAP.md:43`)
**Tier-2 item:** §24 (`docs/visual-identity.md:95`)

## Problem

`threads.upvotes` and `posts.upvotes` are increment-only integers. `POST
/{id}/upvote` does `upvotes += 1` with no record of who voted, so:

- the same user can vote an unlimited number of times (a double-click already
  double-counts);
- a vote cannot be undone;
- there is no downvote;
- read-modify-write in Python means concurrent votes can lose each other.

`books.py:149` and `genres.py:80` rank thread lists by `ORDER BY upvotes DESC`,
so the counter is load-bearing and cannot simply be dropped.

This spec adds one vote per user per item, settable to up, down, or none.

## Decisions

- **Up and down (±1).** Chosen over up-plus-un-vote. Score is a signed sum and
  may go negative.
- **Denormalized counter kept.** A `votes` table *plus* a `score` column on
  `threads`/`posts`, both written in the same transaction. Computing the score
  as `SUM(value)` on every read would turn the two thread-list rankings into a
  grouped join over every vote row on every book and genre page.
- **Column renamed `upvotes` → `score`.** A column that can read `-3` must not
  be called `upvotes`.
- **Existing counts reset to 0.** The current values have no user attribution.
  Resetting buys the invariant that `score` is always exactly `SUM(value)` of
  its vote rows, so any drift is a real bug rather than legacy noise.
- **Nullable `thread_id` XOR `post_id`, not a polymorphic pair.** A
  `(votable_type, votable_id)` pair gives up foreign keys, so deleting a thread
  would orphan its votes. The XOR idiom is the one `Thread` already uses for
  `book_id`/`genre_id`, and both FKs get `ON DELETE CASCADE`.
- **Clearing a vote deletes the row.** No `value = 0` rows. This keeps `value`
  a two-valued `CHECK` and avoids introducing an `Enum` type, whose
  drop-on-downgrade gotcha is documented in `CLAUDE.md`.
- **One idempotent endpoint replaces the increment endpoints.** `POST
  /{id}/upvote` is removed outright, not deprecated: it is an internal API with
  a single consumer, and leaving an increment-only path beside the votes table
  invites drift between `score` and the rows that are supposed to explain it.

## Data model

New `backend/app/models/vote.py`, exported from `models/__init__.py` (so
`Base.metadata` stays complete).

```
votes
  id          UUID  PK, default gen_random_uuid()
  user_id     UUID  FK users.id      ON DELETE CASCADE, NOT NULL, indexed
  thread_id   UUID  FK threads.id    ON DELETE CASCADE, NULL, indexed
  post_id     UUID  FK posts.id      ON DELETE CASCADE, NULL, indexed
  value       SMALLINT NOT NULL
  created_at  TIMESTAMPTZ NOT NULL default now()
  updated_at  TIMESTAMPTZ NOT NULL default now(), onupdate
```

Constraints:

- `ck_vote_value` — `value IN (-1, 1)`
- `ck_vote_exactly_one_target` —
  `(thread_id IS NOT NULL) <> (post_id IS NOT NULL)`
- `uq_vote_user_thread` — partial unique index on `(user_id, thread_id)
  WHERE thread_id IS NOT NULL`
- `uq_vote_user_post` — partial unique index on `(user_id, post_id)
  WHERE post_id IS NOT NULL`

The two partial unique indexes are what make one-vote-per-user-per-item a
database guarantee rather than an application convention.

Relationships: `Vote.user` / `User.votes`, `Vote.thread` / `Thread.votes`,
`Vote.post` / `Post.votes`, all with `cascade="all, delete-orphan"` on the
parent side.

### Migration

One revision, `down_revision = '80f2ffa56f79'` (current head).

`upgrade()`:
1. `op.alter_column('threads', 'upvotes', new_column_name='score')`
2. `op.alter_column('posts', 'upvotes', new_column_name='score')`
3. `op.execute('UPDATE threads SET score = 0')`
4. `op.execute('UPDATE posts SET score = 0')`
5. `op.create_table('votes', ...)` with the constraints above
6. `op.create_index(..., postgresql_where=...)` for the two partial uniques

`downgrade()`: drop `votes` (indexes go with it), rename `score` back to
`upvotes` on both tables. No enum type to drop. Counts are not restored —
they were reset on the way up and the information no longer exists.

## API

Both vote endpoints live in their existing routers and are idempotent
"set my vote to this value":

```
PUT /api/threads/{id}/vote   body {"value": 1 | -1 | 0}  → ThreadOut
PUT /api/posts/{id}/vote     body {"value": 1 | -1 | 0}  → PostOut
```

`value: 0` clears the vote. Idempotency is the point: a double-click sets the
same state twice instead of double-counting, which is today's bug.

New `VoteIn` schema in `schemas/thread.py`: `value: int` with
`Field(ge=-1, le=1)`, so a bad value is a 422 from Pydantic rather than a
`CHECK` violation from Postgres.

Handler logic, shared by both routers via a helper in
`backend/app/services/votes.py` so the rule lives in one place:

1. Load the target; 404 if missing.
2. Load the caller's existing vote row for that target.
3. `old = existing.value if existing else 0`; `delta = new - old`.
4. If `delta == 0`, return the target unchanged (no write).
5. Apply the row change: insert (`old == 0`), update (`old != 0 and new != 0`),
   or delete (`new == 0`).
6. `UPDATE threads SET score = score + :delta WHERE id = :id` as a SQL
   expression — never `obj.score += delta` in Python — so concurrent votes
   cannot lose each other. Switching up→down is a delta of `-2`.
7. Re-read and return the target.

Two concurrent votes from the same user race between steps 2 and 5: both read
"no existing row" and both insert, and the partial unique index rejects the
loser with an `IntegrityError`. The insert therefore runs inside a savepoint
(`async with db.begin_nested()`): without one, the failed statement poisons the
whole session transaction and `get_db` can only roll the request back. The
handler catches the error, and retries the sequence once from step 2, where it
now finds the winner's row and takes the update branch. One retry is enough
because the index guarantees at most one row can exist afterward. This is
preferred over `SELECT ... FOR UPDATE` on the
target, which would serialize every voter on a popular thread to fix a race
that only a single user's double-click can cause.

Requires authentication (`get_current_user`); anonymous callers get 401.

### Response shapes

`ThreadOut`, `ThreadSummary` and `PostOut` in `schemas/thread.py`:

- `upvotes: int` → `score: int`
- new `my_vote: int` (`-1`, `0` or `1`; `0` for anonymous readers)

`my_vote` has to survive a page reload, so the read endpoints need it too:

- `GET /threads/{id}` and `GET /books/{book_id}/threads` and
  `GET /genres/{slug}/threads` gain
  `current_user: User | None = Depends(get_current_user_optional)`.
- In the two list queries, `my_vote` is a correlated scalar subquery wrapped in
  `func.coalesce(..., 0)` — **not** a `LEFT JOIN`, which would have to be added
  to the existing `GROUP BY` that produces `post_count`. For an anonymous
  caller, `literal(0).label("my_vote")` skips the subquery entirely.
- In `GET /threads/{id}`, the thread's own `my_vote` is one scalar query, and
  the posts' votes are fetched as a single
  `SELECT post_id, value FROM votes WHERE user_id = :uid AND post_id IN (...)`
  keyed into a dict. `post_out_from_orm(post, my_vote=...)` gains the
  parameter. No per-post query, and no lazy relationship is touched — the
  `MissingGreenlet` constraint documented in that helper still holds.
- Both list queries change `ORDER BY Thread.upvotes.desc()` to
  `Thread.score.desc()`.

## Frontend

- **`components/VoteControl.jsx`** — gains a down arrow and a `myVote` prop
  (`-1 | 0 | 1`); `onVote` receives the value to set, computed by the control:
  clicking the lit arrow sends `0`, clicking the other sends its own value.
  Both arrows are `ink-muted` at rest; the active one takes `accent-ink`. No
  new tokens, radii, sizes or durations — §24's "voting never dominates"
  survives, and the header comment claiming downvotes are deliberately absent
  is rewritten.
- **`api/threads.js`** — `useUpvoteThread`/`useUpvotePost` become
  `useVoteThread`/`useVotePost`, issuing `PUT` with `{value}`. Invalidation
  targets are unchanged.
- **`components/ThreadCard.jsx`, `components/Post.jsx`** — read `score` and
  `my_vote` instead of `upvotes`, pass both to `VoteControl`.
- **`pages/Thread.jsx:59`** — `{thread.upvotes ?? 0} upvotes` becomes
  `{thread.score ?? 0} points`, since the number can be negative.

## Testing

**Backend (pytest, `margin_test` DB):** new `backend/tests/test_votes.py`, plus
updating `test_threads.py:61` which asserts the old increment behavior.

1. Upvote a thread → `score == 1`, `my_vote == 1`.
2. Downvote → `score == -1`.
3. Same value twice → still `1` (idempotent, no second row).
4. Up then down → `score == -1` (delta of 2 applied once), exactly one row.
5. Setting `0` clears → `score == 0`, zero rows.
6. Two different users voting up → `score == 2`.
7. `value: 2` → 422; unauthenticated → 401; unknown id → 404.
8. `GET /threads/{id}` returns the caller's `my_vote` for the thread *and* for
   each post; returns `0` for every one of them when anonymous.
9. Thread lists order by `score` and carry `my_vote`.
10. Deleting a thread cascades its votes away.
11. The same post votes for two users do not collide (partial unique index is
    per-user).

**Frontend (Vitest + RTL):** new `components/VoteControl.test.jsx` — renders
the three states, and clicking the lit up arrow fires `onVote(0)` while
clicking down fires `onVote(-1)`.

**E2E:** none. The existing auth/thread specs already exercise the page.

## Out of scope (YAGNI)

- Collapsing, hiding or greying heavily-downvoted content.
- A vote-history surface or "who voted" list.
- Rate limiting or vote-fraud detection.
- Hot/rising ranking — that belongs to the Communities slice, which is what
  needs it.
- Backfilling the discarded legacy counts.
