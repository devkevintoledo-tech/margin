# Batch Actions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** In edit mode a librarian checks several books on a series page and applies one fix to all of them under one reason: `move selected…`, `remove selected…`, or `number 1…n`. The server applies the whole batch or none of it, and the batch is undone as one. Grouping a batch into one expandable row on the fix log belongs to item 11, which consumes this item's `batch_id`, `useRevertBatch` and batch-revert route.

**Architecture:** `catalog_corrections` gains `batch_id uuid null, indexed`. A new `services/librarian/batch.py` runs the **unchanged** v1 ops (`set_series`, `set_position`, `remove_from_series`) inside one savepoint and stamps each correction with the batch id. `revert_batch` runs the v1 undo per member, newest first, in one savepoint. The v1 single undo refuses a batch member, so a batch can never end half-undone. `api/librarian.py` gets `POST /librarian/batch` and `POST /librarian/batches/{batch_id}/revert`. The series page gets row checkboxes, an action bar, a `BatchPanel` float and a batch result line. On `/librarian` this item only stops offering a single undo on a batch member (a one-line guard). Item 11 owns the grouped batch row.

**Tech Stack:** FastAPI, async SQLAlchemy 2.0 (savepoints via `begin_nested`), Alembic, Pydantic v2 discriminated unions, React 18 + React Query 5, Tailwind tokens, Vitest + RTL, Playwright.

**Spec:** docs/librarian-ux-roadmap.md §08 · Batch actions (and "Shared names → Backend → Batch")

**Roadmap item:** 08 — tick in docs/librarian-ux-roadmap.md when merged

- [ ] **Merged** (PR: ___)

## Global Constraints

- Binding shared names (roadmap): `catalog_corrections.batch_id uuid null, indexed`. `POST /api/librarian/batch {reason, actions: [BatchAction]}` → `BatchOut {batch_id, corrections: [CorrectionOut]}`. `BatchAction` is a discriminated union on `kind` ∈ `move | position | remove`, with the same fields as the single routes. All-or-nothing, in one transaction. `POST /api/librarian/batches/{batch_id}/revert` undoes every member, newest first, all-or-nothing. `CorrectionOut` gains `batch_id`. `ReasonField` (item 02) is used by every panel that asks for a reason.
- Scope boundary with item 11 (coordination, 2026-09-29): the fix log's batch grouping UI is item 11's. This item provides `useRevertBatch()` in `frontend/src/api/librarian.js` for it. It must not add a second copy of the undo rule: per-member checks go through the v1 revert path (`revert_one`), and `CorrectionOut.undoable` still comes from `undo.undoable`, which item 11 later reroutes through `undo.undoable_ids`.
- Repo rules in `CLAUDE.md` apply verbatim. `api/` stays thin. `services/librarian/` is the only writer of `catalog_corrections`. Everything is async. Schemas are built explicitly (never `model_validate` of an ORM object). Frontend: tokens only, serif only for book titles and series names, no new radii/shadows/sizes/durations, `aria-hidden` on every glyph, §36 test.
- **Migration:** autogenerate at execution time, with `down_revision` = the head *then*. Never hardcode a revision id. No enum value is added by this item.
- **Every write is a correction.** Each batch member is an ordinary v1 correction (same op, same override/`runtime_only_reason` rules, same snapshot) with the batch's one cleaned reason. A batch writes nothing else.
- Every librarian route depends on `require_librarian`. The test module asserts 401 anonymous / 403 reader for both new routes.
- A batch names each book at most once (422 otherwise), holds 1–500 actions (422 otherwise), and needs a non-empty reason (422).
- Backend tests: **`PYTEST`** = `docker compose run --rm --no-deps -v "$PWD/pipeline:/pipeline:ro" -e DATABASE_URL=postgresql+asyncpg://margin:margin@db:5432/margin_test backend pytest` (from the repo root, with `docker compose up -d db` running and `margin_test` created once per CLAUDE.md).
- Frontend unit tests: `cd frontend && npx vitest run <files>`. Network is always mocked.
- One branch, `feat/librarian-lx08-batch-actions`, from `main`. Commit per task. PR to `main`.

## Decisions this plan adds to the roadmap

1. **Undo inside a batch.** Members of one batch name distinct books, so each member's v1 rule ("latest unreverted fix on its subject, catalog unchanged since") is independent of its siblings. The batch is undoable exactly when every member passes that rule. Reverting newest first replays the batch backwards. That order is load-bearing: when a batch moves every book out of a room, the *last* move retires the room, and only undoing that move first brings the room back before the earlier moves' undo looks for it (Task 3 test).
2. **A batch member cannot be undone alone.** `POST /corrections/{id}/revert` on a member answers 422 "This fix is part of a batch; undo the batch." `CorrectionOut.undoable` keeps its v1 meaning for a member (it would pass the latest-and-unchanged check), so a client shows *one* batch undo when every member is `undoable`. The series page never offers a per-member undo, and the fix log stops offering one (Task 8; item 11 then adds the group undo there). A later single fix on a member, or a later batch touching one of its books, blocks the whole batch until that later fix is undone. That is the v1 "undo the later fix first" rule applied to the group.
3. **Atomicity is a savepoint.** `apply_batch` and `revert_batch` run inside `db.begin_nested()`. In production the request transaction (`get_db`) would roll back anyway. The savepoint also makes "all or nothing" true where one session outlives a failed call (the test client pins one session), and it is what the tests assert.
4. **Books are locked up front in id order** (`SELECT … FOR UPDATE ORDER BY id`) before any op runs. Two concurrent batches over overlapping books then queue instead of deadlocking.
5. **A refusal names the book.** The first refused action raises the v1 error with its message prefixed by the book's title (or `Fix <n>` when the id is unknown). Status and shape are unchanged: 404/409/422 with a string `detail`.
6. **`revert_batch` answers `BatchOut`** (the roadmap does not fix its response). Corrections are listed newest first.
7. **`number 1…n` numbers per sub-series group.** A book's position lives in the deepest series that holds it (v1 `set_position`), so the checked books are numbered 1…k within each group in page order. Books whose position already equals their new number get no action. Item 09 reuses the same helpers.

## Review Focus

1. **A batch that moves every book out of its room.** The last move retires the room. Undoing the batch must bring it back and return every book (Task 3, `test_undoing_a_batch_goes_newest_first_so_an_emptied_room_comes_back`).
2. **A later single fix on one member.** Undoing the batch must refuse and leave *every* member applied, not undo the others (Task 3, `test_a_batch_undo_is_all_or_nothing`).
3. **One refused action midway.** For example, a book merged away in another tab. Nothing from the batch may remain: no membership change, no correction (Task 2, `test_one_refused_fix_leaves_nothing_behind`).
4. **Two librarians batching the same books at once.** The second waits on the first's locks and then applies against the new state, with no deadlock (Task 2, `test_two_batches_over_the_same_books_wait_instead_of_deadlocking`).
5. **A stale selection.** A checked book is fixed away by a single action and leaves the room. The selection must drop it rather than send an action the server refuses (Task 7, `drops a selected book once it has left the room`).

---

## File Structure

**Backend — create**
- `backend/alembic/versions/<autogenerated>_correction_batch_id.py`: adds `batch_id` and its index.
- `backend/app/services/librarian/batch.py`: `apply_batch`, `revert_batch`.
- `backend/tests/test_librarian_batch.py`: service and route tests for batches.

**Backend — modify**
- `backend/app/models/correction.py`: `batch_id` column.
- `backend/app/schemas/librarian.py`: `MoveAction`, `PositionAction`, `RemoveAction`, `BatchAction`, `BatchIn`, `BatchOut`; `CorrectionOut.batch_id`.
- `backend/app/services/librarian/undo.py`: `revert` refuses a member; the old body becomes `revert_one`.
- `backend/app/services/librarian/__init__.py`: re-export `apply_batch`, `revert_batch`.
- `backend/app/api/librarian.py`: two routes; `correction_out` fills `batch_id`.
- `backend/tests/test_librarian_api.py`: the new routes join `WRITES`; a single fix has no batch.

**Frontend — create**
- `frontend/src/components/librarian/batch.js`: `groupKey`, `renumber`, `positionActions` (pure).
- `frontend/src/components/librarian/batch.test.js`
- `frontend/src/components/librarian/useDialogFocus.js`: focus-in, Tab trap, Escape, focus-return for a float.
- `frontend/src/components/librarian/BatchPanel.jsx` (+ `BatchPanel.test.jsx`): the batch float.
- `frontend/src/components/librarian/BatchBar.jsx`: the selection toolbar.
- `frontend/src/components/librarian/BatchResultLine.jsx`: a batch's outcome and its undo.

**Frontend — modify**
- `frontend/src/api/librarian.js`: `useLibrarianBatch`, `useRevertBatch`.
- `frontend/src/pages/Series.jsx` (+ test): checkboxes, bar, panel, result line.
- `frontend/src/pages/Librarian.jsx` (+ test): no single undo on a batch member (grouping is item 11).
- `frontend/e2e/helpers.js`, `frontend/e2e/librarian.spec.js`.

**Docs — modify:** `docs/librarian-ux-roadmap.md`, `ROADMAP.md`, `CLAUDE.md`.

---

### Task 1: `batch_id` on corrections, and in `CorrectionOut`

**Files:**
- Modify: `backend/app/models/correction.py`
- Create: `backend/alembic/versions/<autogenerated>_correction_batch_id.py`
- Modify: `backend/app/schemas/librarian.py` (`CorrectionOut`)
- Modify: `backend/app/api/librarian.py` (`correction_out`)
- Test: `backend/tests/test_librarian_api.py`

**Interfaces:**
- Produces: `CatalogCorrection.batch_id: uuid.UUID | None` (indexed, `ix_catalog_corrections_batch_id`), and `CorrectionOut.batch_id: UUID | None = None`, filled by `correction_out`.

- [ ] **Step 1: Branch and mark the item started**

```bash
git checkout main && git pull
git checkout -b feat/librarian-lx08-batch-actions
```

In `docs/librarian-ux-roadmap.md`, set tracker row 08 to status `🟡` and Branch `feat/librarian-lx08-batch-actions`.

- [ ] **Step 2: Write the failing test**

Append to `backend/tests/test_librarian_api.py`:

