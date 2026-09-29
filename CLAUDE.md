# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

MARGIN — a social reading platform (Reddit-style threaded book discussion + Goodreads-style catalog). FastAPI + PostgreSQL backend, React (Vite) frontend. `margin_spec.md` is the authoritative product/design spec. The code is a functionally complete v1 MVP with a test suite and CI, but the spec still describes intent ahead of the code in places (see Known gaps below and `ROADMAP.md`).

## Commands

Everything runs via Docker Compose from the repo root:

```bash
docker compose up --build        # db (5432) + backend (8000) + frontend (5173)
docker compose logs -f backend   # tail backend logs
docker compose exec backend bash # shell into backend
```

Backend (inside `backend/`, or via `docker compose exec backend`):

```bash
uvicorn app.main:app --reload                          # run API (compose does this for you)
alembic revision --autogenerate -m "message"           # create a migration
alembic upgrade head                                    # apply migrations
alembic downgrade -1                                    # roll back one
```

Frontend (inside `frontend/`):

```bash
npm run dev        # vite dev server
npm run build      # production build
```

### Testing

A test pyramid exists; there is no linter/formatter configured yet. Always run tests before claiming they pass. `.github/workflows/ci.yml` runs backend + frontend unit tests on every push/PR and the e2e suite nightly.

**Backend — pytest** (async, `asyncio_mode=auto`, httpx `ASGITransport`). Tests run against a **separate `margin_test` database** so they never touch dev data; the schema is built with `Base.metadata.create_all` (not Alembic) per test, and Google Books must be mocked (`respx`) — never hit the network. Email likewise never leaves the process: override `email_sender_dep` with a fake `EmailSender` to capture the reset URL (see `tests/test_password_reset.py`). From `backend/`:

```bash
docker compose up -d db                                                   # Postgres must be running
docker compose exec db psql -U margin -c "CREATE DATABASE margin_test;"   # one-time
DATABASE_URL=postgresql+asyncpg://margin:margin@localhost:5432/margin_test pytest
```

**Frontend unit — Vitest + React Testing Library** (jsdom). From `frontend/`:

```bash
npm test            # vitest run
npm run test:watch  # watch mode
```

**E2E — Playwright** drives the real app and needs the full stack up. From `frontend/`:

```bash
docker compose up --build      # in another terminal
npx playwright install         # one-time
npm run test:e2e               # auth flow is network-free; thread/reply use live Google Books search
```

### Catalog pipeline

`pipeline/` builds the catalog offline from Open Library dumps and Wikidata and
publishes a versioned release; production only loads releases. It has its own
dependencies and never connects to the app database. From `pipeline/`:

```bash
python -m venv .venv && .venv/bin/pip install -r requirements.txt   # one-time
.venv/bin/python -m pytest                                          # fixture dumps only, no network
cd .. && pipeline/.venv/bin/python -m pipeline run --version 2026.10.1          # full build (~20 GB free disk)
pipeline/.venv/bin/python -m pipeline run --from group --version 2026.10.1      # resume from a stage
pipeline/.venv/bin/python -m pipeline golden-draft Q45875                       # draft a golden entry
```

Working state is `build/catalog.duckdb`; releases land in `releases/catalog-<version>/`
(both git-ignored). `--upload` attaches the release to a GitHub Release via `gh`
(NordVPN breaks `gh` — disconnect first).

### Subagents & roadmap

Feature work is delegated to focused subagents in `.claude/agents/`: `backend-dev`, `frontend-dev`, `test-engineer`, and `code-reviewer`. The phased feature plan lives in `ROADMAP.md` (Phase 0 = test/hardening foundations is done; Phase 1 is the current focus).

## Architecture

### Backend (`backend/app/`)
Async end-to-end FastAPI app. The layering is strict:

