# Series Health Checks + Librarian Queue Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bring the work to the librarian: a `queue` tab on `/librarian` that lists what is wrong with the catalog's series (gaps in the numbering, two books at one place, books shown without a cover, real series of one book), each linking into that series page in edit mode, at the book concerned.

**Architecture:** Nothing is stored. `services/librarian/health.py` runs one SQL statement per check, over live real rooms only, and each statement returns only the rows the requested page needs (`LIMIT offset + limit`), so the database does the scanning and Python never holds the catalog. The whole request runs under a transaction-local `statement_timeout` budget and answers 503 past it rather than tying up a worker. The checks reuse the series page's own rules: placement by the deepest membership in the room's tree (`services/series.placed_memberships`) and the cover ladder of `load_work_presentation`, expressed once as SQL (`works.NO_COVER_SQL`) and pinned to the Python ladder by a test. A new thin router `api/librarian_queue.py` (prefix `/librarian/queue`) serves `GET health`; items 14 and 15 add their queue routes to the same router. The frontend splits `/librarian` into `fixes | queue` tabs (`?tab=queue`) and defines the queue section contract (`QueueSection` shell + `queueSections.js` registry) that 14 and 15 plug into.

**Tech Stack:** FastAPI, async SQLAlchemy 2.0 (`text()` SQL with a recursive CTE), Pydantic v2, React 18 + React Query v5 (`useInfiniteQuery`) + Tailwind tokens, Vitest + RTL, Playwright.

**Spec:** `docs/librarian-ux-roadmap.md` §13 (item "13 · Series health checks + librarian queue", plus "Shared names" → Frontend and Backend → Queue). Read it and `docs/superpowers/specs/2026-09-28-librarian-tools-design.md` (v1) before starting.

**Roadmap item:** 13 — tick in docs/librarian-ux-roadmap.md when merged

- [ ] Item 13 merged (tick this, and the tracker row, when the PR merges)

## Global Constraints