```python
async def test_a_single_fix_belongs_to_no_batch(client, db_session):
    lib = headers_for(await make_user(db_session, librarian=True))
    book = await make_work(db_session, "Solo", ol_id="OL60W")
    resp = await client.post(f"/api/librarian/works/{book.id}/move",
                             json={"new_series_name": "Solo Saga", "reason": "r"}, headers=lib)
    assert resp.status_code == 201, resp.text
    assert resp.json()["batch_id"] is None
    rows = (await client.get("/api/librarian/corrections", headers=lib)).json()
    assert rows[0]["batch_id"] is None
```

- [ ] **Step 3: Run it to make sure it fails**

Run: `PYTEST tests/test_librarian_api.py::test_a_single_fix_belongs_to_no_batch -q`
Expected: FAIL with `KeyError: 'batch_id'`.

- [ ] **Step 4: Add the column, the schema field and the output**

In `backend/app/models/correction.py`, add after the `user_id` column:

```python
    # Set on every member of one batch (roadmap 08); null for a single fix.
    batch_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True, index=True)
```

In `backend/app/schemas/librarian.py`, in `CorrectionOut`, add after `subject`:

```python
    batch_id: UUID | None = None  # the batch this fix was made in, if any; undone only with it
```

In `backend/app/api/librarian.py`, in `correction_out`, change the `CorrectionOut(` call's last line from:

```python
        reverted_at=c.reverted_at, room_slug=room_slug, subject=subject,
    )
```

to:

```python
        reverted_at=c.reverted_at, room_slug=room_slug, subject=subject, batch_id=c.batch_id,
    )
```

- [ ] **Step 5: Run the test**

Run: `PYTEST tests/test_librarian_api.py -q`
Expected: PASS (every test in the module, the new one included).

- [ ] **Step 6: Autogenerate the migration and review it**

```bash
docker compose up -d db
docker compose run --rm --no-deps backend alembic upgrade head
docker compose run --rm --no-deps backend alembic revision --autogenerate -m "correction batch id"
```

Expected: a new file `backend/alembic/versions/<rev>_correction_batch_id.py` whose `down_revision` is the head at this moment. Edit it so the bodies are exactly:

```python
def upgrade() -> None:
    op.add_column("catalog_corrections", sa.Column("batch_id", sa.Uuid(), nullable=True))
    op.create_index(op.f("ix_catalog_corrections_batch_id"), "catalog_corrections", ["batch_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_catalog_corrections_batch_id"), table_name="catalog_corrections")
    op.drop_column("catalog_corrections", "batch_id")
```

Delete any other operation autogenerate emitted. It can misread the generated `works.search_doc` column, and this migration touches only `catalog_corrections`.

Run: `docker compose run --rm --no-deps backend sh -c "alembic upgrade head && alembic downgrade -1 && alembic upgrade head"`
Expected: no errors.

- [ ] **Step 7: Full backend suite and commit**

Run: `PYTEST -q -p no:warnings`
Expected: all pass.

```bash
git add backend/app/models/correction.py backend/alembic/versions/*_correction_batch_id.py \
  backend/app/schemas/librarian.py backend/app/api/librarian.py backend/tests/test_librarian_api.py \
  docs/librarian-ux-roadmap.md
git commit -m "feat(db): corrections carry a batch id, shown on every fix"
```

---

### Task 2: Batch actions and `apply_batch`

**Files:**
- Modify: `backend/app/schemas/librarian.py`
- Create: `backend/app/services/librarian/batch.py`
- Modify: `backend/app/services/librarian/__init__.py`
- Create: `backend/tests/test_librarian_batch.py`

**Interfaces:**
- Consumes: v1 `set_series(db, user, work, *, reason, series=None, new_series_name=None, position=None)`, `set_position(db, user, room, work, position, *, reason)`, `remove_from_series(db, user, room, work, *, reason)` (all in `services/librarian/placement.py`, unchanged), and `clean_reason` (`record.py`).
- Produces (schemas): `MoveAction {kind: 'move', work_id, series_id?, new_series_name?, position?}`, `PositionAction {kind: 'position', series_id, work_id, position?}`, `RemoveAction {kind: 'remove', series_id, work_id}`, `BatchAction` (their union, discriminated on `kind`), `BatchIn {reason, actions: list[BatchAction] (1..500)}`, `BatchOut {batch_id: UUID, corrections: list[CorrectionOut]}`.
- Produces (service): `apply_batch(db, user, actions, *, reason) -> tuple[uuid.UUID, list[CatalogCorrection]]` (in action order), and the private `_labelled(exc, label)` and `_lock_books(db, work_ids)` that Task 3 reuses.

- [ ] **Step 1: Write the failing tests**

`backend/tests/test_librarian_batch.py`:

```python
"""Batch fixes (roadmap 08): one reason, one transaction, one undo."""

import asyncio
import uuid

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.models import CatalogCorrection, CorrectionOp, Series, SeriesMember, User, Work
from app.schemas.librarian import MoveAction, PositionAction, RemoveAction
from app.services.librarian.batch import apply_batch
from app.services.librarian.errors import Conflict, Invalid, NotFound
from app.services.librarian.identity import merge
from tests.conftest import TEST_DB_URL
from tests.librarian_factories import fresh, make_member, make_series, make_user, make_work

R = "2026.10.1"


async def saga(db):
    """Alpha holds Book X (#1) and Book Y (#2); Beta is empty. Returns ids, since
    a rolled-back savepoint expires the ORM objects it touched."""
    lib = await make_user(db, librarian=True)
    a = await make_series(db, "Alpha", release=R)
    b = await make_series(db, "Beta", release=R)
    x = await make_work(db, "Book X", series=a, ol_id="OL1W")
    y = await make_work(db, "Book Y", series=a, ol_id="OL2W")
    await make_member(db, a, x, 1.0)
    await make_member(db, a, y, 2.0)
    return lib, a.id, b.id, x.id, y.id


def move(work_id, **fields):
    return MoveAction(kind="move", work_id=work_id, **fields)


async def count_corrections(db):
    return await db.scalar(select(func.count()).select_from(CatalogCorrection))


async def test_moves_share_one_batch_and_one_reason(db_session):
    lib, a, b, x, y = await saga(db_session)
    batch_id, rows = await apply_batch(db_session, lib, [move(x, series_id=b), move(y, series_id=b)],
                                       reason="  both in Beta ")
    assert [c.op for c in rows] == [CorrectionOp.set_series, CorrectionOp.set_series]
    assert {c.batch_id for c in rows} == {batch_id}
    assert {c.reason for c in rows} == {"both in Beta"}
    assert rows[0].created_at < rows[1].created_at  # newest-first undo relies on this order
    assert await fresh(db_session, Work.series_id, x) == b
    assert await fresh(db_session, Work.series_id, y) == b


async def test_positions_and_removes_in_one_batch(db_session):
    lib, a, _, x, y = await saga(db_session)
    _, rows = await apply_batch(db_session, lib, [
        PositionAction(kind="position", series_id=a, work_id=x, position=2),
        RemoveAction(kind="remove", series_id=a, work_id=y),
    ], reason="r")
    assert [c.op for c in rows] == [CorrectionOp.set_position, CorrectionOp.remove_from_series]
    member = (await db_session.execute(select(SeriesMember.position).where(
        SeriesMember.series_id == a, SeriesMember.work_id == x))).scalar_one()
    assert member == 2
    assert await fresh(db_session, Work.series_id, y) != a


async def test_one_refused_fix_leaves_nothing_behind(db_session):
    lib, a, b, x, y = await saga(db_session)
    other = await make_work(db_session, "Book Z", ol_id="OL3W")
    await merge(db_session, lib, await db_session.get(Work, y), other, reason="dup", confirm=True)
    before = await count_corrections(db_session)

    with pytest.raises(Conflict, match="^Book Y: .*merged"):
        await apply_batch(db_session, lib, [move(x, series_id=b), move(y, series_id=b)], reason="r")

    assert await fresh(db_session, Work.series_id, x) == a
    assert (await db_session.execute(select(func.count()).select_from(SeriesMember).where(
        SeriesMember.series_id == a, SeriesMember.work_id == x))).scalar_one() == 1
    assert await count_corrections(db_session) == before


async def test_a_book_appears_once_a_batch_is_not_empty_and_needs_a_reason(db_session):
    lib, a, b, x, _ = await saga(db_session)
    with pytest.raises(Invalid, match="once"):
        await apply_batch(db_session, lib, [
            move(x, series_id=b), PositionAction(kind="position", series_id=a, work_id=x, position=1)],
            reason="r")
    with pytest.raises(Invalid, match="at least one"):
        await apply_batch(db_session, lib, [], reason="r")
    with pytest.raises(Invalid, match="reason"):
        await apply_batch(db_session, lib, [move(x, series_id=b)], reason="   ")
    assert await count_corrections(db_session) == 0


async def test_an_unknown_book_or_series_is_named_by_its_place(db_session):
    lib, a, b, x, _ = await saga(db_session)
    ghost = uuid.uuid4()
    with pytest.raises(NotFound, match="^Fix 2: Unknown book"):
        await apply_batch(db_session, lib, [move(x, series_id=b), RemoveAction(kind="remove", series_id=a, work_id=ghost)],
                          reason="r")
    with pytest.raises(NotFound, match="^Book X: Unknown series"):
        await apply_batch(db_session, lib, [move(x, series_id=ghost)], reason="r")
    assert await fresh(db_session, Work.series_id, x) == a


async def test_two_batches_over_the_same_books_wait_instead_of_deadlocking(db_session):
    lib, _, b, x, y = await saga(db_session)
    c = (await make_series(db_session, "Gamma", release=R)).id
    lib_id = lib.id
    await db_session.commit()

    engine = create_async_engine(TEST_DB_URL, poolclass=NullPool)
    sessions = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with sessions() as first, sessions() as second:
            await apply_batch(first, await first.get(User, lib_id), [move(y, series_id=b), move(x, series_id=b)],
                              reason="r")  # holds both books' locks until commit
            racing = asyncio.create_task(apply_batch(
                second, await second.get(User, lib_id), [move(x, series_id=c), move(y, series_id=c)], reason="r"))
            await asyncio.sleep(0.3)
            assert not racing.done()  # queued behind the first batch
            await first.commit()
            _, rows = await racing
            await second.commit()
    finally:
        await engine.dispose()
    db_session.expire_all()
    assert len(rows) == 2
    assert await fresh(db_session, Work.series_id, x) == c
    assert await fresh(db_session, Work.series_id, y) == c
```