- **`models/`** — SQLAlchemy 2.0 ORM (`DeclarativeBase` in `models/base.py`). `models/__init__.py` imports every model so `Base.metadata` is fully populated — always import models through the package or this `__init__` so metadata stays complete.
- **`schemas/`** — Pydantic v2 request/response models. Keep API I/O shapes here, never expose ORM models directly.
- **`services/`** — business logic with no FastAPI types. `search.py` owns search: query gating against `search_queries`, Open Library ingest, and the local ranked query (it is the only caller of Google on the search path, and only when Open Library is down); `open_library.py` is both the *search* source (`search_works`, cover URLs, `genre_slug`) and the *work identity* source (the work/edition graph Google Books lacks: batched `isbn:(...)` search, then title+author with an `edition_count` tiebreak, never raising on upstream failure); `google_books.py` is the Google Books HTTP client, now an *enrichment* client rather than a search one (httpx, parses the Volumes API into a normalized dict; optional `GOOGLE_BOOKS_API_KEY`, keyless fallback; two-pass title-weighted search, cover-URL upgrade); `enrichment.py` fills a work's editions and description from Google on first
view of its page, attaching only volumes whose `canonical_key` matches one of
the work's `identity_keys` (its stored key, or the key recomputed from its own
title — some works drifted apart from the key they were created under) —
Google answers a title+author query with everything the author wrote, so an
unattached volume is not evidence that it belongs; `covers.py` HEADs a cover URL to reject Google's placeholder; `works.py` owns the resolution ladder, `upsert_work_from_ol`, representative-edition selection and `merge_works`; `work_identity.py` holds the pure string rules the others build on; `series_identity.py` holds the pure series-tag rules (parsing `franchise:`/`series:` subjects, choosing the container, slugs); `series.py` is the only writer of `series` rows outside librarian fixes — it gives any work flushed without one a singleton, promotes a singleton when its tags later name a series, and provides `absorb_series`, which `merge_works` runs before rewriting thread tags; `threads.py` owns the one thread-listing query (series feed, its per-book filter, genre feed) and thread creation; `genre_inference.py` is the pure taxonomy loader and subject → genre rules (`infer_genres`: `genre:` tags first, whole-word matching, `exclude` lists, no generic fallback); `genre_taxonomy.py` syncs `app/data/genres.yaml` into `genres`; `genres.py` is the only writer of `genre_votes`, `genre_inferences` and `work_genres` — `recompute` runs after every vote, inference, veto, revert and merge, the 5-per-reader cap is taken under `FOR UPDATE` on the work row, and `absorb` is `merge_works`' genre half; `auth.py` holds JWT (python-jose, HS256), bcrypt password hashing, reset-token generation/hashing, and the `get_current_user` / `get_current_user_optional` dependencies; `email.py` provides the `EmailSender` ABC with SMTP and console implementations; `librarian/` holds the librarian tools (`keys`, `record`, `placement`, `identity`, `undo`, `export`, and `genres` for `veto_genre` / `repoint_vetoes`) and is the only writer of `catalog_corrections`; `identity.merge_preview` answers what a merge would do without writing anything: both books through `load_work_presentation` (never raw cover/description columns) and the counts from `merge_consequences`, the same function the merge's 422 confirmation uses — each op applies its change through the services above and records its override entries and undo snapshot in the op's own transaction. `override` is a *list* of pipeline §5.4 entries because a move exports its `remove_from_series` entries before its `set_series`; a fix whose keys the next build may not hold (a heuristic work, a Google edition, a series outside any release) is recorded with `runtime_only_reason` instead. `require_librarian` (in `auth.py`) gates `api/librarian.py`: 401 anonymous, 403 for a reader.
- **`scripts/`** — standalone maintenance entrypoints run with `python -m
  scripts.<name>` (e.g. `backfill_cover_urls`, `repair_presentation`, which
  detaches editions enrichment wrongly attached and re-picks every
  representative under the language ladder). They open their own session via
  `AsyncSessionLocal` and must stay idempotent.
