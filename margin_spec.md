# MARGIN — Project Spec
> APP_NAME=MARGIN (placeholder — rename globally to swap)

## Concept
A social reading platform for serious book discussion. Think Reddit's debate culture meets Goodreads' catalog, with a modern design closer to Letterboxd. No inflated reviews, no sanitized book clubs — just honest, threaded conversation anchored to specific books and genres.

Target user: opinionated readers who currently split their time between Goodreads (catalog) and Reddit (discussion) because nothing does both well.

---

## Tech Stack

| Layer | Choice |
|---|---|
| Backend | FastAPI (Python) |
| Database | PostgreSQL |
| ORM | SQLAlchemy + Alembic (migrations) |
| Auth | Email/password + Google OAuth (via Authlib) |
| Book Data | Open Library API (https://openlibrary.org/developers/api) |
| Frontend | React (Vite) |
| Styling | Tailwind CSS |
| State | React Query (server state) + Zustand (client state) |
| Deploy | Railway (backend + DB) + Vercel (frontend) |

---

## Data Models

### User
```
id              UUID primary key
email           string unique
username        string unique
avatar_url      string nullable
auth_provider   enum (email, google)
password_hash   string nullable (null for google auth)
created_at      timestamp
```

### Book
```
id              UUID primary key
open_library_id string unique (e.g. "OL45804W")
title           string
author          string
cover_url       string nullable
description     text nullable
genre_id        UUID → Genre
published_year  integer nullable
created_at      timestamp
```

### Genre
```
id              UUID primary key
name            string (e.g. "Fantasy")
slug            string unique (e.g. "fantasy")
description     text nullable
```

### Shelf
```
id              UUID primary key
user_id         UUID → User
book_id         UUID → Book
status          enum (want_to_read, reading, read)
created_at      timestamp
updated_at      timestamp
UNIQUE (user_id, book_id)
```

### Thread
```
id              UUID primary key
title           string
user_id         UUID → User
book_id         UUID → Book nullable
genre_id        UUID → Genre nullable
-- Note: exactly one of book_id or genre_id must be set
upvotes         integer default 0
created_at      timestamp
```

### Post
```
id              UUID primary key
thread_id       UUID → Thread
user_id         UUID → User
parent_id       UUID → Post nullable
-- null = top-level post, set = reply
-- NOTE: UI enforces 2 levels max for now, but schema supports infinite nesting for future migration
content         text
upvotes         integer default 0
created_at      timestamp
updated_at      timestamp
```

---

## API Routes

### Auth
```
POST /auth/register          — email + password signup
POST /auth/login             — email + password login, returns JWT
GET  /auth/google            — redirect to Google OAuth
GET  /auth/google/callback   — handle Google OAuth callback
POST /auth/logout
GET  /auth/me                — current user info
```

### Books
```
GET  /books/search?q=        — search Open Library API, cache results in DB
GET  /books/{id}             — book detail + genre info
GET  /books/{id}/threads     — all threads for a book
POST /books/{id}/shelf       — add to user's shelf
PUT  /books/{id}/shelf       — update shelf status
DELETE /books/{id}/shelf     — remove from shelf
```

### Genres
```
GET  /genres                 — list all genres
GET  /genres/{slug}          — genre detail
GET  /genres/{slug}/books    — books in genre
GET  /genres/{slug}/threads  — threads in genre
```

### Threads
```
POST /threads                — create thread (body: title, book_id OR genre_id)
GET  /threads/{id}           — thread detail + posts
POST /threads/{id}/upvote    — upvote thread
```

### Posts
```
POST /posts                  — create post (body: thread_id, content, parent_id?)
POST /posts/{id}/upvote      — upvote post
```

### Users
```
GET  /users/{username}       — public profile + shelves
```

---

## Frontend Pages

### `/` Home
- Search bar (searches Open Library)
- List of genres
- No feed for now (no social graph yet)

### `/books/{id}` Book Page
- Cover, title, author, description (from Open Library)
- Shelf button (want to read / reading / read)
- Threads list for this book (sorted by upvotes)
- Button to start a new thread

### `/books/{id}/threads/{thread_id}` Thread Page
- Thread title + top-level posts
- Each post can have replies (2 levels max in UI)
- Upvoting on posts and replies
- Reply composer

### `/genres/{slug}` Genre Page
- Genre name + description
- Books in this genre (grid)
- Threads in this genre (sorted by upvotes)
- Button to start a new genre thread

### `/search?q=` Search Results
- Results from Open Library
- Each result links to its book page (creates DB record if first visit)

### `/profile/{username}` User Profile
- Username + avatar
- Shelves (want to read, reading, read)

### `/login` and `/register`
- Email/password forms
- Google OAuth button

---

## Project Structure

```
margin/
├── backend/
│   ├── app/
│   │   ├── main.py
│   │   ├── config.py          — env vars, settings
│   │   ├── database.py        — SQLAlchemy setup
│   │   ├── models/            — SQLAlchemy models
│   │   │   ├── user.py
│   │   │   ├── book.py
│   │   │   ├── genre.py
│   │   │   ├── shelf.py
│   │   │   ├── thread.py
│   │   │   └── post.py
│   │   ├── schemas/           — Pydantic schemas
│   │   │   ├── user.py
│   │   │   ├── book.py
│   │   │   ├── thread.py
│   │   │   └── post.py
│   │   ├── api/               — route handlers
│   │   │   ├── auth.py
│   │   │   ├── books.py
│   │   │   ├── genres.py
│   │   │   ├── threads.py
│   │   │   ├── posts.py
│   │   │   └── users.py
│   │   └── services/          — business logic
│   │       ├── open_library.py  — Open Library API client
│   │       └── auth.py          — JWT + OAuth logic
│   ├── alembic/               — migrations
│   ├── requirements.txt
│   └── .env.example
│
└── frontend/
    ├── src/
    │   ├── pages/
    │   │   ├── Home.jsx
    │   │   ├── Book.jsx
    │   │   ├── Thread.jsx
    │   │   ├── Genre.jsx
    │   │   ├── Search.jsx
    │   │   ├── Profile.jsx
    │   │   ├── Login.jsx
    │   │   └── Register.jsx
    │   ├── components/
    │   │   ├── BookCard.jsx
    │   │   ├── ThreadCard.jsx
    │   │   ├── Post.jsx
    │   │   ├── PostComposer.jsx
    │   │   ├── ShelfButton.jsx
    │   │   ├── GenreCard.jsx
    │   │   └── Navbar.jsx
    │   ├── api/               — React Query hooks
    │   │   ├── books.js
    │   │   ├── threads.js
    │   │   ├── posts.js
    │   │   └── auth.js
    │   ├── store/             — Zustand stores
    │   │   └── auth.js
    │   └── main.jsx
    ├── index.html
    ├── vite.config.js
    └── tailwind.config.js
```

---

## Multi-Agent Workstreams

When running Claude Code, split into these parallel workstreams:

**Subagent 1 — Database & Models**
- Set up SQLAlchemy + Alembic
- Implement all models (user, book, genre, shelf, thread, post)
- Write initial migration

**Subagent 2 — Auth System**
- JWT implementation
- Email/password register + login
- Google OAuth flow via Authlib
- `/auth/*` routes

**Subagent 3 — Book & Genre API**
- Open Library API client (search, fetch by ID)
- `/books/*` and `/genres/*` routes
- Shelf logic

**Subagent 4 — Discussion API**
- `/threads/*` and `/posts/*` routes
- Upvote logic
- Parent/child post logic

**Subagent 5 — Frontend Foundation**
- Vite + React + Tailwind setup
- Routing (React Router)
- Navbar, auth pages, Zustand auth store
- React Query setup

**Subagent 6 — Frontend Pages**
- Home, Search, Book, Genre, Thread, Profile pages
- All components (BookCard, Post, PostComposer, ShelfButton)
- Wire to API via React Query hooks

---

## Design Direction
- Editorial/magazine aesthetic — think a literary journal, not a social app
- Dark theme primary
- Typography-first: large, confident type for book titles and thread titles
- Muted palette with one sharp accent color (deep amber or ink blue)
- No rounded-everything — sharp edges, intentional whitespace
- Upvote counts and discussion counts are prominent — signal quality

---

## Environment Variables (.env)
```
APP_NAME=MARGIN
DATABASE_URL=postgresql://...
SECRET_KEY=...
GOOGLE_CLIENT_ID=...
GOOGLE_CLIENT_SECRET=...
OPEN_LIBRARY_BASE_URL=https://openlibrary.org
```

---

## Out of Scope for v1
- Following users / social graph
- Recommendation algorithm
- Reading progress tracking
- Notifications
- Mobile app
- Spoiler tags
- Book ratings/star system
