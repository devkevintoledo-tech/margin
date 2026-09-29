# Fix Log Filters, Links and Per-Book History Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Librarians can narrow the `/librarian` fix log by op, who, text and batch (and the filters live in the URL). Every subject links to its page, a batch folds into one expandable row, and in edit mode each book on a series page gets a `history` float that lists that book's fixes and can undo them.

**Architecture:** `GET /api/librarian/corrections` gains `op`, `user`, `q` and `batch_id` filters. `CorrectionOut` gains `subject_href`. The response is built for the whole page at once by a new `services/librarian/log.py` (`find_corrections`, `corrections_out`), which replaces today's per-row lookups (5+ queries per row) with a fixed number of queries. `undo.undoable_ids` is the batched form of `undoable` and becomes the only copy of that rule. The frontend reads and writes filters with `useSearchParams`. Batches are grouped by a pure `groupBatches` helper. A `HistoryFloat` component reuses `useCorrections({ workId })` and `useRevertCorrection`.

**Tech Stack:** FastAPI, async SQLAlchemy 2.0 (Postgres `DISTINCT ON`), Pydantic v2, React 18 + React Router `useSearchParams` + React Query, Tailwind tokens, pytest, Vitest + RTL, Playwright.

**Spec:** docs/librarian-ux-roadmap.md §11

- [ ] **Roadmap item:** 11 — tick in docs/librarian-ux-roadmap.md when merged

## Global Constraints

- Depends on item **08** being merged. `catalog_corrections.batch_id uuid null, indexed`, `CorrectionOut.batch_id`, and `POST /api/librarian/batches/{batch_id}/revert` → `BatchOut {batch_id, corrections: [CorrectionOut]}` already exist. Check before starting: `grep -n batch_id backend/app/models/correction.py backend/app/schemas/librarian.py` must print both.
- Shared names (binding, from the roadmap): `GET /api/librarian/corrections` gains `op`, `user` (username), `q` (reason/subject text), `batch_id`. `CorrectionOut` gains `subject_href` (a frontend path). New librarian components live in `frontend/src/components/librarian/`. The float is named `history`.
- Repo rules in `CLAUDE.md` apply verbatim: `api/` stays thin, `services/librarian/` is the only writer of `catalog_corrections`, async everywhere, schemas built explicitly (never `model_validate` of an ORM object), design tokens only, serif only for book titles and series names, no new radii/shadows/sizes/durations, `aria-hidden` on every glyph, and the §36 test.
- Allowed literal glyphs: tree elbows `├─` `└─`, sort carets, and `■`. Every one is `aria-hidden`. No `▸`/`✕`: expand and close controls are words.
- No new write and no new route. This item adds query parameters and one response field, so no migration and no new permission test module. A reader still gets 403 on the filtered list (Task 3 asserts it).
- Pagination that exists today (`limit` 1–200, default 50; `offset` ≥ 0; order `created_at desc, id desc`) must keep working, combined with every filter.
- Branch `feat/librarian-lx11-fix-log-history` from `main`, one commit per task, PR to `main`.
- Backend tests run in the backend container against `margin_test` with the pipeline mounted. From the repo root:
  `docker compose run --rm --no-deps -v "$PWD/pipeline:/pipeline:ro" -e DATABASE_URL=postgresql+asyncpg://margin:margin@db:5432/margin_test backend pytest <args>`
  This is referred to below as **`PYTEST`**. Frontend unit tests run from `frontend/`: `npx vitest run <path>`.

## Review Focus

1. **A hand-edited or stale URL** (`?op=bogus`, `?batch_id=abc`). The page must still load the log, ignoring the bad value, and must not show an error from a 422. Task 4 `filtersFromParams drops values the API would refuse`.
2. **A batch split across the 50-row page boundary.** The group shows only the members on this page. `only this batch` must show every member (the `batch_id` filter, ungrouped). Task 5 `folds a batch…` and Task 3 `test_batch_filter_returns_every_member`.
3. **Text search that contains `%` or `_`, or matches only the room's name.** A literal `%` in a reason must not match everything. A book's fix must not match because its *room* shares the words, since the subject is the book. Task 3 `test_q_matches_reason_and_subject_not_the_room`.
4. **Undoing from history moves the book out of the room.** The float unmounts with its row. Focus must not be stranded and nothing may throw. Task 6 covers the close path. The e2e (Task 7) undoes a `set_position` so the row stays, and checks the log afterwards.
5. **A book that absorbed a duplicate.** Its history should include the fixes made to the duplicate before the merge, because a librarian thinks of them as one book now. Task 3 `test_work_filter_includes_books_merged_into_it`.

---

## File Structure

**Backend — create**
- `backend/app/services/librarian/log.py`: `find_corrections(...)` (filtered, paginated query) and `corrections_out(db, rows)` (batched `CorrectionOut` builder).
- `backend/tests/query_count.py`: `count_statements(session)`, which counts the SQL statements a block issues.
- `backend/tests/test_librarian_log.py`: filters, `subject_href`, statement counts, `undoable_ids` parity.

**Backend — modify**
- `backend/app/services/librarian/undo.py`: add `undoable_ids`. `undoable` delegates to it.
- `backend/app/schemas/librarian.py`: `CorrectionOut.subject_href`.
- `backend/app/api/librarian.py`: `correction_out` delegates to `corrections_out`. `list_corrections` gains filters and delegates to `find_corrections`.
- `backend/tests/librarian_factories.py`: `make_fix_row`.

**Frontend — create**
- `frontend/src/components/librarian/fixLog.js` (+ `fixLog.test.js`): `OPS`, `EMPTY_FILTERS`, `filtersFromParams`, `withFilters`, `hasFilters`, `groupBatches`.
- `frontend/src/components/librarian/HistoryFloat.jsx` (+ `HistoryFloat.test.jsx`).

**Frontend — modify**
- `frontend/src/api/librarian.js`: `useCorrections` takes every filter. `useRevertBatch` is added if 08 did not add it.
- `frontend/src/pages/Librarian.jsx` (+ test): filter bar in the URL, `subject_href` links, batch groups.
- `frontend/src/pages/Series.jsx` (+ test): `history` row action and float.
- `frontend/e2e/librarian.spec.js`: one new scenario.

**Docs — modify:** `docs/librarian-ux-roadmap.md`, `ROADMAP.md`, `CLAUDE.md`, `README.md`.

---

### Task 1: One undo-eligibility rule, batched

**Files:**
- Modify: `backend/app/services/librarian/undo.py` (`undoable`, plus a new `undoable_ids` below it)
- Modify: `backend/tests/librarian_factories.py` (append `make_fix_row`)
- Create: `backend/tests/test_librarian_log.py`

**Interfaces:**
- Consumes: `UNDOABLE`, `SERIES_SUBJECT_OPS` (from `record.py`), `CatalogCorrection.batch_id` (08).
- Produces: `undoable_ids(db: AsyncSession, rows: Sequence[CatalogCorrection]) -> set[UUID]`. It issues at most 4 statements whatever `len(rows)` is. `undoable(db, c)` keeps its signature and now returns `c.id in await undoable_ids(db, [c])`.
- Produces (tests): `make_fix_row(db, user, op, *, work=None, series=None, reason="r", created_at=None, reverted_at=None, batch_id=None, exported=False) -> CatalogCorrection`, which writes a log row directly for read-side tests.

- [ ] **Step 1: Create the branch and confirm 08 is in**

```bash
git switch main && git pull && git switch -c feat/librarian-lx11-fix-log-history
grep -n batch_id backend/app/models/correction.py backend/app/schemas/librarian.py
```
Expected: one line from each file. If either is missing, stop, because 08 has not merged.

Then check whether 08 changed the undo rule. Run: `git log --oneline -- backend/app/services/librarian/undo.py`. If a commit after the v1 merge touched `undoable()`, note each added condition. Step 5 must carry every one of them into `undoable_ids`, and Step 1b adds a row for each to the parity test.

- [ ] **Step 1b: Add the test factory**

Append to `backend/tests/librarian_factories.py`, and add `CatalogCorrection` to its `from app.models import (...)` list:

```python
async def make_fix_row(db, user, op, *, work=None, series=None, reason="r", created_at=None,
                       reverted_at=None, batch_id=None, exported=False):
    """A catalog_corrections row written straight to the table, for tests that
    only *read* the log. Real fixes go through services/librarian."""
    c = CatalogCorrection(
        op=op, user_id=user.id, reason=reason, payload={},
        override=[{"test": True}] if exported else None,
        runtime_only_reason=None if exported else "written by a test",
        work_id=work.id if work is not None else None,
        series_id=series.id if series is not None else None,
        reverted_at=reverted_at, batch_id=batch_id,
    )
    if created_at is not None:
        c.created_at = created_at
    db.add(c)
    await db.flush()
    return c
```

- [ ] **Step 2: Write the failing parity test**

`backend/tests/test_librarian_log.py`:

```python
"""Reading the fix log: filters, links, batching, and what it costs."""

import uuid
from datetime import datetime, timedelta, timezone

from app.models import CorrectionOp
from app.services.librarian.undo import undoable, undoable_ids
from tests.librarian_factories import headers_for, make_fix_row, make_series, make_user, make_work

T0 = datetime(2026, 9, 1, tzinfo=timezone.utc)


def at(minutes: int) -> datetime:
    return T0 + timedelta(minutes=minutes)


async def test_undoable_ids_agrees_with_undoable_row_by_row(db_session):
    lib = await make_user(db_session, librarian=True)
    saga, other = await make_series(db_session, "Saga"), await make_series(db_session, "Other")
    a = await make_work(db_session, "A", series=saga)
    b = await make_work(db_session, "B", series=saga)
    gone = await make_work(db_session, "Gone", series=saga)
    gone.merged_into_id = b.id
    await db_session.flush()
    op = CorrectionOp
    rows = {
        "a_old": await make_fix_row(db_session, lib, op.set_series, work=a, series=saga, created_at=at(1)),
        "a_new": await make_fix_row(db_session, lib, op.set_position, work=a, series=saga, created_at=at(2)),
        "a_reverted": await make_fix_row(db_session, lib, op.set_position, work=a, series=saga,
                                         created_at=at(3), reverted_at=at(4)),
        "b_merge": await make_fix_row(db_session, lib, op.merge_works, work=b, series=saga, created_at=at(5)),
        "gone": await make_fix_row(db_session, lib, op.set_series, work=gone, series=saga, created_at=at(6)),
        "rename_old": await make_fix_row(db_session, lib, op.rename_series, series=other, created_at=at(7)),
        "reject_new": await make_fix_row(db_session, lib, op.reject_series, series=other, created_at=at(8)),
        # Same series id, but a book's fix: it must not hide reject_new.
        "b_move": await make_fix_row(db_session, lib, op.set_series, work=b, series=other, created_at=at(9)),
        "orphan": await make_fix_row(db_session, lib, op.set_series, created_at=at(10)),
    }
    batched = await undoable_ids(db_session, list(rows.values()))
    one_by_one = {c.id for c in rows.values() if await undoable(db_session, c)}
    assert batched == one_by_one
    assert batched == {rows[k].id for k in ("a_new", "reject_new", "b_move")}
    assert await undoable_ids(db_session, []) == set()
```

- [ ] **Step 3: Run it to verify it fails**

Run: `PYTEST tests/test_librarian_log.py -q`
Expected: FAIL with `ImportError: cannot import name 'undoable_ids' from 'app.services.librarian.undo'`.

- [ ] **Step 4: Implement `undoable_ids`**

In `backend/app/services/librarian/undo.py`, add `from collections.abc import Sequence` to the imports. Then add below `undoable`:

```python
async def undoable_ids(db: AsyncSession, rows: Sequence[CatalogCorrection]) -> set[UUID]:
    """``undoable`` for a whole page of the log: at most four statements, however
    many rows. The latest live fix on a subject that still exists."""
    candidates = [c for c in rows if c.op in UNDOABLE and c.reverted_at is None]
    work_ids = {c.work_id for c in candidates if c.op not in SERIES_SUBJECT_OPS and c.work_id is not None}
    series_ids = {c.series_id for c in candidates if c.op in SERIES_SUBJECT_OPS and c.series_id is not None}
    live_works: set[UUID] = set()
    live_series: set[UUID] = set()
    latest_work: dict[UUID, UUID] = {}
    latest_series: dict[UUID, UUID] = {}
    if work_ids:
        live_works = set((await db.execute(select(Work.id).where(
            Work.id.in_(work_ids), Work.merged_into_id.is_(None)))).scalars())
        latest_work = dict((await db.execute(
            select(CatalogCorrection.work_id, CatalogCorrection.id)
            .where(CatalogCorrection.work_id.in_(work_ids), CatalogCorrection.reverted_at.is_(None))
            .order_by(CatalogCorrection.work_id, CatalogCorrection.created_at.desc(), CatalogCorrection.id.desc())
            .distinct(CatalogCorrection.work_id)
        )).all())
    if series_ids:
        live_series = set((await db.execute(select(Series.id).where(
            Series.id.in_(series_ids), Series.merged_into_id.is_(None)))).scalars())
        latest_series = dict((await db.execute(
            select(CatalogCorrection.series_id, CatalogCorrection.id)
            .where(CatalogCorrection.series_id.in_(series_ids), CatalogCorrection.reverted_at.is_(None),
                   CatalogCorrection.op.in_(SERIES_SUBJECT_OPS))
            .order_by(CatalogCorrection.series_id, CatalogCorrection.created_at.desc(), CatalogCorrection.id.desc())
            .distinct(CatalogCorrection.series_id)
        )).all())

    def ok(c: CatalogCorrection) -> bool:
        if c.op in SERIES_SUBJECT_OPS:
            return c.series_id in live_series and latest_series.get(c.series_id) == c.id
        return c.work_id in live_works and latest_work.get(c.work_id) == c.id

    return {c.id for c in candidates if ok(c)}
```

If Step 1 found conditions that 08 added to `undoable`, add each one to `ok()` here, and add a matching row to the parity test.

- [ ] **Step 5: Run it to verify it passes**

Run: `PYTEST tests/test_librarian_log.py -q`
Expected: `1 passed`.

- [ ] **Step 6: Make `undoable` delegate, so there is one rule**

Replace the body of `undoable` in `undo.py`:

```python
async def undoable(db: AsyncSession, c: CatalogCorrection) -> bool:
    """What the log's undo button shows: the latest live fix on a subject that
    still exists. revert re-checks everything else. The rule lives in
    ``undoable_ids``; this is its one-row form."""
    return c.id in await undoable_ids(db, [c])
```

`_subject` stays, because `revert` still uses it.

Run: `PYTEST tests/test_librarian_log.py tests/test_librarian_undo.py tests/test_librarian_hardening.py tests/test_librarian_api.py -q`
Expected: all pass. The parity test still passes, because it now compares the rule with itself. The explicit expected set is what pins it.

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/librarian/undo.py backend/tests/librarian_factories.py backend/tests/test_librarian_log.py
git commit -m "feat(librarian): undoable_ids, the batched undo rule"
```

---

### Task 2: Build a page of the log in a fixed number of queries, with `subject_href`

**Files:**
- Create: `backend/app/services/librarian/log.py`
- Create: `backend/tests/query_count.py`
- Modify: `backend/app/schemas/librarian.py` (`CorrectionOut`)
- Modify: `backend/app/api/librarian.py` (`correction_out`, imports)
- Test: `backend/tests/test_librarian_log.py`

**Interfaces:**
- Consumes: `undoable_ids` (Task 1), `make_fix_row` (Task 1).
- Produces: `corrections_out(db: AsyncSession, rows: Sequence[CatalogCorrection]) -> list[CorrectionOut]`, which issues ≤ 9 statements for any `len(rows)`. `CorrectionOut.subject_href: str | None` is `/series/{room_slug}?book={work_id}` for a book subject (following a merge to the survivor), `/series/{slug}` for a series subject, or `None` when the subject is gone. `api.librarian.correction_out(db, c)` keeps its signature, so 08's batch route and every write route keep working.
- Produces (tests): `tests/query_count.count_statements(session)`, a context manager that yields the list of SQL strings run inside it. Plan 12 uses it.

- [ ] **Step 1: Add the statement counter**

`backend/tests/query_count.py`:

```python
"""Count the SQL a block of code sends, to pin 'no per-row queries'."""

from contextlib import contextmanager

from sqlalchemy import event


@contextmanager
def count_statements(session):
    engine = session.bind.sync_engine
    seen: list[str] = []

    def before(conn, cursor, statement, parameters, context, executemany):
        seen.append(statement)

    event.listen(engine, "before_cursor_execute", before)
    try:
        yield seen
    finally:
        event.remove(engine, "before_cursor_execute", before)
```

- [ ] **Step 2: Write the failing tests**

Append to `backend/tests/test_librarian_log.py`, and add `from tests.query_count import count_statements` to its imports:

```python
async def test_subject_href_points_at_the_book_in_its_room_or_at_the_series(client, db_session):
    lib = await make_user(db_session, librarian=True)
    saga = await make_series(db_session, "Saga")
    a = await make_work(db_session, "A", series=saga)
    b = await make_work(db_session, "B", series=saga)
    dup = await make_work(db_session, "B (dup)", series=saga)
    await make_fix_row(db_session, lib, CorrectionOp.set_position, work=a, series=saga, created_at=at(1))
    await make_fix_row(db_session, lib, CorrectionOp.set_position, work=dup, series=saga, created_at=at(2))
    dup.merged_into_id = b.id
    await make_fix_row(db_session, lib, CorrectionOp.rename_series, series=saga, created_at=at(3))
    await make_fix_row(db_session, lib, CorrectionOp.set_series, created_at=at(4))  # subject deleted
    await db_session.flush()

    rows = (await client.get("/api/librarian/corrections", headers=headers_for(lib))).json()
    assert [(r["op"], r["subject"], r["subject_href"]) for r in rows] == [
        ("set_series", None, None),
        ("rename_series", "Saga", f"/series/{saga.slug}"),
        ("set_position", "B", f"/series/{saga.slug}?book={b.id}"),  # followed the merge
        ("set_position", "A", f"/series/{saga.slug}?book={a.id}"),
    ]
    assert all(r["batch_id"] is None for r in rows)


async def _seed(db, lib, n):
    """n book fixes in n rooms, plus one fix on a merged-away book and one rename."""
    for i in range(n):
        room = await make_series(db, f"Room {uuid.uuid4().hex[:6]}")
        w = await make_work(db, f"Book {i}", series=room)
        await make_fix_row(db, lib, CorrectionOp.set_series, work=w, series=room, created_at=at(i))
    room = await make_series(db, f"Merged {uuid.uuid4().hex[:6]}")
    keep = await make_work(db, "Keep", series=room)
    lost = await make_work(db, "Lost", series=room)
    await make_fix_row(db, lib, CorrectionOp.set_position, work=lost, series=room, created_at=at(n))
    lost.merged_into_id = keep.id
    await make_fix_row(db, lib, CorrectionOp.rename_series, series=room, created_at=at(n + 1))
    await db.flush()