- **`api/`** — thin route handlers. Each module owns an `APIRouter(prefix=...)` and is wired in `main.py`.
- **`config.py`** — `Settings` (pydantic-settings) loaded from env / `.env`. `database.py` — async engine + `get_db` dependency (a session that auto-commits on success, rolls back on exception).

**Everything is async**: routes, services, and DB access use `async`/`await`. DB sessions come from `Depends(get_db)`; query with `await db.execute(select(...))` then `.scalar_one_or_none()` / `.scalars()`. The DB URL is rewritten at runtime to the `postgresql+asyncpg://` driver in both `database.py` and `alembic/env.py` — keep those two rewrites in sync.

Auth flow: register/login issue a JWT (`sub` = user id); protected routes depend on `get_current_user`, which decodes the bearer token and loads the `User`. Google OAuth uses Authlib and requires `SessionMiddleware` (already added in `main.py`).

**Password reset** (`POST /auth/forgot-password` → `/auth/reset-password`): only the token's SHA-256 hash is persisted (`password_reset_tokens`), so a leaked row can't be replayed; the raw token only exists in the emailed link. Preserve these properties when touching the flow — the forgot endpoint returns an identical response whether or not the account exists (anti-enumeration) and only issues tokens for `AuthProvider.email` accounts with a password hash, and it commits the token row *before* sending the email so a failed commit can't produce a live link. Tokens are single-use (`used_at`) and expire after `PASSWORD_RESET_TOKEN_TTL_MINUTES`.

**Works vs editions**: `books` rows are *editions* (one Google Books volume
each); `works` is what users search, discuss and shelf. `threads.work_id` and
`shelves.work_id` point at works only — never re-introduce an edition-level FK,
or discussion splits across printings again. A work's identity is
`('openlibrary', 'OL…W')` when Open Library resolved it, otherwise
`('heuristic', sha1(canonical_key))`, recorded in `identity_provenance`.
`canonical_key` is stored on *every* work, including Open Library ones: it is
how a heuristic work is later recognised as the same book and merged.
It records the key of whichever *edition* created the work, while the work's
`title` comes from Open Library — so the two legitimately disagree (*Strength
of the Strong* is stored under `the strength of the strong`, and OL titles
three different Brian Herbert books plain `Dune`, which only the edition keys
tell apart). Never "repair" that by overwriting the key from the title: it
orphans correct editions and collapses distinct books. Both forms are instead
treated as the work's identity — `identity_keys()` for reads, and
`_claim_open_library_work` / `_absorb_heuristic_twin` for lookups, so a work
is found by either. Lookups deliberately stop at a differing *primary author*;
that is a merge decision, not a lookup.
Heuristic → OL merges happen automatically; OL → OL merges never do.
Collections (box sets, omnibuses) are stored with `kind='collection'` and
filtered out of search, not dropped at ingest.

**Series** are the discussion home and a book's only page. `threads.series_id`
is the room; `threads.work_id` is an optional *book tag* inside it, and must be a
member of that series (the series endpoint canonicalizes a merged member's id and
answers a foreign one with 422). Every work has a series — a singleton of its own
when nothing better is known — and a singleton renders with no series chrome.
Detection is the franchise tag, then the broadest `series:` tag (the one most
catalog works share, name as tiebreak), then singleton. A work already in a real
series is never moved to another automatically; that is a merge decision. A
promoted singleton is tombstoned (`merged_into_id`) so its slug keeps resolving
to the survivor. `works.subjects` is stored one subject per line
(`join_subjects`), because the old space-joined form erased tag boundaries.
`assign_series` also leaves a work alone while it has an unreverted
`set_series`/`remove_from_series` correction; a dissolved series (`dissolved_at`)
is never chosen and takes no threads.