- [ ] **Step 2: Run the tests to make sure they fail**

Run: `PYTEST tests/test_librarian_batch.py -q`
Expected: FAIL at collection with `ImportError: cannot import name 'MoveAction' from 'app.schemas.librarian'`.

- [ ] **Step 3: Add the batch schemas**

In `backend/app/schemas/librarian.py`, change the imports at the top to:

```python
from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.models import CorrectionOp
```

Append at the end of the file:

```python
# Batch (roadmap 08): the single routes' fields, with the subject's ids in the
# body instead of the path, and one reason for the whole batch.
class MoveAction(BaseModel):
    kind: Literal["move"]
    work_id: UUID
    series_id: UUID | None = None
    new_series_name: str | None = Field(default=None, max_length=500)
    position: float | None = Field(default=None, allow_inf_nan=False)


class PositionAction(BaseModel):
    kind: Literal["position"]
    series_id: UUID
    work_id: UUID
    position: float | None = Field(default=None, allow_inf_nan=False)


class RemoveAction(BaseModel):
    kind: Literal["remove"]
    series_id: UUID
    work_id: UUID


BatchAction = Annotated[MoveAction | PositionAction | RemoveAction, Field(discriminator="kind")]


class BatchIn(_Reasoned):
    actions: list[BatchAction] = Field(min_length=1, max_length=500)


class BatchOut(BaseModel):
    batch_id: UUID
    corrections: list[CorrectionOut]
```

- [ ] **Step 4: Write `apply_batch`**

`backend/app/services/librarian/batch.py`:

```python
"""Batch fixes (roadmap 08): several v1 placement ops under one reason, in one
transaction, undone together.

A batch reuses the single-op services unchanged: each member is an ordinary
correction that also carries ``batch_id``. Members name distinct books, so the
v1 undo rule (latest unreverted fix on its subject, catalog unchanged since)
holds for each member on its own, and undoing newest first replays the batch
backwards. A room the last move emptied comes back before the earlier moves
look for it.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import CatalogCorrection, Series, User, Work
from app.schemas.librarian import MoveAction, PositionAction, RemoveAction
from app.services.librarian.errors import Invalid, LibrarianError, NotFound
from app.services.librarian.placement import remove_from_series, set_position, set_series
from app.services.librarian.record import clean_reason

Action = MoveAction | PositionAction | RemoveAction


def _labelled(exc: LibrarianError, label: str) -> LibrarianError:
    """Say which fix of the batch was refused; status and shape stay v1's."""
    exc.message = f"{label}: {exc.message}"
    exc.args = (exc.message,)
    return exc


async def _lock_books(db: AsyncSession, work_ids) -> None:
    """Lock every book up front, in id order. Two batches over the same books
    then queue behind each other instead of each holding one and waiting for
    the other, a deadlock Postgres would end with an error."""
    ids = sorted({i for i in work_ids if i is not None})
    if ids:
        await db.execute(select(Work.id).where(Work.id.in_(ids)).order_by(Work.id).with_for_update())


async def _series_or_404(db: AsyncSession, series_id) -> Series:
    series = await db.get(Series, series_id)
    if series is None:
        raise NotFound("Unknown series.")
    return series


async def _apply(db: AsyncSession, user: User, action: Action, work: Work | None,
                 reason: str) -> CatalogCorrection:
    if work is None:
        raise NotFound("Unknown book.")
    if action.kind == "move":
        series = await _series_or_404(db, action.series_id) if action.series_id is not None else None
        return await set_series(db, user, work, series=series, new_series_name=action.new_series_name,
                                position=action.position, reason=reason)
    room = await _series_or_404(db, action.series_id)
    if action.kind == "position":
        return await set_position(db, user, room, work, action.position, reason=reason)
    return await remove_from_series(db, user, room, work, reason=reason)


async def apply_batch(db: AsyncSession, user: User, actions: list[Action], *,
                      reason: str) -> tuple[uuid.UUID, list[CatalogCorrection]]:
    reason = clean_reason(reason)
    if not actions:
        raise Invalid("A batch needs at least one fix.")
    work_ids = [a.work_id for a in actions]
    if len(set(work_ids)) != len(work_ids):
        raise Invalid("Each book can appear once in a batch.")
    batch_id, corrections = uuid.uuid4(), []
    # A savepoint: a refusal undoes the members already applied even where the
    # session outlives the call (in a request, get_db rolls back as well).
    async with db.begin_nested():
        await _lock_books(db, work_ids)
        for number, action in enumerate(actions, start=1):
            work = await db.get(Work, action.work_id)
            label = work.title if work is not None else f"Fix {number}"
            try:
                correction = await _apply(db, user, action, work, reason)
            except LibrarianError as exc:
                raise _labelled(exc, label) from None
            correction.batch_id = batch_id
            corrections.append(correction)
        await db.flush()
    return batch_id, corrections
```

In `backend/app/services/librarian/__init__.py`, append:

```python
from app.services.librarian.batch import apply_batch  # noqa: E402,F401
```

- [ ] **Step 5: Run the tests**

Run: `PYTEST tests/test_librarian_batch.py -q`
Expected: 6 passed.

- [ ] **Step 6: Run the librarian suites and commit**

Run: `PYTEST tests/test_librarian_placement.py tests/test_librarian_undo.py tests/test_librarian_hardening.py tests/test_librarian_batch.py -q`
Expected: all pass. The v1 ops are unchanged.

```bash
git add backend/app/schemas/librarian.py backend/app/services/librarian/batch.py \
  backend/app/services/librarian/__init__.py backend/tests/test_librarian_batch.py
git commit -m "feat(librarian): apply several moves, positions or removes as one all-or-nothing batch"
```

---

### Task 3: Undo a batch, newest first, all or nothing

**Files:**
- Modify: `backend/app/services/librarian/undo.py` (`revert`)
- Modify: `backend/app/services/librarian/batch.py`
- Modify: `backend/app/services/librarian/__init__.py`
- Test: `backend/tests/test_librarian_batch.py`

**Interfaces:**
- Consumes: `_labelled`, `_lock_books` (Task 2).
- Produces: `undo.revert_one(db, user, correction) -> CatalogCorrection` (the v1 revert body, batch-agnostic). `undo.revert` now raises `Invalid("This fix is part of a batch; undo the batch.")` for a member. `batch.revert_batch(db, user, batch_id) -> list[CatalogCorrection]` (newest first). It raises `NotFound("Unknown batch.")`, `Conflict("This batch was already undone.")`, or the first member's v1 refusal, labelled with its book's title.

- [ ] **Step 1: Write the failing tests**

In `backend/tests/test_librarian_batch.py`, extend the imports:

```python
from app.services.librarian.batch import apply_batch, revert_batch
from app.services.librarian.placement import set_position
from app.services.librarian.undo import revert
```

(replacing the existing `from app.services.librarian.batch import apply_batch` line). Append:

```python
async def test_undoing_a_batch_goes_newest_first_so_an_emptied_room_comes_back(db_session):
    lib, a, _, x, y = await saga(db_session)
    batch_id, _ = await apply_batch(db_session, lib, [move(x, new_series_name="Gamma"),
                                                      move(y, new_series_name="Gamma")], reason="r")
    gamma = await fresh(db_session, Work.series_id, x)
    assert await fresh(db_session, Series.merged_into_id, a) == gamma  # the last move emptied Alpha

    rows = await revert_batch(db_session, lib, batch_id)

    assert [r.work_id for r in rows] == [y, x]  # newest first
    assert all(r.reverted_at is not None and r.reverted_by_id == lib.id for r in rows)
    assert await fresh(db_session, Series.merged_into_id, a) is None
    assert await fresh(db_session, Work.series_id, x) == a
    assert await fresh(db_session, Work.series_id, y) == a
    assert await fresh(db_session, Series.merged_into_id, gamma) == a  # the batch's new series is a tombstone again


async def test_a_batch_undo_is_all_or_nothing(db_session):
    lib, _, b, x, y = await saga(db_session)
    batch_id, _ = await apply_batch(db_session, lib, [move(x, series_id=b), move(y, series_id=b)], reason="r")
    await set_position(db_session, lib, await db_session.get(Series, b), await db_session.get(Work, x), 5,
                       reason="a later fix")

    with pytest.raises(Conflict, match="^Book X: A later fix"):
        await revert_batch(db_session, lib, batch_id)

    assert await fresh(db_session, Work.series_id, y) == b  # Book Y's undo was rolled back with the rest
    assert await db_session.scalar(select(func.count()).select_from(CatalogCorrection).where(
        CatalogCorrection.batch_id == batch_id, CatalogCorrection.reverted_at.is_not(None))) == 0


async def test_a_batch_member_is_undone_only_with_its_batch(db_session):
    lib, _, b, x, _ = await saga(db_session)
    batch_id, rows = await apply_batch(db_session, lib, [move(x, series_id=b)], reason="r")
    with pytest.raises(Invalid, match="part of a batch"):
        await revert(db_session, lib, rows[0])
    await revert_batch(db_session, lib, batch_id)
    with pytest.raises(Conflict, match="already undone"):
        await revert_batch(db_session, lib, batch_id)
    with pytest.raises(NotFound, match="Unknown batch"):
        await revert_batch(db_session, lib, uuid.uuid4())
```

- [ ] **Step 2: Run them to make sure they fail**

Run: `PYTEST tests/test_librarian_batch.py -q`
Expected: FAIL at collection with `ImportError: cannot import name 'revert_batch'`.

- [ ] **Step 3: Split `revert` in `undo.py`**

In `backend/app/services/librarian/undo.py`, replace:

```python
async def revert(db: AsyncSession, user: User, correction: CatalogCorrection) -> CatalogCorrection:
    if correction.op not in UNDOABLE:
        raise Invalid("Merges and splits cannot be undone.")
```

with:

```python
async def revert(db: AsyncSession, user: User, correction: CatalogCorrection) -> CatalogCorrection:
    """Undo one fix. A fix made in a batch is undone only with its batch
    (batch.revert_batch), so a batch never ends half-undone."""
    if correction.batch_id is not None:
        raise Invalid("This fix is part of a batch; undo the batch.")
    return await revert_one(db, user, correction)


async def revert_one(db: AsyncSession, user: User, correction: CatalogCorrection) -> CatalogCorrection:
    if correction.op not in UNDOABLE:
        raise Invalid("Merges and splits cannot be undone.")
```

