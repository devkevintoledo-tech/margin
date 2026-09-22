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
| Book data | [Google Books API](https://developers.google.com/books/docs/v1/using) |
| Email | SMTP via `aiosmtplib` (console-logging fallback when unconfigured) |
| Frontend | React 18 (Vite) + React Router |
| Styling | Tailwind CSS |
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
  services/  Business logic, no FastAPI types — google_books.py (HTTP client,
             search dedup, cover-URL upgrade), auth.py (JWT, bcrypt,
             get_current_user, reset-token hashing), email.py (SMTP / console sender).
  api/       Thin route handlers; each module owns an APIRouter, wired in main.py.
  config.py  Settings from env / .env.   database.py  Async engine + get_db.

backend/scripts/
  backfill_cover_urls.py   One-time, idempotent upgrade of stored cover_url strings.

frontend/src/
  api/       axios hooks; client.js sets baseURL '/api', injects the bearer token,
             and clears auth on any 401. errors.js normalizes FastAPI error shapes.
  store/     Zustand auth store (token + user), persisted to localStorage.
  pages/     Home, Login, Register, ForgotPassword, ResetPassword, Book, Genre,
             Thread, Profile, Search, NotFound.
  components/
```

The backend is **async end-to-end** — routes, services, and DB access all use `async`/`await`. All routers are mounted under `/api`; the only non-`/api` route is `GET /`.

### Core data models

`User`, `Book`, `Genre`, `Shelf` (a user's book with `want_to_read` / `reading` / `read` status, unique per user/book), `Thread` (anchored to exactly one of a book or a genre), `Post` (threaded replies), and `PasswordResetToken` (SHA-256 hash of the emailed token, plus `expires_at` / `used_at`). See `margin_spec.md` for full field definitions.

### Auth & sessions

Register and login return a JWT (`sub` = user id); protected routes depend on `get_current_user`. The frontend persists `{ user, token }` to `localStorage` under `margin-auth` and revalidates it against `GET /api/auth/me` on load — a 401 from any request clears the store via an axios response interceptor. Logout is a client-side clear (the server endpoint is a stateless no-op; there is no refresh or revocation).

Password reset: `POST /auth/forgot-password` always returns the same message regardless of whether the account exists (anti-enumeration), and only issues a token for email-auth accounts. Only the token's SHA-256 hash is stored; the raw token travels in the emailed link and is single-use and time-limited (`PASSWORD_RESET_TOKEN_TTL_MINUTES`, default 30). With no `SMTP_HOST` configured, the reset link is logged to the backend console instead of emailed — that's the intended local-dev path.

### Key API routes

```
POST   /api/auth/register | login | logout
POST   /api/auth/forgot-password   /api/auth/reset-password
GET    /api/auth/me
GET    /api/auth/google   /api/auth/google/callback
GET    /api/books/search?q=...        GET /api/books/{id}
GET    /api/books/{id}/threads
POST   /api/books/{id}/shelf  PUT/DELETE  /api/books/{id}/shelf
GET    /api/genres/   /api/genres/{slug}  /api/genres/{slug}/books  /{slug}/threads
POST   /api/threads/   GET /api/threads/{id}   POST /api/threads/{id}/upvote
POST   /api/posts/     POST /api/posts/{id}/upvote
GET    /api/users/{username}
```

## Testing

Backend and frontend unit tests run in CI (`.github/workflows/ci.yml`) on every push and PR; e2e runs nightly. There is no linter/formatter configured yet. Always run tests before claiming they pass.

**Backend — pytest** (async, httpx `ASGITransport`). Tests run against a separate `margin_test` database, build the schema with `Base.metadata.create_all`, and mock Google Books with `respx` (never hit the network). Email is exercised through a fake `EmailSender` installed via `app.dependency_overrides`. From `backend/`:

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
| `GOOGLE_BOOKS_BASE_URL`, `GOOGLE_BOOKS_API_KEY` | Key is optional; the client falls back to keyless requests. |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_USE_TLS`, `MAIL_FROM` | Optional — unset `SMTP_HOST` logs reset links to the console instead of sending. |
| `FRONTEND_BASE_URL` | Base of the emailed reset link (default `http://localhost:5173`). |
| `PASSWORD_RESET_TOKEN_TTL_MINUTES` | Reset token lifetime (default 30). |

## Maintenance scripts

```bash
docker compose exec backend python -m scripts.backfill_cover_urls
```

Upgrades `cover_url` values already stored on `books` (http→https, drop `&edge=curl`, `zoom=1`→`zoom=0`). Idempotent — running it twice is a no-op.

## Development workflow

Feature work is delegated to focused subagents in `.claude/agents/`: `backend-dev`, `frontend-dev`, `test-engineer`, `code-reviewer`. The phased feature plan lives in [`ROADMAP.md`](ROADMAP.md) (Phase 0 — test/hardening foundations — is the current focus). See [`CLAUDE.md`](CLAUDE.md) for conventions and gotchas.

## Known gaps

- **No token revocation** — logout clears the JWT client-side only; a stolen token stays valid until it expires. Same for password reset: existing sessions are not invalidated when the password changes.
- **Content is immutable** — no edit/delete endpoints for threads or posts, and upvotes only increment (no un-vote or per-user vote tracking).
- **Not yet built** — thread sorting/filtering, profile editing, and everything in the spec's social layer (follows, feed, notifications). See [`ROADMAP.md`](ROADMAP.md) for the tracked list.