**Genres** come from a curated two-level taxonomy, `backend/app/data/genres.yaml`
(slugs are permanent; a removed entry is retired, never deleted), synced by
`python -m scripts.sync_genres`, which compose runs after migrations. Readers tag
works (never series) with up to 5 genres each; ingest, enrichment and the catalog
loader write per-source *inferences*; librarians *veto*. A work's effective genres
are the `effective_work_genres` view — readers' genres when any reader voted a
live, unvetoed genre, otherwise the inferred ones — and a subgenre rolls up into
its parent, one reader counted once. The view's SQL is one constant,
`EFFECTIVE_WORK_GENRES_VIEW` in `models/genre.py`, executed by the migration and
by a `create_all` listener: never re-derive the rule, read the view. Vetoes are
`veto_genre` corrections, runtime-only, and undo per `(work, genre)` — they never
block or wait on the book's series fixes. `works.genre_id` is gone; rooms
(`threads.genre_id`) are parent genres only, and a subgenre page shows its
parent's threads. After changing a `match`/`exclude` list, run
`python -m scripts.rebuild_work_genres --reinfer`.

A work may have **zero editions**: Open Library's search response carries
everything a work row stores, so search ingests works without touching `books`
at all, and editions only arrive when someone opens its series page. Everything
edition-derived therefore needs a fallback, which `load_work_presentation` owns:
cover is the representative edition's (verified real, and in the work's
language), then OL's curated image, then none — OL's `cover_i` is one
arbitrary printing's art, which is how an English work wore a Spanish cover;
`edition_count` is OL's total (26 for *Red Rising*) before the local row count,
because it is a fact about the book and not about our database; description is
the representative edition's before the work's, since Google's blurbs are
richer.

**Search is local-first**: `GET /api/works/search` normalizes the query and
checks `search_queries`. On a miss it calls Open Library's `search.json` once
(5s timeout — a cold search blocks a real person), turns each doc into a `Work`
row, and records the query; the row means the catalog already holds everything
upstream would return, so every later search for it makes no HTTP call at all
(TTL 30 days). Every search, cold or warm, is then answered by a Postgres
full-text query over the generated `works.search_doc` column, ranked
`ts_rank_cd(...) * (1 + ln(1 + readinglog_count))` — popularity multiplies the
text match rather than adding to it, so a famous but irrelevant book cannot
outrank a relevant one. Subjects are indexed at weight C (title A, author B),
which is what keeps a series sibling like *Iron Gold* findable by "red rising".
Google Books is never on the search path: it is the degraded fallback when Open
Library is down (and then the query is deliberately *not* recorded, so the next
search retries), and otherwise runs only from `enrichment.py`. `search_doc` is
declared twice on purpose — in the model for `create_all` in tests, and in the
migration for the real database — and the two expressions must stay identical.
Filters (`genre`, repeatable; `author`; `year_from`/`year_to`) only narrow the
local query: gating and ingest stay keyed on `q`, a filter-only search is a
local browse with no upstream call, and a bad filter is refused before any. The
`author` filter reads `works.author_doc`, declared twice like `search_doc`.

`work_identity` exposes two title forms and they are not interchangeable:
`clean_title()` is the *key* (lowercased, depunctuated, feeds `canonical_key`),
`display_title()` is what a reader sees. Both strip the same edition packaging.
A heuristic work names itself from an edition, so it must use `display_title`.

**Upgrading a pre-works database** is a three-step sequence, in this order:
`alembic upgrade 0c433c23eda9` (adds `works`), then
`python -m scripts.resolve_works` (gives every edition a work — needs HTTP, so
it cannot live in a migration), then `alembic upgrade head`, which moves threads
and shelves onto those works in SQL and *refuses to run* if any edition is still
unresolved. `--upgrade` later promotes works that fell back to the heuristic
tier; it skips any whose own editions resolve to different Open Library works,
because that grouping is wrong and no single identity is right.

**Upgrading to series** is the same shape: `alembic upgrade e7b3c9d2a1f4` (adds
`series` and nullable `series_id` columns), then `python -m
scripts.backfill_series` (idempotent; re-fetches space-joined subjects from Open
Library, assigns every work a series, moves each work thread into its room), then
`alembic upgrade head`, which *refuses to run* while any work lacks a series. The
thread constraints (`ck_threads_one_home`, `ck_threads_tag_needs_series`) are
added `NOT VALID` because 10 legacy threads orphaned by the works migration have
no home; the backfill reports them and leaves them alone.

