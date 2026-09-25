# Work Grouping Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make a *work* — not an edition — the thing users search, discuss and shelve, so every thread about *Red Rising* lands in one place regardless of which edition the reader found.

**Architecture:** A new `works` table sits above `books` (now editions). A work's identity is resolved from Open Library's work graph via a three-tier ladder — batched ISBN lookup, then title+author, then a labelled local heuristic — and `threads` / `shelves` move their foreign keys from `books` to `works`. Google Books remains the search and cover source.

**Tech Stack:** FastAPI, SQLAlchemy 2.0 async, Alembic, Pydantic v2, httpx, pytest + respx, React 18 + React Query, Vitest + RTL, Playwright.

**Spec:** [`docs/superpowers/specs/2026-09-23-work-grouping-design.md`](../specs/2026-09-23-work-grouping-design.md)

## Global Constraints

- **Everything is async.** Routes, services and DB access use `async`/`await`. Sessions come from `Depends(get_db)`; query with `await db.execute(select(...))` then `.scalar_one_or_none()` / `.scalars()`.
- **Never `model_validate` an ORM object whose schema reads a relationship.** It triggers a lazy load outside the greenlet (`MissingGreenlet`). Build the schema explicitly from scalar columns — see `post_out_from_orm` in `schemas/thread.py`.
- **Tests never hit the network.** Google Books *and* Open Library are mocked with `respx`.
- **Tests run against `margin_test`**, schema built by `Base.metadata.create_all`, never Alembic. Run from `backend/`: `DATABASE_URL=postgresql+asyncpg://margin:margin@localhost:5432/margin_test pytest` — or in the container: `docker compose exec -T -e DATABASE_URL=postgresql+asyncpg://margin:margin@db:5432/margin_test backend pytest`.
- **New models must be imported in `app/models/__init__.py`** so `Base.metadata` stays complete.
- **Every migration that adds an `Enum` must drop the type in `downgrade()`** with `sa.Enum(name='...').drop(op.get_bind(), checkfirst=True)`, or re-upgrade fails with "type already exists".
- **All routers are mounted under `/api`** in `main.py`, each keeping its own resource prefix.
- **Frontend colors come only from tokens.** No raw `zinc-*`, hex, or arbitrary colors. No new border radii, shadows, font sizes or durations. Serif is reserved for book titles.
- **Commit after every task.** Co-author line on every commit:
  `Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>`

## File Structure

**Created**

| File | Responsibility |
| --- | --- |
| `backend/app/services/work_identity.py` | Pure functions: title cleaning, canonical key, ISBN normalization, collection classification. No IO. |
| `backend/app/services/open_library.py` | Open Library HTTP client. Returns `OLWork` values or nothing; never raises on network failure. |
| `backend/app/services/works.py` | Resolution orchestration, work upsert, representative selection, `merge_works`. The only module that writes `works`. |
| `backend/app/models/work.py` | `Work` ORM model + its three enums. |
| `backend/app/api/works.py` | Replaces `api/books.py`: search, detail, threads, shelf. |
| `backend/scripts/resolve_works.py` | Idempotent backfill + `--upgrade` re-resolution. |
| `backend/tests/test_work_identity.py`, `test_open_library.py`, `test_work_resolution.py`, `test_works.py`, `test_resolve_works_script.py` | Coverage per layer. |
| `frontend/src/api/works.js`, `components/WorkCard.jsx`, `pages/Work.jsx` | Frontend equivalents of the book modules. |

**Modified:** `models/{book,thread,shelf,genre,__init__}.py`, `schemas/{book,thread}.py`, `api/{genres,threads,users,main}.py`, `services/google_books.py` (dedup deleted), two Alembic migrations, and the frontend files that referenced books.

**Deleted:** `backend/app/api/books.py`, `frontend/src/components/BookCard.jsx`, `frontend/src/pages/Book.jsx`, `google_books._dedup_key` / `._dedup_volumes` / `._completeness_score`.

---

## Task 1: Identity helpers (pure functions)

**Files:**
- Create: `backend/app/services/work_identity.py`
- Test: `backend/tests/test_work_identity.py`

**Interfaces:**
- Consumes: `app.services.google_books.normalize` (existing).
- Produces:
  - `clean_title(title: str) -> str` — normalized title with edition noise removed
  - `canonical_key(title: str, author: str | None) -> str` — `"<clean title>\x1f<normalized first author>"`
  - `heuristic_external_id(key: str) -> str` — 40-char sha1 hex
  - `normalize_isbn(raw: str | None) -> str | None` — separators stripped, ISBN-10 upgraded to 13
  - `classify_kind(title: str, subtitle: str | None = None) -> str` — `"single"` or `"collection"`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_work_identity.py`:

```python
import pytest

from app.services import work_identity as wi


# ---------------------------------------------------------------------------
# clean_title() — the Tier 3 fallback's entire accuracy lives here.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "raw,expected",
    [
        ("Red Rising", "red rising"),
        ("Red Rising (Deluxe Slipcase Edition)", "red rising"),
        ("Red Rising [Hardcover]", "red rising"),
        ("Red Rising 01", "red rising"),
        ("Red Rising #1", "red rising"),
        ("Red Rising, Vol. 2", "red rising"),
        ("Red Rising Book 3", "red rising"),
        ("The Hobbit: Illustrated Edition", "the hobbit"),
        ("Dune: 50th Anniversary Edition", "dune"),
    ],
)
def test_clean_title_strips_edition_noise(raw, expected):
    assert wi.clean_title(raw) == expected


@pytest.mark.parametrize(
    "raw,expected",
    [
        # A colon-separated subtitle is meaningful: this is a DIFFERENT work.
        ("Red Rising: Sons of Ares", "red rising sons of ares"),
        # A trailing number that is part of the title must survive. We only
        # strip a trailing volume number <= 20 that leaves >= 2 tokens behind.
        ("Fahrenheit 451", "fahrenheit 451"),
        ("Catch 22", "catch 22"),
        ("Slaughterhouse 5", "slaughterhouse 5"),
        ("1984", "1984"),
    ],
)
def test_clean_title_keeps_meaningful_text(raw, expected):
    assert wi.clean_title(raw) == expected


# ---------------------------------------------------------------------------
# canonical_key() / heuristic_external_id()
# ---------------------------------------------------------------------------

def test_canonical_key_uses_clean_title_and_first_author():
    key = wi.canonical_key("Red Rising (Deluxe Slipcase Edition)", "Pierce Brown, Tim Gerard Reynolds")
    assert key == "red rising\x1fpierce brown"


def test_canonical_key_matches_across_edition_variants():
    assert wi.canonical_key("Red Rising 01", "Pierce Brown") == wi.canonical_key(
        "Red Rising (Deluxe Slipcase Edition)", "Pierce Brown"
    )


def test_canonical_key_separates_different_works_by_the_same_author():
    assert wi.canonical_key("Red Rising", "Pierce Brown") != wi.canonical_key(
        "Red Rising: Sons of Ares", "Pierce Brown"
    )


def test_heuristic_external_id_is_stable_sha1():
    key = wi.canonical_key("Red Rising", "Pierce Brown")
    assert wi.heuristic_external_id(key) == wi.heuristic_external_id(key)
    assert len(wi.heuristic_external_id(key)) == 40


# ---------------------------------------------------------------------------
# normalize_isbn() — OL returns ISBN-10 and ISBN-13 mixed in one list.
# ---------------------------------------------------------------------------

def test_normalize_isbn_upgrades_isbn_10():
    # 0345539788 is an ISBN-10 for a Red Rising edition.
    assert wi.normalize_isbn("0345539788") == "9780345539786"


def test_normalize_isbn_passes_through_isbn_13_and_strips_separators():
    assert wi.normalize_isbn("978-0-345-53980-9") == "9780345539809"
    assert wi.normalize_isbn("9780345539809") == "9780345539809"


def test_normalize_isbn_rejects_junk():
    assert wi.normalize_isbn(None) is None
    assert wi.normalize_isbn("") is None
    assert wi.normalize_isbn("12345") is None


# ---------------------------------------------------------------------------
# classify_kind() — conservative on purpose.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "title",
    [
        "Red Rising 3-Book Bundle",
        "Red Rising 1-6 ebook collection",
        "Pierce Brown's Red Rising: Sons of Ares Omnibus",
        "The Red Rising Series Collection 5 Books Set By Pierce Brown",
        "The Broken Earth Trilogy Box Set",
        "Dune Boxed Set: Books 1-6",
    ],
)
def test_classify_kind_flags_collections(title):
    assert wi.classify_kind(title) == "collection"


@pytest.mark.parametrize(
    "title",
    [
        "Red Rising",
        "Collected Fictions",       # bare "collected" must NOT match
        "The Complete Stories",     # bare "complete" must NOT match
        "Red Rising: Sons of Ares",
    ],
)
def test_classify_kind_leaves_single_works_alone(title):
    assert wi.classify_kind(title) == "single"


def test_classify_kind_reads_the_subtitle_too():
    assert wi.classify_kind("Red Rising", "The Complete Series") == "collection"
```

- [ ] **Step 2: Run the test and verify it fails**

Run: `docker compose exec -T -e DATABASE_URL=postgresql+asyncpg://margin:margin@db:5432/margin_test backend pytest tests/test_work_identity.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.work_identity'`

- [ ] **Step 3: Write the implementation**

Create `backend/app/services/work_identity.py`:

```python
"""Pure identity helpers for grouping editions into works.

No IO, no ORM — everything here is a deterministic string function so the
grouping rules can be tested exhaustively and read in one sitting. The Open
Library client (``open_library.py``) and the resolution orchestration
(``works.py``) build on top of these.
"""

from __future__ import annotations

import hashlib
import re

from app.services.google_books import normalize

# A parenthetical or bracketed group is always edition packaging:
# "(Deluxe Slipcase Edition)", "[Hardcover]".
_BRACKETED = re.compile(r"[\(\[][^\)\]]*[\)\]]")

# A trailing segment introduced by ':' or ',' that is *only* edition words.
# "The Hobbit: Illustrated Edition" loses its tail; "Red Rising: Sons of Ares"
# keeps it, which is the distinction the whole heuristic tier rests on.
_EDITION_WORDS = (
    r"deluxe|slipcase|illustrated|anniversary|revised|reprint|unabridged|"
    r"abridged|annotated|movie tie[- ]?in|collector'?s|special|expanded|"
    r"international|\d+(st|nd|rd|th)"
)
_EDITION_TAIL = re.compile(
    rf"\s*[:,]\s*(?:the\s+)?(?:{_EDITION_WORDS})[\w\s'-]*?(?:edition|printing)?\s*$",
    re.IGNORECASE,
)

# Volume markers: "Red Rising 01", "#1", "Vol. 2", "Book 3", "Part 4".
_VOLUME_MARKER = re.compile(
    r"\s*(?:,\s*)?(?:#|vol\.?|volume|book|part)?\s*(\d{1,3})\s*$",
    re.IGNORECASE,
)
_VOLUME_WORD = re.compile(r"(?:#|vol\.?|volume|book|part)\s*\d{1,3}\s*$", re.IGNORECASE)

# Highest volume number we will treat as a series marker rather than as part of
# the title. "Fahrenheit 451" and "Catch 22" survive this bound.
_MAX_VOLUME_NUMBER = 20

_COLLECTION_PATTERNS = tuple(
    re.compile(p)
    for p in (
        r"\bbox(?:ed)? set\b",
        r"\bomnibus\b",
        r"\bbundle\b",
        r"\bcollection\b",
        r"\bcomplete series\b",
        r"\bbooks? \d+\s*[-–—]\s*\d+\b",
        r"\b\d+\s*[-–—]\s*book\b",
        r"\b\d+ books\b",
    )
)


def clean_title(title: str) -> str:
    """Normalize a title with edition packaging removed.

    Deliberately does NOT drop everything after a colon — a subtitle usually
    names a different book (``Red Rising: Sons of Ares``). Only a colon-led
    tail made of edition words is dropped.
    """
    if not title:
        return ""

    working = _BRACKETED.sub(" ", title)
    working = _EDITION_TAIL.sub("", working)
    working = _strip_volume_marker(working)
    return normalize(working)


def _strip_volume_marker(title: str) -> str:
    """Drop a trailing volume number, but only when it is clearly a marker.

    A bare trailing integer is stripped only when it is <= 20 *and* at least
    two tokens remain, so ``Red Rising 01`` collapses while ``Fahrenheit 451``,
    ``Catch 22`` and ``Slaughterhouse 5`` do not. An explicit marker word
    (``Vol.``, ``Book``, ``#``) removes that bound — it is unambiguous.
    """
    if _VOLUME_WORD.search(title):
        return _VOLUME_WORD.sub("", title).rstrip(" ,:-")

    match = _VOLUME_MARKER.search(title)
    if match is None:
        return title
    if int(match.group(1)) > _MAX_VOLUME_NUMBER:
        return title
    remainder = title[: match.start()].rstrip(" ,:-")
    if len(remainder.split()) < 2:
        return title
    return remainder


def canonical_key(title: str, author: str | None) -> str:
    """Group key for a work: cleaned title + normalized first author."""
    first_author = (author or "").split(",")[0]
    return f"{clean_title(title)}\x1f{normalize(first_author)}"


def heuristic_external_id(key: str) -> str:
    """Stable synthetic id for a work with no Open Library identity."""
    return hashlib.sha1(key.encode("utf-8")).hexdigest()


def normalize_isbn(raw: str | None) -> str | None:
    """Return a 13-digit ISBN, upgrading ISBN-10s. None when unusable.

    Open Library returns both forms mixed in one work's ``isbn`` list, so every
    identifier is funnelled through here before comparison.
    """
    if not raw:
        return None
    digits = re.sub(r"[^0-9Xx]", "", raw)
    if len(digits) == 13 and digits.isdigit():
        return digits
    if len(digits) == 10:
        core = "978" + digits[:9]
        total = sum(int(d) * (1 if i % 2 == 0 else 3) for i, d in enumerate(core))
        return core + str((10 - total % 10) % 10)
    return None


def classify_kind(title: str, subtitle: str | None = None) -> str:
    """``"collection"`` for box sets, bundles and omnibuses; else ``"single"``.

    Conservative by design: bare "complete" and bare "collected" are NOT
    matched, so ``The Complete Stories`` and ``Collected Fictions`` stay
    single works. The return value matches ``WorkKind``'s enum values.
    """
    blob = normalize(f"{title or ''} {subtitle or ''}")
    if any(pattern.search(blob) for pattern in _COLLECTION_PATTERNS):
        return "collection"
    return "single"
```

- [ ] **Step 4: Run the test and verify it passes**

Run: `docker compose exec -T -e DATABASE_URL=postgresql+asyncpg://margin:margin@db:5432/margin_test backend pytest tests/test_work_identity.py -q`
Expected: PASS (all parametrized cases)

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/work_identity.py backend/tests/test_work_identity.py
git commit -m "$(cat <<'EOF'
feat(api): add work identity helpers

Title cleaning, canonical key, ISBN-10 upgrade and collection
classification as pure functions, so the grouping rules are readable
and exhaustively testable on their own.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Open Library client

**Files:**
- Create: `backend/app/services/open_library.py`
- Modify: `backend/app/config.py`, `backend/.env.example`, `docker-compose.yml`
- Test: `backend/tests/test_open_library.py`

