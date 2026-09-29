# Side-by-side Merge Preview Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Before a librarian confirms a merge, show both books side by side (cover, title, author, year, series, editions, threads, shelves, blurb) with a `swap` control that decides which one survives.

**Architecture:** A read-only route `GET /api/librarian/works/{id}/merge-preview?into={id}` asks a new service function, `services/librarian/identity.merge_preview`. That function renders each side through `load_work_presentation`, the same fallback ladder the series page and search cards use. It takes the move counts from `merge_consequences`, which is pulled out of `merge` so the preview and the 422 confirmation cannot disagree. On the frontend, `components/librarian/MergePreview.jsx` renders a `MergePreviewOut`. The merge panel shows it as soon as the other book is picked, and a `swapped` flag in the panel's fields flips which id is the path's source and which is `into_work_id`. The two-step 422 → `confirm: true` contract does not change.

**Tech Stack:** FastAPI, async SQLAlchemy 2.0, Pydantic v2, React 18 + React Query + Tailwind tokens, Vitest + RTL, Playwright.

**Spec:** docs/librarian-ux-roadmap.md §04 (Shared names → Frontend `MergePreview`, Backend **Merge preview**). The v1 merge it wraps is `docs/superpowers/specs/2026-09-28-librarian-tools-design.md` §5.2.

**Roadmap item:** 04 — tick in docs/librarian-ux-roadmap.md when merged