**Catalog releases** are the catalog's seed data. `python -m
scripts.load_catalog_release <folder | tag>` (service:
`services/catalog_loader.py`) verifies checksums and schema, then in one
transaction upserts series, works, editions, `series_members` and
`work_aliases` by their deterministic ids, stamping `catalog_release`. It
*adopts* runtime works the release also holds (by OL id, alias, or
`canonical_key` for heuristic works) with `merge_works`, retires runtime rooms
that emptied into the room most of their books joined, carries tagged threads
when a book changes rooms, and settles rows a newer release dropped (deleted
when unreferenced, kept when a thread or shelf points at them, merged when an
alias names a survivor). Loading a release twice is a no-op; an older one is
refused without `--force`. Runtime code never moves a work out of a release
room (`assign_series` returns early), and a search hit for an aliased OL id
lands on the alias target. A room's page orders books by sub-series, then
`series_members.position`, then `first_publish_year`.

**Email**: routes depend on `email_sender_dep`, never on a concrete sender — that's the seam tests override via `app.dependency_overrides`. `get_email_sender()` picks `SmtpEmailSender` when `SMTP_HOST` is set and `ConsoleEmailSender` (logs the link) otherwise, so local dev needs no SMTP server.

### Frontend (`frontend/src/`)
Vite + React 18 + React Router + Tailwind.
- **`api/`** — axios-based API hooks. All requests go through `api/client.js`, whose axios instance has `baseURL: '/api'`, injects the bearer token from the Zustand auth store, and clears that store on any 401 response (it does not redirect — routes/components decide what to render). `api/errors.js` exports `errorMessage()`, which normalizes both FastAPI error shapes (`detail` as a string, or a 422 array of `{msg}`) into one display string — use it instead of hand-reading `error.response.data`.
- **`store/auth.js`** — Zustand client-state store (token + user), wrapped in `persist` (localStorage key `margin-auth`). `App.jsx` calls `useMe()` on mount to revalidate the persisted token against `/auth/me` and refresh stale user data.
- **`store/librarian.js`** — persisted (`margin-librarian`) librarian UI state: `editMode` / `setEditMode`. Edit mode is sticky across pages and reloads; `?edit=1` on a series URL turns it on and is stripped from the address; `[done]` (series header) or `[done editing]` (navbar) leaves it, and so does signing out. Every surface still gates on `user.is_librarian` as well.
- React Query is the server-state layer — the `api/` modules expose `useQuery`/`useMutation` hooks; components should consume those rather than calling `client` directly.
- `vite.config.js` proxies `/api` → `http://localhost:8000` in dev.
- **Routes**: `/series/:slug` (`pages/Series.jsx`) is a book's only page and replaces the retired work page; threads live at `/series/:slug/threads/:threadId`. Legacy `/works/:id` and `/works/:id/threads/:threadId` URLs go through `WorkRedirect`, which reads the work's `series.slug` from `GET /api/works/{id}` and replaces the history entry. Link to a book with `seriesHref(work)` from `api/series.js`.

### Design system (`frontend/src/index.css` + `frontend/tailwind.config.js`)

MARGIN's visual identity is a terminal: dark, monospaced, character-gridded, and
colorized by meaning. The decisions are recorded in
[`docs/visual-identity.md`](docs/visual-identity.md) and specified in
[`docs/superpowers/specs/2026-09-23-terminal-ui-design.md`](docs/superpowers/specs/2026-09-23-terminal-ui-design.md).
Read those before changing anything visual.

- **Tokens are the only source of color.** Values live as raw `R G B` channels on
  `:root` in `index.css` and map to semantic Tailwind utilities in
  `tailwind.config.js` (so `/opacity` modifiers still work). **Never write a raw
  `zinc-*`, hex, or arbitrary color in a component** — add a token instead.
  Surfaces: `bg` → `panel` → `highlight`; borders: `line`, `line-strong`; text:
  `ink`, `ink-dim`, `ink-muted`, `ink-faint`.