The rest of the old body stays as it is under `revert_one`.

- [ ] **Step 4: Add `revert_batch`**

In `backend/app/services/librarian/batch.py`, change the errors import to:

```python
from app.services.librarian.errors import Conflict, Invalid, LibrarianError, NotFound
```

add under the other imports:

```python
from app.services.librarian.undo import revert_one
```

and append:

```python
async def revert_batch(db: AsyncSession, user: User, batch_id: uuid.UUID) -> list[CatalogCorrection]:
    """Undo every member, newest first, or none. Each member passes the v1
    rule on its own; any refusal rolls back the members already undone."""
    members = list((await db.execute(
        select(CatalogCorrection).where(CatalogCorrection.batch_id == batch_id)
        .order_by(CatalogCorrection.created_at.desc(), CatalogCorrection.id.desc())
    )).scalars().all())
    if not members:
        raise NotFound("Unknown batch.")
    if all(c.reverted_at is not None for c in members):
        raise Conflict("This batch was already undone.")
    async with db.begin_nested():
        await _lock_books(db, [c.work_id for c in members])
        for c in members:
            work = await db.get(Work, c.work_id) if c.work_id is not None else None
            label = work.title if work is not None else "A fix"
            try:
                await revert_one(db, user, c)
            except LibrarianError as exc:
                raise _labelled(exc, label) from None
    return members
```

In `backend/app/services/librarian/__init__.py`, change the batch line to:

```python
from app.services.librarian.batch import apply_batch, revert_batch  # noqa: E402,F401
```

- [ ] **Step 5: Run the tests**

Run: `PYTEST tests/test_librarian_batch.py tests/test_librarian_undo.py tests/test_librarian_hardening.py -q`
Expected: all pass (9 in `test_librarian_batch.py`). The v1 undo tests are unchanged, because a single fix has `batch_id = None`.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/librarian/undo.py backend/app/services/librarian/batch.py \
  backend/app/services/librarian/__init__.py backend/tests/test_librarian_batch.py
git commit -m "feat(librarian): undo a batch newest first, all or nothing; a member is never undone alone"
```

---

### Task 4: The batch routes

**Files:**
- Modify: `backend/app/api/librarian.py`
- Test: `backend/tests/test_librarian_batch.py`, `backend/tests/test_librarian_api.py`

**Interfaces:**
- Consumes: `librarian.apply_batch`, `librarian.revert_batch` (Tasks 2–3), `BatchIn`, `BatchOut` (Task 2), `correction_out` (Task 1).
- Produces: `POST /api/librarian/batch` (201 → `BatchOut`, corrections in action order) and `POST /api/librarian/batches/{batch_id}/revert` (200 → `BatchOut`, corrections newest first). Errors are v1's (404/409/422, string `detail`). The frontend (Task 5) calls these.

- [ ] **Step 1: Write the failing tests**

In `backend/tests/test_librarian_api.py`, add two entries at the end of `WRITES`:

```python
    ("/api/librarian/batch", {"reason": "r", "actions": [{"kind": "remove", "series_id": ANY, "work_id": ANY}]}),
    (f"/api/librarian/batches/{ANY}/revert", {}),
```

(`test_every_route_refuses_readers_and_anonymous` and `test_unknown_ids_are_404` then cover both routes.)

Append to `backend/tests/test_librarian_batch.py`:

```python
from tests.librarian_factories import headers_for  # noqa: E402  (route tests below)

ANY = "00000000-0000-0000-0000-000000000000"


async def test_batch_routes_refuse_readers_and_anonymous(client, db_session):
    reader = headers_for(await make_user(db_session))
    body = {"reason": "r", "actions": [{"kind": "remove", "series_id": ANY, "work_id": ANY}]}
    for path, payload in [("/api/librarian/batch", body), (f"/api/librarian/batches/{ANY}/revert", {})]:
        assert (await client.post(path, json=payload)).status_code in (401, 403), path  # HTTPBearer's anonymous status
        assert (await client.post(path, json=payload, headers=reader)).status_code == 403, path


async def test_batch_route_round_trip_and_group_undo(client, db_session):
    lib, _, _, x, y = await saga(db_session)
    headers = headers_for(lib)
    resp = await client.post("/api/librarian/batch", headers=headers, json={"reason": "a trilogy", "actions": [
        {"kind": "move", "work_id": str(x), "new_series_name": "Gamma"},
        {"kind": "move", "work_id": str(y), "new_series_name": "Gamma"},
    ]})
    assert resp.status_code == 201, resp.text
    out = resp.json()
    assert [c["subject"] for c in out["corrections"]] == ["Book X", "Book Y"]
    assert {c["batch_id"] for c in out["corrections"]} == {out["batch_id"]}
    assert all(c["undoable"] and c["reason"] == "a trilogy" for c in out["corrections"])

    single = await client.post(f"/api/librarian/corrections/{out['corrections'][0]['id']}/revert", headers=headers)
    assert single.status_code == 422 and "part of a batch" in single.json()["detail"]

    undone = await client.post(f"/api/librarian/batches/{out['batch_id']}/revert", headers=headers)
    assert undone.status_code == 200, undone.text
    assert [c["subject"] for c in undone.json()["corrections"]] == ["Book Y", "Book X"]
    assert all(c["reverted_at"] and not c["undoable"] for c in undone.json()["corrections"])
    again = await client.post(f"/api/librarian/batches/{out['batch_id']}/revert", headers=headers)
    assert again.status_code == 409


async def test_batch_bodies_are_validated(client, db_session):
    lib, a, _, x, _ = await saga(db_session)
    headers = headers_for(lib)
    for body in [
        {"reason": "r", "actions": []},
        {"reason": "r", "actions": [{"kind": "merge", "work_id": str(x)}]},
        {"reason": "r", "actions": [{"kind": "position", "work_id": str(x)}]},  # no series_id
        {"reason": "r", "actions": [{"kind": "move", "work_id": str(x), "new_series_name": "S", "position": "NaN"}]},
        {"reason": "  ", "actions": [{"kind": "remove", "series_id": str(a), "work_id": str(x)}]},
        {"reason": "r", "actions": [{"kind": "remove", "series_id": str(a), "work_id": str(x)}] * 2},
    ]:
        resp = await client.post("/api/librarian/batch", json=body, headers=headers)
        assert resp.status_code == 422, (body, resp.text)
    assert await fresh(db_session, Work.series_id, x) == a
```

- [ ] **Step 2: Run them to make sure they fail**

Run: `PYTEST tests/test_librarian_batch.py tests/test_librarian_api.py -q`
Expected: FAIL. The new route tests get 404 (`Not Found` from the router, since no route exists). In `test_every_route_refuses_readers_and_anonymous`, the reader gets 404 and not 403.

- [ ] **Step 3: Add the routes**

In `backend/app/api/librarian.py`, change the schema import to:

```python
from app.schemas.librarian import (
    BatchIn, BatchOut, CorrectionOut, DissolveIn, EditionOut, MergeIn, MoveIn, PositionIn, RemoveIn, RenameIn,
    SeriesHit, SplitIn,
)
```

Add after the `dissolve` route:

```python
@router.post("/batch", response_model=BatchOut, status_code=status.HTTP_201_CREATED)
async def batch(body: BatchIn, db: AsyncSession = Depends(get_db), user: User = Depends(require_librarian)):
    batch_id, rows = await _run(librarian.apply_batch(db, user, body.actions, reason=body.reason))
    return BatchOut(batch_id=batch_id, corrections=[await correction_out(db, c) for c in rows])


@router.post("/batches/{batch_id}/revert", response_model=BatchOut)
async def revert_whole_batch(batch_id: UUID, db: AsyncSession = Depends(get_db),
                             user: User = Depends(require_librarian)):
    rows = await _run(librarian.revert_batch(db, user, batch_id))
    return BatchOut(batch_id=batch_id, corrections=[await correction_out(db, c) for c in rows])
```

- [ ] **Step 4: Run the tests**

Run: `PYTEST tests/test_librarian_batch.py tests/test_librarian_api.py -q`
Expected: PASS (12 in `test_librarian_batch.py`, plus every `test_librarian_api.py` test).

- [ ] **Step 5: Full backend suite and commit**

Run: `PYTEST -q -p no:warnings`
Expected: all pass.

```bash
git add backend/app/api/librarian.py backend/tests/test_librarian_batch.py backend/tests/test_librarian_api.py
git commit -m "feat(api): POST /librarian/batch and /librarian/batches/{id}/revert"
```

---

### Task 5: Frontend API hooks and pure batch helpers

**Files:**
- Modify: `frontend/src/api/librarian.js`
- Create: `frontend/src/components/librarian/batch.js`
- Create: `frontend/src/components/librarian/batch.test.js`

**Interfaces:**
- Produces: `useLibrarianBatch()`, a mutation whose `mutate({ reason, actions })` resolves to `BatchOut` and marks every query stale. `useRevertBatch()`, whose `mutate(batchId)` resolves to `BatchOut`.
- Produces: `groupKey(work) -> string` (`work.subseries ?? ''`), and `renumber(orderedWorks) -> Map<workId, number>` (1…k per group, in the given order). Also `positionActions(orderedWorks, seriesId) -> [{kind: 'position', series_id, work_id, position}]`, only for works whose `position` differs from the new number. Item 09 imports all three. `useRevertBatch()` is the hook item 11 consumes for the fix log's group undo (same shape as `useRevertCorrection()`: no argument to the hook, the id goes to `mutate`).

- [ ] **Step 1: Write the failing helper tests**

`frontend/src/components/librarian/batch.test.js`:

```js
import { describe, it, expect } from 'vitest'
import { positionActions, renumber } from './batch'

const book = (id, position = null, subseries = null) => ({ id, title: id, position, subseries })

describe('renumber', () => {
  it('numbers 1…k within each sub-series group, in the given order', () => {
    const numbers = renumber([book('e'), book('m1', 3, 'Mistborn'), book('m2', 1, 'Mistborn'), book('w')])
    expect(Object.fromEntries(numbers)).toEqual({ e: 1, m1: 1, m2: 2, w: 2 })
  })
})

