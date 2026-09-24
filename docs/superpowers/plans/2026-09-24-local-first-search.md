# Local-First Search Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Answer every book search from the local database, filling it from Open Library once per novel query, and demote Google Books to lazy edition enrichment behind the work page.

**Architecture:** `GET /api/works/search` normalizes the query and checks a new `search_queries` table. On a miss it calls Open Library's `search.json` once, turns each returned doc straight into a `Work` row (cover id, popularity counts, subjects, genre), and records the query. Every search — cold or warm — is then answered by a Postgres full-text query over `works.search_doc`, ranked by text match times popularity. Google Books is called only when a work page is opened for the first time, to attach editions and descriptions.

**Tech Stack:** FastAPI, SQLAlchemy 2.0 (async), Pydantic v2, Alembic, PostgreSQL (`tsvector` + GIN), httpx, pytest + respx, React 18 + Vitest.

**Spec:** `docs/superpowers/specs/2026-09-24-local-first-search-design.md`

## Global Constraints

- **Everything is async.** Routes, services and DB access use `async`/`await`. Query with `await db.execute(select(...))` then `.scalar_one_or_none()` / `.scalars()`.
- **Never hit the network in tests.** Google Books and Open Library are mocked with `respx`. A test that makes a real request is a broken test.
- **Tests build the schema with `Base.metadata.create_all`, not Alembic.** Any column added to a model must therefore be expressible in SQLAlchemy — including the generated `tsvector` column — *and* separately written into a migration. Both are required; neither substitutes for the other.
- **Layering is one-way.** `services/` contains no FastAPI types. `api/` route handlers stay thin. Never expose ORM models directly; responses go through `schemas/`.
- **`open_library.py` never raises.** Every upstream failure degrades to an empty result. Preserve this.
- **Enum drops in migrations:** if a migration adds a SQLAlchemy `Enum`, `downgrade()` must explicitly `sa.Enum(name='...').drop(op.get_bind(), checkfirst=True)`. (No new enums in this plan, but the rule stands if one is added.)
- **Alembic head is `a03fcabf38e0`.** The one new migration in this plan sets `down_revision = 'a03fcabf38e0'`.
- **Frontend colors come only from tokens.** Never write a raw `zinc-*`, hex, or arbitrary color in a component. Reuse the `@layer components` classes.
- **Ranking formula, verbatim from the spec:** `ts_rank_cd(search_doc, query) * (1 + ln(1 + readinglog_count))`, tiebreak `ol_edition_count desc, first_publish_year asc`. The multiplier bottoms out at `1.0`, never `0`.
- **Google's cover placeholder is exactly `content-type: image/png` AND `content-length: 9103`.** Both conditions must hold to reject.
- **Open Library's search timeout is 5s**, tighter than the 10s the identity resolvers use, because a cold search blocks a real person. Past it, fall back to Google.
- **Query TTL is 30 days.** A `search_queries` row older than this is refetched.
- **Commit after every task.** Run the relevant tests before each commit.

## File Structure

**Backend — create:**
| File | Responsibility |
|---|---|
| `app/models/search_query.py` | The `search_queries` table: which queries have been resolved upstream |
| `app/services/covers.py` | Cover-URL verification only — rejects Google's placeholder |
| `app/services/search.py` | Search orchestration: query gating, ingest, local ranked query |
| `app/services/enrichment.py` | Lazy Google Books enrichment of a work's editions |
| `alembic/versions/<rev>_local_first_search.py` | One migration for all schema changes |
| `scripts/backfill_covers.py` | Idempotent repair of the 211 existing works |

**Backend — modify:**
| File | Change |
|---|---|
| `app/services/open_library.py` | `OLWork` gains cover/popularity/subject fields; new `search_works()`, `cover_url()`, `genre_slug()` |
| `app/models/work.py` | Seven new columns + GIN index |
| `app/models/__init__.py` | Register `SearchQuery` so `Base.metadata` stays complete |
| `app/services/works.py` | New `upsert_work_from_ol()`; `load_work_presentation()` precedence |
| `app/api/works.py` | `search_works` delegates to `services/search.py`; `get_work` triggers enrichment |

**Frontend — modify:** `src/components/WorkCard.jsx`, `src/pages/Work.jsx`, `src/components/WorkCard.test.jsx`

---

### Task 1: Open Library search client

Open Library becomes the ingest source. `_FIELDS` is shared with the existing ISBN and title+author resolvers, so widening it also enriches those paths for free — no extra HTTP calls anywhere.

**Files:**
- Modify: `backend/app/services/open_library.py`
- Test: `backend/tests/test_open_library.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces:
  - `OLWork` dataclass gains `cover_id: int | None`, `readinglog_count: int`, `ratings_count: int`, `subjects: tuple[str, ...]`
  - `async def search_works(query: str, limit: int = 20) -> list[OLWork]`
  - `def cover_url(cover_id: int | None, size: str = "L") -> str | None`
  - `def genre_slug(subjects: Sequence[str]) -> str | None`

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_open_library.py`:

```python
SEARCH_DOCS = [
    {
        "key": "/works/OL17076473W",
        "title": "Red Rising",
        "author_name": ["Pierce Brown"],
        "first_publish_year": 2014,
        "edition_count": 26,
        "isbn": ["9780345539809"],
        "cover_i": 7316188,
        "readinglog_count": 1036,
        "ratings_count": 102,
        "subject": ["franchise:Red Rising", "genre:science fiction", "Dystopia"],
    },
    {
        "key": "/works/OL19726995W",
        "title": "Iron Gold",
        "author_name": ["Pierce Brown"],
        "first_publish_year": 2018,
        "edition_count": 14,
        "cover_i": 14511722,
        "readinglog_count": 114,
        "subject": ["franchise:Red Rising", "series:Red Rising Saga"],
    },
]


@respx.mock
async def test_search_works_maps_covers_popularity_and_subjects():
    respx.get(SEARCH_URL).mock(return_value=Response(200, json={"docs": SEARCH_DOCS}))
    works = await ol.search_works("red rising")
    assert [w.key for w in works] == ["OL17076473W", "OL19726995W"]
    first = works[0]
    assert first.cover_id == 7316188
    assert first.readinglog_count == 1036
    assert first.ratings_count == 102
    assert "genre:science fiction" in first.subjects


@respx.mock
async def test_search_works_preserves_open_library_relevance_order():
    # Ranking is Open Library's job on ingest; we must not re-sort here.
    respx.get(SEARCH_URL).mock(
        return_value=Response(200, json={"docs": list(reversed(SEARCH_DOCS))})
    )
    works = await ol.search_works("red rising")
    assert [w.key for w in works] == ["OL19726995W", "OL17076473W"]


@respx.mock
async def test_search_works_returns_empty_on_upstream_failure():
    # The never-raise contract: a search must still succeed when OL is down.
    respx.get(SEARCH_URL).mock(return_value=Response(503))
    assert await ol.search_works("red rising") == []


@respx.mock
async def test_search_works_returns_empty_on_timeout():
    # A cold search blocks a real person, so it gives up at _SEARCH_TIMEOUT
    # and lets the caller fall back rather than waiting out a 12s spike.
    respx.get(SEARCH_URL).mock(side_effect=httpx.ReadTimeout("slow"))
    assert await ol.search_works("red rising") == []


@respx.mock
async def test_search_works_uses_the_shorter_search_timeout():
    respx.get(SEARCH_URL).mock(return_value=Response(200, json={"docs": SEARCH_DOCS}))
    assert ol._SEARCH_TIMEOUT < ol._TIMEOUT
    assert await ol.search_works("red rising")


@respx.mock
async def test_search_works_skips_docs_with_no_key_or_title():
    respx.get(SEARCH_URL).mock(
        return_value=Response(200, json={"docs": [{"title": "No Key"}, SEARCH_DOCS[0]]})
    )
    works = await ol.search_works("red rising")
    assert [w.key for w in works] == ["OL17076473W"]


@respx.mock
async def test_search_works_defaults_missing_counts_to_zero():
    doc = {"key": "/works/OL1W", "title": "Bare", "author_name": ["X"]}
    respx.get(SEARCH_URL).mock(return_value=Response(200, json={"docs": [doc]}))
    work = (await ol.search_works("bare"))[0]
    assert work.readinglog_count == 0
    assert work.ratings_count == 0
    assert work.cover_id is None
    assert work.subjects == ()


def test_cover_url_builds_an_open_library_url():
    assert ol.cover_url(7316188) == "https://covers.openlibrary.org/b/id/7316188-L.jpg"
    assert ol.cover_url(None) is None


def test_genre_slug_prefers_an_explicit_genre_tag():
    assert ol.genre_slug(["Fiction", "genre:science fiction"]) == "science-fiction"


def test_genre_slug_falls_back_to_a_plain_subject():
    assert ol.genre_slug(["Fantasy", "Dragons"]) == "fantasy"


def test_genre_slug_returns_none_when_nothing_matches():
    assert ol.genre_slug(["Dragons", "Swords"]) is None
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd backend
DATABASE_URL=postgresql+asyncpg://margin:margin@localhost:5432/margin_test \
  pytest tests/test_open_library.py -v
```

Expected: FAIL — `AttributeError: module 'app.services.open_library' has no attribute 'search_works'`.

- [ ] **Step 3: Widen `_FIELDS` and `OLWork`**

In `backend/app/services/open_library.py`, replace the `_FIELDS` constant and the `OLWork` dataclass:

```python
# Widened for search ingest. These fields cost nothing extra — Open Library
# returns them in the same response the identity resolvers already make.
_FIELDS = (
    "key,title,author_name,first_publish_year,edition_count,isbn,"
    "cover_i,readinglog_count,ratings_count,subject"
)


@dataclass(frozen=True)
class OLWork:
    """One Open Library work, reduced to what MARGIN stores."""

    key: str  # bare id, e.g. "OL17076473W"
    title: str
    author: str | None
    first_publish_year: int | None
    edition_count: int
    isbn_13s: frozenset[str]
    cover_id: int | None = None
    readinglog_count: int = 0
    ratings_count: int = 0
    subjects: tuple[str, ...] = ()
```

Then extend `_to_work` to populate them — keep the existing early return intact:

```python
def _to_work(doc: dict[str, Any]) -> OLWork | None:
    key = (doc.get("key") or "").rsplit("/", 1)[-1]
    title = doc.get("title")
    if not key or not title:
        return None
    authors = doc.get("author_name") or []
    isbns = {normalize_isbn(raw) for raw in (doc.get("isbn") or [])}
    return OLWork(
        key=key,
        title=title,
        author=authors[0] if authors else None,
        first_publish_year=doc.get("first_publish_year"),
        edition_count=doc.get("edition_count") or 0,
        isbn_13s=frozenset(i for i in isbns if i),
        cover_id=doc.get("cover_i"),
        readinglog_count=doc.get("readinglog_count") or 0,
        ratings_count=doc.get("ratings_count") or 0,
        subjects=tuple(doc.get("subject") or ()),
    )
```

- [ ] **Step 4: Add `search_works`, `cover_url` and `genre_slug`**

Append to `backend/app/services/open_library.py`:

First give `_search` an overridable timeout — it currently hardcodes `_TIMEOUT`.
Change its signature and its client construction only; leave the body's
never-raise behaviour untouched:

```python
async def _search(
    params: dict[str, Any], timeout: float = _TIMEOUT
) -> list[dict[str, Any]]:
    """GET /search.json, returning docs. Any failure yields an empty list."""
    url = f"{settings.OPEN_LIBRARY_BASE_URL}/search.json"
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
```

Then append:

```python
# A cold search blocks a real person, so it gets a tighter budget than identity
# resolution does. Open Library answers in ~2s typically but has been seen to
# spike past 12s; past this ceiling the caller falls back to Google rather than
# making someone wait.
_SEARCH_TIMEOUT = 5.0


# Open Library's own relevance ranking is the thing we came for, so the docs
# are mapped in place and never re-sorted here. Ranking happens later, locally,
# in services/search.py.
async def search_works(query: str, limit: int = 20) -> list[OLWork]:
    """Full-text search for works. Returns [] on any upstream failure."""
    if not query.strip():
        return []
    docs = await _search(
        {"q": query, "fields": _FIELDS, "limit": limit}, timeout=_SEARCH_TIMEOUT
    )
    return [w for w in (_to_work(d) for d in docs) if w is not None]


def cover_url(cover_id: int | None, size: str = "L") -> str | None:
    """Build the Open Library cover URL for a cover id. Sizes are S, M, L."""
    if not cover_id:
        return None
    return f"https://covers.openlibrary.org/b/id/{cover_id}-{size}.jpg"


def genre_slug(subjects: Sequence[str]) -> str | None:
    """Map Open Library subject tags onto a seeded Genre slug.

    OL tags genres explicitly (``genre:science fiction``), which is strictly
    better than the substring guessing Google's free-text categories force. An
    explicit tag wins; plain subjects are a fallback for works that lack one.
    """
    # Imported here rather than at module scope: google_books already imports
    # from this module's neighbours, and the slug table is shared data, not a
    # dependency on Google.
    from app.services.google_books import _CATEGORY_SLUGS

    tagged = [s[len("genre:"):] for s in subjects if s.lower().startswith("genre:")]
    for pool in (tagged, list(subjects)):
        blob = " ".join(pool).lower()
        for needle, slug in _CATEGORY_SLUGS:
            if needle in blob:
                return slug
    return None
```

- [ ] **Step 5: Run the tests to verify they pass**

```bash
cd backend
DATABASE_URL=postgresql+asyncpg://margin:margin@localhost:5432/margin_test \
  pytest tests/test_open_library.py -v
```

Expected: PASS, including the pre-existing tests — widening `_FIELDS` must not break `resolve_by_isbns` or `resolve_by_title_author`.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/open_library.py backend/tests/test_open_library.py
git commit -m "feat(api): open library work search with covers and popularity"
```

---

### Task 2: Schema — work columns, `search_queries`, migration

**Files:**
- Modify: `backend/app/models/work.py`
- Create: `backend/app/models/search_query.py`
- Modify: `backend/app/models/__init__.py`
- Create: `backend/alembic/versions/<rev>_local_first_search.py`
- Test: `backend/tests/test_work_model.py`

**Interfaces:**
- Consumes: nothing from Task 1.
- Produces:
  - `Work.ol_cover_id: int | None`, `Work.readinglog_count: int`, `Work.ratings_count: int`, `Work.ol_edition_count: int`, `Work.description: str | None`, `Work.enriched_at: datetime | None`, `Work.subjects: str | None`, `Work.search_doc` (generated `TSVECTOR`)
  - `SearchQuery` model with `id: UUID`, `normalized_query: str` (unique), `resolved_at: datetime`, `result_count: int`

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_work_model.py`:

```python
import uuid
from datetime import datetime, timezone

from sqlalchemy import select, text

from app.models import SearchQuery, Work, WorkKind, WorkProvenance, WorkSource


def _work(**kw):
    base = dict(
        source=WorkSource.openlibrary,
        external_id=f"OL{uuid.uuid4().hex[:8]}W",
        canonical_key="red rising\x1fpierce brown",
        title="Red Rising",
        author="Pierce Brown",
        kind=WorkKind.single,
        identity_provenance=WorkProvenance.isbn,
    )
    base.update(kw)
    return Work(**base)


async def test_new_work_columns_default_to_zero_and_null(db_session):
    work = _work()
    db_session.add(work)
    await db_session.flush()
    assert work.readinglog_count == 0
    assert work.ratings_count == 0
    assert work.ol_edition_count == 0
    assert work.ol_cover_id is None
    assert work.description is None
    assert work.enriched_at is None
    assert work.subjects is None


async def test_search_doc_is_generated_from_title_author_and_subjects(db_session):
    work = _work(subjects="franchise:Red Rising genre:science fiction")
    db_session.add(work)
    await db_session.flush()
    await db_session.refresh(work)
    doc = (
        await db_session.execute(
            select(Work.search_doc).where(Work.id == work.id)
        )
    ).scalar_one()
    assert "rising" in doc
    assert "brown" in doc
    assert "franchis" in doc  # stemmed


async def test_search_doc_matches_a_tsquery(db_session):
    db_session.add(_work())
    await db_session.flush()
    found = (
        await db_session.execute(
            select(Work.title).where(
                Work.search_doc.op("@@")(
                    text("plainto_tsquery('english', 'red rising')")
                )
            )
        )
    ).scalars().all()
    assert found == ["Red Rising"]


async def test_search_doc_finds_a_series_sibling_through_its_subjects(db_session):
    # The regression the subjects index exists to prevent: Iron Gold must be
    # findable by "red rising" even though neither word is in its title.
    db_session.add(
        _work(
            title="Iron Gold",
            canonical_key="iron gold\x1fpierce brown",
            subjects="franchise:Red Rising series:Red Rising Saga",
        )
    )
    await db_session.flush()
    found = (
        await db_session.execute(
            select(Work.title).where(
                Work.search_doc.op("@@")(
                    text("plainto_tsquery('english', 'red rising')")
                )
            )
        )
    ).scalars().all()
    assert found == ["Iron Gold"]


async def test_search_query_rows_are_unique_on_normalized_query(db_session):
    db_session.add(
        SearchQuery(
            normalized_query="red rising",
            resolved_at=datetime.now(timezone.utc),
            result_count=8,
        )
    )
    await db_session.flush()
    row = (
        await db_session.execute(
            select(SearchQuery).where(SearchQuery.normalized_query == "red rising")
        )
    ).scalar_one()
    assert row.result_count == 8
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd backend
DATABASE_URL=postgresql+asyncpg://margin:margin@localhost:5432/margin_test \
  pytest tests/test_work_model.py -v
```

Expected: FAIL — `ImportError: cannot import name 'SearchQuery' from 'app.models'`.

- [ ] **Step 3: Add the columns to `Work`**

In `backend/app/models/work.py`, extend the imports:

```python
from sqlalchemy import (
    Computed, DateTime, Enum, ForeignKey, Index, Integer, String, Text,
    UniqueConstraint, text,
)
from sqlalchemy.dialects.postgresql import TSVECTOR
```

Replace `__table_args__` with the version that adds the GIN index:

```python
    __table_args__ = (
        UniqueConstraint("source", "external_id", name="uq_works_source_external_id"),
        Index("ix_works_search_doc", "search_doc", postgresql_using="gin"),
    )
```

Then add these columns after `genre_id` and before `merged_into_id`:

```python
    # --- Open Library presentation and ranking data -------------------------
    # Cover precedence inverts here: OL's librarian-curated image wins over
    # Google's, which serves a placeholder PNG at HTTP 200 for metadata-only
    # records and so cannot be trusted.
    ol_cover_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # OL's edition total (26 for Red Rising), which is a fact about the book
    # and independent of how many editions we happen to have ingested.
    ol_edition_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0"), default=0
    )
    readinglog_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0"), default=0
    )
    ratings_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0"), default=0
    )
    # Space-joined OL subject tags. Indexed at weight C so a series sibling
    # (Iron Gold, tagged `franchise:Red Rising`) is findable by the series
    # name — without this the local index returns fewer results than the
    # upstream call that filled it.
    subjects: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Work-level description, filled by lazy enrichment. A work can exist with
    # zero editions, so it cannot always be read through a representative.
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    enriched_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Generated, not maintained in Python: the database is the only writer, so
    # it can never drift from title/author/subjects. Declared here (not only in
    # the migration) because tests build the schema with create_all.
    search_doc: Mapped[str] = mapped_column(
        TSVECTOR,
        Computed(
            "setweight(to_tsvector('english', coalesce(title, '')), 'A') || "
            "setweight(to_tsvector('english', coalesce(author, '')), 'B') || "
            "setweight(to_tsvector('english', coalesce(subjects, '')), 'C')",
            persisted=True,
        ),
        nullable=False,
    )
```

- [ ] **Step 4: Create the `SearchQuery` model**

Create `backend/app/models/search_query.py`:

```python
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Integer, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class SearchQuery(Base):
    """A query that has already been resolved against Open Library.

    This row is what makes search local: its presence means the catalog
    already holds everything upstream would return for this query, so the
    request is answered from Postgres and no HTTP call is made. A query is
    paid for once, by one user, and every later search for it is free.
    """

    __tablename__ = "search_queries"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    # Normalized with google_books.normalize so "Red Rising" and "red  rising"
    # are one row.
    normalized_query: Mapped[str] = mapped_column(
        Text, nullable=False, unique=True, index=True
    )
    resolved_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    result_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
```

- [ ] **Step 5: Register the model**