**Interfaces:**
- Consumes: `work_identity.normalize_isbn`, `work_identity.clean_title`, `google_books.normalize`, `settings.OPEN_LIBRARY_BASE_URL`.
- Produces:
  - `OLWork` frozen dataclass: `key: str` (bare `OL17076473W`), `title: str`, `author: str | None`, `first_publish_year: int | None`, `edition_count: int`, `isbn_13s: frozenset[str]`
  - `async resolve_by_isbns(isbn_13s: Sequence[str]) -> dict[str, OLWork]` — keyed by the *requested* ISBN
  - `async resolve_by_title_author(title: str, author: str) -> OLWork | None`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_open_library.py`:

```python
import httpx
import respx
from httpx import Response

from app.services import open_library as ol

SEARCH_URL = "https://openlibrary.org/search.json"

# Shaped like the live response. Note the mixed ISBN-10 / ISBN-13 forms — this
# is real, and the reason every identifier goes through normalize_isbn().
RED_RISING_DOC = {
    "key": "/works/OL17076473W",
    "title": "Red Rising",
    "author_name": ["Pierce Brown"],
    "first_publish_year": 2014,
    "edition_count": 26,
    "isbn": ["0345539788", "9780345539809", "3453269578"],
}
GOLDEN_SON_DOC = {
    "key": "/works/OL19340986W",
    "title": "Golden Son",
    "author_name": ["Pierce Brown"],
    "first_publish_year": 2015,
    "edition_count": 21,
    "isbn": ["9781473646506"],
}


@respx.mock
async def test_resolve_by_isbns_maps_each_requested_isbn_to_its_work():
    respx.get(SEARCH_URL).mock(
        return_value=Response(200, json={"docs": [RED_RISING_DOC, GOLDEN_SON_DOC]})
    )
    got = await ol.resolve_by_isbns(["9780345539809", "9781473646506"])
    assert got["9780345539809"].key == "OL17076473W"
    assert got["9781473646506"].key == "OL19340986W"
    assert got["9780345539809"].edition_count == 26


@respx.mock
async def test_resolve_by_isbns_matches_through_an_isbn_10_in_the_work():
    # We hold the 13 form; OL lists the 10 form. They must still match.
    respx.get(SEARCH_URL).mock(return_value=Response(200, json={"docs": [RED_RISING_DOC]}))
    got = await ol.resolve_by_isbns(["9780345539786"])  # == 0345539788 upgraded
    assert got["9780345539786"].key == "OL17076473W"


@respx.mock
async def test_resolve_by_isbns_returns_empty_without_isbns():
    route = respx.get(SEARCH_URL).mock(return_value=Response(200, json={"docs": []}))
    assert await ol.resolve_by_isbns([]) == {}
    assert not route.called  # no pointless upstream call


@respx.mock
async def test_resolve_by_isbns_survives_upstream_failure():
    respx.get(SEARCH_URL).mock(return_value=Response(429, json={"error": "slow down"}))
    assert await ol.resolve_by_isbns(["9780345539809"]) == {}


@respx.mock
async def test_resolve_by_isbns_survives_network_error():
    respx.get(SEARCH_URL).mock(side_effect=httpx.ConnectError("boom"))
    assert await ol.resolve_by_isbns(["9780345539809"]) == {}


@respx.mock
async def test_resolve_by_title_author_prefers_the_work_with_more_editions():
    # Open Library itself holds duplicate works for Red Rising; the one with
    # 26 editions is the canonical one.
    duplicate = {
        "key": "/works/OL26627585W",
        "title": "Red Rising",
        "author_name": ["Pierce Brown"],
        "first_publish_year": 2014,
        "edition_count": 8,
        "isbn": [],
    }
    respx.get(SEARCH_URL).mock(
        return_value=Response(200, json={"docs": [duplicate, RED_RISING_DOC]})
    )
    work = await ol.resolve_by_title_author("Red Rising", "Pierce Brown")
    assert work is not None
    assert work.key == "OL17076473W"


@respx.mock
async def test_resolve_by_title_author_rejects_a_title_mismatch():
    respx.get(SEARCH_URL).mock(return_value=Response(200, json={"docs": [GOLDEN_SON_DOC]}))
    assert await ol.resolve_by_title_author("Red Rising", "Pierce Brown") is None


@respx.mock
async def test_resolve_by_title_author_rejects_an_author_mismatch():
    respx.get(SEARCH_URL).mock(return_value=Response(200, json={"docs": [RED_RISING_DOC]}))
    assert await ol.resolve_by_title_author("Red Rising", "Someone Else") is None


@respx.mock
async def test_resolve_by_title_author_survives_a_timeout():
    respx.get(SEARCH_URL).mock(side_effect=httpx.ReadTimeout("slow"))
    assert await ol.resolve_by_title_author("Red Rising", "Pierce Brown") is None
```

- [ ] **Step 2: Run the test and verify it fails**

Run: `docker compose exec -T -e DATABASE_URL=postgresql+asyncpg://margin:margin@db:5432/margin_test backend pytest tests/test_open_library.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.open_library'`

- [ ] **Step 3: Add the base-URL setting**

In `backend/app/config.py`, alongside `GOOGLE_BOOKS_BASE_URL`, add:

```python
    OPEN_LIBRARY_BASE_URL: str = "https://openlibrary.org"
```

In `backend/.env.example`, under the book-data section:

```
# Open Library — supplies work identity (grouping editions into one book).
OPEN_LIBRARY_BASE_URL=https://openlibrary.org
```

In `docker-compose.yml`, in the `backend` service's `environment:` block:

```yaml
      OPEN_LIBRARY_BASE_URL: ${OPEN_LIBRARY_BASE_URL:-https://openlibrary.org}
```

- [ ] **Step 4: Write the client**

Create `backend/app/services/open_library.py`:

```python
"""Open Library client — the source of *work identity*.

Google Books has no concept of a work: every edition is an unrelated volume.
Open Library models works and editions natively, so a single call can tell us
that six volumes are one book. This module only ever answers questions; it
never raises on upstream failure, because a search request must still succeed
when Open Library is down (the caller falls back to a local heuristic).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

import httpx

from app.config import settings
from app.services.google_books import normalize
from app.services.work_identity import clean_title, normalize_isbn

_TIMEOUT = 10.0
_FIELDS = "key,title,author_name,first_publish_year,edition_count,isbn"

# Solr chokes on unbounded OR clauses, and a Google Books page is 20 volumes.
_ISBN_BATCH = 20


@dataclass(frozen=True)
class OLWork:
    """One Open Library work, reduced to what identity resolution needs."""

    key: str  # bare id, e.g. "OL17076473W"
    title: str
    author: str | None
    first_publish_year: int | None
    edition_count: int
    isbn_13s: frozenset[str]


async def _search(params: dict[str, Any]) -> list[dict[str, Any]]:
    """GET /search.json, returning docs. Any failure yields an empty list."""
    url = f"{settings.OPEN_LIBRARY_BASE_URL}/search.json"
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
            return response.json().get("docs", [])
    except (httpx.HTTPStatusError, httpx.RequestError, ValueError):
        # Timeout, 429, outage, malformed body — identity resolution degrades
        # to the heuristic tier rather than failing the user's search.
        return []


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
    )


async def resolve_by_isbns(isbn_13s: Sequence[str]) -> dict[str, OLWork]:
    """Resolve many ISBNs to their works in as few calls as possible.

    Returns a mapping keyed by the *requested* ISBN. Requested ISBNs with no
    match are simply absent.
    """
    wanted = [i for i in (normalize_isbn(v) for v in isbn_13s) if i]
    if not wanted:
        return {}

    works: list[OLWork] = []
    for start in range(0, len(wanted), _ISBN_BATCH):
        chunk = wanted[start : start + _ISBN_BATCH]
        docs = await _search(
            {
                "q": "isbn:({})".format(" OR ".join(chunk)),
                "fields": _FIELDS,
                "limit": len(chunk),
            }
        )
        works.extend(w for w in (_to_work(d) for d in docs) if w)

    resolved: dict[str, OLWork] = {}
    for isbn in wanted:
        for work in works:
            if isbn in work.isbn_13s:
                resolved[isbn] = work
                break
    return resolved


async def resolve_by_title_author(title: str, author: str) -> OLWork | None:
    """Fall back to a title+author lookup for a volume with no usable ISBN.

    Accepts only an exact normalized title and first-author match. Open Library
    contains duplicate works (``Red Rising`` exists twice), so ties are broken
    on ``edition_count`` — the fuller record is the canonical one.
    """
    if not title or not author:
        return None

    docs = await _search(
        {"title": title, "author": author, "fields": _FIELDS, "limit": 5}
    )
    wanted_title = clean_title(title)
    wanted_author = normalize(author.split(",")[0])

    candidates = []
    for work in (_to_work(d) for d in docs):
        if work is None:
            continue
        if clean_title(work.title) != wanted_title:
            continue
        if normalize(work.author or "") != wanted_author:
            continue
        candidates.append(work)

    if not candidates:
        return None
    return max(candidates, key=lambda w: w.edition_count)
```

- [ ] **Step 5: Run the test and verify it passes**

Run: `docker compose exec -T -e DATABASE_URL=postgresql+asyncpg://margin:margin@db:5432/margin_test backend pytest tests/test_open_library.py -q`
Expected: PASS (9 tests)

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/open_library.py backend/tests/test_open_library.py \
        backend/app/config.py backend/.env.example docker-compose.yml
git commit -m "$(cat <<'EOF'
feat(api): add Open Library client for work identity

Batched ISBN resolution plus a title+author fallback that breaks ties
on edition_count, because Open Library holds duplicate works. Never
raises: upstream failure returns nothing so search can degrade.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: `Work` model and migration 1

**Files:**
- Create: `backend/app/models/work.py`, `backend/alembic/versions/<rev>_add_works.py`
- Modify: `backend/app/models/__init__.py`, `backend/app/models/{book,thread,shelf}.py`
- Test: `backend/tests/test_work_model.py`

**Interfaces:**
- Produces:
  - `WorkSource` (`openlibrary`, `heuristic`), `WorkKind` (`single`, `collection`), `WorkProvenance` (`isbn`, `title_author`, `heuristic`) — string enums whose values match `work_identity.classify_kind`'s return
  - `Work` with `id, source, external_id, canonical_key, title, subtitle, author, first_publish_year, kind, identity_provenance, representative_book_id, genre_id, merged_into_id, created_at, updated_at`
  - `Book.work_id`, `Thread.work_id`, `Shelf.work_id` (all nullable at this stage)

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_work_model.py`:

```python
import uuid

from sqlalchemy import select

from app.models import Book, Work, WorkKind, WorkProvenance, WorkSource


async def test_work_round_trips_with_its_editions(db_session):
    work = Work(
        source=WorkSource.openlibrary,
        external_id="OL17076473W",
        canonical_key="red rising\x1fpierce brown",
        title="Red Rising",
        author="Pierce Brown",
        first_publish_year=2014,
        kind=WorkKind.single,
        identity_provenance=WorkProvenance.isbn,
    )
    db_session.add(work)
    await db_session.flush()

    edition = Book(
        source="google_books",
        external_id=uuid.uuid4().hex[:12],
        title="Red Rising (Deluxe Slipcase Edition)",
        author="Pierce Brown",
        work_id=work.id,
    )
    db_session.add(edition)
    await db_session.flush()

    work.representative_book_id = edition.id
    await db_session.commit()

    found = (
        await db_session.execute(select(Work).where(Work.external_id == "OL17076473W"))
    ).scalar_one()
    assert found.representative_book_id == edition.id
    assert found.kind is WorkKind.single


async def test_work_identity_is_unique_per_source(db_session):
    import sqlalchemy.exc

    def make():
        return Work(
            source=WorkSource.openlibrary,
            external_id="OL17076473W",
            canonical_key="red rising\x1fpierce brown",
            title="Red Rising",
            author="Pierce Brown",
            kind=WorkKind.single,
            identity_provenance=WorkProvenance.isbn,
        )

    db_session.add(make())
    await db_session.flush()
    db_session.add(make())
    try:
        await db_session.flush()
    except sqlalchemy.exc.IntegrityError:
        return
    raise AssertionError("expected uq_works_source_external_id to reject the duplicate")
```

- [ ] **Step 2: Run the test and verify it fails**

Run: `docker compose exec -T -e DATABASE_URL=postgresql+asyncpg://margin:margin@db:5432/margin_test backend pytest tests/test_work_model.py -q`
Expected: FAIL — `ImportError: cannot import name 'Work' from 'app.models'`

- [ ] **Step 3: Write the model**

Create `backend/app/models/work.py`:

```python
import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class WorkSource(str, enum.Enum):
    """Where this work's identity came from."""

    openlibrary = "openlibrary"
    heuristic = "heuristic"


class WorkKind(str, enum.Enum):
    """Values match ``work_identity.classify_kind``'s return strings."""

    single = "single"
    collection = "collection"


class WorkProvenance(str, enum.Enum):
    """Which resolution tier produced the identity — isbn is the strongest."""

    isbn = "isbn"
    title_author = "title_author"
    heuristic = "heuristic"


class Work(Base):
    """A book as readers mean it: one work, many editions.

    ``books`` rows are editions of a work. Threads and shelves hang off the
    work, never the edition, so a discussion is never split across printings.
    """

    __tablename__ = "works"
    __table_args__ = (
        UniqueConstraint("source", "external_id", name="uq_works_source_external_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    source: Mapped[WorkSource] = mapped_column(
        Enum(WorkSource, name="work_source_enum"), nullable=False
    )
    external_id: Mapped[str] = mapped_column(String(64), nullable=False)
    # Not identity for Open Library works — the bridge that lets a heuristic
    # work be recognised as the same book once a sibling edition resolves.
    canonical_key: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    subtitle: Mapped[str | None] = mapped_column(String(500), nullable=True)
    author: Mapped[str] = mapped_column(String(500), nullable=False)
    first_publish_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    kind: Mapped[WorkKind] = mapped_column(
        Enum(WorkKind, name="work_kind_enum"), nullable=False, default=WorkKind.single
    )
    identity_provenance: Mapped[WorkProvenance] = mapped_column(
        Enum(WorkProvenance, name="work_provenance_enum"), nullable=False
    )
    # Cover and description are read through this edition rather than copied,
    # so there is nothing to drift. Nullable both ways: insert work → attach
    # editions → set representative.
    representative_book_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("books.id", ondelete="SET NULL"), nullable=True
    )
    genre_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("genres.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # Tombstone pointer: a merged work keeps resolving so its URLs survive.
    merged_into_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("works.id", ondelete="SET NULL"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=text("now()"),
        onupdate=datetime.utcnow,
        nullable=False,
    )

    # Relationships. `foreign_keys` is required on both: works↔books has two
    # FK paths (books.work_id and works.representative_book_id).
    editions: Mapped[list["Book"]] = relationship(  # noqa: F821
        "Book", back_populates="work", foreign_keys="Book.work_id"
    )
    representative: Mapped["Book | None"] = relationship(  # noqa: F821
        "Book", foreign_keys=[representative_book_id], post_update=True
    )
    genre: Mapped["Genre | None"] = relationship("Genre", back_populates="works")  # noqa: F821
    threads: Mapped[list["Thread"]] = relationship("Thread", back_populates="work")  # noqa: F821
    shelves: Mapped[list["Shelf"]] = relationship(  # noqa: F821
        "Shelf", back_populates="work", cascade="all, delete-orphan"
    )
```

- [ ] **Step 4: Wire the model into the package and the related tables**

