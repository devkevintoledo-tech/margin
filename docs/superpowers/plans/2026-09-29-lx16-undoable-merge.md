# Undoable Merge Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A librarian can undo a `merge_works` fix from the result line or the fix log. The revert puts back exactly the rows the merge moved, and it is refused with a 409 that names the reason once anything has touched those rows since.

**Architecture:** The merge op takes a full snapshot of every row `merge_works` is about to touch (`services/librarian/merge_snapshot.py`, captured just before `merge_works`). After the merge and any item-07 `keep` follow-ups it also records how those rows look now. `services/librarian/merge_undo.py` checks the "latest and unchanged since" rule against both halves of the snapshot, then restores editions, threads, shelves, tombstones, the source's room and the survivor's overwritten fields. `undo.revert` / `undo.undoable` dispatch a merge to it. No migration is needed: `catalog_corrections.snapshot` already exists and nullable, and no new op is added.

**Tech Stack:** FastAPI, async SQLAlchemy 2.0, Pydantic v2, pytest + respx, React 18 + React Query, Vitest + RTL, Playwright.

**Spec:** docs/librarian-ux-roadmap.md §16

**Roadmap item:** 16 — tick in docs/librarian-ux-roadmap.md when merged

**Depends on (merged before this starts):**
- **07**: the merge body's `keep`, which records `set_cover` / `set_metadata` follow-ups in the merge's own transaction.
- **08**: batches, whose `BatchAction.kind` is `move | position | remove`.
- **11**: `undo.undoable_ids(db, corrections) -> set[UUID]` in `backend/app/services/librarian/undo.py` is the **single copy of the undo rule**. `undoable(db, c)` is a wrapper over it, and fix-log reads build `CorrectionOut` in `backend/app/services/librarian/log.py` (`find_corrections`, `corrections_out`).

  This plan adds merge undoability *inside* `undoable_ids`, batched with no per-row queries, not as a separate check. It adds `permanent_reason` where `CorrectionOut` is constructed.

Read with the roadmap: `docs/superpowers/specs/2026-09-28-librarian-tools-design.md` §5–§6 (the v1 undo rules this plan extends to merges) and `backend/app/services/works.py` `merge_works` (the function whose effects are snapshotted).

## Global Constraints

- Runs after items **07** and **08** are merged. Branch `feat/librarian-lx16-undoable-merge` from `main`. Commit after each task. Open the PR to `main`.
- Repo rules in `CLAUDE.md` apply as written. `services/librarian/` is the only writer of `catalog_corrections`. `api/` stays thin. Everything is async. Schemas are built explicitly (never `model_validate` of an ORM object with relationships).
- Revert follows v1 §6: only the **latest unreverted** fix on its subject, and only while the current state still equals what the fix left. A failed condition is **409** with the reason as `detail`. An impossible request (a split, or a merge with no snapshot) is **422**. A revert writes no new correction. It sets `reverted_at` / `reverted_by_id`.
- **Split stays permanent.** A merge whose `snapshot` is null (recorded before this item shipped) stays permanent. The UI says so.
- No migration. No new `correction_op_enum` value. No new route, so the existing 401/403 tests in `test_librarian_api.py` still cover `POST /api/librarian/corrections/{id}/revert`.
- Batches (08) never contain a merge. `BatchAction.kind` is `move | position | remove` only. A test pins that.
- Frontend: tokens only. No new radii, shadows, sizes or durations. Every glyph is `aria-hidden`. Serif is used only for book titles.
- Backend tests (from the repo root), referred to below as **`PYTEST`**:
  `docker compose run --rm --no-deps -v "$PWD/pipeline:/pipeline:ro" -e DATABASE_URL=postgresql+asyncpg://margin:margin@db:5432/margin_test backend pytest <args>`
- Frontend unit tests: `cd frontend && npx vitest run <files>`. E2E needs `docker compose up --build` running. Then `cd frontend && npx playwright test <file>`.

## Decisions this plan adds to the roadmap

