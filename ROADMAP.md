# MARGIN Roadmap

A phased feature plan for MARGIN — a social reading platform (Reddit-style
threaded book discussion + Goodreads-style catalog). The authoritative product
spec is [`margin_spec.md`](./margin_spec.md); this file tracks **what
exists, what's next, and in what order**.

**Status legend:** ✅ done · 🟡 partial / stubbed · ⬜ not started

The current code is a functionally complete v1 MVP (6 models, ~20 endpoints, 8
wired frontend pages) with no automated tests. Phase 0 closes that gap and
hardens the MVP; later phases extend it along the spec's "out of scope for v1"
list.

---

## Phase 0 — Foundations & Hardening

Make the MVP safe to change. This is the current focus.

| Status | Feature | Touches |
| --- | --- | --- |
| 🟡 | **Test pyramid** — pytest (backend), Vitest + RTL (frontend unit), Playwright (e2e). Backend coverage: auth, posts, threads, shelves, pagination, openapi; frontend: Login, Navbar, NotFound; e2e: auth, thread, reply. Broader coverage still ongoing. | `backend/tests/`, `frontend/src/**/*.test.jsx`, `frontend/e2e/` |
| ✅ | **CI workflow** — backend + frontend unit tests on push/PR; e2e nightly. | `.github/workflows/ci.yml` |
| ✅ | **Shelf uniqueness** — `UNIQUE (user_id, book_id)` constraint + migration `5e4fc04a4b1d`. | `backend/app/models/shelf.py`, `backend/alembic/versions/` |
| 🟡 | **Real logout / token handling** — frontend calls `POST /auth/logout` then clears the JWT; server endpoint is still a stateless no-op (no refresh/revocation). Strategy = short-lived JWT + client clear; revisit if token revocation is needed. | `backend/app/api/auth.py:121`, `frontend/src/store/auth.js` |
| ✅ | **Pagination** — `limit`/`offset` on book/genre/post lists (thread lists are served under book/genre). | `backend/app/api/{books,genres,posts}.py` |
| 🟡 | **OpenAPI polish** — tags + response models in place, `/docs` & `/redoc` surfaced by default; response examples still to add. | `backend/app/main.py` |
| ✅ | **404 / error pages** — `NotFound` page + wildcard route. Generic error strings on data-fetch failures remain. | `frontend/src/App.jsx`, `frontend/src/pages/NotFound.jsx` |

---

## Phase 1 — MVP Completion

Round out the spec'd v1 behaviors that are schema-ready but not exposed.

| Status | Feature | Touches |
| --- | --- | --- |
| ✅ | Email/password + Google OAuth auth, JWT sessions | `backend/app/api/auth.py`, `backend/app/services/auth.py` |
| ✅ | Google Books search + book cache, genre pages, shelves | `backend/app/api/{books,genres,users}.py`, `backend/app/services/google_books.py` |
| ✅ | Threads (book XOR genre), 2-level posts/replies, upvotes | `backend/app/api/{threads,posts}.py`, `frontend/src/pages/Thread.jsx` |
| ⬜ | **Edit/delete threads & posts** — no endpoints today; content is immutable. | `backend/app/api/{threads,posts}.py`, `frontend/src/components/Post.jsx` |
| ✅ | **Vote toggling / downvotes** — `votes` table (one row per user per thread/post, ±1), idempotent `PUT /threads/{id}/vote` and `PUT /posts/{id}/vote`; `upvotes` is now a signed `score`. | `backend/app/models/vote.py`, `backend/app/services/votes.py`, `backend/app/api/{threads,posts}.py` |
| ⬜ | **Profile editing** — `User` has only `avatar_url`; add bio + edit endpoint/page. | `backend/app/models/user.py`, `backend/app/api/users.py`, `frontend/src/pages/Profile.jsx` |
| ✅ | **Book metadata enrichment** — Google Books search now caches description, ISBN-13, publisher, page count, ratings, language, categories, and links; the book page surfaces them. Categories auto-map to a seeded genre. | `backend/app/api/books.py`, `backend/app/services/google_books.py`, `frontend/src/pages/Book.jsx` |
| ✅ | **Work grouping** — `works` table with Open Library identity (batched ISBN → title+author → labelled heuristic); threads and shelves hang off works, collections hidden from search, `merge_works` for repair. Supersedes the per-response edition dedup. | `backend/app/services/{works,open_library,work_identity}.py`, `backend/app/api/works.py` |
| ✅ | **Local-first search & covers** — a query is resolved against Open Library at most once (`search_queries`, 30-day TTL) and answered thereafter from a generated `works.search_doc` tsvector, ranked by text match × `ln(readinglog_count)`; covers come from Open Library, Google's placeholder is rejected by its bytes, and Google Books is demoted to lazy edition enrichment on first view of a work page. Edition choice is a language-first dominance ladder (`edition_rank`), so an English work never shows a translated cover or blurb; `scripts.repair_presentation` fixes rows that predate it. | `backend/app/services/{search,covers,enrichment,open_library,works}.py`, `backend/scripts/{backfill_covers,repair_presentation}.py` |
| ⬜ | **Thread sorting/filtering** — sort by new/top, filter genre threads by date. | `backend/app/api/{books,genres}.py`, `frontend/src/pages/{Book,Genre}.jsx` |
| ⬜ | **Empty/loading-state polish** across pages. | `frontend/src/pages/` |

---

## Phase 2 — Social Graph

Explicitly out of scope for v1 in the spec; the natural next layer.