- **Text tiers are a contrast contract, asserted in `src/design/tokens.test.js`.**
  `ink` (10.59:1) body · `ink-dim` (8.10:1) secondary, metadata, timestamps ·
  `ink-muted` (4.10:1) **control borders and decoration only — never
  informational text** · `ink-faint` (2.76:1) **`aria-hidden` glyphs only**.
- **Fills invert.** A filled control is `bg-accent text-bg`. White on the accent
  is 2.52:1 and fails AA, so the conventional filled button does not exist here.
- **Color means one thing each.** `accent` interactive · `path` routes and
  references · `user` people · `ok` positive · `danger` negative · `warning`
  mutated state. Nothing means anything by color alone.
- **Serif is reserved for book titles.** Everything else — including thread
  titles — is JetBrains Mono.
- **Reuse the component classes** in the `@layer components` block (`.btn-primary`,
  `.btn-secondary`, `.btn-ghost`, `.input`, `.label`, `.panel`, `.panel-title`,
  `.float`, `.prompt`, `.caret`, `.eyebrow`, `.rule`, `.alert-danger`,
  `.alert-muted`) rather than re-deriving them. Shared shells live in
  `components/` (`AuthLayout`, `VoteControl`, `PathHeader`, `StatusBar`,
  `DiagnosticFloat`, `DataTable`, `ThreadModal`).
- **Librarian components** live in `components/librarian/` (`LibrarianPanel.jsx`
  itself stays in `components/`). Any librarian surface that asks for a reason
  uses `ReasonField` (`<ReasonField kind value onChange />`): preset chips from
  `components/librarian/reasons.js` above a required textarea. A chip only
  writes text (keeping typed words as its detail); add a new action kind's
  presets to `REASONS`. In Playwright, find the field with
  `getByLabel('Reason', { exact: true })` — the `Quick reasons` group matches too.
- **Box-drawing frames and rails are CSS borders, not characters.** Only tree
  elbows (`├─`, `└─`), sort carets (`▾`/`▴`), the float marker (`■`), the
  own-genre-vote marker (`●`) and the remove-filter cross (`×`) are literal
  glyphs, and every one is `aria-hidden`.
- **Measure in `ch`**: `max-w-prose` (72ch), `max-w-table` (96ch),
  `max-w-shell` (120ch). In a monospaced layout that is the grid.
- **No new border radii, shadows, font sizes, or durations.** Corners are square
  by design; motion is `duration-fast` (120ms) or `duration-base` (180ms).
- **Layout**: dense but organized — grids, rules and dividers over floating
  cards. Book covers carry the color, so keep them large and never dim the art.
- **Before calling a screen done**, run the §36 test: if it looks like Goodreads,
  a generic SaaS dashboard, or recolored Reddit, redesign it. Book content stays
  visually dominant; voting never does.
- **No star ratings or user reviews.** This is a product decision, not an
  oversight — see `docs/visual-identity.md` §1 and `margin_spec.md`.

### Catalog pipeline (`pipeline/`)

Five stages, `fetch → select → extract → group → publish`, each reading only
the previous stage's DuckDB tables and writing `tmp_*` tables it swaps in on
success (`db.swap_in`), so a crash leaves no partial stage. The pipeline
imports only the backend's **pure** rule modules (`work_identity`,
`series_identity`, `text`) through `pipeline/_backend.py` — keep those free of
settings, HTTP and ORM imports (`tests/test_pure_imports.py` enforces it).

- **Grouping** lives in `pipeline/group/` as pure functions: author clusters,
  duplicate works, the four-rung series ladder (Wikidata → OL tags → edition
  `series` strings → title patterns), its guards (imprints, folding,
  adaptations) and nesting. Stage modules are thin DuckDB wrappers around them.