In `backend/app/models/__init__.py`, add the import after the `work` import and
the name to `__all__`. This is what keeps `Base.metadata` complete, which is
what makes `create_all` build the table in tests:

```python
from app.models.work import Work, WorkKind, WorkProvenance, WorkSource
from app.models.search_query import SearchQuery

__all__ = [
    "Base",
    "User",
    "AuthProvider",
    "Genre",
    "Book",
    "Shelf",
    "ShelfStatus",
    "Thread",
    "Post",
    "Vote",
    "PasswordResetToken",
    "Work",
    "WorkKind",
    "WorkProvenance",
    "WorkSource",
    "SearchQuery",
]
```

- [ ] **Step 6: Run the model tests to verify they pass**

```bash
cd backend
DATABASE_URL=postgresql+asyncpg://margin:margin@localhost:5432/margin_test \
  pytest tests/test_work_model.py -v
```

Expected: PASS.

- [ ] **Step 7: Write the migration**

Create `backend/alembic/versions/d4e9b21c6f07_local_first_search.py`:

```python
"""local-first search: work ranking columns and search_queries

Revision ID: d4e9b21c6f07
Revises: a03fcabf38e0
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "d4e9b21c6f07"
down_revision: Union[str, None] = "a03fcabf38e0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SEARCH_DOC = (
    "setweight(to_tsvector('english', coalesce(title, '')), 'A') || "
    "setweight(to_tsvector('english', coalesce(author, '')), 'B') || "
    "setweight(to_tsvector('english', coalesce(subjects, '')), 'C')"
)


def upgrade() -> None:
    op.add_column("works", sa.Column("ol_cover_id", sa.Integer(), nullable=True))
    op.add_column(
        "works",
        sa.Column("ol_edition_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "works",
        sa.Column("readinglog_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "works",
        sa.Column("ratings_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column("works", sa.Column("subjects", sa.Text(), nullable=True))
    op.add_column("works", sa.Column("description", sa.Text(), nullable=True))
    op.add_column(
        "works", sa.Column("enriched_at", sa.DateTime(timezone=True), nullable=True)
    )
    # Generated column: Postgres maintains it, so it can never drift.
    op.add_column(
        "works",
        sa.Column(
            "search_doc",
            postgresql.TSVECTOR(),
            sa.Computed(_SEARCH_DOC, persisted=True),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_works_search_doc", "works", ["search_doc"], postgresql_using="gin"
    )

    op.create_table(
        "search_queries",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("normalized_query", sa.Text(), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("result_count", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_search_queries_normalized_query",
        "search_queries",
        ["normalized_query"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_search_queries_normalized_query", table_name="search_queries")
    op.drop_table("search_queries")
    op.drop_index("ix_works_search_doc", table_name="works")
    for column in (
        "search_doc",
        "enriched_at",
        "description",
        "subjects",
        "ratings_count",
        "readinglog_count",
        "ol_edition_count",
        "ol_cover_id",
    ):
        op.drop_column("works", column)
```

- [ ] **Step 8: Verify the migration round-trips**

```bash
cd /Users/kevintoledo/projects/marginalia
docker compose exec backend alembic upgrade head
docker compose exec backend alembic downgrade -1
docker compose exec backend alembic upgrade head
```

Expected: all three succeed. The second upgrade is the one that catches a
downgrade that failed to clean up.

- [ ] **Step 9: Commit**

```bash
git add backend/app/models/ backend/alembic/versions/ backend/tests/test_work_model.py
git commit -m "feat(api): add work ranking columns and search_queries table"
```

---

### Task 3: Build works from Open Library docs

Turns an `OLWork` into a `Work` row. Identity is unchanged: `uq_works_source_external_id` means an OL doc for `OL17076473W` finds the existing row rather than duplicating it, and `_absorb_heuristic_twin` folds a matching heuristic work in.

**Files:**
- Modify: `backend/app/services/works.py`
- Test: `backend/tests/test_work_resolution.py`

**Interfaces:**
- Consumes: `OLWork` (Task 1), the new `Work` columns (Task 2).
- Produces: `async def upsert_work_from_ol(db: AsyncSession, ol: OLWork) -> Work`

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_work_resolution.py`:

```python
import uuid

from sqlalchemy import select

from app.models import Genre, Work, WorkKind, WorkProvenance, WorkSource
from app.services.open_library import OLWork
from app.services.works import upsert_work_from_ol


def ol_work(**kw):
    base = dict(
        key="OL17076473W",
        title="Red Rising",
        author="Pierce Brown",
        first_publish_year=2014,
        edition_count=26,
        isbn_13s=frozenset({"9780345539809"}),
        cover_id=7316188,
        readinglog_count=1036,
        ratings_count=102,
        subjects=("franchise:Red Rising", "genre:science fiction"),
    )
    base.update(kw)
    return OLWork(**base)


async def test_upsert_creates_a_work_with_cover_popularity_and_subjects(db_session):
    work = await upsert_work_from_ol(db_session, ol_work())
    assert work.source is WorkSource.openlibrary
    assert work.external_id == "OL17076473W"
    assert work.title == "Red Rising"
    assert work.ol_cover_id == 7316188
    assert work.readinglog_count == 1036
    assert work.ratings_count == 102
    assert work.ol_edition_count == 26
    assert "franchise:Red Rising" in work.subjects
    assert work.identity_provenance is WorkProvenance.isbn


async def test_upsert_is_idempotent_on_the_open_library_key(db_session):
    first = await upsert_work_from_ol(db_session, ol_work())
    second = await upsert_work_from_ol(db_session, ol_work())
    assert first.id == second.id
    rows = (await db_session.execute(select(Work))).scalars().all()
    assert len(rows) == 1


async def test_upsert_refreshes_popularity_on_an_existing_work(db_session):
    await upsert_work_from_ol(db_session, ol_work(readinglog_count=10))
    work = await upsert_work_from_ol(db_session, ol_work(readinglog_count=1036))
    assert work.readinglog_count == 1036


async def test_upsert_assigns_a_genre_from_the_open_library_subject_tag(db_session):
    genre = Genre(name="Science Fiction", slug="science-fiction")
    db_session.add(genre)
    await db_session.flush()
    work = await upsert_work_from_ol(db_session, ol_work())
    assert work.genre_id == genre.id


async def test_upsert_absorbs_a_matching_heuristic_work(db_session):
    from app.services.work_identity import canonical_key, heuristic_external_id

    key = canonical_key("Red Rising", "Pierce Brown")
    twin = Work(
        source=WorkSource.heuristic,
        external_id=heuristic_external_id(key),
        canonical_key=key,
        title="Red Rising",
        author="Pierce Brown",
        kind=WorkKind.single,
        identity_provenance=WorkProvenance.heuristic,
    )
    db_session.add(twin)
    await db_session.flush()

    work = await upsert_work_from_ol(db_session, ol_work())
    await db_session.refresh(twin)
    assert twin.merged_into_id == work.id


async def test_upsert_marks_a_box_set_as_a_collection(db_session):
    work = await upsert_work_from_ol(
        db_session, ol_work(key="OL99W", title="Red Rising Series 5 Books Collection Set")
    )
    assert work.kind is WorkKind.collection
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd backend
DATABASE_URL=postgresql+asyncpg://margin:margin@localhost:5432/margin_test \
  pytest tests/test_work_resolution.py -v -k upsert
```

Expected: FAIL — `ImportError: cannot import name 'upsert_work_from_ol'`.

- [ ] **Step 3: Implement `upsert_work_from_ol`**

Add to `backend/app/services/works.py`, after `_upsert_work`. Add `Genre` to the
existing `from app.models import ...` line first.

```python
async def upsert_work_from_ol(db: AsyncSession, ol: OLWork) -> Work:
    """Create or refresh the work an Open Library search doc describes.

    Unlike ``_upsert_work``, this needs no edition: Open Library's search
    response carries everything a work row stores, so a work can exist with
    zero ``books`` rows until someone opens its page.
    """
    author = ol.author or "Unknown"
    key = canonical_key(ol.title, author)

    existing = (
        await db.execute(
            select(Work).where(
                Work.source == WorkSource.openlibrary, Work.external_id == ol.key
            )
        )
    ).scalar_one_or_none()

    work = await canonical_work(db, existing) if existing is not None else None

    if work is None:
        work = Work(
            source=WorkSource.openlibrary,
            external_id=ol.key,
            canonical_key=key,
            title=ol.title,
            author=author,
            first_publish_year=ol.first_publish_year,
            kind=WorkKind(classify_kind(ol.title)),
            # An OL search hit is an authority's own match for the query, the
            # same standard tier 1 applies to an ISBN lookup.
            identity_provenance=WorkProvenance.isbn,
        )
        db.add(work)
        await db.flush()
        await _absorb_heuristic_twin(db, work)

    # Refreshed on every ingest: popularity drifts upward over time, and a
    # cover can appear on a work that had none.
    work.ol_cover_id = ol.cover_id or work.ol_cover_id
    work.ol_edition_count = ol.edition_count
    work.readinglog_count = ol.readinglog_count
    work.ratings_count = ol.ratings_count
    work.subjects = " ".join(ol.subjects) or None

    if work.genre_id is None and ol.subjects:
        slug = ol_genre_slug(ol.subjects)
        if slug:
            work.genre_id = (
                await db.execute(select(Genre.id).where(Genre.slug == slug))
            ).scalar_one_or_none()

    await db.flush()
    return work
```

Extend the module's existing Open Library import so both names are available:

```python
from app.services.open_library import OLWork, genre_slug as ol_genre_slug
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
cd backend
DATABASE_URL=postgresql+asyncpg://margin:margin@localhost:5432/margin_test \
  pytest tests/test_work_resolution.py -v
```

Expected: PASS, including the pre-existing edition-first resolution tests.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/works.py backend/tests/test_work_resolution.py
git commit -m "feat(api): build works directly from open library search docs"
```

---

### Task 4: Local ranked search

**Files:**
- Create: `backend/app/services/search.py`
- Test: `backend/tests/test_search_local.py`

**Interfaces:**
- Consumes: `Work` columns (Task 2).
- Produces: `async def search_local(db: AsyncSession, query: str, limit: int = 20) -> list[Work]`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_search_local.py`:

```python
import uuid

from app.models import Work, WorkKind, WorkProvenance, WorkSource
from app.services.search import search_local