- Repo rules in `CLAUDE.md` apply verbatim: `api/` thin, services decide; async everywhere; schemas built explicitly (never `model_validate` of an ORM object with relationships); design tokens only; serif only for book titles and series names; no new radii/shadows/font sizes/durations; `aria-hidden` on every glyph; §36 test before calling a screen done.
- Route and shape, verbatim from the roadmap: `GET /api/librarian/queue/health` → `[HealthIssue {kind: 'gap' | 'duplicate_position' | 'missing_cover' | 'single_book_series', series_id, series_slug, series_name, work_ids, detail}]`.
- Computed on request, no table. This item has **no migration**.
- The `/librarian` page is tabbed `fixes` (the existing table) · `queue`; the tab is in the URL: `/librarian?tab=queue`. The queue tab renders sections in the order **reports** (15) · **duplicates** (14) · **series health** (13).
- Every librarian route depends on `require_librarian`; the test module that adds a route asserts 401 anonymous (or 403, as v1's `test_every_route_refuses_readers_and_anonymous` accepts) and 403 reader.
- New librarian components live in `frontend/src/components/librarian/`.
- Tests: pytest against `margin_test`, Vitest + RTL, one Playwright scenario. Network always mocked (the e2e scenario mocks the API responses it depends on with `page.route`).
- Branch `feat/librarian-lx13-series-health-queue` from `main`; commit per task; PR to `main`.
- Backend tests run in the backend container against `margin_test`. From the repo root, with `docker compose up -d db` running (and `margin_test` created once, see `CLAUDE.md`):
  `docker compose run --rm --no-deps -e DATABASE_URL=postgresql+asyncpg://margin:margin@db:5432/margin_test backend pytest <args>`
  Referred to below as **`PYTEST`**.

## Decisions this plan adds to the roadmap

1. **Only live real rooms are checked**: `series.kind = 'series'`, not tombstoned (`merged_into_id IS NULL`), not dissolved, top-level (`parent_series_id IS NULL`). Singletons are one book's page, so "missing cover" on the ~every-runtime-work singleton would bury the queue; they are out of scope for all four checks. A sub-series is checked *inside* its room (below), never as a room of its own.
2. **Positions are the ones the page shows.** A book is placed by its membership in the deepest series of its room's tree (the rule `services/series.placed_memberships` and `api/series._members` use), so a gap or a shared place is reported per placed series: a room's own numbering and each sub-series' numbering separately. A room-level membership hidden behind a deeper one is ignored, because the librarian cannot see or fix it from the page (`set_position` edits the placed one).
3. **What a gap is:** among a placed series' whole-number positions ≥ 1, each missing integer from 1 up to the highest. Fractional positions (2.5) neither fill nor open a gap; unnumbered books are ignored. A series whose highest position is above `MAX_GAP_POSITION = 200` is not gap-checked: its "positions" are years or catalog numbers, and listing every missing integer would bury real gaps. `work_ids` for a gap are the books right *after* each missing place (where the librarian lands to fix it).
4. **One issue per series for `missing_cover` and `single_book_series`** (all coverless books of a room in one row's `work_ids`); one issue per placed series for `gap`; one issue per (placed series, position) for `duplicate_position`.
5. **Bounded, paginated.** `?kind=&limit=&offset=`: `limit` 1–200 (default 50), `offset` 0–1000. Issues are ordered by kind (the roadmap's order above), then series name, then series id. Each kind's SQL returns at most `offset + limit` rows in that order, so a page is a slice of their concatenation and no statement returns more than 1200 rows. The request runs under `statement_timeout = 10s` (`BUDGET_MS`), set transaction-locally with `set_config(..., true)` and restored afterwards; a cancelled statement (SQLSTATE `57014`) becomes `QueueTooSlow` → **503** "The queue took too long to compute; show one kind at a time."
6. **A new router module**, `api/librarian_queue.py` (`APIRouter(prefix="/librarian/queue", tags=["librarian"])`), registered in `main.py`. 14 and 15 add their `/api/librarian/queue/...` routes there, keeping `api/librarian.py` about fixes.
7. **Links** go to `/series/<series_slug>?edit=1&book=<work_ids[0]>` (just `?edit=1` when `work_ids` is empty). `?edit=1` still turns edit mode on after item 01, and `?book=` already scrolls to and highlights that row.
8. **The queue section contract** (what 14 and 15 build on) is defined in Task 4 and restated here:
   - A section is a component in `components/librarian/`, taking **no props**, owning its own data hook(s), and rendering exactly one `<QueueSection>` with `id` equal to its registry key.
   - `components/librarian/queueSections.js` exports `QUEUE_ORDER = ['reports', 'duplicates', 'health']` (never reordered) and `QUEUE_SECTIONS = { <key>: Component }`. 13 registers `health`; 14 adds `duplicates: DuplicatesSection`; 15 adds `reports: ReportsSection`. The queue tab renders `QUEUE_ORDER.filter((k) => QUEUE_SECTIONS[k])` — so an unshipped section renders nothing: no placeholder, no "coming soon".
   - `<QueueSection id title count hasMore loading error emptyMessage onMore loadingMore controls>{children}</QueueSection>` renders a `<section aria-labelledby="queue-<id>">` (an ARIA region named by its title), a heading with the count (`50+` when more pages exist), optional `controls` (filters), and exactly one of: a loading bar, the error (`errorMessage`), the `emptyMessage` (when `count === 0`), or `children`; then a `more` button when `hasMore`.
   - Paging uses `QUEUE_PAGE = 50` and `QUEUE_MAX_OFFSET = 1000` from `api/librarian.js`, with `useInfiniteQuery` and `getNextPageParam: nextQueueOffset`.

## Review Focus

1. **A catalog numbered by year (positions 1965, 1966, …).** A naive gap check lists ~1960 missing places per series and buries the queue. Expected: no gap issue above `MAX_GAP_POSITION` (Task 2 `test_year_positions_are_not_gaps`).
2. **A sub-series inside a room (Mistborn in the Cosmere).** A book with a room-level position *and* a sub-series position must be checked only at the place the page shows it, or the queue reports a gap the librarian cannot see (Task 2 `test_sub_series_are_checked_where_the_page_places_books`).
3. **A tombstoned or dissolved row.** A merged-away work must not count as a series' second book or as a coverless book; a dissolved series and a singleton must not appear at all (Task 2 `test_single_book_series_counts_live_books_in_live_rooms`, `test_missing_cover_follows_the_page_ladder`).
4. **A cover the page shows through the OL fallback, or an empty-string edition cover.** The queue must agree with the page exactly, in both directions (Task 1 `test_no_cover_sql_matches_the_page_ladder`).
5. **A big catalog.** The request must neither return unbounded rows nor hang: the page is a slice, `offset` is capped, and a statement past the budget answers 503 with a readable message (Task 2 `test_pages_are_slices_of_the_kind_ordered_list`, `test_a_statement_past_its_budget_is_queue_too_slow`; Task 3 `test_a_slow_queue_is_503`, `test_paging_is_bounded`).

---

## File Structure

**Backend — create**
- `backend/app/services/librarian/health.py` — `KINDS`, `MAX_GAP_POSITION`, `BUDGET_MS`, `statement_budget`, `health_issues`.
- `backend/app/api/librarian_queue.py` — the queue router (`GET /health` now; 14 and 15 add routes).
- `backend/tests/test_cover_ladder_sql.py`, `backend/tests/test_librarian_health.py`, `backend/tests/test_librarian_queue_api.py`.

**Backend — modify**
- `backend/app/services/works.py` (`NO_COVER_SQL`), `backend/app/services/librarian/errors.py` (`QueueTooSlow`), `backend/app/schemas/librarian.py` (`HealthKind`, `HealthIssue`), `backend/app/main.py` (register the router).

**Frontend — create**
- `frontend/src/components/librarian/QueueSection.jsx`, `frontend/src/components/librarian/HealthSection.jsx`, `frontend/src/components/librarian/queueSections.js`, and tests `HealthSection.test.jsx`, `queueSections.test.js`.
- `frontend/e2e/librarian-queue.spec.js`.

**Frontend — modify**
- `frontend/src/api/librarian.js` (`QUEUE_PAGE`, `QUEUE_MAX_OFFSET`, `nextQueueOffset`, `useHealthIssues`), `frontend/src/pages/Librarian.jsx` (tabs + queue tab), `frontend/src/pages/Librarian.test.jsx`.

**Docs — modify:** `docs/librarian-ux-roadmap.md`, `ROADMAP.md`, `CLAUDE.md`, `README.md`.

---

### Task 1: Start the item; the cover ladder as SQL

**Files:**
- Modify: `backend/app/services/works.py` (add `NO_COVER_SQL` right above `class WorkPresentation`), `docs/librarian-ux-roadmap.md` (tracker row 13)
- Test: `backend/tests/test_cover_ladder_sql.py`

**Interfaces:**
- Consumes: `load_work_presentation(db, work_ids) -> dict[UUID, WorkPresentation]` (existing, `services/works.py`); factories `make_series`, `make_work`, `make_edition` (`tests/librarian_factories.py`).
- Produces: `NO_COVER_SQL: str` in `app.services.works` — a SQL boolean expression over the aliases `w` (`works`) and `rep` (`books`, the representative edition, LEFT JOINed on `rep.id = w.representative_book_id`) that is true exactly when `load_work_presentation` answers `cover_url=None`. Task 2 uses it.

- [ ] **Step 1: Branch and mark the item started**

```bash
git switch main && git pull --ff-only
git switch -c feat/librarian-lx13-series-health-queue
```

In `docs/librarian-ux-roadmap.md`, tracker row 13: set Status to `🟡` and Branch to `feat/librarian-lx13-series-health-queue`.

- [ ] **Step 2: Write the failing test**

`backend/tests/test_cover_ladder_sql.py`:

```python
"""NO_COVER_SQL is load_work_presentation's cover ladder, as SQL.

The health queue reports "missing cover" in SQL; the series page decides the
cover in Python. They must agree on every rung, or the queue sends a librarian
to fix a cover the page already shows (or hides a blank one)."""

from sqlalchemy import text

from app.services.works import NO_COVER_SQL, load_work_presentation
from tests.librarian_factories import make_edition, make_series, make_work


async def _with_rep(db, work, cover_url):
    edition = await make_edition(db, work)
    edition.cover_url = cover_url
    work.representative_book_id = edition.id
    await db.flush()


async def test_no_cover_sql_matches_the_page_ladder(db_session):
    room = await make_series(db_session, "Ladder")
    bare = await make_work(db_session, "Bare", series=room)                 # nothing at all
    ol_only = await make_work(db_session, "OL Only", series=room)           # OL's curated image
    ol_only.ol_cover_id = 42
    ol_zero = await make_work(db_session, "OL Zero", series=room)           # cover_id 0 is no cover
    ol_zero.ol_cover_id = 0
    rep = await make_work(db_session, "Rep", series=room)                   # the edition's cover
    await _with_rep(db_session, rep, "https://books.example/rep.jpg")
    rep_blank = await make_work(db_session, "Rep Blank", series=room)       # '' is no cover
    await _with_rep(db_session, rep_blank, "")
    rep_none_ol = await make_work(db_session, "Rep None OL", series=room)   # edition without, OL with
    await _with_rep(db_session, rep_none_ol, None)
    rep_none_ol.ol_cover_id = 7
    await db_session.flush()
    works = [bare, ol_only, ol_zero, rep, rep_blank, rep_none_ol]

    shown = await load_work_presentation(db_session, [w.id for w in works])
    page_says = {w.id for w in works if shown[w.id].cover_url is None}
    sql_says = set((await db_session.execute(text(
        f"SELECT w.id FROM works w LEFT JOIN books rep ON rep.id = w.representative_book_id "
        f"WHERE w.id = ANY(:ids) AND {NO_COVER_SQL}"), {"ids": [w.id for w in works]})).scalars())

    assert page_says == {bare.id, ol_zero.id, rep_blank.id}
    assert sql_says == page_says
```

- [ ] **Step 3: Run it to verify it fails**

Run: `PYTEST tests/test_cover_ladder_sql.py -q`
Expected: collection error, `ImportError: cannot import name 'NO_COVER_SQL' from 'app.services.works'`.

- [ ] **Step 4: Add the SQL twin**

In `backend/app/services/works.py`, directly above `class WorkPresentation(NamedTuple):`:

```python
# load_work_presentation's cover ladder as a SQL condition, for queries that
# must agree with the page without loading every work (the librarian health
# queue). True exactly when the page shows no cover: no representative edition
# cover (Python's `or` treats '' as none), and no OL curated image
# (open_library.cover_url returns None for a falsy id, so 0 is none too).
# Aliases: `w` is works, `rep` the representative edition, LEFT JOINed on
# rep.id = w.representative_book_id. tests/test_cover_ladder_sql.py pins the two.
NO_COVER_SQL = "(nullif(rep.cover_url, '') IS NULL AND coalesce(w.ol_cover_id, 0) = 0)"
```

- [ ] **Step 5: Run it to verify it passes**

Run: `PYTEST tests/test_cover_ladder_sql.py -q`
Expected: `1 passed`.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/works.py backend/tests/test_cover_ladder_sql.py docs/librarian-ux-roadmap.md
git commit -m "feat(catalog): the cover ladder as a SQL condition, pinned to the page's"
```

---

### Task 2: The health checks

**Files:**
- Create: `backend/app/services/librarian/health.py`
- Modify: `backend/app/services/librarian/errors.py`, `backend/app/schemas/librarian.py`
- Test: `backend/tests/test_librarian_health.py`

**Interfaces:**
- Consumes: `NO_COVER_SQL` (Task 1); `LibrarianError` (`services/librarian/errors.py`); factories `make_series(db, name, *, parent=None)`, `make_work(db, title, *, series=None, ol_id=None)`, `make_member(db, series, work, position=None)`, `make_edition`.
- Produces:
  - `app.schemas.librarian.HealthKind = Literal["gap", "duplicate_position", "missing_cover", "single_book_series"]`
  - `app.schemas.librarian.HealthIssue(BaseModel)`: `kind: HealthKind`, `series_id: UUID`, `series_slug: str`, `series_name: str`, `work_ids: list[UUID]`, `detail: str`.
  - `app.services.librarian.errors.QueueTooSlow(LibrarianError)`, `status_code = 503`. Item 14 reuses it.
  - `app.services.librarian.health`: `KINDS: tuple[HealthKind, ...]` (roadmap order), `MAX_GAP_POSITION = 200`, `BUDGET_MS = 10_000`, `statement_budget(db, ms: int | None = None)` (async context manager; item 14 reuses it), `async health_issues(db, *, kind: HealthKind | None = None, limit: int = 50, offset: int = 0) -> list[HealthIssue]`.

- [ ] **Step 1: Write the failing tests**

`backend/tests/test_librarian_health.py`:

```python
"""Series health (roadmap item 13): computed on request, in the page's own terms."""

from datetime import datetime, timezone

import pytest
from sqlalchemy import text

from app.models import SeriesKind
from app.services.librarian.errors import QueueTooSlow
from app.services.librarian.health import health_issues, statement_budget
from tests.librarian_factories import make_edition, make_member, make_series, make_work


async def _room(db, name, positions, **series_kw):
    """A real series whose books sit at ``positions`` (None = unnumbered)."""
    room = await make_series(db, name, **series_kw)
    works = []
    for i, position in enumerate(positions):
        work = await make_work(db, f"{name} {i}", series=room)
        await make_member(db, room, work, position)
        works.append(work)
    return room, works


async def _covered(db, work):
    edition = await make_edition(db, work)
    edition.cover_url = "https://books.example/c.jpg"
    work.representative_book_id = edition.id
    await db.flush()


async def test_a_gap_names_the_missing_places_and_the_book_after_each(db_session):
    room, (_one, _two, four, seven) = await _room(db_session, "Saga", [1, 2, 4, 7])
    [issue] = await health_issues(db_session, kind="gap")
    assert (issue.kind, issue.series_id, issue.series_slug, issue.series_name) == ("gap", room.id, room.slug, "Saga")
    assert issue.detail == "no book at #3, #5, #6"
    assert set(issue.work_ids) == {four.id, seven.id}


async def test_a_long_gap_list_is_shortened(db_session):
    await _room(db_session, "Sparse", [1, 9])
    [issue] = await health_issues(db_session, kind="gap")
    assert issue.detail == "no book at #2, #3, #4, #5, #6 and 2 more"


async def test_fractional_and_unnumbered_books_neither_fill_nor_open_gaps(db_session):
    await _room(db_session, "Novellas", [1, 1.5, 2, None])
    assert await health_issues(db_session, kind="gap") == []
    room, (_a, half, _c) = await _room(db_session, "Halves", [1, 2.5, 3])
    [issue] = await health_issues(db_session, kind="gap")
    assert issue.series_id == room.id and issue.detail == "no book at #2" and issue.work_ids == [half.id]


async def test_year_positions_are_not_gaps(db_session):
    await _room(db_session, "Annual", [1965, 1966])
    assert await health_issues(db_session, kind="gap") == []


async def test_two_books_at_one_place(db_session):
    room, (_one, a, b) = await _room(db_session, "Twins", [1, 2, 2])
    [issue] = await health_issues(db_session, kind="duplicate_position")
    assert issue.series_id == room.id and issue.detail == "2 books at #2"
    assert issue.work_ids == [a.id, b.id]  # title order: "Twins 1", "Twins 2"


async def test_sub_series_are_checked_where_the_page_places_books(db_session):
    cosmere = await make_series(db_session, "Cosmere")
    mistborn = await make_series(db_session, "Mistborn", parent=cosmere)
    first = await make_work(db_session, "The Final Empire", series=cosmere)
    third = await make_work(db_session, "The Hero of Ages", series=cosmere)
    # A room-level place the page never shows: the deeper membership wins.
    await make_member(db_session, cosmere, first, 5)
    await make_member(db_session, mistborn, first, 1)
    await make_member(db_session, mistborn, third, 3)

    [gap] = await health_issues(db_session, kind="gap")
    assert gap.series_id == cosmere.id and gap.detail == "Mistborn: no book at #2" and gap.work_ids == [third.id]
    assert await health_issues(db_session, kind="duplicate_position") == []


async def test_missing_cover_follows_the_page_ladder(db_session):
    room = await make_series(db_session, "Covers")
    bare = await make_work(db_session, "Bare", series=room)
    ol = await make_work(db_session, "Has OL", series=room)
    ol.ol_cover_id = 5
    covered = await make_work(db_session, "Has Edition", series=room)
    await _covered(db_session, covered)
    gone = await make_work(db_session, "Merged Away", series=room)
    gone.merged_into_id = covered.id
    await make_work(db_session, "A Singleton Without Art")  # its own singleton room: out of scope
    await db_session.flush()

    [issue] = await health_issues(db_session, kind="missing_cover")
    assert issue.series_id == room.id and issue.work_ids == [bare.id] and issue.detail == "1 book without a cover"


async def test_single_book_series_counts_live_books_in_live_rooms(db_session):
    lonely = await make_series(db_session, "Lonely")
    only = await make_work(db_session, "Only", series=lonely)
    ghost = await make_work(db_session, "Ghost", series=lonely)
    ghost.merged_into_id = only.id
    pair = await make_series(db_session, "Pair")
    await make_work(db_session, "One", series=pair)
    await make_work(db_session, "Two", series=pair)
    dissolved = await make_series(db_session, "Dissolved")
    await make_work(db_session, "Left", series=dissolved)
    dissolved.dissolved_at = datetime.now(timezone.utc)
    await make_work(db_session, "Singleton")
    await db_session.flush()

    [issue] = await health_issues(db_session, kind="single_book_series")
    assert issue.series_id == lonely.id and issue.work_ids == [only.id] and issue.detail == "only one book"


async def test_pages_are_slices_of_the_kind_ordered_list(db_session):
    alpha, _ = await _room(db_session, "Alpha", [1, 3])
    beta, _ = await _room(db_session, "Beta", [1, 3])
    every = await health_issues(db_session)
    assert [(i.kind, i.series_name) for i in every] == [
        ("gap", "Alpha"), ("gap", "Beta"), ("missing_cover", "Alpha"), ("missing_cover", "Beta"),
    ]
    assert await health_issues(db_session, limit=1, offset=1) == every[1:2]
    assert await health_issues(db_session, limit=2, offset=2) == every[2:4]
    assert await health_issues(db_session, limit=5, offset=4) == []


async def test_a_statement_past_its_budget_is_queue_too_slow(db_session):
    with pytest.raises(QueueTooSlow):
        async with statement_budget(db_session, 50):
            await db_session.execute(text("SELECT pg_sleep(1)"))


async def test_the_budget_ends_with_its_block(db_session):
    before = await db_session.scalar(text("SHOW statement_timeout"))
    async with statement_budget(db_session, 5000):
        assert await db_session.scalar(text("SHOW statement_timeout")) == "5s"
    assert await db_session.scalar(text("SHOW statement_timeout")) == before
```

(`_room` gives every book a membership, `None` included, which is how a runtime series with an unnumbered member looks. Every book it creates has no cover, which is why the ordering test also sees `missing_cover` rows.)

- [ ] **Step 2: Run to verify they fail**

Run: `PYTEST tests/test_librarian_health.py -q`
Expected: collection error, `ModuleNotFoundError: No module named 'app.services.librarian.health'`.

- [ ] **Step 3: The schema and the error**

Append to `backend/app/schemas/librarian.py` (add `Literal` to a new `from typing import Literal` import at the top):

```python
HealthKind = Literal["gap", "duplicate_position", "missing_cover", "single_book_series"]


class HealthIssue(BaseModel):
    """One problem on one series page (roadmap item 13). ``work_ids`` are the
    books the librarian should look at: after a gap, sharing a place, without
    a cover, or the one book."""

    kind: HealthKind
    series_id: UUID
    series_slug: str
    series_name: str
    work_ids: list[UUID]
    detail: str
```

Append to `backend/app/services/librarian/errors.py`:

```python
class QueueTooSlow(LibrarianError):
    """A queue query ran past its statement budget; the catalog is too big to
    answer this request in one go."""

    status_code = 503
```

- [ ] **Step 4: The checks**

`backend/app/services/librarian/health.py`:

```python
"""Series health (librarian UX roadmap item 13): problems computed on request.

Nothing is stored. Each check is one SQL statement over live real rooms that
returns only the rows the requested page needs, so the database does the
scanning and Python never holds the catalog; the request runs under a
statement budget and answers 503 past it instead of tying up a worker.

The rules are the series page's own: a book is placed by its membership in the
deepest series of its room's tree (``services/series.placed_memberships``, the
order ``api/series._members`` renders), and "no cover" is
``load_work_presentation``'s ladder (``works.NO_COVER_SQL``). The queue never
reports a problem the page does not show.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.librarian import HealthIssue, HealthKind
from app.services.librarian.errors import QueueTooSlow
from app.services.works import NO_COVER_SQL

# The order the queue lists them in.
KINDS: tuple[HealthKind, ...] = ("gap", "duplicate_position", "missing_cover", "single_book_series")
# Above this, "positions" are years or catalog numbers rather than a reading
# order, and listing every missing integer would bury the real gaps.
MAX_GAP_POSITION = 200
BUDGET_MS = 10_000
_SHOWN_NUMBERS = 5

# A live real room: the only pages these checks describe.
_ROOM = ("s.kind = 'series' AND s.merged_into_id IS NULL AND s.dissolved_at IS NULL "
         "AND s.parent_series_id IS NULL")

# Every live work's placed membership: the deepest series of its room's tree,
# name as tiebreak (room_tree + placed_memberships, in SQL). `nodes` keeps each
# series at its shallowest depth, as room_tree's setdefault does.
_PLACED = f"""
WITH RECURSIVE tree(room_id, series_id, depth, name) AS (
    SELECT s.id, s.id, 0, s.name FROM series s WHERE {_ROOM}
  UNION ALL
    SELECT t.room_id, c.id, t.depth + 1, c.name
    FROM series c JOIN tree t ON c.parent_series_id = t.series_id
    WHERE c.merged_into_id IS NULL AND t.depth < 5
),
nodes AS (
    SELECT room_id, series_id, min(depth) AS depth, min(name) AS name
    FROM tree GROUP BY room_id, series_id
),
placed AS (
    SELECT DISTINCT ON (w.id) w.id AS work_id, w.title, w.series_id AS room_id, m.series_id, m.position
    FROM works w
    JOIN nodes n ON n.room_id = w.series_id
    JOIN series_members m ON m.work_id = w.id AND m.series_id = n.series_id
    WHERE w.merged_into_id IS NULL
    ORDER BY w.id, n.depth DESC, n.name DESC
)"""

_GAPS = _PLACED + """,
numbered AS (
    SELECT room_id, series_id, max(position)::int AS top FROM placed
    WHERE position >= 1 AND position = trunc(position)
    GROUP BY room_id, series_id
    HAVING max(position) <= :max_gap
),
missing AS (
    SELECT g.room_id, g.series_id, n.n
    FROM numbered g CROSS JOIN LATERAL generate_series(1, g.top) AS n(n)
    WHERE NOT EXISTS (SELECT 1 FROM placed p
                      WHERE p.room_id = g.room_id AND p.series_id = g.series_id AND p.position = n.n)
)
SELECT r.id AS series_id, r.slug AS series_slug, r.name AS series_name, sub.name AS sub_name,
       array_agg(m.n ORDER BY m.n) AS numbers,
       array_remove(array_agg(DISTINCT nxt.work_id), NULL) AS work_ids
FROM missing m
JOIN series r ON r.id = m.room_id
LEFT JOIN series sub ON sub.id = m.series_id AND m.series_id <> m.room_id
LEFT JOIN LATERAL (
    SELECT p.work_id FROM placed p
    WHERE p.room_id = m.room_id AND p.series_id = m.series_id AND p.position > m.n
    ORDER BY p.position, p.work_id LIMIT 1
) nxt ON true
GROUP BY r.id, r.slug, r.name, sub.name, m.series_id
ORDER BY r.name, r.id, sub.name NULLS FIRST, m.series_id
LIMIT :n"""

_SHARED = _PLACED + """
SELECT r.id AS series_id, r.slug AS series_slug, r.name AS series_name, sub.name AS sub_name,
       ARRAY[p.position] AS numbers,
       array_agg(p.work_id ORDER BY p.title, p.work_id) AS work_ids
FROM placed p
JOIN series r ON r.id = p.room_id
LEFT JOIN series sub ON sub.id = p.series_id AND p.series_id <> p.room_id
WHERE p.position IS NOT NULL
GROUP BY r.id, r.slug, r.name, sub.name, p.series_id, p.position
HAVING count(*) > 1
ORDER BY r.name, r.id, sub.name NULLS FIRST, p.series_id, p.position
LIMIT :n"""

_COVERLESS = f"""
SELECT s.id AS series_id, s.slug AS series_slug, s.name AS series_name, NULL::text AS sub_name,
       NULL::numeric[] AS numbers, array_agg(w.id ORDER BY w.title, w.id) AS work_ids
FROM works w
JOIN series s ON s.id = w.series_id
LEFT JOIN books rep ON rep.id = w.representative_book_id
WHERE w.merged_into_id IS NULL AND {_ROOM} AND {NO_COVER_SQL}
GROUP BY s.id, s.slug, s.name
ORDER BY s.name, s.id
LIMIT :n"""

_SINGLES = f"""
SELECT s.id AS series_id, s.slug AS series_slug, s.name AS series_name, NULL::text AS sub_name,
       NULL::numeric[] AS numbers, array_agg(w.id) AS work_ids
FROM series s
JOIN works w ON w.series_id = s.id AND w.merged_into_id IS NULL
WHERE {_ROOM}
GROUP BY s.id, s.slug, s.name
HAVING count(*) = 1
ORDER BY s.name, s.id
LIMIT :n"""

_SQL: dict[str, str] = {
    "gap": _GAPS, "duplicate_position": _SHARED, "missing_cover": _COVERLESS, "single_book_series": _SINGLES,
}


def _cancelled(exc: DBAPIError) -> bool:
    return getattr(exc.orig, "sqlstate", None) == "57014" or "statement timeout" in str(exc)


@asynccontextmanager
async def statement_budget(db: AsyncSession, ms: int | None = None):
    """Cap every statement inside the block at ``ms`` (default ``BUDGET_MS``).

    ``set_config(..., true)`` is transaction-local, and the previous value is
    put back when the block ends normally, so the budget never outlives it.
    After a cancel the transaction is aborted; ``get_db`` rolls it back.
    """
    budget = BUDGET_MS if ms is None else ms
    previous = await db.scalar(text("SELECT current_setting('statement_timeout')"))
    await db.execute(text("SELECT set_config('statement_timeout', :v, true)"), {"v": f"{budget}ms"})
    try:
        yield
    except DBAPIError as exc:
        if _cancelled(exc):
            raise QueueTooSlow("The queue took too long to compute; show one kind at a time.") from None
        raise
    await db.execute(text("SELECT set_config('statement_timeout', :v, true)"), {"v": previous})


def _place(n) -> str:
    value = float(n)
    return f"#{int(value)}" if value.is_integer() else f"#{value:g}"


def _detail(kind: str, row) -> str:
    where = f"{row.sub_name}: " if row.sub_name else ""
    if kind == "gap":
        shown = ", ".join(_place(n) for n in row.numbers[:_SHOWN_NUMBERS])
        more = len(row.numbers) - _SHOWN_NUMBERS
        return f"{where}no book at {shown}" + (f" and {more} more" if more > 0 else "")
    if kind == "duplicate_position":
        return f"{where}{len(row.work_ids)} books at {_place(row.numbers[0])}"
    if kind == "missing_cover":
        n = len(row.work_ids)
        return f"{n} {'book' if n == 1 else 'books'} without a cover"
    return "only one book"


async def health_issues(db: AsyncSession, *, kind: HealthKind | None = None, limit: int = 50,
                        offset: int = 0) -> list[HealthIssue]:
    """One page of problems, ordered by kind (``KINDS``), then series name and id.

    Each kind's statement returns at most the rows still needed to reach
    ``offset + limit``, in that order, so the page is a slice of their
    concatenation and nothing past it is ever fetched.
    """
    wanted = offset + limit
    issues: list[HealthIssue] = []
    async with statement_budget(db):
        for k in (kind,) if kind else KINDS:
            need = wanted - len(issues)
            if need <= 0:
                break
            params = {"n": need, **({"max_gap": MAX_GAP_POSITION} if k == "gap" else {})}
            rows = (await db.execute(text(_SQL[k]), params)).all()
            issues += [
                HealthIssue(kind=k, series_id=r.series_id, series_slug=r.series_slug, series_name=r.series_name,
                            work_ids=list(r.work_ids), detail=_detail(k, r))
                for r in rows
            ]
    return issues[offset:offset + limit]
```

- [ ] **Step 5: Run the tests**

Run: `PYTEST tests/test_librarian_health.py -q`
Expected: `11 passed`.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/librarian/health.py backend/app/services/librarian/errors.py \
        backend/app/schemas/librarian.py backend/tests/test_librarian_health.py
git commit -m "feat(librarian): series health checks computed on request, paged and under a statement budget"
```

---

### Task 3: `GET /api/librarian/queue/health`

**Files:**
- Create: `backend/app/api/librarian_queue.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_librarian_queue_api.py`

**Interfaces:**
- Consumes: `health_issues`, `HealthIssue`, `HealthKind` (Task 2); `_run` (`api/librarian.py`, maps `LibrarianError` to its status); `require_librarian`.
- Produces: `app.api.librarian_queue.router = APIRouter(prefix="/librarian/queue", tags=["librarian"])`, mounted under `/api`; route `GET /api/librarian/queue/health?kind=&limit=&offset=` → `list[HealthIssue]`. Items 14 and 15 add routes to this module and extend `QUEUE_ROUTES` in its test.

- [ ] **Step 1: Write the failing tests**

`backend/tests/test_librarian_queue_api.py`:

```python
"""The librarian queue's routes (roadmap items 13–15). 14 and 15 append theirs."""

from app.api import librarian_queue
from app.services.librarian.errors import QueueTooSlow
from tests.librarian_factories import headers_for, make_member, make_series, make_user, make_work

# (method, path, body) for every queue route; 14 and 15 extend this list.
QUEUE_ROUTES = [
    ("GET", "/api/librarian/queue/health", None),
]


async def test_every_queue_route_refuses_readers_and_anonymous(client, db_session):
    reader = headers_for(await make_user(db_session))
    for method, path, body in QUEUE_ROUTES:
        assert (await client.request(method, path, json=body, headers=reader)).status_code == 403, path
        assert (await client.request(method, path, json=body)).status_code in (401, 403), path


async def test_health_lists_issues_in_the_roadmap_shape(client, db_session):
    lib = headers_for(await make_user(db_session, librarian=True))
    room = await make_series(db_session, "Saga")
    for title, position in (("One", 1), ("Three", 3)):
        await make_member(db_session, room, await make_work(db_session, title, series=room), position)

    resp = await client.get("/api/librarian/queue/health", params={"kind": "gap"}, headers=lib)
    assert resp.status_code == 200, resp.text
    [issue] = resp.json()
    assert set(issue) == {"kind", "series_id", "series_slug", "series_name", "work_ids", "detail"}
    assert issue["kind"] == "gap" and issue["series_slug"] == room.slug and issue["detail"] == "no book at #2"

    every = (await client.get("/api/librarian/queue/health", headers=lib)).json()
    assert [i["kind"] for i in every] == ["gap", "missing_cover"]


async def test_paging_is_bounded(client, db_session):
    lib = headers_for(await make_user(db_session, librarian=True))
    for params in ({"limit": 0}, {"limit": 201}, {"offset": -1}, {"offset": 1001}, {"kind": "typo"}):
        resp = await client.get("/api/librarian/queue/health", params=params, headers=lib)
        assert resp.status_code == 422, params
    assert (await client.get("/api/librarian/queue/health", params={"limit": 200, "offset": 1000},
                             headers=lib)).status_code == 200


async def test_a_slow_queue_is_503(client, db_session, monkeypatch):
    lib = headers_for(await make_user(db_session, librarian=True))

    async def too_slow(*args, **kwargs):
        raise QueueTooSlow("The queue took too long to compute; show one kind at a time.")

    monkeypatch.setattr(librarian_queue, "health_issues", too_slow)
    resp = await client.get("/api/librarian/queue/health", headers=lib)
    assert resp.status_code == 503
    assert resp.json()["detail"] == "The queue took too long to compute; show one kind at a time."
```

- [ ] **Step 2: Run to verify they fail**

Run: `PYTEST tests/test_librarian_queue_api.py -q`
Expected: collection error, `ImportError: cannot import name 'librarian_queue' from 'app.api'`.

- [ ] **Step 3: The router**

`backend/app/api/librarian_queue.py`:

```python
"""The librarian queue (roadmap items 13–15): what needs fixing, brought to the
librarian. Thin, like api/librarian.py: services compute, these map errors."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.librarian import _run
from app.database import get_db
from app.models import User
from app.schemas.librarian import HealthIssue, HealthKind
from app.services.auth import require_librarian
from app.services.librarian.health import health_issues

router = APIRouter(prefix="/librarian/queue", tags=["librarian"])

# Every queue list pages the same way; offset is capped so no request can ask
# the database to rank more than 1200 rows.
_LIMIT = Query(50, ge=1, le=200)
_OFFSET = Query(0, ge=0, le=1000)


@router.get("/health", response_model=list[HealthIssue])
async def health(kind: HealthKind | None = None, limit: int = _LIMIT, offset: int = _OFFSET,
                 db: AsyncSession = Depends(get_db), user: User = Depends(require_librarian)):
    return await _run(health_issues(db, kind=kind, limit=limit, offset=offset))
```

In `backend/app/main.py`, change the api import line to

```python
from app.api import genres, librarian, librarian_queue, posts, series, threads, users, works  # noqa: E402
```

and add after `app.include_router(librarian.router, prefix="/api")`:

```python
app.include_router(librarian_queue.router, prefix="/api")
```

- [ ] **Step 4: Run the tests, then the librarian suites**

Run: `PYTEST tests/test_librarian_queue_api.py tests/test_librarian_api.py tests/test_openapi.py -q`
Expected: all pass (`test_openapi` is unchanged: the router reuses the `librarian` tag).

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/librarian_queue.py backend/app/main.py backend/tests/test_librarian_queue_api.py
git commit -m "feat(librarian): GET /api/librarian/queue/health"
```

---

### Task 4: The queue section contract and the health section

**Files:**
- Create: `frontend/src/components/librarian/QueueSection.jsx`, `frontend/src/components/librarian/HealthSection.jsx`, `frontend/src/components/librarian/queueSections.js`
- Modify: `frontend/src/api/librarian.js`
- Test: `frontend/src/components/librarian/HealthSection.test.jsx`, `frontend/src/components/librarian/queueSections.test.js`

**Interfaces:**
- Consumes: `GET /api/librarian/queue/health` (Task 3); `DataTable`; `errorMessage`.
- Produces (items 14 and 15 rely on these exact names):
  - `api/librarian.js`: `QUEUE_PAGE = 50`, `QUEUE_MAX_OFFSET = 1000`, `nextQueueOffset(lastPage, pages) -> number | undefined`, `useHealthIssues(kind = null)` (an infinite query, key `['librarian', 'queue', 'health', kind ?? 'all']`).
  - `components/librarian/QueueSection.jsx` (default export): `<QueueSection id title count hasMore loading error emptyMessage onMore loadingMore controls>{children}</QueueSection>` — see Decision 8.
  - `components/librarian/queueSections.js`: `QUEUE_ORDER = ['reports', 'duplicates', 'health']`, `QUEUE_SECTIONS = { health: HealthSection }`.
  - `components/librarian/HealthSection.jsx` (default export, no props); named export `issueHref(issue) -> string`.

- [ ] **Step 1: Write the failing tests**

`frontend/src/components/librarian/queueSections.test.js`:

```js
import { describe, it, expect } from 'vitest'
import { QUEUE_ORDER, QUEUE_SECTIONS } from './queueSections'

describe('queue sections', () => {
  it('keeps the roadmap order: reports, duplicates, series health', () => {
    expect(QUEUE_ORDER).toEqual(['reports', 'duplicates', 'health'])
  })

  it('registers only sections that have a place in that order', () => {
    for (const key of Object.keys(QUEUE_SECTIONS)) expect(QUEUE_ORDER).toContain(key)
    expect(QUEUE_SECTIONS.health).toBeTypeOf('function')
  })
})
```

`frontend/src/components/librarian/HealthSection.test.jsx`:

```jsx
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

vi.mock('../../api/client', () => ({ default: { get: vi.fn(), post: vi.fn() } }))

import client from '../../api/client'
import HealthSection, { issueHref } from './HealthSection'

const GAP = { kind: 'gap', series_id: 's1', series_slug: 'red-rising', series_name: 'Red Rising',
  work_ids: ['w4'], detail: 'no book at #3' }
const LONELY = { kind: 'single_book_series', series_id: 's2', series_slug: 'lonely', series_name: 'Lonely Saga',
  work_ids: ['w9'], detail: 'only one book' }

function renderSection() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(<QueryClientProvider client={qc}><MemoryRouter><HealthSection /></MemoryRouter></QueryClientProvider>)
}

beforeEach(() => vi.clearAllMocks())

describe('HealthSection', () => {
  it('links each problem into its series page in edit mode, at the book', async () => {
    client.get.mockResolvedValue({ data: [GAP, LONELY] })
    renderSection()
    const region = await screen.findByRole('region', { name: /Series health/ })
    expect(await within(region).findByRole('link', { name: 'Red Rising' }))
      .toHaveAttribute('href', '/series/red-rising?edit=1&book=w4')
    expect(within(region).getByText('no book at #3')).toBeInTheDocument()
    expect(within(region).getByText('only one book')).toBeInTheDocument()
    expect(client.get).toHaveBeenCalledWith('/librarian/queue/health', { params: { limit: 50, offset: 0 } })
  })

  it('links to the page alone when an issue names no book', () => {
    expect(issueHref({ ...GAP, work_ids: [] })).toBe('/series/red-rising?edit=1')
  })

  it('says so when nothing is wrong', async () => {
    client.get.mockResolvedValue({ data: [] })
    renderSection()
    expect(await screen.findByText('No series problems found.')).toBeInTheDocument()
  })

  it('filters by kind', async () => {
    client.get.mockResolvedValue({ data: [GAP] })
    renderSection()
    await screen.findByRole('link', { name: 'Red Rising' })
    await userEvent.click(screen.getByRole('button', { name: 'gap' }))
    expect(screen.getByRole('button', { name: 'gap' })).toHaveAttribute('aria-pressed', 'true')
    expect(client.get).toHaveBeenLastCalledWith('/librarian/queue/health',
      { params: { limit: 50, offset: 0, kind: 'gap' } })
  })

  it('pages with more', async () => {
    const page = Array.from({ length: 50 }, (_, i) => ({ ...GAP, series_id: `s${i}`, series_name: `Saga ${i}` }))
    client.get.mockResolvedValueOnce({ data: page }).mockResolvedValueOnce({ data: [LONELY] })
    renderSection()
    expect(await screen.findByText('50+')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'more' }))
    expect(await screen.findByRole('link', { name: 'Lonely Saga' })).toBeInTheDocument()
    expect(client.get).toHaveBeenLastCalledWith('/librarian/queue/health', { params: { limit: 50, offset: 50 } })
    expect(screen.queryByRole('button', { name: 'more' })).not.toBeInTheDocument()
  })

  it('shows why the server refused', async () => {
    client.get.mockRejectedValue({ response: { status: 503,
      data: { detail: 'The queue took too long to compute; show one kind at a time.' } } })
    renderSection()
    expect(await screen.findByText(/took too long/)).toBeInTheDocument()
  })
})
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd frontend && npx vitest run src/components/librarian/`
Expected: both files fail to resolve `./queueSections` / `./HealthSection`.

- [ ] **Step 3: The hooks**

In `frontend/src/api/librarian.js`, change the first import to `import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'` and append:

```js
/** Queue lists page 50 at a time; the server refuses offsets past 1000. */
export const QUEUE_PAGE = 50
export const QUEUE_MAX_OFFSET = 1000

/** getNextPageParam for every queue list: the next offset while pages come back full. */
export function nextQueueOffset(lastPage, pages) {
  const next = pages.length * QUEUE_PAGE
  return lastPage.length === QUEUE_PAGE && next <= QUEUE_MAX_OFFSET ? next : undefined
}

export function useHealthIssues(kind = null) {
  return useInfiniteQuery({
    queryKey: ['librarian', 'queue', 'health', kind ?? 'all'],
    queryFn: ({ pageParam }) =>
      client.get('/librarian/queue/health', {
        params: { limit: QUEUE_PAGE, offset: pageParam, ...(kind ? { kind } : {}) },
      }).then((r) => r.data),
    initialPageParam: 0,
    getNextPageParam: nextQueueOffset,
  })
}
```

- [ ] **Step 4: The shell**

`frontend/src/components/librarian/QueueSection.jsx`:

```jsx
import { errorMessage } from '../../api/errors'

/**
 * One section of the librarian queue. Every section — reader reports (15),
 * possible duplicates (14), series health (13) — renders through this shell,
 * so the queue reads as one list of work with one set of states.
 *
 * The contract a section keeps: it is a component in components/librarian/
 * with no props, registered in queueSections.js under its key; it owns its
 * data hook and hands this shell the states; `id` is its registry key. It
 * never renders its own heading, loading bar, error or empty text.
 */
function QueueSection({
  id, title, count, hasMore = false, loading = false, error = null, emptyMessage,
  onMore, loadingMore = false, controls = null, children,
}) {
  const headingId = `queue-${id}`
  const settled = !loading && !error
  return (
    <section aria-labelledby={headingId} className="flex flex-col gap-3">
      <div className="flex items-baseline justify-between gap-3 border-b border-line pb-2">
        <h2 id={headingId} className="text-sm uppercase tracking-eyebrow text-ink">{title}</h2>
        {settled && <span className="text-ink-dim text-xs tabular-nums">{count}{hasMore ? '+' : ''}</span>}
      </div>
      {controls}
      {loading ? (
        <div className="h-8 border border-line bg-panel animate-pulse" />
      ) : error ? (
        <p className="alert-danger text-xs">{errorMessage(error)}</p>
      ) : count === 0 ? (
        <p className="text-ink-dim text-sm">{emptyMessage}</p>
      ) : (
        children
      )}
      {settled && hasMore && (
        <button type="button" className="btn-ghost text-xs self-start" disabled={loadingMore} onClick={onMore}>
          more
        </button>
      )}
    </section>
  )
}

export default QueueSection
```

- [ ] **Step 5: The health section and the registry**

`frontend/src/components/librarian/HealthSection.jsx`:

```jsx
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useHealthIssues } from '../../api/librarian'
import DataTable from '../DataTable'
import QueueSection from './QueueSection'

const LABELS = {
  gap: 'gap',
  duplicate_position: 'shared place',
  missing_cover: 'no cover',
  single_book_series: 'one book',
}

/** The series page in edit mode, scrolled to the first book concerned. */
export function issueHref(issue) {
  const params = new URLSearchParams({ edit: '1' })
  if (issue.work_ids.length) params.set('book', issue.work_ids[0])
  return `/series/${issue.series_slug}?${params}`
}

/** Queue section: what is wrong with the catalog's series pages (roadmap item 13). */
function HealthSection() {
  const [kind, setKind] = useState(null)
  const query = useHealthIssues(kind)
  const issues = (query.data?.pages ?? []).flat()
    .map((issue) => ({ ...issue, id: `${issue.kind}:${issue.series_id}:${issue.detail}` }))

  const filter = (value, label) => (
    <button
      key={value ?? 'all'}
      type="button"
      aria-pressed={kind === value}
      onClick={() => setKind(value)}
      className={`text-xs px-1 transition-colors duration-fast ${
        // Underlined as well as coloured: nothing means anything by colour alone.
        kind === value ? 'text-accent underline underline-offset-4' : 'text-ink-dim hover:text-accent'
      }`}
    >
      {label}
    </button>
  )

  const columns = [
    { key: 'series', label: 'Series',
      render: (i) => (
        <Link to={issueHref(i)} className="font-serif text-ink hover:text-accent transition-colors duration-fast">
          {i.series_name}
        </Link>
      ) },
    { key: 'kind', label: 'Problem', width: 14, render: (i) => <span className="text-ink">{LABELS[i.kind]}</span> },
    { key: 'detail', label: 'Detail', render: (i) => <span className="text-ink-dim">{i.detail}</span> },
  ]

  return (
    <QueueSection
      id="health"
      title="Series health"
      count={issues.length}
      hasMore={!!query.hasNextPage}
      loading={query.isLoading}
      error={query.error}
      emptyMessage={kind ? 'No series with this problem.' : 'No series problems found.'}
      onMore={() => query.fetchNextPage()}
      loadingMore={query.isFetchingNextPage}
      controls={
        <div role="group" aria-label="Filter by problem" className="flex flex-wrap items-center gap-2">
          {filter(null, 'all')}
          {Object.entries(LABELS).map(([value, label]) => filter(value, label))}
        </div>
      }
    >
      <DataTable columns={columns} rows={issues} caption="Series health problems" />
    </QueueSection>
  )
}

export default HealthSection
```

`frontend/src/components/librarian/queueSections.js`:

```js
import HealthSection from './HealthSection'

/**
 * The librarian queue's sections, in the roadmap's order: reader reports (15),
 * possible duplicates (14), series health (13). Never reorder this list; a new
 * section adds its component to QUEUE_SECTIONS under its key. The queue tab
 * renders only registered keys, so an unshipped section leaves no placeholder.
 */
export const QUEUE_ORDER = ['reports', 'duplicates', 'health']

export const QUEUE_SECTIONS = {
  health: HealthSection,
}
```

- [ ] **Step 6: Run the tests**

Run: `cd frontend && npx vitest run src/components/librarian/`
Expected: `queueSections.test.js` 2 passed, `HealthSection.test.jsx` 6 passed.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/api/librarian.js frontend/src/components/librarian/
git commit -m "feat(web): queue section contract and the series health section"
```

---

### Task 5: `/librarian` tabs — fixes | queue

**Files:**
- Modify: `frontend/src/pages/Librarian.jsx`, `frontend/src/pages/Librarian.test.jsx`

**Interfaces:**
- Consumes: `QUEUE_ORDER`, `QUEUE_SECTIONS` (Task 4); the existing `Log` component in `Librarian.jsx`.
- Produces: `/librarian` (fixes, the default) and `/librarian?tab=queue`; tab links named `fixes` and `queue` with `aria-current="page"` on the open one. Any other `tab` value shows fixes.

- [ ] **Step 1: Write the failing tests**

In `frontend/src/pages/Librarian.test.jsx`:

1. Add `import { QUEUE_ORDER, QUEUE_SECTIONS } from '../components/librarian/queueSections'` after the `Librarian` import.
2. Replace `renderPage` with a version that takes the starting URL:

```jsx
function renderPage(path = '/librarian') {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[path]}><Librarian /></MemoryRouter>
    </QueryClientProvider>,
  )
}
```

3. Change the `beforeEach` mock so every queue list answers empty and the fix log answers `ROWS`:

```jsx
beforeEach(() => {
  vi.clearAllMocks()
  client.get.mockImplementation((url) => Promise.resolve({ data: url === '/librarian/corrections' ? ROWS : [] }))
})
```

4. Append a new `describe` block:

```jsx
describe('Librarian tabs', () => {
  const librarian = () => useAuthStore.setState({ token: 't', user: { id: 'u', username: 'ada', is_librarian: true } })

  it('opens on the fix log', async () => {
    librarian()
    renderPage()
    expect(screen.getByRole('link', { name: 'fixes' })).toHaveAttribute('aria-current', 'page')
    expect(await screen.findByRole('link', { name: 'Iron Gold' })).toBeInTheDocument()
  })

  it('opens the queue from the URL, sections in roadmap order, with no placeholders', async () => {
    librarian()
    renderPage('/librarian?tab=queue')
    expect(screen.getByRole('link', { name: 'queue' })).toHaveAttribute('aria-current', 'page')
    expect(await screen.findByText('No series problems found.')).toBeInTheDocument()
    expect(screen.queryByText('Catalog fixes')).not.toBeInTheDocument()
    const shown = screen.getAllByRole('region').map((r) => r.getAttribute('aria-labelledby'))
    expect(shown).toEqual(QUEUE_ORDER.filter((k) => QUEUE_SECTIONS[k]).map((k) => `queue-${k}`))
  })

  it('switches tabs with links', async () => {
    librarian()
    renderPage()
    await userEvent.click(screen.getByRole('link', { name: 'queue' }))
    expect(await screen.findByRole('region', { name: /Series health/ })).toBeInTheDocument()
    await userEvent.click(screen.getByRole('link', { name: 'fixes' }))
    expect(await screen.findByText('Catalog fixes')).toBeInTheDocument()
  })

  it('treats an unknown tab as the fix log', async () => {
    librarian()
    renderPage('/librarian?tab=nope')
    expect(await screen.findByText('Catalog fixes')).toBeInTheDocument()
  })

  it('never shows readers the queue', () => {
    useAuthStore.setState({ token: 't', user: { id: 'u', username: 'reader' } })
    renderPage('/librarian?tab=queue')
    expect(screen.getByText(/not found/i)).toBeInTheDocument()
    expect(client.get).not.toHaveBeenCalled()
  })
})
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd frontend && npx vitest run src/pages/Librarian.test.jsx`
Expected: the new tests fail (no `fixes`/`queue` links); the existing ones still pass.

- [ ] **Step 3: Implement**

In `frontend/src/pages/Librarian.jsx`:

1. Imports: change `import { Link } from 'react-router-dom'` to `import { Link, useSearchParams } from 'react-router-dom'`, and add `import { QUEUE_ORDER, QUEUE_SECTIONS } from '../components/librarian/queueSections'`.
2. In `Log`'s return, the outer wrapper and its path header move up to the page. Replace

```jsx
    <main className="max-w-shell mx-auto px-4 py-6 flex flex-col gap-6">
      <PathHeader segments={[{ label: 'librarian' }]} />
```

with

```jsx
    <div className="flex flex-col gap-6">
```

and `Log`'s closing `</main>` with `</div>`. Nothing else in `Log` changes (item 11 may have added filters there; keep them).

3. Replace the `Librarian` function with:

```jsx
const TABS = ['fixes', 'queue']

/** The queue: what needs fixing, one section per source (roadmap items 13–15). */
function Queue() {
  useStatusBar({ mode: 'LIBRARIAN', path: '~/librarian/queue', facts: [] })
  return (
    <div className="flex flex-col gap-10">
      {QUEUE_ORDER.filter((key) => QUEUE_SECTIONS[key]).map((key) => {
        const Section = QUEUE_SECTIONS[key]
        return <Section key={key} />
      })}
    </div>
  )
}

function Tabs({ current }) {
  return (
    <nav aria-label="Librarian" className="flex gap-4 text-sm">
      {TABS.map((tab) => (
        <Link
          key={tab}
          to={tab === 'fixes' ? '/librarian' : `/librarian?tab=${tab}`}
          aria-current={current === tab ? 'page' : undefined}
          className={`transition-colors duration-fast ${
            current === tab ? 'text-accent underline underline-offset-4' : 'text-ink-dim hover:text-accent'
          }`}
        >
          {tab}
        </Link>
      ))}
    </nav>
  )
}

function Librarian() {
  const user = useAuthStore((s) => s.user)
  const [searchParams] = useSearchParams()
  if (!user?.is_librarian) return <NotFound />
  const tab = searchParams.get('tab') === 'queue' ? 'queue' : 'fixes'
  return (
    <main className="max-w-shell mx-auto px-4 py-6 flex flex-col gap-6">
      <PathHeader segments={tab === 'queue'
        ? [{ label: 'librarian', to: '/librarian' }, { label: 'queue' }]
        : [{ label: 'librarian' }]} />
      <Tabs current={tab} />
      {tab === 'queue' ? <Queue /> : <Log />}
    </main>
  )
}
```

- [ ] **Step 4: Run the unit suite**

Run: `cd frontend && npm test`
Expected: every test passes, including the existing Librarian log tests.

- [ ] **Step 5: §36 check, then commit**

Run `docker compose up --build`, sign in as a librarian, open `/librarian?tab=queue`. It must read as a terminal listing (rules, `ls -l` table, eyebrow headings), not a SaaS dashboard: no cards, no badges, no new colours. Then:

```bash
git add frontend/src/pages/Librarian.jsx frontend/src/pages/Librarian.test.jsx
git commit -m "feat(web): /librarian is tabbed fixes | queue, the tab in the URL"
```

---

### Task 6: End-to-end: follow a health issue into edit mode

**Files:**
- Create: `frontend/e2e/librarian-queue.spec.js`

**Interfaces:**
- Consumes: `registerViaUi`, `grantLibrarian` (`e2e/helpers.js`); the queue tab (Task 5).
- Produces: nothing later tasks use.

- [ ] **Step 1: The scenario**

`frontend/e2e/librarian-queue.spec.js`:

```js
import { test, expect } from '@playwright/test'
import { grantLibrarian, registerViaUi } from './helpers'

// The queue's answers and the series page are mocked in the browser, so the
// scenario never depends on what the dev catalog happens to hold.
const ISSUE = { kind: 'gap', series_id: 's-e2e', series_slug: 'e2e-saga', series_name: 'E2E Saga',
  work_ids: ['w3'], detail: 'no book at #2' }
const book = (id, title, position) => ({ id, title, author: 'A. Author', first_publish_year: 2001,
  cover_url: null, shelf_status: null, position, subseries: null, provenance: null })
const SERIES = { id: 's-e2e', slug: 'e2e-saga', name: 'E2E Saga', kind: 'series', dissolved: false,
  description: null, works: [book('w1', 'First', 1), book('w3', 'Third', 3)] }

test('a librarian follows a health issue from the queue into edit mode', async ({ page }) => {
  const user = await registerViaUi(page)
  grantLibrarian(user)
  await page.reload() // useMe refreshes the stored user, now a librarian

  // Later-registered routes win: every other queue list answers empty.
  await page.route(/\/api\/librarian\/queue\//, (route) => route.fulfill({ json: [] }))
  await page.route(/\/api\/librarian\/queue\/health/, (route) => route.fulfill({ json: [ISSUE] }))
  await page.route(/\/api\/series\/e2e-saga\/threads/, (route) => route.fulfill({ json: [] }))
  await page.route(/\/api\/series\/e2e-saga(\?|$)/, (route) => route.fulfill({ json: SERIES }))

  await page.goto('/librarian')
  await page.getByRole('link', { name: 'queue', exact: true }).click()
  await expect(page).toHaveURL(/\/librarian\?tab=queue/)

  const health = page.getByRole('region', { name: /Series health/ })
  await expect(health.getByText('no book at #2')).toBeVisible()
  await health.getByRole('link', { name: 'E2E Saga' }).click()

  await expect(page).toHaveURL(/\/series\/e2e-saga\?edit=1&book=w3/)
  await expect(page.getByRole('link', { name: '[done]' })).toBeVisible()
  const third = page.getByRole('listitem').filter({ has: page.getByRole('heading', { name: 'Third' }) })
  await expect(third).toHaveAttribute('aria-current', 'true')
})
```

- [ ] **Step 2: Run it**

Run (stack up in another terminal via `docker compose up --build`, then from `frontend/`): `npm run test:e2e -- librarian-queue.spec.js`
Expected: `1 passed`.

- [ ] **Step 3: Commit**

```bash
git add frontend/e2e/librarian-queue.spec.js
git commit -m "test(e2e): a librarian follows a health issue into edit mode"
```

---

### Task 7: Docs and the roadmap tracker

**Files:**
- Modify: `docs/librarian-ux-roadmap.md`, `ROADMAP.md`, `CLAUDE.md`, `README.md`

- [ ] **Step 1: Write them**

- `docs/librarian-ux-roadmap.md`:
  - Tracker row 13: Status `✅`, Done = the merge date (`YYYY-MM-DD`), PR = the PR link. Tick the checkbox in this plan's header.
  - Under **Shared names → Backend → Queue**, after the `GET health` line, add: "`?kind=&limit=&offset=` (limit ≤ 200, offset ≤ 1000); 503 past a 10s statement budget (`QueueTooSlow`). Queue routes live in `api/librarian_queue.py`."
  - Under **Shared names → Frontend**, after the queue-order bullet, add: "Queue sections: `components/librarian/QueueSection.jsx` (shell) and `components/librarian/queueSections.js` (`QUEUE_ORDER`, `QUEUE_SECTIONS`); a section is a no-prop component registered under its key (13). Paging: `QUEUE_PAGE`, `QUEUE_MAX_OFFSET`, `nextQueueOffset` in `api/librarian.js`."
  - Under **Notes**, add a dated line: "2026-09-29 (13): health checks cover live real rooms only (no singletons); positions are checked where the page places a book (deepest membership); gaps above position 200 are not checked. `works.NO_COVER_SQL` is the cover ladder as SQL; any change to `load_work_presentation`'s cover rule must change both (a test pins them)."
- `ROADMAP.md`, Phase 5 table, directly under the **Librarian tools** row, add:
  `| ✅ | **Librarian queue** — \`/librarian?tab=queue\`: series health problems (gaps, shared places, books without a cover, one-book series), computed on request and paged, each linking into the series page in edit mode. | [roadmap](docs/librarian-ux-roadmap.md), \`services/librarian/health.py\`, \`api/librarian_queue.py\`, \`components/librarian/\`, \`pages/Librarian.jsx\` |`
- `CLAUDE.md`, backend architecture, in the `librarian/` sentence of the services list: add `health` to the module list and append "`health` computes the queue's series problems on request (no table), one bounded SQL statement per check under a statement budget; it and later queue sources are served by `api/librarian_queue.py` (`/api/librarian/queue/*`)." Under **Works vs editions**' cover paragraph (the one about `load_work_presentation`), append: "`works.NO_COVER_SQL` is the same cover rule in SQL; change both together."
- `README.md`, Key API routes, after the librarian lines: `GET    /api/librarian/queue/health?kind=&limit=&offset=      (series health problems)`.

- [ ] **Step 2: Verify everything, then commit**

Run: `PYTEST -q -p no:warnings`, then `cd frontend && npm test && npm run build`.
Expected: all green.

```bash
git add docs/librarian-ux-roadmap.md ROADMAP.md CLAUDE.md README.md docs/superpowers/plans/2026-09-29-lx13-series-health-queue.md
git commit -m "docs: librarian queue and series health checks"
```

---

## Self-review

- **Roadmap coverage:** gaps, two books at one position, books without a cover, real series with one book (Task 2); computed on request, no table (no migration anywhere); `GET health` shape (Tasks 2–3); tabs with `?tab=queue` (Task 5); queue order reports · duplicates · health with no placeholders (Tasks 4–5, `queueSections.js` + the region-order test); links into the series page in edit mode (Task 4 `issueHref`, Task 6); 401/403 (Task 3); one e2e (Task 6); tracker, ROADMAP.md, CLAUDE.md (Task 7).
- **Placeholders:** none; every code step has the code, every run step its command and expected result.
- **Names:** `HealthIssue`/`HealthKind` (Task 2) are what Task 3 imports; `health_issues(db, *, kind, limit, offset)` matches its call; `QueueTooSlow` is in `errors.py`, which `_run` maps by `status_code`; `useHealthIssues`, `QUEUE_PAGE`, `nextQueueOffset`, `QueueSection`, `QUEUE_ORDER`, `QUEUE_SECTIONS` are used with the same names in Tasks 4–5 and in plans 14 and 15.
- **Review Focus:** each of the five lines has a named test in the task that owns the code.