In `backend/app/models/__init__.py`, import and export the new names:

```python
from app.models.work import Work, WorkKind, WorkProvenance, WorkSource
```

Add `"Work"`, `"WorkKind"`, `"WorkProvenance"`, `"WorkSource"` to `__all__`.

In `backend/app/models/book.py`, add the column (next to `genre_id`) and relationship:

```python
    work_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("works.id", ondelete="CASCADE"), nullable=True, index=True
    )
```

```python
    work: Mapped["Work | None"] = relationship(  # noqa: F821
        "Work", back_populates="editions", foreign_keys=[work_id]
    )
```

In `backend/app/models/thread.py`, beside `book_id`:

```python
    work_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("works.id", ondelete="CASCADE"), nullable=True, index=True
    )
```

```python
    work: Mapped["Work | None"] = relationship("Work", back_populates="threads")  # noqa: F821
```

In `backend/app/models/shelf.py`, beside `book_id`:

```python
    work_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("works.id", ondelete="CASCADE"), nullable=True, index=True
    )
```

```python
    work: Mapped["Work | None"] = relationship("Work", back_populates="shelves")  # noqa: F821
```

In `backend/app/models/genre.py`, add the reverse side:

```python
    works: Mapped[list["Work"]] = relationship("Work", back_populates="genre")  # noqa: F821
```

- [ ] **Step 5: Run the model test and verify it passes**

Run: `docker compose exec -T -e DATABASE_URL=postgresql+asyncpg://margin:margin@db:5432/margin_test backend pytest tests/test_work_model.py -q`
Expected: PASS (2 tests)

- [ ] **Step 6: Generate migration 1 and replace its body**

```bash
docker compose exec backend alembic revision --autogenerate -m "add works table and work_id columns"
```

Open the generated file in `backend/alembic/versions/`. Confirm `down_revision = 'c3a7e1b8d904'` and replace `upgrade()` / `downgrade()` with:

```python
def upgrade() -> None:
    work_source = sa.Enum("openlibrary", "heuristic", name="work_source_enum")
    work_kind = sa.Enum("single", "collection", name="work_kind_enum")
    work_provenance = sa.Enum("isbn", "title_author", "heuristic", name="work_provenance_enum")

    op.create_table(
        "works",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("source", work_source, nullable=False),
        sa.Column("external_id", sa.String(length=64), nullable=False),
        sa.Column("canonical_key", sa.Text(), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("subtitle", sa.String(length=500), nullable=True),
        sa.Column("author", sa.String(length=500), nullable=False),
        sa.Column("first_publish_year", sa.Integer(), nullable=True),
        sa.Column("kind", work_kind, nullable=False),
        sa.Column("identity_provenance", work_provenance, nullable=False),
        sa.Column("representative_book_id", sa.UUID(), nullable=True),
        sa.Column("genre_id", sa.UUID(), nullable=True),
        sa.Column("merged_into_id", sa.UUID(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["representative_book_id"], ["books.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["genre_id"], ["genres.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["merged_into_id"], ["works.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source", "external_id", name="uq_works_source_external_id"),
    )
    op.create_index("ix_works_canonical_key", "works", ["canonical_key"])
    op.create_index("ix_works_genre_id", "works", ["genre_id"])
    op.create_index("ix_works_merged_into_id", "works", ["merged_into_id"])

    for table in ("books", "threads", "shelves"):
        op.add_column(table, sa.Column("work_id", sa.UUID(), nullable=True))
        op.create_index(f"ix_{table}_work_id", table, ["work_id"])
        op.create_foreign_key(
            f"fk_{table}_work_id", table, "works", ["work_id"], ["id"], ondelete="CASCADE"
        )


def downgrade() -> None:
    for table in ("shelves", "threads", "books"):
        op.drop_constraint(f"fk_{table}_work_id", table, type_="foreignkey")
        op.drop_index(f"ix_{table}_work_id", table_name=table)
        op.drop_column(table, "work_id")

    op.drop_index("ix_works_merged_into_id", table_name="works")
    op.drop_index("ix_works_genre_id", table_name="works")
    op.drop_index("ix_works_canonical_key", table_name="works")
    op.drop_table("works")

    # Autogenerate does NOT drop enum types; without this, re-upgrading fails
    # with "type already exists" (see CLAUDE.md).
    for name in ("work_provenance_enum", "work_kind_enum", "work_source_enum"):
        sa.Enum(name=name).drop(op.get_bind(), checkfirst=True)
```

- [ ] **Step 7: Verify the migration round-trips**

```bash
docker compose exec backend alembic upgrade head
docker compose exec backend alembic downgrade -1
docker compose exec backend alembic upgrade head
```
Expected: all three succeed. The second `upgrade` is the one that catches a missing enum drop.

- [ ] **Step 8: Run the full backend suite**

Run: `docker compose exec -T -e DATABASE_URL=postgresql+asyncpg://margin:margin@db:5432/margin_test backend pytest -q`
Expected: 118 passed (116 existing + 2 new)

- [ ] **Step 9: Commit**

```bash
git add backend/app/models backend/alembic/versions backend/tests/test_work_model.py
git commit -m "$(cat <<'EOF'
feat(api): add works table and nullable work_id columns

Editions keep living in books; works becomes the entity threads and
shelves will hang off. Columns land nullable so the backfill script can
resolve identities before the FKs move.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: Resolution service and merge

**Files:**
- Create: `backend/app/services/works.py`
- Test: `backend/tests/test_work_resolution.py`

**Interfaces:**
- Consumes: `open_library.resolve_by_isbns`, `open_library.resolve_by_title_author`, `work_identity.{canonical_key,heuristic_external_id,classify_kind,clean_title}`, the `Work`/`Book` models.
- Produces:
  - `completeness_score(edition: Book) -> int`
  - `async resolve_editions(db: AsyncSession, editions: Sequence[Book], genre_hints: Mapping[UUID, UUID] | None = None) -> dict[UUID, Work]` — keyed by `Book.id`, values are canonical (post-merge) works. `genre_hints` maps `Book.id → Genre.id` and is how a work gets its genre; `books.genre_id` is dropped in Task 9, so nothing may read it.
  - `async merge_works(db: AsyncSession, source: Work, target: Work) -> Work`
  - `async canonical_work(db: AsyncSession, work: Work) -> Work` — follows `merged_into_id` one hop
  - `class WorkPresentation(NamedTuple)`: `cover_url: str | None`, `description: str | None`, `edition_count: int`
  - `async load_work_presentation(db: AsyncSession, work_ids: Sequence[UUID]) -> dict[UUID, WorkPresentation]`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_work_resolution.py`:

```python
import uuid

import respx
from httpx import Response
from sqlalchemy import select

from app.models import Book, Shelf, ShelfStatus, Thread, User, Work, WorkKind, WorkProvenance, WorkSource
from app.services import works as works_service

SEARCH_URL = "https://openlibrary.org/search.json"

RED_RISING_DOC = {
    "key": "/works/OL17076473W",
    "title": "Red Rising",
    "author_name": ["Pierce Brown"],
    "first_publish_year": 2014,
    "edition_count": 26,
    "isbn": ["9780345539809", "9781444758986"],
}


def make_edition(**overrides) -> Book:
    defaults = dict(
        source="google_books",
        external_id=uuid.uuid4().hex[:12],
        title="Red Rising",
        author="Pierce Brown",
    )
    defaults.update(overrides)
    return Book(**defaults)


@respx.mock
async def test_editions_sharing_an_isbn_work_collapse_into_one_work(db_session):
    respx.get(SEARCH_URL).mock(return_value=Response(200, json={"docs": [RED_RISING_DOC]}))
    paperback = make_edition(isbn_13="9780345539809", cover_url="https://x/cover.jpg")
    deluxe = make_edition(title="Red Rising (Deluxe Slipcase Edition)", isbn_13="9781444758986")
    db_session.add_all([paperback, deluxe])
    await db_session.flush()

    resolved = await works_service.resolve_editions(db_session, [paperback, deluxe])

    assert resolved[paperback.id].id == resolved[deluxe.id].id
    work = resolved[paperback.id]
    assert work.source is WorkSource.openlibrary
    assert work.external_id == "OL17076473W"
    assert work.identity_provenance is WorkProvenance.isbn
    assert work.title == "Red Rising"  # OL's clean name, not the deluxe title


@respx.mock
async def test_representative_is_the_richest_edition(db_session):
    respx.get(SEARCH_URL).mock(return_value=Response(200, json={"docs": [RED_RISING_DOC]}))
    bare = make_edition(isbn_13="9780345539809")
    rich = make_edition(
        isbn_13="9781444758986",
        cover_url="https://x/cover.jpg",
        description="A boy from the mines.",
        page_count=400,
    )
    db_session.add_all([bare, rich])
    await db_session.flush()

    resolved = await works_service.resolve_editions(db_session, [bare, rich])
    assert resolved[bare.id].representative_book_id == rich.id


@respx.mock
async def test_falls_back_to_title_author_without_an_isbn(db_session):
    respx.get(SEARCH_URL).mock(return_value=Response(200, json={"docs": [RED_RISING_DOC]}))
    edition = make_edition(isbn_13=None)
    db_session.add(edition)
    await db_session.flush()

    work = (await works_service.resolve_editions(db_session, [edition]))[edition.id]
    assert work.source is WorkSource.openlibrary
    assert work.identity_provenance is WorkProvenance.title_author


@respx.mock
async def test_falls_back_to_heuristic_when_open_library_is_down(db_session):
    respx.get(SEARCH_URL).mock(return_value=Response(503, json={}))
    a = make_edition(title="Red Rising 01", isbn_13="9780345539809")
    b = make_edition(title="Red Rising (Deluxe Slipcase Edition)")
    db_session.add_all([a, b])
    await db_session.flush()

    resolved = await works_service.resolve_editions(db_session, [a, b])
    work = resolved[a.id]
    assert work.source is WorkSource.heuristic
    assert work.identity_provenance is WorkProvenance.heuristic
    # The heuristic still groups the two editions — it just can't name the work
    # with an authority's id.
    assert resolved[b.id].id == work.id


@respx.mock
async def test_collections_are_classified_not_dropped(db_session):
    respx.get(SEARCH_URL).mock(return_value=Response(503, json={}))
    bundle = make_edition(title="Red Rising 3-Book Bundle")
    db_session.add(bundle)
    await db_session.flush()

    work = (await works_service.resolve_editions(db_session, [bundle]))[bundle.id]
    assert work.kind is WorkKind.collection


@respx.mock
async def test_a_resolved_edition_is_never_re_resolved(db_session):
    route = respx.get(SEARCH_URL).mock(
        return_value=Response(200, json={"docs": [RED_RISING_DOC]})
    )
    edition = make_edition(isbn_13="9780345539809")
    db_session.add(edition)
    await db_session.flush()

    await works_service.resolve_editions(db_session, [edition])
    calls_after_first = route.call_count
    await works_service.resolve_editions(db_session, [edition])
    assert route.call_count == calls_after_first  # zero upstream cost on repeat


@respx.mock
async def test_a_heuristic_work_is_absorbed_when_open_library_answers_later(db_session):
    # First pass: OL is down, so the edition lands in a heuristic work.
    respx.get(SEARCH_URL).mock(return_value=Response(503, json={}))
    first = make_edition(title="Red Rising 01")
    db_session.add(first)
    await db_session.flush()
    heuristic_work = (await works_service.resolve_editions(db_session, [first]))[first.id]
    assert heuristic_work.source is WorkSource.heuristic

    # Second pass: OL answers for a sibling edition with the same canonical key.
    respx.get(SEARCH_URL).mock(return_value=Response(200, json={"docs": [RED_RISING_DOC]}))
    second = make_edition(isbn_13="9780345539809")
    db_session.add(second)
    await db_session.flush()
    ol_work = (await works_service.resolve_editions(db_session, [second]))[second.id]

    assert ol_work.source is WorkSource.openlibrary
    await db_session.refresh(heuristic_work)
    assert heuristic_work.merged_into_id == ol_work.id
    await db_session.refresh(first)
    assert first.work_id == ol_work.id


@respx.mock
async def test_genre_comes_from_the_hint_not_from_the_edition(db_session):
    from app.models import Genre

    respx.get(SEARCH_URL).mock(return_value=Response(200, json={"docs": [RED_RISING_DOC]}))
    genre = Genre(name="Science Fiction", slug="science-fiction")
    edition = make_edition(isbn_13="9780345539809")
    db_session.add_all([genre, edition])
    await db_session.flush()

    resolved = await works_service.resolve_editions(
        db_session, [edition], genre_hints={edition.id: genre.id}
    )
    assert resolved[edition.id].genre_id == genre.id


async def test_merge_moves_threads_and_shelves(db_session):
    source = Work(
        source=WorkSource.heuristic,
        external_id="abc",
        canonical_key="red rising\x1fpierce brown",
        title="Red Rising",
        author="Pierce Brown",
        kind=WorkKind.single,
        identity_provenance=WorkProvenance.heuristic,
    )
    target = Work(
        source=WorkSource.openlibrary,
        external_id="OL17076473W",
        canonical_key="red rising\x1fpierce brown",
        title="Red Rising",
        author="Pierce Brown",
        kind=WorkKind.single,
        identity_provenance=WorkProvenance.isbn,
    )
    user = User(email="m@example.com", username="merger", password_hash="x")
    db_session.add_all([source, target, user])
    await db_session.flush()

    thread = Thread(title="Is Darrow a hero?", user_id=user.id, work_id=source.id)
    shelf = Shelf(user_id=user.id, work_id=source.id, status=ShelfStatus.read)
    db_session.add_all([thread, shelf])
    await db_session.flush()

    await works_service.merge_works(db_session, source, target)

    await db_session.refresh(thread)
    await db_session.refresh(shelf)
    await db_session.refresh(source)
    assert thread.work_id == target.id
    assert shelf.work_id == target.id
    assert source.merged_into_id == target.id


async def test_merge_keeps_the_oldest_row_on_a_shelf_collision(db_session):
    source = Work(
        source=WorkSource.heuristic, external_id="abc",
        canonical_key="k", title="T", author="A",
        kind=WorkKind.single, identity_provenance=WorkProvenance.heuristic,
    )
    target = Work(
        source=WorkSource.openlibrary, external_id="OL1W",
        canonical_key="k", title="T", author="A",
        kind=WorkKind.single, identity_provenance=WorkProvenance.isbn,
    )
    user = User(email="c@example.com", username="collider", password_hash="x")
    db_session.add_all([source, target, user])
    await db_session.flush()

    db_session.add(Shelf(user_id=user.id, work_id=target.id, status=ShelfStatus.read))
    await db_session.flush()
    db_session.add(Shelf(user_id=user.id, work_id=source.id, status=ShelfStatus.want_to_read))
    await db_session.flush()

    await works_service.merge_works(db_session, source, target)

    rows = (
        await db_session.execute(select(Shelf).where(Shelf.user_id == user.id))
    ).scalars().all()
    assert len(rows) == 1
    assert rows[0].status is ShelfStatus.read  # the older row survived


async def test_canonical_work_follows_the_tombstone(db_session):
    target = Work(
        source=WorkSource.openlibrary, external_id="OL1W",
        canonical_key="k", title="T", author="A",
        kind=WorkKind.single, identity_provenance=WorkProvenance.isbn,
    )
    db_session.add(target)
    await db_session.flush()
    source = Work(
        source=WorkSource.heuristic, external_id="abc",
        canonical_key="k", title="T", author="A",
        kind=WorkKind.single, identity_provenance=WorkProvenance.heuristic,
        merged_into_id=target.id,
    )
    db_session.add(source)
    await db_session.flush()

    assert (await works_service.canonical_work(db_session, source)).id == target.id
```