def make_work(title, author="Pierce Brown", **kw):
    base = dict(
        source=WorkSource.openlibrary,
        external_id=f"OL{uuid.uuid4().hex[:8]}W",
        canonical_key=f"{title.lower()}\x1f{author.lower()}",
        title=title,
        author=author,
        kind=WorkKind.single,
        identity_provenance=WorkProvenance.isbn,
    )
    base.update(kw)
    return Work(**base)


async def test_search_local_finds_a_work_by_title(db_session):
    db_session.add(make_work("Red Rising"))
    await db_session.flush()
    found = await search_local(db_session, "red rising")
    assert [w.title for w in found] == ["Red Rising"]


async def test_famous_work_outranks_an_obscure_one_with_the_same_title(db_session):
    db_session.add(make_work("Red Rising", "Renee Joiner", readinglog_count=8))
    db_session.add(make_work("Red Rising", "Pierce Brown", readinglog_count=1036))
    await db_session.flush()
    found = await search_local(db_session, "red rising")
    assert [w.author for w in found] == ["Pierce Brown", "Renee Joiner"]


async def test_an_irrelevant_famous_work_does_not_surface(db_session):
    db_session.add(make_work("Dune", "Frank Herbert", readinglog_count=4402))
    db_session.add(make_work("Red Rising", "Pierce Brown", readinglog_count=1036))
    await db_session.flush()
    found = await search_local(db_session, "red rising")
    assert [w.title for w in found] == ["Red Rising"]


async def test_a_series_sibling_is_found_through_its_subjects(db_session):
    db_session.add(
        make_work("Iron Gold", subjects="franchise:Red Rising series:Red Rising Saga")
    )
    await db_session.flush()
    found = await search_local(db_session, "red rising")
    assert [w.title for w in found] == ["Iron Gold"]


async def test_a_title_match_outranks_a_subject_only_match(db_session):
    # Weight A over weight C: the book you named beats its series siblings.
    db_session.add(make_work("Iron Gold", subjects="franchise:Red Rising"))
    db_session.add(make_work("Red Rising"))
    await db_session.flush()
    found = await search_local(db_session, "red rising")
    assert [w.title for w in found] == ["Red Rising", "Iron Gold"]


async def test_zero_readers_still_ranks_by_text_match(db_session):
    # The multiplier bottoms out at 1.0; it must never zero the text rank.
    db_session.add(make_work("Red Rising", readinglog_count=0))
    db_session.add(make_work("Unrelated Book", "Someone", readinglog_count=0))
    await db_session.flush()
    found = await search_local(db_session, "red rising")
    assert [w.title for w in found] == ["Red Rising"]


async def test_collections_are_excluded(db_session):
    db_session.add(make_work("Red Rising Collection Set", kind=WorkKind.collection))
    db_session.add(make_work("Red Rising"))
    await db_session.flush()
    found = await search_local(db_session, "red rising")
    assert [w.title for w in found] == ["Red Rising"]


async def test_merged_tombstones_are_excluded(db_session):
    target = make_work("Red Rising")
    db_session.add(target)
    await db_session.flush()
    tombstone = make_work("Red Rising", "Duplicate", merged_into_id=target.id)
    db_session.add(tombstone)
    await db_session.flush()
    found = await search_local(db_session, "red rising")
    assert [w.author for w in found] == ["Pierce Brown"]


async def test_blank_query_returns_nothing(db_session):
    db_session.add(make_work("Red Rising"))
    await db_session.flush()
    assert await search_local(db_session, "   ") == []
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd backend
DATABASE_URL=postgresql+asyncpg://margin:margin@localhost:5432/margin_test \
  pytest tests/test_search_local.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.search'`.

- [ ] **Step 3: Implement `search_local`**

Create `backend/app/services/search.py`:

```python
"""Search orchestration: the database answers, Open Library fills it.

Every query is served from local ``works`` rows. Open Library is consulted at
most once per distinct query — see ``search`` — which is what makes its ~2s
response affordable: the cost is paid once, by one user, and amortized across
every later search for the same term.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Work, WorkKind

_DEFAULT_LIMIT = 20


async def search_local(
    db: AsyncSession, query: str, limit: int = _DEFAULT_LIMIT
) -> list[Work]:
    """Rank the local catalog against a query.

    ``ts_rank_cd`` scores the text match across the weighted document (title A,
    author B, subjects C); popularity multiplies it. Popularity is a multiplier
    rather than an addend so a famous but irrelevant book cannot outrank a
    relevant one — Dune does not surface for "red rising". The multiplier
    bottoms out at 1.0, so a work Open Library reports no readers for is still
    ranked by its text match rather than collapsed to zero.
    """
    if not query.strip():
        return []

    tsquery = func.plainto_tsquery("english", query)
    score = func.ts_rank_cd(Work.search_doc, tsquery) * (
        1 + func.ln(1 + Work.readinglog_count)
    )

    stmt = (
        select(Work)
        .where(
            Work.search_doc.op("@@")(tsquery),
            Work.kind == WorkKind.single,
            Work.merged_into_id.is_(None),
        )
        .order_by(
            score.desc(),
            Work.ol_edition_count.desc(),
            Work.first_publish_year.asc().nulls_last(),
        )
        .limit(limit)
    )
    return list((await db.execute(stmt)).scalars().all())
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
cd backend
DATABASE_URL=postgresql+asyncpg://margin:margin@localhost:5432/margin_test \
  pytest tests/test_search_local.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/search.py backend/tests/test_search_local.py
git commit -m "feat(api): rank the local catalog by text match times popularity"
```

---

### Task 5: Query gating, ingest, and route wiring

The task that makes search local. A query is resolved upstream once; afterwards
the database answers it alone.

**Files:**
- Modify: `backend/app/services/search.py`
- Modify: `backend/app/api/works.py:100-129`
- Test: `backend/tests/test_search.py`

**Interfaces:**
- Consumes: `search_local` (Task 4), `upsert_work_from_ol` (Task 3), `open_library.search_works` (Task 1), `SearchQuery` (Task 2).
- Produces: `async def search(db: AsyncSession, query: str, limit: int = 20) -> list[Work]`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_search.py`:

```python
import respx
from httpx import Response
from sqlalchemy import select

from app.models import SearchQuery, Work

OL_URL = "https://openlibrary.org/search.json"
GOOGLE_URL = "https://www.googleapis.com/books/v1/volumes"

DOCS = [
    {
        "key": "/works/OL17076473W",
        "title": "Red Rising",
        "author_name": ["Pierce Brown"],
        "first_publish_year": 2014,
        "edition_count": 26,
        "cover_i": 7316188,
        "readinglog_count": 1036,
        "ratings_count": 102,
        "subject": ["franchise:Red Rising", "genre:science fiction"],
    },
    {
        "key": "/works/OL19726995W",
        "title": "Iron Gold",
        "author_name": ["Pierce Brown"],
        "first_publish_year": 2018,
        "edition_count": 14,
        "cover_i": 14511722,
        "readinglog_count": 114,
        "subject": ["franchise:Red Rising", "series:Red Rising Saga"],
    },
]


@respx.mock
async def test_cold_query_ingests_from_open_library(client, db_session):
    route = respx.get(OL_URL).mock(return_value=Response(200, json={"docs": DOCS}))
    resp = await client.get("/api/works/search", params={"q": "red rising"})
    assert resp.status_code == 200
    titles = [w["title"] for w in resp.json()]
    assert titles == ["Red Rising", "Iron Gold"]
    assert route.call_count == 1


@respx.mock
async def test_cold_query_returns_covers_from_open_library(client):
    respx.get(OL_URL).mock(return_value=Response(200, json={"docs": DOCS}))
    resp = await client.get("/api/works/search", params={"q": "red rising"})
    covers = [w["cover_url"] for w in resp.json()]
    assert covers[0] == "https://covers.openlibrary.org/b/id/7316188-L.jpg"
    assert all(covers)


@respx.mock
async def test_repeat_query_makes_zero_upstream_calls_and_keeps_order(client):
    route = respx.get(OL_URL).mock(return_value=Response(200, json={"docs": DOCS}))
    first = await client.get("/api/works/search", params={"q": "red rising"})
    second = await client.get("/api/works/search", params={"q": "Red  Rising"})
    # Normalization collapses the two spellings onto one search_queries row.
    assert route.call_count == 1
    # The series must not vanish on the second search — the regression the
    # subjects index exists to prevent.
    assert [w["title"] for w in second.json()] == [w["title"] for w in first.json()]


@respx.mock
async def test_search_records_the_resolved_query(client, db_session):
    respx.get(OL_URL).mock(return_value=Response(200, json={"docs": DOCS}))
    await client.get("/api/works/search", params={"q": "Red Rising"})
    row = (
        await db_session.execute(
            select(SearchQuery).where(SearchQuery.normalized_query == "red rising")
        )
    ).scalar_one()
    assert row.result_count == 2


@respx.mock
async def test_open_library_failure_falls_back_to_google(client, db_session):
    respx.get(OL_URL).mock(return_value=Response(503))
    respx.get(GOOGLE_URL).mock(
        return_value=Response(
            200,
            json={
                "items": [
                    {
                        "id": "g1",
                        "volumeInfo": {
                            "title": "Red Rising",
                            "authors": ["Pierce Brown"],
                        },
                    }
                ]
            },
        )
    )
    resp = await client.get("/api/works/search", params={"q": "red rising"})
    assert resp.status_code == 200
    assert [w["title"] for w in resp.json()] == ["Red Rising"]


@respx.mock
async def test_open_library_failure_does_not_record_the_query(client, db_session):
    # Not recording means the next search retries upstream rather than being
    # permanently stuck with a degraded result set.
    respx.get(OL_URL).mock(return_value=Response(503))
    respx.get(GOOGLE_URL).mock(return_value=Response(200, json={"items": []}))
    await client.get("/api/works/search", params={"q": "red rising"})
    rows = (await db_session.execute(select(SearchQuery))).scalars().all()
    assert rows == []


@respx.mock
async def test_stale_query_is_refetched(client, db_session):
    from datetime import datetime, timedelta, timezone

    route = respx.get(OL_URL).mock(return_value=Response(200, json={"docs": DOCS}))
    await client.get("/api/works/search", params={"q": "red rising"})
    row = (await db_session.execute(select(SearchQuery))).scalar_one()
    row.resolved_at = datetime.now(timezone.utc) - timedelta(days=31)
    await db_session.flush()

    await client.get("/api/works/search", params={"q": "red rising"})
    assert route.call_count == 2