async def test_a_page_of_the_log_costs_the_same_queries_for_5_or_25_fixes(client, db_session):
    lib = await make_user(db_session, librarian=True)
    headers = headers_for(lib)
    await _seed(db_session, lib, 5)
    db_session.expunge_all()  # a real request starts with an empty session
    with count_statements(db_session) as small:
        resp = await client.get("/api/librarian/corrections?limit=200", headers=headers)
    assert len(resp.json()) == 7

    await _seed(db_session, lib, 20)
    db_session.expunge_all()
    with count_statements(db_session) as big:
        resp = await client.get("/api/librarian/corrections?limit=200", headers=headers)
    assert len(resp.json()) == 29
    assert len(big) == len(small), big
```

- [ ] **Step 3: Run them to verify they fail**

Run: `PYTEST tests/test_librarian_log.py -q`
Expected: the href test fails with `KeyError: 'subject_href'`. The count test fails on `assert len(big) == len(small)`, because today each row issues its own `latest_for_subject` query.

- [ ] **Step 4: Add the schema field**

In `backend/app/schemas/librarian.py`, add to `CorrectionOut` after `subject`:

```python
    # Where the subject can be seen, as a frontend path: the book on its room's
    # page (?book=), or the series. Null once the subject is gone.
    subject_href: str | None = None
```

- [ ] **Step 5: Write `services/librarian/log.py`**

```python
"""Reading the corrections log: one query for a page's rows, and a fixed number
more to describe them. Nothing here writes."""

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import CatalogCorrection, Series, User, Work
from app.schemas.librarian import CorrectionOut
from app.services.librarian.undo import undoable_ids


async def _by_id(db: AsyncSession, model, ids: set) -> dict:
    ids = {i for i in ids if i is not None}
    if not ids:
        return {}
    return {row.id: row for row in (await db.execute(select(model).where(model.id.in_(ids)))).scalars()}


async def corrections_out(db: AsyncSession, rows: Sequence[CatalogCorrection]) -> list[CorrectionOut]:
    if not rows:
        return []
    users = await _by_id(db, User, {c.user_id for c in rows})
    works = await _by_id(db, Work, {c.work_id for c in rows})
    # Merges repoint, so one hop reaches the survivor (as canonical_work does).
    works |= await _by_id(db, Work, {w.merged_into_id for w in works.values()} - works.keys())

    def canonical(w: Work) -> Work:
        return works.get(w.merged_into_id, w) if w.merged_into_id is not None else w

    subjects = {wid: canonical(w) for wid, w in works.items()}
    series = await _by_id(db, Series, {w.series_id for w in subjects.values()} | {c.series_id for c in rows})
    live = await undoable_ids(db, rows)

    out = []
    for c in rows:
        subject = room_slug = href = None
        work = subjects.get(c.work_id) if c.work_id is not None else None
        if work is not None:
            room = series.get(work.series_id)
            subject = work.title
            if room is not None:
                room_slug, href = room.slug, f"/series/{room.slug}?book={work.id}"
        elif c.series_id is not None and (s := series.get(c.series_id)) is not None:
            subject, room_slug, href = s.name, s.slug, f"/series/{s.slug}"
        out.append(CorrectionOut(
            id=c.id, op=c.op, reason=c.reason, created_at=c.created_at, user=users[c.user_id].username,
            exportable=c.override is not None, runtime_only_reason=c.runtime_only_reason,
            undoable=c.id in live, reverted_at=c.reverted_at, room_slug=room_slug, subject=subject,
            subject_href=href, batch_id=c.batch_id,
        ))
    return out
```

If 08 added more fields to `CorrectionOut` than `batch_id`, open 08's `correction_out` (`git show main:backend/app/api/librarian.py`) and set the same fields here the same way.

- [ ] **Step 6: Make the route helper delegate**

In `backend/app/api/librarian.py`, replace the whole `correction_out` function with:

```python
async def correction_out(db: AsyncSession, c: CatalogCorrection) -> CorrectionOut:
    return (await corrections_out(db, [c]))[0]
```

Add `from app.services.librarian.log import corrections_out` to the imports. Remove the imports that are now unused: `undoable` from `app.services.librarian.undo` and `canonical_work` from `app.services.works` (`_work`, `_series`, `Book` and `func` are still used). In `list_corrections`, replace the last line with:

```python
    return await corrections_out(db, rows)
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `PYTEST tests/test_librarian_log.py tests/test_librarian_api.py tests/test_librarian_hardening.py -q`
Expected: all pass. Then run the whole librarian suite, `PYTEST tests -q -k librarian`, which includes 08's batch tests. Expected: all pass.

- [ ] **Step 8: Commit**

```bash
git add backend/app/services/librarian/log.py backend/app/schemas/librarian.py backend/app/api/librarian.py backend/tests/query_count.py backend/tests/test_librarian_log.py
git commit -m "feat(librarian): subject_href on fixes; build a page of the log without per-row queries"
```

---

### Task 3: Filters: op, who, text, batch

**Files:**
- Modify: `backend/app/services/librarian/log.py` (add `find_corrections`, `like_pattern`)
- Modify: `backend/app/api/librarian.py` (`list_corrections`)
- Test: `backend/tests/test_librarian_log.py`

**Interfaces:**
- Consumes: `corrections_out` (Task 2).
- Produces: `GET /api/librarian/corrections` query params `runtime_only`, `work_id`, `series_id` (unchanged); `op: CorrectionOp` (422 on an unknown value); `user: str ≤ 100` (username, case-insensitive exact match; an unknown name gives `[]`); `q: str ≤ 200` (case-insensitive substring of the reason or of the subject: the book's current title for a book fix, the series' name when there is no book); `batch_id: UUID` (422 when malformed); `limit`, `offset` (unchanged). Blank `user`/`q` mean "no filter". `work_id` now also matches fixes whose book was merged into that work.
- Produces: `find_corrections(db, *, runtime_only=None, work_id=None, series_id=None, op=None, username=None, q=None, batch_id=None, limit=50, offset=0) -> list[CatalogCorrection]`.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_librarian_log.py`:

```python
async def _cast(db):
    """Two librarians, a saga with two books, and five fixes, newest last."""
    ada = await make_user(db, librarian=True, username=f"Ada{uuid.uuid4().hex[:4]}")
    bo = await make_user(db, librarian=True)
    saga = await make_series(db, "Red Rising")
    gold = await make_work(db, "Golden Son", series=saga)
    star = await make_work(db, "Morning Star", series=saga)
    batch = uuid.uuid4()
    rows = [
        await make_fix_row(db, ada, CorrectionOp.set_position, work=gold, series=saga, reason="book two",
                           created_at=at(1), batch_id=batch),
        await make_fix_row(db, ada, CorrectionOp.set_position, work=star, series=saga, reason="book three",
                           created_at=at(2), batch_id=batch),
        await make_fix_row(db, bo, CorrectionOp.merge_works, work=gold, series=saga, reason="100% the same",
                           created_at=at(3)),
        await make_fix_row(db, bo, CorrectionOp.rename_series, series=saga, reason="official name",
                           created_at=at(4)),
        await make_fix_row(db, ada, CorrectionOp.set_series, work=star, series=saga, reason="trilogy",
                           created_at=at(5)),
    ]
    return ada, bo, saga, gold, star, batch, rows


async def _reasons(client, lib, query=""):
    resp = await client.get(f"/api/librarian/corrections{query}", headers=headers_for(lib))
    assert resp.status_code == 200, resp.text
    return [r["reason"] for r in resp.json()]


async def test_op_filter_and_unknown_op_is_422(client, db_session):
    ada, *_ = await _cast(db_session)
    assert await _reasons(client, ada, "?op=set_position") == ["book three", "book two"]
    assert (await client.get("/api/librarian/corrections?op=bogus", headers=headers_for(ada))).status_code == 422


async def test_user_filter_is_the_username_any_case(client, db_session):
    ada, bo, *_ = await _cast(db_session)
    assert await _reasons(client, ada, f"?user={ada.username.lower()}") == ["trilogy", "book three", "book two"]
    assert await _reasons(client, ada, f"?user={bo.username}") == ["official name", "100% the same"]
    assert await _reasons(client, ada, "?user=nobody") == []
    assert len(await _reasons(client, ada, "?user=%20%20")) == 5  # blank is no filter


async def test_q_matches_reason_and_subject_not_the_room(client, db_session):
    ada, *_ = await _cast(db_session)
    assert await _reasons(client, ada, "?q=BOOK%20T") == ["book three", "book two"]  # reason, any case
    assert await _reasons(client, ada, "?q=morning") == ["trilogy", "book three"]  # the book's title
    # The series' name matches the rename (its subject) but not the books' fixes in that room.
    assert await _reasons(client, ada, "?q=red%20rising") == ["official name"]
    assert await _reasons(client, ada, "?q=%25") == ["100% the same"]  # a literal %, not a wildcard


async def test_batch_filter_returns_every_member_and_bad_ids_are_422(client, db_session):
    ada, _, _, _, _, batch, _ = await _cast(db_session)
    assert await _reasons(client, ada, f"?batch_id={batch}") == ["book three", "book two"]
    assert (await client.get("/api/librarian/corrections?batch_id=abc", headers=headers_for(ada))).status_code == 422