- [x] **Merged** (PR: #18, date: 2026-09-29)

## Global Constraints

- Names are binding, verbatim from the roadmap: `GET /api/librarian/works/{id}/merge-preview?into={id}` → `MergePreviewOut {source: MergeSide, target: MergeSide, threads, shelves, editions}`, `MergeSide {id, title, author, first_publish_year, cover_url, description, edition_count, thread_count, shelf_count, series_slug, series_name}`. The component is `components/librarian/MergePreview.jsx`, `<MergePreview preview={MergePreviewOut} onSwap={() => …} />`. Items 05, 07 and 14 import it.
- The preview "refuses self/merged exactly like merge": the same `Invalid("A book cannot merge into itself.")` → 422 and `Conflict("<title> was merged into another book; reload the page.")` → 409, and 404 for an unknown id (the route's `_work`).
- `cover_url`, `description` and `edition_count` come from `load_work_presentation` (`backend/app/services/works.py`), never a raw column. Cover is the representative edition's, then OL's curated image, then null. Description is the representative edition's, then the work's. Edition count is OL's total, then the local row count.
- `threads`/`shelves`/`editions` at the top level equal the `consequences` dict the merge's 422 returns for the same direction. Both come from `merge_consequences`.
- The route depends on `require_librarian`: 401 anonymous, 403 reader. The test module asserts both.
- The preview is a read. It writes no `catalog_corrections` row and takes no `FOR UPDATE` lock.
- Existing merge contract is unchanged: `POST /works/{id}/merge {into_work_id, reason, confirm}`, 422 with `detail.consequences` without `confirm`, 201 `CorrectionOut` with it.
- Frontend: tokens only. No new radii, shadows, font sizes or durations. Serif only for book titles. Every glyph is `aria-hidden`, and this plan adds none (the swap control is the word `swap`). `danger` labels the book that merges away, `ok` the survivor, and each label is also written out as text.
- `PYTEST` means, from the repo root: `docker compose run --rm --no-deps -v "$PWD/pipeline:/pipeline:ro" -e DATABASE_URL=postgresql+asyncpg://margin:margin@db:5432/margin_test backend pytest` (with `docker compose up -d db` running and `margin_test` created once, see `CLAUDE.md`).
- Branch `feat/librarian-lx04-merge-preview` from `main`, one commit per task, PR to `main`.

## Review Focus

1. **The picked book was merged away (by another librarian, or by search's heuristic→OL absorb) between picking and confirming.** The preview answers 409. The panel shows that message and keeps `Merge` disabled, so no 422/confirm round-trip starts on a dead pair. Test: Task 4 `refuses to go on when the preview says a book is gone`.
2. **Swapping after the server already answered with counts.** Those counts describe the other direction. The confirm step must drop back to the form, and the next submit must post the swapped ids. Test: Task 4 `swapping after the counts came back asks again`.
3. **A search-ingested work with zero editions on one side** (the common case for a duplicate found in search). Its cover must be OL's curated one, its edition count OL's total, and its blurb the work's. The side with editions must use its representative edition's cover and blurb even when the work row also has an OL cover and description. Test: Task 1 `test_sides_use_the_page_fallback_ladder_not_raw_columns`.
4. **Two books with identical title and author** (the typical duplicate). The sides must still be distinguishable and addressable: each is a region named by its role (`merges away: Dune` / `survives: Dune`) and shows year, series, and counts. Test: Task 3 `labels each side by its role, not only by colour`.
5. **Picking a different book after swapping.** The swap must reset, so the newly picked book is the one kept, and the preview must be fetched for the new pair. A swap that silently carried over would merge the wrong way. Test: Task 4 `picking another book resets the swap`.

---

## File Structure

**Backend — modify**
- `backend/app/schemas/librarian.py` — add `MergeSide`, `MergePreviewOut`.
- `backend/app/services/librarian/identity.py` — extract `merge_consequences`; add `_distinct`, `_side`, `merge_preview`; `merge` uses the first two.
- `backend/app/services/librarian/__init__.py` — re-export `merge_preview`.
- `backend/app/api/librarian.py` — the `GET /works/{work_id}/merge-preview` route.
- `backend/tests/test_librarian_api.py` — add the route to `READS`.

**Backend — create**
- `backend/tests/test_librarian_merge_preview.py` — service and route tests.

**Frontend — create**
- `frontend/src/components/librarian/MergePreview.jsx` — the two-sided view (first file in `components/librarian/` if items 01–03 have not landed yet).
- `frontend/src/components/librarian/MergePreview.test.jsx`.

**Frontend — modify**
- `frontend/src/api/librarian.js` — `useMergePreview(sourceId, intoId)`.
- `frontend/src/components/LibrarianPanel.jsx` — `swapped` field, `mergeSides`, `PreviewSlot`, preview in both merge steps.
- `frontend/src/components/LibrarianPanel.test.jsx` — URL-aware GET mock for merge tests; new merge-preview tests.
- `frontend/e2e/librarian.spec.js` — one scenario: preview and swap from the series page.

**Docs — modify:** `docs/librarian-ux-roadmap.md`, `ROADMAP.md`, `CLAUDE.md`.

---

### Task 1: `merge_preview` service and its schemas

**Files:**
- Modify: `backend/app/schemas/librarian.py` (append after `EditionOut`)
- Modify: `backend/app/services/librarian/identity.py:1-50`
- Modify: `backend/app/services/librarian/__init__.py:6`
- Test: `backend/tests/test_librarian_merge_preview.py`

**Interfaces:**
- Consumes: `load_work_presentation(db, work_ids) -> dict[UUID, WorkPresentation]` and `WorkPresentation(cover_url, description, edition_count, series)` from `app.services.works`. Also `live_work` from `record.py`, and `_count` and `Invalid` already in `identity.py`.
- Produces:
  - `app.schemas.librarian.MergeSide`, `app.schemas.librarian.MergePreviewOut` (fields exactly as in Global Constraints).
  - `app.services.librarian.identity.merge_consequences(db, source: Work, target: Work) -> dict[str, int]` with keys `threads`, `shelves`, `editions`.
  - `app.services.librarian.merge_preview(db, source: Work, target: Work) -> MergePreviewOut`. Raises `Invalid` (self) and `Conflict` (either side tombstoned).

- [ ] **Step 1: Start the item**

```bash
git checkout main && git pull
git checkout -b feat/librarian-lx04-merge-preview
```

In `docs/librarian-ux-roadmap.md`, change row 04 of the Tracker to status `🟡` and set Branch to `feat/librarian-lx04-merge-preview`. It is committed with this task.

- [ ] **Step 2: Write the failing service tests**

Create `backend/tests/test_librarian_merge_preview.py`:

```python
import pytest
from sqlalchemy import func, select

from app.models import CatalogCorrection, Series, Shelf, ShelfStatus, Work
from app.services.librarian import merge_preview
from app.services.librarian.errors import Conflict, Invalid, NeedsConfirmation
from app.services.librarian.identity import merge
from app.services.open_library import cover_url as ol_cover_url
from tests.librarian_factories import (
    fresh, headers_for, make_edition, make_member, make_series, make_thread, make_user, make_work,
)

R = "2026.10.1"


async def _duplicate_pair(db):
    """Brian Herbert's *Dune* (a singleton, two editions, threads, a shelf) and
    Frank Herbert's *Dune* (in a real series, no editions: ingested from search)."""
    lib = await make_user(db, librarian=True)
    source = await make_work(db, "Dune", ol_id="OL2W", author="Brian Herbert")
    best = await make_edition(db, source, ol_id="OL5M")
    await make_edition(db, source)
    best.cover_url, best.description = "https://books.example/dune-en.jpg", "Google's richer blurb."
    source.representative_book_id = best.id
    # Present on the row, but the ladder must prefer the representative edition.
    source.ol_cover_id, source.description = 111, "OL's short blurb."
    room = await db.get(Series, source.series_id)
    await make_thread(db, lib, room)  # untagged, in the singleton: about this book
    await make_thread(db, lib, room, source)
    db.add(Shelf(user_id=lib.id, work_id=source.id, status=ShelfStatus.read))

    saga = await make_series(db, "Dune Saga", release=R)
    target = await make_work(db, "Dune", ol_id="OL1W", author="Frank Herbert", series=saga)
    await make_member(db, saga, target, 1.0)
    target.first_publish_year, target.ol_cover_id, target.ol_edition_count = 1965, 8231856, 26
    target.description = "Set on the desert planet Arrakis."
    await make_thread(db, lib, saga, target)
    await db.flush()
    return lib, source, target, room, saga


async def test_sides_use_the_page_fallback_ladder_not_raw_columns(db_session):
    _, source, target, room, saga = await _duplicate_pair(db_session)
    out = await merge_preview(db_session, source, target)

    assert out.source.id == source.id and out.target.id == target.id
    # Representative edition first, even though the row has an OL cover and blurb.
    assert out.source.cover_url == "https://books.example/dune-en.jpg"
    assert out.source.description == "Google's richer blurb."
    assert out.source.edition_count == 2  # no OL total on this row, so the local count
    # No editions at all: OL's curated cover, the work's blurb, OL's total.
    assert out.target.cover_url == ol_cover_url(8231856)
    assert out.target.description == "Set on the desert planet Arrakis."
    assert out.target.edition_count == 26
    assert (out.target.author, out.target.first_publish_year) == ("Frank Herbert", 1965)


async def test_sides_name_their_page_and_count_what_is_about_them(db_session):
    _, source, target, room, saga = await _duplicate_pair(db_session)
    out = await merge_preview(db_session, source, target)

    # A singleton is the book's own page: a slug to link, no series name to show.
    assert (out.source.series_slug, out.source.series_name) == (room.slug, None)
    assert (out.target.series_slug, out.target.series_name) == (saga.slug, "Dune Saga")
    assert (out.source.thread_count, out.source.shelf_count) == (2, 1)
    assert (out.target.thread_count, out.target.shelf_count) == (1, 0)


async def test_preview_counts_are_the_confirmation_counts_and_nothing_changes(db_session):
    lib, source, target, *_ = await _duplicate_pair(db_session)
    out = await merge_preview(db_session, source, target)
    assert (out.threads, out.shelves, out.editions) == (2, 1, 2)

    with pytest.raises(NeedsConfirmation) as asked:
        await merge(db_session, lib, source, target, reason="same book")
    assert asked.value.consequences == {"threads": out.threads, "shelves": out.shelves, "editions": out.editions}
    assert await fresh(db_session, Work.merged_into_id, source.id) is None
    assert await db_session.scalar(select(func.count()).select_from(CatalogCorrection)) == 0


async def test_swapping_the_arguments_swaps_the_sides(db_session):
    _, source, target, *_ = await _duplicate_pair(db_session)
    out = await merge_preview(db_session, target, source)
    assert (out.source.id, out.target.id) == (target.id, source.id)
    # Frank Herbert's Dune moving: its one tagged thread, no shelves, no local editions.
    assert (out.threads, out.shelves, out.editions) == (1, 0, 0)


async def test_preview_refuses_what_merge_refuses(db_session):
    lib = await make_user(db_session, librarian=True)
    a = await make_work(db_session, "A", ol_id="OL1W")
    b = await make_work(db_session, "B", ol_id="OL2W")
    c = await make_work(db_session, "C", ol_id="OL3W")
    with pytest.raises(Invalid, match="itself"):
        await merge_preview(db_session, a, a)
    await merge(db_session, lib, a, b, reason="r", confirm=True)
    with pytest.raises(Conflict, match="merged"):
        await merge_preview(db_session, a, c)
    with pytest.raises(Conflict, match="merged"):
        await merge_preview(db_session, c, a)
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `PYTEST tests/test_librarian_merge_preview.py -v`
Expected: collection error `ImportError: cannot import name 'merge_preview' from 'app.services.librarian'`.

- [ ] **Step 4: Add the schemas**

Append to `backend/app/schemas/librarian.py`:

```python
class MergeSide(BaseModel):
    """One book in a merge preview, shown the way its own page shows it."""

    id: UUID
    title: str
    author: str
    first_publish_year: int | None = None
    # load_work_presentation's ladder, never a raw column: the representative
    # edition's cover, then OL's curated image; its blurb, then the work's.
    cover_url: str | None = None
    description: str | None = None
    # OL's total, then local rows: the number a search card shows for this book.
    edition_count: int = 0
    # Threads about this book: tagged with it, plus a singleton room's untagged ones.
    thread_count: int = 0
    shelf_count: int = 0
    series_slug: str | None = None  # the book's page
    series_name: str | None = None  # null for a singleton, which has no series chrome


class MergePreviewOut(BaseModel):
    source: MergeSide  # merges away
    target: MergeSide  # survives
    # What the merge moves: the numbers its 422 confirmation states.
    threads: int
    shelves: int
    editions: int
```

- [ ] **Step 5: Extract `merge_consequences`, add `merge_preview`**

In `backend/app/services/librarian/identity.py`, replace the imports and the `merge` function (lines 1–50) with:

```python
"""Which book is which: merge and split (spec §5.2). Neither can be undone."""

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Book, CatalogCorrection, CorrectionOp, Series, SeriesKind, Shelf, Thread, User, Work, WorkProvenance, WorkSource,
)
from app.schemas.librarian import MergePreviewOut, MergeSide
from app.services.librarian.errors import Conflict, Invalid, NeedsConfirmation, NotFound
from app.services.librarian.keys import edition_key, exported, work_key
from app.services.librarian.placement import _override_member
from app.services.librarian.record import clean_reason, ids, live_work, locked, record
from app.services.work_identity import canonical_key, display_title, heuristic_external_id
from app.services.works import (
    WorkPresentation, _refresh_work, edition_rank, identity_keys, load_work_presentation, merge_works,
)


async def _count(db: AsyncSession, model, *conditions) -> int:
    return await db.scalar(select(func.count()).select_from(model).where(*conditions)) or 0


def _distinct(source: Work | None, target: Work | None) -> None:
    if source is not None and target is not None and source.id == target.id:
        raise Invalid("A book cannot merge into itself.")


async def merge_consequences(db: AsyncSession, source: Work, target: Work) -> dict[str, int]:
    """What folding ``source`` into ``target`` moves. The confirmation and the
    preview both read it, so the two can never disagree."""
    room = await db.get(Series, source.series_id)
    moving_threads = await _count(db, Thread, Thread.work_id == source.id)
    if room.kind is SeriesKind.singleton and room.id != target.series_id:
        # absorb_series tags a singleton's untagged threads with the book and carries them.
        moving_threads += await _count(db, Thread, Thread.series_id == room.id, Thread.work_id.is_(None))
    return {
        "threads": moving_threads,
        "shelves": await _count(db, Shelf, Shelf.work_id == source.id),
        "editions": await _count(db, Book, Book.work_id == source.id),
    }


async def _side(db: AsyncSession, work: Work, shown: WorkPresentation) -> MergeSide:
    room = await db.get(Series, work.series_id)
    threads = await _count(db, Thread, Thread.work_id == work.id)
    if room.kind is SeriesKind.singleton:
        threads += await _count(db, Thread, Thread.series_id == room.id, Thread.work_id.is_(None))
    return MergeSide(
        id=work.id, title=work.title, author=work.author, first_publish_year=work.first_publish_year,
        cover_url=shown.cover_url, description=shown.description, edition_count=shown.edition_count,
        thread_count=threads, shelf_count=await _count(db, Shelf, Shelf.work_id == work.id),
        series_slug=room.slug, series_name=room.name if room.kind is SeriesKind.series else None,
    )


async def merge_preview(db: AsyncSession, source: Work, target: Work) -> MergePreviewOut:
    """What merging ``source`` into ``target`` would do, without doing it: both
    books as their pages render them, and the counts the confirmation states.
    Refuses exactly what ``merge`` refuses. A read: no lock, no correction."""
    _distinct(source, target)
    source, target = live_work(source), live_work(target)
    shown = await load_work_presentation(db, [source.id, target.id])
    return MergePreviewOut(
        source=await _side(db, source, shown[source.id]),
        target=await _side(db, target, shown[target.id]),
        **await merge_consequences(db, source, target),
    )


async def merge(db: AsyncSession, user: User, source: Work, target: Work, *, reason: str,
                confirm: bool = False) -> CatalogCorrection:
    reason = clean_reason(reason)
    _distinct(source, target)
    for work in sorted((w for w in (source, target) if w is not None), key=lambda w: w.id):
        await locked(db, work)  # id order, so two opposite merges cannot deadlock
    source, target = live_work(source), live_work(target)
    consequences = await merge_consequences(db, source, target)
    if not confirm:
        raise NeedsConfirmation(f"Merging {source.title} into {target.title} cannot be undone.", consequences)
    entries, missing = exported(lambda: [{"merge_works": [work_key(target), work_key(source)]}])
    await merge_works(db, source, target)
    return await record(
        db, op=CorrectionOp.merge_works, user=user, reason=reason,
        payload={"source": str(source.id), "target": str(target.id), "consequences": consequences},
        entries=entries, runtime_only_reason=missing, work=target,
        series=await db.get(Series, target.series_id),
    )
```

`split` and everything below it stay as they are.

In `backend/app/services/librarian/__init__.py`, change line 6 to:

```python
from app.services.librarian.identity import merge, merge_preview, split  # noqa: E402,F401
```

- [ ] **Step 6: Run the new tests and the v1 identity tests**

Run: `PYTEST tests/test_librarian_merge_preview.py tests/test_librarian_identity.py -v`
Expected: all PASS. That includes the unchanged `test_merge_asks_first_with_real_counts` and `test_merge_refusals`, which prove the extraction kept `merge` identical.

- [ ] **Step 7: Commit**

```bash
git add backend/app/schemas/librarian.py backend/app/services/librarian/identity.py \
        backend/app/services/librarian/__init__.py backend/tests/test_librarian_merge_preview.py \
        docs/librarian-ux-roadmap.md
git commit -m "feat(librarian): merge_preview renders both books through the page ladder, shares merge's counts"
```

---

### Task 2: The merge-preview route

**Files:**
- Modify: `backend/app/api/librarian.py:11-13` (import), and add the route after `merge_work` (after line 69)
- Modify: `backend/tests/test_librarian_api.py:22` (`READS`)
- Test: `backend/tests/test_librarian_merge_preview.py` (append)

**Interfaces:**
- Consumes: `librarian.merge_preview` and `MergePreviewOut` (Task 1). Also `_work`, `_run` and `require_librarian`, already in the module.
- Produces: `GET /api/librarian/works/{work_id}/merge-preview?into={uuid}` → 200 `MergePreviewOut`. It answers 401 anonymous, 403 reader, 404 unknown id, 409 tombstoned side, 422 self (string `detail`, no `consequences`) and 422 for a missing `into`. Tasks 3–5 call it.

- [ ] **Step 1: Write the failing route tests**

Append to `backend/tests/test_librarian_merge_preview.py`:

```python
def _path(source_id, into_id):
    return f"/api/librarian/works/{source_id}/merge-preview?into={into_id}"


async def test_route_refuses_anonymous_and_readers(client, db_session):
    a = await make_work(db_session, "A", ol_id="OL1W")
    b = await make_work(db_session, "B", ol_id="OL2W")
    # HTTPBearer answers a missing header with 401 or 403 depending on the FastAPI
    # version; the v1 permission test accepts both for the same reason.
    assert (await client.get(_path(a.id, b.id))).status_code in (401, 403)
    reader = headers_for(await make_user(db_session))
    assert (await client.get(_path(a.id, b.id), headers=reader)).status_code == 403


async def test_route_answers_the_preview(client, db_session):
    lib, source, target, room, saga = await _duplicate_pair(db_session)
    resp = await client.get(_path(source.id, target.id), headers=headers_for(lib))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert set(body) == {"source", "target", "threads", "shelves", "editions"}
    assert set(body["source"]) == {
        "id", "title", "author", "first_publish_year", "cover_url", "description", "edition_count",
        "thread_count", "shelf_count", "series_slug", "series_name"}
    assert body["target"]["id"] == str(target.id) and body["target"]["series_name"] == "Dune Saga"
    assert (body["threads"], body["shelves"], body["editions"]) == (2, 1, 2)

    swapped = (await client.get(_path(target.id, source.id), headers=headers_for(lib))).json()
    assert (swapped["source"]["id"], swapped["target"]["id"]) == (str(target.id), str(source.id))


async def test_route_refusals_match_merge(client, db_session):
    librarian = await make_user(db_session, librarian=True)
    lib = headers_for(librarian)
    a = await make_work(db_session, "A", ol_id="OL1W")
    b = await make_work(db_session, "B", ol_id="OL2W")
    c = await make_work(db_session, "C", ol_id="OL3W")
    ANY = "00000000-0000-0000-0000-000000000000"

    assert (await client.get(_path(ANY, b.id), headers=lib)).status_code == 404
    assert (await client.get(_path(a.id, ANY), headers=lib)).status_code == 404
    self_merge = await client.get(_path(a.id, a.id), headers=lib)
    assert self_merge.status_code == 422 and "itself" in self_merge.json()["detail"]
    missing_into = await client.get(f"/api/librarian/works/{a.id}/merge-preview", headers=lib)
    assert missing_into.status_code == 422

    await merge(db_session, librarian, a, b, reason="r", confirm=True)
    assert (await client.get(_path(a.id, c.id), headers=lib)).status_code == 409
    assert (await client.get(_path(c.id, a.id), headers=lib)).status_code == 409
```

In `backend/tests/test_librarian_api.py`, replace the `READS` line with:

```python
READS = ["/api/librarian/corrections", "/api/librarian/series-search?q=a", f"/api/librarian/works/{ANY}/editions",
         f"/api/librarian/works/{ANY}/merge-preview?into={ANY}"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `PYTEST tests/test_librarian_merge_preview.py -k route tests/test_librarian_api.py::test_every_route_refuses_readers_and_anonymous -v`
Expected: FAIL. The new route tests get `404` where they expect `401`/`403`/`200`/`409`, and the READS loop fails on the merge-preview path with `assert 404 == 403`.

- [ ] **Step 3: Add the route**

In `backend/app/api/librarian.py`, extend the schema import:

```python
from app.schemas.librarian import (
    CorrectionOut, DissolveIn, EditionOut, MergeIn, MergePreviewOut, MoveIn, PositionIn, RemoveIn, RenameIn,
    SeriesHit, SplitIn,
)
```

and add this route directly after `merge_work`:

```python
@router.get("/works/{work_id}/merge-preview", response_model=MergePreviewOut)
async def preview_merge(work_id: UUID, into: UUID = Query(...), db: AsyncSession = Depends(get_db),
                        user: User = Depends(require_librarian)):
    """Both books as their pages show them, and what merging ``work_id`` into
    ``into`` would move. Swapping the two ids swaps the survivor."""
    source, target = await _work(db, work_id), await _work(db, into)
    return await _run(librarian.merge_preview(db, source, target))
```

- [ ] **Step 4: Run the librarian suites**

Run: `PYTEST tests/test_librarian_merge_preview.py tests/test_librarian_api.py tests/test_librarian_permissions.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/librarian.py backend/tests/test_librarian_merge_preview.py backend/tests/test_librarian_api.py
git commit -m "feat(librarian): GET works/{id}/merge-preview?into= for librarians"
```

---

### Task 3: `useMergePreview` and the `MergePreview` component

**Files:**
- Modify: `frontend/src/api/librarian.js` (append)
- Create: `frontend/src/components/librarian/MergePreview.jsx`
- Test: `frontend/src/components/librarian/MergePreview.test.jsx`

**Interfaces:**
- Consumes: the route from Task 2.
- Produces:
  - `useMergePreview(sourceId, intoId)` in `api/librarian.js`. It is a React Query `useQuery` with key `['librarian', 'merge-preview', sourceId, intoId]`, enabled only when both ids are set, and `retry: false`, because a 409/422 is an answer and not a blip.
  - `export default function MergePreview({ preview, onSwap })`. `preview` is a `MergePreviewOut`. `onSwap` is optional; when it is absent no swap control renders (item 14's compact rows can omit it). It renders `role="group"` named `Merge preview`, with two `<section>` regions named `merges away: <title>` and `survives: <title>`, and a button whose accessible name is `swap which book survives`.

- [ ] **Step 1: Write the failing component tests**

Create `frontend/src/components/librarian/MergePreview.test.jsx`:

```jsx
import { describe, it, expect, vi } from 'vitest'
import { fireEvent, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import MergePreview from './MergePreview'

const side = (over) => ({
  id: 'w1', title: 'Dune', author: 'Brian Herbert', first_publish_year: 1999, cover_url: null,
  description: null, edition_count: 2, thread_count: 2, shelf_count: 1, series_slug: 'dune-b1',
  series_name: null, ...over,
})
const PREVIEW = {
  source: side({}),
  target: side({ id: 'w2', author: 'Frank Herbert', first_publish_year: 1965, cover_url: 'https://x/dune.jpg',
                 description: 'Set on the desert planet Arrakis.', edition_count: 26, thread_count: 3,
                 shelf_count: 0, series_slug: 'dune', series_name: 'Dune Saga' }),
  threads: 2, shelves: 1, editions: 2,
}

describe('MergePreview', () => {
  it('labels each side by its role, not only by colour', () => {
    render(<MergePreview preview={PREVIEW} onSwap={vi.fn()} />)
    const group = screen.getByRole('group', { name: 'Merge preview' })
    const away = within(group).getByRole('region', { name: 'merges away: Dune' })
    const kept = within(group).getByRole('region', { name: 'survives: Dune' })
    expect(within(away).getByText('merges away')).toBeInTheDocument()
    expect(within(away).getByText('Brian Herbert')).toBeInTheDocument()
    expect(within(away).getByText('1999')).toBeInTheDocument()
    expect(within(kept).getByText('Frank Herbert')).toBeInTheDocument()
    expect(within(kept).getByText('1965')).toBeInTheDocument()
  })

  it('shows what each book carries: editions, threads, shelves, series, blurb', () => {
    render(<MergePreview preview={PREVIEW} onSwap={vi.fn()} />)
    const away = screen.getByRole('region', { name: /^merges away/ })
    const kept = screen.getByRole('region', { name: /^survives/ })
    expect(within(away).getByText('no series')).toBeInTheDocument()
    expect(within(kept).getByText('Dune Saga')).toHaveClass('text-path')
    expect(within(kept).getByText('26')).toBeInTheDocument()
    expect(within(kept).getByText('Set on the desert planet Arrakis.')).toBeInTheDocument()
    expect(within(away).getByText('editions').nextSibling).toHaveTextContent('2')
    expect(within(away).getByText('threads').nextSibling).toHaveTextContent('2')
    expect(within(away).getByText('shelves').nextSibling).toHaveTextContent('1')
  })

  it('states what moves, agreeing in number', () => {
    render(<MergePreview preview={{ ...PREVIEW, threads: 1, shelves: 2, editions: 0 }} />)
    expect(screen.getByText('1 thread, 2 shelf entries and 0 editions move to the survivor.')).toBeInTheDocument()
  })

  it('shows the cover when there is one and the title when there is none or it fails', () => {
    render(<MergePreview preview={PREVIEW} onSwap={vi.fn()} />)
    const kept = screen.getByRole('region', { name: /^survives/ })
    const img = within(kept).getByRole('img', { name: 'Dune' })
    expect(img).toHaveAttribute('src', 'https://x/dune.jpg')
    const away = screen.getByRole('region', { name: /^merges away/ })
    expect(within(away).queryByRole('img')).toBeNull()
    fireEvent.error(img)
    expect(within(kept).queryByRole('img')).toBeNull()
  })

  it('swaps on request, and offers no swap when the caller gives none', async () => {
    const onSwap = vi.fn()
    const { unmount } = render(<MergePreview preview={PREVIEW} onSwap={onSwap} />)
    await userEvent.click(screen.getByRole('button', { name: 'swap which book survives' }))
    expect(onSwap).toHaveBeenCalledTimes(1)
    unmount()
    render(<MergePreview preview={PREVIEW} />)
    expect(screen.queryByRole('button')).toBeNull()
  })
})
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd frontend && npx vitest run src/components/librarian/MergePreview.test.jsx`
Expected: FAIL. `Failed to resolve import "./MergePreview"`.

- [ ] **Step 3: Add the hook**

Append to `frontend/src/api/librarian.js`:

```js
/** Both books of a prospective merge, and what it would move. */
export function useMergePreview(sourceId, intoId) {
  return useQuery({
    queryKey: ['librarian', 'merge-preview', sourceId, intoId],
    queryFn: () =>
      client.get(`/librarian/works/${sourceId}/merge-preview`, { params: { into: intoId } }).then((r) => r.data),
    enabled: !!sourceId && !!intoId,
    retry: false, // a 409 (merged away) or 422 (same book) is an answer, not a blip
  })
}
```

- [ ] **Step 4: Write the component**

Create `frontend/src/components/librarian/MergePreview.jsx`:

```jsx
import { useState } from 'react'

const plural = (n, one, many = `${one}s`) => `${n} ${n === 1 ? one : many}`

function Cover({ side }) {
  // Same answer for "no art" as the series page: the title, never a broken image.
  const [failed, setFailed] = useState(false)
  if (side.cover_url && !failed) {
    return <img src={side.cover_url} alt={side.title} onError={() => setFailed(true)} className="w-full border border-line" />
  }
  return (
    <div className="w-full aspect-[2/3] bg-panel border border-line flex items-center justify-center p-2">
      <span className="font-serif italic text-ink-dim text-xs text-center">{side.title}</span>
    </div>
  )
}

function Side({ side, label, tone }) {
  return (
    // Named by role first: the two halves of a duplicate usually share a title.
    <section aria-label={`${label}: ${side.title}`} className="flex flex-col gap-2 min-w-0">
      <p className={`text-xs uppercase tracking-eyebrow ${tone}`}>{label}</p>
      {/* Covers carry the colour; large, full colour, never dimmed. */}
      <div className="w-28"><Cover side={side} /></div>
      <h3 className="font-serif text-lg text-ink leading-tight">{side.title}</h3>
      <p className="text-user text-xs lowercase tracking-eyebrow">{side.author}</p>
      <p className="text-ink-dim text-xs tabular-nums">{side.first_publish_year ?? 'year unknown'}</p>
      <p className="text-xs lowercase">
        {side.series_name ? (
          <><span className="text-ink-dim">series </span><span className="text-path">{side.series_name}</span></>
        ) : (
          <span className="text-ink-dim">no series</span>
        )}
      </p>
      <dl className="flex flex-wrap gap-x-4 text-xs tabular-nums">
        {[['editions', side.edition_count], ['threads', side.thread_count], ['shelves', side.shelf_count]].map(([name, n]) => (
          <div key={name} className="flex gap-1">
            <dt className="text-ink-dim">{name}</dt>
            <dd className="text-ink">{n}</dd>
          </div>
        ))}
      </dl>
      {side.description && (
        <p className="text-ink-dim text-xs leading-relaxed line-clamp-4">{side.description}</p>
      )}
    </section>
  )
}

/**
 * Two books about to become one, side by side. The left merges away; the
 * right survives. ``onSwap`` flips them (the caller owns which id is which);
 * without it the preview is read-only.
 */
function MergePreview({ preview, onSwap }) {
  const { source, target, threads, shelves, editions } = preview
  return (
    <div role="group" aria-label="Merge preview" className="flex flex-col gap-3">
      <div className="grid grid-cols-2 gap-5">
        {/* Keyed by book, so a swap moves each cover's state with its book. */}
        <Side key={source.id} side={source} label="merges away" tone="text-danger" />
        <Side key={target.id} side={target} label="survives" tone="text-ok" />
      </div>
      <div className="flex flex-wrap items-center gap-3">
        <p className="text-sm text-ink">
          {plural(threads, 'thread')}, {plural(shelves, 'shelf entry', 'shelf entries')} and{' '}
          {plural(editions, 'edition')} move to the survivor.
        </p>
        {onSwap && (
          <button type="button" className="btn-ghost text-xs" onClick={onSwap} aria-label="swap which book survives">
            swap
          </button>
        )}
      </div>
    </div>
  )
}

export default MergePreview
```

- [ ] **Step 5: Run the tests and the token contract**

Run: `cd frontend && npx vitest run src/components/librarian/MergePreview.test.jsx src/design/tokens.test.js`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/api/librarian.js frontend/src/components/librarian/MergePreview.jsx \
        frontend/src/components/librarian/MergePreview.test.jsx
git commit -m "feat(web): MergePreview shows both books side by side with a swap control"
```

---

### Task 4: The merge panel shows the preview and swaps the survivor

**Files:**
- Modify: `frontend/src/components/LibrarianPanel.jsx`
- Test: `frontend/src/components/LibrarianPanel.test.jsx`

**Interfaces:**
- Consumes: `useMergePreview` and `MergePreview` (Task 3). If item 02 or 03 has landed, the reason field may be `ReasonField` and `WorkPicker` may come from `components/librarian/pickers.jsx`. This task leaves both as they are and only edits the lines named below.
- Produces: the merge panel's fields gain `swapped: boolean` (false by default, reset to false whenever `into` changes). Also `mergeSides(work, fields) -> [mergesAway, survives]`, a module-private helper. Item 05 presets `fields.into` from `action.into` and relies on `swapped` working the same way.

- [ ] **Step 1: Write the failing panel tests**

In `frontend/src/components/LibrarianPanel.test.jsx`, add after the `CORRECTION` constant:

```jsx
const OTHER = { id: 'w2', title: 'Dune', author: 'Frank Herbert' }
const THIRD = { id: 'w3', title: 'Dune', author: 'Kevin J. Anderson' }
const side = (book, over = {}) => ({
  id: book.id, title: book.title, author: book.author, first_publish_year: null, cover_url: null,
  description: null, edition_count: 1, thread_count: 0, shelf_count: 0, series_slug: `s-${book.id}`,
  series_name: null, ...over,
})
const BY_ID = { w1: BOOK, w2: OTHER, w3: THIRD }

/** Search answers `works`; a merge preview answers for whichever pair it is asked about. */
function mockGets(works = [OTHER, THIRD], previewError = null) {
  client.get.mockImplementation((url, config) => {
    if (url === '/works/search') return Promise.resolve({ data: works })
    const preview = url.match(/^\/librarian\/works\/(\w+)\/merge-preview$/)
    if (preview) {
      if (previewError) return Promise.reject(previewError)
      const [from, to] = [BY_ID[preview[1]], BY_ID[config.params.into]]
      return Promise.resolve({ data: {
        source: side(from), target: side(to), threads: from.id === 'w1' ? 3 : 1, shelves: 0, editions: 1 } })
    }
    return Promise.resolve({ data: [] })
  })
}

async function pickToKeep(name) {
  await userEvent.type(screen.getByLabelText('Find the book to keep'), 'dune')
  await userEvent.click(await screen.findByRole('radio', { name }))
}
```

Replace the first two lines of the existing test `confirms a merge with the counts the server returned`:

```jsx
    client.get.mockResolvedValue({ data: [{ id: 'w2', title: 'Dune', author: 'Frank Herbert' }] })
```

with:

```jsx
    mockGets([OTHER])
```

Then, in the same test, insert this line before the `Reason` typing line. The submit now waits for the preview:

```jsx
    await screen.findByRole('group', { name: 'Merge preview' })
```

Append these tests inside the `describe('LibrarianPanel', …)` block:

```jsx
  it('shows both books side by side once the other book is picked', async () => {
    mockGets()
    renderPanel({ kind: 'merge', work: BOOK })
    expect(screen.queryByRole('group', { name: 'Merge preview' })).toBeNull()
    await pickToKeep(/Frank Herbert/)
    const preview = await screen.findByRole('group', { name: 'Merge preview' })
    expect(within(preview).getByRole('region', { name: 'merges away: Dune' })).toHaveTextContent('Brian Herbert')
    expect(within(preview).getByRole('region', { name: 'survives: Dune' })).toHaveTextContent('Frank Herbert')
    expect(client.get).toHaveBeenCalledWith('/librarian/works/w1/merge-preview', { params: { into: 'w2' } })
  })

  it('swap makes the picked book the one that merges away', async () => {
    mockGets()
    client.post
      .mockRejectedValueOnce({ response: { status: 422, data: { detail: {
        message: 'm', consequences: { threads: 1, shelves: 0, editions: 1 } } } } })
      .mockResolvedValueOnce({ data: CORRECTION })
    const onDone = renderPanel({ kind: 'merge', work: BOOK })
    await pickToKeep(/Frank Herbert/)
    await userEvent.click(await screen.findByRole('button', { name: 'swap which book survives' }))
    const preview = await screen.findByRole('group', { name: 'Merge preview' })
    await waitFor(() => expect(within(preview).getByRole('region', { name: /^merges away/ })).toHaveTextContent('Frank Herbert'))
    expect(client.get).toHaveBeenCalledWith('/librarian/works/w2/merge-preview', { params: { into: 'w1' } })

    await userEvent.type(screen.getByLabelText('Reason'), 'same book')
    await userEvent.click(screen.getByRole('button', { name: 'Merge' }))
    expect(client.post).toHaveBeenCalledWith('/librarian/works/w2/merge',
      { reason: 'same book', into_work_id: 'w1', confirm: false })
    expect(await screen.findByText(/Frank Herbert\) will merge into/)).toHaveTextContent(/\(Brian Herbert\)/)
    await userEvent.click(screen.getByRole('button', { name: 'Confirm merge' }))
    await waitFor(() => expect(onDone).toHaveBeenCalledWith(CORRECTION))
    expect(client.post).toHaveBeenLastCalledWith('/librarian/works/w2/merge',
      { reason: 'same book', into_work_id: 'w1', confirm: true })
  })

  it('swapping after the counts came back asks again', async () => {
    mockGets()
    client.post.mockRejectedValue({ response: { status: 422, data: { detail: {
      message: 'm', consequences: { threads: 3, shelves: 0, editions: 1 } } } } })
    renderPanel({ kind: 'merge', work: BOOK })
    await pickToKeep(/Frank Herbert/)
    await screen.findByRole('group', { name: 'Merge preview' })
    await userEvent.type(screen.getByLabelText('Reason'), 'same book')
    await userEvent.click(screen.getByRole('button', { name: 'Merge' }))
    expect(await screen.findByRole('button', { name: 'Confirm merge' })).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: 'swap which book survives' }))
    expect(screen.queryByRole('button', { name: 'Confirm merge' })).toBeNull()
    await waitFor(() => expect(screen.getByRole('button', { name: 'Merge' })).toBeEnabled())
    await userEvent.click(screen.getByRole('button', { name: 'Merge' }))
    expect(client.post).toHaveBeenLastCalledWith('/librarian/works/w2/merge',
      { reason: 'same book', into_work_id: 'w1', confirm: false })
  })

  it('refuses to go on when the preview says a book is gone', async () => {
    mockGets([OTHER], { response: { status: 409, data: { detail: 'Dune was merged into another book; reload the page.' } } })
    renderPanel({ kind: 'merge', work: BOOK })
    await pickToKeep(/Frank Herbert/)
    expect(await screen.findByText('Dune was merged into another book; reload the page.')).toHaveClass('alert-danger')
    await userEvent.type(screen.getByLabelText('Reason'), 'same book')
    expect(screen.getByRole('button', { name: 'Merge' })).toBeDisabled()
  })

  it('picking another book resets the swap', async () => {
    mockGets()
    renderPanel({ kind: 'merge', work: BOOK })
    await pickToKeep(/Frank Herbert/)
    await userEvent.click(await screen.findByRole('button', { name: 'swap which book survives' }))
    await userEvent.click(screen.getByRole('radio', { name: /Kevin J. Anderson/ }))
    const preview = await screen.findByRole('group', { name: 'Merge preview' })
    await waitFor(() => expect(within(preview).getByRole('region', { name: /^survives/ })).toHaveTextContent('Kevin J. Anderson'))
    expect(client.get).toHaveBeenLastCalledWith('/librarian/works/w1/merge-preview', { params: { into: 'w3' } })
  })
