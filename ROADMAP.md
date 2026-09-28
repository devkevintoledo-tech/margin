# MARGIN Roadmap

A phased feature plan for MARGIN — a social reading platform (Reddit-style
threaded book discussion + Goodreads-style catalog). The authoritative product
spec is [`margin_spec.md`](./margin_spec.md); this file tracks **what
exists, what's next, and in what order**.

**Status legend:** ✅ done · 🟡 partial / stubbed · ⬜ not started

The current code is a functionally complete v1 MVP: works and series as the
catalog, series pages as the discussion home, an offline catalog pipeline that
publishes loadable releases, and a terminal-style design system — covered by
backend, frontend-unit and e2e suites in CI. Phase 0 finishes hardening it;
later phases extend it along the spec's "out of scope for v1" list.

---

## Phase 0 — Foundations & Hardening

Make the MVP safe to change. This is the current focus.

| Status | Feature | Touches |
| --- | --- | --- |
| 🟡 | **Test pyramid** — pytest (backend, ~370 tests: auth, works, series, search, enrichment, votes, catalog loader, scripts), Vitest + RTL (frontend unit: pages, shared components, design tokens), Playwright (e2e: auth, search, series, thread, reply). Gaps: Home, Genre, Search, Thread and Register pages have no unit tests. | `backend/tests/`, `frontend/src/**/*.test.jsx`, `frontend/e2e/` |
| ✅ | **CI workflow** — backend, frontend unit and pipeline tests on push/PR; e2e nightly. | `.github/workflows/ci.yml` |
| ✅ | **Shelf uniqueness** — `UNIQUE (user_id, work_id)` (`uq_shelf_user_work`); shelves hang off works since work grouping. | `backend/app/models/shelf.py`, `backend/alembic/versions/` |
| 🟡 | **Real logout / token handling** — frontend calls `POST /auth/logout` then clears the JWT; server endpoint is still a stateless no-op (no refresh/revocation). Strategy = short-lived JWT + client clear; revisit if token revocation is needed. | `backend/app/api/auth.py:203`, `frontend/src/store/auth.js` |
| ✅ | **Pagination** — `limit`/`offset` on genre works, genre threads and series threads. | `backend/app/api/{genres,series}.py`, `backend/app/services/threads.py` |
| 🟡 | **OpenAPI polish** — tags + response models in place, `/docs` & `/redoc` surfaced by default; response examples still to add. | `backend/app/main.py` |
| ✅ | **404 / error pages** — `NotFound` page + wildcard route. Generic error strings on data-fetch failures remain. | `frontend/src/App.jsx`, `frontend/src/pages/NotFound.jsx` |
| ✅ | **Public profile hides email** — `GET /api/users/{username}` is anonymous and now serializes `PublicUserOut`; `email` stays on the auth routes. | `backend/app/schemas/user.py`, `backend/app/api/users.py` |

---

## Phase 1 — MVP Completion

Round out the spec'd v1 behaviors that are schema-ready but not exposed.