| Status | Feature | Touches |
| --- | --- | --- |
| ⬜ | **Follow users** — `follows` table, follow/unfollow endpoints, follower counts on profile. | new model, `backend/app/api/users.py`, `frontend/src/pages/Profile.jsx` |
| ⬜ | **Activity feed** — home feed of followed users' threads/posts/shelf activity. | new endpoint, `frontend/src/pages/Home.jsx` |
| ⬜ | **Notifications** — replies, mentions, upvotes; `notifications` table + read/unread. | new model + endpoints, new navbar component |
| ⬜ | **Thread subscriptions** — subscribe/notify on new replies. | new model, `backend/app/api/threads.py` |

---

## Phase 3 — Discovery

| Status | Feature | Touches |
| --- | --- | --- |
| ⬜ | **Trending** — surface hot books/genres/threads by recent upvotes + post velocity. | new endpoint, `frontend/src/pages/Home.jsx` |
| ⬜ | **Full-text search** — search across thread titles + post content (Postgres FTS / `tsvector`). | new endpoint + migration, `frontend/src/pages/Search.jsx` |
| ⬜ | **Search filters** — book search by genre/author/year. | `backend/app/api/books.py`, `frontend/src/pages/Search.jsx` |
| ⬜ | **Typo tolerance** — a misspelled query matches nothing today, because `plainto_tsquery` only matches lexemes. Wants a `pg_trgm` index and a similarity fallback; the ranking seam in `search_local` is where it goes. Deliberately out of scope of local-first search. | `backend/app/services/search.py` + migration |
| ⬜ | **Bulk pre-seeding from an Open Library dump** — the catalog fills one query at a time, so the first search for any term still pays ~1.5s. A dump import would make the common case warm from day one. | new script under `backend/scripts/` |
| ⬜ | **Author and series pages** — works now store Open Library's `franchise:` and `series:` subject tags, which makes these mostly a query and a route. | `backend/app/api/works.py`, `frontend/src/pages/` |
| ⬜ | **Recommendations** — book/thread suggestions from shelves + follows. | new service |

---

## Phase 4 — Rich Content

Spec lists ratings, reading-progress, and spoiler tags as out of scope for v1.

| Status | Feature | Touches |
| --- | --- | --- |
| ⬜ | **Markdown / rich-text posts** — render + sanitize; schema unchanged (content stays text). | `frontend/src/components/{Post,PostComposer}.jsx` |
| ⬜ | **Image & avatar uploads** — object storage + signed URLs. | new service, `backend/app/api/users.py` |
| ⬜ | **Book ratings** — star ratings, aggregate on book page. | new model/migration, `frontend/src/pages/Book.jsx` |
| ⬜ | **Reading-progress tracking** — page/percent on shelf entries. | `backend/app/models/shelf.py` + migration |
| ⬜ | **Spoiler tags** — inline spoiler markup, click-to-reveal. | `frontend/src/components/Post.jsx` |

---

## Phase 5 — Moderation & Admin

No moderation surface exists today (no roles, flags, or admin tools).

| Status | Feature | Touches |
| --- | --- | --- |
| ⬜ | **Roles & permissions** — `role` on `User`, admin dependency. | `backend/app/models/user.py`, `backend/app/services/auth.py` |
| ⬜ | **Admin merge/split for works** — surface `merge_works()`; split a work whose editions were wrongly grouped. `scripts.resolve_works --upgrade` deliberately skips a work whose own editions disagree, so those need a human. | `backend/app/services/works.py`, new frontend area |
| ⬜ | **Reporting / flagging** — report threads/posts; moderation queue. | new model + endpoints |
| ⬜ | **Admin dashboard** — review reports, remove content, manage users. | new frontend area |
| ⬜ | **Genre CRUD** — genres are seed-only via migration today; admin create/edit. | `backend/app/api/genres.py` |
| ⬜ | **Audit trail + rate limiting** — who-changed-what; throttle write endpoints. | middleware, new model |

---

## Phase 6 — Scale & Ops

| Status | Feature | Touches |
| --- | --- | --- |
| ⬜ | **Background jobs / queue** — async Google Books sync, notification fan-out. | new worker service |
| ⬜ | **Email verification** — password reset already ships (`/auth/forgot-password`). | `backend/app/api/auth.py`, email service |
| ⬜ | **Rate-limit `/api/works/search`** — much cheaper since local-first search: a repeat query makes no upstream call at all, so only a *cold* query costs anything (one 5s Open Library call, or the Google fallback). Still anonymous and still writes `works` rows, so a stream of distinct queries is unbounded work. | `backend/app/api/works.py`, `backend/app/services/search.py` |
| ⬜ | **Profile shelves render empty cards** — `GET /api/users/{username}` returns shelf rows (shelf `id` + `work_id`, no title/author/cover) and `Profile.jsx` feeds them to `WorkCard`, which links to `/works/<shelf-id>`. Pre-dates work grouping. Return `WorkOut` rows instead. | `backend/app/api/users.py`, `frontend/src/pages/Profile.jsx` |
| ⬜ | **Data export** — user shelf/post export. | new endpoint |
| ⬜ | **Observability** — structured logging, metrics, error tracking. | `backend/app/main.py`, infra |

---

## Working on this repo

Feature work is delegated to focused subagents defined in
[`.claude/agents/`](./.claude/agents): `backend-dev`, `frontend-dev`,
`test-engineer`, and `code-reviewer`. See [`CLAUDE.md`](./CLAUDE.md) for
architecture, conventions, gotchas, and test commands.