async def test_filters_combine_and_paginate(client, db_session):
    ada, *_ = await _cast(db_session)
    assert await _reasons(client, ada, f"?user={ada.username}&op=set_position&q=three") == ["book three"]
    assert await _reasons(client, ada, "?limit=2") == ["trilogy", "official name"]
    assert await _reasons(client, ada, "?limit=2&offset=2") == ["100% the same", "book three"]
    assert await _reasons(client, ada, f"?user={ada.username}&limit=1&offset=1") == ["book three"]


async def test_work_filter_includes_books_merged_into_it(client, db_session):
    ada, _, saga, gold, star, *_ = await _cast(db_session)
    dup = await make_work(db_session, "Golden Son (dup)", series=saga)
    await make_fix_row(db_session, ada, CorrectionOp.set_position, work=dup, series=saga, reason="dup placed",
                       created_at=at(0))
    dup.merged_into_id = gold.id
    await db_session.flush()
    assert await _reasons(client, ada, f"?work_id={gold.id}") == ["100% the same", "book two", "dup placed"]


async def test_filtered_log_still_refuses_readers(client, db_session):
    reader = await make_user(db_session)
    resp = await client.get("/api/librarian/corrections?op=set_series&q=x", headers=headers_for(reader))
    assert resp.status_code == 403
```

- [ ] **Step 2: Run them to verify they fail**

Run: `PYTEST tests/test_librarian_log.py -q`
Expected: the new tests fail. Unknown params are ignored today, so for example `test_op_filter…` gets 5 reasons instead of 2, and `?op=bogus` returns 200. `test_filtered_log_still_refuses_readers` already passes. `test_work_filter…` fails because `dup placed` is missing.

- [ ] **Step 3: Implement `find_corrections`**

Append to `backend/app/services/librarian/log.py`, and extend its imports to `from sqlalchemy import and_, func, or_, select`, `from sqlalchemy.orm import aliased`, `from app.models import CatalogCorrection, CorrectionOp, Series, User, Work`:

```python
def like_pattern(text: str) -> str:
    """``%text%`` for ILIKE with ``\\`` as the escape, so % and _ match themselves."""
    escaped = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


async def find_corrections(
    db: AsyncSession, *, runtime_only: bool | None = None, work_id: UUID | None = None,
    series_id: UUID | None = None, op: CorrectionOp | None = None, username: str | None = None,
    q: str | None = None, batch_id: UUID | None = None, limit: int = 50, offset: int = 0,
) -> list[CatalogCorrection]:
    """The log, newest first. ``q`` matches the reason or the subject the log
    shows: the book's current title, or the series' name when there is no book."""
    query = select(CatalogCorrection)
    if runtime_only is not None:
        query = query.where(CatalogCorrection.override.is_(None) if runtime_only
                            else CatalogCorrection.override.is_not(None))
    if work_id is not None:
        # A book's history includes the books merged into it (merges repoint: one hop).
        absorbed = select(Work.id).where(Work.merged_into_id == work_id)
        query = query.where(or_(CatalogCorrection.work_id == work_id, CatalogCorrection.work_id.in_(absorbed)))
    if series_id is not None:
        query = query.where(CatalogCorrection.series_id == series_id)
    if op is not None:
        query = query.where(CatalogCorrection.op == op)
    if username and username.strip():
        query = query.where(CatalogCorrection.user_id.in_(
            select(User.id).where(func.lower(User.username) == username.strip().lower())))
    if batch_id is not None:
        query = query.where(CatalogCorrection.batch_id == batch_id)
    if q and q.strip():
        pattern = like_pattern(q.strip())
        subject, canon, room = aliased(Work), aliased(Work), aliased(Series)
        query = (
            query.outerjoin(subject, subject.id == CatalogCorrection.work_id)
            .outerjoin(canon, canon.id == subject.merged_into_id)
            .outerjoin(room, room.id == CatalogCorrection.series_id)
            .where(or_(
                CatalogCorrection.reason.ilike(pattern, escape="\\"),
                func.coalesce(canon.title, subject.title).ilike(pattern, escape="\\"),
                and_(subject.id.is_(None), room.name.ilike(pattern, escape="\\")),
            ))
        )
    query = query.order_by(CatalogCorrection.created_at.desc(), CatalogCorrection.id.desc()).limit(limit).offset(offset)
    return list((await db.execute(query)).scalars().all())
```

The three outer joins are one-to-one (each on a primary key), so they never duplicate a row, and `limit` stays exact.

- [ ] **Step 4: Make the route delegate**

Replace `list_corrections` in `backend/app/api/librarian.py` with the version below, and add `CorrectionOp` to the `from app.models import ...` line and `find_corrections` to the `log` import:

```python
@router.get("/corrections", response_model=list[CorrectionOut])
async def list_corrections(
    runtime_only: bool | None = None, work_id: UUID | None = None, series_id: UUID | None = None,
    op: CorrectionOp | None = None, user: str | None = Query(None, max_length=100),
    q: str | None = Query(None, max_length=200), batch_id: UUID | None = None,
    limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db), _librarian: User = Depends(require_librarian),
):
    """``user`` is the filter (a username); the caller is ``_librarian``."""
    rows = await find_corrections(db, runtime_only=runtime_only, work_id=work_id, series_id=series_id, op=op,
                                  username=user, q=q, batch_id=batch_id, limit=limit, offset=offset)
    return await corrections_out(db, rows)
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `PYTEST tests/test_librarian_log.py tests/test_librarian_api.py tests/test_librarian_hardening.py tests/test_openapi.py -q`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/librarian/log.py backend/app/api/librarian.py backend/tests/test_librarian_log.py
git commit -m "feat(librarian): filter the fix log by op, who, text and batch"
```

---

### Task 4: Frontend filter state and batch grouping (pure)

**Files:**
- Create: `frontend/src/components/librarian/fixLog.js`
- Create: `frontend/src/components/librarian/fixLog.test.js`
- Modify: `frontend/src/api/librarian.js` (`useCorrections`, and `useRevertBatch` if it is absent)

**Interfaces:**
- Consumes: the API params from Task 3.
- Produces:
  - `OPS: string[]`, every `CorrectionOp` value.
  - `EMPTY_FILTERS = { op: '', user: '', q: '', batchId: '', runtimeOnly: false }`.
  - `filtersFromParams(URLSearchParams) -> Filters`, which drops an unknown `op` and a non-UUID `batch_id`.
  - `withFilters(URLSearchParams, Filters) -> URLSearchParams`, which keeps unrelated params such as 13's `tab`.
  - `hasFilters(Filters) -> boolean`.
  - `groupBatches(rows) -> Array<{ kind: 'fix', row } | { kind: 'batch', batchId, rows }>`, in first-appearance order.
  - URL keys: `op`, `user`, `q`, `batch_id`, `runtime_only=1`.
  - `useCorrections({ runtimeOnly, op, user, q, batchId, workId, limit } = {})` sends only the set params, with API names.
  - `useRevertBatch()`: a mutation of `batchId`.

- [ ] **Step 1: Write the failing tests**

`frontend/src/components/librarian/fixLog.test.js`:

```js
import { describe, it, expect } from 'vitest'
import { EMPTY_FILTERS, OPS, filtersFromParams, groupBatches, hasFilters, withFilters } from './fixLog'

const B = '0b0b0b0b-0000-4000-8000-000000000001'

describe('fix log filters', () => {
  it('reads every filter from the URL', () => {
    const f = filtersFromParams(new URLSearchParams(`op=set_series&user=%20ada%20&q=gold&batch_id=${B}&runtime_only=1`))
    expect(f).toEqual({ op: 'set_series', user: 'ada', q: 'gold', batchId: B, runtimeOnly: true })
  })

  it('filtersFromParams drops values the API would refuse', () => {
    const f = filtersFromParams(new URLSearchParams('op=bogus&batch_id=abc&runtime_only=yes'))
    expect(f).toEqual(EMPTY_FILTERS)
  })

  it('writes filters back, keeping params it does not own', () => {
    const next = withFilters(new URLSearchParams('tab=fixes&op=merge_works'), { ...EMPTY_FILTERS, user: 'ada', q: ' dup ' })
    expect(next.toString()).toBe('tab=fixes&user=ada&q=dup')
    expect(withFilters(next, EMPTY_FILTERS).toString()).toBe('tab=fixes')
  })

  it('knows when anything is filtered', () => {
    expect(hasFilters(EMPTY_FILTERS)).toBe(false)
    expect(hasFilters({ ...EMPTY_FILTERS, runtimeOnly: true })).toBe(true)
  })

  it('lists every v1 op', () => {
    expect(OPS).toEqual(expect.arrayContaining([
      'merge_works', 'split_work', 'set_series', 'set_position', 'remove_from_series', 'reject_series', 'rename_series',
    ]))
  })
})

describe('groupBatches', () => {
  it('folds rows sharing a batch into one entry where the batch first appears', () => {
    const rows = [{ id: 'c5', batch_id: null }, { id: 'c4', batch_id: B }, { id: 'c3', batch_id: null }, { id: 'c2', batch_id: B }]
    expect(groupBatches(rows)).toEqual([
      { kind: 'fix', row: rows[0] },
      { kind: 'batch', batchId: B, rows: [rows[1], rows[3]] },
      { kind: 'fix', row: rows[2] },
    ])
  })

  it('keeps a lone member of a batch as a group, so it still says it was a batch', () => {
    expect(groupBatches([{ id: 'c1', batch_id: B }])).toEqual([{ kind: 'batch', batchId: B, rows: [{ id: 'c1', batch_id: B }] }])
  })
})
```

- [ ] **Step 2: Run them to verify they fail**

Run (from `frontend/`): `npx vitest run src/components/librarian/fixLog.test.js`
Expected: FAIL with `Failed to resolve import "./fixLog"`.

- [ ] **Step 3: Implement `fixLog.js`**

First list the backend enum values: `grep -n ' = "' backend/app/models/correction.py`. `OPS` must hold exactly those values, in that order. The array below is the v1 set. Append `'set_cover'` and `'set_metadata'` if items 06/07 have merged and the grep shows them.

`frontend/src/components/librarian/fixLog.js`:

```js
/**
 * The fix log's filters live in the URL, so a filtered view can be shared and
 * survives a reload. These helpers are the only place that knows the keys.
 */