describe('positionActions', () => {
  it('asks only for positions that change', () => {
    expect(positionActions([book('a', 1), book('b', 3), book('c')], 's1')).toEqual([
      { kind: 'position', series_id: 's1', work_id: 'b', position: 2 },
      { kind: 'position', series_id: 's1', work_id: 'c', position: 3 },
    ])
  })

  it('asks for nothing when the books are already numbered in this order', () => {
    expect(positionActions([book('a', 1), book('b', 2)], 's1')).toEqual([])
  })
})
```

- [ ] **Step 2: Run them to make sure they fail**

Run: `cd frontend && npx vitest run src/components/librarian/batch.test.js`
Expected: FAIL. `Failed to resolve import "./batch"`.

- [ ] **Step 3: Write the helpers and the hooks**

`frontend/src/components/librarian/batch.js`:

```js
/**
 * Pure helpers for batch fixes. A book's position lives in the deepest series
 * that holds it, so numbering restarts in each sub-series group, the groups
 * the series page draws.
 */
export const groupKey = (work) => work.subseries ?? ''

/** workId → 1…k within its group, in the order given. */
export function renumber(orderedWorks) {
  const counts = new Map()
  const numbers = new Map()
  for (const work of orderedWorks) {
    const n = (counts.get(groupKey(work)) ?? 0) + 1
    counts.set(groupKey(work), n)
    numbers.set(work.id, n)
  }
  return numbers
}

/** Batch `position` actions numbering these books 1…k per group; unchanged ones are left out. */
export function positionActions(orderedWorks, seriesId) {
  const numbers = renumber(orderedWorks)
  return orderedWorks
    .filter((work) => work.position !== numbers.get(work.id))
    .map((work) => ({ kind: 'position', series_id: seriesId, work_id: work.id, position: numbers.get(work.id) }))
}
```

Append to `frontend/src/api/librarian.js`:

```js
export function useLibrarianBatch() {
  const invalidate = useInvalidateCatalog()
  return useMutation({
    mutationFn: (body) => client.post('/librarian/batch', body).then((r) => r.data),
    onSuccess: invalidate,
  })
}

export function useRevertBatch() {
  const invalidate = useInvalidateCatalog()
  return useMutation({
    mutationFn: (batchId) => client.post(`/librarian/batches/${batchId}/revert`).then((r) => r.data),
    onSuccess: invalidate,
  })
}
```

- [ ] **Step 4: Run the tests**

Run: `cd frontend && npx vitest run src/components/librarian/batch.test.js`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/api/librarian.js frontend/src/components/librarian/batch.js frontend/src/components/librarian/batch.test.js
git commit -m "feat(web): batch API hooks and numbering helpers"
```

---

### Task 6: `BatchPanel`

**Files:**
- Create: `frontend/src/components/librarian/useDialogFocus.js`
- Create: `frontend/src/components/librarian/BatchPanel.jsx`
- Create: `frontend/src/components/librarian/BatchPanel.test.jsx`

**Interfaces:**
- Consumes: `useLibrarianBatch` and `positionActions`/`renumber` (Task 5), `SeriesPicker` from `components/librarian/pickers.jsx` (item 03), and `ReasonField` from `components/librarian/ReasonField.jsx` (item 02).
- Produces: `useDialogFocus(onClose) -> { dialogRef, onKeyDown }`. It focuses the first input or textarea on mount, keeps Tab inside, closes on Escape, and gives focus back on unmount.
- Produces: `export function actionsFor(batch, target)` and `default BatchPanel({ batch: { kind: 'move' | 'remove' | 'number', works, series }, onClose, onDone })`. `onDone(batchOut)` runs after the server accepts. Submit buttons are `Move books` / `Remove books` / `Number books`. Item 09 adds kind `order`.

- [ ] **Step 1: Check the item 02 and 03 contracts this task builds on**

Run: `ls frontend/src/components/librarian/ReasonField.jsx frontend/src/components/librarian/pickers.jsx`

Both must exist (item 08 depends on 02; the pickers moved in 03). If `pickers.jsx` is missing, do item 03 Task 1 first, since it is self-contained. Open `ReasonField.jsx` and confirm its props. This plan calls it as `<ReasonField kind={…} value={reason} onChange={setReason} />`, with `onChange` receiving the new string and its textarea labelled `Reason`. If the real props differ (for example, `onChange` receives an event, or the preset kind is named differently), adapt the one call in Step 3, and keep the tests' `getByLabelText('Reason')`.

- [ ] **Step 2: Write the failing tests**

`frontend/src/components/librarian/BatchPanel.test.jsx`:

```jsx
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

vi.mock('../../api/client', () => ({ default: { get: vi.fn(), post: vi.fn() } }))

import client from '../../api/client'
import BatchPanel from './BatchPanel'

const SERIES = { id: 's1', name: 'Dune', slug: 'dune', kind: 'series' }
const WORKS = [
  { id: 'w1', title: 'Dune', position: 1, subseries: null },
  { id: 'w2', title: 'Dune Messiah', position: 3, subseries: null },
]
const OUT = { batch_id: 'b1', corrections: [] }

function renderPanel(batch, { onDone = vi.fn(), onClose = vi.fn() } = {}) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={qc}>
      <BatchPanel batch={{ series: SERIES, works: WORKS, ...batch }} onClose={onClose} onDone={onDone} />
    </QueryClientProvider>,
  )
  return { onDone, onClose }
}

beforeEach(() => vi.clearAllMocks())

describe('BatchPanel', () => {
  it('moves every selected book into the picked series in one batch', async () => {
    client.get.mockResolvedValue({ data: [{ id: 's2', slug: 'legends', name: 'Legends of Dune', book_count: 3 }] })
    client.post.mockResolvedValue({ data: OUT })
    const { onDone } = renderPanel({ kind: 'move' })
    expect(screen.getByRole('dialog', { name: 'Move 2 books' })).toBeInTheDocument()
    await userEvent.type(screen.getByLabelText('Move them to'), 'legends')
    await userEvent.click(await screen.findByRole('radio', { name: /Legends of Dune/ }))
    const submit = screen.getByRole('button', { name: 'Move books' })
    expect(submit).toBeDisabled() // no reason yet
    await userEvent.type(screen.getByLabelText('Reason'), 'prequels')
    await userEvent.click(submit)
    await waitFor(() => expect(onDone).toHaveBeenCalledWith(OUT))
    expect(client.post).toHaveBeenCalledWith('/librarian/batch', { reason: 'prequels', actions: [
      { kind: 'move', work_id: 'w1', series_id: 's2' },
      { kind: 'move', work_id: 'w2', series_id: 's2' },
    ] })
  })

  it('will not move books into the series they are already in', async () => {
    client.get.mockResolvedValue({ data: [{ id: 's1', slug: 'dune', name: 'Dune', book_count: 2 }] })
    renderPanel({ kind: 'move' })
    await userEvent.type(screen.getByLabelText('Move them to'), 'dune')
    await userEvent.click(await screen.findByRole('radio', { name: /^Dune/ }))
    await userEvent.type(screen.getByLabelText('Reason'), 'r')
    expect(screen.getByText(/They are already in/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Move books' })).toBeDisabled()
  })

  it('removes every selected book from this series', async () => {
    client.post.mockResolvedValue({ data: OUT })
    renderPanel({ kind: 'remove' })
    expect(screen.getByText(/Each book gets its own page again/)).toBeInTheDocument()
    await userEvent.type(screen.getByLabelText('Reason'), 'not this series')
    await userEvent.click(screen.getByRole('button', { name: 'Remove books' }))
    await waitFor(() => expect(client.post).toHaveBeenCalledWith('/librarian/batch', { reason: 'not this series', actions: [
      { kind: 'remove', series_id: 's1', work_id: 'w1' },
      { kind: 'remove', series_id: 's1', work_id: 'w2' },
    ] }))
  })

  it('numbers the books 1…n in page order and shows what changes', async () => {
    client.post.mockResolvedValue({ data: OUT })
    renderPanel({ kind: 'number' })
    const list = screen.getByRole('list', { name: 'Books in this batch' })
    expect(within(list).getByText('#1, unchanged')).toBeInTheDocument()
    expect(within(list).getAllByRole('listitem')[1]).toHaveTextContent('#3 becomes #2')
    await userEvent.type(screen.getByLabelText('Reason'), 'reading order')
    await userEvent.click(screen.getByRole('button', { name: 'Number books' }))
    await waitFor(() => expect(client.post).toHaveBeenCalledWith('/librarian/batch', { reason: 'reading order', actions: [
      { kind: 'position', series_id: 's1', work_id: 'w2', position: 2 },
    ] }))
  })

  it('has nothing to send when the books are already numbered', async () => {
    renderPanel({ kind: 'number', works: [{ ...WORKS[0] }, { ...WORKS[1], position: 2 }] })
    await userEvent.type(screen.getByLabelText('Reason'), 'r')
    expect(screen.getByText(/already numbered in this order/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Number books' })).toBeDisabled()
  })

  it('shows the server refusal, naming the book, and clears it on edit', async () => {
    client.post.mockRejectedValueOnce({ response: { status: 409, data: {
      detail: 'Dune Messiah: Dune Messiah was merged into another book; reload the page.' } } })
    renderPanel({ kind: 'remove' })
    await userEvent.type(screen.getByLabelText('Reason'), 'r')
    await userEvent.click(screen.getByRole('button', { name: 'Remove books' }))
    expect(await screen.findByText(/^Dune Messiah: Dune Messiah was merged/)).toBeInTheDocument()
    await userEvent.type(screen.getByLabelText('Reason'), 'x')
    expect(screen.queryByText(/was merged/)).toBeNull()
  })

  it('starts with focus inside and closes on Escape', () => {
    const { onClose } = renderPanel({ kind: 'remove' })
    expect(screen.getByRole('dialog').contains(document.activeElement)).toBe(true)
    fireEvent.keyDown(document.activeElement, { key: 'Escape' })
    expect(onClose).toHaveBeenCalled()
  })
})
```

- [ ] **Step 3: Run them to make sure they fail**

Run: `cd frontend && npx vitest run src/components/librarian/BatchPanel.test.jsx`
Expected: FAIL. `Failed to resolve import "./BatchPanel"`.

- [ ] **Step 4: Write `useDialogFocus` and `BatchPanel`**

`frontend/src/components/librarian/useDialogFocus.js`:

```js
import { useEffect, useRef } from 'react'

/**
 * A modal float's keyboard contract: focus starts inside, Tab cannot leave
 * (aria-modal promises the page behind is out of reach), Escape closes, and
 * focus returns to whatever opened it.
 */
export default function useDialogFocus(onClose) {
  const dialogRef = useRef(null)
  useEffect(() => {
    const opener = document.activeElement
    dialogRef.current?.querySelector('input, textarea')?.focus()
    return () => opener?.focus?.()
  }, [])
  const onKeyDown = (e) => {
    if (e.key === 'Escape') return onClose()
    if (e.key !== 'Tab') return
    const focusable = [...dialogRef.current.querySelectorAll('button, input, textarea, select, a[href]')]
      .filter((el) => !el.disabled)
    if (!focusable.length) return
    const first = focusable[0]
    const last = focusable[focusable.length - 1]
    if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus() }
    else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus() }
  }
  return { dialogRef, onKeyDown }
}
```

`frontend/src/components/librarian/BatchPanel.jsx`:

```jsx
import { useState } from 'react'
import { useLibrarianBatch } from '../../api/librarian'
import { errorMessage } from '../../api/errors'
import { SeriesPicker } from './pickers'
import ReasonField from './ReasonField'
import useDialogFocus from './useDialogFocus'
import { positionActions, renumber } from './batch'

/**
 * One reason for several fixes, sent as one batch: the server applies all of
 * them or none, and they are undone together. Nothing here decides anything.
 */
const plural = (n, one, many = `${one}s`) => `${n} ${n === 1 ? one : many}`
const REASON_KIND = { move: 'move', remove: 'remove', number: 'position' }
const SUBMIT = { move: 'Move books', remove: 'Remove books', number: 'Number books' }

export function actionsFor({ kind, works, series }, target) {
  if (kind === 'move') {
    const to = target?.id ? { series_id: target.id } : { new_series_name: target?.name }
    return works.map((w) => ({ kind: 'move', work_id: w.id, ...to }))
  }
  if (kind === 'remove') return works.map((w) => ({ kind: 'remove', series_id: series.id, work_id: w.id }))
  return positionActions(works, series.id)
}

function titleOf({ kind, works, series }) {
  const n = plural(works.length, 'book')
  if (kind === 'move') return `Move ${n}`
  if (kind === 'remove') return `Remove ${n} from ${series.name}`
  return `Number ${n} in ${series.name}`
}

function Renumbered({ from, to }) {
  if (from === to) return <span className="text-ink-dim text-xs tabular-nums">#{to}, unchanged</span>
  return (
    <span className="text-ink-dim text-xs tabular-nums">
      {from == null ? 'no position' : `#${from}`}{' '}
      <span aria-hidden="true">→</span><span className="sr-only">becomes</span>{' '}
      <span className="text-warning">#{to}</span>
    </span>
  )
}

function BatchPanel({ batch, onClose, onDone }) {
  const { kind, works, series } = batch
  const [reason, setReason] = useState('')
  const [target, setTarget] = useState(null)
  const mutation = useLibrarianBatch()
  const { dialogRef, onKeyDown } = useDialogFocus(onClose)
  const edit = (setter) => (value) => {
    if (mutation.isError) mutation.reset() // a refusal answered the old values, not these
    setter(value)
  }
  const actions = actionsFor(batch, target)
  const numbers = kind === 'number' ? renumber(works) : null
  const sameRoom = kind === 'move' && target?.id === series.id
  const canSubmit = !!reason.trim() && actions.length > 0 && !mutation.isPending
    && (kind !== 'move' || (!!target && !sameRoom))
  const title = titleOf(batch)
  const submit = (e) => {
    e.preventDefault()
    mutation.mutate({ reason: reason.trim(), actions }, { onSuccess: onDone })
  }

  return (
    <div className="fixed inset-0 bg-bg/90 flex items-center justify-center z-50 p-4">
      <div ref={dialogRef} role="dialog" aria-modal="true" aria-label={title} onKeyDown={onKeyDown}
           className="float w-full max-w-prose flex flex-col gap-4 p-5">
        <div className="flex items-center justify-between">
          <h2 className="text-sm uppercase tracking-eyebrow text-ink">{title}</h2>
          <button type="button" onClick={onClose} aria-label="Close" className="text-ink-dim hover:text-danger">
            <span aria-hidden="true">✕</span>
          </button>
        </div>
        <form className="flex flex-col gap-3" onSubmit={submit}>
          <ul aria-label="Books in this batch" className="flex flex-col gap-1 text-sm">
            {works.map((w) => (
              <li key={w.id} className="flex items-baseline gap-3">
                <span className="font-serif text-ink">{w.title}</span>
                {numbers && <Renumbered from={w.position} to={numbers.get(w.id)} />}
              </li>
            ))}
          </ul>
          {kind === 'move' && <SeriesPicker label="Move them to" value={target} onChange={edit(setTarget)} />}
          {sameRoom && (
            <p className="alert-muted">They are already in <span className="font-serif">{series.name}</span>.</p>
          )}
          {kind === 'remove' && (
            <p className="text-sm text-ink-dim">Each book gets its own page again, with the threads tagged with it.</p>
          )}
          {kind === 'number' && actions.length === 0 && (
            <p className="alert-muted">These books are already numbered in this order.</p>
          )}
          <ReasonField kind={REASON_KIND[kind]} value={reason} onChange={edit(setReason)} />
          {mutation.isError && <p className="alert-danger">{errorMessage(mutation.error)}</p>}
          <button type="submit" className="btn-primary text-xs self-start" disabled={!canSubmit}>{SUBMIT[kind]}</button>
        </form>
      </div>
    </div>
  )
}

export default BatchPanel
```

- [ ] **Step 5: Run the tests**

Run: `cd frontend && npx vitest run src/components/librarian/BatchPanel.test.jsx src/design/tokens.test.js`
Expected: PASS (7 panel tests, and the token tests unchanged).

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/librarian/useDialogFocus.js frontend/src/components/librarian/BatchPanel.jsx \
  frontend/src/components/librarian/BatchPanel.test.jsx
git commit -m "feat(web): batch panel moves, removes or numbers several books under one reason"
```

---

### Task 7: Checkboxes, action bar and batch result on the series page

**Files:**
- Create: `frontend/src/components/librarian/BatchBar.jsx`
- Create: `frontend/src/components/librarian/BatchResultLine.jsx`
- Modify: `frontend/src/pages/Series.jsx`
- Test: `frontend/src/pages/Series.test.jsx`

**Interfaces:**
- Consumes: `BatchPanel` (Task 6), `useRevertBatch` (Task 5).
- Produces: in edit mode on a live real series, each row has a checkbox named `` `select ${title}` ``. With one or more checked, a toolbar named `Selected books` shows `N selected`, `move selected…`, `remove selected…`, `number 1…n` and `clear selection`. After a batch, a group named `Librarian batch result` shows `N fixes`, the export state and `undo batch`. `BookRow` gains `selected` and `onSelect` props. Item 09 adds `reorder`. Item 10's `x` shortcut calls the same toggle.

- [ ] **Step 1: Write the failing tests**

Append inside `describe('Series page', …)` in `frontend/src/pages/Series.test.jsx`:

```jsx
  it('selects books in edit mode, numbers them 1…n as one batch, then undoes the batch', async () => {
    useAuthStore.setState({ token: 't', user: { id: 'u1', username: 'lib', is_librarian: true } })
    mockApi({ ...SAGA, id: 's1' })
    const corrections = [
      { id: 'c1', batch_id: 'b1', op: 'set_position', exportable: true, undoable: true, room_slug: 'red-rising' },
      { id: 'c2', batch_id: 'b1', op: 'set_position', exportable: true, undoable: true, room_slug: 'red-rising' },
    ]
    client.post
      .mockResolvedValueOnce({ data: { batch_id: 'b1', corrections } })
      .mockResolvedValueOnce({ data: { batch_id: 'b1', corrections: corrections.map((c) => (
        { ...c, undoable: false, reverted_at: '2026-09-29T00:00:00Z' })) } })
    renderPage('/series/red-rising?edit=1')

    const list = await screen.findByRole('list', { name: 'Books in this series' })
    expect(screen.queryByRole('toolbar', { name: 'Selected books' })).toBeNull()
    await userEvent.click(within(list).getByRole('checkbox', { name: 'select Red Rising' }))
    await userEvent.click(within(list).getByRole('checkbox', { name: 'select Golden Son' }))
    const bar = screen.getByRole('toolbar', { name: 'Selected books' })
    expect(within(bar).getByText('2 selected')).toBeInTheDocument()
    await userEvent.click(within(bar).getByRole('button', { name: 'number 1…n' }))
    await userEvent.type(screen.getByLabelText('Reason'), 'reading order')
    await userEvent.click(screen.getByRole('button', { name: 'Number books' }))

    await waitFor(() => expect(client.post).toHaveBeenCalledWith('/librarian/batch', { reason: 'reading order', actions: [
      { kind: 'position', series_id: 's1', work_id: 'b1', position: 1 },
      { kind: 'position', series_id: 's1', work_id: 'b2', position: 2 },
    ] }))
    const status = await screen.findByRole('group', { name: 'Librarian batch result' })
    expect(within(status).getByText('2 fixes')).toBeInTheDocument()
    expect(within(status).getByText('exported')).toBeInTheDocument()
    expect(screen.queryByRole('toolbar', { name: 'Selected books' })).toBeNull() // selection cleared
    await userEvent.click(within(status).getByRole('button', { name: 'undo batch' }))
    expect(client.post).toHaveBeenLastCalledWith('/librarian/batches/b1/revert')
    expect(await within(status).findByText('undone')).toBeInTheDocument()
  })

  it('offers selection only in edit mode on a real series', async () => {
    useAuthStore.setState({ token: 't', user: { id: 'u1', username: 'lib', is_librarian: true } })
    mockApi({ ...SINGLE, id: 's9' }, [])
    const { unmount } = renderPage('/series/the-hobbit-a1b2c3?edit=1')
    await screen.findByRole('heading', { level: 1, name: 'The Hobbit' })
    expect(screen.queryByRole('checkbox', { name: /^select / })).toBeNull()
    unmount()

    mockApi({ ...SAGA, id: 's1' })
    renderPage('/series/red-rising')
    await screen.findByRole('list', { name: 'Books in this series' })
    expect(screen.queryByRole('checkbox', { name: /^select / })).toBeNull()
  })

  it('drops a selected book once it has left the room', async () => {
    useAuthStore.setState({ token: 't', user: { id: 'u1', username: 'lib', is_librarian: true } })
    let payload = { ...SAGA, id: 's1' }
    client.get.mockImplementation((url) =>
      Promise.resolve({ data: url.endsWith('/threads') ? [] : payload }))
    client.post.mockImplementation(() => {
      payload = { ...SAGA, id: 's1', works: [SAGA.works[0]] }
      return Promise.resolve({ data: { id: 'c1', op: 'remove_from_series', exportable: true, undoable: true, room_slug: 'red-rising' } })
    })
    renderPage('/series/red-rising?edit=1')
    const list = await screen.findByRole('list', { name: 'Books in this series' })
    await userEvent.click(within(list).getByRole('checkbox', { name: 'select Red Rising' }))
    await userEvent.click(within(list).getByRole('checkbox', { name: 'select Golden Son' }))
    await userEvent.click(within(list).getByRole('button', { name: 'remove Golden Son' }))
    await userEvent.type(screen.getByLabelText('Reason'), 'not a sequel')
    await userEvent.click(screen.getByRole('button', { name: 'Remove from series' }))
    await waitFor(() => expect(within(screen.getByRole('toolbar', { name: 'Selected books' }))
      .getByText('1 selected')).toBeInTheDocument())
  })
```