@respx.mock
async def test_ingest_does_not_duplicate_works_across_queries(client, db_session):
    respx.get(OL_URL).mock(return_value=Response(200, json={"docs": DOCS}))
    await client.get("/api/works/search", params={"q": "red rising"})
    await client.get("/api/works/search", params={"q": "iron gold"})
    works = (await db_session.execute(select(Work))).scalars().all()
    assert len(works) == 2
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd backend
DATABASE_URL=postgresql+asyncpg://margin:margin@localhost:5432/margin_test \
  pytest tests/test_search.py -v
```

Expected: FAIL — `ImportError: cannot import name 'search' from 'app.services.search'`.

- [ ] **Step 3: Implement the gating and ingest**

Add to `backend/app/services/search.py` — extend the imports first:

```python
from datetime import datetime, timedelta, timezone

import httpx

from app.models import SearchQuery, Work, WorkKind
from app.services import google_books, open_library
from app.services.google_books import normalize
from app.services.works import resolve_editions, upsert_work_from_ol
```

Then append:

```python
# How long a resolved query stays trusted. Long, because a book's identity does
# not change; the ceiling exists so a growing Open Library eventually reaches
# queries resolved when it was thinner.
_QUERY_TTL = timedelta(days=30)


async def _is_fresh(db: AsyncSession, normalized: str) -> bool:
    row = (
        await db.execute(
            select(SearchQuery).where(SearchQuery.normalized_query == normalized)
        )
    ).scalar_one_or_none()
    if row is None:
        return False
    return datetime.now(timezone.utc) - row.resolved_at < _QUERY_TTL


async def _record(db: AsyncSession, normalized: str, count: int) -> None:
    row = (
        await db.execute(
            select(SearchQuery).where(SearchQuery.normalized_query == normalized)
        )
    ).scalar_one_or_none()
    if row is None:
        db.add(
            SearchQuery(
                normalized_query=normalized,
                resolved_at=datetime.now(timezone.utc),
                result_count=count,
            )
        )
    else:
        row.resolved_at = datetime.now(timezone.utc)
        row.result_count = count
    await db.flush()


async def _ingest_from_google(db: AsyncSession, query: str) -> None:
    """Degraded path: Open Library is down, so fall back to the old pipeline.

    Deliberately does not record a search_queries row — the query must be
    retried upstream next time rather than be permanently stuck with whatever
    Google's weaker recall produced.
    """
    # Imported here to keep api/works.py's edition upsert as the single owner
    # of that logic.
    from app.api.works import _upsert_editions

    try:
        results = await google_books.search_books(query)
    except (httpx.HTTPStatusError, httpx.RequestError):
        return
    editions, hints = await _upsert_editions(db, results)
    await resolve_editions(db, editions, hints)


async def search(db: AsyncSession, query: str, limit: int = _DEFAULT_LIMIT) -> list[Work]:
    """Answer a search, filling the catalog from Open Library on a cold query."""
    normalized = normalize(query)
    if not normalized:
        return []

    if not await _is_fresh(db, normalized):
        ol_works = await open_library.search_works(query, limit=limit)
        if ol_works:
            for ol in ol_works:
                await upsert_work_from_ol(db, ol)
            await _record(db, normalized, len(ol_works))
        else:
            await _ingest_from_google(db, query)

    return await search_local(db, query, limit=limit)
```

- [ ] **Step 4: Wire the route**

In `backend/app/api/works.py`, replace the body of `search_works` (lines 100-129):

```python
@router.get("/search", response_model=list[WorkOut])
async def search_works(
    q: str = Query(..., min_length=1),
    db: AsyncSession = Depends(get_db),
):
    """Answer from the local catalog, filling it from Open Library when cold.

    No upstream call happens on a query the database has already resolved, so
    the common case never leaves the process.
    """
    works = await search.search(db, q)
    return await _to_work_outs(db, works)
```

Add `from app.services import search` to the module's imports. The `httpx`
exception handler and its 503 are no longer reachable here — `search` degrades
internally rather than failing — so remove them along with the now-unused
`WorkKind`/`UUID` locals if nothing else in the module uses them. Leave
`_upsert_editions` in place: `services/search.py` and Task 8 both call it.

- [ ] **Step 5: Run the tests to verify they pass**

```bash
cd backend
DATABASE_URL=postgresql+asyncpg://margin:margin@localhost:5432/margin_test \
  pytest tests/test_search.py tests/test_works.py -v
```

Expected: PASS. `tests/test_works.py` exercises the old Google-first path and
will need its assertions updated to the new ordering — do that here rather than
deleting the tests.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/search.py backend/app/api/works.py backend/tests/
git commit -m "feat(api): answer search locally, resolve each query upstream once"
```

---

### Task 6: Presentation precedence

A work can now have zero editions, so cover, description and edition count each
need a stated fallback order.

**Files:**
- Modify: `backend/app/services/works.py:300-343`
- Test: `backend/tests/test_works.py`

**Interfaces:**
- Consumes: `Work` columns (Task 2).
- Produces: `WorkPresentation` unchanged in shape; `load_work_presentation` unchanged in signature.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_works.py`:

```python
import uuid

from app.models import Book, Work, WorkKind, WorkProvenance, WorkSource
from app.services.works import load_work_presentation


def bare_work(**kw):
    base = dict(
        source=WorkSource.openlibrary,
        external_id=f"OL{uuid.uuid4().hex[:8]}W",
        canonical_key="red rising\x1fpierce brown",
        title="Red Rising",
        author="Pierce Brown",
        kind=WorkKind.single,
        identity_provenance=WorkProvenance.isbn,
    )
    base.update(kw)
    return Work(**base)


async def test_cover_prefers_open_library_over_the_representative_edition(db_session):
    work = bare_work(ol_cover_id=7316188)
    db_session.add(work)
    await db_session.flush()
    edition = Book(
        source="google_books",
        external_id="g1",
        title="Red Rising",
        author="Pierce Brown",
        work_id=work.id,
        cover_url="https://books.google.com/placeholder",
    )
    db_session.add(edition)
    await db_session.flush()
    work.representative_book_id = edition.id
    await db_session.flush()

    got = await load_work_presentation(db_session, [work.id])
    assert got[work.id].cover_url == "https://covers.openlibrary.org/b/id/7316188-L.jpg"


async def test_cover_falls_back_to_the_edition_when_open_library_has_none(db_session):
    work = bare_work()
    db_session.add(work)
    await db_session.flush()
    edition = Book(
        source="google_books",
        external_id="g2",
        title="Red Rising",
        author="Pierce Brown",
        work_id=work.id,
        cover_url="https://books.google.com/real.jpg",
    )
    db_session.add(edition)
    await db_session.flush()
    work.representative_book_id = edition.id
    await db_session.flush()

    got = await load_work_presentation(db_session, [work.id])
    assert got[work.id].cover_url == "https://books.google.com/real.jpg"


async def test_a_work_with_no_editions_still_presents(db_session):
    work = bare_work(ol_cover_id=7316188, ol_edition_count=26, description="A boy.")
    db_session.add(work)
    await db_session.flush()

    got = await load_work_presentation(db_session, [work.id])
    assert got[work.id].cover_url == "https://covers.openlibrary.org/b/id/7316188-L.jpg"
    assert got[work.id].description == "A boy."
    assert got[work.id].edition_count == 26


async def test_edition_count_prefers_open_librarys_total(db_session):
    # OL knows Red Rising has 26 editions; we have ingested one.
    work = bare_work(ol_edition_count=26)
    db_session.add(work)
    await db_session.flush()
    db_session.add(
        Book(
            source="google_books",
            external_id="g3",
            title="Red Rising",
            author="Pierce Brown",
            work_id=work.id,
        )
    )
    await db_session.flush()

    got = await load_work_presentation(db_session, [work.id])
    assert got[work.id].edition_count == 26


async def test_edition_count_falls_back_to_the_local_count(db_session):
    work = bare_work(ol_edition_count=0)
    db_session.add(work)
    await db_session.flush()
    db_session.add(
        Book(
            source="google_books",
            external_id="g4",
            title="Red Rising",
            author="Pierce Brown",
            work_id=work.id,
        )
    )
    await db_session.flush()

    got = await load_work_presentation(db_session, [work.id])
    assert got[work.id].edition_count == 1


async def test_description_prefers_the_enriched_edition(db_session):
    work = bare_work(description="Short OL blurb.")
    db_session.add(work)
    await db_session.flush()
    edition = Book(
        source="google_books",
        external_id="g5",
        title="Red Rising",
        author="Pierce Brown",
        work_id=work.id,
        description="A richer Google blurb.",
    )
    db_session.add(edition)
    await db_session.flush()
    work.representative_book_id = edition.id
    await db_session.flush()

    got = await load_work_presentation(db_session, [work.id])
    assert got[work.id].description == "A richer Google blurb."
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd backend
DATABASE_URL=postgresql+asyncpg://margin:margin@localhost:5432/margin_test \
  pytest tests/test_works.py -v -k "cover or edition_count or description or no_editions"
```

Expected: FAIL — the OL cover is ignored and `edition_count` reports the local count.

- [ ] **Step 3: Rewrite `load_work_presentation`**

Replace the function in `backend/app/services/works.py`:

```python
async def load_work_presentation(
    db: AsyncSession, work_ids: Sequence[UUID]
) -> dict[UUID, WorkPresentation]:
    """Fetch cover, description and edition count for many works in one query.

    Each field has a fallback order, because a work may have no editions at all
    once Open Library becomes the ingest source:

    * cover — OL's curated image, then the representative edition's, then none.
      OL wins because Google serves a placeholder PNG at HTTP 200 for
      metadata-only records, so its URL cannot be trusted on its own.
    * description — the representative edition's, then the work's. Google's
      edition blurbs are richer than OL's, so an enriched edition wins.
    * edition count — OL's total, then the local row count. OL knows Red Rising
      has 26 editions while we may have ingested none, and the number is shown
      as a fact about the book, not about our database.

    Kept out of the routes so both ``api/works.py`` and ``api/genres.py`` build
    the same shape, and out of the schema layer so nothing lazy-loads a
    relationship mid-serialization (MissingGreenlet).
    """
    if not work_ids:
        return {}

    representative = Book.__table__.alias("representative")
    counts = (
        select(Book.work_id, func.count(Book.id).label("n"))
        .where(Book.work_id.in_(work_ids))
        .group_by(Book.work_id)
        .subquery()
    )
    stmt = (
        select(
            Work.id,
            Work.ol_cover_id,
            representative.c.cover_url,
            representative.c.description,
            Work.description,
            Work.ol_edition_count,
            func.coalesce(counts.c.n, 0),
        )
        .outerjoin(representative, Work.representative_book_id == representative.c.id)
        .outerjoin(counts, counts.c.work_id == Work.id)
        .where(Work.id.in_(work_ids))
    )
    rows = (await db.execute(stmt)).all()
    return {
        row[0]: WorkPresentation(
            cover_url=ol_cover_url(row[1]) or row[2],
            description=row[3] or row[4],
            edition_count=row[5] or row[6],
        )
        for row in rows
    }