- [ ] **Step 2: Run the test and verify it fails**

Run: `docker compose exec -T -e DATABASE_URL=postgresql+asyncpg://margin:margin@db:5432/margin_test backend pytest tests/test_work_resolution.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.works'`

- [ ] **Step 3: Write the service**

Create `backend/app/services/works.py`:

```python
"""Work resolution: turning edition rows into a shared book identity.

The only module that writes ``works``. Resolution runs the ladder described in
the spec — batched ISBN, then title+author, then a local heuristic — and every
tier is allowed to fail: the heuristic always produces *some* grouping, so a
search never dies because Open Library did.
"""

from __future__ import annotations

from typing import Mapping, NamedTuple, Sequence
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.book import Book
from app.models.shelf import Shelf
from app.models.thread import Thread
from app.models.work import Work, WorkKind, WorkProvenance, WorkSource
from app.services import open_library
from app.services.open_library import OLWork
from app.services.work_identity import (
    canonical_key,
    classify_kind,
    clean_title,
    heuristic_external_id,
)

# Tier 2 costs one HTTP call per volume, so it is capped. Anything past the cap
# falls to the heuristic tier and can be upgraded later by the script.
_TITLE_AUTHOR_CALL_CAP = 5


def completeness_score(edition: Book) -> int:
    """Higher = richer edition. Cover weighted highest — it carries the page.

    Moved here from ``google_books._completeness_score``: picking the richest
    edition is the only decision it was ever really making, and that decision
    now belongs to the work, not to a single search response.
    """
    score = 0
    if edition.cover_url:
        score += 4
    if edition.description:
        score += 1
    if edition.isbn_13:
        score += 1
    if edition.page_count:
        score += 1
    if edition.ratings_count:
        score += 1
    return score


async def canonical_work(db: AsyncSession, work: Work) -> Work:
    """Follow ``merged_into_id`` one hop. Merges repoint, so chains never grow."""
    if work.merged_into_id is None:
        return work
    target = await db.get(Work, work.merged_into_id)
    return target or work


async def resolve_editions(
    db: AsyncSession,
    editions: Sequence[Book],
    genre_hints: Mapping[UUID, UUID] | None = None,
) -> dict[UUID, Work]:
    """Attach every edition to a work, creating works as needed.

    Returns ``{book_id: work}`` with canonical (post-merge) works. Editions that
    already carry a ``work_id`` are returned as-is without any upstream call —
    an edition is resolved exactly once, ever.

    ``genre_hints`` maps ``Book.id`` to a ``Genre.id`` derived from the search
    payload's categories. Genre lives on the work, and ``books.genre_id`` is
    dropped, so this is the only path by which a work acquires one.
    """
    resolved: dict[UUID, Work] = {}
    pending: list[Book] = []

    for edition in editions:
        if edition.work_id is not None:
            work = await db.get(Work, edition.work_id)
            if work is not None:
                resolved[edition.id] = await canonical_work(db, work)
                continue
        pending.append(edition)

    if not pending:
        return resolved

    ol_by_edition = await _resolve_upstream(pending)

    touched: set[UUID] = set()
    for edition in pending:
        ol_work, provenance = ol_by_edition.get(
            edition.id, (None, WorkProvenance.heuristic)
        )
        work = await _upsert_work(db, edition, ol_work, provenance)
        edition.work_id = work.id
        resolved[edition.id] = work
        touched.add(work.id)

    await db.flush()
    for work_id in touched:
        work = await db.get(Work, work_id)
        if work is not None:
            await _refresh_work(db, work, genre_hints)
    await db.flush()

    return resolved


async def _resolve_upstream(
    editions: Sequence[Book],
) -> dict[UUID, tuple[OLWork | None, WorkProvenance]]:
    """Run tiers 1 and 2. Absent entries fall to the heuristic tier."""
    out: dict[UUID, tuple[OLWork | None, WorkProvenance]] = {}

    # Tier 1 — one batched ISBN call for the whole page of results.
    isbns = [e.isbn_13 for e in editions if e.isbn_13]
    by_isbn = await open_library.resolve_by_isbns(isbns) if isbns else {}
    for edition in editions:
        if edition.isbn_13 and edition.isbn_13 in by_isbn:
            out[edition.id] = (by_isbn[edition.isbn_13], WorkProvenance.isbn)

    # Tier 2 — title + author, capped.
    budget = _TITLE_AUTHOR_CALL_CAP
    for edition in editions:
        if edition.id in out or budget <= 0:
            continue
        if not edition.title or not edition.author:
            continue
        budget -= 1
        found = await open_library.resolve_by_title_author(edition.title, edition.author)
        if found is not None:
            out[edition.id] = (found, WorkProvenance.title_author)

    return out


async def _upsert_work(
    db: AsyncSession,
    edition: Book,
    ol_work: OLWork | None,
    provenance: WorkProvenance,
) -> Work:
    """Get-or-create the work an edition belongs to, merging on upgrade."""
    key = canonical_key(edition.title or "", edition.author)

    if ol_work is not None:
        source, external_id = WorkSource.openlibrary, ol_work.key
        title = ol_work.title
        author = ol_work.author or edition.author or "Unknown"
        year = ol_work.first_publish_year or edition.published_year
    else:
        source, external_id = WorkSource.heuristic, heuristic_external_id(key)
        title = (clean_title(edition.title or "") or edition.title or "Untitled").strip()
        author = edition.author or "Unknown"
        year = edition.published_year

    existing = (
        await db.execute(
            select(Work).where(Work.source == source, Work.external_id == external_id)
        )
    ).scalar_one_or_none()

    if existing is not None:
        return await canonical_work(db, existing)

    work = Work(
        source=source,
        external_id=external_id,
        canonical_key=key,
        title=title,
        subtitle=edition.subtitle,
        author=author,
        first_publish_year=year,
        kind=WorkKind(classify_kind(edition.title or "", edition.subtitle)),
        identity_provenance=provenance,
    )
    db.add(work)
    await db.flush()

    if source is WorkSource.openlibrary:
        await _absorb_heuristic_twin(db, work)
    return work


async def _absorb_heuristic_twin(db: AsyncSession, work: Work) -> None:
    """Merge any heuristic work that turns out to be this same book.

    Heuristic → Open Library only. Two distinct Open Library work ids are an
    authority's claim, and overriding one belongs in a deliberate merge, not in
    the middle of a search request.
    """
    twin = (
        await db.execute(
            select(Work).where(
                Work.source == WorkSource.heuristic,
                Work.canonical_key == work.canonical_key,
                Work.merged_into_id.is_(None),
            )
        )
    ).scalars().first()
    if twin is not None:
        await merge_works(db, twin, work)


async def _refresh_work(
    db: AsyncSession, work: Work, genre_hints: Mapping[UUID, UUID] | None = None
) -> None:
    """Recompute the derived fields that depend on the work's editions."""
    editions = (
        await db.execute(select(Book).where(Book.work_id == work.id))
    ).scalars().all()
    if not editions:
        return

    best = max(editions, key=completeness_score)
    work.representative_book_id = best.id

    if work.genre_id is None and genre_hints:
        work.genre_id = next(
            (genre_hints[e.id] for e in editions if e.id in genre_hints), None
        )


async def merge_works(db: AsyncSession, source: Work, target: Work) -> Work:
    """Fold ``source`` into ``target``, leaving a tombstone behind.

    Editions, threads and shelves move; the source row survives with
    ``merged_into_id`` set so its URLs keep resolving.
    """
    if source.id == target.id:
        return target

    # Shelves first: uq_shelf_user_work allows one row per (user, work), so a
    # user who shelved both works keeps their oldest entry.
    source_shelves = (
        await db.execute(select(Shelf).where(Shelf.work_id == source.id))
    ).scalars().all()
    target_owners = set(
        (
            await db.execute(select(Shelf.user_id).where(Shelf.work_id == target.id))
        ).scalars().all()
    )
    for shelf in source_shelves:
        if shelf.user_id in target_owners:
            await db.delete(shelf)
        else:
            shelf.work_id = target.id
            target_owners.add(shelf.user_id)
    await db.flush()

    await db.execute(
        update(Book).where(Book.work_id == source.id).values(work_id=target.id)
    )
    await db.execute(
        update(Thread).where(Thread.work_id == source.id).values(work_id=target.id)
    )

    source.merged_into_id = target.id
    await db.flush()
    await _refresh_work(db, target)
    await db.flush()
    return target


class WorkPresentation(NamedTuple):
    """The edition-derived bits a work needs to render."""

    cover_url: str | None
    description: str | None
    edition_count: int


async def load_work_presentation(
    db: AsyncSession, work_ids: Sequence[UUID]
) -> dict[UUID, WorkPresentation]:
    """Fetch cover, description and edition count for many works in one query.

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
            representative.c.cover_url,
            representative.c.description,
            func.coalesce(counts.c.n, 0),
        )
        .outerjoin(representative, Work.representative_book_id == representative.c.id)
        .outerjoin(counts, counts.c.work_id == Work.id)
        .where(Work.id.in_(work_ids))
    )
    rows = (await db.execute(stmt)).all()
    return {
        row[0]: WorkPresentation(cover_url=row[1], description=row[2], edition_count=row[3])
        for row in rows
    }
```

- [ ] **Step 4: Run the test and verify it passes**

Run: `docker compose exec -T -e DATABASE_URL=postgresql+asyncpg://margin:margin@db:5432/margin_test backend pytest tests/test_work_resolution.py -q`
Expected: PASS (11 tests)

- [ ] **Step 5: Run the full backend suite**

Run: `docker compose exec -T -e DATABASE_URL=postgresql+asyncpg://margin:margin@db:5432/margin_test backend pytest -q`
Expected: 129 passed

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/works.py backend/tests/test_work_resolution.py
git commit -m "$(cat <<'EOF'
feat(api): resolve editions to works, with merge

The resolution ladder (batched ISBN, capped title+author, heuristic)
plus merge_works. A heuristic work is absorbed automatically once Open
Library answers for a sibling edition; OL-to-OL merges stay manual.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---
## Task 5: `WorkOut` schema and the works router

**Files:**
- Create: `backend/app/api/works.py`
- Delete: `backend/app/api/books.py`
- Modify: `backend/app/schemas/book.py`, `backend/app/main.py`, `backend/app/services/google_books.py`
- Test: create `backend/tests/test_works.py` (from `test_books.py`, which is deleted), modify `backend/tests/test_google_books.py`, `backend/tests/test_pagination.py`, `backend/tests/test_openapi.py`, `backend/tests/conftest.py`

**Interfaces:**
- Consumes: `works.resolve_editions`, `works.load_work_presentation`, `works.canonical_work`, `works.WorkPresentation`.
- Produces:
  - `WorkOut` (in `schemas/book.py`): `id, title, subtitle, author, first_publish_year, kind, genre_id, cover_url, description, edition_count, shelf_status`
  - `work_out(work: Work, presentation: WorkPresentation | None, shelf_status: ShelfStatus | None = None) -> WorkOut`
  - `ShelfOut.work_id` replaces `ShelfOut.book_id`
  - Routes under `/api/works` (search, detail, threads, shelf CRUD)
  - `conftest.work` fixture replaces `conftest.book`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_works.py`. This is `test_books.py` reframed around works — the central assertion is that five editions become one card:

```python
import respx
from httpx import Response

GOOGLE_URL = "https://www.googleapis.com/books/v1/volumes"
OL_URL = "https://openlibrary.org/search.json"


def volume(vol_id, title, isbn=None, **info):
    data = {"title": title, "authors": ["Pierce Brown"], **info}
    if isbn:
        data["industryIdentifiers"] = [{"type": "ISBN_13", "identifier": isbn}]
    return {"id": vol_id, "volumeInfo": data}


# The motivating search: five Google volumes, one book.
RED_RISING_VOLUMES = [
    volume("g1", "Red Rising (Deluxe Slipcase Edition)", "9780345539809",
           imageLinks={"thumbnail": "http://x/deluxe?zoom=1"}),
    volume("g2", "Red Rising 01", "9781444758986"),
    volume("g3", "Red Rising", "9780345539823", description="A boy from the mines.",
           pageCount=400, imageLinks={"thumbnail": "http://x/plain?zoom=1"}),
    volume("g4", "Red Rising 3-Book Bundle"),
    volume("g5", "Red Rising 1-6 ebook collection"),
]

OL_RED_RISING = {
    "key": "/works/OL17076473W",
    "title": "Red Rising",
    "author_name": ["Pierce Brown"],
    "first_publish_year": 2014,
    "edition_count": 26,
    "isbn": ["9780345539809", "9781444758986", "9780345539823"],
}


def mock_upstream(ol_docs=None):
    respx.get(GOOGLE_URL).mock(
        return_value=Response(200, json={"items": RED_RISING_VOLUMES})
    )
    respx.get(OL_URL).mock(
        return_value=Response(200, json={"docs": ol_docs if ol_docs is not None else [OL_RED_RISING]})
    )


@respx.mock
async def test_search_collapses_editions_into_one_work(client):
    mock_upstream()
    resp = await client.get("/api/works/search", params={"q": "red rising"})
    assert resp.status_code == 200, resp.text
    body = resp.json()

    # Three single editions collapse to one work; two collections are hidden.
    assert len(body) == 1
    work = body[0]
    assert work["title"] == "Red Rising"
    assert work["author"] == "Pierce Brown"
    assert work["first_publish_year"] == 2014
    assert work["edition_count"] == 3
    # The richest edition supplies the cover and description.
    assert work["description"] == "A boy from the mines."
    assert work["cover_url"].startswith("https://")


@respx.mock
async def test_search_hides_collections_but_keeps_them_reachable(client, db_session):
    from sqlalchemy import select
    from app.models import Work, WorkKind

    mock_upstream()
    await client.get("/api/works/search", params={"q": "red rising"})

    collections = (
        await db_session.execute(select(Work).where(Work.kind == WorkKind.collection))
    ).scalars().all()
    assert len(collections) == 2  # stored, not dropped

    resp = await client.get(f"/api/works/{collections[0].id}")
    assert resp.status_code == 200
    assert resp.json()["kind"] == "collection"


@respx.mock
async def test_search_is_idempotent_and_costs_no_second_open_library_call(client):
    mock_upstream()
    ol_route = respx.get(OL_URL)
    first = (await client.get("/api/works/search", params={"q": "red rising"})).json()
    calls_after_first = ol_route.call_count
    second = (await client.get("/api/works/search", params={"q": "red rising"})).json()

    assert first[0]["id"] == second[0]["id"]
    assert ol_route.call_count == calls_after_first


@respx.mock
async def test_search_still_works_when_open_library_is_down(client):
    respx.get(GOOGLE_URL).mock(
        return_value=Response(200, json={"items": RED_RISING_VOLUMES})
    )
    respx.get(OL_URL).mock(return_value=Response(503, json={}))

    resp = await client.get("/api/works/search", params={"q": "red rising"})
    assert resp.status_code == 200
    # The heuristic still groups the three single editions by cleaned title.
    assert len(resp.json()) == 1


