# MARGIN

A social reading platform for serious book discussion — Reddit-style threaded debate meets a Goodreads-style catalog, with a design closer to Letterboxd. No inflated reviews, no sanitized book clubs: just honest, threaded conversation anchored to specific books and genres.

**Target user:** opinionated readers who currently split their time between Goodreads (catalog) and Reddit (discussion) because nothing does both well.

> `margin_spec.md` is the authoritative product/design spec. The code is a functionally complete v1 MVP with a test suite and CI, but the spec still runs ahead of it in places (see [Known gaps](#known-gaps) and [`ROADMAP.md`](ROADMAP.md)).

## Tech stack

| Layer | Choice |
|---|---|
| Backend | FastAPI (async, Python) |
| Database | PostgreSQL |
| ORM / migrations | SQLAlchemy 2.0 + Alembic |
| Auth | Email/password (JWT, bcrypt) + Google OAuth (Authlib) + email password reset |
| Book data | [Open Library](https://openlibrary.org/developers/api) (search, work identity, dumps) + [Wikidata](https://www.wikidata.org/) (series) + [Google Books](https://developers.google.com/books/docs/v1/using) (edition enrichment) |
| Catalog pipeline | Python + DuckDB, publishing Parquet releases |
| Email | SMTP via `aiosmtplib` (console-logging fallback when unconfigured) |
| Frontend | React 18 (Vite) + React Router |
| Styling | Tailwind CSS on design tokens (terminal identity, see [`docs/visual-identity.md`](docs/visual-identity.md)) |
| State | React Query (server state) + Zustand (client state) |

## Quick start

Everything runs via Docker Compose from the repo root:

```bash
docker compose up --build
```

This starts three services:

| Service | URL |
|---|---|
| PostgreSQL | `localhost:5432` |
| Backend (FastAPI) | http://localhost:8000 (docs at `/docs`) |
| Frontend (Vite) | http://localhost:5173 |

Alembic migrations are applied automatically before the backend starts. The frontend proxies `/api` → `http://localhost:8000` in dev.

Useful commands:

```bash
docker compose logs -f backend     # tail backend logs
docker compose exec backend bash   # shell into the backend container
```

## Architecture

```
backend/app/
  models/    SQLAlchemy 2.0 ORM (DeclarativeBase). __init__ imports every model
             so Base.metadata is complete.
  schemas/   Pydantic v2 request/response shapes. ORM models are never exposed directly.
  services/  Business logic, no FastAPI types:
               search.py          local-first search (query gate, OL ingest, ranked FTS)
               open_library.py    OL search + work identity
               google_books.py    Google Books client, used for enrichment only
               enrichment.py      fills a work's editions/description on first view
               works.py           resolution ladder, representative edition, merge_works
               series.py          the only writer of series rows
               threads.py         thread listing and creation
               catalog_loader.py  loads a pipeline release in one transaction
               votes.py, covers.py, auth.py, email.py
               work_identity.py, series_identity.py, text.py  pure rules (shared with pipeline/)
  api/       Thin route handlers; each module owns an APIRouter, wired in main.py.
  config.py  Settings from env / .env.   database.py  Async engine + get_db.

backend/scripts/   Idempotent maintenance entrypoints (see Maintenance scripts).

pipeline/          Offline catalog build: fetch → select → extract → group → publish.
                   Never touches the app database; production only loads its releases.

frontend/src/
  api/       axios + React Query hooks; client.js sets baseURL '/api', injects the
             bearer token, and clears auth on any 401. errors.js normalizes FastAPI
             error shapes. series.js exports seriesHref(work) for linking to a book.
  store/     Zustand auth store (token + user), persisted to localStorage.
  pages/     Home, Search, Series (a book's only page), Thread, Genre, Profile,
             WorkRedirect (legacy /works/:id URLs), Login, Register,
             ForgotPassword, ResetPassword, NotFound.
  components/ Shared shells: PathHeader, StatusBar, DiagnosticFloat, DataTable,
             ThreadModal, VoteControl, WorkCard, Post, AuthLayout, …
```

The backend is **async end-to-end** — routes, services, and DB access all use `async`/`await`. All routers are mounted under `/api`; the only non-`/api` route is `GET /`.

### Core data models

- **`Work`** — a book as readers mean it; what users search, discuss and shelve. Identity is an Open Library work id when resolved, otherwise a labelled heuristic key.
- **`Book`** — an *edition* (one printing). A work may have zero editions; they arrive lazily from Google Books.
- **`Series`** — the discussion room and a book's only page. Every work has one (a singleton when nothing better is known); `SeriesMember` holds release-loaded order and sub-series, `WorkAlias` maps retired ids to survivors.
- **`Thread`** — lives in exactly one of a series room or a genre, optionally tagged with one member book. **`Post`** — two-level replies. **`Vote`** — one ±1 per user per thread/post; scores are signed.
- **`Shelf`** — a user's work with `want_to_read` / `reading` / `read`, unique per user/work.
- **`User`**, **`Genre`**, **`SearchQuery`** (queries already resolved upstream), **`CatalogRelease`**, **`PasswordResetToken`** (SHA-256 hash only, with `expires_at` / `used_at`).

### Auth & sessions

Register and login return a JWT (`sub` = user id); protected routes depend on `get_current_user`. The frontend persists `{ user, token }` to `localStorage` under `margin-auth` and revalidates it against `GET /api/auth/me` on load — a 401 from any request clears the store via an axios response interceptor. Logout is a client-side clear (the server endpoint is a stateless no-op; there is no refresh or revocation).

Password reset: `POST /auth/forgot-password` always returns the same message regardless of whether the account exists (anti-enumeration), and only issues a token for email-auth accounts. Only the token's SHA-256 hash is stored; the raw token travels in the emailed link and is single-use and time-limited (`PASSWORD_RESET_TOKEN_TTL_MINUTES`, default 30). With no `SMTP_HOST` configured, the reset link is logged to the backend console instead of emailed — that's the intended local-dev path.

### Search and the catalog

Search is **local-first**: `GET /api/works/search` checks whether the normalized query has been resolved before. On a miss it calls Open Library once, ingests the results as works and records the query (30-day TTL); every search is then answered by Postgres full-text search over `works.search_doc`, ranked by text match × popularity. Google Books never serves search — it is the fallback when Open Library is down, and otherwise only enriches a work's editions the first time its page is opened.

The bulk of the catalog comes from **releases** built offline by `pipeline/` (Open Library dumps + Wikidata → works, series, order, aliases). Loading one is a single transaction that adopts works already created at runtime, and loading it twice is a no-op. Catalog corrections are data in `pipeline/overrides/*.yaml`.

### Key API routes

```
POST   /api/auth/register | login | logout | forgot-password | reset-password
GET    /api/auth/me   /api/auth/google   /api/auth/google/callback
GET    /api/works/search?q=...          GET /api/works/{id}
POST   /api/works/{id}/shelf            PUT/DELETE /api/works/{id}/shelf
GET    /api/series/{slug}               GET/POST /api/series/{slug}/threads
GET    /api/genres/   /api/genres/{slug}   /api/genres/{slug}/works   /api/genres/{slug}/threads
POST   /api/threads/   GET /api/threads/{id}   PUT /api/threads/{id}/vote
POST   /api/posts/     PUT /api/posts/{id}/vote
GET    /api/users/{username}            (public: no email)
```

## Testing

Backend, frontend unit and pipeline tests run in CI (`.github/workflows/ci.yml`) on every push and PR; e2e runs nightly. There is no linter/formatter configured yet. Always run tests before claiming they pass.

**Backend — pytest** (async, httpx `ASGITransport`). Tests run against a separate `margin_test` database, build the schema with `Base.metadata.create_all`, and mock Open Library and Google Books with `respx` (never hit the network). Email is exercised through a fake `EmailSender` installed via `app.dependency_overrides`. From `backend/`:

```bash
docker compose up -d db
docker compose exec db psql -U margin -c "CREATE DATABASE margin_test;"   # one-time
DATABASE_URL=postgresql+asyncpg://margin:margin@localhost:5432/margin_test pytest
```

**Frontend unit — Vitest + React Testing Library** (jsdom). From `frontend/`:

```bash
npm test            # vitest run
npm run test:watch
```

**E2E — Playwright** (drives the full stack). From `frontend/`, with `docker compose up` running in another terminal:

```bash
npx playwright install   # one-time
npm run test:e2e
```

**Pipeline — pytest** over fixture dumps, no network. From `pipeline/`:

```bash
python -m venv .venv && .venv/bin/pip install -r requirements.txt   # one-time
.venv/bin/python -m pytest
```

## Migrations

The schema is owned entirely by Alembic migrations (not `create_all` at runtime). From `backend/` or `docker compose exec backend`:

```bash
alembic revision --autogenerate -m "message"
alembic upgrade head
alembic downgrade -1
```

After changing a model, autogenerate a migration and review it. When a migration adds a SQLAlchemy `Enum`, add an explicit type drop in `downgrade()` (autogenerate omits it, which breaks re-upgrade) — see the initial migration for the pattern.

## Environment

The backend reads (see `backend/.env.example` and the `backend` service in `docker-compose.yml`):

| Var | Notes |
|---|---|
| `DATABASE_URL`, `SECRET_KEY`, `APP_NAME` | Core. |
| `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` | Optional — Google OAuth. |
| `OPEN_LIBRARY_BASE_URL` | Open Library API base. |
| `GOOGLE_BOOKS_BASE_URL`, `GOOGLE_BOOKS_API_KEY` | Key is optional; the client falls back to keyless requests. |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_USE_TLS`, `MAIL_FROM` | Optional — unset `SMTP_HOST` logs reset links to the console instead of sending. |
| `FRONTEND_BASE_URL` | Base of the emailed reset link (default `http://localhost:5173`). |
| `PASSWORD_RESET_TOKEN_TTL_MINUTES` | Reset token lifetime (default 30). |

## Catalog

Build a release offline (needs ~20 GB free disk; from the repo root):

```bash
pipeline/.venv/bin/python -m pipeline run --version 2026.10.1
pipeline/.venv/bin/python -m pipeline run --from group --version 2026.10.1   # resume from a stage
```

Working state is `build/catalog.duckdb`; releases land in `releases/catalog-<version>/` (both git-ignored). `publish` refuses to write a release below 95% exact membership or order on the golden set (`pipeline/golden/series.yaml`). `--upload` attaches it to a GitHub Release.

Load a release into the app database (a folder or a release tag; an older release is refused without `--force`):

```bash
docker compose exec backend python -m scripts.load_catalog_release catalog-2026.10.1
```

## Maintenance scripts

All run as `docker compose exec backend python -m scripts.<name>` and are idempotent.

| Script | Purpose |
|---|---|
| `load_catalog_release` | Load a pipeline release (see above). |
| `resolve_works` | Give every edition a work; `--upgrade` promotes heuristic works to Open Library identities. Part of the pre-works upgrade sequence in `CLAUDE.md`. |
| `backfill_series` | Give every work a series and move work threads into their rooms. Part of the series upgrade sequence in `CLAUDE.md`. |
| `backfill_covers` | Repair covers on works ingested before local-first search. |
| `repair_presentation` | Detach wrongly-attached editions and re-pick representatives under the language ladder. |
| `backfill_cover_urls` | Upgrade legacy `cover_url` strings on `books` (https, no curl edge, full zoom). |

## Development workflow

Feature work is delegated to focused subagents in `.claude/agents/`: `backend-dev`, `frontend-dev`, `test-engineer`, `code-reviewer`. The phased feature plan lives in [`ROADMAP.md`](ROADMAP.md) (Phase 0 hardening is nearly done; librarian tools are the next designed feature). See [`CLAUDE.md`](CLAUDE.md) for conventions and gotchas.

## Known gaps

- **No token revocation** — logout clears the JWT client-side only; a stolen token stays valid until it expires. Same for password reset: existing sessions are not invalidated when the password changes.
- **Content is immutable** — no edit/delete endpoints for threads or posts.
- **No in-app catalog fixes** — merges and series corrections need `pipeline/overrides/*.yaml` or `merge_works()` from a shell until librarian tools ship.
- **Not yet built** — thread sorting/filtering, profile editing, author pages, and everything in the spec's social layer (follows, feed, notifications). See [`ROADMAP.md`](ROADMAP.md) for the tracked list.