```

Extend the Open Library import line added in Task 3:

```python
from app.services.open_library import (
    OLWork,
    cover_url as ol_cover_url,
    genre_slug as ol_genre_slug,
)
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
cd backend
DATABASE_URL=postgresql+asyncpg://margin:margin@localhost:5432/margin_test \
  pytest tests/test_works.py tests/test_genre_works.py -v
```

Expected: PASS. `test_genre_works.py` consumes the same function, so it is the
check that the shared shape survived.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/works.py backend/tests/test_works.py
git commit -m "feat(api): prefer open library covers and edition totals"
```

---

### Task 7: Cover verification

Isolated because it is the only thing in the codebase that cares what bytes a
cover URL returns, and Task 8 is its only caller.

**Files:**
- Create: `backend/app/services/covers.py`
- Test: `backend/tests/test_covers.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `async def verify(urls: Sequence[str]) -> set[str]`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_covers.py`:

```python
import respx
from httpx import Response

from app.services.covers import verify

REAL = "https://books.google.com/books/content?id=vSCbAwAAQBAJ"
FAKE = "https://books.google.com/books/content?id=5tDS0AEACAAJ"


@respx.mock
async def test_verify_rejects_googles_placeholder():
    # The live placeholder: a fixed 9103-byte PNG served at HTTP 200.
    respx.head(FAKE).mock(
        return_value=Response(
            200, headers={"content-type": "image/png", "content-length": "9103"}
        )
    )
    assert await verify([FAKE]) == set()


@respx.mock
async def test_verify_keeps_a_real_cover():
    respx.head(REAL).mock(
        return_value=Response(
            200, headers={"content-type": "image/jpeg", "content-length": "401823"}
        )
    )
    assert await verify([REAL]) == {REAL}


@respx.mock
async def test_verify_keeps_a_png_of_a_different_size():
    # Both conditions must hold; a legitimate PNG cover is not a placeholder.
    respx.head(REAL).mock(
        return_value=Response(
            200, headers={"content-type": "image/png", "content-length": "51200"}
        )
    )
    assert await verify([REAL]) == {REAL}


@respx.mock
async def test_verify_rejects_a_dead_url():
    respx.head(FAKE).mock(return_value=Response(404))
    assert await verify([FAKE]) == set()


@respx.mock
async def test_verify_rejects_on_transport_error():
    import httpx

    respx.head(FAKE).mock(side_effect=httpx.ConnectError("boom"))
    assert await verify([FAKE]) == set()


@respx.mock
async def test_verify_checks_many_urls():
    respx.head(REAL).mock(
        return_value=Response(200, headers={"content-type": "image/jpeg"})
    )
    respx.head(FAKE).mock(
        return_value=Response(
            200, headers={"content-type": "image/png", "content-length": "9103"}
        )
    )
    assert await verify([REAL, FAKE]) == {REAL}


async def test_verify_of_nothing_is_empty():
    assert await verify([]) == set()
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd backend
DATABASE_URL=postgresql+asyncpg://margin:margin@localhost:5432/margin_test \
  pytest tests/test_covers.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.covers'`.

- [ ] **Step 3: Implement `verify`**

Create `backend/app/services/covers.py`:

```python
"""Tells a real cover from Google's placeholder.

Google Books returns ``imageLinks`` for metadata-only catalog records that have
no cover, then serves a placeholder image at HTTP 200 — so nothing in the JSON
distinguishes a real cover from a missing one, and only the bytes can. The
placeholder is a fixed asset: ``image/png``, exactly 9103 bytes, where real
covers are JPEG. Both conditions must hold, so a legitimate PNG cover survives.

This costs one HEAD per URL, which is why it runs during lazy enrichment and
never on the search path.
"""

from __future__ import annotations

import asyncio
from typing import Sequence

import httpx

_TIMEOUT = 10.0
_PLACEHOLDER_TYPE = "image/png"
_PLACEHOLDER_BYTES = "9103"


async def _is_real(client: httpx.AsyncClient, url: str) -> bool:
    try:
        response = await client.head(url, follow_redirects=True)
    except httpx.RequestError:
        return False
    if response.status_code != 200:
        return False
    content_type = response.headers.get("content-type", "").split(";")[0].strip()
    length = response.headers.get("content-length", "")
    if content_type == _PLACEHOLDER_TYPE and length == _PLACEHOLDER_BYTES:
        return False
    return content_type.startswith("image/")


async def verify(urls: Sequence[str]) -> set[str]:
    """Return the subset of ``urls`` that are real cover images.

    Never raises: an unreachable cover is simply not a cover.
    """
    unique = [u for u in dict.fromkeys(urls) if u]
    if not unique:
        return set()

    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        verdicts = await asyncio.gather(*(_is_real(client, u) for u in unique))
    return {url for url, ok in zip(unique, verdicts) if ok}
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
cd backend
DATABASE_URL=postgresql+asyncpg://margin:margin@localhost:5432/margin_test \
  pytest tests/test_covers.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/covers.py backend/tests/test_covers.py
git commit -m "feat(api): reject google's placeholder cover by its bytes"
```

---

### Task 8: Lazy Google enrichment

**Files:**
- Create: `backend/app/services/enrichment.py`
- Modify: `backend/app/api/works.py:132-149`
- Test: `backend/tests/test_enrichment.py`

**Interfaces:**
- Consumes: `covers.verify` (Task 7), `Work.enriched_at` / `Work.description` (Task 2), `_upsert_editions` from `api/works.py`.
- Produces: `async def enrich_work(db: AsyncSession, work: Work) -> None`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_enrichment.py`:

```python
import uuid

import respx
from httpx import Response
from sqlalchemy import select

from app.models import Book, Work, WorkKind, WorkProvenance, WorkSource
from app.services.enrichment import enrich_work

GOOGLE_URL = "https://www.googleapis.com/books/v1/volumes"

VOLUMES = {
    "items": [
        {
            "id": "g1",
            "volumeInfo": {
                "title": "Red Rising",
                "authors": ["Pierce Brown"],
                "description": "A boy from the mines.",
                "pageCount": 400,
                "imageLinks": {"thumbnail": "http://x/real?zoom=1"},
            },
        },
        {
            "id": "g2",
            "volumeInfo": {
                "title": "Red Rising",
                "authors": ["Pierce Brown"],
                "imageLinks": {"thumbnail": "http://x/fake?zoom=1"},
            },
        },
    ]
}


async def seed(db):
    work = Work(
        source=WorkSource.openlibrary,
        external_id=f"OL{uuid.uuid4().hex[:8]}W",
        canonical_key="red rising\x1fpierce brown",
        title="Red Rising",
        author="Pierce Brown",
        kind=WorkKind.single,
        identity_provenance=WorkProvenance.isbn,
    )
    db.add(work)
    await db.flush()
    return work


def mock_google_and_covers():
    respx.get(GOOGLE_URL).mock(return_value=Response(200, json=VOLUMES))
    respx.head("https://x/real?zoom=0").mock(
        return_value=Response(200, headers={"content-type": "image/jpeg"})
    )
    respx.head("https://x/fake?zoom=0").mock(
        return_value=Response(
            200, headers={"content-type": "image/png", "content-length": "9103"}
        )
    )


@respx.mock
async def test_enrich_attaches_editions_to_the_work(db_session):
    mock_google_and_covers()
    work = await seed(db_session)
    await enrich_work(db_session, work)
    editions = (
        await db_session.execute(select(Book).where(Book.work_id == work.id))
    ).scalars().all()
    assert len(editions) == 2


@respx.mock
async def test_enrich_nulls_the_placeholder_cover(db_session):
    mock_google_and_covers()
    work = await seed(db_session)
    await enrich_work(db_session, work)
    covers = {
        b.external_id: b.cover_url
        for b in (
            await db_session.execute(select(Book).where(Book.work_id == work.id))
        ).scalars()
    }
    assert covers["g1"] == "https://x/real?zoom=0"
    assert covers["g2"] is None


@respx.mock
async def test_enrich_picks_a_representative_with_real_art(db_session):
    mock_google_and_covers()
    work = await seed(db_session)
    await enrich_work(db_session, work)
    await db_session.refresh(work)
    representative = await db_session.get(Book, work.representative_book_id)
    assert representative.external_id == "g1"


@respx.mock
async def test_enrich_sets_enriched_at(db_session):
    mock_google_and_covers()
    work = await seed(db_session)
    await enrich_work(db_session, work)
    assert work.enriched_at is not None


@respx.mock
async def test_enrich_is_a_no_op_once_enriched(db_session):
    mock_google_and_covers()
    route = respx.get(GOOGLE_URL)
    work = await seed(db_session)
    await enrich_work(db_session, work)
    await enrich_work(db_session, work)
    assert route.call_count == 1


@respx.mock
async def test_enrich_survives_a_google_outage(db_session):
    respx.get(GOOGLE_URL).mock(return_value=Response(503))
    work = await seed(db_session)
    await enrich_work(db_session, work)
    # No enriched_at, so the next open retries rather than caching a failure.
    assert work.enriched_at is None


@respx.mock
async def test_get_work_triggers_enrichment(client, db_session):
    mock_google_and_covers()
    work = await seed(db_session)
    resp = await client.get(f"/api/works/{work.id}")
    assert resp.status_code == 200
    assert resp.json()["description"] == "A boy from the mines."
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd backend
DATABASE_URL=postgresql+asyncpg://margin:margin@localhost:5432/margin_test \
  pytest tests/test_enrichment.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.enrichment'`.