@respx.mock
async def test_search_returns_503_when_google_books_fails(client):
    respx.get(GOOGLE_URL).mock(return_value=Response(429, json={"error": "rate limited"}))
    resp = await client.get("/api/works/search", params={"q": "red rising"})
    assert resp.status_code == 503
    assert "unavailable" in resp.json()["detail"].lower()


@respx.mock
async def test_search_maps_a_genre_onto_the_work(client, db_session):
    from app.models import Genre

    db_session.add(Genre(name="Science Fiction", slug="science-fiction"))
    await db_session.flush()
    respx.get(GOOGLE_URL).mock(
        return_value=Response(
            200,
            json={"items": [volume("g9", "Red Rising", "9780345539809",
                                   categories=["Fiction / Science Fiction"])]},
        )
    )
    respx.get(OL_URL).mock(return_value=Response(200, json={"docs": [OL_RED_RISING]}))

    body = (await client.get("/api/works/search", params={"q": "red rising"})).json()
    assert body[0]["genre_id"] is not None


async def test_get_work_includes_shelf_status_for_owner(client, auth_headers, work):
    await client.post(
        f"/api/works/{work.id}/shelf", json={"status": "reading"}, headers=auth_headers
    )
    resp = await client.get(f"/api/works/{work.id}", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["shelf_status"] == "reading"


async def test_get_work_shelf_status_null_when_anonymous(client, work):
    resp = await client.get(f"/api/works/{work.id}")
    assert resp.status_code == 200
    assert resp.json()["shelf_status"] is None


async def test_get_work_follows_a_merge_tombstone(client, db_session, work):
    from app.models import Work, WorkKind, WorkProvenance, WorkSource

    merged = Work(
        source=WorkSource.heuristic,
        external_id="old",
        canonical_key=work.canonical_key,
        title=work.title,
        author=work.author,
        kind=WorkKind.single,
        identity_provenance=WorkProvenance.heuristic,
        merged_into_id=work.id,
    )
    db_session.add(merged)
    await db_session.flush()

    resp = await client.get(f"/api/works/{merged.id}")
    assert resp.status_code == 200
    assert resp.json()["id"] == str(work.id)


async def test_shelf_crud_is_keyed_on_the_work(client, auth_headers, work):
    created = await client.post(
        f"/api/works/{work.id}/shelf", json={"status": "want_to_read"}, headers=auth_headers
    )
    assert created.status_code == 201
    assert created.json()["work_id"] == str(work.id)

    duplicate = await client.post(
        f"/api/works/{work.id}/shelf", json={"status": "reading"}, headers=auth_headers
    )
    assert duplicate.status_code == 409

    updated = await client.put(
        f"/api/works/{work.id}/shelf", json={"status": "read"}, headers=auth_headers
    )
    assert updated.json()["status"] == "read"

    removed = await client.delete(f"/api/works/{work.id}/shelf", headers=auth_headers)
    assert removed.status_code == 204


async def test_work_threads_listing(client, auth_headers, work):
    await client.post(
        "/api/threads/",
        json={"title": "Is Darrow a hero?", "work_id": str(work.id), "content": "Discuss."},
        headers=auth_headers,
    )
    resp = await client.get(f"/api/works/{work.id}/threads")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["title"] == "Is Darrow a hero?"
    assert body[0]["post_count"] == 1
```

- [ ] **Step 2: Replace the `book` fixture with a `work` fixture**

In `backend/tests/conftest.py`, change the import line and replace the `book` fixture:

```python
from app.models import Base, Book, Work, WorkKind, WorkProvenance, WorkSource  # noqa: E402
```

```python
@pytest_asyncio.fixture
async def work(db_session):
    """Seed a work and one edition (no upstream round-trip) for thread/shelf tests."""
    w = Work(
        source=WorkSource.openlibrary,
        external_id=f"OL{uuid.uuid4().hex[:8]}W",
        canonical_key="the test book\x1fa tester",
        title="The Test Book",
        author="A. Tester",
        kind=WorkKind.single,
        identity_provenance=WorkProvenance.isbn,
    )
    db_session.add(w)
    await db_session.flush()

    edition = Book(
        source="google_books",
        external_id=uuid.uuid4().hex[:12],
        title="The Test Book",
        author="A. Tester",
        work_id=w.id,
    )
    db_session.add(edition)
    await db_session.flush()

    w.representative_book_id = edition.id
    await db_session.commit()
    await db_session.refresh(w)
    return w
```

- [ ] **Step 3: Run the test and verify it fails**

Run: `docker compose exec -T -e DATABASE_URL=postgresql+asyncpg://margin:margin@db:5432/margin_test backend pytest tests/test_works.py -q`
Expected: FAIL — 404s on `/api/works/search` (router does not exist)

- [ ] **Step 4: Add `WorkOut` to the schemas**

In `backend/app/schemas/book.py`, add the import and the new shapes, and change `ShelfOut.book_id` to `work_id`:

```python
from app.models.work import Work, WorkKind
from app.services.works import WorkPresentation


class WorkOut(BaseModel):
    """A book as readers mean it. Cover and description come from the work's
    representative edition, resolved by the route — never by a lazy relationship
    load, which would raise MissingGreenlet mid-serialization."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    title: str
    subtitle: str | None = None
    author: str
    first_publish_year: int | None = None
    kind: WorkKind
    genre_id: UUID | None = None
    cover_url: str | None = None
    description: str | None = None
    edition_count: int = 0
    shelf_status: ShelfStatus | None = None


def work_out(
    work: Work,
    presentation: WorkPresentation | None = None,
    shelf_status: ShelfStatus | None = None,
) -> WorkOut:
    """Build a WorkOut from scalar columns plus its presentation row."""
    return WorkOut(
        id=work.id,
        title=work.title,
        subtitle=work.subtitle,
        author=work.author,
        first_publish_year=work.first_publish_year,
        kind=work.kind,
        genre_id=work.genre_id,
        cover_url=presentation.cover_url if presentation else None,
        description=presentation.description if presentation else None,
        edition_count=presentation.edition_count if presentation else 0,
        shelf_status=shelf_status,
    )
```

```python
class ShelfOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID
    work_id: UUID
    status: ShelfStatus
    created_at: datetime
```

- [ ] **Step 5: Write the works router**

Create `backend/app/api/works.py`:

```python
from __future__ import annotations

from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, literal, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.base import Base  # noqa: F401 — ensure metadata loaded
from app.schemas.book import ShelfIn, ShelfOut, WorkOut, work_out
from app.schemas.thread import ThreadSummary
from app.services import google_books
from app.services.auth import get_current_user, get_current_user_optional
from app.services.works import (
    canonical_work,
    load_work_presentation,
    resolve_editions,
)

from app.models.book import Book  # type: ignore[import]
from app.models.genre import Genre  # type: ignore[import]
from app.models.post import Post  # type: ignore[import]
from app.models.shelf import Shelf  # type: ignore[import]
from app.models.thread import Thread  # type: ignore[import]
from app.models.user import User  # type: ignore[import]
from app.models.vote import Vote  # type: ignore[import]
from app.models.work import Work, WorkKind  # type: ignore[import]

router = APIRouter(prefix="/works", tags=["works"])

# Fields copied verbatim from the normalized Google Books dict onto an edition.
_EDITION_FIELDS = (
    "title", "subtitle", "author", "cover_url", "description", "publisher",
    "published_date", "published_year", "isbn_13", "page_count",
    "average_rating", "ratings_count", "language", "categories",
    "maturity_rating", "info_link", "preview_link",
)


async def _get_work_or_404(work_id: UUID, db: AsyncSession) -> Work:
    work = await db.get(Work, work_id)
    if work is None:
        raise HTTPException(status_code=404, detail="Work not found")
    return await canonical_work(db, work)


async def _upsert_editions(
    db: AsyncSession, results: list[dict]
) -> tuple[list[Book], dict[UUID, UUID]]:
    """Upsert every volume as an edition; return them in relevance order.

    The second return value maps ``Book.id`` to the genre its categories imply.
    Genre belongs to the work, so the hint is passed through rather than stored
    on the edition.
    """
    slugs = {r["genre_slug"] for r in results if r.get("genre_slug")}
    genre_ids: dict[str, UUID] = {}
    if slugs:
        rows = (await db.execute(select(Genre.slug, Genre.id).where(Genre.slug.in_(slugs)))).all()
        genre_ids = {slug: gid for slug, gid in rows}

    editions: list[Book] = []
    hints: dict[UUID, UUID] = {}
    for item in results:
        ext_id = item.get("external_id")
        if not ext_id:
            continue

        stmt = select(Book).where(Book.source == "google_books", Book.external_id == ext_id)
        existing = (await db.execute(stmt)).scalars().first()

        if existing:
            for field in _EDITION_FIELDS:
                value = item.get(field)
                if value:  # only overwrite when Google gave us something
                    setattr(existing, field, value)
            edition = existing
        else:
            edition = Book(
                source="google_books",
                external_id=ext_id,
                **{f: item.get(f) for f in _EDITION_FIELDS},
            )
            db.add(edition)

        await db.flush()  # get generated id
        editions.append(edition)
        if item.get("genre_slug") in genre_ids:
            hints[edition.id] = genre_ids[item["genre_slug"]]

    return editions, hints


async def _to_work_outs(
    db: AsyncSession, works: list[Work], shelf_by_work: dict[UUID, str] | None = None
) -> list[WorkOut]:
    presentation = await load_work_presentation(db, [w.id for w in works])
    shelf_by_work = shelf_by_work or {}
    return [
        work_out(w, presentation.get(w.id), shelf_by_work.get(w.id)) for w in works
    ]


@router.get("/search", response_model=list[WorkOut])
async def search_works(
    q: str = Query(..., min_length=1),
    db: AsyncSession = Depends(get_db),
):
    """Search Google Books, group the volumes into works, return one per work."""
    try:
        results = await google_books.search_books(q)
    except (httpx.HTTPStatusError, httpx.RequestError) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Book search is temporarily unavailable. Please try again shortly.",
        ) from exc

    editions, genre_hints = await _upsert_editions(db, results)
    by_edition = await resolve_editions(db, editions, genre_hints)

    # A work takes the position of its first-seen edition, so Google's relevance
    # ranking still drives the page.
    ordered: list[Work] = []
    seen: set[UUID] = set()
    for edition in editions:
        work = by_edition.get(edition.id)
        if work is None or work.id in seen:
            continue
        seen.add(work.id)
        if work.kind is WorkKind.single:
            ordered.append(work)

    return await _to_work_outs(db, ordered)


@router.get("/{work_id}", response_model=WorkOut)
async def get_work(
    work_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user_optional),
):
    work = await _get_work_or_404(work_id, db)
    shelf_by_work: dict[UUID, str] = {}
    if current_user is not None:
        stmt = select(Shelf.status).where(
            Shelf.user_id == current_user.id, Shelf.work_id == work.id
        )
        found = (await db.execute(stmt)).scalar_one_or_none()
        if found is not None:
            shelf_by_work[work.id] = found
    return (await _to_work_outs(db, [work], shelf_by_work))[0]


@router.get("/{work_id}/threads", response_model=list[ThreadSummary])
async def get_work_threads(
    work_id: UUID,
    db: AsyncSession = Depends(get_db),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current_user=Depends(get_current_user_optional),
):
    work = await _get_work_or_404(work_id, db)
    if current_user is None:
        my_vote = literal(0).label("my_vote")
    else:
        # A correlated scalar subquery, not a LEFT JOIN: this query already
        # GROUP BYs to produce post_count, and a join would have to be folded
        # into that grouping.
        my_vote = func.coalesce(
            select(Vote.value)
            .where(Vote.thread_id == Thread.id, Vote.user_id == current_user.id)
            .scalar_subquery(),
            0,
        ).label("my_vote")

    stmt = (
        select(
            Thread.id,
            Thread.title,
            Thread.score,
            my_vote,
            Thread.work_id,
            Thread.created_at,
            User.username.label("author"),
            Genre.slug.label("genre_slug"),
            func.count(Post.id).label("post_count"),
        )
        .join(User, Thread.user_id == User.id)
        .outerjoin(Genre, Thread.genre_id == Genre.id)
        .outerjoin(Post, Post.thread_id == Thread.id)
        .where(Thread.work_id == work.id)
        .group_by(Thread.id, User.username, Genre.slug)
        .order_by(Thread.score.desc())
        .limit(limit)
        .offset(offset)
    )
    rows = (await db.execute(stmt)).all()
    return [ThreadSummary.model_validate(row) for row in rows]


@router.post("/{work_id}/shelf", response_model=ShelfOut, status_code=status.HTTP_201_CREATED)
async def add_to_shelf(
    work_id: UUID,
    payload: ShelfIn,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    work = await _get_work_or_404(work_id, db)

    stmt = select(Shelf).where(Shelf.user_id == current_user.id, Shelf.work_id == work.id)
    existing = (await db.execute(stmt)).scalars().first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Book already on shelf. Use PUT to update.",
        )

    shelf = Shelf(user_id=current_user.id, work_id=work.id, status=payload.status)
    db.add(shelf)
    await db.flush()
    return shelf


@router.put("/{work_id}/shelf", response_model=ShelfOut)
async def update_shelf(
    work_id: UUID,
    payload: ShelfIn,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    work = await _get_work_or_404(work_id, db)
    stmt = select(Shelf).where(Shelf.user_id == current_user.id, Shelf.work_id == work.id)
    shelf = (await db.execute(stmt)).scalars().first()
    if shelf is None:
        raise HTTPException(status_code=404, detail="Shelf entry not found")

    shelf.status = payload.status
    await db.flush()
    return shelf


@router.delete("/{work_id}/shelf", status_code=status.HTTP_204_NO_CONTENT)
async def remove_from_shelf(
    work_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    work = await _get_work_or_404(work_id, db)
    stmt = select(Shelf).where(Shelf.user_id == current_user.id, Shelf.work_id == work.id)
    shelf = (await db.execute(stmt)).scalars().first()
    if shelf is None:
        raise HTTPException(status_code=404, detail="Shelf entry not found")

    await db.delete(shelf)
```

- [ ] **Step 6: Swap the router in `main.py` and delete the old one**

In `backend/app/main.py`, replace the books import and registration:

```python
from app.api import auth, genres, posts, threads, users, works
```

```python
app.include_router(works.router, prefix="/api")
```

Then:

```bash
git rm backend/app/api/books.py backend/tests/test_books.py
```

- [ ] **Step 7: Delete the superseded dedup from `google_books.py`**

Remove `_dedup_key` (line 44), `_completeness_score` (line 56) and `_dedup_volumes` (line 72) entirely, and change the two return statements in `search_books` (lines 226 and 233):

```python
    async with httpx.AsyncClient(timeout=15.0) as client:
        title_results = await _query_volumes(client, f"intitle:{query}")
        if len(title_results) >= _MIN_TITLE_RESULTS:
            return title_results

        broad_results = await _query_volumes(client, query)

    seen = {r["external_id"] for r in title_results}
    merged = list(title_results)
    merged.extend(r for r in broad_results if r["external_id"] not in seen)
    return merged
```

Update the `search_books` docstring's last paragraph to:

```
    Duplicate editions are no longer collapsed here — work grouping
    (``services/works.py``) does that persistently and by identity, so a second
    string-keyed pass would only disagree with it at the seams.
```

In `backend/tests/test_google_books.py`, delete the six tests covering `_dedup_key`, `_completeness_score` and `_dedup_volumes` (from the `# _dedup_key() helper for edition grouping.` comment block at line 277 to the end of the completeness-score tests). Their replacements live in `test_work_identity.py` and `test_works.py`.

- [ ] **Step 8: Repoint the remaining suites**

In `backend/tests/test_openapi.py:16`, rename the expected tag:

```python
    expected = {"auth", "works", "genres", "threads", "posts", "users"}
```

In `backend/tests/test_pagination.py`, update the module docstring to "work-threads, genre-works, and genre-threads endpoints", swap the `book` fixture for `work`, change `_seed_book_threads` to build `Thread(..., work_id=work.id)`, and replace the three `/api/books/{...}/threads` paths with `/api/works/{...}/threads`. Leave `_seed_genre_books` and `test_genre_books_limit_and_offset` alone for now — they seed `Book(genre_id=...)`, which Task 6 replaces wholesale.

- [ ] **Step 9: Run the full backend suite**

Run: `docker compose exec -T -e DATABASE_URL=postgresql+asyncpg://margin:margin@db:5432/margin_test backend pytest -q`
Expected: PASS. Threads tests still reference `book_id` and are fixed in Task 7 — if they fail here, note it and continue; everything else must be green.

- [ ] **Step 10: Commit**

```bash
git add -A backend
git commit -m "$(cat <<'EOF'
feat(api): serve works instead of editions

/api/books becomes /api/works: search groups volumes into works, hides
collections, and reads cover and description through each work's
representative edition. Deletes the per-response dedup it supersedes.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: Genre and profile listings

**Files:**
- Modify: `backend/app/api/genres.py`, `backend/app/api/users.py`
- Test: modify `backend/tests/test_shelves.py`, create `backend/tests/test_genre_works.py`

**Interfaces:**
- Consumes: `schemas.book.WorkOut`, `schemas.book.work_out`, `works.load_work_presentation`.
- Produces: `GET /api/genres/{slug}/works` → `list[WorkOut]`; `ShelfBookOut.work_id` replaces `.book_id`.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_genre_works.py`:

```python
import uuid

from app.models import Book, Genre, Work, WorkKind, WorkProvenance, WorkSource


async def seed_work(db_session, genre, title, kind=WorkKind.single):
    work = Work(
        source=WorkSource.openlibrary,
        external_id=f"OL{uuid.uuid4().hex[:8]}W",
        canonical_key=f"{title.lower()}\x1fauthor",
        title=title,
        author="Author",
        kind=kind,
        identity_provenance=WorkProvenance.isbn,
        genre_id=genre.id,
    )
    db_session.add(work)
    await db_session.flush()
    edition = Book(
        source="google_books",
        external_id=uuid.uuid4().hex[:12],
        title=title,
        author="Author",
        cover_url="https://x/cover.jpg",
        work_id=work.id,
    )
    db_session.add(edition)
    await db_session.flush()
    work.representative_book_id = edition.id
    await db_session.flush()
    return work


async def test_genre_lists_works_with_their_covers(client, db_session):
    genre = Genre(name="Science Fiction", slug="science-fiction")
    db_session.add(genre)
    await db_session.flush()
    await seed_work(db_session, genre, "Red Rising")
    await db_session.commit()

    resp = await client.get("/api/genres/science-fiction/works")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["title"] == "Red Rising"
    assert body[0]["cover_url"] == "https://x/cover.jpg"
    assert body[0]["edition_count"] == 1


async def test_genre_listing_hides_collections(client, db_session):
    genre = Genre(name="Science Fiction", slug="science-fiction")
    db_session.add(genre)
    await db_session.flush()
    await seed_work(db_session, genre, "Red Rising")
    await seed_work(db_session, genre, "Red Rising Box Set", kind=WorkKind.collection)
    await db_session.commit()

    body = (await client.get("/api/genres/science-fiction/works")).json()
    assert [w["title"] for w in body] == ["Red Rising"]


async def test_genre_listing_skips_merged_works(client, db_session):
    genre = Genre(name="Science Fiction", slug="science-fiction")
    db_session.add(genre)
    await db_session.flush()
    keeper = await seed_work(db_session, genre, "Red Rising")
    merged = await seed_work(db_session, genre, "Red Rising")
    merged.merged_into_id = keeper.id
    await db_session.commit()

    body = (await client.get("/api/genres/science-fiction/works")).json()
    assert len(body) == 1
    assert body[0]["id"] == str(keeper.id)
```

- [ ] **Step 2: Run the test and verify it fails**

Run: `docker compose exec -T -e DATABASE_URL=postgresql+asyncpg://margin:margin@db:5432/margin_test backend pytest tests/test_genre_works.py -q`
Expected: FAIL — 404 on `/api/genres/science-fiction/works`

- [ ] **Step 3: Replace the genre books endpoint**

In `backend/app/api/genres.py`, swap the imports:

```python
from app.schemas.book import GenreOut, WorkOut, work_out
from app.models.work import Work, WorkKind  # type: ignore[import]
from app.services.works import load_work_presentation
```

(`BookOut` and the `Book` model import are no longer used here — remove both.)

Replace `get_genre_books` with:

```python
@router.get("/{slug}/works", response_model=list[WorkOut])
async def get_genre_works(
    slug: str,
    db: AsyncSession = Depends(get_db),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    genre = await _get_genre_or_404(slug, db)
    stmt = (
        select(Work)
        .where(
            Work.genre_id == genre.id,
            Work.kind == WorkKind.single,
            Work.merged_into_id.is_(None),  # tombstones are reachable, not listed
        )
        .order_by(Work.title)
        .limit(limit)
        .offset(offset)
    )
    works = (await db.execute(stmt)).scalars().all()
    presentation = await load_work_presentation(db, [w.id for w in works])
    return [work_out(w, presentation.get(w.id)) for w in works]
```

Also change the `Thread.book_id` column in `get_genre_threads`'s select list to `Thread.work_id`.

- [ ] **Step 4: Move the profile shelf shape to works**

In `backend/app/api/users.py`, rename the field on `ShelfBookOut`:

```python
class ShelfBookOut(BaseModel):
    model_config = {"from_attributes": True}

    id: UUID
    work_id: UUID
    status: str
    created_at: datetime
```

- [ ] **Step 5: Update the shelf tests**

In `backend/tests/test_shelves.py`, replace every `/api/books/{...}/shelf` path with `/api/works/{...}/shelf`, the `book` fixture with `work`, and any `book_id` assertion with `work_id`.

- [ ] **Step 6: Move the genre pagination test onto works**

In `backend/tests/test_pagination.py`, replace `_seed_genre_books` and its test:

```python
async def _seed_genre_works(db_session, genre, n: int):
    from app.models import Work, WorkKind, WorkProvenance, WorkSource

    works = []
    for i in range(n):
        w = Work(
            source=WorkSource.openlibrary,
            external_id=f"OL{i}{uuid.uuid4().hex[:6]}W",
            canonical_key=f"book {i}\x1fauthor",
            title=f"Book {i}",
            author="Author",
            kind=WorkKind.single,
            identity_provenance=WorkProvenance.isbn,
            genre_id=genre.id,
        )
        db_session.add(w)
        works.append(w)
    await db_session.flush()
    return works


async def test_genre_works_limit_and_offset(client, db_session, genre):
    await _seed_genre_works(db_session, genre, 3)

    page1 = await client.get(f"/api/genres/{genre.slug}/works?limit=2&offset=0")
    assert len(page1.json()) == 2

    page2 = await client.get(f"/api/genres/{genre.slug}/works?limit=2&offset=2")
    assert len(page2.json()) == 1
```

Add `import uuid` at the top if it is not already there, and drop the now-unused `from app.models.book import Book` if nothing else in the file uses it.

- [ ] **Step 7: Run the tests**

Run: `docker compose exec -T -e DATABASE_URL=postgresql+asyncpg://margin:margin@db:5432/margin_test backend pytest tests/test_genre_works.py tests/test_shelves.py tests/test_pagination.py -q`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add backend/app/api/genres.py backend/app/api/users.py backend/tests
git commit -m "$(cat <<'EOF'
feat(api): list works on genre pages and profiles

A genre page listed edition rows, so it showed the same book five
times. It now lists works, hides collections, and skips merge
tombstones.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: Threads hang off works

**Files:**
- Modify: `backend/app/schemas/thread.py`, `backend/app/api/threads.py`
- Test: modify `backend/tests/test_threads.py`, `backend/tests/test_posts.py`, `backend/tests/test_votes.py`

**Interfaces:**
- Produces: `ThreadCreate.work_id`, `ThreadOut.work_id`, `ThreadSummary.work_id`, `ThreadWorkRef` (replacing `ThreadBookRef`), `ThreadWithPosts.work`.

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/test_threads.py`:

```python
async def test_thread_is_created_against_a_work(client, auth_headers, work):
    resp = await client.post(
        "/api/threads/",
        json={"title": "Is Darrow a hero?", "work_id": str(work.id), "content": "Discuss."},
        headers=auth_headers,
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["work_id"] == str(work.id)


async def test_thread_detail_names_its_work(client, auth_headers, work):
    created = await client.post(
        "/api/threads/",
        json={"title": "Is Darrow a hero?", "work_id": str(work.id)},
        headers=auth_headers,
    )
    thread_id = created.json()["id"]
    resp = await client.get(f"/api/threads/{thread_id}")
    assert resp.status_code == 200
    assert resp.json()["work"] == {"id": str(work.id), "title": work.title}


async def test_thread_requires_exactly_one_target(client, auth_headers, work):
    both = await client.post(
        "/api/threads/",
        json={"title": "X", "work_id": str(work.id), "genre_slug": "fantasy"},
        headers=auth_headers,
    )
    assert both.status_code == 422

    neither = await client.post("/api/threads/", json={"title": "X"}, headers=auth_headers)
    assert neither.status_code == 422
```

Then, throughout `test_threads.py`, `test_posts.py` and `test_votes.py`, replace the `book` fixture with `work` and every `"book_id"` payload key and assertion with `"work_id"`.

- [ ] **Step 2: Run the test and verify it fails**

Run: `docker compose exec -T -e DATABASE_URL=postgresql+asyncpg://margin:margin@db:5432/margin_test backend pytest tests/test_threads.py -q`
Expected: FAIL — 422, `ThreadCreate` has no `work_id`

- [ ] **Step 3: Update the thread schemas**

In `backend/app/schemas/thread.py`:

```python
class ThreadCreate(BaseModel):
    # Accept the frontend's payload as-is: genre threads are created by `slug`
    # and the opening post body arrives as `content`.
    model_config = ConfigDict(populate_by_name=True)

    title: str
    work_id: UUID | None = None
    genre_id: UUID | None = None
    genre_slug: str | None = None
    body: str | None = Field(default=None, alias="content")

    @model_validator(mode="after")
    def exactly_one_target(self) -> "ThreadCreate":
        has_work = self.work_id is not None
        has_genre = self.genre_id is not None or self.genre_slug is not None
        if has_work == has_genre:  # both set or neither set
            raise ValueError(
                "Exactly one of work_id or genre (genre_slug/genre_id) must be provided."
            )
        return self
```

```python
class ThreadWorkRef(BaseModel):
    """Just enough of a work to render a link and a path segment."""

    model_config = {"from_attributes": True}

    id: UUID
    title: str
```

(Delete `ThreadBookRef`.) In `ThreadOut` and `ThreadSummary`, replace `book_id: UUID | None` with `work_id: UUID | None`.

- [ ] **Step 4: Update the threads router**

In `backend/app/api/threads.py`: replace the `Book` model import with `from app.models.work import Work`, import `ThreadWorkRef` instead of `ThreadBookRef`, and apply these three changes:

```python
    thread = Thread(
        title=payload.title,
        user_id=current_user.id,
        work_id=payload.work_id,
        genre_id=genre_id,
    )
```

```python
    work_ref = None
    if thread.work_id is not None:
        work = (
            await db.execute(select(Work.id, Work.title).where(Work.id == thread.work_id))
        ).first()
        if work is not None:
            work_ref = ThreadWorkRef(id=work.id, title=work.title)
```

Then in `ThreadWithPosts`, rename the field `book: ThreadBookRef | None = None` to `work: ThreadWorkRef | None = None`, and in all three `ThreadOut(...)` / `ThreadWithPosts(...)` constructions (create, detail, vote) replace `book_id=thread.book_id` with `work_id=thread.work_id` and `book=book_ref` with `work=work_ref`.

- [ ] **Step 5: Run the full backend suite**

Run: `docker compose exec -T -e DATABASE_URL=postgresql+asyncpg://margin:margin@db:5432/margin_test backend pytest -q`
Expected: PASS — all tests green

- [ ] **Step 6: Commit**

```bash
git add backend/app/schemas/thread.py backend/app/api/threads.py backend/tests
git commit -m "$(cat <<'EOF'
feat(api): hang threads off works, not editions

Threads take work_id, and thread detail names the work. This is the
change the whole feature exists for: one discussion per book.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 8: Backfill script

**Files:**
- Create: `backend/scripts/resolve_works.py`
- Test: `backend/tests/test_resolve_works_script.py`

**Interfaces:**
- Consumes: `works.resolve_editions`, `works.merge_works`, `open_library`, `AsyncSessionLocal`.
- Produces:
  - `async resolve_all(session: AsyncSession, *, upgrade: bool = False) -> dict[str, int]` with keys `editions_resolved`, `threads_linked`, `shelves_linked`, `works_upgraded`
  - CLI: `python -m scripts.resolve_works [--upgrade]`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_resolve_works_script.py`:

```python
import uuid

import respx
from httpx import Response
from sqlalchemy import select

from app.models import Book, Shelf, ShelfStatus, Thread, User, Work, WorkSource
from scripts.resolve_works import resolve_all

OL_URL = "https://openlibrary.org/search.json"

OL_RED_RISING = {
    "key": "/works/OL17076473W",
    "title": "Red Rising",
    "author_name": ["Pierce Brown"],
    "first_publish_year": 2014,
    "edition_count": 26,
    "isbn": ["9780345539809"],
}


async def seed_legacy_rows(db_session):
    """An edition with a thread and a shelf pointing at it — the pre-works world."""
    edition = Book(
        source="google_books",
        external_id=uuid.uuid4().hex[:12],
        title="Red Rising (Deluxe Slipcase Edition)",
        author="Pierce Brown",
        isbn_13="9780345539809",
    )
    user = User(email="b@example.com", username="backfiller", password_hash="x")
    db_session.add_all([edition, user])
    await db_session.flush()

    thread = Thread(title="Legacy thread", user_id=user.id, book_id=edition.id)
    shelf = Shelf(user_id=user.id, book_id=edition.id, status=ShelfStatus.read)
    db_session.add_all([thread, shelf])
    await db_session.flush()
    return edition, thread, shelf


@respx.mock
async def test_backfill_resolves_editions_and_moves_fks(db_session):
    respx.get(OL_URL).mock(return_value=Response(200, json={"docs": [OL_RED_RISING]}))
    edition, thread, shelf = await seed_legacy_rows(db_session)

    summary = await resolve_all(db_session)

    await db_session.refresh(edition)
    await db_session.refresh(thread)
    await db_session.refresh(shelf)
    assert edition.work_id is not None
    assert thread.work_id == edition.work_id
    assert shelf.work_id == edition.work_id
    assert summary["editions_resolved"] == 1
    assert summary["threads_linked"] == 1
    assert summary["shelves_linked"] == 1


@respx.mock
async def test_backfill_is_idempotent(db_session):
    respx.get(OL_URL).mock(return_value=Response(200, json={"docs": [OL_RED_RISING]}))
    await seed_legacy_rows(db_session)

    await resolve_all(db_session)
    second = await resolve_all(db_session)

    assert second["editions_resolved"] == 0
    assert second["threads_linked"] == 0
    assert second["shelves_linked"] == 0


@respx.mock
async def test_upgrade_promotes_a_heuristic_work_and_merges_it(db_session):
    # First pass with Open Library down produces a heuristic work.
    respx.get(OL_URL).mock(return_value=Response(503, json={}))
    edition, thread, _ = await seed_legacy_rows(db_session)
    await resolve_all(db_session)

    await db_session.refresh(edition)
    heuristic = await db_session.get(Work, edition.work_id)
    assert heuristic.source is WorkSource.heuristic

    # Second pass with Open Library answering upgrades and merges.
    respx.get(OL_URL).mock(return_value=Response(200, json={"docs": [OL_RED_RISING]}))
    summary = await resolve_all(db_session, upgrade=True)

    assert summary["works_upgraded"] == 1
    await db_session.refresh(edition)
    await db_session.refresh(thread)
    upgraded = await db_session.get(Work, edition.work_id)
    assert upgraded.source is WorkSource.openlibrary
    assert thread.work_id == upgraded.id

    await db_session.refresh(heuristic)
    assert heuristic.merged_into_id == upgraded.id


@respx.mock
async def test_backfill_leaves_no_thread_behind(db_session):
    """The gate migration 2 depends on: no thread keeps a book_id without a work_id."""
    respx.get(OL_URL).mock(return_value=Response(200, json={"docs": [OL_RED_RISING]}))
    await seed_legacy_rows(db_session)
    await resolve_all(db_session)

    orphans = (
        await db_session.execute(
            select(Thread).where(Thread.book_id.is_not(None), Thread.work_id.is_(None))
        )
    ).scalars().all()
    assert orphans == []
```

- [ ] **Step 2: Run the test and verify it fails**

Run: `docker compose exec -T -e DATABASE_URL=postgresql+asyncpg://margin:margin@db:5432/margin_test backend pytest tests/test_resolve_works_script.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'scripts.resolve_works'`

- [ ] **Step 3: Write the script**

Create `backend/scripts/resolve_works.py`:

```python
"""Backfill: give every edition a work, then move threads and shelves onto it.

Alembic must not make HTTP calls, so identity resolution lives here, between
the two migrations. Run after migration 1 and before migration 2::

    docker compose exec backend python -m scripts.resolve_works

Idempotent: a second run resolves nothing. ``--upgrade`` re-attempts works that
fell back to the heuristic tier (because Open Library was unreachable or had no
record at the time) and merges each one into its Open Library work on success::

    docker compose exec backend python -m scripts.resolve_works --upgrade

Before running migration 2, confirm the gate is clean::

    SELECT count(*) FROM threads WHERE book_id IS NOT NULL AND work_id IS NULL;
"""

from __future__ import annotations

import argparse
import asyncio

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal
from app.models import Book, Shelf, Thread, Work, WorkSource
from app.services import open_library
from app.services.works import merge_works, resolve_editions

# Google Books pages are 20 volumes; one Open Library call covers a batch.
_BATCH = 20


async def resolve_all(session: AsyncSession, *, upgrade: bool = False) -> dict[str, int]:
    """Resolve unresolved editions, link threads and shelves, optionally upgrade.

    Returns a summary dict with ``editions_resolved``, ``threads_linked``,
    ``shelves_linked`` and ``works_upgraded``.
    """
    editions = (
        await session.execute(select(Book).where(Book.work_id.is_(None)))
    ).scalars().all()

    for start in range(0, len(editions), _BATCH):
        await resolve_editions(session, editions[start : start + _BATCH])
    await session.flush()

    threads_linked = await _link_through_editions(session, Thread)
    shelves_linked = await _link_through_editions(session, Shelf)

    upgraded = await _upgrade_heuristic_works(session) if upgrade else 0

    await session.commit()
    return {
        "editions_resolved": len(editions),
        "threads_linked": threads_linked,
        "shelves_linked": shelves_linked,
        "works_upgraded": upgraded,
    }


async def _link_through_editions(session: AsyncSession, model) -> int:
    """Copy ``work_id`` onto rows that still only know their edition."""
    result = await session.execute(
        update(model)
        .where(model.work_id.is_(None), model.book_id.is_not(None))
        .values(
            work_id=select(Book.work_id).where(Book.id == model.book_id).scalar_subquery()
        )
    )
    return result.rowcount or 0


async def _upgrade_heuristic_works(session: AsyncSession) -> int:
    """Re-attempt Open Library for heuristic works; merge each success."""
    works = (
        await session.execute(
            select(Work).where(
                Work.source == WorkSource.heuristic, Work.merged_into_id.is_(None)
            )
        )
    ).scalars().all()

    upgraded = 0
    for work in works:
        editions = (
            await session.execute(select(Book).where(Book.work_id == work.id))
        ).scalars().all()

        isbns = [e.isbn_13 for e in editions if e.isbn_13]
        found = None
        if isbns:
            by_isbn = await open_library.resolve_by_isbns(isbns)
            found = next(iter(by_isbn.values()), None)
        if found is None:
            found = await open_library.resolve_by_title_author(work.title, work.author)
        if found is None:
            continue

        target = (
            await session.execute(
                select(Work).where(
                    Work.source == WorkSource.openlibrary, Work.external_id == found.key
                )
            )
        ).scalar_one_or_none()

        if target is None:
            # Promote in place: same row, real identity. Cheaper and safer than
            # creating a twin and merging into it.
            work.source = WorkSource.openlibrary
            work.external_id = found.key
            work.title = found.title
            work.author = found.author or work.author
            work.first_publish_year = found.first_publish_year or work.first_publish_year
            from app.models import WorkProvenance

            work.identity_provenance = (
                WorkProvenance.isbn if isbns else WorkProvenance.title_author
            )
        else:
            await merge_works(session, work, target)
        upgraded += 1

    await session.flush()
    return upgraded


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--upgrade",
        action="store_true",
        help="re-attempt Open Library for works that fell back to the heuristic tier",
    )
    args = parser.parse_args()

    async with AsyncSessionLocal() as session:
        summary = await resolve_all(session, upgrade=args.upgrade)

    print(
        "Work resolution complete: "
        f"{summary['editions_resolved']} editions resolved, "
        f"{summary['threads_linked']} threads linked, "
        f"{summary['shelves_linked']} shelves linked, "
        f"{summary['works_upgraded']} works upgraded."
    )


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 4: Run the test and verify it passes**

Run: `docker compose exec -T -e DATABASE_URL=postgresql+asyncpg://margin:margin@db:5432/margin_test backend pytest tests/test_resolve_works_script.py -q`
Expected: PASS (4 tests)

- [ ] **Step 5: Run the backfill against the dev database**

```bash
docker compose exec backend alembic upgrade head
docker compose exec backend python -m scripts.resolve_works
docker compose exec -T db psql -U margin -d margin -c \
  "SELECT count(*) AS orphan_threads FROM threads WHERE book_id IS NOT NULL AND work_id IS NULL;"
```
Expected: the script reports ~223 editions resolved and 8 threads linked; the gate query returns 0.

- [ ] **Step 6: Commit**

```bash
git add backend/scripts/resolve_works.py backend/tests/test_resolve_works_script.py
git commit -m "$(cat <<'EOF'
feat(api): add work resolution backfill script

Sits between the two migrations, because Alembic must not make HTTP
calls. Idempotent, and --upgrade re-attempts works that fell back to
the heuristic tier.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 9: Migration 2 — drop the edition foreign keys

**Files:**
- Create: `backend/alembic/versions/<rev>_drop_book_fks.py`
- Modify: `backend/app/models/{book,thread,shelf,genre}.py`

**Interfaces:**
- Produces: `Thread.book_id`, `Shelf.book_id`, `Book.genre_id` gone from both the models and the database; `shelves.work_id` NOT NULL; `uq_shelf_user_work` replaces `uq_shelf_user_book`.

**Deviation from the spec, and why.** The spec ends by setting `books.work_id NOT NULL`. Do not: an edition is inserted and flushed *before* it is resolved (`_upsert_editions` needs the generated id to build the resolution batch), so a NOT NULL column makes the upsert order illegal, and Postgres cannot defer NOT NULL. `shelves.work_id` still becomes NOT NULL — a shelf row is never created without a work. The editions invariant is enforced by the resolver and asserted by `test_backfill_resolves_unlinked_editions`, not by the column.

- [ ] **Step 1: Confirm the gate is clean**

```bash
docker compose exec -T db psql -U margin -d margin -c \
  "SELECT count(*) AS orphan_threads FROM threads WHERE book_id IS NOT NULL AND work_id IS NULL;"
docker compose exec -T db psql -U margin -d margin -c \
  "SELECT count(*) AS unresolved_editions FROM books WHERE work_id IS NULL;"
```
Expected: both 0. **If either is non-zero, stop** and re-run `python -m scripts.resolve_works` — this migration is the destructive one.

- [ ] **Step 2: Remove the superseded columns from the models**

In `backend/app/models/book.py`, delete the `genre_id` column and the `genre` relationship. Leave `work_id` nullable — see the deviation note above — and say so in the column's comment:

```python
    # Nullable by necessity, not by design: an edition is inserted and flushed
    # before resolution can batch it. Every edition ends a transaction with a
    # work; the resolver enforces that, not the column.
    work_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("works.id", ondelete="CASCADE"), nullable=True, index=True
    )
```

In `backend/app/models/thread.py`, delete the `book_id` column and the `book` relationship.

In `backend/app/models/shelf.py`, delete the `book_id` column and the `book` relationship, make `work_id` non-nullable, and replace the table args:

```python
    __table_args__ = (UniqueConstraint("user_id", "work_id", name="uq_shelf_user_work"),)
```

```python
    work_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("works.id", ondelete="CASCADE"), nullable=False, index=True
    )