| Status | Feature | Touches |
| --- | --- | --- |
| ✅ | Email/password + Google OAuth auth, JWT sessions | `backend/app/api/auth.py`, `backend/app/services/auth.py` |
| ✅ | Book search, genre pages, shelves (search is now local-first; see below) | `backend/app/api/{works,genres,users}.py` |
| ✅ | Threads (series room XOR genre, optional book tag), 2-level posts/replies | `backend/app/api/{series,threads,posts}.py`, `frontend/src/pages/Thread.jsx` |
| ⬜ | **Edit/delete threads & posts** — no endpoints today; content is immutable. | `backend/app/api/{threads,posts}.py`, `frontend/src/components/Post.jsx` |
| ✅ | **Vote toggling / downvotes** — `votes` table (one row per user per thread/post, ±1), idempotent `PUT /threads/{id}/vote` and `PUT /posts/{id}/vote`; `upvotes` is now a signed `score`. | `backend/app/models/vote.py`, `backend/app/services/votes.py`, `backend/app/api/{threads,posts}.py` |
| ⬜ | **Profile editing** — `User` has only `avatar_url`; add bio + edit endpoint/page (`Profile.jsx` already renders `bio` if present). | `backend/app/models/user.py`, `backend/app/api/users.py`, `frontend/src/pages/Profile.jsx` |
| ✅ | **Book metadata enrichment** — editions carry description, ISBN-13, publisher, page count, language, categories and links from Google Books, filled lazily on first view of a book's series page. Categories auto-map to a seeded genre. | `backend/app/services/{enrichment,google_books}.py` |
| ✅ | **Work grouping** — `works` table with Open Library identity (batched ISBN → title+author → labelled heuristic); threads and shelves hang off works, collections hidden from search, `merge_works` for repair. Supersedes the per-response edition dedup. | `backend/app/services/{works,open_library,work_identity}.py`, `backend/app/api/works.py` |
| ✅ | **Local-first search & covers** — a query is resolved against Open Library at most once (`search_queries`, 30-day TTL) and answered thereafter from a generated `works.search_doc` tsvector, ranked by text match × `ln(readinglog_count)`; covers come from Open Library, Google's placeholder is rejected by its bytes, and Google Books is demoted to lazy edition enrichment on first view of a work page. Edition choice is a language-first dominance ladder (`edition_rank`), so an English work never shows a translated cover or blurb; `scripts.repair_presentation` fixes rows that predate it. | `backend/app/services/{search,covers,enrichment,open_library,works}.py`, `backend/scripts/{backfill_covers,repair_presentation}.py` |
| ✅ | **Series as the discussion home** — every work has a series (a singleton when nothing better is known); `/series/:slug` is a book's only page and its room, threads can tag one member book, and legacy `/works/:id` URLs redirect. | `backend/app/services/series.py`, `backend/app/api/series.py`, `frontend/src/pages/Series.jsx` |
| ✅ | **Terminal design system** — tokens, contrast-tested text tiers, path header, status bar, diagnostic floats, `ls -l` tables. | `frontend/src/index.css`, `frontend/tailwind.config.js`, `docs/visual-identity.md` |
| ✅ | **Profile shelves render real cards** — each shelf is a list of `WorkOut` rows, newest first, linking to the book's series. | `backend/app/api/users.py`, `frontend/src/pages/Profile.jsx` |
| ⬜ | **Thread sorting/filtering** — thread lists are score-ordered only; add new/top and date filters. | `backend/app/services/threads.py`, `frontend/src/pages/{Series,Genre}.jsx` |
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
| ⬜ | **Search filters** — book search by genre/author/year. | `backend/app/api/works.py`, `backend/app/services/search.py`, `frontend/src/pages/Search.jsx` |
| ⬜ | **Typo tolerance** — a misspelled query matches nothing today, because `plainto_tsquery` only matches lexemes. Wants a `pg_trgm` index and a similarity fallback; the ranking seam in `search_local` is where it goes. Deliberately out of scope of local-first search. | `backend/app/services/search.py` + migration |
| ✅ | **Catalog pipeline & releases** — `pipeline/` builds the catalog offline from Open Library dumps and Wikidata (series ladder, duplicate grouping, overrides, golden-set gate) and publishes a versioned release; `scripts.load_catalog_release` loads it in one transaction, adopting runtime works. Replaces one-query-at-a-time pre-seeding. | `pipeline/`, `backend/app/services/catalog_loader.py`, `backend/scripts/load_catalog_release.py` |
| ⬜ | **Catalog refresh** — monthly re-runs against new dumps: cutting, reviewing (report diff, golden set) and loading a release, and how books published after the last dump enter between releases. Needs a spec (see `TODO.md`). | `pipeline/`, `backend/app/services/catalog_loader.py` |
| ⬜ | **Author pages** — series pages shipped (Phase 1); authors are still a string on `works`, so this needs an author identity first (the pipeline already clusters authors). | `backend/app/models/work.py`, `frontend/src/pages/` |
| ⬜ | **Recommendations** — book/thread suggestions from shelves + follows. | new service |

---

## Phase 4 — Rich Content

Spec lists reading-progress and spoiler tags as out of scope for v1. Star ratings
and user reviews are **rejected**, not deferred — see `docs/visual-identity.md` §1.

| Status | Feature | Touches |
| --- | --- | --- |
| ⬜ | **Takes** — short opinionated statements as a first-class object; interaction model (agree/disagree vs. voting) still undecided (`docs/visual-identity.md` §5). | new model + endpoints + feed |
| ⬜ | **Markdown / rich-text posts** — render + sanitize; schema unchanged (content stays text). | `frontend/src/components/{Post,PostComposer}.jsx` |
| ⬜ | **Image & avatar uploads** — object storage + signed URLs. | new service, `backend/app/api/users.py` |
| ⬜ | **Reading-progress tracking** — page/percent on shelf entries, plus Paused/DNF statuses. | `backend/app/models/shelf.py` + migration |
| ⬜ | **Spoiler tags** — inline spoiler markup, click-to-reveal. | `frontend/src/components/Post.jsx` |

---

## Phase 5 — Moderation & Admin

No moderation surface exists today (no roles, flags, or admin tools).

| Status | Feature | Touches |
| --- | --- | --- |
| ⬜ | **Roles & permissions** — `role` on `User`, admin dependency. Librarian tools start with an `is_librarian` flag that must not preclude this. | `backend/app/models/user.py`, `backend/app/services/auth.py` |
| 🟡 | **Librarian tools** — in-app merge, split, move-to-series, reorder, rename, remove and dissolve from the series page, logged in `catalog_corrections`, undoable (except merge/split), and exported to `pipeline/overrides/` so releases keep them. Design approved, not yet planned. | [spec](docs/superpowers/specs/2026-09-28-librarian-tools-design.md), new `services/librarian.py`, `api/librarian.py` |
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
| ⬜ | **Data export** — user shelf/post export. | new endpoint |
| ⬜ | **Observability** — structured logging, metrics, error tracking. | `backend/app/main.py`, infra |

---

## Working on this repo

Feature work is delegated to focused subagents defined in
[`.claude/agents/`](./.claude/agents): `backend-dev`, `frontend-dev`,
`test-engineer`, and `code-reviewer`. See [`CLAUDE.md`](./CLAUDE.md) for
architecture, conventions, gotchas, and test commands.