- [ ] **Step 3: Implement `enrich_work`**

Create `backend/app/services/enrichment.py`:

```python
"""Fills a work's editions from Google Books, once, on first view.

Open Library ingests works but carries no description or page count, and Google
Books has both. Calling Google here rather than during search keeps its latency
and its thin quota off the path every reader hits, and gives the cover
verification somewhere to live where an extra HEAD per edition costs nothing
anyone is waiting on.
"""

from __future__ import annotations

from datetime import datetime, timezone

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Book, Work
from app.services import covers, google_books
from app.services.works import _refresh_work


async def enrich_work(db: AsyncSession, work: Work) -> None:
    """Attach Google Books editions to a work that has never been enriched.

    A no-op once ``enriched_at`` is set. On upstream failure it leaves
    ``enriched_at`` null so the next view retries, rather than caching a
    failure forever.
    """
    if work.enriched_at is not None:
        return

    query = f'intitle:"{work.title}"'
    if work.author and work.author != "Unknown":
        query += f' inauthor:"{work.author}"'

    try:
        results = await google_books.search_books(query)
    except (httpx.HTTPStatusError, httpx.RequestError):
        return

    # Imported here: api/works.py owns edition upsert, and importing it at
    # module scope would close an import cycle through the router.
    from app.api.works import _upsert_editions

    editions, _ = await _upsert_editions(db, results)
    for edition in editions:
        if edition.work_id is None:
            edition.work_id = work.id

    mine = [e for e in editions if e.work_id == work.id]
    real = await covers.verify([e.cover_url for e in mine if e.cover_url])
    for edition in mine:
        if edition.cover_url and edition.cover_url not in real:
            edition.cover_url = None

    if not work.description:
        work.description = next((e.description for e in mine if e.description), None)

    await db.flush()
    # Re-pick the representative now that placeholder covers are gone, so the
    # edition with real art wins completeness_score.
    await _refresh_work(db, work)
    work.enriched_at = datetime.now(timezone.utc)
    await db.flush()
```

- [ ] **Step 4: Wire `get_work`**

In `backend/app/api/works.py`, add `from app.services.enrichment import enrich_work`
and call it inside `get_work` before building the response:

```python
@router.get("/{work_id}", response_model=WorkOut)
async def get_work(
    work_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(get_current_user_optional),
):
    work = await _get_work_or_404(work_id, db)
    # First view pays for Google Books; every later view is local.
    await enrich_work(db, work)
    ...
```

Keep the rest of the existing handler body — shelf lookup and `_to_work_outs` —
exactly as it is.

- [ ] **Step 5: Run the tests to verify they pass**

```bash
cd backend
DATABASE_URL=postgresql+asyncpg://margin:margin@localhost:5432/margin_test \
  pytest tests/test_enrichment.py tests/test_works.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/enrichment.py backend/app/api/works.py backend/tests/test_enrichment.py
git commit -m "feat(api): enrich a work's editions from google on first view"
```

---

### Task 9: Frontend cover fallback

**Files:**
- Modify: `frontend/src/components/WorkCard.jsx:10-23`
- Modify: `frontend/src/pages/Work.jsx`
- Test: `frontend/src/components/WorkCard.test.jsx`

**Interfaces:**
- Consumes: `cover_url` from `WorkOut`, unchanged in shape.
- Produces: no new exports.

- [ ] **Step 1: Write the failing test**

In `frontend/src/components/WorkCard.test.jsx`, widen the existing import to
include `fireEvent`, then add the test as the last case inside the existing
`describe('WorkCard', ...)` block so it reuses that block's `renderCard` helper
and `work` fixture:

```jsx
import { fireEvent, render, screen } from '@testing-library/react'
```

```jsx
  it('falls back to the title when the cover fails to load', () => {
    renderCard({ ...work, cover_url: 'https://example.test/dead.jpg' })
    fireEvent.error(screen.getByRole('img', { name: 'Red Rising' }))
    expect(screen.queryByRole('img')).not.toBeInTheDocument()
    expect(screen.getAllByText('Red Rising').length).toBeGreaterThan(0)
  })
```

`getAllByText` rather than `getByText`: the fallback renders the title inside
the cover frame *and* under it, so the exact-match query finds two nodes — the
same reason the existing no-cover test uses it.

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd frontend
npm test -- WorkCard
```

Expected: FAIL — the `img` stays in the document because nothing handles `error`.

- [ ] **Step 3: Add the fallback**

In `frontend/src/components/WorkCard.jsx`, track a failure and treat it as an
absent cover. The existing placeholder branch is reused unchanged — no new
markup, no new tokens.

```jsx
import { useState } from 'react'
import { Link } from 'react-router-dom'

function WorkCard({ work }) {
  const { id, title, author, cover_url, edition_count } = work
  // A cover URL can 404 or be pulled upstream. Falling back to the same
  // placeholder the no-cover case uses keeps one visual answer for "no art"
  // rather than a broken-image glyph.
  const [coverFailed, setCoverFailed] = useState(false)
  const showCover = cover_url && !coverFailed

  return (
    <Link to={`/works/${id}`} className="group flex flex-col">
      {/* Covers carry most of the color in the UI (§13), so they stay large and
          unobstructed — the frame reacts on hover, the art never dims. */}
      <div className="aspect-[2/3] bg-panel border border-line group-hover:border-accent transition-colors duration-base overflow-hidden">
        {showCover ? (
          <img
            src={cover_url}
            alt={title}
            loading="lazy"
            onError={() => setCoverFailed(true)}
            className="w-full h-full object-cover group-hover:scale-[1.03] transition-transform duration-base"
          />
        ) : (
          <div className="w-full h-full flex items-center justify-center p-4">
            <span className="font-serif italic text-ink-dim text-xs text-center">{title}</span>
          </div>
        )}
      </div>
      <div className="pt-3 flex flex-col gap-1">
        <p className="font-serif text-ink text-sm leading-snug line-clamp-2 group-hover:text-accent transition-colors duration-fast">
          {title}
        </p>
        <p className="text-ink-dim text-xs lowercase tracking-eyebrow line-clamp-1">{author}</p>
        {/* Search collapses many editions into one card; saying so keeps the
            smaller result count legible rather than mysterious. */}
        {edition_count > 1 && (
          <p className="text-ink-dim text-xs tabular-nums">{edition_count} editions</p>
        )}
      </div>
    </Link>
  )
}

export default WorkCard
```

- [ ] **Step 4: Apply the same fallback to the work page**

In `frontend/src/pages/Work.jsx`, add the state alongside the component's
existing hooks:

```jsx
const [coverFailed, setCoverFailed] = useState(false)
```

Then replace the cover block at lines 117-123 — the existing `No Cover`
placeholder is reused unchanged, so no new markup and no new tokens:

```jsx
          {work.cover_url && !coverFailed ? (
            <img
              src={work.cover_url}
              alt={work.title}
              onError={() => setCoverFailed(true)}
              className="w-full border border-line"
            />
          ) : (
            <div className="w-full aspect-[2/3] bg-panel border border-line flex items-center justify-center text-ink-dim text-xs">
              No Cover
            </div>
          )}
```

Ensure `useState` is in the file's `react` import.

- [ ] **Step 5: Run the tests to verify they pass**

```bash
cd frontend
npm test
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/WorkCard.jsx frontend/src/components/WorkCard.test.jsx frontend/src/pages/Work.jsx
git commit -m "feat(web): fall back to the title when a cover fails to load"
```

---

### Task 10: Backfill the existing catalog

Repairs the 211 works already in the dev database. Idempotent, so it can be run
repeatedly.

**Files:**
- Create: `backend/scripts/backfill_covers.py`
- Test: `backend/tests/test_backfill_covers.py`

**Interfaces:**
- Consumes: `open_library.search_works` (Task 1), `covers.verify` (Task 7), `works._refresh_work`.
- Produces: `async def backfill(session: AsyncSession) -> dict[str, int]`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_backfill_covers.py`:

```python
import uuid

import respx
from httpx import Response

from app.models import Book, Work, WorkKind, WorkProvenance, WorkSource
from scripts.backfill_covers import backfill

OL_URL = "https://openlibrary.org/search.json"

DOC = {
    "key": "/works/OL17076473W",
    "title": "Red Rising",
    "author_name": ["Pierce Brown"],
    "edition_count": 26,
    "cover_i": 7316188,
    "readinglog_count": 1036,
    "ratings_count": 102,
    "subject": ["franchise:Red Rising"],
}


async def seed(db, **kw):
    work = Work(
        source=WorkSource.openlibrary,
        external_id="OL17076473W",
        canonical_key="red rising\x1fpierce brown",
        title="Red Rising",
        author="Pierce Brown",
        kind=WorkKind.single,
        identity_provenance=WorkProvenance.isbn,
        **kw,
    )
    db.add(work)
    await db.flush()
    return work


@respx.mock
async def test_backfill_populates_cover_and_popularity(db_session):
    respx.get(OL_URL).mock(return_value=Response(200, json={"docs": [DOC]}))
    work = await seed(db_session)
    summary = await backfill(db_session, commit=False)
    assert work.ol_cover_id == 7316188
    assert work.readinglog_count == 1036
    assert work.ol_edition_count == 26
    assert summary["works_updated"] == 1


@respx.mock
async def test_backfill_nulls_placeholder_covers(db_session):
    respx.get(OL_URL).mock(return_value=Response(200, json={"docs": [DOC]}))
    respx.head("https://x/fake").mock(
        return_value=Response(
            200, headers={"content-type": "image/png", "content-length": "9103"}
        )
    )
    work = await seed(db_session)
    edition = Book(
        source="google_books",
        external_id="g1",
        title="Red Rising",
        author="Pierce Brown",
        work_id=work.id,
        cover_url="https://x/fake",
    )
    db_session.add(edition)
    await db_session.flush()

    summary = await backfill(db_session, commit=False)
    assert edition.cover_url is None
    assert summary["covers_nulled"] == 1


@respx.mock
async def test_backfill_moves_the_representative_to_real_art(db_session):
    respx.get(OL_URL).mock(return_value=Response(200, json={"docs": [DOC]}))
    respx.head("https://x/fake").mock(
        return_value=Response(
            200, headers={"content-type": "image/png", "content-length": "9103"}
        )
    )
    respx.head("https://x/real").mock(
        return_value=Response(200, headers={"content-type": "image/jpeg"})
    )
    work = await seed(db_session)
    fake = Book(source="google_books", external_id="g1", title="Red Rising",
                author="Pierce Brown", work_id=work.id, cover_url="https://x/fake")
    real = Book(source="google_books", external_id="g2", title="Red Rising",
                author="Pierce Brown", work_id=work.id, cover_url="https://x/real")
    db_session.add_all([fake, real])
    await db_session.flush()
    work.representative_book_id = fake.id
    await db_session.flush()

    await backfill(db_session, commit=False)
    assert work.representative_book_id == real.id


@respx.mock
async def test_backfill_is_idempotent(db_session):
    respx.get(OL_URL).mock(return_value=Response(200, json={"docs": [DOC]}))
    work = await seed(db_session)
    await backfill(db_session, commit=False)
    second = await backfill(db_session, commit=False)
    assert work.ol_cover_id == 7316188
    assert second["covers_nulled"] == 0


@respx.mock
async def test_backfill_skips_heuristic_works(db_session):
    route = respx.get(OL_URL).mock(return_value=Response(200, json={"docs": [DOC]}))
    work = Work(
        source=WorkSource.heuristic,
        external_id=uuid.uuid4().hex,
        canonical_key="red rising saga\x1fpierce brown",
        title="Red Rising Saga",
        author="Pierce Brown",
        kind=WorkKind.single,
        identity_provenance=WorkProvenance.heuristic,
    )
    db_session.add(work)
    await db_session.flush()
    await backfill(db_session, commit=False)
    # Heuristic works keep their own upgrade path: resolve_works --upgrade.
    assert route.call_count == 0
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd backend
DATABASE_URL=postgresql+asyncpg://margin:margin@localhost:5432/margin_test \
  pytest tests/test_backfill_covers.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'scripts.backfill_covers'`.