// Every CorrectionOp value (backend/app/models/correction.py), in its order.
export const OPS = [
  'merge_works', 'split_work', 'set_series', 'set_position', 'remove_from_series', 'reject_series', 'rename_series',
]

export const EMPTY_FILTERS = { op: '', user: '', q: '', batchId: '', runtimeOnly: false }

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i

/** Filters from the URL. A value the API would 422 on (a stale or hand-edited link) is dropped. */
export function filtersFromParams(params) {
  const op = params.get('op') ?? ''
  const batchId = params.get('batch_id') ?? ''
  return {
    op: OPS.includes(op) ? op : '',
    user: (params.get('user') ?? '').trim(),
    q: (params.get('q') ?? '').trim(),
    batchId: UUID_RE.test(batchId) ? batchId : '',
    runtimeOnly: params.get('runtime_only') === '1',
  }
}

/** ``params`` with the filter keys replaced by ``filters``; every other key is kept. */
export function withFilters(params, filters) {
  const next = new URLSearchParams(params)
  const put = (key, value) => (value ? next.set(key, value) : next.delete(key))
  put('op', filters.op)
  put('user', filters.user?.trim())
  put('q', filters.q?.trim())
  put('batch_id', filters.batchId)
  put('runtime_only', filters.runtimeOnly ? '1' : '')
  return next
}

export function hasFilters(f) {
  return !!(f.op || f.user || f.q || f.batchId || f.runtimeOnly)
}

/** Rows sharing a batch_id become one entry, placed where the batch first appears. */
export function groupBatches(rows) {
  const entries = []
  const batches = new Map()
  for (const row of rows) {
    if (!row.batch_id) {
      entries.push({ kind: 'fix', row })
      continue
    }
    let group = batches.get(row.batch_id)
    if (!group) {
      group = { kind: 'batch', batchId: row.batch_id, rows: [] }
      batches.set(row.batch_id, group)
      entries.push(group)
    }
    group.rows.push(row)
  }
  return entries
}
```

- [ ] **Step 4: Extend the hooks**

In `frontend/src/api/librarian.js`, replace `useCorrections` with:

```js
export function useCorrections({ runtimeOnly = false, op, user, q, batchId, workId, limit } = {}) {
  // Only set filters are sent, under the API's names.
  const params = {
    ...(runtimeOnly ? { runtime_only: true } : {}),
    ...(op ? { op } : {}),
    ...(user ? { user } : {}),
    ...(q ? { q } : {}),
    ...(batchId ? { batch_id: batchId } : {}),
    ...(workId ? { work_id: workId } : {}),
    ...(limit ? { limit } : {}),
  }
  return useQuery({
    queryKey: ['librarian', 'corrections', params],
    queryFn: () => client.get('/librarian/corrections', { params }).then((r) => r.data),
  })
}
```

Then run `grep -n "batches/" frontend/src/api/librarian.js`. If 08 already exports a hook that posts to `/librarian/batches/${id}/revert`, use its name wherever this plan says `useRevertBatch`. If not, append:

```js
export function useRevertBatch() {
  const invalidate = useInvalidateCatalog()
  return useMutation({
    mutationFn: (batchId) => client.post(`/librarian/batches/${batchId}/revert`).then((r) => r.data),
    onSuccess: invalidate,
  })
}
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `npx vitest run src/components/librarian/fixLog.test.js src/pages/Librarian.test.jsx`
Expected: all pass. The existing runtime-only test still sees `{ params: { runtime_only: true } }`.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/librarian/fixLog.js frontend/src/components/librarian/fixLog.test.js frontend/src/api/librarian.js
git commit -m "feat(web): fix log filter state and batch grouping helpers"
```

---

### Task 5: The fix log page: filters in the URL, subject links, batch rows

**Files:**
- Modify: `frontend/src/pages/Librarian.jsx` (the `Log` component; `Librarian` is unchanged)
- Test: `frontend/src/pages/Librarian.test.jsx`

**Interfaces:**
- Consumes: `fixLog.js` and the hooks (Task 4), `CorrectionOut.subject_href` and `batch_id`.
- Produces: `/librarian?op=&user=&q=&batch_id=&runtime_only=1`. A `form role="search"` named "Filter fixes" holds `Op` (select, applies on change), `Who`, and `Text` (apply on submit). The page also has `clear filters`, `only fixes by <name>` buttons in the By column, and a batch row whose Op cell is the toggle `batch · N fixes` (`aria-expanded`). Its Subject cell holds `only this batch`, and its undo is `undo batch of N fixes`. With `batch_id` set, rows render ungrouped.

If 08 already folded batches on this page, this task replaces 08's folding with the version below. Before editing, run 08's `Librarian.test.jsx` cases. Keep them, and adapt only selectors whose names changed.

- [ ] **Step 1: Write the failing tests**

In `frontend/src/pages/Librarian.test.jsx`:

1. Change the router import to `import { MemoryRouter, useLocation } from 'react-router-dom'`.
2. Replace `ROWS` and `renderPage` with the versions below.
3. In `'lists fixes with export status, links and undo'`, change the href expectation to `'/series/red-rising?book=w2'`.
4. Append the new `describe` block.

```jsx
const ROWS = [
  { id: 'c2', op: 'set_series', subject: 'Iron Gold', room_slug: 'red-rising', subject_href: '/series/red-rising?book=w2',
    reason: 'book four', user: 'ada', batch_id: null,
    created_at: new Date().toISOString(), exportable: true, runtime_only_reason: null, undoable: true, reverted_at: null },
  { id: 'c1', op: 'merge_works', subject: 'Dune', room_slug: 'dune', subject_href: '/series/dune?book=w1',
    reason: 'dup', user: 'ada', batch_id: null,
    created_at: new Date().toISOString(), exportable: false, runtime_only_reason: 'Dune has no Open Library id',
    undoable: false, reverted_at: null },
]

function Where() {
  const loc = useLocation()
  return <p data-testid="where">{`${loc.pathname}${loc.search}`}</p>
}

function renderPage(entry = '/librarian') {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[entry]}><Where /><Librarian /></MemoryRouter>
    </QueryClientProvider>,
  )
}
```

```jsx
const BATCH = '0b0b0b0b-0000-4000-8000-000000000001'
const asLibrarian = () => useAuthStore.setState({ token: 't', user: { id: 'u', username: 'ada', is_librarian: true } })