- **Rules and corrections are data**: `pipeline/rules/junk.yaml`,
  `pipeline/rules/imprints.yaml`, and `pipeline/overrides/*.yaml`. An override
  referencing anything the build does not hold fails the run.
- **Ids are deterministic** (`ids.py`, `uuid5` over `MARGIN_NS`): never change
  the namespace. Output is sorted by identity, and two runs over the same
  inputs produce byte-identical Parquet (asserted in `test_end_to_end.py`).
- **The release contract** is `pipeline/contract.py`; the loader's `COLUMNS`
  must match it (`backend/tests/test_catalog_contract.py`). Change both and
  bump `SCHEMA_VERSION` together.
- **`publish` is gated** on `pipeline/golden/series.yaml`: it refuses to write
  a release below 95% exact membership or 95% exact order.

## Conventions & gotchas

- **API prefix**: all routers are mounted under `/api` in `main.py` (each router keeps its own resource prefix, e.g. `/api/auth/login`, `/api/genres/`). This matches the frontend's axios `baseURL: '/api'` and the vite dev proxy. New routers must be `include_router(..., prefix="/api")` and registered in `main.py`. The only non-`/api` route is `GET /` (returns the app name).
- **Schema = Alembic, not `create_all`**: the schema is owned entirely by Alembic migrations in `alembic/versions/` (the initial one creates all six tables). `main.py` does **not** call `create_all` — run `alembic upgrade head` (compose does this automatically before uvicorn). After changing a model, autogenerate a migration and review it.
- **Enum drops in migrations**: SQLAlchemy `Enum` columns implicitly `CREATE TYPE` on upgrade but autogenerate does **not** drop the type on downgrade, which breaks re-upgrade ("type already exists"). When a migration adds an enum, add an explicit `sa.Enum(name='...').drop(op.get_bind(), checkfirst=True)` in `downgrade()` (see the initial migration for the pattern).
- **Async DB URL rewrite**: the `postgresql+asyncpg://` driver rewrite is duplicated in `database.py` and `alembic/env.py` — keep both in sync.

## Known remaining gaps

- **No token revocation**: `POST /auth/logout` is a stateless acknowledgement — the frontend just clears the persisted JWT, and a stolen token stays valid until expiry (`ACCESS_TOKEN_EXPIRE_MINUTES`, default 30). A password reset does not invalidate existing sessions either. Anything relying on server-side session invalidation needs a refresh/denylist design first.
- Librarian tools cover merge/split/move/reorder/rename/remove/dissolve and genre vetoes in-app (from the series page in edit mode, which can also add a book, as a move; merge also from search results via `select`);
  `python -m scripts.export_overrides` writes them to
  `pipeline/overrides/z-librarian.yaml`, which a person reviews and commits.
  Librarians are granted with `python -m scripts.grant_librarian`. Merge and
  split cannot be undone, and there is no role system beyond the flag. Genre
  vetoes are runtime-only (the pipeline has no genre overrides). The genre
  taxonomy has no in-app editor: the YAML file is the editor.
- Content is immutable (no edit/delete for threads or posts). See `ROADMAP.md` for the tracked list.

## Environment

Backend reads env vars (see `backend/.env.example` and the `backend` service in `docker-compose.yml`):

- Core: `DATABASE_URL`, `SECRET_KEY`, `APP_NAME`
- OAuth (optional): `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`
- Book data: `GOOGLE_BOOKS_BASE_URL`, `GOOGLE_BOOKS_API_KEY` (optional; keyless fallback), `OPEN_LIBRARY_BASE_URL`
- Email (optional — no `SMTP_HOST` means reset links are logged, not sent): `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_USE_TLS`, `MAIL_FROM`
- Password reset: `FRONTEND_BASE_URL` (base of the emailed link), `PASSWORD_RESET_TOKEN_TTL_MINUTES`
- Sessions: `ACCESS_TOKEN_EXPIRE_MINUTES` (JWT lifetime; default 30)