```

In `backend/app/models/genre.py`, delete the `books` relationship (genres reach books through works now).

- [ ] **Step 3: Write migration 2**

```bash
docker compose exec backend alembic revision -m "drop book fks in favour of works"
```

Replace the body of the generated file (its `down_revision` is migration 1's revision id):

```python
def upgrade() -> None:
    op.drop_constraint("uq_shelf_user_book", "shelves", type_="unique")
    op.create_unique_constraint("uq_shelf_user_work", "shelves", ["user_id", "work_id"])

    op.drop_column("shelves", "book_id")
    op.drop_column("threads", "book_id")
    op.drop_column("books", "genre_id")

    # books.work_id stays nullable: editions are flushed before they are
    # resolved. shelves.work_id is always known at insert time.
    op.alter_column("shelves", "work_id", existing_type=sa.UUID(), nullable=False)


def downgrade() -> None:
    op.alter_column("shelves", "work_id", existing_type=sa.UUID(), nullable=True)

    op.add_column("books", sa.Column("genre_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        "books_genre_id_fkey", "books", "genres", ["genre_id"], ["id"], ondelete="SET NULL"
    )
    op.create_index("ix_books_genre_id", "books", ["genre_id"])

    op.add_column("threads", sa.Column("book_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        "threads_book_id_fkey", "threads", "books", ["book_id"], ["id"], ondelete="CASCADE"
    )
    op.create_index("ix_threads_book_id", "threads", ["book_id"])

    op.add_column("shelves", sa.Column("book_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        "shelves_book_id_fkey", "shelves", "books", ["book_id"], ["id"], ondelete="CASCADE"
    )
    op.create_index("ix_shelves_book_id", "shelves", ["book_id"])

    op.drop_constraint("uq_shelf_user_work", "shelves", type_="unique")
    op.create_unique_constraint("uq_shelf_user_book", "shelves", ["user_id", "book_id"])
```

Note: the downgrade restores the columns but **not their data** — the edition-level link is gone once this runs. That is the intent, and the reason for the gate in Step 1.

- [ ] **Step 4: Drop `book_id` from the script's linking step**

`_link_through_editions` in `backend/scripts/resolve_works.py` reads `Thread.book_id` and `Shelf.book_id`, which no longer exist. Replace it with a no-op that is honest about why:

```python
async def _link_through_editions(session: AsyncSession, model) -> int:
    """No-op since migration 2: threads and shelves carry work_id directly.

    Kept so the summary shape and the CLI output stay stable for anyone
    following the runbook in this module's docstring.
    """
    return 0
```

And delete the two now-dead tests in `backend/tests/test_resolve_works_script.py` — `test_backfill_resolves_editions_and_moves_fks`'s FK assertions and `test_backfill_leaves_no_thread_behind` — replacing the first with:

```python
@respx.mock
async def test_backfill_resolves_unlinked_editions(db_session):
    respx.get(OL_URL).mock(return_value=Response(200, json={"docs": [OL_RED_RISING]}))
    edition = Book(
        source="google_books",
        external_id=uuid.uuid4().hex[:12],
        title="Red Rising (Deluxe Slipcase Edition)",
        author="Pierce Brown",
        isbn_13="9780345539809",
    )
    db_session.add(edition)
    await db_session.flush()

    summary = await resolve_all(db_session)

    await db_session.refresh(edition)
    assert edition.work_id is not None
    assert summary["editions_resolved"] == 1
```

Replace `seed_legacy_rows` with a version that seeds an unresolved edition and nothing else, since a thread can no longer name one:

```python
async def seed_unresolved_edition(db_session):
    edition = Book(
        source="google_books",
        external_id=uuid.uuid4().hex[:12],
        title="Red Rising (Deluxe Slipcase Edition)",
        author="Pierce Brown",
        isbn_13="9780345539809",
    )
    db_session.add(edition)
    await db_session.flush()
    return edition
```

`test_backfill_is_idempotent` and `test_upgrade_promotes_a_heuristic_work_and_merges_it` both call it instead of `seed_legacy_rows`. In the upgrade test, create the thread *after* the first `resolve_all`, pointing at the resolved work:

```python
    await db_session.refresh(edition)
    user = User(email="b@example.com", username="backfiller", password_hash="x")
    db_session.add(user)
    await db_session.flush()
    thread = Thread(title="Legacy thread", user_id=user.id, work_id=edition.work_id)
    db_session.add(thread)
    await db_session.flush()
```

- [ ] **Step 5: Apply and verify the migration round-trips**

```bash
docker compose exec backend alembic upgrade head
docker compose exec backend alembic downgrade -1
docker compose exec backend alembic upgrade head
```
Expected: all three succeed.

- [ ] **Step 6: Run the full backend suite**

Run: `docker compose exec -T -e DATABASE_URL=postgresql+asyncpg://margin:margin@db:5432/margin_test backend pytest -q`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add backend
git commit -m "$(cat <<'EOF'
feat(api): drop edition foreign keys from threads and shelves

Completes the move: threads and shelves reference works only, shelves
are unique per (user, work), and books.work_id is NOT NULL. Run
scripts.resolve_works before this migration.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 10: Frontend API layer and `WorkCard`

**Files:**
- Create: `frontend/src/api/works.js`, `frontend/src/components/WorkCard.jsx`, `frontend/src/components/WorkCard.test.jsx`
- Delete: `frontend/src/api/books.js`, `frontend/src/components/BookCard.jsx`
- Modify: `frontend/src/pages/Search.jsx`, `frontend/src/pages/Profile.jsx`, `frontend/src/components/ShelfButton.jsx`

**Interfaces:**
- Produces: `useSearchWorks(query)`, `useWork(id)`, `useWorkThreads(id)`, `useAddToShelf()`, `useUpdateShelf()`, `useRemoveFromShelf()` (query key root `['works', ...]`); `<WorkCard work={...} />` linking to `/works/:id`.

- [ ] **Step 1: Write the failing test**

Create `frontend/src/components/WorkCard.test.jsx`:

```jsx
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import WorkCard from './WorkCard'

function renderCard(work) {
  return render(
    <MemoryRouter>
      <WorkCard work={work} />
    </MemoryRouter>,
  )
}

describe('WorkCard', () => {
  const work = {
    id: 'w1',
    title: 'Red Rising',
    author: 'Pierce Brown',
    cover_url: 'https://x/cover.jpg',
    edition_count: 26,
  }

  it('links to the work, not to an edition', () => {
    renderCard(work)
    expect(screen.getByRole('link')).toHaveAttribute('href', '/works/w1')
  })

  it('shows the cover with the title as its accessible name', () => {
    renderCard(work)
    expect(screen.getByRole('img', { name: 'Red Rising' })).toBeInTheDocument()
  })

  it('reports the edition count, so collapsing results reads as information', () => {
    renderCard(work)
    expect(screen.getByText('26 editions')).toBeInTheDocument()
  })

  it('says nothing about editions when there is only one', () => {
    renderCard({ ...work, edition_count: 1 })
    expect(screen.queryByText(/editions/)).not.toBeInTheDocument()
  })

  it('falls back to the title when there is no cover', () => {
    renderCard({ ...work, cover_url: null })
    expect(screen.queryByRole('img')).not.toBeInTheDocument()
    expect(screen.getAllByText('Red Rising').length).toBeGreaterThan(0)
  })
})
```

- [ ] **Step 2: Run the test and verify it fails**

Run: `cd frontend && npx vitest run src/components/WorkCard.test.jsx`
Expected: FAIL — cannot resolve `./WorkCard`

- [ ] **Step 3: Write the API module**

Create `frontend/src/api/works.js`:

```js
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import client from './client'

export function useSearchWorks(query) {
  return useQuery({
    queryKey: ['works', 'search', query],
    queryFn: () => client.get('/works/search', { params: { q: query } }).then((r) => r.data),
    enabled: query.length > 1,
  })
}

export function useWork(id) {
  return useQuery({
    queryKey: ['works', id],
    queryFn: () => client.get(`/works/${id}`).then((r) => r.data),
    enabled: !!id,
  })
}

export function useWorkThreads(id) {
  return useQuery({
    queryKey: ['works', id, 'threads'],
    queryFn: () => client.get(`/works/${id}/threads`).then((r) => r.data),
    enabled: !!id,
  })
}

export function useAddToShelf() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ id, status }) => client.post(`/works/${id}/shelf`, { status }).then((r) => r.data),
    onSuccess: (_, { id }) => {
      queryClient.invalidateQueries({ queryKey: ['works', id] })
      queryClient.invalidateQueries({ queryKey: ['me'] })
    },
  })
}

export function useUpdateShelf() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ id, status }) => client.put(`/works/${id}/shelf`, { status }).then((r) => r.data),
    onSuccess: (_, { id }) => {
      queryClient.invalidateQueries({ queryKey: ['works', id] })
      queryClient.invalidateQueries({ queryKey: ['me'] })
    },
  })
}

export function useRemoveFromShelf() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ id }) => client.delete(`/works/${id}/shelf`).then((r) => r.data),
    onSuccess: (_, { id }) => {
      queryClient.invalidateQueries({ queryKey: ['works', id] })
      queryClient.invalidateQueries({ queryKey: ['me'] })
    },
  })
}
```

- [ ] **Step 4: Write `WorkCard`**

Create `frontend/src/components/WorkCard.jsx`:

```jsx
import { Link } from 'react-router-dom'

function WorkCard({ work }) {
  const { id, title, author, cover_url, edition_count } = work

  return (
    <Link to={`/works/${id}`} className="group flex flex-col">
      {/* Covers carry most of the color in the UI (§13), so they stay large and
          unobstructed — the frame reacts on hover, the art never dims. */}
      <div className="aspect-[2/3] bg-panel border border-line group-hover:border-accent transition-colors duration-base overflow-hidden">
        {cover_url ? (
          <img
            src={cover_url}
            alt={title}
            loading="lazy"
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

- [ ] **Step 5: Repoint the consumers and delete the old modules**

In `frontend/src/pages/Search.jsx`: import `useSearchWorks` from `../api/works` and `WorkCard` from `../components/WorkCard`, rename the `books` binding to `works`, and render `<WorkCard key={work.id} work={work} />`.

In `frontend/src/pages/Profile.jsx`: import `WorkCard`, and in `ShelfSection` rename the `books` prop to `works` and render `<WorkCard key={work.id} work={work} />`.

In `frontend/src/components/ShelfButton.jsx`: import the mutations from `../api/works` and rename the `bookId` prop to `workId` (three `mutate({ id: bookId … })` call sites).

```bash
git rm frontend/src/api/books.js frontend/src/components/BookCard.jsx
```

- [ ] **Step 6: Run the frontend unit tests**

Run: `cd frontend && npm test`
Expected: `WorkCard.test.jsx` passes. `Book`-page tests do not exist yet, but any test importing the deleted modules fails — those are fixed in Task 11.

- [ ] **Step 7: Commit**

```bash
git add -A frontend
git commit -m "$(cat <<'EOF'
feat(web): work-based API hooks and WorkCard

One card per work, with an edition count so a collapsed result set
reads as information rather than as search having gotten worse.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 11: The work page and the routes

**Files:**
- Create: `frontend/src/pages/Work.jsx`
- Delete: `frontend/src/pages/Book.jsx`
- Modify: `frontend/src/App.jsx`, `frontend/src/pages/{Genre,Thread}.jsx`, `frontend/src/api/threads.js`, `frontend/src/components/ThreadModal.jsx`, `frontend/src/components/ThreadModal.test.jsx`

**Interfaces:**
- Produces: routes `/works/:id` and `/works/:id/threads/:threadId`; `ThreadModal` target `{ work_id }`; thread query invalidation under `['works', id, 'threads']`.

- [ ] **Step 1: Create the work page from the book page**

```bash
git mv frontend/src/pages/Book.jsx frontend/src/pages/Work.jsx
```

In `frontend/src/pages/Work.jsx`, apply these changes and nothing else — the layout, the `DataTable`, the `ShelfButton` placement and the §36 balance all stay as they are:

- `import { useWork, useWorkThreads } from '../api/works'`
- rename the component and its default export to `Work`
- rename the `book` binding to `work` throughout (including `bookLoading` → `workLoading`, `bookError` → `workError`)
- status bar: `path: work ? \`~/works/${slug(work.title)}\` : '~/works'`
- breadcrumb: `segments={[{ label: 'works', to: '/' }, { label: work.title }]}`
- thread links: `to={\`/works/${id}/threads/${row.id}\`}`
- vote mutation: `voteMutation.mutate({ id: row.id, value, workId: id })`
- shelf button: `<ShelfButton workId={id} currentStatus={work.shelf_status} />`
- thread modal: `target={{ work_id: id }}` and `onCreated={(thread) => navigate(\`/works/${id}/threads/${thread.id}\`)}`
- error copy: `Failed to load work.`
- the `published_year`, `publisher`, `page_count`, `categories` and `description` blocks read from `work` — `first_publish_year` replaces `published_year`:

```jsx
            {work.first_publish_year && (
              <div>
                <dt className="text-ink-dim text-xs lowercase tracking-eyebrow">first published</dt>
                <dd className="text-ink tabular-nums">{work.first_publish_year}</dd>
              </div>
            )}
            {work.edition_count > 1 && (
              <div>
                <dt className="text-ink-dim text-xs lowercase tracking-eyebrow">editions</dt>
                <dd className="text-ink tabular-nums">{work.edition_count}</dd>
              </div>
            )}
```

Delete the `publisher`, `page_count` and `categories` blocks: those are edition facts, and `WorkOut` does not carry them.

- [ ] **Step 2: Update the routes**

In `frontend/src/App.jsx`:

```jsx
import Work from './pages/Work'
```

```jsx
          <Route path="/works/:id" element={<Work />} />
          <Route path="/works/:id/threads/:threadId" element={<Thread />} />
```

- [ ] **Step 3: Update the remaining consumers**

`frontend/src/pages/Genre.jsx`:

```jsx
  const { data: works } = useQuery({
    queryKey: ['genres', genreSlug, 'works'],
    queryFn: () => client.get(`/genres/${genreSlug}/works`).then((r) => r.data),
  })
```

and render `<WorkCard key={work.id} work={work} />` under the heading, which becomes `Notable works`.

`frontend/src/pages/Thread.jsx`:

```jsx
  const anchor = thread?.work?.title || thread?.genre?.name || ''
```

```jsx
  if (thread.work) {
    segments.push({ label: 'works', to: '/' })
    segments.push({ label: thread.work.title, to: `/works/${thread.work.id}` })
  }
```

`frontend/src/api/threads.js` — both invalidation sites:

```js
      if (data.work_id) {
        queryClient.invalidateQueries({ queryKey: ['works', String(data.work_id), 'threads'] })
      }
```

```js
    onSuccess: (_, { id, workId, genreSlug }) => {
      queryClient.invalidateQueries({ queryKey: ['threads', String(id)] })
      if (workId) {
        queryClient.invalidateQueries({ queryKey: ['works', String(workId), 'threads'] })
      }
```

`frontend/src/components/ThreadModal.jsx` — update the docstring comment to name `{ work_id }`, and in `ThreadModal.test.jsx` change the target prop to `target={{ work_id: '1' }}`.

- [ ] **Step 4: Run the frontend unit tests and the build**

```bash
cd frontend && npm test && npm run build
```
Expected: all tests pass, build succeeds with no unresolved imports.

- [ ] **Step 5: Look at a real work page**

```bash
docker compose up --build -d
```
Open `http://localhost:5173`, search `red rising`, and confirm: one Red Rising card (not five), an edition count on it, no bundles, and that the card opens `/works/<id>` with its discussion table intact.

- [ ] **Step 6: Commit**

```bash
git add -A frontend
git commit -m "$(cat <<'EOF'
feat(web): work pages replace book pages

Routes move to /works/:id, the page reads first_publish_year and an
edition count, and thread creation targets work_id. Edition-only facts
(publisher, page count) come off the page with the edition.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 12: E2E, docs and full verification

**Files:**
- Modify: `frontend/e2e/helpers.js`, `frontend/e2e/{thread,reply}.spec.js`, `CLAUDE.md`, `ROADMAP.md`

- [ ] **Step 1: Repoint the e2e helper**

In `frontend/e2e/helpers.js`, update the search-result navigation:

```js
// Opens the first work returned by a search and waits for the work detail page.
  const firstWork = page.locator('a[href^="/works/"]').first()
  await firstWork.click()
  await expect(page).toHaveURL(/\/works\//)
```

The exported helper is `openFirstSearchResult(page, query)` — the name still fits, so only its internals and comment change. Update the comments in `thread.spec.js` and `reply.spec.js` ("book page" → "work page") and the `thread.spec.js` test name `create a thread on a book page` → `create a thread on a work page`.

- [ ] **Step 2: Run the e2e suite**

```bash
docker compose up --build -d
cd frontend && npm run test:e2e
```
Expected: all specs pass. The thread and reply specs use live Google Books *and* live Open Library now — if Open Library is slow, the heuristic tier still groups the results, so the specs must not depend on a work's `edition_count`.

- [ ] **Step 3: Update `CLAUDE.md`**

In the **Backend** section, extend the `services/` bullet:

```
`open_library.py` resolves *work identity* (the work/edition graph Google Books
lacks: batched `isbn:(...)` search, then title+author with an `edition_count`
tiebreak, never raising on upstream failure); `works.py` owns the resolution
ladder, representative-edition selection and `merge_works`.
```

Add a new subsection after **Password reset**:

```markdown
**Works vs editions**: `books` rows are *editions* (one Google Books volume
each); `works` is what users search, discuss and shelf. `threads.work_id` and
`shelves.work_id` point at works only — never re-introduce an edition-level FK,
or discussion splits across printings again. A work's identity is
`('openlibrary', 'OL…W')` when Open Library resolved it, otherwise
`('heuristic', sha1(canonical_key))`, recorded in `identity_provenance`.
`canonical_key` is stored on *every* work, including Open Library ones: it is
how a heuristic work is later recognised as the same book and merged.
Heuristic → OL merges happen automatically; OL → OL merges never do.
Collections (box sets, omnibuses) are stored with `kind='collection'` and
filtered out of search, not dropped at ingest.

After a deploy that adds editions predating the works table, run
`python -m scripts.resolve_works` (and `--upgrade` to promote heuristic works).
```

In **Known remaining gaps**, add:

```
- **No admin merge/split UI**: `merge_works()` and `scripts.resolve_works
  --upgrade` are the only repair tools; a mis-grouped work needs a shell.
```

- [ ] **Step 4: Update `ROADMAP.md`**

Replace the "Duplicate search results" row in Phase 1 with:

```
| ✅ | **Work grouping** — `works` table with Open Library identity (batched ISBN → title+author → labelled heuristic); threads and shelves hang off works, collections hidden from search, `merge_works` for repair. Supersedes the per-response edition dedup. | `backend/app/services/{works,open_library,work_identity}.py`, `backend/app/api/works.py` |
```

Add to Phase 5:

```
| ⬜ | **Admin merge/split for works** — surface `merge_works()`; split a work whose editions were wrongly grouped. | `backend/app/services/works.py`, new frontend area |
```

And fix the stale Phase 6 row, since password reset shipped:

```
| ⬜ | **Email verification** — password reset already ships (`/auth/forgot-password`). | `backend/app/api/auth.py`, email service |
```

- [ ] **Step 5: Full verification**

Run every suite and record the actual output:

```bash
docker compose exec -T -e DATABASE_URL=postgresql+asyncpg://margin:margin@db:5432/margin_test backend pytest -q
cd frontend && npm test && npm run build
cd frontend && npm run test:e2e
docker compose exec backend alembic upgrade head
docker compose exec backend alembic downgrade -2 && docker compose exec backend alembic upgrade head
```
Expected: backend green, frontend green, build clean, e2e green, migrations round-trip twice.

- [ ] **Step 6: Search the codebase for leftovers**

```bash
grep -rn "api/books\|/books/\|book_id\|BookCard\|useBook" backend/app frontend/src frontend/e2e --include='*.py' --include='*.js' --include='*.jsx'
```
Expected: no hits outside comments that deliberately describe the old model. Any hit is a missed rename.

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "$(cat <<'EOF'
docs: record works-vs-editions model; repoint e2e at work pages

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Notes for the executor

- **Branch from `main` after `feat/terminal-ui` merges.** This plan renames files that branch is actively rewriting (`pages/Book.jsx`, `components/BookCard.jsx`); stacking the two guarantees conflicts.
- **Tasks 3, 8 and 9 are a sequence, not three independent changes.** Migration 1 → backfill script → gate → migration 2. Running migration 2 before the script destroys the only link between a thread and its book.
- **If Open Library is unreachable while you work**, the heuristic tier keeps everything functional and the tests all mock upstream anyway. Do not add retries or a cache — `books.work_id` already is the cache.