describe('Librarian log filters and batches', () => {
  it('reads its filters from the URL and ignores values the API would refuse', async () => {
    asLibrarian()
    renderPage('/librarian?op=set_series&user=ada&q=gold&batch_id=not-a-uuid&runtime_only=1')
    await screen.findByRole('link', { name: 'Iron Gold' })
    expect(client.get).toHaveBeenLastCalledWith('/librarian/corrections', {
      params: { runtime_only: true, op: 'set_series', user: 'ada', q: 'gold' },
    })
    expect(screen.getByLabelText('Op')).toHaveValue('set_series')
  })

  it('writes filters to the URL and clears them', async () => {
    asLibrarian()
    renderPage('/librarian?tab=fixes')
    await screen.findByRole('link', { name: 'Iron Gold' })
    await userEvent.selectOptions(screen.getByLabelText('Op'), 'merge_works')
    expect(screen.getByTestId('where')).toHaveTextContent('/librarian?tab=fixes&op=merge_works')
    await userEvent.type(screen.getByLabelText('Who'), 'ada')
    await userEvent.type(screen.getByLabelText('Text'), 'dup{Enter}')
    expect(screen.getByTestId('where')).toHaveTextContent('/librarian?tab=fixes&op=merge_works&user=ada&q=dup')
    expect(client.get).toHaveBeenLastCalledWith('/librarian/corrections', { params: { op: 'merge_works', user: 'ada', q: 'dup' } })
    await userEvent.click(screen.getByRole('button', { name: 'clear filters' }))
    expect(screen.getByTestId('where').textContent).toBe('/librarian?tab=fixes')
  })

  it('filters by a person from their name in the table', async () => {
    asLibrarian()
    renderPage()
    await screen.findByRole('link', { name: 'Iron Gold' })
    await userEvent.click(screen.getAllByRole('button', { name: 'only fixes by ada' })[0])
    expect(screen.getByTestId('where')).toHaveTextContent('/librarian?user=ada')
  })

  it('folds a batch into one row that expands, filters and undoes as one', async () => {
    asLibrarian()
    const members = [
      { ...ROWS[0], id: 'c4', batch_id: BATCH, subject: 'Golden Son', subject_href: '/series/red-rising?book=w4', reason: 'renumber' },
      { ...ROWS[0], id: 'c3', batch_id: BATCH, subject: 'Red Rising', subject_href: '/series/red-rising?book=w3', reason: 'renumber' },
    ]
    client.get.mockResolvedValue({ data: [...members, ROWS[1]] })
    client.post.mockResolvedValue({ data: { batch_id: BATCH, corrections: [] } })
    renderPage()
    const toggle = await screen.findByRole('button', { name: 'batch · 2 fixes' })
    expect(toggle).toHaveAttribute('aria-expanded', 'false')
    expect(screen.getByText('+ 1 more')).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Red Rising' })).toBeNull()
    expect(screen.getByRole('link', { name: 'Dune' })).toBeInTheDocument()

    await userEvent.click(toggle)
    expect(toggle).toHaveAttribute('aria-expanded', 'true')
    expect(screen.getByRole('link', { name: 'Red Rising' })).toHaveAttribute('href', '/series/red-rising?book=w3')

    await userEvent.click(screen.getByRole('button', { name: 'undo batch of 2 fixes' }))
    expect(client.post).toHaveBeenCalledWith(`/librarian/batches/${BATCH}/revert`)

    await userEvent.click(screen.getByRole('button', { name: 'only this batch' }))
    expect(screen.getByTestId('where')).toHaveTextContent(`/librarian?batch_id=${BATCH}`)
    // One batch is the whole view now: its members are plain rows.
    expect(await screen.findByRole('link', { name: 'Red Rising' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'batch · 2 fixes' })).toBeNull()
  })

  it('says when the filters match nothing', async () => {
    asLibrarian()
    client.get.mockResolvedValue({ data: [] })
    renderPage('/librarian?user=nobody')
    expect(await screen.findByText('No fixes match these filters.')).toBeInTheDocument()
  })
})
```

- [ ] **Step 2: Run them to verify they fail**

Run: `npx vitest run src/pages/Librarian.test.jsx`
Expected: the new tests fail (for example, `Unable to find a label with the text of: Op`). The href test fails because the link still points at `/series/red-rising`.

- [ ] **Step 3: Rewrite the `Log` component**

Replace everything in `frontend/src/pages/Librarian.jsx` above `function Librarian()` with the code below. Keep `Librarian` and the default export. If 13 has already made the page tabbed, the tab wrapper stays as it is, and this `Log` is still the `fixes` tab body. `withFilters` keeps `tab`.

```jsx
import { useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { useCorrections, useRevertBatch, useRevertCorrection } from '../api/librarian'
import { errorMessage } from '../api/errors'
import DataTable from '../components/DataTable'
import DiagnosticFloat from '../components/DiagnosticFloat'
import PathHeader from '../components/PathHeader'
import { relativeTime } from '../components/Post'
import { EMPTY_FILTERS, OPS, filtersFromParams, groupBatches, hasFilters, withFilters } from '../components/librarian/fixLog'
import { useStatusBar } from '../store/status'
import useAuthStore from '../store/auth'
import NotFound from './NotFound'

const fixes = (n) => `${n} ${n === 1 ? 'fix' : 'fixes'}`

/** Op applies at once; who and text apply on Enter or `filter`, so typing never refetches. */
function FilterBar({ filters, onApply }) {
  const [draft, setDraft] = useState(filters)
  const set = (key) => (e) => setDraft({ ...draft, [key]: e.target.value })
  return (
    <form role="search" aria-label="Filter fixes" className="flex flex-wrap items-end gap-3"
          onSubmit={(e) => { e.preventDefault(); onApply(draft) }}>
      <div>
        <label className="label" htmlFor="log-op">Op</label>
        <select id="log-op" className="input" value={draft.op} onChange={(e) => onApply({ ...draft, op: e.target.value })}>
          <option value="">all</option>
          {OPS.map((op) => <option key={op} value={op}>{op}</option>)}
        </select>
      </div>
      <div>
        <label className="label" htmlFor="log-user">Who</label>
        <input id="log-user" className="input" value={draft.user} onChange={set('user')} />
      </div>
      <div className="grow">
        <label className="label" htmlFor="log-q">Text</label>
        <input id="log-q" type="search" className="input" value={draft.q} onChange={set('q')} />
      </div>
      <button type="submit" className="btn-secondary text-xs">filter</button>
    </form>
  )
}

/** The log of catalog fixes: what, why, who, whether it exports, and undo. */
function Log() {
  const [searchParams, setSearchParams] = useSearchParams()
  const filters = filtersFromParams(searchParams)
  const apply = (next) => setSearchParams(withFilters(searchParams, next))
  const { data: rows = [], isLoading } = useCorrections(filters)
  const revert = useRevertCorrection()
  const revertBatch = useRevertBatch()
  const [open, setOpen] = useState(() => new Set())
  const toggle = (id) => setOpen((prev) => {
    const next = new Set(prev)
    if (next.has(id)) next.delete(id)
    else next.add(id)
    return next
  })
  useStatusBar({ mode: 'LIBRARIAN', path: '~/librarian', facts: [fixes(rows.length)] })

  // Filtered to one batch, the batch is the whole view: no folding.
  const entries = filters.batchId ? rows.map((row) => ({ kind: 'fix', row })) : groupBatches(rows)
  const tableRows = entries.flatMap((e) => (e.kind === 'fix' ? [e.row] : [
    { id: `batch-${e.batchId}`, group: e },
    ...(open.has(e.batchId) ? e.rows.map((r, i) => ({ ...r, elbow: i === e.rows.length - 1 ? '└─' : '├─' })) : []),
  ]))
  const head = (r) => r.group?.rows[0] ?? r

  const subject = (r) => (
    <span className="inline-flex gap-1">
      {r.elbow && <span aria-hidden="true" className="text-ink-faint">{r.elbow}</span>}
      {r.subject_href
        ? <Link to={r.subject_href} className="font-serif text-ink hover:text-accent">{r.subject}</Link>
        : <span className="font-serif text-ink-dim">{r.subject}</span>}
    </span>
  )
  const exported = (r) => (r.exportable
    ? <span className="text-ok">exported</span>
    : <DiagnosticFloat severity="warn" message={r.runtime_only_reason}><span className="text-warning">runtime-only</span></DiagnosticFloat>)
  const undo = (r) => (r.reverted_at ? <span className="text-ink-dim">undone</span> : r.undoable && (
    <button type="button" className="btn-ghost text-xs" aria-label={`undo ${r.subject}`}
            disabled={revert.isPending} onClick={() => revert.mutate(r.id)}>undo</button>
  ))

  const columns = [
    { key: 'created_at', label: 'Age', align: 'right', width: 6,
      render: (r) => <span className="text-ink-dim tabular-nums">{relativeTime(head(r).created_at)}</span> },
    { key: 'op', label: 'Op', width: 18,
      render: (r) => (r.group
        ? <button type="button" className="btn-ghost text-xs" aria-expanded={open.has(r.group.batchId)}
                  onClick={() => toggle(r.group.batchId)}>batch · {fixes(r.group.rows.length)}</button>
        : <span className="text-ink-dim">{r.op}</span>) },
    { key: 'subject', label: 'Subject',
      render: (r) => (r.group ? (
        <span className="flex flex-col items-start gap-1">
          <span>
            <span className="font-serif text-ink">{r.group.rows[0].subject}</span>
            {r.group.rows.length > 1 && <span className="text-ink-dim"> + {r.group.rows.length - 1} more</span>}
          </span>
          <button type="button" className="btn-ghost text-xs" onClick={() => apply({ ...filters, batchId: r.group.batchId })}>
            only this batch
          </button>
        </span>
      ) : subject(r)) },
    { key: 'reason', label: 'Why', render: (r) => <span className="text-ink">{head(r).reason}</span> },
    { key: 'user', label: 'By', width: 12,
      render: (r) => (
        <button type="button" className="text-user hover:text-accent" aria-label={`only fixes by ${head(r).user}`}
                onClick={() => apply({ ...filters, user: head(r).user })}>{head(r).user}</button>
      ) },
    { key: 'export', label: 'Export', width: 14,
      render: (r) => {
        if (!r.group) return exported(r)
        const runtime = r.group.rows.filter((x) => !x.exportable).length
        return runtime ? <span className="text-warning">{runtime} runtime-only</span> : <span className="text-ok">exported</span>
      } },
    { key: 'undo', label: '', width: 6,
      render: (r) => {
        if (!r.group) return undo(r)
        // The server decides; a batch straddling pages may have members not shown here.
        if (r.group.rows.every((x) => x.reverted_at)) return <span className="text-ink-dim">undone</span>
        return (
          <button type="button" className="btn-ghost text-xs" aria-label={`undo batch of ${fixes(r.group.rows.length)}`}
                  disabled={revertBatch.isPending} onClick={() => revertBatch.mutate(r.group.batchId)}>undo</button>
        )
      } },
  ]

  const failed = revert.isError ? revert.error : revertBatch.isError ? revertBatch.error : null
  return (
    <main className="max-w-shell mx-auto px-4 py-6 flex flex-col gap-6">
      <PathHeader segments={[{ label: 'librarian' }]} />
      <div className="flex items-center justify-between">
        <h1 className="text-sm uppercase tracking-eyebrow text-ink">Catalog fixes</h1>
        <button type="button" aria-pressed={filters.runtimeOnly}
                onClick={() => apply({ ...filters, runtimeOnly: !filters.runtimeOnly })}
                className={`text-xs ${filters.runtimeOnly ? 'text-accent underline underline-offset-4' : 'text-ink-dim hover:text-accent'}`}>
          runtime-only only
        </button>
      </div>
      {/* Keyed by the URL: back/forward or a clear resets what the fields show. */}
      <FilterBar key={searchParams.toString()} filters={filters} onApply={apply} />
      {hasFilters(filters) && (
        <p className="flex flex-wrap items-center gap-3 text-xs">
          {filters.batchId && <span className="text-ink-dim">batch {filters.batchId.slice(0, 8)}</span>}
          <button type="button" className="btn-ghost text-xs" onClick={() => apply(EMPTY_FILTERS)}>clear filters</button>
        </p>
      )}
      {failed && <p className="alert-danger text-xs">{errorMessage(failed)}</p>}
      {isLoading
        ? <div className="h-8 border border-line bg-panel animate-pulse" />
        : <DataTable columns={columns} rows={tableRows} caption="Catalog fixes"
                     emptyMessage={hasFilters(filters) ? 'No fixes match these filters.' : 'No fixes yet.'} />}
    </main>
  )
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `npx vitest run src/pages/Librarian.test.jsx src/components/librarian/fixLog.test.js`
Expected: all pass.

- [ ] **Step 5: §36 check, then commit**

Run `npm run dev` with the stack up and open `/librarian` as a librarian. The filter bar must read as one prompt-like row of `.input`s over an `ls -l` table, not as a SaaS filter sidebar. There must be no coloured pills, and the batch row must be a table row with a word toggle. Fix anything that fails, then:

```bash
git add frontend/src/pages/Librarian.jsx frontend/src/pages/Librarian.test.jsx
git commit -m "feat(web): fix log filters in the URL, subject links, batch rows"
```

---

### Task 6: `history` on each book in edit mode

**Files:**
- Create: `frontend/src/components/librarian/HistoryFloat.jsx`
- Create: `frontend/src/components/librarian/HistoryFloat.test.jsx`
- Modify: `frontend/src/pages/Series.jsx` (`BookRow`, `Series`)
- Test: `frontend/src/pages/Series.test.jsx`

**Interfaces:**
- Consumes: `useCorrections({ workId, limit })` (Task 4), `useRevertCorrection()`, and `errorMessage()`.
- Produces: `<HistoryFloat work={{ id, title }} onClose={() => …} />`, a `section` named `History of <title>` with the `.float` class. It focuses itself on mount and closes on Escape. It lists up to `HISTORY_LIMIT` (20) fixes newest first, each with `undo <op>, <reason>` or `undone`. The `BookRow` gets props `historyOpen: boolean` and `onHistory(open: boolean)`, and an edit-mode button `history <title>` with `aria-expanded`. Only one book's history is open at a time.

- [ ] **Step 1: Write the failing component tests**

`frontend/src/components/librarian/HistoryFloat.test.jsx`:

```jsx
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

vi.mock('../../api/client', () => ({ default: { get: vi.fn(), post: vi.fn() } }))

import client from '../../api/client'
import HistoryFloat from './HistoryFloat'

const WORK = { id: 'w1', title: 'Red Rising' }
const FIXES = [
  { id: 'c2', op: 'set_position', reason: 'book one', user: 'ada', created_at: new Date().toISOString(),
    undoable: true, reverted_at: null },
  { id: 'c1', op: 'set_series', reason: 'trilogy', user: 'bo', created_at: new Date().toISOString(),
    undoable: false, reverted_at: '2026-09-28T00:00:00Z' },
]

function renderFloat(onClose = vi.fn()) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(<QueryClientProvider client={qc}><HistoryFloat work={WORK} onClose={onClose} /></QueryClientProvider>)
  return onClose
}

beforeEach(() => {
  vi.clearAllMocks()
  client.get.mockResolvedValue({ data: FIXES })
})

describe('HistoryFloat', () => {
  it("lists the book's fixes, newest first, with undo where it is allowed", async () => {
    renderFloat()
    const region = screen.getByRole('region', { name: 'History of Red Rising' })
    expect(region).toHaveFocus()
    expect(client.get).toHaveBeenCalledWith('/librarian/corrections', { params: { work_id: 'w1', limit: 20 } })
    const items = await within(region).findAllByRole('listitem')
    expect(items[0]).toHaveTextContent('set_position')
    expect(items[0]).toHaveTextContent('book one')
    expect(within(items[1]).getByText('undone')).toBeInTheDocument()
    client.post.mockResolvedValue({ data: { ...FIXES[0], undoable: false, reverted_at: new Date().toISOString() } })
    await userEvent.click(within(region).getByRole('button', { name: 'undo set_position, book one' }))
    expect(client.post).toHaveBeenCalledWith('/librarian/corrections/c2/revert')
  })

  it('says why an undo was refused', async () => {
    client.post.mockRejectedValue({ response: { status: 409, data: { detail: 'A later fix came after this one; undo that first.' } } })
    renderFloat()
    await userEvent.click(await screen.findByRole('button', { name: 'undo set_position, book one' }))
    expect(await screen.findByText(/undo that first/)).toBeInTheDocument()
  })

  it('says so when the book has no fixes', async () => {
    client.get.mockResolvedValue({ data: [] })
    renderFloat()
    expect(await screen.findByText('No fixes to this book yet.')).toBeInTheDocument()
  })

  it('closes on Escape and on close', async () => {
    const onClose = renderFloat()
    await screen.findAllByRole('listitem')
    await userEvent.keyboard('{Escape}')
    await userEvent.click(screen.getByRole('button', { name: 'close history' }))
    expect(onClose).toHaveBeenCalledTimes(2)
  })
})
```

Append to `frontend/src/pages/Series.test.jsx` (inside the existing `describe`), and add to the reader test `'offers edit mode only to librarians'` the line `expect(screen.queryByRole('button', { name: /^history/ })).toBeNull()`:

```jsx
  it("opens a book's history in edit mode, one at a time, and returns focus when it closes", async () => {
    useAuthStore.setState({ token: 't', user: { id: 'u1', username: 'lib', is_librarian: true } })
    client.get.mockImplementation((url) => {
      if (url.endsWith('/threads')) return Promise.resolve({ data: [] })
      if (url === '/librarian/corrections') {
        return Promise.resolve({ data: [{ id: 'c1', op: 'set_position', reason: 'book one', user: 'ada',
          created_at: new Date().toISOString(), undoable: true, reverted_at: null }] })
      }
      return Promise.resolve({ data: { ...SAGA, id: 's1' } })
    })
    renderPage('/series/red-rising?edit=1')
    const list = await screen.findByRole('list', { name: 'Books in this series' })
    const button = within(list).getByRole('button', { name: 'history Red Rising' })
    expect(button).toHaveAttribute('aria-expanded', 'false')
    await userEvent.click(button)
    const region = await screen.findByRole('region', { name: 'History of Red Rising' })
    expect(await within(region).findByText('book one')).toBeInTheDocument()
    expect(client.get).toHaveBeenCalledWith('/librarian/corrections', { params: { work_id: 'b1', limit: 20 } })

    await userEvent.click(within(list).getByRole('button', { name: 'history Golden Son' }))
    expect(screen.queryByRole('region', { name: 'History of Red Rising' })).toBeNull()
    expect(await screen.findByRole('region', { name: 'History of Golden Son' })).toBeInTheDocument()

    await userEvent.keyboard('{Escape}')
    expect(screen.queryByRole('region', { name: 'History of Golden Son' })).toBeNull()
    expect(within(list).getByRole('button', { name: 'history Golden Son' })).toHaveFocus()
  })
```

- [ ] **Step 2: Run them to verify they fail**

Run: `npx vitest run src/components/librarian/HistoryFloat.test.jsx src/pages/Series.test.jsx`
Expected: FAIL. The component test cannot resolve `./HistoryFloat`, and the Series test finds no button named `history Red Rising`.

- [ ] **Step 3: Write `HistoryFloat.jsx`**

```jsx
import { useEffect, useRef } from 'react'
import { useCorrections, useRevertCorrection } from '../../api/librarian'
import { errorMessage } from '../../api/errors'
import { relativeTime } from '../Post'

export const HISTORY_LIMIT = 20

/**
 * One book's fixes, newest first, under its row in edit mode. Undo is the
 * log's undo: the server decides; a refusal is shown here.
 */
function HistoryFloat({ work, onClose }) {
  const { data: rows = [], isLoading } = useCorrections({ workId: work.id, limit: HISTORY_LIMIT })
  const revert = useRevertCorrection()
  const ref = useRef(null)
  useEffect(() => { ref.current?.focus() }, [])

  return (
    <section
      ref={ref}
      tabIndex={-1}
      aria-label={`History of ${work.title}`}
      onKeyDown={(e) => { if (e.key === 'Escape') { e.stopPropagation(); onClose() } }}
      className="float flex flex-col gap-2 max-w-prose"
    >
      <div className="flex items-center justify-between gap-3">
        <h4 className="uppercase tracking-eyebrow text-ink-dim">history</h4>
        <button type="button" className="btn-ghost text-xs" aria-label="close history" onClick={onClose}>close</button>
      </div>
      {isLoading ? (
        <div className="h-4 bg-highlight animate-pulse" />
      ) : rows.length === 0 ? (
        <p className="text-ink-dim">No fixes to this book yet.</p>
      ) : (
        <ul className="flex flex-col gap-1">
          {rows.map((r) => (
            <li key={r.id} className="flex flex-wrap items-baseline gap-x-3">
              <span className="text-ink-dim tabular-nums">{relativeTime(r.created_at)}</span>
              <span className="text-ink-dim">{r.op}</span>
              <span className="text-ink">{r.reason}</span>
              <span className="text-user">{r.user}</span>
              {r.reverted_at ? <span className="text-ink-dim">undone</span> : r.undoable && (
                <button type="button" className="btn-ghost text-xs" disabled={revert.isPending}
                        aria-label={`undo ${r.op}, ${r.reason}`} onClick={() => revert.mutate(r.id)}>undo</button>
              )}
            </li>
          ))}
        </ul>
      )}
      {rows.length === HISTORY_LIMIT && <p className="text-ink-dim">latest {HISTORY_LIMIT} shown</p>}
      {revert.isError && <p className="alert-danger">{errorMessage(revert.error)}</p>}
    </section>
  )
}

export default HistoryFloat
```

- [ ] **Step 4: Wire it into `Series.jsx`**

1. Add the import: `import HistoryFloat from '../components/librarian/HistoryFloat'`.
2. Change the `BookRow` signature to `function BookRow({ work, current, rowRef, editing, isSeries, onAction, historyOpen, onHistory })`. Keep any props other items added. As its first line after the `useState`, add:

```jsx
  const historyButton = useRef(null)
  const closeHistory = () => { onHistory(false); historyButton.current?.focus() }
```

3. Inside the edit-mode action bar (`<div className="flex flex-wrap gap-x-3 text-xs" aria-label={`Fix ${work.title}`}>`), add after the mapped buttons:

```jsx
            <button ref={historyButton} type="button" className="btn-ghost text-xs" aria-expanded={historyOpen}
                    aria-label={`history ${work.title}`} onClick={() => onHistory(!historyOpen)}>
              history
            </button>
```

4. Directly after that action bar's closing `</div>`, and still inside the `{editing && (...)}` region's parent column, add:

```jsx
        {editing && historyOpen && <HistoryFloat work={work} onClose={closeHistory} />}
```

5. In `Series`, next to the `action` state, add `const [historyFor, setHistoryFor] = useState(null) // a work id`. Pass these props where `BookRow` is rendered:

```jsx
              historyOpen={historyFor === work.id}
              onHistory={(open) => setHistoryFor(open ? work.id : null)}
```

`useRef` is already imported in `Series.jsx`.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `npx vitest run src/components/librarian/HistoryFloat.test.jsx src/pages/Series.test.jsx`
Expected: all pass. The existing test that loops over row actions is unaffected, because it only checks for the names it lists.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/librarian/HistoryFloat.jsx frontend/src/components/librarian/HistoryFloat.test.jsx frontend/src/pages/Series.jsx frontend/src/pages/Series.test.jsx
git commit -m "feat(web): per-book history float with undo in edit mode"
```

---

### Task 7: End to end: find a fix in the log, follow it, undo from history

**Files:**
- Modify: `frontend/e2e/librarian.spec.js` (append one test)

**Interfaces:**
- Consumes: `registerViaUi`, `grantLibrarian`, `openFirstSearchResult` from `e2e/helpers.js`, plus the whole stack.

- [ ] **Step 1: Write the scenario**

Append to `frontend/e2e/librarian.spec.js`:

```js
// Item 11: a librarian moves a book, reorders it, undoes the reorder from the
// book's history, then finds both fixes in the filtered log and follows one home.
test('a librarian undoes a fix from a book history and finds it in the filtered log', async ({ page }) => {
  const user = await registerViaUi(page)
  grantLibrarian(user)
  await page.reload()

  await openFirstSearchResult(page, 'the dispossessed')
  const url = new URL(page.url())
  url.searchParams.set('edit', '1') // works with or without sticky edit mode (item 01)
  await page.goto(url.toString())
  const books = page.getByRole('list', { name: 'Books in this series' })
  const title = await books.getByRole('heading').first().textContent()

  await books.getByRole('button', { name: `move ${title}`, exact: true }).click()
  const saga = `E2E Log ${Date.now()}`
  await page.getByLabel('Find a series').fill(saga)
  await page.getByRole('radio', { name: `new series: ${saga}` }).check()
  await page.getByLabel('Reason', { exact: true }).fill('e2e: log move')
  await page.getByRole('button', { name: 'Move', exact: true }).click()
  const status = page.getByRole('group', { name: 'Librarian fix result' })
  const follow = status.getByRole('link', { name: /go to its page/ })
  const heading = page.getByRole('heading', { level: 1, name: saga })
  await expect(async () => {
    if (await follow.isVisible()) await follow.click({ timeout: 1000 }).catch(() => {})
    await expect(heading).toBeVisible({ timeout: 1000 })
  }).toPass()

  await books.getByRole('button', { name: `position ${title}`, exact: true }).click()
  await page.getByLabel('Position (blank clears)').fill('1')
  await page.getByLabel('Reason', { exact: true }).fill('e2e: log position')
  await page.getByRole('button', { name: 'Set position', exact: true }).click()
  await expect(status).toBeVisible()

  await books.getByRole('button', { name: `history ${title}`, exact: true }).click()
  const history = page.getByRole('region', { name: `History of ${title}` })
  await expect(history.getByText('e2e: log move')).toBeVisible()
  await history.getByRole('button', { name: 'undo set_position, e2e: log position' }).click()
  await expect(history.getByText('undone')).toBeVisible()

  await page.goto(`/librarian?user=${user.username}`)
  const log = page.getByRole('table', { name: 'Catalog fixes' })
  await expect(log.getByText('e2e: log move')).toBeVisible()
  await expect(log.getByText('e2e: log position')).toBeVisible()
  await page.getByLabel('Op').selectOption('set_series')
  await expect(page).toHaveURL(/op=set_series/)
  await expect(log.getByText('e2e: log position')).toBeHidden()
  await log.getByRole('link', { name: title }).first().click()
  await expect(page).toHaveURL(/\/series\/.+\?book=/)
  await expect(heading).toBeVisible()
})
```

- [ ] **Step 2: Run it**

With the stack up in another terminal (`docker compose up --build`), run from `frontend/`: `npm run test:e2e -- librarian.spec.js`
Expected: 2 passed (the v1 scenario and this one).

- [ ] **Step 3: Commit**

```bash
git add frontend/e2e/librarian.spec.js
git commit -m "test(e2e): fix log filters, links and per-book history"
```

---

### Task 8: Docs and tracker

**Files:**
- Modify: `docs/librarian-ux-roadmap.md`, `ROADMAP.md`, `CLAUDE.md`, `README.md`, and this plan's header checkbox

- [ ] **Step 1: Update them**

- `docs/librarian-ux-roadmap.md`, tracker row 11: set Status `✅`, Branch `feat/librarian-lx11-fix-log-history`, Done to the merge date, and PR to the PR number. Under **Notes**, add a dated line: "11 — the log is built by `services/librarian/log.py` (`find_corrections`, `corrections_out`) in a fixed number of queries; `undo.undoable_ids` is the one undo-eligibility rule (`undoable` delegates), so 16 extends it there. `work_id` now includes fixes on books merged into that work. Batch folding on `/librarian` lives in `components/librarian/fixLog.js` (`groupBatches`)."
- `ROADMAP.md`, Phase 5 table: add a row under **Librarian tools**:
  `| ✅ | **Fix log filters & per-book history** — filter /librarian by op, who, text and batch (in the URL); subjects link to their book; batches fold into one row; \`history\` on each book in edit mode lists its fixes with undo. | [plan](docs/superpowers/plans/2026-09-29-lx11-fix-log-history.md), \`services/librarian/log.py\`, \`pages/Librarian.jsx\`, \`components/librarian/{fixLog.js,HistoryFloat.jsx}\` |`
- `CLAUDE.md`, backend `librarian/` sentence: change "(`keys`, `record`, `placement`, `identity`, `undo`, `export`)" to include `log`. Append: "`log` reads the log: `find_corrections` filters (op, username, text, batch) and `corrections_out` describes a whole page in a fixed number of queries. Never build `CorrectionOut` per row. `undo.undoable_ids` is the only copy of the undo-eligibility rule."
- `README.md`, Key API routes: change `GET    /api/librarian/corrections` to `GET    /api/librarian/corrections?op&user&q&batch_id&work_id&runtime_only&limit&offset`.
- This plan's header: tick **Roadmap item**.

- [ ] **Step 2: Verify everything, then commit**

Run `PYTEST -q -p no:warnings`, then `cd frontend && npm test && npm run build`.
Expected: all green, and the build succeeds.

```bash
git add docs/librarian-ux-roadmap.md ROADMAP.md CLAUDE.md README.md docs/superpowers/plans/2026-09-29-lx11-fix-log-history.md
git commit -m "docs: fix log filters, links and per-book history (lx11)"
```

---

## Self-review

- **Spec coverage (§11 and shared names):** the filters `op`/`user`/`q`/`batch_id` are Task 3, with URL state in Tasks 4–5. `subject_href` is Task 2, and subjects link in Task 5. Batch rows are grouped in Tasks 4–5, using 08's `batch_id` and group revert. The `history` float with undo is Task 6. Pagination is kept (Task 3 `test_filters_combine_and_paginate`), and the N+1 is removed (Task 2). The roadmap and docs are Task 8.
- **Placeholders:** none. The two execution-time checks (08's changes to `undoable`, and whether items 06/07 added ops) name the exact command and the exact edit.
- **Type consistency:** `undoable_ids(db, rows) -> set[UUID]` is defined in Task 1 and used in Task 2. `corrections_out(db, rows)` is defined in Task 2 and used in Task 3. `find_corrections(..., username=...)` is fed from the route's `user` param. The Filters keys `op/user/q/batchId/runtimeOnly` are the same in `fixLog.js`, `useCorrections` and `Librarian.jsx`. The `HISTORY_LIMIT` of 20 matches both tests' `limit: 20`.
- **Review Focus:** each of the five lines names the test that pins it.
