# Cover Picker Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** In edit mode a librarian opens `cover` on a book row, sees every edition's cover (plus Open Library's curated image when the work has one) with the current one marked, picks one, gives a reason, and the book wears it from then on. Nothing automatic overrides that choice, and it can be undone.

**Architecture:** A new correction op `set_cover` pins `works.representative_book_id`. The one choke point every re-pick goes through, `services/works._refresh_work`, reads the newest unreverted `set_cover` (`cover_pin`) and keeps it while the pin still holds. Every caller (search ingest, enrichment, `merge_works`, split, `repair_presentation`, `backfill_covers`) inherits that. Two paths do not go through `_refresh_work`: the catalog loader's raw `UPDATE … representative_book_id` (guarded in SQL), and automatic merges, which carry the source's pin to the target (`services/librarian/carry.py`, called from `merge_works`). `services/librarian/covers.py` lists options, sets the pin and undoes it. The frontend adds a `cover` row action and a `CoverGrid` inside `LibrarianPanel`.

**Tech Stack:** FastAPI, async SQLAlchemy 2.0, Alembic, Pydantic v2, React 18 + React Query + Tailwind tokens, Vitest + RTL, Playwright.

**Spec:** docs/librarian-ux-roadmap.md §06 (Cover picker), plus the "Cover (06)" entry under *Shared names → Backend*. The v1 design (`docs/superpowers/specs/2026-09-28-librarian-tools-design.md`) still applies to everything this plan does not change.

- [ ] **Roadmap item:** 06 — tick in docs/librarian-ux-roadmap.md when merged

## Global Constraints

- Repo rules in `CLAUDE.md` apply verbatim: `api/` thin, `services/librarian/` is the only writer of `catalog_corrections`, async everywhere, schemas built explicitly (never `model_validate` of an ORM object with relationships).
- Route names (binding): `GET /api/librarian/works/{id}/covers` → `[CoverOption {book_id, cover_url, title, published_year, language, source, current}]`; `POST /api/librarian/works/{id}/cover {book_id, reason}` → `CorrectionOut`.
- New op `set_cover`. Runtime-only, always: `runtime_only_reason = "the overrides format has no cover entry"`. Undoable.
- The representative picker (`services/works.py`) and `scripts.repair_presentation` leave a work alone while it has an unreverted `set_cover` correction (same rule shape as `services/series._placed_by_librarian`).
- Every new write carries a required, non-empty `reason` (`clean_reason`, 422 otherwise).
- Every librarian route depends on `require_librarian`; the test module asserts 401 anonymous / 403 reader for each new route.
- Migration: create it at execution time with `alembic revision -m …` so `down_revision` is the head *then*. Never hardcode a revision id. The enum value is added with `ALTER TYPE correction_op_enum ADD VALUE IF NOT EXISTS 'set_cover'`; downgrade leaves the value in place and says so in a comment.
- Frontend: tokens only; no new radii, shadows, font sizes or durations; every glyph `aria-hidden`; serif only for book titles; covers are never dimmed. §36 test before calling the screen done.
- Tests: pytest against `margin_test`, Vitest + RTL, one Playwright scenario. Network always mocked (`respx` in pytest, `page.route` in Playwright).
- Branch `feat/librarian-lx06-cover-picker` from `main`; one commit per task; PR to `main`.
- Backend tests run in the backend container against `margin_test`, from the repo root. Referred to below as **`PYTEST`**:
  `docker compose run --rm --no-deps -v "$PWD/pipeline:/pipeline:ro" -e DATABASE_URL=postgresql+asyncpg://margin:margin@db:5432/margin_test backend pytest <args>`
  Frontend unit tests: `cd frontend && npx vitest run <path>`.

## Decisions this plan adds to the roadmap

1. **An Open Library curated cover has no `books` row. It is represented as `book_id: null`.** In `CoverOption` it is the option with `book_id: null` and `source: "ol_curated"`. `POST …/cover {book_id: null}` pins it by setting `representative_book_id = NULL`. `load_work_presentation` already falls back to `ol_cover_url(work.ol_cover_id)` when the representative has no cover, so no read path changes. The option exists only while `works.ol_cover_id` is set. If an edition's `cover_url` is the same URL, the edition is listed and the OL option is dropped, so exactly one option can be `current`.
2. **A pin holds only while it can.** An edition pin holds while that edition still belongs to the work and still has a `cover_url`. An OL pin holds while `ol_cover_id` is set. A pin that no longer holds is *inert*: the ranking runs as if it were not there. It is not deleted. So a split, `repair_presentation` detaching the edition, or enrichment rejecting a placeholder cover can never leave a book pointing at a foreign or blank picture.
3. **The newest unreverted `set_cover` wins.** Undo re-derives the representative as if the undone fix had never happened (`_refresh_work(…, ignore_pin=c.id)`). An older pin then applies again, or the ranking does. That is more robust than restoring a stored id that may since have left the work. The stored `snapshot.prior` is kept for the log only.
4. **Pinning the cover the book already shows is allowed.** It is how a librarian says "keep this one" before enrichment gets a chance to re-rank it. Only re-pinning the *same* choice the newest pin already names is refused (422 `That is already the chosen cover.`).
5. **Automatic merges carry the pin, librarian merges do not.** `merge_works(…, carry_fixes=True)` (the default: search's `_absorb_heuristic_twin`, the loader's adoption and alias merges) moves the source's unreverted edition pins onto the target, unless the target has a pin of its own. The pinned edition moves with the merge, so the book keeps the art the librarian chose. A librarian merge (`services/librarian/identity.merge`) passes `carry_fixes=False`: the surviving book keeps its own cover, which is what the merge panel shows. Item 07 adds the choice. An OL pin is never carried, because on the target `null` would mean a *different* record's image.
6. **The catalog loader's `representative_book_id IS NULL` refill skips an OL pin.** Without this, the next release would silently overwrite a librarian's "use Open Library's image" (NULL) with the release's representative. An edition pin is safe there already, because the column is not NULL.
7. **Choosing a cover also chooses the description.** Both are read through the representative edition (`load_work_presentation`: the representative's description before the work's). Picking the Spanish edition's cover shows its Spanish blurb. This is existing coupling, and it usually helps: the "wrong language" fix fixes both. It is pinned by a test and stated in the panel hint. Item 07 adds a separate description override.
8. **A `set_cover` is a fix on its book, so it takes part in v1's "latest fix on the subject" undo rule.** An earlier move of the same book cannot be undone until the cover fix is undone. The error names this ("A later fix to the same book or series came after this one; undo that first.").

## Review Focus

1. **A search or first view re-picks the representative right after the librarian chose one.** Enrichment attaches a better-ranked English edition. The chosen cover must stay (Task 1 `test_enrichment_keeps_a_pinned_cover`).
2. **The next catalog release after a librarian chose Open Library's own image.** The loader must not refill `representative_book_id`, and must refill it once the fix is undone (Task 3 `test_a_release_does_not_refill_a_cover_set_to_open_librarys` and `…_after_undo`).
3. **An option whose image URL is dead.** The tile must say so and cannot be chosen, and the other tiles keep working (Task 5 `marks a broken image and will not choose it`).
4. **The chosen edition later leaves the book** (split, or `repair_presentation` detaching it). The book must fall back to the ranked cover, never keep a foreign one, and undo must refuse as stale rather than guess (Task 1 `test_a_pin_on_an_edition_that_left_is_inert`, Task 2 `test_undo_refuses_when_the_pinned_edition_was_detached`).
5. **A runtime book with a chosen cover is adopted by a release.** The adopted book keeps the chosen art (Task 3 `test_an_adopted_runtime_work_keeps_its_librarians_cover`).

---

## File Structure

**Backend — create**
- `backend/alembic/versions/<generated>_set_cover_correction_op.py` — adds `set_cover` to `correction_op_enum`.
- `backend/app/services/librarian/covers.py` — `CoverChoice`, `CoverCandidate`, `shown_cover`, `cover_options`, `set_cover`, `RUNTIME_ONLY`, `OL_CURATED`.
- `backend/app/services/librarian/carry.py` — `carry_fixes` (pins follow an automatic merge).
- `backend/tests/test_cover_pin.py` — the pin rule and every in-process re-pick path.
- `backend/tests/test_librarian_covers.py` — options, set, refusals, undo.
- `backend/tests/test_catalog_loader_cover_pin.py` — release refill guard and adoption carry.