- [ ] **Step 3: Implement the script**

Create `backend/scripts/backfill_covers.py`:

```python
"""One-time repair for works ingested before local-first search.

Three idempotent passes:

1. Fill ``ol_cover_id`` and the popularity counts on every Open Library work,
   by looking each one up by title and author.
2. HEAD every stored ``books.cover_url`` and null Google's placeholders.
3. Re-pick each work's representative edition, so one with real art wins.

Heuristic works are skipped — they keep their existing upgrade path,
``python -m scripts.resolve_works --upgrade``.

Run with::

    python -m scripts.backfill_covers
    # or:
    docker compose exec backend python -m scripts.backfill_covers
"""

from __future__ import annotations

import asyncio

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal
from app.models import Book, Work, WorkSource
from app.services import covers, open_library
from app.services.works import _refresh_work


async def backfill(session: AsyncSession, commit: bool = True) -> dict[str, int]:
    """Repair covers and popularity in place. Returns a summary of counts."""
    works = (
        await session.execute(
            select(Work).where(
                Work.source == WorkSource.openlibrary,
                Work.merged_into_id.is_(None),
            )
        )
    ).scalars().all()

    works_updated = 0
    for work in works:
        found = await open_library.search_works(
            f"{work.title} {work.author}", limit=5
        )
        match = next((w for w in found if w.key == work.external_id), None)
        if match is None:
            continue
        work.ol_cover_id = match.cover_id or work.ol_cover_id
        work.ol_edition_count = match.edition_count
        work.readinglog_count = match.readinglog_count
        work.ratings_count = match.ratings_count
        work.subjects = " ".join(match.subjects) or work.subjects
        works_updated += 1

    editions = (
        await session.execute(select(Book).where(Book.cover_url.is_not(None)))
    ).scalars().all()
    real = await covers.verify([e.cover_url for e in editions])

    covers_nulled = 0
    touched: set = set()
    for edition in editions:
        if edition.cover_url not in real:
            edition.cover_url = None
            covers_nulled += 1
            if edition.work_id:
                touched.add(edition.work_id)

    await session.flush()

    for work_id in touched:
        work = await session.get(Work, work_id)
        if work is not None:
            await _refresh_work(session, work)

    await session.flush()
    if commit:
        await session.commit()

    return {
        "works_scanned": len(works),
        "works_updated": works_updated,
        "covers_scanned": len(editions),
        "covers_nulled": covers_nulled,
        "representatives_repicked": len(touched),
    }


async def main() -> None:
    async with AsyncSessionLocal() as session:
        summary = await backfill(session)
    print(
        "Cover backfill complete: "
        f"{summary['works_scanned']} works scanned, "
        f"{summary['works_updated']} updated, "
        f"{summary['covers_scanned']} covers checked, "
        f"{summary['covers_nulled']} placeholders removed, "
        f"{summary['representatives_repicked']} representatives re-picked."
    )


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
cd backend
DATABASE_URL=postgresql+asyncpg://margin:margin@localhost:5432/margin_test \
  pytest tests/test_backfill_covers.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/scripts/backfill_covers.py backend/tests/test_backfill_covers.py
git commit -m "feat(api): backfill covers and popularity for existing works"
```

---

### Task 11: Full verification and documentation

**Files:**
- Modify: `CLAUDE.md`
- Modify: `ROADMAP.md`
- Modify: `frontend/e2e/` — the spec covering search

- [ ] **Step 1: Run the whole backend suite**

```bash
cd backend
DATABASE_URL=postgresql+asyncpg://margin:margin@localhost:5432/margin_test pytest -v
```

Expected: PASS. Any failure here is a real regression in a neighbouring
feature — fix it rather than adjusting the assertion to match.

- [ ] **Step 2: Run the frontend unit suite**

```bash
cd frontend
npm test
```

Expected: PASS.

- [ ] **Step 3: Apply the migration and backfill against the dev database**

```bash
cd /Users/kevintoledo/projects/marginalia
docker compose up -d --build
docker compose exec backend alembic upgrade head
docker compose exec backend python -m scripts.backfill_covers
```

Expected: the backfill prints non-zero `works_updated`, and the placeholder
count matches roughly the number of *image not available* tiles seen before.

- [ ] **Step 4: Verify the motivating search by hand**

```bash
curl -s 'http://localhost:8000/api/works/search?q=red+rising' \
  | python3 -c "import json,sys; [print(w['title'], '|', w['author'], '|', bool(w['cover_url'])) for w in json.load(sys.stdin)]"
```

Expected: *Red Rising* by Pierce Brown first, every row `True` for a cover, and
no *Osceola the Seminole*. Run it twice — the second call must be visibly
faster, because it makes no upstream request.

- [ ] **Step 5: Add an E2E search spec**

`frontend/e2e/helpers.js:38` already drives `/search?q=…` and picks the first
`a[href^="/works/"]`, so the ordering this plan changes is exactly what that
helper depends on. Create `frontend/e2e/search.spec.js`:

```js
import { expect, test } from '@playwright/test'

// Runs against the live stack and the real Open Library, so a cold database
// exercises the ingest path; a warm one exercises the local index. Both must
// produce the same first result.
test.describe('search relevance and covers', () => {
  test('puts the canonical work first and gives every result a cover', async ({ page }) => {
    await page.goto('/search?q=red%20rising')

    const results = page.locator('a[href^="/works/"]')
    await expect(results.first()).toBeVisible({ timeout: 30_000 })

    await expect(results.first()).toContainText('Red Rising')
    await expect(results.first()).toContainText('pierce brown')

    // No tile may render Google's "image not available" placeholder. Every
    // result either shows real art or the serif-title fallback — never a
    // broken or placeholder image.
    const images = results.locator('img')
    for (let i = 0; i < (await images.count()); i++) {
      const natural = await images.nth(i).evaluate((img) => img.naturalWidth)
      expect(natural).toBeGreaterThan(130)
    }
  })

  test('is fast on a repeat query, because it never leaves the database', async ({ page }) => {
    await page.goto('/search?q=red%20rising')
    await expect(page.locator('a[href^="/works/"]').first()).toBeVisible({ timeout: 30_000 })

    const started = Date.now()
    await page.goto('/search?q=red%20rising')
    await expect(page.locator('a[href^="/works/"]').first()).toBeVisible()
    expect(Date.now() - started).toBeLessThan(2_000)
  })
})
```

```bash
cd frontend
npm run test:e2e
```

- [ ] **Step 6: Update `CLAUDE.md`**

Three sections are now wrong and must be corrected:

1. **Services list** — `google_books.py` is no longer "the Google Books HTTP
   client" for search; describe it as the enrichment client. Add `search.py`
   (query gating + local ranking), `covers.py` (placeholder rejection) and
   `enrichment.py` (lazy edition fill). Describe `open_library.py` as the
   search and identity source, not identity alone.
2. **Works vs editions** — add that a work may have zero editions, that cover
   precedence is OL then representative edition, and that `edition_count`
   reports OL's total rather than a local row count.
3. **New subsection, "Search is local-first"** — a query is resolved against
   Open Library at most once, recorded in `search_queries`, and answered from
   `works.search_doc` thereafter; the subjects are indexed at weight C so
   series siblings stay findable; Google Books is never on the search path.

- [ ] **Step 7: Update `ROADMAP.md`**

Mark the cover and relevance items done, and record what this plan deliberately
left out, so it is tracked rather than forgotten: typo tolerance (`pg_trgm`),
bulk pre-seeding from an Open Library dump, and author/series pages — which the
stored `franchise:` and `series:` subject tags now make straightforward.

- [ ] **Step 8: Commit**

```bash
git add CLAUDE.md ROADMAP.md frontend/e2e/
git commit -m "docs: record local-first search; update e2e for work ordering"
```

---

## Notes for the implementer

- **`_upsert_editions` gets three callers** — `services/search.py` (degraded
  path), `services/enrichment.py`, and its own module. It stays in
  `api/works.py` and both services import it lazily inside the function to
  avoid an import cycle through the router. If it grows a fourth caller, move
  it to `services/` properly rather than adding another lazy import.
- **`tests/test_works.py` will need updating, not deleting.** It asserts the
  old Google-first ordering. The behaviour it covers is still real — it just
  arrives by a different route now.
- **The generated column is declared twice on purpose** — in the model for
  `create_all` (tests) and in the migration for the real database. They must
  stay character-identical, or a test will pass against a schema production
  does not have.
- **Do not add a `pg_trgm` index** while implementing this. It is explicitly
  out of scope in the spec; the ranking seam in `search_local` is where it
  would go later.