```

Add `within` to the Testing Library import on line 2:

```jsx
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd frontend && npx vitest run src/components/LibrarianPanel.test.jsx`
Expected: the five new tests FAIL with `Unable to find role="group" and name "Merge preview"`, and the edited `confirms a merge…` test fails the same way. The other tests PASS.

- [ ] **Step 3: Wire the preview into the panel**

In `frontend/src/components/LibrarianPanel.jsx`:

(a) Imports. Replace the first-party import lines so they read:

```jsx
import { confirmationOf, useLibrarianAction, useMergePreview, useSeriesSearch, useWorkEditions } from '../api/librarian'
import { useSearchWorks } from '../api/works'
import { errorMessage } from '../api/errors'
import MergePreview from './librarian/MergePreview'
```

Keep `useSeriesSearch`/`useSearchWorks` only while the pickers still live in this file. If item 03 moved them, keep that file's existing picker import and add only `useMergePreview` and `MergePreview`.

(b) Add this helper directly above `function request(`:

```jsx
/** [merges away, survives]: the row's book into the picked one, unless swapped. */
function mergeSides(work, f) {
  return f.swapped ? [f.into, work] : [work, f.into]
}
```

(c) In `request`, replace the `case 'merge':` line with:

```jsx
    case 'merge': {
      const [from, to] = mergeSides(work, f)
      return { path: `works/${from.id}/merge`, body: { reason, into_work_id: to?.id, confirm } }
    }
```

(d) In `Consequences`, replace the merge branch's `return (...)` with:

```jsx
    const [from, to] = mergeSides(work, fields)
    return (
      <p className="text-sm text-ink">
        <span className="font-serif italic">{from.title}</span> ({from.author}) will merge into{' '}
        <span className="font-serif italic">{to.title}</span> ({to.author}).{' '}
        {plural(counts.threads, 'thread')} and {plural(counts.shelves, 'shelf entry', 'shelf entries')} move.{' '}
        <span className="text-danger">This cannot be undone.</span>
      </p>
    )
```

(e) Add this component directly above `function LibrarianPanel(`:

```jsx
/** The preview, or why there is none. A refusal here is final for this pair. */
function PreviewSlot({ query, onSwap }) {
  if (query.isError) return <p className="alert-danger">{errorMessage(query.error)}</p>
  if (!query.data) return <p className="text-ink-dim text-xs">loading preview</p>
  return <MergePreview preview={query.data} onSwap={onSwap} />
}
```

(f) In `LibrarianPanel`, add `swapped: false` to the initial `fields` object, which then reads:

```jsx
  const [fields, setFields] = useState({
    reason: '', name: '', target: null, into: null, editions: [], swapped: false,
    // Only a reorder starts from the current place; a move names its own.
    position: kind === 'position' && work?.position != null ? String(work.position) : '',
  })
```

Replace the `set` helper with `patch` + `set`, and add the preview query and `swap` right after it:

```jsx
  const patch = (changes) => {
    if (mutation.isError) mutation.reset() // a refusal answered the old values, not these
    setFields((f) => ({ ...f, ...changes }))
  }
  const set = (key) => (value) => patch({ [key]: value })
  const [from, to] = kind === 'merge' && fields.into ? mergeSides(work, fields) : [null, null]
  const preview = useMergePreview(from?.id, to?.id)
  // Counts from the server described the other direction; ask again.
  const swap = () => { patch({ swapped: !fields.swapped }); setCounts(null) }
```

(g) Replace the `const title = …` line with:

```jsx
  const subject = from ?? work
  const title = `${TITLES[kind]}${subject ? ` ${subject.title}` : ` ${series.name}`}`
```

(h) In the confirm step, render the preview above `Consequences`:

```jsx
          <div className="flex flex-col gap-3">
            {kind === 'merge' && <PreviewSlot query={preview} onSwap={swap} />}
            <Consequences action={action} fields={fields} counts={counts} />
```

(i) In the form, replace the merge picker line with the picker (which resets the swap) followed by the preview:

```jsx
            {kind === 'merge' && (
              <WorkPicker exclude={work.id} value={fields.into} onChange={(w) => patch({ into: w, swapped: false })} />
            )}
            {kind === 'merge' && fields.into && <PreviewSlot query={preview} onSwap={swap} />}
```

(j) The submit button waits for a successful preview on a merge:

```jsx
            <button type="submit" className="btn-primary text-xs self-start"
                    disabled={!ready(kind, fields, editions) || mutation.isPending
                              || (kind === 'merge' && !preview.isSuccess)}>
              {TITLES[kind]}
            </button>
```

- [ ] **Step 4: Run the panel, series and token tests**

Run: `cd frontend && npx vitest run src/components/LibrarianPanel.test.jsx src/pages/Series.test.jsx src/design/tokens.test.js`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/LibrarianPanel.jsx frontend/src/components/LibrarianPanel.test.jsx
git commit -m "feat(web): merge panel previews both books and swaps which survives before confirm"
```

---

### Task 5: End-to-end: preview and swap from the series page

**Files:**
- Modify: `frontend/e2e/librarian.spec.js` (append)

**Interfaces:**
- Consumes: `registerViaUi`, `grantLibrarian`, `openFirstSearchResult` from `e2e/helpers.js`; the panel from Task 4.
- Produces: nothing later tasks use.

This scenario never confirms. Merge cannot be undone until item 16, and e2e runs against the dev database. Like the existing v1 scenario, it needs the full stack and live Open Library.

- [ ] **Step 1: Write the scenario**

Append to `frontend/e2e/librarian.spec.js`:

```js
// A librarian opens a merge from a series row, sees both books side by side,
// swaps which survives, and backs out. Never confirms: a merge is permanent.
test('a librarian previews a merge side by side and swaps the survivor', async ({ page }) => {
  const user = await registerViaUi(page)
  grantLibrarian(user)
  await page.reload()

  await openFirstSearchResult(page, 'dune')
  // A link in v1, a button once edit mode is sticky (item 01): match the text.
  await page.getByText('[edit]', { exact: true }).click()
  const books = page.getByRole('list', { name: 'Books in this series' })
  const title = await books.getByRole('heading').first().textContent()
  await books.getByRole('button', { name: `merge into… ${title}`, exact: true }).click()

  const dialog = page.getByRole('dialog')
  await dialog.getByLabel('Find the book to keep').fill('dune messiah')
  await dialog.getByRole('radio').first().check()
  const preview = dialog.getByRole('group', { name: 'Merge preview' })
  await expect(preview.getByRole('region', { name: `merges away: ${title}` })).toBeVisible()

  await preview.getByRole('button', { name: 'swap which book survives' }).click()
  await expect(preview.getByRole('region', { name: `survives: ${title}` })).toBeVisible()

  await page.keyboard.press('Escape')
  await expect(dialog).toBeHidden()
})
```

- [ ] **Step 2: Run it**

Run (stack up in another terminal via `docker compose up --build`, then from `frontend/`): `npm run test:e2e -- librarian.spec.js`
Expected: `2 passed` (the v1 move scenario and this one).

- [ ] **Step 3: Commit**

```bash
git add frontend/e2e/librarian.spec.js
git commit -m "test(e2e): librarian previews a merge and swaps the survivor"
```

---

### Task 6: Docs and tracker

**Files:**
- Modify: `docs/librarian-ux-roadmap.md`, `ROADMAP.md`, `CLAUDE.md`

- [ ] **Step 1: Write them**

- `docs/librarian-ux-roadmap.md`:
  - Tracker row 04: status `✅`, *Done* = merge date, *PR* = the PR link (fill both when the PR merges; until then leave `🟡`).
  - Under **Notes**, add:
    `- 2026-09-29 (04): MergeSide.series_name is null for a singleton (series_slug still set: it is the book's page). MergeSide.edition_count is the presentation count (OL total, then local rows) and matches search cards; the top-level editions is local rows that move. MergePreview's onSwap is optional; without it no swap control renders (for 14's compact rows). Service: services/librarian/identity.merge_preview; counts come from merge_consequences, shared with merge. Frontend hook: useMergePreview(sourceId, intoId). The panel's merge fields carry swapped (reset when into changes).`
  - Tick this plan's **Merged** checkbox in its header.
- `ROADMAP.md`, Phase 5 table: add this row directly under **Librarian tools**:
  `| ✅ | **Librarian: side-by-side merge preview** — before confirming a merge both books are shown next to each other (cover, author, year, series, editions, threads, shelves) with a swap control choosing the survivor; \`GET /api/librarian/works/{id}/merge-preview?into=\`. | [plan](docs/superpowers/plans/2026-09-29-lx04-merge-preview.md), \`services/librarian/identity.py\`, \`api/librarian.py\`, \`components/librarian/MergePreview.jsx\`, \`components/LibrarianPanel.jsx\` |`
- `CLAUDE.md`, in the `services/` paragraph after "`librarian/` holds the librarian tools (…) and is the only writer of `catalog_corrections`", add:
  `` `identity.merge_preview` answers what a merge would do without writing anything: both books through `load_work_presentation` (never raw cover/description columns) and the counts from `merge_consequences`, the same function the merge's 422 confirmation uses. ``

- [ ] **Step 2: Verify everything, then commit**

Run: `PYTEST -q -p no:warnings`, then `cd frontend && npm test && npm run build`.
Expected: all green. Vite builds with no errors.

```bash
git add docs/librarian-ux-roadmap.md ROADMAP.md CLAUDE.md docs/superpowers/plans/2026-09-29-lx04-merge-preview.md
git commit -m "docs: side-by-side merge preview (lx04)"
```

---

## Self-review

- **Spec coverage (§04 + shared names):** the endpoint and exact field names are Tasks 1–2. "Refuses self/merged exactly like merge" is `_distinct` + `live_work`, tested at service and route level. `cover_url`/`description` use the page ladder: Task 1 `test_sides_use_the_page_fallback_ladder_not_raw_columns`. `MergePreview` at `components/librarian/` with `preview`/`onSwap` is Task 3. The panel shows it before confirm, and the swap changes the source id: Task 4. The 422 confirm contract still works: the edited v1 test and the swap tests post `confirm: false` then `true`. The e2e scenario is Task 5, and the tracker and docs are Task 6.
- **Placeholders:** none. Every code step carries its code, and every run step its command and expected result.
- **Type consistency:** `merge_preview(db, source, target)` / `merge_consequences(db, source, target)` are named the same in Tasks 1, 2 and 6. `useMergePreview(sourceId, intoId)` is the same in Tasks 3 and 4. The group name `Merge preview`, the region names `merges away: <title>` / `survives: <title>` and the button `swap which book survives` are the same across Tasks 3, 4 and 5 (and item 05's plan).
- **Review Focus:** each of the five lines has a named test in its owning task.