**Backend — modify**
- `backend/app/models/correction.py` — `CorrectionOp.set_cover`.
- `backend/app/services/works.py` — `CoverPin`, `cover_pin`, `_pin_holds`, `_refresh_work(…, ignore_pin=)`, `merge_works(…, carry_fixes=)`.
- `backend/app/services/librarian/identity.py` — `merge_works(…, carry_fixes=False)`.
- `backend/app/services/librarian/undo.py` — `_undo_set_cover`, `UNDOABLE`.
- `backend/app/services/librarian/__init__.py` — re-export `set_cover`, `cover_options`.
- `backend/app/services/catalog_loader.py` — the refill `UPDATE` skips an OL pin.
- `backend/app/schemas/librarian.py` — `CoverIn`, `CoverOption`.
- `backend/app/api/librarian.py` — two routes.
- `backend/scripts/repair_presentation.py` — docstring (pass 4 honours a librarian's cover).
- `backend/tests/librarian_factories.py` — `make_edition(…, cover_url=None)`.
- `backend/tests/test_librarian_api.py` — new routes in `WRITES`/`READS`, one flow test.

**Frontend — create**
- `frontend/src/components/librarian/CoverGrid.jsx`, `frontend/src/components/librarian/CoverGrid.test.jsx`.
- `frontend/e2e/librarian-cover.spec.js`.

**Frontend — modify**
- `frontend/src/api/librarian.js` — `useWorkCovers`.
- `frontend/src/components/LibrarianPanel.jsx` (+ `.test.jsx`) — the `cover` action.
- `frontend/src/pages/Series.jsx` (+ `.test.jsx`) — `cover` in the row actions.

**Docs — modify:** `docs/librarian-ux-roadmap.md`, `ROADMAP.md`, `CLAUDE.md`.

---

### Task 1: `set_cover` op and the pin rule in `_refresh_work`

**Files:**
- Create: `backend/alembic/versions/<generated>_set_cover_correction_op.py`, `backend/tests/test_cover_pin.py`
- Modify: `backend/app/models/correction.py`, `backend/app/services/works.py:405-422`, `backend/scripts/repair_presentation.py:1-24`, `backend/tests/librarian_factories.py:96-103`

**Interfaces:**
- Produces: `CorrectionOp.set_cover`; `works.CoverPin(correction_id: UUID, book_id: UUID | None)`; `async works.cover_pin(db, work_id: UUID, *, ignore: UUID | None = None) -> CoverPin | None`; `async works._refresh_work(db, work, genre_hints=None, *, ignore_pin: UUID | None = None) -> None`; test factory `make_edition(db, work, *, ol_id=None, title=None, language="en", cover_url=None)`.
- Payload contract every later task relies on: a `set_cover` correction's `payload` is `{"work": "<uuid>", "book_id": "<uuid>" | null, "cover_url": "<url>"}`.

- [ ] **Step 0: Mark the item started**

In `docs/librarian-ux-roadmap.md`, tracker row 06: set Status to `🟡` and Branch to `feat/librarian-lx06-cover-picker`.

- [ ] **Step 1: Let the factory give an edition a cover**

In `backend/tests/librarian_factories.py`, replace `make_edition` with:

```python
async def make_edition(db, work, *, ol_id=None, title=None, language="en", cover_url=None):
    """An Open Library edition when ``ol_id`` is given, otherwise a Google volume."""
    b = Book(source="openlibrary" if ol_id else "google_books",
             external_id=ol_id or uuid.uuid4().hex[:12], title=title or work.title,
             author=work.author, language=language, work_id=work.id, cover_url=cover_url)
    db.add(b)
    await db.flush()
    return b
```

- [ ] **Step 2: Write the failing tests**

`backend/tests/test_cover_pin.py`:

```python
"""Roadmap 06: a librarian's cover choice survives every representative re-pick."""

from datetime import datetime, timezone

import respx
from httpx import Response

from app.models import CorrectionOp, Work
from app.services.enrichment import enrich_work
from app.services.librarian.identity import merge, split
from app.services.librarian.record import record
from app.services.works import _refresh_work, cover_pin, merge_works
from scripts.backfill_covers import backfill
from scripts.repair_presentation import repair
from tests.librarian_factories import fresh, make_edition, make_user, make_work

RUNTIME = "the overrides format has no cover entry"
GOOGLE_URL = "https://www.googleapis.com/books/v1/volumes"


async def pin(db, work, book):
    """A set_cover correction written directly; Task 2 adds the real op."""
    user = await make_user(db, librarian=True)
    c = await record(db, op=CorrectionOp.set_cover, user=user, reason="r",
                     payload={"work": str(work.id), "book_id": str(book.id) if book else None,
                              "cover_url": book.cover_url if book else "ol"},
                     entries=None, runtime_only_reason=RUNTIME, snapshot={"prior": None}, work=work)
    work.representative_book_id = book.id if book else None
    await db.flush()
    return c


async def english_and_spanish(db, work):
    """edition_rank prefers the English one; the tests pin the Spanish one."""
    english = await make_edition(db, work, cover_url="https://img.test/en.jpg")
    spanish = await make_edition(db, work, language="es", cover_url="https://img.test/es.jpg")
    return english, spanish


async def test_an_unpinned_work_is_ranked(db_session):
    work = await make_work(db_session, "Red Rising", ol_id="OL30W", author="Pierce Brown")
    english, _ = await english_and_spanish(db_session, work)
    await _refresh_work(db_session, work)
    assert work.representative_book_id == english.id


async def test_refresh_keeps_a_pinned_edition(db_session):
    work = await make_work(db_session, "Red Rising", ol_id="OL30W", author="Pierce Brown")
    _, spanish = await english_and_spanish(db_session, work)
    await pin(db_session, work, spanish)
    await _refresh_work(db_session, work)
    assert work.representative_book_id == spanish.id


async def test_a_reverted_pin_is_ignored(db_session):
    work = await make_work(db_session, "Red Rising", ol_id="OL30W", author="Pierce Brown")
    english, spanish = await english_and_spanish(db_session, work)
    c = await pin(db_session, work, spanish)
    c.reverted_at = datetime.now(timezone.utc)
    await db_session.flush()
    await _refresh_work(db_session, work)
    assert work.representative_book_id == english.id


async def test_the_newest_pin_wins_and_ignore_skips_one(db_session):
    work = await make_work(db_session, "Red Rising", ol_id="OL30W", author="Pierce Brown")
    english, spanish = await english_and_spanish(db_session, work)
    await pin(db_session, work, spanish)
    newest = await pin(db_session, work, english)
    assert (await cover_pin(db_session, work.id)).book_id == english.id
    assert (await cover_pin(db_session, work.id, ignore=newest.id)).book_id == spanish.id
    await _refresh_work(db_session, work, ignore_pin=newest.id)
    assert work.representative_book_id == spanish.id


async def test_an_open_library_pin_keeps_no_representative(db_session):
    work = await make_work(db_session, "Red Rising", ol_id="OL30W", author="Pierce Brown")
    work.ol_cover_id = 7316188
    await english_and_spanish(db_session, work)
    await pin(db_session, work, None)
    await _refresh_work(db_session, work)
    assert work.representative_book_id is None


async def test_an_open_library_pin_without_an_ol_cover_is_inert(db_session):
    work = await make_work(db_session, "Red Rising", ol_id="OL30W", author="Pierce Brown")
    english, _ = await english_and_spanish(db_session, work)
    await pin(db_session, work, None)  # ol_cover_id is None
    await _refresh_work(db_session, work)
    assert work.representative_book_id == english.id


async def test_a_pin_on_an_edition_that_left_is_inert(db_session):
    work = await make_work(db_session, "Red Rising", ol_id="OL30W", author="Pierce Brown")
    other = await make_work(db_session, "Iron Gold", ol_id="OL31W", author="Pierce Brown")
    english, spanish = await english_and_spanish(db_session, work)
    await pin(db_session, work, spanish)
    spanish.work_id = other.id
    await db_session.flush()
    await _refresh_work(db_session, work)
    assert work.representative_book_id == english.id


async def test_a_pin_on_an_edition_whose_cover_was_rejected_is_inert(db_session):
    work = await make_work(db_session, "Red Rising", ol_id="OL30W", author="Pierce Brown")
    english, spanish = await english_and_spanish(db_session, work)
    await pin(db_session, work, spanish)
    spanish.cover_url = None  # what enrichment and backfill_covers do to a placeholder
    await db_session.flush()
    await _refresh_work(db_session, work)
    assert work.representative_book_id == english.id


async def test_merge_works_keeps_the_targets_pin(db_session):
    target = await make_work(db_session, "Red Rising", ol_id="OL30W", author="Pierce Brown")
    source = await make_work(db_session, "Red Rising", author="Pierce Brown")
    spanish = await make_edition(db_session, target, language="es", cover_url="https://img.test/es.jpg")
    await make_edition(db_session, source, cover_url="https://img.test/en.jpg")
    await pin(db_session, target, spanish)
    await merge_works(db_session, source, target)
    assert target.representative_book_id == spanish.id


async def test_split_keeps_a_pin_that_stays_behind(db_session):
    lib = await make_user(db_session, librarian=True)
    work = await make_work(db_session, "Dune", ol_id="OL100W", author="Frank Herbert")
    await make_edition(db_session, work, ol_id="OL1M", cover_url="https://img.test/en.jpg")
    spanish = await make_edition(db_session, work, ol_id="OL2M", language="es", cover_url="https://img.test/es.jpg")
    messiah = await make_edition(db_session, work, ol_id="OL3M", title="Dune Messiah")
    await pin(db_session, work, spanish)
    await split(db_session, lib, work, [messiah.id], reason="a different book", confirm=True)
    assert await fresh(db_session, Work.representative_book_id, work.id) == spanish.id


@respx.mock
async def test_enrichment_keeps_a_pinned_cover(db_session):
    respx.get(GOOGLE_URL).mock(return_value=Response(200, json={"items": [{"id": "g1", "volumeInfo": {
        "title": "Red Rising", "authors": ["Pierce Brown"], "description": "A boy from the mines.",
        "language": "en", "imageLinks": {"thumbnail": "http://x/real?zoom=1"}}}]}))
    respx.head("https://x/real?zoom=0").mock(return_value=Response(200, headers={"content-type": "image/jpeg"}))
    work = await make_work(db_session, "Red Rising", ol_id="OL30W", author="Pierce Brown")
    work.enriched_at = None
    spanish = await make_edition(db_session, work, language="es", cover_url="https://img.test/es.jpg")
    await pin(db_session, work, spanish)

    await enrich_work(db_session, work)

    assert work.enriched_at is not None  # it ran, attached the English volume, re-picked
    assert work.representative_book_id == spanish.id


async def test_repair_presentation_keeps_a_pinned_cover(db_session):
    work = await make_work(db_session, "Red Rising", ol_id="OL30W", author="Pierce Brown")
    _, spanish = await english_and_spanish(db_session, work)
    await pin(db_session, work, spanish)
    summary = await repair(db_session, commit=False)
    assert await fresh(db_session, Work.representative_book_id, work.id) == spanish.id
    assert summary["representatives_changed"] == 0


@respx.mock
async def test_backfill_covers_keeps_a_pinned_cover(db_session):
    # A heuristic work: backfill only searches Open Library for OL works.
    work = await make_work(db_session, "Red Rising", author="Pierce Brown")
    _, spanish = await english_and_spanish(db_session, work)
    await make_edition(db_session, work, cover_url="https://img.test/placeholder.jpg")
    await pin(db_session, work, spanish)
    respx.head("https://img.test/en.jpg").mock(return_value=Response(200, headers={"content-type": "image/jpeg"}))
    respx.head("https://img.test/es.jpg").mock(return_value=Response(200, headers={"content-type": "image/jpeg"}))
    respx.head("https://img.test/placeholder.jpg").mock(return_value=Response(404))

    summary = await backfill(db_session, commit=False)

    assert summary["representatives_repicked"] == 1  # the work was touched and re-picked
    assert await fresh(db_session, Work.representative_book_id, work.id) == spanish.id


async def test_a_librarian_merge_does_not_carry_the_sources_pin(db_session):
    lib = await make_user(db_session, librarian=True)
    target = await make_work(db_session, "Red Rising", ol_id="OL30W", author="Pierce Brown")
    source = await make_work(db_session, "Red Rising", ol_id="OL31W", author="Pierce Brown")
    english = await make_edition(db_session, target, cover_url="https://img.test/en.jpg")
    spanish = await make_edition(db_session, source, language="es", cover_url="https://img.test/es.jpg")
    c = await pin(db_session, source, spanish)
    await merge(db_session, lib, source, target, reason="same book", confirm=True)
    assert await fresh(db_session, Work.representative_book_id, target.id) == english.id
    await db_session.refresh(c)
    assert c.work_id == source.id  # stays on the tombstone, inert
```

The last test needs `carry_fixes` (Task 3). Mark it `@pytest.mark.skip(reason="carry_fixes lands in Task 3")` for now (add `import pytest`), and remove the mark in Task 3 Step 4.

- [ ] **Step 3: Run the tests and watch them fail**

Run: `PYTEST tests/test_cover_pin.py -v`
Expected: collection error `AttributeError: set_cover` (the enum has no such member) or `ImportError: cannot import name 'cover_pin'`.

- [ ] **Step 4: Add the op**

In `backend/app/models/correction.py`, add the member after `rename_series`:

```python
    rename_series = "rename_series"
    set_cover = "set_cover"  # pins works.representative_book_id; runtime-only (roadmap 06)
```

- [ ] **Step 5: Implement the pin rule**

In `backend/app/services/works.py`, add the import next to the other model imports:

```python
from app.models.correction import CatalogCorrection, CorrectionOp
```

Add above `_refresh_work`:

```python
class CoverPin(NamedTuple):
    """A librarian's unreverted cover choice (roadmap 06). ``book_id`` None
    means Open Library's curated image, which has no ``books`` row."""

    correction_id: UUID
    book_id: UUID | None


async def cover_pin(db: AsyncSession, work_id: UUID, *, ignore: UUID | None = None) -> CoverPin | None:
    """The newest unreverted ``set_cover`` on ``work_id``, skipping ``ignore``
    (undo re-derives the cover as if that fix never happened)."""
    query = select(CatalogCorrection.id, CatalogCorrection.payload).where(
        CatalogCorrection.work_id == work_id,
        CatalogCorrection.op == CorrectionOp.set_cover,
        CatalogCorrection.reverted_at.is_(None),
    )
    if ignore is not None:
        query = query.where(CatalogCorrection.id != ignore)
    row = (await db.execute(
        query.order_by(CatalogCorrection.created_at.desc(), CatalogCorrection.id.desc()).limit(1)
    )).first()
    if row is None:
        return None
    book_id = row.payload.get("book_id")
    return CoverPin(row.id, UUID(book_id) if book_id else None)


def _pin_holds(work: Work, pin: CoverPin, editions: Sequence[Book]) -> bool:
    """A pin holds while it can: its edition is still this work's and still has
    art, or — for Open Library's image — the work still has an OL cover. An
    inert pin is ignored, never deleted."""
    if pin.book_id is None:
        return work.ol_cover_id is not None
    return any(e.id == pin.book_id and e.cover_url for e in editions)
```

Replace `_refresh_work` with:

```python
async def _refresh_work(
    db: AsyncSession,
    work: Work,
    genre_hints: Mapping[UUID, UUID] | None = None,
    *,
    ignore_pin: UUID | None = None,
) -> None:
    """Recompute the derived fields that depend on the work's editions.

    Every representative re-pick goes through here — ingest, enrichment,
    merges, split, repair_presentation, backfill_covers — so this is where a
    librarian's cover choice (an unreverted ``set_cover``) is honoured.
    """
    editions = (
        await db.execute(select(Book).where(Book.work_id == work.id))
    ).scalars().all()

    pin = await cover_pin(db, work.id, ignore=ignore_pin)
    if pin is not None and _pin_holds(work, pin, editions):
        work.representative_book_id = pin.book_id
    elif editions:
        work.representative_book_id = max(editions, key=edition_rank).id

    if editions and work.genre_id is None and genre_hints:
        work.genre_id = next(
            (genre_hints[e.id] for e in editions if e.id in genre_hints), None
        )
```

- [ ] **Step 6: Document it where the next reader looks**

In `backend/scripts/repair_presentation.py`, replace docstring item 4 with:

```
4. Re-pick every work's representative under ``edition_rank``, so an English
   edition speaks for an English work — except where a librarian chose the
   cover (an unreverted ``set_cover``), which ``_refresh_work`` keeps while
   the chosen edition is still the work's.
```

- [ ] **Step 7: Write the migration**

Run: `docker compose exec backend alembic revision -m "set_cover correction op"`
Expected: `Generating /app/alembic/versions/<rev>_set_cover_correction_op.py ... done`. Open it: `down_revision` already names the current head. Replace the bodies:

```python
def upgrade() -> None:
    # ADD VALUE cannot run inside a transaction block on older Postgres.
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE correction_op_enum ADD VALUE IF NOT EXISTS 'set_cover'")


def downgrade() -> None:
    # Postgres cannot drop an enum value: 'set_cover' stays in correction_op_enum.
    # Harmless — nothing writes it once the code is rolled back.
    pass
```

Run: `docker compose exec backend alembic upgrade head && docker compose exec backend alembic downgrade -1 && docker compose exec backend alembic upgrade head`
Expected: three runs with no error. The second upgrade is a no-op thanks to `IF NOT EXISTS`.

- [ ] **Step 8: Run the tests**

Run: `PYTEST tests/test_cover_pin.py tests/test_enrichment.py tests/test_repair_presentation.py tests/test_backfill_covers.py tests/test_edition_rank.py tests/test_works.py tests/test_librarian_identity.py -v`
Expected: all PASS; `test_a_librarian_merge_does_not_carry_the_sources_pin` SKIPPED.

- [ ] **Step 9: Commit**

```bash
git add backend/app/models/correction.py backend/app/services/works.py backend/scripts/repair_presentation.py \
        backend/alembic/versions/*_set_cover_correction_op.py backend/tests/librarian_factories.py \
        backend/tests/test_cover_pin.py docs/librarian-ux-roadmap.md
git commit -m "feat(librarian): set_cover op; every representative re-pick honours a librarian's cover"
```

---

### Task 2: Cover options, `set_cover` and its undo

**Files:**
- Create: `backend/app/services/librarian/covers.py`, `backend/tests/test_librarian_covers.py`
- Modify: `backend/app/services/librarian/undo.py`, `backend/app/services/librarian/__init__.py`

**Interfaces:**
- Consumes: `works.cover_pin`, `works._refresh_work(…, ignore_pin=)`, `works.edition_rank`, `open_library.cover_url`, `record.{clean_reason, live_work, locked, record}`.
- Produces (07 relies on these):
  - `covers.RUNTIME_ONLY = "the overrides format has no cover entry"`, `covers.OL_CURATED = "ol_curated"`.
  - `covers.CoverChoice(book_id: UUID | None, cover_url: str)` (NamedTuple, compares by value).
  - `async covers.shown_cover(db, work: Work) -> CoverChoice | None`: what `load_work_presentation` shows.
  - `covers.CoverCandidate(book_id, cover_url, title, published_year, language, source, current)`.
  - `async covers.cover_options(db, work: Work) -> list[CoverCandidate]`.
  - `async covers.set_cover(db, user: User, work: Work, book_id: UUID | None, *, reason: str) -> CatalogCorrection`.
  - `set_cover` is in `undo.UNDOABLE`.

- [ ] **Step 1: Write the failing tests**

`backend/tests/test_librarian_covers.py`:

```python
import pytest

from app.models import CorrectionOp, Work
from app.services.librarian.covers import OL_CURATED, RUNTIME_ONLY, cover_options, set_cover
from app.services.librarian.errors import Conflict, Invalid, NotFound
from app.services.librarian.identity import merge
from app.services.librarian.placement import set_series
from app.services.librarian.undo import revert, undoable
from app.services.works import _refresh_work, load_work_presentation
from scripts.repair_presentation import repair
from tests.librarian_factories import fresh, make_edition, make_user, make_work

EN, ES, OL = "https://img.test/en.jpg", "https://img.test/es.jpg", "https://covers.openlibrary.org/b/id/7316188-L.jpg"


async def book_with_two_covers(db, *, ol_cover=True):
    work = await make_work(db, "Red Rising", ol_id="OL30W", author="Pierce Brown")
    work.ol_cover_id = 7316188 if ol_cover else None
    english = await make_edition(db, work, cover_url=EN)
    spanish = await make_edition(db, work, language="es", cover_url=ES)
    await make_edition(db, work, title="Red Rising (audio)")  # no cover: never an option
    await _refresh_work(db, work)
    return work, english, spanish


async def test_options_list_every_cover_and_open_librarys_marking_the_current_one(db_session):
    work, english, spanish = await book_with_two_covers(db_session)
    options = await cover_options(db_session, work)
    assert [(o.book_id, o.cover_url, o.source, o.current) for o in options] == [
        (None, OL, OL_CURATED, False),
        (english.id, EN, "google_books", True),  # edition_rank's pick is what shows
        (spanish.id, ES, "google_books", False),
    ]
    assert options[2].language == "es" and options[0].language is None


async def test_the_ol_option_is_dropped_when_an_edition_carries_the_same_image(db_session):
    work, english, _ = await book_with_two_covers(db_session)
    english.cover_url = OL
    await db_session.flush()
    options = await cover_options(db_session, work)
    assert [o.book_id for o in options if o.cover_url == OL] == [english.id]
    assert sum(o.current for o in options) == 1


async def test_set_cover_pins_an_edition_runtime_only(db_session):
    lib = await make_user(db_session, librarian=True)
    work, _, spanish = await book_with_two_covers(db_session)
    c = await set_cover(db_session, lib, work, spanish.id, reason="the edition readers know")
    assert c.op is CorrectionOp.set_cover and c.work_id == work.id and c.series_id == work.series_id
    assert c.override is None and c.runtime_only_reason == RUNTIME_ONLY
    assert c.payload == {"work": str(work.id), "book_id": str(spanish.id), "cover_url": ES}
    shown = (await load_work_presentation(db_session, [work.id]))[work.id]
    assert shown.cover_url == ES
    await _refresh_work(db_session, work)  # the next re-pick leaves it alone
    assert work.representative_book_id == spanish.id


async def test_set_cover_to_open_librarys_image(db_session):
    lib = await make_user(db_session, librarian=True)
    work, _, _ = await book_with_two_covers(db_session)
    await set_cover(db_session, lib, work, None, reason="the canonical art")
    assert work.representative_book_id is None
    assert (await load_work_presentation(db_session, [work.id]))[work.id].cover_url == OL
    assert [o.current for o in await cover_options(db_session, work)] == [True, False, False]


async def test_the_description_follows_the_chosen_edition(db_session):
    lib = await make_user(db_session, librarian=True)
    work, english, spanish = await book_with_two_covers(db_session)
    english.description, spanish.description = "A boy from the mines.", "Un chico de las minas."
    await set_cover(db_session, lib, work, spanish.id, reason="r")
    assert (await load_work_presentation(db_session, [work.id]))[work.id].description == "Un chico de las minas."


async def test_pinning_the_cover_already_shown_is_allowed_once(db_session):
    lib = await make_user(db_session, librarian=True)
    work, english, _ = await book_with_two_covers(db_session)
    await set_cover(db_session, lib, work, english.id, reason="keep this one")
    with pytest.raises(Invalid, match="already the chosen cover"):
        await set_cover(db_session, lib, work, english.id, reason="again")


async def test_set_cover_refusals(db_session):
    lib = await make_user(db_session, librarian=True)
    work, english, _ = await book_with_two_covers(db_session, ol_cover=False)
    other = await make_work(db_session, "Iron Gold", ol_id="OL31W", author="Pierce Brown")
    foreign = await make_edition(db_session, other, cover_url="https://img.test/ig.jpg")
    bare = await make_edition(db_session, work, title="Red Rising (large print)")

    with pytest.raises(Invalid, match="reason"):
        await set_cover(db_session, lib, work, english.id, reason="   ")
    with pytest.raises(Invalid, match="not an edition of Red Rising"):
        await set_cover(db_session, lib, work, foreign.id, reason="r")
    with pytest.raises(Invalid, match="no cover"):
        await set_cover(db_session, lib, work, bare.id, reason="r")
    with pytest.raises(Invalid, match="no Open Library cover"):
        await set_cover(db_session, lib, work, None, reason="r")
    with pytest.raises(NotFound):
        await set_cover(db_session, lib, work, other.id, reason="r")  # a work id is not an edition id
    await merge(db_session, lib, work, other, reason="r", confirm=True)
    with pytest.raises(Conflict, match="merged"):
        await set_cover(db_session, lib, work, english.id, reason="r")
    with pytest.raises(Conflict, match="merged"):
        await cover_options(db_session, work)


async def test_undo_restores_the_ranked_cover(db_session):
    lib = await make_user(db_session, librarian=True)
    work, english, spanish = await book_with_two_covers(db_session)
    c = await set_cover(db_session, lib, work, spanish.id, reason="r")
    assert await undoable(db_session, c)
    await revert(db_session, lib, c)
    assert c.reverted_at is not None
    assert await fresh(db_session, Work.representative_book_id, work.id) == english.id


async def test_undo_falls_back_to_the_previous_pin(db_session):
    lib = await make_user(db_session, librarian=True)
    work, english, spanish = await book_with_two_covers(db_session)
    await set_cover(db_session, lib, work, spanish.id, reason="first")
    second = await set_cover(db_session, lib, work, None, reason="second")
    await revert(db_session, lib, second)
    assert await fresh(db_session, Work.representative_book_id, work.id) == spanish.id


async def test_undo_refuses_when_the_pinned_edition_was_detached(db_session):
    lib = await make_user(db_session, librarian=True)
    work, _, spanish = await book_with_two_covers(db_session)
    c = await set_cover(db_session, lib, work, spanish.id, reason="r")
    spanish.title = "Iron Gold"  # a mis-attached volume; repair detaches it
    await db_session.flush()
    await repair(db_session, commit=False)
    assert await fresh(db_session, Work.representative_book_id, work.id) != spanish.id
    with pytest.raises(Conflict, match="changed since"):
        await revert(db_session, lib, c)


async def test_a_cover_fix_is_the_latest_fix_on_its_book(db_session):
    lib = await make_user(db_session, librarian=True)
    work, _, spanish = await book_with_two_covers(db_session)
    move = await set_series(db_session, lib, work, new_series_name="The Red Rising Saga", reason="r")
    cover = await set_cover(db_session, lib, work, spanish.id, reason="r")
    with pytest.raises(Conflict, match="later fix"):
        await revert(db_session, lib, move)
    await revert(db_session, lib, cover)
    await revert(db_session, lib, move)
```

- [ ] **Step 2: Run the tests and watch them fail**

Run: `PYTEST tests/test_librarian_covers.py -v`
Expected: `ModuleNotFoundError: No module named 'app.services.librarian.covers'`.

- [ ] **Step 3: Implement the service**

`backend/app/services/librarian/covers.py`:

```python
"""Which picture a book wears (roadmap 06).

A choice pins ``works.representative_book_id``; ``works._refresh_work`` keeps
it. Open Library's curated image has no ``books`` row, so choosing it pins
``None`` — ``load_work_presentation`` then falls back to ``ol_cover_id``.
Runtime-only: the overrides format has no cover entry.
"""

from typing import NamedTuple
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Book, CatalogCorrection, CorrectionOp, Series, User, Work
from app.services.librarian.errors import Invalid, NotFound
from app.services.librarian.record import clean_reason, live_work, locked, record
from app.services.open_library import cover_url as ol_cover_url
from app.services.works import cover_pin, edition_rank

RUNTIME_ONLY = "the overrides format has no cover entry"
OL_CURATED = "ol_curated"  # CoverOption.source of Open Library's own image


class CoverChoice(NamedTuple):
    book_id: UUID | None
    cover_url: str


class CoverCandidate(NamedTuple):
    book_id: UUID | None
    cover_url: str
    title: str
    published_year: int | None
    language: str | None
    source: str
    current: bool


async def shown_cover(db: AsyncSession, work: Work) -> CoverChoice | None:
    """The cover ``load_work_presentation`` shows: the representative
    edition's, then Open Library's curated image, then none."""
    if work.representative_book_id is not None:
        rep = await db.get(Book, work.representative_book_id)
        if rep is not None and rep.cover_url:
            return CoverChoice(rep.id, rep.cover_url)
    url = ol_cover_url(work.ol_cover_id)
    return CoverChoice(None, url) if url else None


async def cover_options(db: AsyncSession, work: Work) -> list[CoverCandidate]:
    """Open Library's image first, then every edition with art, best-ranked
    first. An edition carrying the same URL as OL's image replaces it, so
    exactly one option can be current."""
    work = live_work(work)
    shown = await shown_cover(db, work)
    editions = (await db.execute(
        select(Book).where(Book.work_id == work.id, Book.cover_url.is_not(None))
    )).scalars().all()
    editions = sorted(editions, key=lambda e: (tuple(-t for t in edition_rank(e)), e.title, str(e.id)))

    options: list[CoverCandidate] = []
    seen: set[str] = set()
    for e in editions:
        if e.cover_url in seen:
            continue
        seen.add(e.cover_url)
        options.append(CoverCandidate(e.id, e.cover_url, e.title, e.published_year, e.language, e.source,
                                      shown is not None and shown.book_id == e.id))
    ol = ol_cover_url(work.ol_cover_id)
    if ol and ol not in seen:
        options.insert(0, CoverCandidate(None, ol, work.title, work.first_publish_year, None, OL_CURATED,
                                         shown == CoverChoice(None, ol)))
    return options


async def set_cover(db: AsyncSession, user: User, work: Work, book_id: UUID | None, *,
                    reason: str) -> CatalogCorrection:
    reason = clean_reason(reason)
    work = live_work(await locked(db, work))
    if book_id is None:
        url = ol_cover_url(work.ol_cover_id)
        if url is None:
            raise Invalid(f"{work.title} has no Open Library cover to choose.")
    else:
        book = await db.get(Book, book_id)
        if book is None:
            raise NotFound("Unknown edition.")
        if book.work_id != work.id:
            raise Invalid(f"That is not an edition of {work.title}.")
        if not book.cover_url:
            raise Invalid("That edition has no cover.")
        url = book.cover_url
    pinned = await cover_pin(db, work.id)
    if pinned is not None and pinned.book_id == book_id:
        raise Invalid("That is already the chosen cover.")

    prior = work.representative_book_id
    work.representative_book_id = book_id
    await db.flush()
    return await record(
        db, op=CorrectionOp.set_cover, user=user, reason=reason,
        payload={"work": str(work.id), "book_id": str(book_id) if book_id else None, "cover_url": url},
        entries=None, runtime_only_reason=RUNTIME_ONLY,
        snapshot={"prior": str(prior) if prior else None},  # for the log; undo re-derives
        work=work, series=await db.get(Series, work.series_id),
    )
```

- [ ] **Step 4: Implement undo**

In `backend/app/services/librarian/undo.py`:

Add the import:

```python
from app.services.works import _refresh_work
```

Add `CorrectionOp.set_cover` to `UNDOABLE`:

```python
UNDOABLE = frozenset({CorrectionOp.set_series, CorrectionOp.set_position, CorrectionOp.rename_series,
                      CorrectionOp.remove_from_series, CorrectionOp.reject_series, CorrectionOp.set_cover})
```

Add above `_REVERT`:

```python
async def _undo_set_cover(db: AsyncSession, c: CatalogCorrection) -> None:
    """Re-derive the cover as if this fix never happened: an older pin, or the ranking."""
    work = await db.get(Work, c.work_id) if c.work_id else None
    if work is None or work.merged_into_id is not None:
        raise Conflict(_STALE)
    await db.refresh(work)
    pinned = UUID(c.payload["book_id"]) if c.payload["book_id"] else None
    if work.representative_book_id != pinned:
        raise Conflict(_STALE)
    await _refresh_work(db, work, ignore_pin=c.id)
    await db.flush()
```

and register it:

```python
    CorrectionOp.reject_series: _undo_reject,
    CorrectionOp.set_cover: _undo_set_cover,
}
```

- [ ] **Step 5: Re-export**

In `backend/app/services/librarian/__init__.py`, add:

```python
from app.services.librarian.covers import cover_options, set_cover  # noqa: E402,F401
```

- [ ] **Step 6: Run the tests**

Run: `PYTEST tests/test_librarian_covers.py tests/test_librarian_undo.py tests/test_cover_pin.py -v`
Expected: all PASS (one SKIPPED in `test_cover_pin.py`).

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/librarian/covers.py backend/app/services/librarian/undo.py \
        backend/app/services/librarian/__init__.py backend/tests/test_librarian_covers.py
git commit -m "feat(librarian): list a book's covers, pin one with a reason, undo re-derives it"
```

---

### Task 3: Automatic merges carry a pin; a release load keeps an OL pin

**Files:**
- Create: `backend/app/services/librarian/carry.py`, `backend/tests/test_catalog_loader_cover_pin.py`
- Modify: `backend/app/services/works.py:424-475` (`merge_works`), `backend/app/services/librarian/identity.py:44`, `backend/app/services/catalog_loader.py:232-235`, `backend/tests/test_cover_pin.py` (unskip)

**Interfaces:**
- Consumes: `works.cover_pin`, `covers.set_cover`.
- Produces: `async carry.carry_fixes(db, source: Work, target: Work) -> int` (the number of corrections re-pointed). `merge_works(db, source, target, *, carry_fixes: bool = True) -> Work`. Item 07 extends `carry_fixes` to `set_metadata`. A carried correction's payload gains `"carried_from": "<source uuid>"`, and its `payload["work"]`, `work_id` and `series_id` name the target.

- [ ] **Step 1: Write the failing tests**

`backend/tests/test_catalog_loader_cover_pin.py`:

```python
"""Roadmap 06: a catalog release never undoes a librarian's cover."""

from app.models import Work
from app.services.catalog_loader import load_release, read_release
from app.services.librarian.covers import set_cover
from app.services.librarian.undo import revert
from app.services.works import merge_works
from tests.librarian_factories import fresh, make_edition, make_user, make_work
from tests.test_catalog_loader import ALIASES, ED_RED, EDITIONS, MEMBERS, RED, SERIES, WORKS, runtime_work

TABLES = dict(series=SERIES, works=[{**WORKS[0], "ol_cover_id": 7316188}, *WORKS[1:]],
              series_members=MEMBERS, editions=EDITIONS, work_aliases=ALIASES)


async def test_a_release_does_not_refill_a_cover_set_to_open_librarys(db_session, write_release):
    await load_release(db_session, read_release(write_release("2026.10.1", **TABLES)))
    assert await fresh(db_session, Work.representative_book_id, RED) == ED_RED
    lib = await make_user(db_session, librarian=True)
    await set_cover(db_session, lib, await db_session.get(Work, RED), None, reason="the canonical art")

    await load_release(db_session, read_release(write_release("2026.10.2", **TABLES)))

    assert await fresh(db_session, Work.representative_book_id, RED) is None


async def test_a_release_refills_it_after_undo(db_session, write_release):
    await load_release(db_session, read_release(write_release("2026.10.1", **TABLES)))
    lib = await make_user(db_session, librarian=True)
    red = await db_session.get(Work, RED)
    c = await set_cover(db_session, lib, red, None, reason="r")
    await revert(db_session, lib, c)
    red.representative_book_id = None  # as if the ranking had nothing to pick
    await db_session.flush()

    await load_release(db_session, read_release(write_release("2026.10.2", **TABLES)))

    assert await fresh(db_session, Work.representative_book_id, RED) == ED_RED


async def test_an_adopted_runtime_work_keeps_its_librarians_cover(db_session, write_release):
    lib = await make_user(db_session, librarian=True)
    runtime = await runtime_work(db_session, "OL30W")
    spanish = await make_edition(db_session, runtime, language="es", cover_url="https://img.test/es.jpg")
    c = await set_cover(db_session, lib, runtime, spanish.id, reason="the art readers know")

    await load_release(db_session, read_release(write_release("2026.10.1", **TABLES)))

    assert await fresh(db_session, Work.representative_book_id, RED) == spanish.id  # not ED_RED
    await db_session.refresh(c)
    assert c.work_id == RED
    assert c.payload["work"] == str(RED) and c.payload["carried_from"] == str(runtime.id)


async def test_an_automatic_merge_carries_an_edition_pin(db_session):
    lib = await make_user(db_session, librarian=True)
    twin = await make_work(db_session, "Red Rising", author="Pierce Brown")  # heuristic
    target = await make_work(db_session, "Red Rising", ol_id="OL30W", author="Pierce Brown")
    await make_edition(db_session, target, cover_url="https://img.test/en.jpg")
    spanish = await make_edition(db_session, twin, language="es", cover_url="https://img.test/es.jpg")
    c = await set_cover(db_session, lib, twin, spanish.id, reason="r")

    await merge_works(db_session, twin, target)  # what _absorb_heuristic_twin does

    await db_session.refresh(c)
    assert c.work_id == target.id and c.payload["carried_from"] == str(twin.id)
    assert target.representative_book_id == spanish.id


async def test_an_automatic_merge_does_not_carry_an_open_library_pin(db_session):
    lib = await make_user(db_session, librarian=True)
    twin = await make_work(db_session, "Red Rising", author="Pierce Brown")
    twin.ol_cover_id = 1
    target = await make_work(db_session, "Red Rising", ol_id="OL30W", author="Pierce Brown")
    english = await make_edition(db_session, target, cover_url="https://img.test/en.jpg")
    spanish = await make_edition(db_session, twin, language="es", cover_url="https://img.test/es.jpg")
    older = await set_cover(db_session, lib, twin, spanish.id, reason="r")
    newest = await set_cover(db_session, lib, twin, None, reason="r")  # OL's image of the *twin*

    await merge_works(db_session, twin, target)

    await db_session.refresh(older)
    await db_session.refresh(newest)
    # The librarian's latest word was an image only the twin carries; an older
    # choice they replaced is not resurrected on the survivor either.
    assert older.work_id == twin.id and newest.work_id == twin.id
    assert target.representative_book_id == english.id


async def test_the_targets_own_pin_wins_over_a_carried_one(db_session):
    lib = await make_user(db_session, librarian=True)
    twin = await make_work(db_session, "Red Rising", author="Pierce Brown")
    target = await make_work(db_session, "Red Rising", ol_id="OL30W", author="Pierce Brown")
    english = await make_edition(db_session, target, cover_url="https://img.test/en.jpg")
    spanish = await make_edition(db_session, twin, language="es", cover_url="https://img.test/es.jpg")
    await set_cover(db_session, lib, target, english.id, reason="r")
    theirs = await set_cover(db_session, lib, twin, spanish.id, reason="r")

    await merge_works(db_session, twin, target)

    await db_session.refresh(theirs)
    assert theirs.work_id == twin.id
    assert target.representative_book_id == english.id
```

- [ ] **Step 2: Run the tests and watch them fail**

Run: `PYTEST tests/test_catalog_loader_cover_pin.py -v`
Expected: `test_a_release_does_not_refill…` FAILS (`assert UUID(ED_RED) is None`). `test_an_adopted…` and `test_an_automatic_merge_carries_an_edition_pin` FAIL (`c.work_id` still names the source). `test_a_release_refills_it_after_undo`, `…does_not_carry_an_open_library_pin` and `test_the_targets_own_pin_wins…` PASS already.

- [ ] **Step 3: Implement the carry**

`backend/app/services/librarian/carry.py`:

```python
"""Librarian fixes that follow an *automatic* merge (roadmap 06).

Search absorbing a heuristic twin and a release adopting a runtime work are
the same book changing rows; a librarian's choice about it must not be lost
with the tombstone. A librarian merge decides these itself, so it never calls
this (identity.merge passes ``carry_fixes=False``).
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import CatalogCorrection, CorrectionOp, Work
from app.services.works import cover_pin


async def carry_fixes(db: AsyncSession, source: Work, target: Work) -> int:
    """Re-point the source's unreverted edition cover pins at the target.

    Runs after the editions moved and before the target is re-picked. Skipped
    when the target has a pin of its own, or when the source's newest pin is
    Open Library's image — ``None`` on the target would name a different
    record's picture.
    """
    newest = await cover_pin(db, source.id)
    if newest is None or newest.book_id is None or await cover_pin(db, target.id) is not None:
        return 0
    pins = (await db.execute(select(CatalogCorrection).where(
        CatalogCorrection.work_id == source.id,
        CatalogCorrection.op == CorrectionOp.set_cover,
        CatalogCorrection.reverted_at.is_(None),
    ).order_by(CatalogCorrection.created_at, CatalogCorrection.id))).scalars().all()
    carried = 0
    for c in pins:
        if c.payload.get("book_id") is None:
            continue  # an OL pin stays on the tombstone, inert
        c.work_id, c.series_id = target.id, target.series_id
        c.payload = {**c.payload, "work": str(target.id), "carried_from": str(source.id)}
        carried += 1
    await db.flush()
    return carried
```

- [ ] **Step 4: Call it from `merge_works`, and not from a librarian merge**

In `backend/app/services/works.py`, change the signature and add the call between the `update(Work)…merged_into_id` statement and the tombstone clean-up:

```python
async def merge_works(db: AsyncSession, source: Work, target: Work, *, carry_fixes: bool = True) -> Work:
    """Fold ``source`` into ``target``, leaving a tombstone behind.

    Editions, threads and shelves move; the source row survives with
    ``merged_into_id`` set so its URLs keep resolving. ``carry_fixes`` moves a
    librarian's cover choice onto the target — right for automatic merges
    (search, catalog releases), wrong for a librarian merge, which decides.
    """
```

```python
    await db.execute(
        update(Work).where(Work.merged_into_id == source.id).values(merged_into_id=target.id)
    )
    if carry_fixes:
        # Imported here: services/librarian imports this module.
        from app.services.librarian.carry import carry_fixes as carry

        await carry(db, source, target)
```

(The rest of `merge_works` is unchanged; its closing `_refresh_work(db, target)` now honours the carried pin.)

In `backend/app/services/librarian/identity.py`, change the merge call:

```python
    await merge_works(db, source, target, carry_fixes=False)
```

In `backend/tests/test_cover_pin.py`, delete the `@pytest.mark.skip(...)` line above `test_a_librarian_merge_does_not_carry_the_sources_pin`.

- [ ] **Step 5: Guard the loader's refill**

In `backend/app/services/catalog_loader.py`, replace the representative statement in `_UPSERTS`:

```python
    # Enrichment may have picked a better representative since; keep it. A NULL
    # that is a librarian's "use Open Library's image" (the newest unreverted
    # set_cover names no edition) is a choice too.
    """UPDATE works w SET representative_book_id = t.representative_edition_id
       FROM stage_works t WHERE w.id = t.id AND w.representative_book_id IS NULL
         AND t.representative_edition_id IS NOT NULL
         AND NOT EXISTS (
             SELECT 1 FROM (SELECT c.payload ->> 'book_id' AS book_id FROM catalog_corrections c
                            WHERE c.work_id = w.id AND c.op = 'set_cover' AND c.reverted_at IS NULL
                            ORDER BY c.created_at DESC, c.id DESC LIMIT 1) pin
             WHERE pin.book_id IS NULL AND w.ol_cover_id IS NOT NULL)""",
```

- [ ] **Step 6: Run the tests**

Run: `PYTEST tests/test_catalog_loader_cover_pin.py tests/test_catalog_loader.py tests/test_catalog_runtime.py tests/test_cover_pin.py tests/test_librarian_identity.py tests/test_works.py tests/test_work_resolution.py -v`
Expected: all PASS, none skipped.

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/librarian/carry.py backend/app/services/works.py backend/app/services/librarian/identity.py \
        backend/app/services/catalog_loader.py backend/tests/test_catalog_loader_cover_pin.py backend/tests/test_cover_pin.py
git commit -m "feat(librarian): a librarian's cover survives automatic merges and release loads"
```

---

### Task 4: Routes

**Files:**
- Modify: `backend/app/schemas/librarian.py`, `backend/app/api/librarian.py`, `backend/tests/test_librarian_api.py`

**Interfaces:**
- Consumes: `librarian.cover_options`, `librarian.set_cover`, `correction_out`.
- Produces: `CoverIn {book_id: UUID | None = None, reason: str}`; `CoverOption {book_id: UUID | None, cover_url: str, title: str, published_year: int | None, language: str | None, source: str, current: bool}`; `GET /api/librarian/works/{work_id}/covers` → `list[CoverOption]`; `POST /api/librarian/works/{work_id}/cover` → 201 `CorrectionOut`.

- [ ] **Step 1: Write the failing tests**

In `backend/tests/test_librarian_api.py`, add to `WRITES`:

```python
    (f"/api/librarian/works/{ANY}/cover", {"book_id": None, "reason": "r"}),
```

add to `READS`:

```python
READS = ["/api/librarian/corrections", "/api/librarian/series-search?q=a", f"/api/librarian/works/{ANY}/editions",
         f"/api/librarian/works/{ANY}/covers"]
```

and append:

```python
async def test_a_librarian_picks_a_cover_and_undoes_it(client, db_session):
    librarian = await make_user(db_session, librarian=True)
    lib = headers_for(librarian)
    book = await make_work(db_session, "Red Rising", ol_id="OL30W", author="Pierce Brown")
    book.ol_cover_id = 7316188
    english = await make_edition(db_session, book, cover_url="https://img.test/en.jpg")
    spanish = await make_edition(db_session, book, language="es", cover_url="https://img.test/es.jpg")
    book.representative_book_id = english.id
    await db_session.flush()
    slug = (await db_session.get(Series, book.series_id)).slug

    options = (await client.get(f"/api/librarian/works/{book.id}/covers", headers=lib)).json()
    assert [(o["book_id"], o["source"], o["current"]) for o in options] == [
        (None, "ol_curated", False), (str(english.id), "google_books", True), (str(spanish.id), "google_books", False)]
    assert options[2] == {"book_id": str(spanish.id), "cover_url": "https://img.test/es.jpg", "title": "Red Rising",
                          "published_year": None, "language": "es", "source": "google_books", "current": False}

    resp = await client.post(f"/api/librarian/works/{book.id}/cover",
                             json={"book_id": str(spanish.id), "reason": "the edition readers know"}, headers=lib)
    assert resp.status_code == 201, resp.text
    out = resp.json()
    assert out["op"] == "set_cover" and out["exportable"] is False and out["undoable"] is True
    assert out["runtime_only_reason"] == "the overrides format has no cover entry"
    assert out["subject"] == "Red Rising" and out["room_slug"] == slug
    page = (await client.get(f"/api/series/{slug}")).json()
    assert page["works"][0]["cover_url"] == "https://img.test/es.jpg"

    assert (await client.post(f"/api/librarian/corrections/{out['id']}/revert", headers=lib)).status_code == 200
    page = (await client.get(f"/api/series/{slug}")).json()
    assert page["works"][0]["cover_url"] == "https://img.test/en.jpg"


async def test_cover_refusals_map_to_statuses(client, db_session):
    lib = headers_for(await make_user(db_session, librarian=True))
    book = await make_work(db_session, "Red Rising", ol_id="OL30W", author="Pierce Brown")
    blank = await client.post(f"/api/librarian/works/{book.id}/cover", json={"book_id": None, "reason": " "}, headers=lib)
    assert blank.status_code == 422
    no_ol = await client.post(f"/api/librarian/works/{book.id}/cover", json={"book_id": None, "reason": "r"}, headers=lib)
    assert no_ol.status_code == 422 and "no Open Library cover" in no_ol.json()["detail"]
    unknown = await client.post(f"/api/librarian/works/{book.id}/cover", json={"book_id": ANY, "reason": "r"}, headers=lib)
    assert unknown.status_code == 404
```

- [ ] **Step 2: Run the tests and watch them fail**

Run: `PYTEST tests/test_librarian_api.py -v`
Expected: `test_every_route_refuses_readers_and_anonymous` FAILS (`404 != 403` for `/cover`), and the two new tests FAIL with 404/405.

- [ ] **Step 3: Add the schemas**

In `backend/app/schemas/librarian.py`, add after `DissolveIn`:

```python
class CoverIn(_Reasoned):
    # null = Open Library's curated image, which has no edition row.
    book_id: UUID | None = None
```

and after `EditionOut`:

```python
class CoverOption(BaseModel):
    """One picture a book could wear. ``book_id`` null and ``source`` 'ol_curated'
    is Open Library's own image; otherwise an edition's."""

    book_id: UUID | None = None
    cover_url: str
    title: str
    published_year: int | None = None
    language: str | None = None
    source: str
    current: bool
```

- [ ] **Step 4: Add the routes**

In `backend/app/api/librarian.py`, extend the schema import with `CoverIn, CoverOption`, and add after `work_editions`:

```python
@router.get("/works/{work_id}/covers", response_model=list[CoverOption])
async def work_covers(work_id: UUID, db: AsyncSession = Depends(get_db),
                      user: User = Depends(require_librarian)):
    work = await _work(db, work_id)
    options = await _run(librarian.cover_options(db, work))
    return [CoverOption(book_id=o.book_id, cover_url=o.cover_url, title=o.title, published_year=o.published_year,
                        language=o.language, source=o.source, current=o.current) for o in options]


@router.post("/works/{work_id}/cover", **_CREATED)
async def set_cover(work_id: UUID, body: CoverIn, db: AsyncSession = Depends(get_db),
                    user: User = Depends(require_librarian)):
    work = await _work(db, work_id)
    c = await _run(librarian.set_cover(db, user, work, body.book_id, reason=body.reason))
    return await correction_out(db, c)
```

- [ ] **Step 5: Run the tests**

Run: `PYTEST tests/test_librarian_api.py tests/test_openapi.py -v`
Expected: all PASS.

- [ ] **Step 6: Run the whole backend suite**

Run: `PYTEST`
Expected: every test passes.

- [ ] **Step 7: Commit**

```bash
git add backend/app/schemas/librarian.py backend/app/api/librarian.py backend/tests/test_librarian_api.py
git commit -m "feat(librarian): GET works/{id}/covers and POST works/{id}/cover"
```

---

### Task 5: `useWorkCovers` and `CoverGrid`

**Files:**
- Create: `frontend/src/components/librarian/CoverGrid.jsx`, `frontend/src/components/librarian/CoverGrid.test.jsx`
- Modify: `frontend/src/api/librarian.js`

**Interfaces:**
- Produces: `useWorkCovers(workId | null)` → React Query result of `CoverOption[]`, key `['librarian', 'covers', workId]`, disabled when `workId` is falsy. `<CoverGrid options={CoverOption[]} loaded={boolean} value={CoverOption | null} onChange={(option) => void} />`, default export.

- [ ] **Step 1: Write the failing test**

`frontend/src/components/librarian/CoverGrid.test.jsx`:

```jsx
import { describe, it, expect, vi } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import CoverGrid from './CoverGrid'

const OPTIONS = [
  { book_id: null, cover_url: 'https://img.test/ol.jpg', title: 'Red Rising', published_year: 2014, language: null, source: 'ol_curated', current: false },
  { book_id: 'e1', cover_url: 'https://img.test/en.jpg', title: 'Red Rising', published_year: 2015, language: 'en', source: 'google_books', current: true },
  { book_id: 'e2', cover_url: 'https://img.test/es.jpg', title: 'Amanecer rojo', published_year: 2016, language: 'es', source: 'openlibrary', current: false },
]

describe('CoverGrid', () => {
  it('offers every option and marks the current one', () => {
    render(<CoverGrid options={OPTIONS} loaded value={null} onChange={vi.fn()} />)
    const radios = screen.getAllByRole('radio')
    expect(radios).toHaveLength(3)
    expect(screen.getByRole('radio', { name: /Red Rising, open library · 2014/ })).toBeInTheDocument()
    expect(screen.getByRole('radio', { name: /2015 · en, current/ })).toBeInTheDocument()
    expect(screen.getAllByText('current')).toHaveLength(1)
  })

  it('chooses an option', async () => {
    const onChange = vi.fn()
    render(<CoverGrid options={OPTIONS} loaded value={null} onChange={onChange} />)
    await userEvent.click(screen.getByRole('radio', { name: /Amanecer rojo/ }))
    expect(onChange).toHaveBeenCalledWith(OPTIONS[2])
  })

  it('marks a broken image and will not choose it', async () => {
    const onChange = vi.fn()
    const { container } = render(<CoverGrid options={OPTIONS} loaded value={null} onChange={onChange} />)
    fireEvent.error(container.querySelector('img[src="https://img.test/es.jpg"]'))
    const broken = screen.getByRole('radio', { name: /Amanecer rojo.*image did not load/ })
    expect(broken).toBeDisabled()
    expect(screen.getByText('image did not load')).toBeInTheDocument()
    await userEvent.click(broken)
    expect(onChange).not.toHaveBeenCalled()
    expect(screen.getByRole('radio', { name: /2015 · en/ })).toBeEnabled()
  })

  it('says so when no edition has a cover', () => {
    render(<CoverGrid options={[]} loaded value={null} onChange={vi.fn()} />)
    expect(screen.getByText(/No edition of this book has a cover yet/)).toBeInTheDocument()
  })
})
```

- [ ] **Step 2: Run it and watch it fail**

Run: `cd frontend && npx vitest run src/components/librarian/CoverGrid.test.jsx`
Expected: FAIL, `Failed to resolve import "./CoverGrid"`.

- [ ] **Step 3: Add the hook**

In `frontend/src/api/librarian.js`, add after `useWorkEditions`:

```js
export function useWorkCovers(workId) {
  return useQuery({
    queryKey: ['librarian', 'covers', workId],
    queryFn: () => client.get(`/librarian/works/${workId}/covers`).then((r) => r.data),
    enabled: !!workId,
  })
}
```

- [ ] **Step 4: Implement the grid**

`frontend/src/components/librarian/CoverGrid.jsx`:

```jsx
import { useState } from 'react'

/** "open library · 2014", "2015 · en": what tells two printings' art apart. */
function factsOf(option) {
  const source = option.source === 'ol_curated' ? 'open library' : null
  return [source, option.published_year, option.language].filter(Boolean).join(' · ')
}

function CoverTile({ option, checked, onChoose }) {
  // A broken image is never a cover: say so, and refuse the choice.
  const [broken, setBroken] = useState(false)
  const facts = factsOf(option)
  const name = [option.title, facts, option.current && 'current', broken && 'image did not load']
    .filter(Boolean).join(', ')
  return (
    <label className={`flex flex-col gap-1 p-1 border transition-colors duration-fast focus-within:border-accent ${
      checked ? 'border-accent' : 'border-line'} ${broken ? '' : 'cursor-pointer hover:border-accent'}`}>
      <input type="radio" name="lib-cover" className="sr-only" aria-label={name}
             checked={checked} disabled={broken} onChange={() => onChoose(option)} />
      {broken ? (
        <div className="w-full aspect-[2/3] bg-panel flex items-center justify-center p-2">
          <span className="text-ink-dim text-xs text-center">image did not load</span>
        </div>
      ) : (
        // Covers carry the colour: full size in the tile, never dimmed.
        <img src={option.cover_url} alt="" onError={() => setBroken(true)} className="w-full" />
      )}
      {facts && <span className="text-ink-dim text-xs tabular-nums">{facts}</span>}
      {option.current && <span className="text-ink text-xs">current</span>}
    </label>
  )
}

/** Every picture a book could wear, as one radio group. */
function CoverGrid({ options, loaded, value, onChange }) {
  if (loaded && options.length === 0) {
    return <p className="alert-muted">No edition of this book has a cover yet.</p>
  }
  return (
    <div role="radiogroup" aria-label="Covers" className="grid grid-cols-3 gap-3">
      {options.map((option) => (
        <CoverTile key={option.book_id ?? 'ol'} option={option}
                   checked={value?.book_id === option.book_id && value?.cover_url === option.cover_url}
                   onChoose={onChange} />
      ))}
    </div>
  )
}

export default CoverGrid
```

- [ ] **Step 5: Run it**

Run: `cd frontend && npx vitest run src/components/librarian/CoverGrid.test.jsx`
Expected: 4 passed.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/api/librarian.js frontend/src/components/librarian/CoverGrid.jsx \
        frontend/src/components/librarian/CoverGrid.test.jsx
git commit -m "feat(web): CoverGrid — every cover a book could wear, broken images refused"
```

---

### Task 6: The `cover` row action and panel, end to end

**Files:**
- Create: `frontend/e2e/librarian-cover.spec.js`
- Modify: `frontend/src/components/LibrarianPanel.jsx`, `frontend/src/components/LibrarianPanel.test.jsx`, `frontend/src/pages/Series.jsx:74`, `frontend/src/pages/Series.test.jsx:200`

**Interfaces:**
- Consumes: `useWorkCovers`, `CoverGrid`, `POST /librarian/works/{id}/cover`.
- Produces: action kind `'cover'` in `LibrarianPanel` (`TITLES.cover = 'Set cover'`); row action button `cover <title>` in edit mode. Item 10's `c` shortcut opens this action.

- [ ] **Step 1: Write the failing tests**

Append to the `describe` in `frontend/src/components/LibrarianPanel.test.jsx`:

```jsx
  it('sets a cover from the grid', async () => {
    client.get.mockResolvedValue({ data: [
      { book_id: 'e1', cover_url: 'https://img.test/en.jpg', title: 'Dune', published_year: 1965, language: 'en', source: 'openlibrary', current: true },
      { book_id: null, cover_url: 'https://img.test/ol.jpg', title: 'Dune', published_year: 1965, language: null, source: 'ol_curated', current: false },
    ] })
    client.post.mockResolvedValue({ data: { ...CORRECTION, op: 'set_cover' } })
    const onDone = renderPanel({ kind: 'cover', work: BOOK })
    const submit = screen.getByRole('button', { name: 'Set cover' })
    await userEvent.click(await screen.findByRole('radio', { name: /open library/ }))
    expect(submit).toBeDisabled() // still needs a reason
    await userEvent.type(screen.getByLabelText('Reason'), 'the canonical art')
    await userEvent.click(submit)
    await waitFor(() => expect(client.post).toHaveBeenCalledWith('/librarian/works/w1/cover',
      { reason: 'the canonical art', book_id: null }))
    expect(onDone).toHaveBeenCalled()
    expect(client.get).toHaveBeenCalledWith('/librarian/works/w1/covers')
    expect(screen.getByText(/description follows the chosen edition/)).toBeInTheDocument()
  })
```

In `frontend/src/pages/Series.test.jsx`, test `shows row and header actions in edit mode…`, change the loop list to:

```jsx
    for (const name of ['move', 'position', 'remove', 'merge into…', 'split', 'cover']) {
```

- [ ] **Step 2: Run them and watch them fail**

Run: `cd frontend && npx vitest run src/components/LibrarianPanel.test.jsx src/pages/Series.test.jsx`
Expected: FAIL. `Unable to find role="button" and name "Set cover"` and `…name "cover Red Rising"`.

- [ ] **Step 3: Add the action to the panel**

In `frontend/src/components/LibrarianPanel.jsx`:

Imports:

```jsx
import { confirmationOf, useLibrarianAction, useSeriesSearch, useWorkCovers, useWorkEditions } from '../api/librarian'
import CoverGrid from './librarian/CoverGrid'
```

`TITLES` gains `cover: 'Set cover'`:

```jsx
const TITLES = {
  move: 'Move', position: 'Set position', remove: 'Remove from series', merge: 'Merge',
  split: 'Split', rename: 'Rename', dissolve: 'Dissolve', cover: 'Set cover',
}
```

In `request`, add before `default:`:

```jsx
    case 'cover':
      // book_id null is Open Library's own image, which has no edition row.
      return { path: `works/${work.id}/cover`, body: { reason, book_id: f.cover?.book_id ?? null } }
```

In `ready`, add before `return true`:

```jsx
  if (kind === 'cover') return !!f.cover
```

In `LibrarianPanel`, add `cover: null` to the initial `fields` object (after `editions: []`), and after the `editionsQuery` lines:

```jsx
  const coversQuery = useWorkCovers(kind === 'cover' ? work.id : null)
```

The float may now be taller than the viewport. Add `max-h-full overflow-y-auto` to the dialog's class list:

```jsx
           onKeyDown={trapTab} className="float w-full max-w-prose max-h-full overflow-y-auto flex flex-col gap-4 p-5">
```

In the form, after the `split` line:

```jsx
            {kind === 'cover' && (
              <div className="flex flex-col gap-2">
                <p className="text-ink-dim text-xs">The description follows the chosen edition.</p>
                <CoverGrid options={coversQuery.data ?? []} loaded={coversQuery.isSuccess}
                           value={fields.cover} onChange={set('cover')} />
              </div>
            )}
```

If item 02 has merged, the reason field is `ReasonField` and receives `kind`. It then offers the `cover` presets from `components/librarian/reasons.js` with no further change here.

- [ ] **Step 4: Add the row action**

In `frontend/src/pages/Series.jsx`, `BookRow`:

```jsx
            {(isSeries ? ['move', 'position', 'remove', 'merge into…', 'split', 'cover'] : ['move', 'merge into…', 'split', 'cover']).map((name) => (
```

- [ ] **Step 5: Run the unit tests**

Run: `cd frontend && npm test`
Expected: every test passes.

- [ ] **Step 6: Write the e2e scenario**

`frontend/e2e/librarian-cover.spec.js`:

```js
import { test, expect } from '@playwright/test'
import { grantLibrarian, openFirstSearchResult, registerViaUi } from './helpers'

// A librarian opens a book's covers, sees a dead image refused, picks another
// and gets a runtime-only fix. The cover routes and images are mocked; only
// the page itself comes from the stack.
const PNG = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII=', 'base64')

test('a librarian picks a cover and a broken one is refused', async ({ page }) => {
  const user = await registerViaUi(page)
  grantLibrarian(user)
  await page.reload()

  await page.route('https://img.e2e/good.png', (route) => route.fulfill({ status: 200, contentType: 'image/png', body: PNG }))
  await page.route('https://img.e2e/dead.png', (route) => route.fulfill({ status: 404 }))
  await page.route('**/api/librarian/works/*/covers', (route) => route.fulfill({ json: [
    { book_id: 'e2e-1', cover_url: 'https://img.e2e/good.png', title: 'Good', published_year: 2001, language: 'en', source: 'openlibrary', current: true },
    { book_id: 'e2e-2', cover_url: 'https://img.e2e/dead.png', title: 'Dead', published_year: 2002, language: 'en', source: 'google_books', current: false },
    { book_id: null, cover_url: 'https://img.e2e/good.png?ol', title: 'Good', published_year: 2001, language: null, source: 'ol_curated', current: false },
  ] }))
  await page.route('https://img.e2e/good.png?ol', (route) => route.fulfill({ status: 200, contentType: 'image/png', body: PNG }))
  let posted = null
  await page.route('**/api/librarian/works/*/cover', (route) => {
    posted = route.request().postDataJSON()
    return route.fulfill({ status: 201, json: {
      id: 'c-e2e', op: 'set_cover', reason: posted.reason, created_at: new Date().toISOString(), user: user.username,
      exportable: false, runtime_only_reason: 'the overrides format has no cover entry', undoable: true,
      reverted_at: null, room_slug: null, subject: 'Good' } })
  })

  await openFirstSearchResult(page, 'the left hand of darkness')
  await page.getByRole('link', { name: '[edit]' }).click()
  const books = page.getByRole('list', { name: 'Books in this series' })
  const title = await books.getByRole('heading').first().textContent()
  await books.getByRole('button', { name: `cover ${title}`, exact: true }).click()

  const dialog = page.getByRole('dialog', { name: `Set cover ${title}` })
  await expect(dialog.getByRole('radio', { name: /Dead.*image did not load/ })).toBeDisabled()
  await expect(dialog.getByText('current')).toBeVisible()
  await dialog.getByRole('radio', { name: /open library/ }).check({ force: true }) // sr-only input
  await dialog.getByLabel('Reason').fill('e2e: the canonical art')
  await dialog.getByRole('button', { name: 'Set cover', exact: true }).click()

  const status = page.getByRole('group', { name: 'Librarian fix result' })
  await expect(status.getByText(/runtime-only: the overrides format has no cover entry/)).toBeVisible()
  expect(posted).toEqual({ reason: 'e2e: the canonical art', book_id: null })
})
```

Run (stack up in another terminal: `docker compose up --build`): `cd frontend && npx playwright test e2e/librarian-cover.spec.js`
Expected: 1 passed.

- [ ] **Step 7: §36 check**

Open a series page in edit mode, click `cover`, and look. The tiles are square-cornered, the art is full colour, the selection is an `accent` border, and there is no card shadow or rounded thumbnail. If it reads as a generic image picker from a SaaS dashboard, tighten it to the grid rules in `docs/visual-identity.md` before continuing.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/components/LibrarianPanel.jsx frontend/src/components/LibrarianPanel.test.jsx \
        frontend/src/pages/Series.jsx frontend/src/pages/Series.test.jsx frontend/e2e/librarian-cover.spec.js
git commit -m "feat(web): cover row action — pick a book's cover from every edition's"
```

---

### Task 7: Docs and tracker

**Files:**
- Modify: `docs/librarian-ux-roadmap.md`, `ROADMAP.md`, `CLAUDE.md`

- [ ] **Step 1: Roadmap notes**

In `docs/librarian-ux-roadmap.md`, under `## Notes`, replace the placeholder line with (or append after existing notes):

```markdown
- **2026-09-29 · 06 cover picker.** Open Library's curated cover has no book
  row: it is `CoverOption {book_id: null, source: "ol_curated"}` and
  `POST …/cover {book_id: null}` pins `representative_book_id = NULL`. A pin
  holds only while its edition is still the work's and has art (or, for
  OL's image, while `ol_cover_id` is set); otherwise it is inert, never
  deleted. The rule lives in `works._refresh_work` (`cover_pin`), so every
  re-pick honours it; the loader's NULL refill skips an OL pin; automatic
  merges (`merge_works(carry_fixes=True)`) carry edition pins, librarian
  merges do not (07 decides). Choosing a cover also chooses the description
  (both read through the representative). A cover fix is the latest fix on
  its book, so it blocks undoing an earlier move of that book until undone.
```

- [ ] **Step 2: ROADMAP.md**

In `ROADMAP.md`, Phase 5, in the **Librarian tools** row, change `in-app merge, split, move-to-series, reorder, rename, remove and dissolve` to `in-app merge, split, move-to-series, reorder, rename, remove, dissolve and cover choice`, and add `components/librarian/CoverGrid.jsx` to its *Touches* list.

- [ ] **Step 3: CLAUDE.md**

In `CLAUDE.md`:
- In the `services/` paragraph, change `` `works.py` owns the resolution ladder, `upsert_work_from_ol`, representative-edition selection and `merge_works` `` to `` `works.py` owns the resolution ladder, `upsert_work_from_ol`, representative-edition selection (which keeps a librarian's unreverted `set_cover` — `cover_pin`) and `merge_works` ``. Change the librarian module list `(`keys`, `record`, `placement`, `identity`, `undo`, `export`)` to `(`keys`, `record`, `placement`, `identity`, `covers`, `carry`, `undo`, `export`)`.
- In the paragraph that begins "A work may have **zero editions**", after "…which is how an English work wore a Spanish cover;", add: `a librarian's set_cover pins the representative (null = OL's image) and outranks all of that;`.
- In *Known remaining gaps*, change `Librarian tools cover merge/split/move/reorder/rename/remove/dissolve in-app;` to `Librarian tools cover merge/split/move/reorder/rename/remove/dissolve and cover choice in-app (cover choice is runtime-only: the overrides format has no cover entry);`.

- [ ] **Step 4: Tracker row (at merge time)**

When the PR merges, set row 06 to Status `✅`, Done `<YYYY-MM-DD>` and PR `#<n>`, and tick the **Roadmap item** checkbox at the top of this plan.

- [ ] **Step 5: Commit**

```bash
git add docs/librarian-ux-roadmap.md ROADMAP.md CLAUDE.md
git commit -m "docs: cover picker in the roadmap, CLAUDE.md and ROADMAP.md"
```

---

## Self-review

- **Spec coverage.** Row action and grid: Tasks 5–6. OL curated option: Task 2 (`cover_options`) and Decision 1. Current one marked: Tasks 2 and 5. Reason: `clean_reason` in Task 2, and the panel's required field in Task 6. `set_cover` op: Task 1. Covers endpoint and POST: Task 4. Picker and repair leave the work alone: Task 1 covers `_refresh_work` (search ingest, enrichment, `merge_works`, split, `repair_presentation` pass 4, `backfill_covers`). Task 3 covers the loader refill and adoption. `repair_presentation` pass 3 only nulls a representative whose edition belongs to another work, where the pin is inert by Decision 2. Runtime-only reason: Task 2 `RUNTIME_ONLY`. Undoable: Task 2. Broken-image handling: Task 5.
- **Types.** `CoverPin.book_id`, `CoverChoice`, `CoverCandidate` and `CoverOption` share field names and order. `set_cover(db, user, work, book_id, *, reason)` is the same in Tasks 2, 3 and 4 and in item 07. `carry_fixes` is both a kwarg of `merge_works` and a function in `carry.py`. The function is imported as `carry` inside `merge_works` so the two names never shadow each other.
- **Placeholders.** The one `<generated>` is the Alembic file name, which the roadmap forbids fixing in advance. Step 7 of Task 1 shows how to produce it.