- [ ] **Step 2: Run them to make sure they fail**

Run: `cd frontend && npx vitest run src/pages/Series.test.jsx`
Expected: FAIL. The first and third tests fail with `Unable to find an accessible element with the role "checkbox" and name "select Red Rising"`. The second passes, because it asserts absence.

- [ ] **Step 3: Write `BatchBar` and `BatchResultLine`**

`frontend/src/components/librarian/BatchBar.jsx`:

```jsx
/** What can be done to the checked books at once. */
const KINDS = [['move', 'move selected…'], ['remove', 'remove selected…'], ['number', 'number 1…n']]

function BatchBar({ count, onPick, onClear }) {
  return (
    <div role="toolbar" aria-label="Selected books" className="flex flex-wrap items-center gap-3 text-xs border-b border-line pb-3">
      <span className="text-ink tabular-nums">{count} selected</span>
      {KINDS.map(([kind, label]) => (
        <button key={kind} type="button" className="btn-ghost text-xs" onClick={() => onPick(kind)}>{label}</button>
      ))}
      <button type="button" className="btn-ghost text-xs" onClick={onClear}>clear selection</button>
    </div>
  )
}

export default BatchBar
```

`frontend/src/components/librarian/BatchResultLine.jsx`:

```jsx
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useRevertBatch } from '../../api/librarian'
import { errorMessage } from '../../api/errors'

const plural = (n, one, many = `${one}s`) => `${n} ${n === 1 ? one : many}`

/** A batch's outcome on the pages it concerns, with one undo for all of it. */
function BatchResultLine({ batch, currentSlug }) {
  const revert = useRevertBatch()
  const [state, setState] = useState(batch)
  const { corrections } = state
  const runtime = corrections.filter((c) => !c.exportable).length
  const undone = corrections.every((c) => c.reverted_at)
  const undoable = !undone && corrections.every((c) => c.undoable)
  // A move batch sends every book to one series; follow it from here.
  const elsewhere = [...new Set(corrections.map((c) => c.room_slug))].filter((s) => s && s !== currentSlug)
  return (
    // A group, not one live region: only the outcome is announced, not the controls.
    <div role="group" aria-label="Librarian batch result" className="flex flex-col gap-2 border-b border-line pb-3">
      <p className="text-xs flex flex-wrap items-center gap-3">
        <span role="status">
          <span className="text-ink">{plural(corrections.length, 'fix', 'fixes')}</span>{' '}
          {runtime === 0
            ? <span className="text-ok">exported</span>
            : <span className="text-warning">{runtime} runtime-only</span>}
          {undone && <span className="text-ink-dim ml-3">undone</span>}
        </span>
        {undoable && (
          <button type="button" className="btn-ghost text-xs" disabled={revert.isPending}
                  onClick={() => revert.mutate(state.batch_id, { onSuccess: setState })}>
            undo batch
          </button>
        )}
        {elsewhere.length === 1 && !undone && (
          <Link to={`/series/${elsewhere[0]}?edit=1`} state={{ batch: state }} className="text-path hover:text-accent">
            go to the series
          </Link>
        )}
      </p>
      {/* The server re-checks every member: a later fix to any of them refuses the whole undo. */}
      {revert.isError && <p className="alert-danger text-xs">{errorMessage(revert.error)}</p>}
    </div>
  )
}

export default BatchResultLine
```

- [ ] **Step 4: Wire them into `Series.jsx`**

Each snippet below is quoted from the v1 file. If another item has since changed a line (01, 03, 06, 10), make the same change to the line as it now reads.

Imports: add after `import LibrarianPanel from '../components/LibrarianPanel'`:

```jsx
import BatchBar from '../components/librarian/BatchBar'
import BatchPanel from '../components/librarian/BatchPanel'
import BatchResultLine from '../components/librarian/BatchResultLine'
```

`BookRow`: change its signature to

```jsx
function BookRow({ work, current, rowRef, editing, isSeries, onAction, selected = false, onSelect }) {
```

and insert directly above `      {/* Covers carry the colour; large, full colour, never dimmed. */}`:

```jsx
      {onSelect && (
        <input type="checkbox" className="mt-1 shrink-0" checked={selected} onChange={onSelect}
               aria-label={`select ${work.title}`} />
      )}
```

State: add after `const [action, setAction] = useState(null) // { kind, work? } while the panel is open`:

```jsx
  // Checked rows, keyed by the page they were checked on, and the batch float.
  const [selection, setSelection] = useState({ slug: null, ids: [] })
  const [batch, setBatch] = useState(null) // { kind, works } while the batch panel is open
```

Replace the `result` initializer:

```jsx
  const [result, setResult] = useState(() => {
    const correction = location.state?.correction
    return correction ? { correction, pages: [slug, correction.room_slug] } : null
  })
```

with:

```jsx
  const [result, setResult] = useState(() => {
    const { correction, batch: done } = location.state ?? {}
    if (done) return { batch: done, pages: [slug, ...done.corrections.map((c) => c.room_slug)] }
    return correction ? { correction, pages: [slug, correction.room_slug] } : null
  })
```

Derived selection: insert directly above `  const columns = [`:

```jsx
  const selectable = editing && isSeries && !series.dissolved
  // A book fixed away (merged, moved, removed) since it was checked drops out.
  const selectedIds = selectable && selection.slug === series.slug
    ? selection.ids.filter((id) => series.works.some((w) => w.id === id)) : []
  const selectedWorks = series.works.filter((w) => selectedIds.includes(w.id))
  const toggleSelected = (id) => setSelection({
    slug: series.slug,
    ids: selectedIds.includes(id) ? selectedIds.filter((v) => v !== id) : [...selectedIds, id],
  })
  const clearSelection = () => setSelection({ slug: null, ids: [] })
```

Result line: replace

```jsx
      {result && result.pages.includes(series.slug) && (
        <ResultLine key={result.correction.id} correction={result.correction} currentSlug={series.slug} />
      )}
```

with:

```jsx
      {result && result.pages.includes(series.slug) && (result.batch
        ? <BatchResultLine key={result.batch.batch_id} batch={result.batch} currentSlug={series.slug} />
        : <ResultLine key={result.correction.id} correction={result.correction} currentSlug={series.slug} />)}
```

Bar: insert directly above `      <ul aria-label="Books in this series" className="flex flex-col divide-y divide-line">`:

```jsx
      {selectedIds.length > 0 && (
        <BatchBar count={selectedIds.length} onClear={clearSelection}
                  onPick={(kind) => setBatch({ kind, works: selectedWorks })} />
      )}
```

Rows: in the `<BookRow` element inside `groupBySubseries(series.works).map(...)`, add two props after `onAction={…}`:

```jsx
              selected={selectedIds.includes(work.id)}
              onSelect={selectable ? () => toggleSelected(work.id) : undefined}
```

Panel: insert directly after the `{action && ( <LibrarianPanel … /> )}` block:

```jsx
      {batch && (
        <BatchPanel
          batch={{ ...batch, series }}
          onClose={() => setBatch(null)}
          onDone={(out) => {
            setBatch(null)
            clearSelection()
            setResult({ batch: out, pages: [series.slug, ...out.corrections.map((c) => c.room_slug)] })
          }}
        />
      )}
```

- [ ] **Step 5: Run the tests**

Run: `cd frontend && npx vitest run src/pages/Series.test.jsx`
Expected: PASS (all series tests, the 3 new ones included).

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/librarian/BatchBar.jsx frontend/src/components/librarian/BatchResultLine.jsx \
  frontend/src/pages/Series.jsx frontend/src/pages/Series.test.jsx
git commit -m "feat(web): select books on the series page and fix them as one batch, with one undo"
```

---

### Task 8: The fix log offers no single undo on a batch member

Item 11 owns grouping a batch into one row on `/librarian`, and adds the group undo there with `useRevertBatch()`. Until then, a member's row must not offer the single `undo`: the server answers 422 "part of a batch" for it. This task is that guard only. Do not build grouping UI here.

**Files:**
- Modify: `frontend/src/pages/Librarian.jsx` (the `undo` column)
- Test: `frontend/src/pages/Librarian.test.jsx`

**Interfaces:**
- Consumes: `CorrectionOut.batch_id` (Task 1).
- Produces: a row with a non-null `batch_id` renders no `undo` button (a reverted one still shows `undone`). Item 11 replaces this column when it groups batches.

- [ ] **Step 1: Write the failing test**

Append inside `describe('Librarian log', …)` in `frontend/src/pages/Librarian.test.jsx`:

```jsx
  it('offers no single undo on a fix made in a batch', async () => {
    useAuthStore.setState({ token: 't', user: { id: 'u', username: 'ada', is_librarian: true } })
    client.get.mockResolvedValue({ data: [{ ...ROWS[0], batch_id: 'b1' }, { ...ROWS[1], id: 'c0', batch_id: 'b1',
      undoable: false, reverted_at: new Date().toISOString() }] })
    renderPage()
    await screen.findByRole('link', { name: 'Iron Gold' })
    expect(screen.queryByRole('button', { name: 'undo Iron Gold' })).toBeNull()
    expect(screen.getByText('undone')).toBeInTheDocument()
  })