1. **Snapshot shape (`version: 1`)**, written by `merge_snapshot.capture_merge` / `finish_merge`:
   `releases` (loaded catalog versions) · `source {id, representative_book_id, genre_id}` · `target {id, room, before, after}` where `before`/`after` hold `title, subtitle, description, representative_book_id` · `room {id, retired, works}` (the source's room; `retired` = `absorb_series` tombstoned its singleton; `works` = other works that sat in it) · `editions` (moved) · `target_editions` (the survivor's own) · `threads [{id, before: [series_id, work_id], after: [...]}]` · `shelves {moved: [ids], dropped: [{id, user_id, status, created_at}]}` (dropped = the user had shelved both books, so `merge_works` deleted the source entry) · `repointed` (tombstones that pointed at the source) · `target_tombstones` (works already merged into the survivor) · `memberships` (the source's `series_members` rows) · `follow_ups` (correction ids).
2. **Aliases are not snapshotted.** `merge_works` writes no `work_aliases` row; only the catalog loader does. So a merge touches no alias, and a release loaded since the merge blocks the revert anyway (staleness S5). The roadmap's §16 intent lists aliases. This is where that sentence is honoured.
3. **Follow-ups (07).** Every correction on the target recorded after `merge()` took its row locks, other than the merge itself, is the merge's own `keep` follow-up (`set_cover`, `set_metadata`). The lock is held until commit, so no other fix can interleave. They are listed in `snapshot.follow_ups`. The "latest" check skips them. Revert restores the survivor's `before` fields and marks the follow-ups reverted in the same transaction. This does not depend on how 07 orders its `record()` calls.
4. **"Latest" spans both works.** This is the newest unreverted correction whose `work_id` is the source or the target, excluding follow-ups. A later merge *of the survivor into a third book* has that third book as `work_id`, so it is caught by the survivor-liveness check (S3) instead.
5. **Reader activity since the merge does not block undo**, because nothing in it is ambiguous:
   - New threads started on the survivor stay with the survivor. They were started about the survivor's page.
   - New posts in moved threads travel with their thread.
   - A moved shelf whose status changed moves back with the new status.
   - A moved shelf the reader removed is not given back.
   - New shelves on the survivor stay.

   Blocking on these would let any reader lock a librarian's mistake in place.
8. **Editions enrichment attached since the merge.** `services/enrichment.py` runs on the first view of a series page, which usually happens right after the merge because the librarian lands there. It attaches Google volumes whose `canonical_key(title, author)` is in the work's `identity_keys`, and fills `works.description` when it is empty.

   `books` records neither who attached an edition nor when. It has `source` (`openlibrary` / `google_books`) and `created_at` (insert time, not attach time), and neither says "attached by a librarian". So newcomers are told apart by the snapshot instead: an edition on the survivor at revert time that is in neither `editions` nor `target_editions` arrived after the merge.

   Only two librarian ops move editions. A merge into the survivor is S2/S6. A split only takes editions off (S2, S7). Every newcomer is therefore non-librarian and never blocks. On revert, each newcomer goes to the source if its `canonical_key(title, author)` is in `identity_keys(source)` and not in `identity_keys(target)`. Otherwise it stays on the survivor: it matched the survivor, which is where enrichment attached it, and both books' keys match it equally.
9. **Survivor text after the merge.** For each of `title, subtitle, description`: if the merge changed it (`before != after`, i.e. a `keep` choice) and it still equals `after`, it goes back to `before`. Otherwise it is left as it is now, which keeps a description enrichment filled on a field the merge did not touch. If a merge-changed field no longer equals `after`, only a librarian can have changed it (enrichment only fills an empty description, and `keep: source` left it non-empty). That correction already fails S2.
6. **`CorrectionOut.permanent_reason: str | null`** extends the shared name. It is set for a split (`"Splits are permanent."`) and for a merge with no snapshot (`LEGACY_MERGE`). The log's undo column shows `permanent` with that reason in a `DiagnosticFloat`. Task 1 adds it to the roadmap's Shared names first.
7. **`UNDOABLE` gains `merge_works`.** `undoable_ids()` (item 11's single copy of the rule) partitions merges out and unions in `merge_undo.undoable_merge_ids(db, merges)`. That is batched: one works query and one corrections query for any number of merges. `revert()` sends a merge to `merge_undo.revert_merge` before the generic path. Both exist because the generic "latest on subject" would count the follow-ups, and it only looks at one work.

## Staleness conditions (each is a 409 unless noted, each has a test)

| # | Condition | Reason text (substring the test matches) | Task |
|---|---|---|---|
| S0 | snapshot is null (merged before 16) — **422** | `before merges could be undone` | 2 |
| S1 | already reverted | `already undone` | 2 |
| S2 | a later unreverted fix on either book (follow-ups excluded) | `later fix` | 2 |
| S3 | the survivor was merged away since | `was merged into another book since` | 2 |
| S4 | the source tombstone no longer points at the survivor (revived by a release, or gone) | `changed since this merge` | 2 |
| S5 | a catalog release was loaded since (loaded versions differ) | `catalog release was loaded` | 3 |
| S6 | another book was merged into the survivor since (auto heuristic twin, loader adoption, or librarian) | `Another book was merged into` | 3 |
| S7 | a moved edition is no longer on the survivor | `editions were moved off` | 3 |
| S8 | *Not a blocker.* Editions attached to the survivor since (enrichment, a search ingest) are reassigned on revert by enrichment's own rule (Decision 8). A librarian op that adds editions to the survivor (a merge into it) is already S2/S6, and a split only takes editions off | — (test asserts undo succeeds) | 3 |
| S9 | a moved thread is not where the merge left it | `moved again` | 3 |
| S10 | the survivor's room changed since | `moved to another series` | 3 |
| S11 | the source's old room changed: a retired singleton is no longer tombstoned into the survivor's room, its tombstoned works left, or a real old room was retired or dissolved | `old page or series changed` | 3 |
| S12 | one of the source's `series_members` rows is gone | `membership changed` | 3 |
| S13 | *Not a separate blocker.* A librarian text change after the merge is an unreverted correction on the survivor (07's `set_metadata`, or any other), so S2 refuses it. An enrichment-filled description does not block. Revert restores only fields the merge itself changed, and leaves the rest as they are now (Decision 9) | — (test asserts undo succeeds and keeps the filled description) | 2, 3 |

## Review Focus

1. **The librarian lands on the survivor's page right after merging, so enrichment attaches Google editions and fills a blank description.** Undo still works. Editions titled as the source go back to it, and the filled description stays (Task 3 `test_editions_enrichment_attached_since_go_where_their_title_says`, `test_a_description_enrichment_filled_since_survives_undo`). New threads started on the survivor also stay with it (Task 3 `test_new_threads_on_the_survivor_stay_with_it`).
2. **A reader had both books shelved.** `merge_works` deleted their source entry. Undo gives it back with the same id, status and `created_at`, and leaves their survivor entry alone (Task 2 `test_undo_puts_a_merge_back_exactly`).
3. **A merge recorded before this shipped.** Revert answers 422 and changes nothing. The log shows `permanent` with the reason, not a dead undo button (Task 2 `test_a_merge_without_a_snapshot_stays_permanent`, Task 5, Task 6).
4. **A keep-from-source merge (07).** Undo puts back the survivor's own title, description and cover, and closes the `set_cover` / `set_metadata` follow-ups so they neither export nor keep protecting the cover (Task 4 `test_undo_takes_back_what_keep_copied_from_the_source`).
5. **Undo clicked in two tabs.** The second click is 409 `already undone` and nothing moves twice (Task 2 `test_undo_merge_twice_conflicts`).

---

## File Structure

**Backend — create**
- `backend/app/services/librarian/merge_snapshot.py` — `capture_merge`, `finish_merge`, `values_of`, `place`, `TEXT_FIELDS`, `KEPT_FIELDS`, `SNAPSHOT_VERSION`.
- `backend/app/services/librarian/merge_undo.py` — `LEGACY_MERGE`, `follow_ups`, `latest_on_either`, `undoable_merge_ids`, `revert_merge`.
- `backend/tests/test_librarian_merge_snapshot.py`, `backend/tests/test_librarian_merge_undo.py`.

**Backend — modify**
- `backend/app/services/librarian/identity.py` (snapshot wiring, confirmation message), `backend/app/services/librarian/undo.py` (merges inside `undoable_ids`, revert dispatch, `UNDOABLE`, `permanent_reason`), `backend/app/schemas/librarian.py` + `backend/app/services/librarian/log.py` (`corrections_out`) + `backend/app/api/librarian.py` (`permanent_reason`, wherever `CorrectionOut(` is built).
- `backend/tests/librarian_factories.py` (`make_dune_pair`), `backend/tests/test_librarian_identity.py`, `backend/tests/test_librarian_undo.py`, `backend/tests/test_librarian_api.py`.

**Frontend — create:** `frontend/src/components/librarian/UndoCell.jsx`, `frontend/src/components/librarian/UndoCell.test.jsx`.
**Frontend — modify:** `frontend/src/pages/Librarian.jsx`, `frontend/src/pages/Librarian.test.jsx`, `frontend/src/components/LibrarianPanel.jsx`, `frontend/src/components/LibrarianPanel.test.jsx`, `frontend/e2e/librarian.spec.js`.
**Docs — modify:** `docs/librarian-ux-roadmap.md`, `CLAUDE.md`, `ROADMAP.md`, `docs/superpowers/specs/2026-09-28-librarian-tools-design.md`.

---

### Task 1: The contract, and a merge that records what it moves

**Files:**
- Create: `backend/app/services/librarian/merge_snapshot.py`, `backend/tests/test_librarian_merge_snapshot.py`
- Modify: `docs/librarian-ux-roadmap.md` (Shared names), `backend/app/services/librarian/identity.py`, `backend/tests/librarian_factories.py`, `backend/tests/test_librarian_identity.py`, `backend/tests/test_librarian_api.py`

**Interfaces:**
- Consumes: `merge_works(db, source, target)` (`services/works.py`), `record(...)`, `ids`, `member_state` (`services/librarian/record.py`).
- Produces:
  - `SNAPSHOT_VERSION = 1`; `TEXT_FIELDS = ("title", "subtitle", "description")`; `KEPT_FIELDS = TEXT_FIELDS + ("representative_book_id",)`.
  - `place(series_id, work_id) -> list[str | None]`.
  - `async values_of(db, column, *where) -> list` (ordered by `column`).
  - `async capture_merge(db, source: Work, target: Work) -> dict`.
  - `async finish_merge(db, snapshot: dict, correction: CatalogCorrection, target: Work, started: datetime) -> dict`.
  - Every new merge correction has `snapshot["version"] == 1` in the shape of Decision 1.
  - Test helper `make_dune_pair(db) -> DunePair`, with fields `lib, reader, source, target, room, ghost, s_ed, t_ed, untagged, tagged, kept, dup_src, dup_tgt`.

- [ ] **Step 1: Branch, and update the contract first**

```bash
git checkout main && git pull && git checkout -b feat/librarian-lx16-undoable-merge
```

In `docs/librarian-ux-roadmap.md` "Shared names → Backend", replace the **Undoable merge (16)** bullet with:

```markdown
- **Undoable merge** (16): `merge_works` corrections record a `snapshot`
  (`version: 1`, shape in `services/librarian/merge_snapshot.py`) and join
  `UNDOABLE` (decided inside `undo.undoable_ids`, batched). Revert follows v1's "latest and unchanged since" rule, where
  "latest" spans both works and skips the merge's own `keep` follow-ups (every
  correction on the target recorded inside the merge op, listed in
  `snapshot.follow_ups`); the revert closes those with it. A merge whose
  snapshot is null (recorded before 16) stays permanent. `CorrectionOut` gains
  `permanent_reason: str | null` (a split, a pre-16 merge). Supersedes "Undo
  for merge and split" as a non-goal for merge only; split stays permanent.
```

- [ ] **Step 2: Add the shared test pair to `backend/tests/librarian_factories.py`**

Add `Shelf, ShelfStatus` to the `app.models` import, add `from dataclasses import dataclass` and `from app.services.works import _refresh_work`, then append:

```python
@dataclass
class DunePair:
    lib: User
    reader: User
    source: Work
    target: Work
    room: Series
    ghost: Work
    s_ed: Book
    t_ed: Book
    untagged: Thread
    tagged: Thread
    kept: Shelf
    dup_src: Shelf
    dup_tgt: Shelf


async def make_dune_pair(db) -> DunePair:
    """Brian Herbert's *Dune* on its own page (one edition, an old tombstone,
    an untagged and a tagged thread, a reader's shelf, and a shelf by a
    librarian who also shelved Frank Herbert's) and Frank Herbert's *Dune*."""
    lib, reader = await make_user(db, librarian=True), await make_user(db)
    source = await make_work(db, "Dune", ol_id="OL2W", author="Brian Herbert")
    target = await make_work(db, "Dune", ol_id="OL1W", author="Frank Herbert")
    room = await db.get(Series, source.series_id)
    ghost = await make_work(db, "Dune (1984 printing)", ol_id="OL3W", author="Brian Herbert", series=room)
    ghost.merged_into_id = source.id
    s_ed = await make_edition(db, source, ol_id="OL5M")
    t_ed = await make_edition(db, target, ol_id="OL6M")
    await _refresh_work(db, source)
    await _refresh_work(db, target)
    untagged = await make_thread(db, lib, room, title="Untagged")
    tagged = await make_thread(db, lib, room, source, title="Tagged")
    kept = Shelf(user_id=reader.id, work_id=source.id, status=ShelfStatus.want_to_read)
    dup_src = Shelf(user_id=lib.id, work_id=source.id, status=ShelfStatus.read)
    dup_tgt = Shelf(user_id=lib.id, work_id=target.id, status=ShelfStatus.reading)
    db.add_all([kept, dup_src, dup_tgt])
    await db.flush()
    return DunePair(lib, reader, source, target, room, ghost, s_ed, t_ed, untagged, tagged, kept, dup_src, dup_tgt)
```

- [ ] **Step 3: Write the failing tests**

Create `backend/tests/test_librarian_merge_snapshot.py`:

```python
from app.models import SeriesMember
from app.services.librarian.identity import merge
from app.services.librarian.placement import set_position
from app.services.librarian.record import member_state
from tests.librarian_factories import make_dune_pair, make_member, make_series, make_thread, make_user, make_work


def by_id(rows):
    return sorted(rows, key=lambda r: r["id"])


async def test_a_merge_records_everything_it_moves(db_session):
    p = await make_dune_pair(db_session)
    c = await merge(db_session, p.lib, p.source, p.target, reason="same book", confirm=True)
    s = c.snapshot
    target_room = str(p.target.series_id)

    assert s["version"] == 1 and s["releases"] == [] and s["follow_ups"] == []
    assert s["source"] == {"id": str(p.source.id), "representative_book_id": str(p.s_ed.id), "genre_id": None}
    assert s["target"]["id"] == str(p.target.id) and s["target"]["room"] == target_room
    assert s["target"]["before"] == {"title": "Dune", "subtitle": None, "description": None,
                                     "representative_book_id": str(p.t_ed.id)}
    assert s["target"]["after"]["title"] == "Dune"
    assert s["target"]["after"]["representative_book_id"] in {str(p.s_ed.id), str(p.t_ed.id)}
    assert s["room"] == {"id": str(p.room.id), "retired": True, "works": [str(p.ghost.id)]}
    assert s["editions"] == [str(p.s_ed.id)] and s["target_editions"] == [str(p.t_ed.id)]
    assert by_id(s["threads"]) == by_id([
        {"id": str(p.untagged.id), "before": [str(p.room.id), None], "after": [target_room, str(p.target.id)]},
        {"id": str(p.tagged.id), "before": [str(p.room.id), str(p.source.id)],
         "after": [target_room, str(p.target.id)]},
    ])
    assert s["shelves"]["moved"] == [str(p.kept.id)]
    [dropped] = s["shelves"]["dropped"]
    assert (dropped["id"], dropped["user_id"], dropped["status"]) == (str(p.dup_src.id), str(p.lib.id), "read")
    assert s["repointed"] == [str(p.ghost.id)] and s["target_tombstones"] == []
    assert s["memberships"] == []


async def test_a_merge_out_of_a_real_series_records_the_membership_not_a_retired_room(db_session):
    lib = await make_user(db_session, librarian=True)
    alpha, beta = await make_series(db_session, "Alpha"), await make_series(db_session, "Beta")
    source = await make_work(db_session, "Book X", series=alpha, ol_id="OL1W")
    target = await make_work(db_session, "Book Y", series=beta, ol_id="OL2W")
    member = await make_member(db_session, alpha, source, 1.0)
    await make_member(db_session, beta, target, 1.0)
    await make_thread(db_session, lib, alpha)  # series-wide: not about Book X, never moves
    earlier = await set_position(db_session, lib, beta, target, 2, reason="r")  # before the merge

    c = await merge(db_session, lib, source, target, reason="dup", confirm=True)

    s = c.snapshot
    assert s["room"] == {"id": str(alpha.id), "retired": False, "works": []}
    assert s["threads"] == []
    assert s["memberships"] == [member_state(member)]
    assert s["follow_ups"] == [] and str(earlier.id) not in s["follow_ups"]
    assert await db_session.get(SeriesMember, (alpha.id, source.id)) is not None  # merge_works leaves it
```

In `backend/tests/test_librarian_identity.py::test_merge_asks_first_with_real_counts`, change the assertion `... and c.snapshot is None` to `... and c.snapshot["version"] == 1`.

In `backend/tests/test_librarian_api.py::test_merge_asks_for_confirmation_then_refuses_a_second_merge`, change `assert "cannot be undone" in ask.json()["detail"]["message"]` to:

```python
    assert "can be undone from the fix log" in ask.json()["detail"]["message"]
```

- [ ] **Step 4: Run them to see them fail**

Run: `PYTEST tests/test_librarian_merge_snapshot.py tests/test_librarian_identity.py tests/test_librarian_api.py -q`
Expected: FAIL. `TypeError: 'NoneType' object is not subscriptable` (snapshot is None), and the message assertion fails on `cannot be undone`.

- [ ] **Step 5: Write `backend/app/services/librarian/merge_snapshot.py`**

```python
"""What a merge moved (roadmap item 16), so it can be put back exactly.

``capture_merge`` runs just before ``merge_works`` and reads every row it is
about to touch: editions, the threads ``absorb_series`` carries, shelves
(including the entries it deletes when a reader shelved both books),
tombstones, and the source's room and memberships. ``finish_merge`` runs after
the merge and any ``keep`` follow-ups (item 07). It records what those rows
look like now, which is what ``merge_undo`` checks against. ``merge_works``
writes no ``work_aliases`` rows, so there are none to record.
"""

from datetime import datetime
from uuid import UUID

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Book, CatalogCorrection, CatalogRelease, Series, SeriesKind, SeriesMember, Shelf, Thread, Work,
)
from app.services.librarian.record import ids, member_state

SNAPSHOT_VERSION = 1
# Work fields a merge's `keep` choices (item 07) may overwrite on the survivor.
TEXT_FIELDS = ("title", "subtitle", "description")
KEPT_FIELDS = TEXT_FIELDS + ("representative_book_id",)


def _str(value) -> str | None:
    return str(value) if value is not None else None


def place(series_id, work_id) -> list[str | None]:
    """Where a thread is: its room and its book tag."""
    return [_str(series_id), _str(work_id)]


def _fields(work: Work) -> dict:
    return {name: (_str(getattr(work, name)) if name == "representative_book_id" else getattr(work, name))
            for name in KEPT_FIELDS}


async def values_of(db: AsyncSession, column, *where) -> list:
    return list((await db.execute(select(column).where(*where).order_by(column))).scalars().all())


async def capture_merge(db: AsyncSession, source: Work, target: Work) -> dict:
    room = await db.get(Series, source.series_id)
    # absorb_series only acts across rooms, and only tombstones a singleton.
    retires = source.series_id != target.series_id and room.kind is SeriesKind.singleton
    touched = Thread.work_id == source.id
    if retires:
        touched = or_(touched, and_(Thread.series_id == room.id, Thread.work_id.is_(None)))
    threads = (await db.execute(
        select(Thread.id, Thread.series_id, Thread.work_id).where(touched).order_by(Thread.id))).all()
    shelves = (await db.execute(select(Shelf).where(Shelf.work_id == source.id).order_by(Shelf.id))).scalars().all()
    owners = set(await values_of(db, Shelf.user_id, Shelf.work_id == target.id))
    members = (await db.execute(select(SeriesMember).where(SeriesMember.work_id == source.id)
                                .order_by(SeriesMember.series_id))).scalars().all()
    return {
        "version": SNAPSHOT_VERSION,
        "releases": sorted(await values_of(db, CatalogRelease.version)),
        "source": {"id": str(source.id), "representative_book_id": _str(source.representative_book_id),
                   "genre_id": _str(source.genre_id)},
        "target": {"id": str(target.id), "room": str(target.series_id), "before": _fields(target), "after": None},
        "room": {"id": str(room.id), "retired": retires,
                 "works": ids(await values_of(db, Work.id, Work.series_id == room.id, Work.id != source.id))
                 if retires else []},
        "editions": ids(await values_of(db, Book.id, Book.work_id == source.id)),
        "target_editions": ids(await values_of(db, Book.id, Book.work_id == target.id)),
        "threads": [{"id": str(t.id), "before": place(t.series_id, t.work_id), "after": None} for t in threads],
        # merge_works keeps a user's survivor entry and deletes their source one.
        "shelves": {
            "moved": [str(s.id) for s in shelves if s.user_id not in owners],
            "dropped": [{"id": str(s.id), "user_id": str(s.user_id), "status": s.status.value,
                         "created_at": s.created_at.isoformat()} for s in shelves if s.user_id in owners],
        },
        "repointed": ids(await values_of(db, Work.id, Work.merged_into_id == source.id)),
        "target_tombstones": ids(await values_of(db, Work.id, Work.merged_into_id == target.id)),
        "memberships": [member_state(m) for m in members],
        "follow_ups": [],
    }


async def finish_merge(db: AsyncSession, snapshot: dict, correction: CatalogCorrection, target: Work,
                       started: datetime) -> dict:
    """``started`` is taken right after merge() locks both works. Every other fix
    on the target recorded since then is this merge's own keep follow-up."""
    await db.flush()
    await db.refresh(target)
    wanted = [UUID(t["id"]) for t in snapshot["threads"]]
    now = {str(i): place(s, w) for i, s, w in (await db.execute(
        select(Thread.id, Thread.series_id, Thread.work_id).where(Thread.id.in_(wanted)))).all()}
    follow = await values_of(db, CatalogCorrection.id, CatalogCorrection.work_id == target.id,
                             CatalogCorrection.created_at >= started, CatalogCorrection.id != correction.id)
    return {
        **snapshot,
        "target": {**snapshot["target"], "after": _fields(target)},
        "threads": [{**t, "after": now[t["id"]]} for t in snapshot["threads"]],
        "follow_ups": ids(follow),
    }
```

- [ ] **Step 6: Wire it into `merge()` in `backend/app/services/librarian/identity.py`**

Change the module docstring to `"""Which book is which: merge and split (spec §5.2). A merge can be undone (merge_undo); a split cannot."""`. Add the imports:

```python
from datetime import datetime, timezone

from app.services.librarian.merge_snapshot import capture_merge, finish_merge
```

Make three edits in `merge()`. Leave everything else, including item 07's `keep` handling, where it is.

(a) Directly after `source, target = live_work(source), live_work(target)`:

```python
    # After the locks: any fix recorded on the target from here on is this merge's own (07's keep).
    started = datetime.now(timezone.utc)
```

(b) Replace the confirmation message:

```python
    if not confirm:
        raise NeedsConfirmation(
            f"Merging {source.title} into {target.title} can be undone from the fix log until either book changes.",
            consequences)
```

(c) Capture directly before `await merge_works(db, source, target)`, and finish directly before the function returns. v1's tail was `await merge_works(...)` followed by `return await record(...)`. It becomes:

```python
    before = await capture_merge(db, source, target)
    await merge_works(db, source, target)
    correction = await record(
        db, op=CorrectionOp.merge_works, user=user, reason=reason,
        payload={"source": str(source.id), "target": str(target.id), "consequences": consequences},
        entries=entries, runtime_only_reason=missing, work=target,
        series=await db.get(Series, target.series_id),
    )
    correction.snapshot = await finish_merge(db, before, correction, target, started)
    await db.flush()
    return correction
```

Item 07 changed this tail: its `payload` carries `keep`, and it records `set_cover` / `set_metadata` follow-ups. Keep 07's payload and its follow-up block exactly as merged. Move only the `return` below the new `finish_merge` line, so the follow-ups exist before `finish_merge` looks for them. If 07 records the follow-ups *before* the merge correction, that still works: they carry `created_at >= started`.

- [ ] **Step 7: Run the tests to see them pass**

Run: `PYTEST tests/test_librarian_merge_snapshot.py tests/test_librarian_identity.py tests/test_librarian_api.py -q`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add docs/librarian-ux-roadmap.md backend/app/services/librarian/merge_snapshot.py \
  backend/app/services/librarian/identity.py backend/tests/librarian_factories.py \
  backend/tests/test_librarian_merge_snapshot.py backend/tests/test_librarian_identity.py backend/tests/test_librarian_api.py
git commit -m "feat(librarian): a merge records a full snapshot of what it moves"
```

---

### Task 2: Revert a merge — restore every row

**Files:**
- Create: `backend/app/services/librarian/merge_undo.py`, `backend/tests/test_librarian_merge_undo.py`
- Modify: `backend/app/services/librarian/undo.py`, `backend/tests/test_librarian_undo.py`, `backend/tests/test_librarian_api.py`

**Interfaces:**
- Consumes: `capture_merge` snapshot shape (Task 1), `values_of`, `place`, `TEXT_FIELDS`; `locked`, `uuids` (`record.py`); `_refresh_work` (`services/works.py`).
- Produces:
  - `LEGACY_MERGE: str`, `follow_ups(c) -> list[UUID]`, `async latest_on_either(db, c) -> CatalogCorrection | None`.
  - `async undoable_merge_ids(db, merges: list[CatalogCorrection]) -> set[UUID]` (two queries total), and `async revert_merge(db, user, c) -> None`. The latter does not set `reverted_at`; `undo.revert` does.
  - Consumes from item 11: `undo.undoable_ids(db, corrections) -> set[UUID]` and its wrapper `undo.undoable(db, c) -> bool`.
  - `_require_unchanged(db, s, source, target) -> Series` (Task 3 replaces its body), `_restore(db, s, source, target, room)`, `_restore_survivor(db, s, target)`.
  - `undo.UNDOABLE` includes `CorrectionOp.merge_works`. `undo.permanent_reason(c) -> str | None`.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_librarian_merge_undo.py`:

```python
import pytest
from sqlalchemy import update

from app.models import Book, SeriesMember, Shelf, ShelfStatus, Thread, Work, Series
from app.services.librarian.errors import Conflict, Invalid
from app.services.librarian.export import exportable
from app.services.librarian.identity import merge
from app.services.librarian.placement import set_position
from app.services.librarian.undo import revert, undoable, undoable_ids
from tests.librarian_factories import (
    fresh, make_dune_pair, make_member, make_series, make_thread, make_user, make_work,
)


async def merged(db):
    p = await make_dune_pair(db)
    c = await merge(db, p.lib, p.source, p.target, reason="same book", confirm=True)
    return p, c


async def two_rooms(db):
    lib = await make_user(db, librarian=True)
    alpha, beta = await make_series(db, "Alpha"), await make_series(db, "Beta")
    source = await make_work(db, "Book X", series=alpha, ol_id="OL1W")
    target = await make_work(db, "Book Y", series=beta, ol_id="OL2W")
    await make_member(db, alpha, source, 1.0)
    await make_member(db, beta, target, 1.0)
    return lib, alpha, beta, source, target


async def test_undo_puts_a_merge_back_exactly(db_session):
    p = await make_dune_pair(db_session)
    dropped_at = await fresh(db_session, Shelf.created_at, p.dup_src.id)
    c = await merge(db_session, p.lib, p.source, p.target, reason="same book", confirm=True)
    assert await undoable(db_session, c)

    await revert(db_session, p.lib, c)

    assert c.reverted_at is not None and c.reverted_by_id == p.lib.id
    assert await fresh(db_session, Work.merged_into_id, p.source.id) is None
    assert await fresh(db_session, Work.series_id, p.source.id) == p.room.id
    assert await fresh(db_session, Series.merged_into_id, p.room.id) is None  # its own page again
    assert await fresh(db_session, Work.merged_into_id, p.ghost.id) == p.source.id
    assert await fresh(db_session, Work.series_id, p.ghost.id) == p.room.id
    assert await fresh(db_session, Book.work_id, p.s_ed.id) == p.source.id
    assert await fresh(db_session, Book.work_id, p.t_ed.id) == p.target.id
    assert await fresh(db_session, Thread.series_id, p.untagged.id) == p.room.id
    assert await fresh(db_session, Thread.work_id, p.untagged.id) is None  # untagged again
    assert await fresh(db_session, Thread.series_id, p.tagged.id) == p.room.id
    assert await fresh(db_session, Thread.work_id, p.tagged.id) == p.source.id
    assert await fresh(db_session, Shelf.work_id, p.kept.id) == p.source.id
    back = await db_session.get(Shelf, p.dup_src.id)
    assert (back.user_id, back.work_id, back.status) == (p.lib.id, p.source.id, ShelfStatus.read)
    assert await fresh(db_session, Shelf.created_at, p.dup_src.id) == dropped_at
    assert await fresh(db_session, Shelf.work_id, p.dup_tgt.id) == p.target.id
    assert await fresh(db_session, Work.representative_book_id, p.source.id) == p.s_ed.id
    assert await fresh(db_session, Work.representative_book_id, p.target.id) == p.t_ed.id
    assert not await undoable(db_session, c)


async def test_undo_merge_out_of_a_real_series(db_session):
    lib, alpha, beta, source, target = await two_rooms(db_session)
    about_x = await make_thread(db_session, lib, alpha, source)
    series_wide = await make_thread(db_session, lib, alpha)
    c = await merge(db_session, lib, source, target, reason="dup", confirm=True)
    assert await fresh(db_session, Thread.series_id, about_x.id) == beta.id

    await revert(db_session, lib, c)

    assert await fresh(db_session, Work.series_id, source.id) == alpha.id
    assert (await fresh(db_session, Thread.series_id, about_x.id), await fresh(db_session, Thread.work_id, about_x.id)) \
        == (alpha.id, source.id)
    assert await fresh(db_session, Thread.work_id, series_wide.id) is None
    assert await fresh(db_session, Series.merged_into_id, alpha.id) is None
    assert (await db_session.get(SeriesMember, (alpha.id, source.id))).position == 1.0


async def test_undo_merge_within_one_room(db_session):
    lib = await make_user(db_session, librarian=True)
    alpha = await make_series(db_session, "Alpha")
    source = await make_work(db_session, "Book X", series=alpha, ol_id="OL1W")
    target = await make_work(db_session, "Book X (reissue)", series=alpha, ol_id="OL2W")
    about_x = await make_thread(db_session, lib, alpha, source)
    c = await merge(db_session, lib, source, target, reason="dup", confirm=True)
    assert await fresh(db_session, Thread.work_id, about_x.id) == target.id

    await revert(db_session, lib, c)

    assert await fresh(db_session, Thread.work_id, about_x.id) == source.id
    assert await fresh(db_session, Thread.series_id, about_x.id) == alpha.id
    assert await fresh(db_session, Work.series_id, source.id) == alpha.id


async def test_a_merge_without_a_snapshot_stays_permanent(db_session):
    p, c = await merged(db_session)
    c.snapshot = None  # recorded before item 16 shipped
    await db_session.flush()
    assert not await undoable(db_session, c)
    with pytest.raises(Invalid, match="before merges could be undone"):
        await revert(db_session, p.lib, c)
    assert await fresh(db_session, Work.merged_into_id, p.source.id) == p.target.id


async def test_undo_merge_twice_conflicts(db_session):
    p, c = await merged(db_session)
    await revert(db_session, p.lib, c)
    with pytest.raises(Conflict, match="already undone"):
        await revert(db_session, p.lib, c)
    assert await fresh(db_session, Work.merged_into_id, p.source.id) is None


async def test_a_later_fix_on_the_survivor_blocks_until_it_is_undone(db_session):
    lib, alpha, beta, source, target = await two_rooms(db_session)
    c = await merge(db_session, lib, source, target, reason="dup", confirm=True)
    reorder = await set_position(db_session, lib, beta, target, 3, reason="r")
    assert not await undoable(db_session, c)
    with pytest.raises(Conflict, match="later fix"):
        await revert(db_session, lib, c)
    await revert(db_session, lib, reorder)
    await revert(db_session, lib, c)
    assert await fresh(db_session, Work.merged_into_id, source.id) is None


async def test_fixes_on_the_source_before_the_merge_are_undoable_again(db_session):
    lib, alpha, beta, source, target = await two_rooms(db_session)
    reorder = await set_position(db_session, lib, alpha, source, 5, reason="r")
    c = await merge(db_session, lib, source, target, reason="dup", confirm=True)
    assert not await undoable(db_session, reorder)  # its book is merged away
    await revert(db_session, lib, c)
    assert await undoable(db_session, reorder)
    await revert(db_session, lib, reorder)


async def test_the_survivor_merged_away_since_blocks_undo(db_session):
    p, c = await merged(db_session)
    third = await make_work(db_session, "Dune (omnibus)", ol_id="OL9W", author="Frank Herbert")
    await merge(db_session, p.lib, p.target, third, reason="dup", confirm=True)
    assert not await undoable(db_session, c)
    with pytest.raises(Conflict, match="was merged into another book since"):
        await revert(db_session, p.lib, c)


async def test_a_revived_source_blocks_undo(db_session):
    p, c = await merged(db_session)
    # A release upsert sets merged_into_id = NULL on a work it still holds.
    await db_session.execute(update(Work).where(Work.id == p.source.id).values(merged_into_id=None))
    with pytest.raises(Conflict, match="changed since this merge"):
        await revert(db_session, p.lib, c)


async def test_an_undone_merge_leaves_the_export(db_session):
    lib = await make_user(db_session, librarian=True)
    target = await make_work(db_session, "Target", ol_id="OL1W")
    c = await merge(db_session, lib, await make_work(db_session, "Loser", ol_id="OL2W"), target,
                    reason="dup", confirm=True)
    assert [x.id for x, _ in await exportable(db_session)] == [c.id]
    await revert(db_session, lib, c)
    assert await exportable(db_session) == []


async def test_undoable_ids_answers_for_many_merges_at_once(db_session):
    lib = await make_user(db_session, librarian=True)
    a, b, c, d, e, f, g = [await make_work(db_session, t, ol_id=f"OL{i}W") for i, t in enumerate("ABCDEFG", start=1)]
    open_merge = await merge(db_session, lib, a, b, reason="r", confirm=True)
    legacy = await merge(db_session, lib, c, d, reason="r", confirm=True)
    legacy.snapshot = None
    buried = await merge(db_session, lib, e, f, reason="r", confirm=True)
    later = await merge(db_session, lib, g, f, reason="r", confirm=True)  # a newer fix on buried's survivor
    await db_session.flush()
    assert await undoable_ids(db_session, [open_merge, legacy, buried, later]) == {open_merge.id, later.id}
```

In `backend/tests/test_librarian_undo.py`, delete `test_merge_and_split_cannot_be_undone`. Change the import `from app.services.librarian.identity import merge` to `from app.services.librarian.identity import split`, add `make_edition` to the factories import, and add:

```python
async def test_split_cannot_be_undone(db_session):
    lib = await make_user(db_session, librarian=True)
    work = await make_work(db_session, "Dune", ol_id="OL100W")
    await make_edition(db_session, work, ol_id="OL1M")
    other = await make_edition(db_session, work, ol_id="OL2M", title="Dune Messiah")
    c = await split(db_session, lib, work, [other.id], reason="r", confirm=True)
    with pytest.raises(Invalid, match="Splits cannot be undone"):
        await revert(db_session, lib, c)
```

(If the file still uses `merge` elsewhere after 07/08 landed, keep both imports.)

In `backend/tests/test_librarian_api.py::test_merge_asks_for_confirmation_then_refuses_a_second_merge`, change `done.json()["undoable"] is False` to `done.json()["undoable"] is True`.

- [ ] **Step 2: Run them to see them fail**

Run: `PYTEST tests/test_librarian_merge_undo.py tests/test_librarian_undo.py tests/test_librarian_api.py -q`
Expected: FAIL. `Invalid: Merges and splits cannot be undone.` on every merge revert, and `undoable` is False.

- [ ] **Step 3: Write `backend/app/services/librarian/merge_undo.py`**

```python
"""Undo a merge (roadmap item 16).

Only the latest fix on either book, and only while every row the merge moved is
still where it left them (``merge_snapshot``). Then each row goes back:
editions, threads, shelves, tombstones, the source's room, and whatever the
merge's ``keep`` choices overwrote on the survivor. ``search_doc`` is a
generated column, so the source is searchable again with no further write.
Posts and votes hang off threads, so they travel with them.
"""

from datetime import datetime
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Book, CatalogCorrection, Series, Shelf, ShelfStatus, Thread, User, Work
from app.services.librarian.errors import Conflict, Invalid
from app.services.librarian.merge_snapshot import TEXT_FIELDS
from app.services.librarian.record import locked, uuids
from app.services.work_identity import canonical_key
from app.services.works import _refresh_work, identity_keys

LEGACY_MERGE = "Merged before merges could be undone; this one is permanent."
_STALE = "The books changed since this merge; it can no longer be undone."


def _uuid(value: str | None) -> UUID | None:
    return UUID(value) if value else None


def follow_ups(c: CatalogCorrection) -> list[UUID]:
    return uuids((c.snapshot or {}).get("follow_ups", []))


async def _pair(db: AsyncSession, c: CatalogCorrection) -> tuple[Work | None, Work | None]:
    s = c.snapshot
    return await db.get(Work, UUID(s["source"]["id"])), await db.get(Work, UUID(s["target"]["id"]))


async def latest_on_either(db: AsyncSession, c: CatalogCorrection) -> CatalogCorrection | None:
    """The newest live fix on the source or the survivor, not counting the
    merge's own keep follow-ups."""
    s = c.snapshot
    query = (select(CatalogCorrection).where(
        CatalogCorrection.reverted_at.is_(None),
        CatalogCorrection.work_id.in_([UUID(s["source"]["id"]), UUID(s["target"]["id"])]),
        CatalogCorrection.id.not_in(follow_ups(c)),
    ).order_by(CatalogCorrection.created_at.desc(), CatalogCorrection.id.desc()).limit(1))
    return (await db.execute(query)).scalar_one_or_none()


_GONE = object()


async def undoable_merge_ids(db: AsyncSession, merges: list[CatalogCorrection]) -> set[UUID]:
    """Which of these merges the undo button shows. It takes two queries however
    many merges there are (a fix-log page). revert_merge re-checks everything else."""
    live = [c for c in merges if c.snapshot is not None and c.reverted_at is None]
    if not live:
        return set()
    pairs = {c.id: (UUID(c.snapshot["source"]["id"]), UUID(c.snapshot["target"]["id"])) for c in live}
    work_ids = {w for pair in pairs.values() for w in pair}
    merged_into = dict((await db.execute(
        select(Work.id, Work.merged_into_id).where(Work.id.in_(work_ids)))).all())
    fixes = (await db.execute(select(CatalogCorrection.id, CatalogCorrection.work_id, CatalogCorrection.created_at)
                              .where(CatalogCorrection.reverted_at.is_(None),
                                     CatalogCorrection.work_id.in_(work_ids)))).all()
    undoable = set()
    for c in live:
        source, target = pairs[c.id]
        if merged_into.get(target, _GONE) is not None or merged_into.get(source, _GONE) != target:
            continue  # the survivor is gone or merged away, or the source is no longer its tombstone
        skip = set(follow_ups(c))
        # Same order as latest_on_either: created_at, then id (Postgres and Python order uuids alike).
        newest = max(((f.created_at, f.id) for f in fixes if f.work_id in (source, target) and f.id not in skip),
                     default=None)
        if newest is not None and newest[1] == c.id:
            undoable.add(c.id)
    return undoable


async def revert_merge(db: AsyncSession, user: User, c: CatalogCorrection) -> None:
    if c.snapshot is None:
        raise Invalid(LEGACY_MERGE)
    source, target = await _pair(db, c)
    # Id order, as merge() locks them, so an undo and a new merge cannot deadlock.
    for work in sorted((w for w in (source, target) if w is not None), key=lambda w: w.id):
        await locked(db, work)
    await locked(db, c)
    if c.reverted_at is not None:
        raise Conflict("This fix was already undone.")
    latest = await latest_on_either(db, c)
    if latest is None or latest.id != c.id:
        raise Conflict("A later fix to one of these books came after this merge; undo that first.")
    room = await _require_unchanged(db, c.snapshot, source, target)
    await _restore(db, c.snapshot, source, target, room)


async def _require_unchanged(db: AsyncSession, s: dict, source: Work | None, target: Work | None) -> Series:
    """Refuse (409) unless every row the merge moved is still where it left it.
    Returns the source's old room."""
    if target is None or target.merged_into_id is not None:
        raise Conflict(f"{s['target']['before']['title']} was merged into another book since; undo that merge first.")
    if source is None or source.merged_into_id != target.id:
        raise Conflict(_STALE)
    room = await db.get(Series, UUID(s["room"]["id"]))
    if room is None:
        raise Conflict(_STALE)
    await db.refresh(room)  # retire_series and the loader write series with raw SQL
    return room


async def _restore(db: AsyncSession, s: dict, source: Work, target: Work, room: Series) -> None:
    if s["room"]["retired"]:
        room.merged_into_id = None
        if s["room"]["works"]:
            await db.execute(update(Work).where(Work.id.in_(uuids(s["room"]["works"]))).values(series_id=room.id))
    for t in s["threads"]:
        series_id, work_id = t["before"]
        await db.execute(update(Thread).where(Thread.id == UUID(t["id"]))
                         .values(series_id=_uuid(series_id), work_id=_uuid(work_id)))
    # Editions attached since the merge (enrichment, ingest) go where enrichment's own rule sends them.
    known = set(uuids(s["editions"])) | set(uuids(s["target_editions"]))
    source_keys, target_keys = identity_keys(source), identity_keys(target)
    for book in (await db.execute(select(Book).where(Book.work_id == target.id))).scalars().all():
        key = canonical_key(book.title, book.author)
        if book.id not in known and key in source_keys and key not in target_keys:
            book.work_id = source.id
    if s["editions"]:
        await db.execute(update(Book).where(Book.id.in_(uuids(s["editions"]))).values(work_id=source.id))
    if s["shelves"]["moved"]:
        # A reader who unshelved the book since is not given it back.
        await db.execute(update(Shelf).where(Shelf.id.in_(uuids(s["shelves"]["moved"])), Shelf.work_id == target.id)
                         .values(work_id=source.id))
    for d in s["shelves"]["dropped"]:
        db.add(Shelf(id=UUID(d["id"]), user_id=UUID(d["user_id"]), work_id=source.id,
                     status=ShelfStatus(d["status"]), created_at=datetime.fromisoformat(d["created_at"])))
    if s["repointed"]:
        await db.execute(update(Work).where(Work.id.in_(uuids(s["repointed"]))).values(merged_into_id=source.id))
    source.merged_into_id = None
    source.series_id = room.id
    source.representative_book_id = _uuid(s["source"]["representative_book_id"])
    source.genre_id = _uuid(s["source"]["genre_id"])
    await db.flush()
    await _restore_survivor(db, s, target)


async def _restore_survivor(db: AsyncSession, s: dict, target: Work) -> None:
    """The survivor's own title, description and cover, as they were before.
    Only fields the merge changed (a keep choice) go back. A description
    enrichment filled since, on a field the merge left alone, stays."""
    before, after = s["target"]["before"], s["target"]["after"]
    for name in TEXT_FIELDS:
        if before[name] != after[name] and getattr(target, name) == after[name]:
            setattr(target, name, before[name])
    rep = _uuid(before["representative_book_id"])
    if rep is not None and await db.scalar(select(Book.work_id).where(Book.id == rep)) == target.id:
        target.representative_book_id = rep
    else:
        # It had none, or its own cover edition was split off since: pick again.
        target.representative_book_id = None
        await _refresh_work(db, target)
    await db.flush()
```

- [ ] **Step 4: Dispatch merges in `backend/app/services/librarian/undo.py`**

Add the import and extend `UNDOABLE`. Keep every op 06–08 added to it.

```python
from app.services.librarian.merge_undo import LEGACY_MERGE, revert_merge, undoable_merge_ids
```

```python
UNDOABLE = frozenset({CorrectionOp.set_series, CorrectionOp.set_position, CorrectionOp.rename_series,
                      CorrectionOp.remove_from_series, CorrectionOp.reject_series,
                      CorrectionOp.merge_works})  # a merge only while it has a snapshot (merge_undo)
```

(Keep `CorrectionOp.set_cover` and any other value 06/07 added to the set.)

Add the function:

```python
def permanent_reason(c: CatalogCorrection) -> str | None:
    """Why a fix can never be undone, for the log to say instead of a dead button."""
    if c.op is CorrectionOp.split_work:
        return "Splits are permanent."
    if c.op is CorrectionOp.merge_works and c.snapshot is None:
        return LEGACY_MERGE
    return None
```

Put merges into item 11's `undoable_ids(db, corrections)`, the single copy of the rule. Do not add a check to the `undoable(db, c)` wrapper. Make these the first statements of `undoable_ids`:

```python
    # Merges follow their own rule (both works, keep follow-ups skipped), still batched.
    merges = [c for c in corrections if c.op is CorrectionOp.merge_works]
    corrections = [c for c in corrections if c.op is not CorrectionOp.merge_works]
    merge_ids = await undoable_merge_ids(db, merges)
```

Then make every `return` of `undoable_ids` return its set unioned with `merge_ids`. For example, 11's final `return undoable` becomes `return undoable | merge_ids`, and an early `return set()` for an empty input becomes `return merge_ids`. The generic rule below keeps working on the filtered `corrections` unchanged.

Make the first statements of `revert()`, and replace its "not undoable" message:

```python
    if correction.op is CorrectionOp.merge_works:
        # merge_undo runs its own latest-and-unchanged checks: the generic
        # latest_for_subject would count the merge's keep follow-ups.
        await revert_merge(db, user, correction)
        correction.reverted_at = datetime.now(timezone.utc)
        correction.reverted_by_id = user.id
        await db.flush()
        return correction
    if correction.op not in UNDOABLE:
        raise Invalid("Splits cannot be undone." if correction.op is CorrectionOp.split_work
                      else "This fix cannot be undone.")
```

The rest of `revert()` stays as it is, including anything 08 added.

- [ ] **Step 5: Run the tests to see them pass**

Run: `PYTEST tests/test_librarian_merge_undo.py tests/test_librarian_undo.py tests/test_librarian_api.py tests/test_librarian_hardening.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/librarian/merge_undo.py backend/app/services/librarian/undo.py \
  backend/tests/test_librarian_merge_undo.py backend/tests/test_librarian_undo.py backend/tests/test_librarian_api.py
git commit -m "feat(librarian): undo a merge — editions, threads, shelves, tombstones and the source's room go back"
```

---

### Task 3: Every staleness condition refuses with its reason

**Files:**
- Modify: `backend/app/services/librarian/merge_undo.py` (`_require_unchanged`)
- Test: `backend/tests/test_librarian_merge_undo.py`

**Interfaces:**
- Consumes: `values_of`, `place`, `TEXT_FIELDS` (Task 1), `_require_unchanged` signature (Task 2).
- Produces: `_require_unchanged(db, s, source, target) -> Series` enforcing S3–S7 and S9–S12 in the table's order. Each failure is `Conflict` with the table's text. S8 and S13 are deliberately not checks (Decisions 8–9).

- [ ] **Step 1: Write the failing tests**

Add `Post` to the `app.models` import, and add `from app.services.catalog_loader import load_release, read_release`, `from app.services.works import merge_works`, and `make_edition, make_release` to the factories import. Then append to `backend/tests/test_librarian_merge_undo.py`:

```python
async def test_a_release_loaded_since_blocks_undo(db_session):
    p, c = await merged(db_session)
    await make_release(db_session, "2026.11.1")
    with pytest.raises(Conflict, match="catalog release was loaded"):
        await revert(db_session, p.lib, c)


async def test_a_real_release_load_since_blocks_undo(db_session, write_release):
    p, c = await merged(db_session)
    await load_release(db_session, read_release(write_release("2026.11.1")))
    with pytest.raises(Conflict, match="catalog release was loaded"):
        await revert(db_session, p.lib, c)


async def test_another_book_merged_into_the_survivor_since_blocks_undo(db_session):
    p, c = await merged(db_session)
    twin = await make_work(db_session, "Dune", author="Frank Herbert")  # heuristic
    await merge_works(db_session, twin, p.target)  # _absorb_heuristic_twin does this, with no correction
    with pytest.raises(Conflict, match="Another book was merged into"):
        await revert(db_session, p.lib, c)


async def test_a_moved_edition_taken_off_the_survivor_blocks_undo(db_session):
    p, c = await merged(db_session)
    stray = await make_work(db_session, "Elsewhere", ol_id="OL8W")
    # repair_presentation detaches editions with no correction.
    await db_session.execute(update(Book).where(Book.id == p.s_ed.id).values(work_id=stray.id))
    with pytest.raises(Conflict, match="editions were moved off"):
        await revert(db_session, p.lib, c)


async def test_editions_enrichment_attached_since_go_where_their_title_says(db_session):
    p, c = await merged(db_session)
    # What enrich_work does on the survivor's first view: attach Google volumes by identity key.
    brians = Book(source="google_books", external_id="gBrian1", title="Dune", author="Brian Herbert",
                  language="en", work_id=p.target.id)
    franks = Book(source="google_books", external_id="gFrank1", title="Dune", author="Frank Herbert",
                  language="en", work_id=p.target.id)
    db_session.add_all([brians, franks])
    await db_session.flush()

    await revert(db_session, p.lib, c)

    assert await fresh(db_session, Book.work_id, brians.id) == p.source.id
    assert await fresh(db_session, Book.work_id, franks.id) == p.target.id
    assert await fresh(db_session, Book.work_id, p.s_ed.id) == p.source.id


async def test_a_moved_thread_moved_again_blocks_undo(db_session):
    p, c = await merged(db_session)
    other = await make_series(db_session, "Gamma")
    await db_session.execute(update(Thread).where(Thread.id == p.tagged.id).values(series_id=other.id))
    with pytest.raises(Conflict, match="moved again"):
        await revert(db_session, p.lib, c)


async def test_the_survivor_changing_rooms_blocks_undo(db_session):
    p, c = await merged(db_session)
    saga = await make_series(db_session, "Dune Chronicles")
    # assign_series promotes a singleton with no correction.
    await db_session.execute(update(Work).where(Work.id == p.target.id).values(series_id=saga.id))
    with pytest.raises(Conflict, match="moved to another series"):
        await revert(db_session, p.lib, c)


async def test_a_revived_singleton_blocks_undo(db_session):
    p, c = await merged(db_session)
    await db_session.execute(update(Series).where(Series.id == p.room.id).values(merged_into_id=None))
    with pytest.raises(Conflict, match="old page or series changed"):
        await revert(db_session, p.lib, c)


async def test_a_dissolved_old_series_blocks_undo(db_session):
    from datetime import datetime, timezone
    lib, alpha, beta, source, target = await two_rooms(db_session)
    c = await merge(db_session, lib, source, target, reason="dup", confirm=True)
    await db_session.execute(update(Series).where(Series.id == alpha.id)
                             .values(dissolved_at=datetime.now(timezone.utc)))
    with pytest.raises(Conflict, match="old page or series changed"):
        await revert(db_session, lib, c)


async def test_a_lost_membership_blocks_undo(db_session):
    lib, alpha, beta, source, target = await two_rooms(db_session)
    c = await merge(db_session, lib, source, target, reason="dup", confirm=True)
    await db_session.delete(await db_session.get(SeriesMember, (alpha.id, source.id)))
    await db_session.flush()
    with pytest.raises(Conflict, match="membership changed"):
        await revert(db_session, lib, c)


async def test_a_description_enrichment_filled_since_survives_undo(db_session):
    p, c = await merged(db_session)
    p.target.description = "Filled by enrichment"  # enrich_work fills an empty description
    await db_session.flush()
    await revert(db_session, p.lib, c)
    assert await fresh(db_session, Work.description, p.target.id) == "Filled by enrichment"
    assert await fresh(db_session, Work.merged_into_id, p.source.id) is None


async def test_new_threads_on_the_survivor_stay_with_it(db_session):
    p, c = await merged(db_session)
    survivor_room = await db_session.get(Series, p.target.series_id)
    since = await make_thread(db_session, p.reader, survivor_room, p.target, title="Started after")
    await revert(db_session, p.lib, c)
    assert (await fresh(db_session, Thread.series_id, since.id), await fresh(db_session, Thread.work_id, since.id)) \
        == (survivor_room.id, p.target.id)


async def test_new_posts_travel_with_their_thread(db_session):
    p, c = await merged(db_session)
    post = Post(thread_id=p.tagged.id, user_id=p.reader.id, content="written after the merge")
    db_session.add(post)
    await db_session.flush()
    await revert(db_session, p.lib, c)
    assert await fresh(db_session, Post.thread_id, post.id) == p.tagged.id
    assert await fresh(db_session, Thread.series_id, p.tagged.id) == p.room.id


async def test_reader_shelf_changes_since_are_kept(db_session):
    p, c = await merged(db_session)
    p.kept.status = ShelfStatus.reading  # the reader moved it along
    await db_session.delete(await db_session.get(Shelf, p.dup_tgt.id))  # the librarian unshelved theirs
    await db_session.flush()
    await revert(db_session, p.lib, c)
    assert await fresh(db_session, Shelf.status, p.kept.id) == ShelfStatus.reading
    assert await fresh(db_session, Shelf.work_id, p.kept.id) == p.source.id
    assert await fresh(db_session, Shelf.work_id, p.dup_src.id) == p.source.id  # their source entry is back


async def test_a_moved_shelf_removed_since_is_not_given_back(db_session):
    p, c = await merged(db_session)
    await db_session.delete(await db_session.get(Shelf, p.kept.id))
    await db_session.flush()
    await revert(db_session, p.lib, c)
    assert await db_session.get(Shelf, p.kept.id) is None
```

`Post` belongs in the module-level `app.models` import, not inside a test.

- [ ] **Step 2: Run them to see them fail**

Run: `PYTEST tests/test_librarian_merge_undo.py -q`
Expected: the nine staleness tests (release ×2, merged-in, edition off, thread, room, singleton, dissolved, membership) FAIL with `DID NOT RAISE <class '...Conflict'>`. The six non-blocking tests (enrichment editions, enrichment description, new threads, posts, shelf changes, removed shelf) pass already, because Task 2's `_restore` / `_restore_survivor` hold those rules.

- [ ] **Step 3: Replace `_require_unchanged` in `merge_undo.py`**

Add `CatalogRelease, SeriesMember` to the `app.models` import and `values_of, place` to the `merge_snapshot` import. Replace the whole function with:

```python
async def _require_unchanged(db: AsyncSession, s: dict, source: Work | None, target: Work | None) -> Series:
    """Refuse (409) unless every row the merge moved is still where it left it.
    Returns the source's old room. Checks run cheapest first."""
    # S3, S4: both books are still the pair the merge made.
    if target is None or target.merged_into_id is not None:
        raise Conflict(f"{s['target']['before']['title']} was merged into another book since; undo that merge first.")
    if source is None or source.merged_into_id != target.id:
        raise Conflict(_STALE)
    # S5: a release adopts, re-rooms, aliases and revives rows wholesale.
    if sorted(await values_of(db, CatalogRelease.version)) != s["releases"]:
        raise Conflict("A catalog release was loaded since this merge; fix the books by hand instead.")
    # S6: an automatic or librarian merge into the survivor since.
    expected = {source.id, *uuids(s["repointed"]), *uuids(s["target_tombstones"])}
    if set(await values_of(db, Work.id, Work.merged_into_id == target.id)) != expected:
        raise Conflict(f"Another book was merged into {target.title} since; undoing would leave it half-separated.")
    # S10: the survivor's room.
    target_room = UUID(s["target"]["room"])
    if target.series_id != target_room:
        raise Conflict(f"{target.title} moved to another series since; move it back first.")
    # S11: the source's old room.
    room = await db.get(Series, UUID(s["room"]["id"]))
    if room is None:
        raise Conflict(_STALE)
    await db.refresh(room)  # retire_series and the loader write series with raw SQL
    changed = f"{source.title}'s old page or series changed since the merge."
    if s["room"]["retired"]:
        if room.merged_into_id != target_room:
            raise Conflict(changed)
        if s["room"]["works"] and set(await values_of(
                db, Work.series_id, Work.id.in_(uuids(s["room"]["works"])))) != {target_room}:
            raise Conflict(changed)
    elif room.merged_into_id is not None or room.dissolved_at is not None:
        raise Conflict(changed)
    # S12: the source's memberships (merge_works never touches them).
    for m in s["memberships"]:
        if await db.get(SeriesMember, (UUID(m["series_id"]), UUID(m["work_id"]))) is None:
            raise Conflict(f"{source.title}'s series membership changed since the merge.")
    # S7: every moved edition is still on the survivor. Newcomers do not block (S8, Decision 8).
    now = set(await values_of(db, Book.id, Book.work_id == target.id))
    if not set(uuids(s["editions"])) <= now:
        raise Conflict(f"Some of {source.title}'s editions were moved off {target.title} since.")
    # S9: every thread the merge moved is where it left it.
    wanted = {t["id"]: t["after"] for t in s["threads"]}
    if wanted:
        rows = (await db.execute(select(Thread.id, Thread.series_id, Thread.work_id)
                                 .where(Thread.id.in_(uuids(wanted))))).all()
        if {str(i): place(se, w) for i, se, w in rows} != wanted:
            raise Conflict("A thread that moved with the merge was moved again since.")
    # S13 is no check: a librarian text change is a correction on the survivor (S2),
    # and enrichment's filled description is kept by _restore_survivor (Decision 9).
    return room
```

- [ ] **Step 4: Run the tests to see them pass**

Run: `PYTEST tests/test_librarian_merge_undo.py tests/test_librarian_undo.py tests/test_librarian_hardening.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/librarian/merge_undo.py backend/tests/test_librarian_merge_undo.py
git commit -m "feat(librarian): merge undo refuses once a release, a merge, an edition, a thread, a room or an edit moved since"
```

---

### Task 4: Undo takes back the merge's `keep` follow-ups; batches carry no merge

**Files:**
- Modify: `backend/app/services/librarian/merge_undo.py` (`_close_follow_ups`, `revert_merge`)
- Test: `backend/tests/test_librarian_merge_undo.py`

**Interfaces:**
- Consumes: item 07's merge body `keep: {title, cover, description}` and ops `CorrectionOp.set_cover` / `CorrectionOp.set_metadata`. Item 08's `POST /api/librarian/batch {reason, actions: [BatchAction]}`. `follow_ups(c)` (Task 2).
- Produces: `_close_follow_ups(db, user, c)`. It runs *before* `_restore`, so 06's "leave a work with an unreverted `set_cover` alone" rule no longer protects the survivor when `_refresh_work` re-picks its cover.

- [ ] **Step 1: Write the failing tests**

Add `import uuid`, `import httpx`, `import respx`, `from sqlalchemy import select`, `CatalogCorrection, CorrectionOp` to the `app.models` import, `from app.services.works import _refresh_work`, and `headers_for` to the factories import. Then append:

```python
@respx.mock
async def test_undo_takes_back_what_keep_copied_from_the_source(client, db_session):
    # set_cover may verify the cover URL (covers.verify); never hit the network.
    respx.route(host="covers.example").mock(
        return_value=httpx.Response(200, headers={"content-type": "image/jpeg"}, content=b"\xff\xd8"))
    librarian = await make_user(db_session, librarian=True)
    lib = headers_for(librarian)
    source = await make_work(db_session, "Dune: Special Edition", ol_id="OL2W", author="Frank Herbert")
    target = await make_work(db_session, "Dune", ol_id="OL1W", author="Frank Herbert")
    source.description, target.description = "The source's blurb", "The survivor's blurb"
    s_ed = await make_edition(db_session, source, ol_id="OL5M")
    t_ed = await make_edition(db_session, target, ol_id="OL6M")
    s_ed.cover_url, t_ed.cover_url = "https://covers.example/s.jpg", "https://covers.example/t.jpg"
    await _refresh_work(db_session, source)
    await _refresh_work(db_session, target)
    await db_session.flush()

    resp = await client.post(f"/api/librarian/works/{source.id}/merge", headers=lib, json={
        "into_work_id": str(target.id), "reason": "same book", "confirm": True,
        "keep": {"title": "source", "cover": "source", "description": "source"}})
    assert resp.status_code == 201, resp.text
    merge_fix = (await db_session.execute(select(CatalogCorrection).where(
        CatalogCorrection.op == CorrectionOp.merge_works))).scalar_one()
    extra = (await db_session.execute(select(CatalogCorrection).where(
        CatalogCorrection.op.in_((CorrectionOp.set_cover, CorrectionOp.set_metadata)),
        CatalogCorrection.work_id == target.id))).scalars().all()
    assert extra and {str(e.id) for e in extra} == set(merge_fix.snapshot["follow_ups"])
    assert await fresh(db_session, Work.title, target.id) == "Dune: Special Edition"

    undone = await client.post(f"/api/librarian/corrections/{merge_fix.id}/revert", headers=lib)

    assert undone.status_code == 200, undone.text
    assert await fresh(db_session, Work.title, target.id) == "Dune"
    assert await fresh(db_session, Work.description, target.id) == "The survivor's blurb"
    assert await fresh(db_session, Work.representative_book_id, target.id) == t_ed.id
    assert await fresh(db_session, Work.representative_book_id, source.id) == s_ed.id
    for e in extra:
        assert await fresh(db_session, CatalogCorrection.reverted_at, e.id) is not None
        assert await fresh(db_session, CatalogCorrection.reverted_by_id, e.id) == librarian.id


async def test_a_batch_cannot_carry_a_merge(client, db_session):
    lib = headers_for(await make_user(db_session, librarian=True))
    a = await make_work(db_session, "A", ol_id="OL1W")
    b = await make_work(db_session, "B", ol_id="OL2W")
    resp = await client.post("/api/librarian/batch", headers=lib, json={
        "reason": "r", "actions": [{"kind": "merge", "work_id": str(a.id), "into_work_id": str(b.id)}]})
    assert resp.status_code == 422
    assert await fresh(db_session, Work.merged_into_id, a.id) is None
```

- [ ] **Step 2: Run them to see them fail**

Run: `PYTEST tests/test_librarian_merge_undo.py -q -k "keep or batch"`
Expected: `test_undo_takes_back_what_keep_copied_from_the_source` FAILS on `reverted_at is not None` (the follow-ups stay live). It may also fail on the representative assertion, if 06's rule kept `_refresh_work` away while a `set_cover` is live. `test_a_batch_cannot_carry_a_merge` PASSES already, because 08's discriminated union rejects `kind: merge`. It stays as the guard.

- [ ] **Step 3: Close the follow-ups in `merge_undo.py`**

Add `from datetime import timezone` next to `datetime`, then add:

```python
async def _close_follow_ups(db: AsyncSession, user: User, c: CatalogCorrection) -> None:
    """The survivor's keep-from-source fixes (item 07) were part of the merge.
    _restore_survivor undoes their effect. Closing them here means they neither
    export nor keep protecting the survivor's cover. A follow-up someone
    already undid on its own stays as it is."""
    wanted = follow_ups(c)
    if wanted:
        await db.execute(update(CatalogCorrection).where(
            CatalogCorrection.id.in_(wanted), CatalogCorrection.reverted_at.is_(None),
        ).values(reverted_at=datetime.now(timezone.utc), reverted_by_id=user.id))
```

In `revert_merge`, call it between the checks and the restore:

```python
    room = await _require_unchanged(db, c.snapshot, source, target)
    await _close_follow_ups(db, user, c)
    await _restore(db, c.snapshot, source, target, room)
```

- [ ] **Step 4: Run the tests to see them pass**

Run: `PYTEST tests/test_librarian_merge_undo.py tests/test_librarian_merge_snapshot.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/librarian/merge_undo.py backend/tests/test_librarian_merge_undo.py
git commit -m "feat(librarian): undoing a merge closes its keep follow-ups; batches never carry a merge"
```

---

### Task 5: The API says which fixes are permanent

**Files:**
- Modify: `backend/app/schemas/librarian.py`, `backend/app/services/librarian/log.py` (item 11's `corrections_out`), `backend/app/api/librarian.py` (any remaining `CorrectionOut(` site)
- Test: `backend/tests/test_librarian_api.py`

**Interfaces:**
- Consumes: `undo.permanent_reason(c)` (Task 2).
- Produces: `CorrectionOut.permanent_reason: str | None` on every route that returns `CorrectionOut` (writes, `GET /corrections`, revert, and 08's `BatchOut.corrections`).

- [ ] **Step 1: Write the failing tests**

Add `from sqlalchemy import update` and `from app.models import CatalogCorrection` to `backend/tests/test_librarian_api.py`, then append:

```python
async def test_a_merge_is_undone_through_the_log_and_its_book_comes_back(client, db_session):
    lib = headers_for(await make_user(db_session, librarian=True))
    source = await make_work(db_session, "Dune", ol_id="OL2W", author="Brian Herbert")
    target = await make_work(db_session, "Dune", ol_id="OL1W", author="Frank Herbert")
    source_slug = (await db_session.get(Series, source.series_id)).slug
    done = (await client.post(f"/api/librarian/works/{source.id}/merge", headers=lib, json={
        "into_work_id": str(target.id), "reason": "same", "confirm": True})).json()
    assert done["undoable"] is True and done["permanent_reason"] is None

    undone = await client.post(f"/api/librarian/corrections/{done['id']}/revert", headers=lib)

    assert undone.status_code == 200, undone.text
    assert undone.json()["reverted_at"] is not None and undone.json()["undoable"] is False
    page = (await client.get(f"/api/series/{source_slug}")).json()
    assert [w["author"] for w in page["works"]] == ["Brian Herbert"]


async def test_a_merge_from_before_undo_existed_is_permanent(client, db_session):
    lib = headers_for(await make_user(db_session, librarian=True))
    source = await make_work(db_session, "A", ol_id="OL2W")
    target = await make_work(db_session, "B", ol_id="OL1W")
    done = (await client.post(f"/api/librarian/works/{source.id}/merge", headers=lib, json={
        "into_work_id": str(target.id), "reason": "same", "confirm": True})).json()
    await db_session.execute(update(CatalogCorrection).where(CatalogCorrection.id == uuid.UUID(done["id"]))
                             .values(snapshot=None))
    db_session.expire_all()

    [row] = (await client.get("/api/librarian/corrections", headers=lib)).json()
    assert row["undoable"] is False and "before merges could be undone" in row["permanent_reason"]
    refused = await client.post(f"/api/librarian/corrections/{done['id']}/revert", headers=lib)
    assert refused.status_code == 422 and "before merges could be undone" in refused.json()["detail"]


async def test_a_split_says_it_is_permanent(client, db_session):
    lib = headers_for(await make_user(db_session, librarian=True))
    work = await make_work(db_session, "Dune", ol_id="OL100W")
    await make_edition(db_session, work, ol_id="OL1M")
    messiah = await make_edition(db_session, work, ol_id="OL2M", title="Dune Messiah")
    out = (await client.post(f"/api/librarian/works/{work.id}/split", headers=lib, json={
        "edition_ids": [str(messiah.id)], "reason": "sequel", "confirm": True})).json()
    assert out["undoable"] is False and out["permanent_reason"] == "Splits are permanent."
```

- [ ] **Step 2: Run them to see them fail**

Run: `PYTEST tests/test_librarian_api.py -q`
Expected: FAIL with `KeyError: 'permanent_reason'`.

- [ ] **Step 3: Add the field**

In `backend/app/schemas/librarian.py`, `CorrectionOut`, after `undoable: bool`:

```python
    permanent_reason: str | None = None  # why this fix can never be undone (a split, a pre-undo merge)
```

Pass the field wherever a `CorrectionOut` is built. After item 11 that is `services/librarian/log.py::corrections_out`, plus `api/librarian.py::correction_out` if 11 kept one for single writes. Find every site with:

```bash
grep -rn "CorrectionOut(" backend/app
```

In each file, add `permanent_reason` to its import from `app.services.librarian.undo`. In each `CorrectionOut(...)` call, add the keyword next to `undoable=`. For example, in `corrections_out`, where 11 computes `undoable = await undoable_ids(db, rows)` once for the page:

```python
            undoable=c.id in undoable, permanent_reason=permanent_reason(c),
```

`permanent_reason` is pure (no query), so the page stays batched.

- [ ] **Step 4: Run the tests to see them pass**

Run: `PYTEST tests/test_librarian_api.py tests/test_openapi.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/schemas/librarian.py backend/app/services/librarian/log.py backend/app/api/librarian.py backend/tests/test_librarian_api.py
git commit -m "feat(librarian): CorrectionOut says why a fix is permanent"
```

---

### Task 6: Frontend — undo a merge, and say when one is permanent

**Files:**
- Create: `frontend/src/components/librarian/UndoCell.jsx`, `frontend/src/components/librarian/UndoCell.test.jsx`
- Modify: `frontend/src/pages/Librarian.jsx`, `frontend/src/pages/Librarian.test.jsx`, `frontend/src/components/LibrarianPanel.jsx`, `frontend/src/components/LibrarianPanel.test.jsx`

**Interfaces:**
- Consumes: `CorrectionOut.permanent_reason`, `undoable`, `reverted_at`, `subject` (Task 5); `useRevertCorrection` (`api/librarian.js`); `DiagnosticFloat`.
- Produces: `<UndoCell row={CorrectionOut} onUndo={(id) => …} pending={bool} />`. The series page's `ResultLine` needs no change: it already shows `undo` whenever `undoable` is true, which a merge now is.

- [ ] **Step 1: Write the failing tests**

Create `frontend/src/components/librarian/UndoCell.test.jsx`:

```jsx
import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import UndoCell from './UndoCell'

const ROW = { id: 'c1', subject: 'Dune', undoable: false, reverted_at: null, permanent_reason: null }

describe('UndoCell', () => {
  it('offers undo when the server allows it', async () => {
    const onUndo = vi.fn()
    render(<UndoCell row={{ ...ROW, undoable: true }} onUndo={onUndo} pending={false} />)
    await userEvent.click(screen.getByRole('button', { name: 'undo Dune' }))
    expect(onUndo).toHaveBeenCalledWith('c1')
  })

  it('says a fix was undone', () => {
    render(<UndoCell row={{ ...ROW, reverted_at: '2026-09-29T00:00:00Z' }} onUndo={vi.fn()} pending={false} />)
    expect(screen.getByText('undone')).toBeInTheDocument()
  })

  it('says why a merge from before undo existed is permanent', () => {
    render(<UndoCell row={{ ...ROW, permanent_reason: 'Merged before merges could be undone; this one is permanent.' }}
                     onUndo={vi.fn()} pending={false} />)
    expect(screen.getByText('permanent')).toBeInTheDocument()
    expect(screen.getByRole('tooltip')).toHaveTextContent('Merged before merges could be undone')
    expect(screen.queryByRole('button', { name: /undo/ })).not.toBeInTheDocument()
  })

  it('renders nothing for a fix that is simply no longer the latest', () => {
    const { container } = render(<UndoCell row={ROW} onUndo={vi.fn()} pending={false} />)
    expect(container).toBeEmptyDOMElement()
  })
})
```

In `frontend/src/pages/Librarian.test.jsx`, give `ROWS[1]` (the `merge_works` row) `permanent_reason: 'Merged before merges could be undone; this one is permanent.'`, add `permanent_reason: null` to `ROWS[0]`, and add:

```jsx
  it('marks a permanent merge instead of offering undo', async () => {
    useAuthStore.setState({ token: 't', user: { id: 'u', username: 'ada', is_librarian: true } })
    renderPage()
    expect(await screen.findByText('permanent')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'undo Dune' })).not.toBeInTheDocument()
  })
```

In `frontend/src/components/LibrarianPanel.test.jsx`, `confirms a merge with the counts the server returned`, change the mocked message to `'Merging Dune into Dune can be undone from the fix log until either book changes.'`. Replace `expect(screen.getByText(/This cannot be undone/)).toBeInTheDocument()` with:

```jsx
    expect(screen.getByText(/Undo stays in the fix log until either book changes/)).toBeInTheDocument()
    expect(screen.queryByText(/This cannot be undone/)).not.toBeInTheDocument()
```

- [ ] **Step 2: Run them to see them fail**

Run: `cd frontend && npx vitest run src/components/librarian/UndoCell.test.jsx src/pages/Librarian.test.jsx src/components/LibrarianPanel.test.jsx`
Expected: FAIL. `Failed to resolve import "./UndoCell"`, `Unable to find an element with the text: permanent`, and the merge copy assertion fails.

- [ ] **Step 3: Write `frontend/src/components/librarian/UndoCell.jsx`**

```jsx
import DiagnosticFloat from '../DiagnosticFloat'

/** The fix log's last column: undone, an undo button, or why it never can be. */
function UndoCell({ row, onUndo, pending }) {
  if (row.reverted_at) return <span className="text-ink-dim">undone</span>
  if (row.undoable) {
    return (
      <button type="button" className="btn-ghost text-xs" aria-label={`undo ${row.subject}`}
              disabled={pending} onClick={() => onUndo(row.id)}>
        undo
      </button>
    )
  }
  if (row.permanent_reason) {
    return (
      <DiagnosticFloat severity="hint" message={row.permanent_reason} align="end">
        <span className="text-ink-dim">permanent</span>
      </DiagnosticFloat>
    )
  }
  return null
}

export default UndoCell
```

- [ ] **Step 4: Use it in the log, and fix the merge confirmation copy**

In `frontend/src/pages/Librarian.jsx`, import `UndoCell from '../components/librarian/UndoCell'` and replace the `undo` column with:

```jsx
    { key: 'undo', label: '', width: 10,
      render: (r) => <UndoCell row={r} onUndo={(id) => revert.mutate(id)} pending={revert.isPending} /> },
```

If item 11's per-book history float renders its own undo control, find it with `grep -rn "revert.mutate" frontend/src` and render `<UndoCell row={…} onUndo={…} pending={…} />` there in the same way.

In `frontend/src/components/LibrarianPanel.jsx`, `Consequences`, merge branch: replace

```jsx
        <span className="text-danger">This cannot be undone.</span>
```

with

```jsx
        <span className="text-ink-dim">Undo stays in the fix log until either book changes.</span>
```

Leave the split branch's `This cannot be undone.` alone. If item 04/07 moved the merge confirmation line into another component, find it with `grep -rn "cannot be undone" frontend/src` (the merge occurrence) and make the same replacement there.

- [ ] **Step 5: Run the tests to see them pass**

Run: `cd frontend && npx vitest run src/components/librarian/UndoCell.test.jsx src/pages/Librarian.test.jsx src/components/LibrarianPanel.test.jsx src/pages/Series.test.jsx src/design/tokens.test.js`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/librarian/UndoCell.jsx frontend/src/components/librarian/UndoCell.test.jsx \
  frontend/src/pages/Librarian.jsx frontend/src/pages/Librarian.test.jsx \
  frontend/src/components/LibrarianPanel.jsx frontend/src/components/LibrarianPanel.test.jsx
git commit -m "feat(web): merges can be undone from the result line and the log; permanent fixes say why"
```

---

### Task 7: End-to-end — merge a book and undo it

**Files:**
- Modify: `frontend/e2e/librarian.spec.js`

**Interfaces:**
- Consumes: `registerViaUi`, `grantLibrarian`, `openFirstSearchResult` (`e2e/helpers.js`); row button `merge into… <title>`; panel labels `Find the book to keep`, `Reason`, buttons `Merge` / `Confirm merge`; result group `Librarian fix result`.

- [ ] **Step 1: Write the scenario**

Append to `frontend/e2e/librarian.spec.js`:

```js
const escapeRegExp = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')

// A librarian merges one book of a series into another, sees it leave the
// list, undoes the merge from the result line, and the book is back.
// Needs the full stack and live Open Library.
test('a librarian merges two books and undoes it', async ({ page }) => {
  const user = await registerViaUi(page)
  grantLibrarian(user)
  await page.reload()

  await openFirstSearchResult(page, 'red rising')
  await page.getByRole('link', { name: '[edit]' }).click()
  const books = page.getByRole('list', { name: 'Books in this series' })
  const titles = await books.getByRole('heading').allTextContents()
  test.skip(titles.length < 2, 'the first result opened a single book')
  const [loser, keeper] = titles

  await books.getByRole('button', { name: `merge into… ${loser}`, exact: true }).click()
  await page.getByLabel('Find the book to keep').fill(keeper)
  await page.getByRole('radio', { name: new RegExp(escapeRegExp(keeper)) }).first().check()
  await page.getByLabel('Reason', { exact: true }).fill('e2e: checking merge undo')
  await page.getByRole('button', { name: 'Merge', exact: true }).click()
  await expect(page.getByText(/Undo stays in the fix log/)).toBeVisible()
  await page.getByRole('button', { name: 'Confirm merge' }).click()

  const status = page.getByRole('group', { name: 'Librarian fix result' })
  await expect(status).toBeVisible()
  await expect(books.getByRole('heading', { name: loser, exact: true })).toHaveCount(0)

  await status.getByRole('button', { name: 'undo' }).click()
  await expect(status.getByText('undone')).toBeVisible()
  await expect(books.getByRole('heading', { name: loser, exact: true })).toBeVisible()
})
```

If item 04 renamed the merge panel's controls (the picker label, the submit, or a preview step before `Confirm merge`), use 04's names. The flow is the same.

- [ ] **Step 2: Run it**

Run (stack up via `docker compose up --build`): `cd frontend && npx playwright test e2e/librarian.spec.js -g "merges two books"`
Expected: `1 passed`, or `1 skipped` if the search's first result is a single book.

- [ ] **Step 3: Commit**

```bash
git add frontend/e2e/librarian.spec.js
git commit -m "test(e2e): a librarian merges two books and undoes it"
```

---

### Task 8: Docs and the tracker

**Files:**
- Modify: `CLAUDE.md`, `ROADMAP.md`, `docs/librarian-ux-roadmap.md`, `docs/superpowers/specs/2026-09-28-librarian-tools-design.md`

- [ ] **Step 1: Write them**

- `CLAUDE.md`, Known remaining gaps: replace `Merge and split cannot be undone, and there is no role system beyond the flag.` with:
  `A merge can be undone from the fix log while neither book has changed since (services/librarian/merge_undo.py lists the conditions; merges recorded before that shipped stay permanent). Split cannot be undone, and there is no role system beyond the flag.`
  In the backend `services/` paragraph, change the `librarian/` module list `(keys, record, placement, identity, undo, export)` to `(keys, record, placement, identity, merge_snapshot, merge_undo, undo, export)`.
- `ROADMAP.md`, the **Librarian tools** row: change `undoable (except merge/split)` to `undoable (except split; a merge while neither book changed since)`.
- `docs/superpowers/specs/2026-09-28-librarian-tools-design.md` §2 Non-goals: after `- Undo for merge and split.`, add ` Superseded for merge by docs/librarian-ux-roadmap.md §16; split stays permanent.`
- `docs/librarian-ux-roadmap.md`:
  - Tracker row 16: Status `✅`, Branch `feat/librarian-lx16-undoable-merge`, Done = the merge date, PR = the PR link. Fill these once the PR is merged.
  - Under **Notes**, add:
    `- 2026-09-29 (16): merge undo skips only the reader activity that is unambiguous — new threads and shelves on the survivor stay with it, a reader's unshelve since wins; editions and a description enrichment adds after the merge never block (newcomers are reassigned by enrichment's own identity-key rule, and only fields the merge changed are restored). Aliases are not snapshotted because merge_works writes none; a release loaded since blocks the undo instead. \`keep\` follow-ups are found as "every fix on the target recorded inside the merge op", so 07 needs no id link.`
  - In this plan's header, tick the roadmap item.

- [ ] **Step 2: Verify everything, then commit**

Run `PYTEST -q -p no:warnings`, then `cd frontend && npm test && npm run build`.
Expected: all green.

```bash
git add CLAUDE.md ROADMAP.md docs/librarian-ux-roadmap.md docs/superpowers/specs/2026-09-28-librarian-tools-design.md \
  docs/superpowers/plans/2026-09-29-lx16-undoable-merge.md
git commit -m "docs: merges can be undone (roadmap item 16)"
```

---

## Self-review

- **Coverage.** Roadmap §16 is covered as follows:
  - Snapshot: Task 1.
  - Exact restore, un-tombstoning, room and membership: Task 2.
  - Staleness with a 409 reason each: Tasks 2–3.
  - The export drops the entry: Task 2 `test_an_undone_merge_leaves_the_export`.
  - Pre-16 merges permanent, and said so in the UI: Tasks 2, 5 and 6.
  - 07's follow-ups: Task 4.
  - 08 carries no merges: Task 4.
  - CLAUDE.md and the tracker row: Task 8.
- **Routine activity must not block undo.** The revision of S8 and S13 checked every writer that runs after a merge without a correction:
  - enrichment (editions, description);
  - search ingest (editions via `canonical_work`);
  - `repair_presentation` (detaches editions, which is S7);
  - reader threads, posts and shelves (Decision 5).

  Only the edition detach and the non-librarian room, thread and tombstone changes in S4–S12 block. Each of those leaves the merge's own rows somewhere a revert cannot safely reach.
- **Names.** These are identical across tasks: `capture_merge` / `finish_merge` / `values_of` / `place` / `TEXT_FIELDS`, `follow_ups` / `latest_on_either` / `undoable_merge_ids` / `revert_merge` / `_require_unchanged` / `_restore` / `_restore_survivor` / `_close_follow_ups`, `permanent_reason`, `LEGACY_MERGE`, and `make_dune_pair`.
- **Placeholders.** There are none. Where 04, 07, 08 or 11 own the surrounding code, the step names the grep that finds it and the exact edit to make.