```

- [ ] **Step 2: Run it to make sure it fails**

Run: `cd frontend && npx vitest run src/pages/Librarian.test.jsx`
Expected: FAIL. `expect(element).toBeNull()` receives the `undo Iron Gold` button.

- [ ] **Step 3: Add the guard**

In `frontend/src/pages/Librarian.jsx`, in the `undo` column, change

```jsx
      render: (r) => r.reverted_at ? <span className="text-ink-dim">undone</span> : r.undoable && (
```

to

```jsx
      // A fix made in a batch is undone only with its batch (grouped on this page by item 11).
      render: (r) => r.reverted_at ? <span className="text-ink-dim">undone</span> : r.undoable && !r.batch_id && (
```

(If item 11 has already merged and replaced this column with grouped batch rows, this task is already done. Check that its test for a member row passes and skip to Step 5.)

- [ ] **Step 4: Run the tests**

Run: `cd frontend && npx vitest run src/pages/Librarian.test.jsx`
Expected: 5 passed.

- [ ] **Step 5: Full frontend suite and commit**

Run: `cd frontend && npm test`
Expected: all pass.

```bash
git add frontend/src/pages/Librarian.jsx frontend/src/pages/Librarian.test.jsx
git commit -m "fix(web): the fix log offers no single undo on a batch member"
```

---

### Task 9: Playwright scenario

**Files:**
- Modify: `frontend/e2e/helpers.js` (only if item 03 has not merged)
- Modify: `frontend/e2e/librarian.spec.js`

**Interfaces:**
- Consumes: `ensureEditMode(page)` and `moveFirstResultInto(page, query, saga, { create, position })` from `frontend/e2e/helpers.js`.

- [ ] **Step 1: Make sure the helpers exist**

Run: `grep -n "export async function ensureEditMode\|export async function moveFirstResultInto" frontend/e2e/helpers.js`

If either is missing, append the missing one(s) to `frontend/e2e/helpers.js`. These are the same definitions item 03 adds:

```js
// Edit mode is sticky after roadmap item 01 and per-URL before it: click
// [edit] only when the page is not already in edit mode.
export async function ensureEditMode(page) {
  const done = page.getByRole('link', { name: '[done]' })
  if (!(await done.isVisible())) await page.getByRole('link', { name: '[edit]' }).click()
  await expect(done).toBeVisible()
}

// Opens the first search result for `query` and moves its first book into
// `saga`. `create` names a new series; otherwise `saga` must already exist.
// Leaves the page on the saga's series page. Returns the moved book's title.
export async function moveFirstResultInto(page, query, saga, { create = false, position } = {}) {
  await openFirstSearchResult(page, query)
  await ensureEditMode(page)
  const books = page.getByRole('list', { name: 'Books in this series' })
  const title = (await books.getByRole('heading', { level: 3 }).first().textContent()).trim()
  await books.getByRole('button', { name: `move ${title}`, exact: true }).click()
  await page.getByLabel('Find a series').fill(saga)
  const radio = create
    ? page.getByRole('radio', { name: `new series: ${saga}` })
    : page.getByRole('radio', { name: new RegExp(`^${saga}`) })
  await radio.check()
  if (position != null) await page.getByLabel('Position (optional)').fill(String(position))
  await page.getByLabel('Reason').fill('e2e: building a series')
  await page.getByRole('button', { name: 'Move', exact: true }).click()
  const status = page.getByRole('group', { name: 'Librarian fix result' })
  await expect(status).toBeVisible()
  const heading = page.getByRole('heading', { level: 1, name: saga })
  const follow = status.getByRole('link', { name: /go to its page/ })
  await expect(async () => {
    if (await follow.isVisible()) await follow.click({ timeout: 1000 }).catch(() => {})
    await expect(heading).toBeVisible({ timeout: 1000 })
  }).toPass()
  return title
}
```

- [ ] **Step 2: Write the scenario**

Make sure the import line of `frontend/e2e/librarian.spec.js` reads `import { ensureEditMode, grantLibrarian, moveFirstResultInto, openFirstSearchResult, registerViaUi } from './helpers'`, then append:

```js
// Two books in a new series are numbered in one batch, then the batch is
// undone as one. Needs the full stack and live Open Library.
test('a librarian numbers two books in one batch and undoes the batch', async ({ page }) => {
  const user = await registerViaUi(page)
  grantLibrarian(user)
  await page.reload()

  const saga = `E2E Batch ${Date.now()}`
  await moveFirstResultInto(page, 'the left hand of darkness', saga, { create: true })
  await moveFirstResultInto(page, 'the dispossessed', saga)
  await ensureEditMode(page)

  const books = page.getByRole('list', { name: 'Books in this series' })
  for (const box of await books.getByRole('checkbox', { name: /^select / }).all()) await box.check()
  await page.getByRole('button', { name: 'number 1…n', exact: true }).click()
  await page.getByLabel('Reason').fill('e2e: numbering in one batch')
  await page.getByRole('button', { name: 'Number books', exact: true }).click()

  const status = page.getByRole('group', { name: 'Librarian batch result' })
  await expect(status.getByText('2 fixes')).toBeVisible()
  await expect(books.getByText('#1', { exact: true })).toBeVisible()
  await expect(books.getByText('#2', { exact: true })).toBeVisible()

  await status.getByRole('button', { name: 'undo batch', exact: true }).click()
  await expect(status.getByText('undone')).toBeVisible()
  await expect(books.getByText('#1', { exact: true })).toHaveCount(0)
})
```

- [ ] **Step 3: Run it**

Run (stack up with `docker compose up --build`): `cd frontend && npx playwright test e2e/librarian.spec.js -g "one batch"`
Expected: 1 passed.

- [ ] **Step 4: Commit**

```bash
git add frontend/e2e/helpers.js frontend/e2e/librarian.spec.js
git commit -m "test(e2e): librarian numbers two books as one batch and undoes it"
```

---

### Task 10: Docs and tracker

**Files:**
- Modify: `docs/librarian-ux-roadmap.md`, `ROADMAP.md`, `CLAUDE.md`, and this plan's header

- [ ] **Step 1: §36 check**

On a real series in edit mode, check a few rows. The checkboxes must sit left of the covers without shrinking them. The bar must read as a terminal toolbar (ghost buttons, `N selected`), and the float must match the v1 panel. If the selected state looks like a SaaS dashboard (cards, badges), strip it back to text and rules.

- [ ] **Step 2: Update the docs**

`CLAUDE.md`, backend architecture paragraph: change `` `librarian/` holds the librarian tools (`keys`, `record`, `placement`, `identity`, `undo`, `export`) `` to `` `librarian/` holds the librarian tools (`keys`, `record`, `placement`, `identity`, `undo`, `batch`, `export`) ``. After the sentence ending `…records its override entries and undo snapshot in the op's own transaction.`, add: `` A batch (`batch.apply_batch`) runs several placement ops under one reason in one savepoint and stamps each correction with `batch_id`; a member is undone only with its batch (`revert_batch`, newest first, all or nothing). ``

`CLAUDE.md`, "Known remaining gaps", librarian bullet: append the sentence `Several books can be moved, removed or numbered at once as one batch, undone together.`

`ROADMAP.md`, the **Librarian tools** row: after `…from the series page (`?edit=1`)`, insert `, one at a time or as a batch of checked books (one reason, all or nothing, one undo)`.

`docs/librarian-ux-roadmap.md`: set tracker row 08 to `✅`, with *Done* date and *PR*. Under **Notes**, add:

```markdown
- 2026-09-29 (08): `CorrectionOut.undoable` keeps its v1 meaning for a batch member (it would pass the latest-and-unchanged check); a batch is undoable when every member is. A member's own `POST /corrections/{id}/revert` is 422 "part of a batch" — **item 11's per-book history must offer the batch undo (`POST /batches/{batch_id}/revert`) for a row with `batch_id`, not the single one.** `POST /batches/{id}/revert` answers `BatchOut` (members newest first). A refused batch action's message is prefixed with its book's title (`"<title>: …"`, or `"Fix <n>: …"` for an unknown id). `number 1…n` numbers per sub-series group. Frontend helpers `groupKey`, `renumber`, `positionActions`, `groupBatches` live in `components/librarian/batch.js` (09 reuses them); the float's focus contract is `components/librarian/useDialogFocus.js` (LibrarianPanel still has its own inline copy).
```

In this plan's header, tick `- [x] **Merged** (PR: <link>)`.

- [ ] **Step 3: Commit**

```bash
git add docs/librarian-ux-roadmap.md ROADMAP.md CLAUDE.md docs/superpowers/plans/2026-09-29-lx08-batch-actions.md
git commit -m "docs: roadmap item 08 (batch actions) done"
```

---

## Self-review

- **Spec coverage:** `batch_id uuid null, indexed` (Task 1). `POST /librarian/batch` with a discriminated union `move | position | remove`, the single routes' fields and one reason (Tasks 2 and 4). All-or-nothing (Task 2 savepoint and test). Batch revert newest first, all-or-nothing (Task 3). `CorrectionOut.batch_id` (Task 1). Row checkboxes and a bar offering `move selected…`, `remove selected…`, `number 1…n` (Tasks 6–7). One reason via `ReasonField` (Task 6). The fix log groups a batch into one expandable row (Task 8). 401/403 for new routes (Task 4). Playwright (Task 9). Docs and tracker (Task 10).
- **Placeholders:** none.
- **Type consistency:** `apply_batch(db, user, actions, *, reason) -> (UUID, [CatalogCorrection])` and `revert_batch(db, user, batch_id) -> [CatalogCorrection]` are used identically in Tasks 2–4. `revert_one` is defined in Task 3 and used by `revert_batch`. The frontend `positionActions(orderedWorks, seriesId)` / `renumber(orderedWorks)` / `groupBatches(rows)` are consistent across Tasks 5–8. `BatchPanel`'s `batch = { kind, works, series }` matches Series.jsx's `setBatch({ kind, works })` plus the spread `series`.
- **Review Focus:** each of the five lines has its named test (Tasks 2, 3 and 7).
