# Keep the Best of Both on Merge Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** In the merge preview, for each of title, cover and description, the librarian picks which book's version the surviving book keeps. The survivor then shows exactly what was picked, and no later search, enrichment or catalog release overwrites it.

**Architecture:** The merge body gains `keep`, which is stored in the merge correction's payload. Before merging, the service records what each side shows. After `merge_works`, it records follow-up corrections in the same transaction, only where the merged book would otherwise show something other than what was kept. A cover goes through item 06's `set_cover`. Title and description go through a new runtime-only op `set_metadata`. A kept title is written in place to `works.title`, and the catalog loader's upsert skips it while the fix is unreverted. A kept description goes to a new column `works.description_override`, which only `services/librarian` writes and which `load_work_presentation` reads first. Automatic merges carry `set_metadata` the way 06 carries cover pins. The frontend adds `KeepChoices` inside 04's `MergePreview`.

**Tech Stack:** FastAPI, async SQLAlchemy 2.0, Alembic, Pydantic v2, React 18 + React Query + Tailwind tokens, Vitest + RTL, Playwright.

**Spec:** docs/librarian-ux-roadmap.md §07 (Keep the best of both on merge), plus the "Keep the best (07)", "Cover (06)" and "Merge preview (04)" entries under *Shared names*. **Depends on 04 and 06 being merged.** This plan uses 04's `GET …/merge-preview`, `MergeSide` and `components/librarian/MergePreview.jsx`, and 06's `services/librarian/covers.py` (`shown_cover`, `set_cover`, `CoverChoice`), `services/librarian/carry.py` (`carry_fixes`) and `works._refresh_work`'s cover pin.

- [ ] **Roadmap item:** 07 — tick in docs/librarian-ux-roadmap.md when merged

## Global Constraints

- Repo rules in `CLAUDE.md` apply verbatim: `api/` thin, `services/librarian/` is the only writer of `catalog_corrections` (and, from this item, of `works.description_override`), async everywhere, schemas built explicitly.
- Merge body (binding): `keep: {title: 'source'|'target', cover: 'source'|'target', description: 'source'|'target'}`, each defaulting to `target`. Stored in the correction payload.
- `cover: 'source'` records a follow-up `set_cover` in the same transaction. `title`/`description` from source are recorded as a new op `set_metadata`, which is runtime-only: `runtime_only_reason = "the overrides format has no title or description entry"`.
- Merge stays non-undoable (item 16 changes that). Each follow-up is its own correction and is undoable under v1's rules.
- Every write carries a required non-empty `reason`. The follow-ups reuse the merge's reason.
- Migration: autogenerate at execution time (`down_revision` = the head then). `set_metadata` is added with `ALTER TYPE correction_op_enum ADD VALUE IF NOT EXISTS 'set_metadata'`. Downgrade drops the column and leaves the enum value, saying so in a comment.
- `<MergePreview preview onSwap />` keeps its props. This item adds optional `keep` and `onKeepChange`. Without them it renders exactly as 04 left it.
- Frontend: tokens only; no new radii, shadows, font sizes or durations; every glyph `aria-hidden`; serif only for book titles. §36 test.
- Tests: pytest against `margin_test`, Vitest + RTL, one Playwright scenario. Network always mocked.
- Branch `feat/librarian-lx07-merge-keep-best` from `main` (after 04 and 06 are merged); one commit per task; PR to `main`.
- **`PYTEST`** = `docker compose run --rm --no-deps -v "$PWD/pipeline:/pipeline:ro" -e DATABASE_URL=postgresql+asyncpg://margin:margin@db:5432/margin_test backend pytest <args>` (from the repo root). Frontend: `cd frontend && npx vitest run <path>`.

## Decisions this plan adds to the roadmap

1. **`keep` is honoured, not just recorded.** The rule is: *after the merge, the survivor shows the kept side's value; a follow-up is recorded only where the merge alone would show something else.* So `target` can also produce a follow-up. Merging an English edition into a book that wore a Spanish cover would otherwise re-rank the survivor onto the English art (and its blurb) behind the librarian's back. With the default `keep`, a merge that changes nothing the librarian can see records nothing extra. This extends the roadmap's "`cover: 'source'` records a follow-up `set_cover`". A default merge can record a `set_cover` (or a `set_metadata` for the description) to keep the target as it was.
2. **Where each override lives, and why nothing automatic overwrites it:**
   - **Cover**: 06's pin (`set_cover`, `representative_book_id`). `_refresh_work` and the loader already respect it.
   - **Title**: written in place to `works.title`. Search (`search_doc` is generated from it), every card and thread tag read that column, so a side column would miss most readers. Writers that could overwrite it: the catalog loader's works upsert (`title = EXCLUDED.title`), now `CASE`-guarded on an unreverted `set_metadata` naming a title. `upsert_work_from_ol` and `_upsert_work` never rewrite an existing work's title, and enrichment never writes one. `canonical_key` is never touched (CLAUDE.md: never re-derive it from the title).
   - **Description**: a new column `works.description_override`, read first by `load_work_presentation` (`override → representative edition → work`). An in-place write would lose to the representative edition's blurb on every read. Enrichment writes `works.description` and releases write no description, so neither can reach the override. Only `services/librarian` writes it.
   - **Automatic merges** (search absorbing a twin, release adoption) carry unreverted `set_metadata` onto the target, as 06 carries cover pins. The snapshots are rewritten to the target's values so that undo restores the target.
3. **A singleton's page name follows its book's title.** `GET /api/series/{slug}` answers a singleton with `name = its book's title`. A singleton "takes its book's title" (v1 already refuses to rename one), and a kept title must not leave the page heading on the old one.
4. **Some sources cannot be kept, and the merge is refused before anything happens:** `cover: 'source'` when the source shows no cover, or shows Open Library's own image (no `books` row moves with the merge; `null` on the target would mean the *target's* OL image); `description: 'source'` when the source shows none. All three are 422, checked before the confirmation step, so a librarian never confirms a merge that then fails. `MergeSide` gains **`cover_book_id`** so the UI can disable the OL-only case ahead of time. This is an extension of 04's shared `MergeSide`, made in the roadmap first (Task 1 Step 0).
5. **The merge payload records `keep` (all three fields, defaults filled) and `follow_ups: [correction ids]`** when any were made.
6. **Swapping sides resets `keep` to the defaults.** A choice made about the old pairing refers to the other book after a swap. Resetting is predictable and never sends a stale choice. Picking a different book to merge into resets it too.

## Review Focus

1. **A plain merge re-ranks the survivor's cover.** The source brings a better-ranked edition, and the librarian changed nothing in the preview. The survivor must keep the cover and blurb the preview showed (Task 3 `test_a_default_merge_keeps_what_the_target_showed`).
2. **Keeping the source's cover when that cover is Open Library's own image.** This must be refused before the merge. The UI disables the choice, and the server says why with a 422, never a half-merge (Task 3 `test_keep_refusals_happen_before_anything_merges`, Task 5 `disables what the source cannot give`).
3. **The next catalog release after a kept title.** The survivor must keep it, and take the release's title again once the fix is undone (Task 2 `test_a_release_keeps_a_librarians_title` and `…after_undo`).
4. **Enrichment on first view after a kept description.** Google fills the work's own description. The kept one must still show (Task 1 `test_enrichment_does_not_reach_a_kept_description`).
5. **The librarian swaps sides after choosing.** The choices must reset, not flip silently onto the other book (Task 5 `resets the choices when the sides swap`).

---

## File Structure

**Backend — create**
- `backend/alembic/versions/<generated>_description_override_and_set_metadata.py`.
- `backend/app/services/librarian/metadata.py` — `set_metadata`, `RUNTIME_ONLY`.
- `backend/tests/test_librarian_metadata.py` — presentation precedence, singleton name, `set_metadata`, undo, loader guard, carry.
- `backend/tests/test_librarian_merge_keep.py` — `keep` on merge.

**Backend — modify**
- `backend/app/models/work.py` — `description_override`.
- `backend/app/models/correction.py` — `CorrectionOp.set_metadata`.
- `backend/app/services/works.py` — `load_work_presentation` precedence.
- `backend/app/api/series.py` — singleton name from its book.
- `backend/app/services/catalog_loader.py` — works upsert keeps a librarian's title.
- `backend/app/services/librarian/carry.py` — carries `set_metadata` too.
- `backend/app/services/librarian/undo.py` — `_undo_set_metadata`.
- `backend/app/services/librarian/identity.py` — `merge(…, keep=)`.
- `backend/app/services/librarian/__init__.py` — re-export `set_metadata`.
- `backend/app/schemas/librarian.py` — `KeepIn`, `MergeIn.keep`, `MergeSide.cover_book_id`.
- `backend/app/api/librarian.py` — pass `keep`; `MergeSide.cover_book_id` where 04 builds it.
- `backend/tests/test_librarian_api.py` — keep through the route.

**Frontend — create**
- `frontend/src/components/librarian/KeepChoices.jsx`, `frontend/src/components/librarian/KeepChoices.test.jsx`.
- `frontend/e2e/librarian-merge-keep.spec.js`.

**Frontend — modify**
- `frontend/src/components/librarian/MergePreview.jsx` (+ `.test.jsx`) — optional `keep`/`onKeepChange`.
- `frontend/src/components/LibrarianPanel.jsx` (+ `.test.jsx`) — `fields.keep`, request body, reset on new target.

**Docs — modify:** `docs/librarian-ux-roadmap.md`, `ROADMAP.md`, `CLAUDE.md`.

---

### Task 1: Schema, description precedence, singleton name

**Files:**
- Create: `backend/alembic/versions/<generated>_description_override_and_set_metadata.py`, `backend/tests/test_librarian_metadata.py`
- Modify: `docs/librarian-ux-roadmap.md` (shared names), `backend/app/models/work.py:127-129`, `backend/app/models/correction.py`, `backend/app/services/works.py` (`load_work_presentation`), `backend/app/api/series.py:106-112`

**Interfaces:**
- Produces: `Work.description_override: str | None`; `CorrectionOp.set_metadata`; `WorkPresentation.description` = `description_override or representative.description or work.description`; singleton `SeriesOut.name` = its first book's title.

- [ ] **Step 0: Change the shared names first, and mark the item started**

In `docs/librarian-ux-roadmap.md`, *Shared names → Backend → Merge preview (04)*, change the `MergeSide` list to end with `series_slug, series_name, cover_book_id}` and add the sentence: `` `cover_book_id` (07) is the edition behind `cover_url`, null when the cover is Open Library's own image or there is none. `` Under *Keep the best (07)*, append: `A follow-up is recorded only where the merged book would otherwise show something other than the kept side's value, so the default can record one too. A kept description lives in works.description_override.` In the tracker, set row 07 to Status `🟡` and Branch `feat/librarian-lx07-merge-keep-best`.

- [ ] **Step 1: Write the failing tests**

`backend/tests/test_librarian_metadata.py`:

```python
"""Roadmap 07: where a kept title and description live, and what may not overwrite them."""

import respx
from httpx import Response

from app.models import Series, SeriesKind
from app.services.enrichment import enrich_work
from app.services.works import load_work_presentation
from tests.librarian_factories import make_edition, make_user, make_work

GOOGLE_URL = "https://www.googleapis.com/books/v1/volumes"


async def test_a_kept_description_outranks_the_editions_and_the_works(db_session):
    work = await make_work(db_session, "Red Rising", ol_id="OL30W", author="Pierce Brown")
    edition = await make_edition(db_session, work)
    edition.description, work.description = "Edition blurb.", "Work blurb."
    work.representative_book_id = edition.id
    await db_session.flush()
    assert (await load_work_presentation(db_session, [work.id]))[work.id].description == "Edition blurb."
    work.description_override = "The librarian's blurb."
    await db_session.flush()
    assert (await load_work_presentation(db_session, [work.id]))[work.id].description == "The librarian's blurb."


@respx.mock
async def test_enrichment_does_not_reach_a_kept_description(db_session):
    respx.get(GOOGLE_URL).mock(return_value=Response(200, json={"items": [{"id": "g1", "volumeInfo": {
        "title": "Red Rising", "authors": ["Pierce Brown"], "description": "Google's blurb.", "language": "en"}}]}))
    work = await make_work(db_session, "Red Rising", ol_id="OL30W", author="Pierce Brown")
    work.enriched_at, work.description_override = None, "The librarian's blurb."
    await db_session.flush()

    await enrich_work(db_session, work)

    assert work.enriched_at is not None and work.description == "Google's blurb."
    assert work.description_override == "The librarian's blurb."
    assert (await load_work_presentation(db_session, [work.id]))[work.id].description == "The librarian's blurb."


async def test_a_singleton_page_takes_its_books_title(client, db_session):
    work = await make_work(db_session, "Red Rising", ol_id="OL30W", author="Pierce Brown")
    room = await db_session.get(Series, work.series_id)
    assert room.kind is SeriesKind.singleton
    work.title = "Red Rising: Book One"  # what a kept title does
    await db_session.flush()
    page = (await client.get(f"/api/series/{room.slug}")).json()
    assert page["name"] == "Red Rising: Book One" and page["slug"] == room.slug
```

- [ ] **Step 2: Run them and watch them fail**

Run: `PYTEST tests/test_librarian_metadata.py -v`
Expected: `TypeError`/`AttributeError` on `description_override` (not a mapped column), and `assert 'Red Rising' == 'Red Rising: Book One'`.

- [ ] **Step 3: Model and enum**

In `backend/app/models/work.py`, after `description`:

```python
    # A librarian's kept description (set_metadata, roadmap 07). Read before
    # every other description. Only services/librarian writes it: enrichment
    # writes `description` and releases carry none, so nothing automatic can
    # overwrite a librarian's choice.
    description_override: Mapped[str | None] = mapped_column(Text, nullable=True)
```

In `backend/app/models/correction.py`:

```python
    set_cover = "set_cover"  # pins works.representative_book_id; runtime-only (roadmap 06)
    set_metadata = "set_metadata"  # a kept title / description; runtime-only (roadmap 07)
```

- [ ] **Step 4: Read the override first**

In `backend/app/services/works.py`, `load_work_presentation`: add `Work.description_override` as the **last** column of the `select(...)` (after `Series.kind`), and change the description line:

```python
            description=row[10] or row[3] or row[4],
```

In its docstring, replace the description bullet with:

```
    * description — a librarian's kept one (``description_override``, roadmap
      07), then the representative edition's, then the work's. Google's
      edition blurbs are richer than OL's, so an enriched edition wins over
      the work's own.
```

- [ ] **Step 5: A singleton's name is its book's title**

In `backend/app/api/series.py`, `get_series`, in the `SeriesOut(...)` call replace `name=series.name,` with:

```python
        # A singleton takes its book's title (rename refuses one), so a kept
        # title (roadmap 07) renames the page too; the slug never changes.
        name=works[0].title if series.kind is SeriesKind.singleton and works else series.name,
```

Add `SeriesKind` to the `app.models` import in that module if it is not already there.

- [ ] **Step 6: Migration**

Run: `docker compose exec backend alembic revision --autogenerate -m "description override and set_metadata op"`
Expected: a file whose `upgrade()` has `op.add_column('works', sa.Column('description_override', sa.Text(), nullable=True))`. Delete anything else autogenerate put in it (review it: nothing else changed). Make the bodies:

```python
def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE correction_op_enum ADD VALUE IF NOT EXISTS 'set_metadata'")
    op.add_column("works", sa.Column("description_override", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("works", "description_override")
    # Postgres cannot drop an enum value: 'set_metadata' stays in correction_op_enum.
```

Run: `docker compose exec backend alembic upgrade head && docker compose exec backend alembic downgrade -1 && docker compose exec backend alembic upgrade head`
Expected: no errors.

- [ ] **Step 7: Run the tests**

Run: `PYTEST tests/test_librarian_metadata.py tests/test_series_api.py tests/test_works.py tests/test_enrichment.py -v`
Expected: all PASS.

- [ ] **Step 8: Commit**

```bash
git add docs/librarian-ux-roadmap.md backend/app/models/work.py backend/app/models/correction.py \
        backend/app/services/works.py backend/app/api/series.py \
        backend/alembic/versions/*_description_override_and_set_metadata.py backend/tests/test_librarian_metadata.py
git commit -m "feat(librarian): description_override read first; a singleton page takes its book's title"
```

---

### Task 2: `set_metadata`, its undo, and what may not overwrite it

**Files:**
- Create: `backend/app/services/librarian/metadata.py`
- Modify: `backend/app/services/librarian/undo.py`, `backend/app/services/librarian/carry.py`, `backend/app/services/librarian/__init__.py`, `backend/app/services/catalog_loader.py` (works upsert), `backend/tests/test_librarian_metadata.py`

**Interfaces:**
- Consumes: `record.{clean_reason, live_work, locked, record}`; 06's `carry.carry_fixes`, `works.cover_pin`.
- Produces: `metadata.RUNTIME_ONLY = "the overrides format has no title or description entry"`; `async metadata.set_metadata(db, user: User, work: Work, *, reason: str, title: str | None = None, description: str | None = None) -> CatalogCorrection`. Payload `{"work": "<uuid>", "fields": {"title"?: str, "description"?: str}}`; snapshot `{"title"?: <old works.title>, "description_override"?: <old override or null>}`. `set_metadata` is in `undo.UNDOABLE`. `carry_fixes` now also carries `set_metadata` and returns the total number of corrections re-pointed.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_librarian_metadata.py`. Move the new imports into the file's import block at the top:

```python
import pytest

from app.models import CorrectionOp, Work
from app.services.catalog_loader import load_release, read_release
from app.services.librarian.errors import Conflict, Invalid
from app.services.librarian.identity import merge
from app.services.librarian.metadata import RUNTIME_ONLY, set_metadata
from app.services.librarian.undo import revert, undoable
from app.services.works import merge_works
from tests.librarian_factories import fresh
from tests.test_catalog_loader import ALIASES, EDITIONS, MEMBERS, RED, SERIES, WORKS

TABLES = dict(series=SERIES, works=WORKS, series_members=MEMBERS, editions=EDITIONS, work_aliases=ALIASES)


async def test_set_metadata_writes_title_in_place_and_description_aside(db_session):
    lib = await make_user(db_session, librarian=True)
    work = await make_work(db_session, "Red Rising", ol_id="OL30W", author="Pierce Brown")
    key = work.canonical_key
    c = await set_metadata(db_session, lib, work, reason="the fuller title", title="  Red Rising: Book One ",
                           description="A boy from the mines.")
    assert c.op is CorrectionOp.set_metadata and c.work_id == work.id
    assert c.override is None and c.runtime_only_reason == RUNTIME_ONLY
    assert c.payload == {"work": str(work.id),
                         "fields": {"title": "Red Rising: Book One", "description": "A boy from the mines."}}
    assert c.snapshot == {"title": "Red Rising", "description_override": None}
    assert work.title == "Red Rising: Book One" and work.canonical_key == key  # identity untouched
    assert work.description_override == "A boy from the mines."
    assert await undoable(db_session, c)


async def test_set_metadata_refusals(db_session):
    lib = await make_user(db_session, librarian=True)
    work = await make_work(db_session, "Red Rising", ol_id="OL30W", author="Pierce Brown")
    other = await make_work(db_session, "Iron Gold", ol_id="OL31W", author="Pierce Brown")
    with pytest.raises(Invalid, match="reason"):
        await set_metadata(db_session, lib, work, reason=" ", title="X")
    with pytest.raises(Invalid, match="needs a title"):
        await set_metadata(db_session, lib, work, reason="r", title="   ")
    with pytest.raises(Invalid, match="already reads that way"):
        await set_metadata(db_session, lib, work, reason="r", title="Red Rising")
    with pytest.raises(Invalid, match="already reads that way"):
        await set_metadata(db_session, lib, work, reason="r")
    await merge(db_session, lib, work, other, reason="r", confirm=True)
    with pytest.raises(Conflict, match="merged"):
        await set_metadata(db_session, lib, work, reason="r", title="X")


async def test_undo_restores_and_refuses_when_changed_since(db_session):
    lib = await make_user(db_session, librarian=True)
    work = await make_work(db_session, "Red Rising", ol_id="OL30W", author="Pierce Brown")
    c = await set_metadata(db_session, lib, work, reason="r", title="Red Rising: Book One", description="Kept.")
    await revert(db_session, lib, c)
    assert work.title == "Red Rising" and work.description_override is None

    d = await set_metadata(db_session, lib, work, reason="r", title="Red Rising: Book One")
    work.title = "Something else"  # a hand edit the fix does not know about
    await db_session.flush()
    with pytest.raises(Conflict, match="changed since"):
        await revert(db_session, lib, d)


async def test_a_release_keeps_a_librarians_title(db_session, write_release):
    await load_release(db_session, read_release(write_release("2026.10.1", **TABLES)))
    lib = await make_user(db_session, librarian=True)
    await set_metadata(db_session, lib, await db_session.get(Work, RED), reason="r", title="Red Rising: Book One")

    await load_release(db_session, read_release(write_release("2026.10.2", **TABLES)))

    assert await fresh(db_session, Work.title, RED) == "Red Rising: Book One"


async def test_a_release_retitles_it_after_undo(db_session, write_release):
    await load_release(db_session, read_release(write_release("2026.10.1", **TABLES)))
    lib = await make_user(db_session, librarian=True)
    c = await set_metadata(db_session, lib, await db_session.get(Work, RED), reason="r", title="Red Rising: Book One")
    await revert(db_session, lib, c)
    red = await db_session.get(Work, RED)
    red.title = "Stale"  # so the release visibly writes it again
    await db_session.flush()

    await load_release(db_session, read_release(write_release("2026.10.2", **TABLES)))

    assert await fresh(db_session, Work.title, RED) == "Red Rising"


async def test_an_automatic_merge_carries_kept_metadata_and_undo_restores_the_target(db_session):
    lib = await make_user(db_session, librarian=True)
    twin = await make_work(db_session, "Red Rising (heuristic)", author="Pierce Brown")
    target = await make_work(db_session, "Red Rising", ol_id="OL30W", author="Pierce Brown")
    first = await set_metadata(db_session, lib, twin, reason="r", title="Red Rising: Book One")
    assert first.snapshot == {"title": "Red Rising (heuristic)"}
    second = await set_metadata(db_session, lib, twin, reason="r", description="Kept blurb.")

    await merge_works(db_session, twin, target)  # what _absorb_heuristic_twin does

    assert target.title == "Red Rising: Book One" and target.description_override == "Kept blurb."
    await db_session.refresh(first)
    await db_session.refresh(second)
    assert first.work_id == target.id and first.payload["carried_from"] == str(twin.id)
    assert first.snapshot == {"title": "Red Rising"}  # the target's own title, not the twin's
    await revert(db_session, lib, second)
    await revert(db_session, lib, first)
    assert target.title == "Red Rising" and target.description_override is None
```

- [ ] **Step 2: Run them and watch them fail**

Run: `PYTEST tests/test_librarian_metadata.py -v`
Expected: `ModuleNotFoundError: No module named 'app.services.librarian.metadata'`.

- [ ] **Step 3: Implement `set_metadata`**

`backend/app/services/librarian/metadata.py`:

```python
"""A kept title or description (roadmap 07). Runtime-only.

The title is written in place — search, cards and thread tags all read
``works.title`` — and the catalog loader leaves it alone while this fix is
unreverted. The description goes to ``works.description_override``, which
only this module writes and ``load_work_presentation`` reads first.
``canonical_key`` is never touched: it is identity, not presentation.
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import CatalogCorrection, CorrectionOp, Series, User, Work
from app.services.librarian.errors import Invalid
from app.services.librarian.record import clean_reason, live_work, locked, record

RUNTIME_ONLY = "the overrides format has no title or description entry"
_TITLE_MAX = 500  # works.title is String(500)


async def set_metadata(db: AsyncSession, user: User, work: Work, *, reason: str, title: str | None = None,
                       description: str | None = None) -> CatalogCorrection:
    reason = clean_reason(reason)
    work = live_work(await locked(db, work))
    fields: dict[str, str] = {}
    snapshot: dict[str, str | None] = {}
    if title is not None:
        title = title.strip()
        if not title:
            raise Invalid("A book needs a title.")
        if len(title) > _TITLE_MAX:
            raise Invalid(f"A title is at most {_TITLE_MAX} characters.")
        if title != work.title:
            fields["title"], snapshot["title"] = title, work.title
    if description is not None:
        description = description.strip()
        if not description:
            raise Invalid("A kept description cannot be blank.")
        if description != work.description_override:
            fields["description"], snapshot["description_override"] = description, work.description_override
    if not fields:
        raise Invalid(f"{work.title} already reads that way.")

    if "title" in fields:
        work.title = fields["title"]
    if "description" in fields:
        work.description_override = fields["description"]
    await db.flush()
    return await record(
        db, op=CorrectionOp.set_metadata, user=user, reason=reason,
        payload={"work": str(work.id), "fields": fields}, entries=None, runtime_only_reason=RUNTIME_ONLY,
        snapshot=snapshot, work=work, series=await db.get(Series, work.series_id),
    )
```

In `backend/app/services/librarian/__init__.py`, add:

```python
from app.services.librarian.metadata import set_metadata  # noqa: E402,F401
```

- [ ] **Step 4: Undo**

In `backend/app/services/librarian/undo.py`, add `CorrectionOp.set_metadata` to `UNDOABLE`, and add above `_REVERT`:

```python
async def _undo_set_metadata(db: AsyncSession, c: CatalogCorrection) -> None:
    work = await db.get(Work, c.work_id) if c.work_id else None
    if work is None or work.merged_into_id is not None:
        raise Conflict(_STALE)
    await db.refresh(work)
    fields = c.payload["fields"]
    if "title" in fields and work.title != fields["title"]:
        raise Conflict(_STALE)
    if "description" in fields and work.description_override != fields["description"]:
        raise Conflict(_STALE)
    if "title" in fields:
        work.title = c.snapshot["title"]
    if "description" in fields:
        work.description_override = c.snapshot["description_override"]
    await db.flush()
```

and register `CorrectionOp.set_metadata: _undo_set_metadata,` in `_REVERT`.

- [ ] **Step 5: The loader keeps a librarian's title**

In `backend/app/services/catalog_loader.py`, in the works upsert of `_UPSERTS`, replace `title = EXCLUDED.title,` with:

```sql
           title = CASE WHEN EXISTS (
                       SELECT 1 FROM catalog_corrections c
                       WHERE c.work_id = works.id AND c.op = 'set_metadata' AND c.reverted_at IS NULL
                         AND c.payload -> 'fields' ->> 'title' IS NOT NULL)
                   THEN works.title ELSE EXCLUDED.title END,
```

Add a comment above the statement: `# A librarian's kept title (set_metadata, roadmap 07) outlives releases until undone.`

- [ ] **Step 6: Automatic merges carry `set_metadata`**

Replace `backend/app/services/librarian/carry.py` with (06's cover logic is unchanged, only moved into `_carry_cover_pins`):

```python
"""Librarian fixes that follow an *automatic* merge (roadmaps 06, 07).

Search absorbing a heuristic twin and a release adopting a runtime work are
the same book changing rows; a librarian's choice about it must not be lost
with the tombstone. A librarian merge decides these itself, so it never calls
this (identity.merge passes ``carry_fixes=False``).
"""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import CatalogCorrection, CorrectionOp, Work
from app.services.works import cover_pin


async def _unreverted(db: AsyncSession, work_id, op: CorrectionOp) -> list[CatalogCorrection]:
    return (await db.execute(select(CatalogCorrection).where(
        CatalogCorrection.work_id == work_id, CatalogCorrection.op == op, CatalogCorrection.reverted_at.is_(None),
    ).order_by(CatalogCorrection.created_at, CatalogCorrection.id))).scalars().all()


def _repoint(c: CatalogCorrection, source: Work, target: Work) -> None:
    c.work_id, c.series_id = target.id, target.series_id
    c.payload = {**c.payload, "work": str(target.id), "carried_from": str(source.id)}


async def _carry_cover_pins(db: AsyncSession, source: Work, target: Work) -> int:
    """Skipped when the target has a pin of its own, or when the source's newest
    pin is Open Library's image — None on the target names another record's picture."""
    newest = await cover_pin(db, source.id)
    if newest is None or newest.book_id is None or await cover_pin(db, target.id) is not None:
        return 0
    carried = 0
    for c in await _unreverted(db, source.id, CorrectionOp.set_cover):
        if c.payload.get("book_id") is None:
            continue  # an OL pin stays on the tombstone, inert
        _repoint(c, source, target)
        carried += 1
    return carried


async def _carry_metadata(db: AsyncSession, source: Work, target: Work) -> int:
    """Re-apply the source's kept title/description on the target, rewriting each
    snapshot to the value it replaces *on the target*, so undo restores the target."""
    fixes = await _unreverted(db, source.id, CorrectionOp.set_metadata)
    if not fixes or await db.scalar(select(func.count()).select_from(CatalogCorrection).where(
            CatalogCorrection.work_id == target.id, CatalogCorrection.op == CorrectionOp.set_metadata,
            CatalogCorrection.reverted_at.is_(None))):
        return 0
    title, description = target.title, target.description_override
    for c in fixes:
        fields, snapshot = c.payload["fields"], {}
        if "title" in fields:
            snapshot["title"], title = title, fields["title"]
        if "description" in fields:
            snapshot["description_override"], description = description, fields["description"]
        c.snapshot = snapshot
        _repoint(c, source, target)
    target.title, target.description_override = title, description
    return len(fixes)


async def carry_fixes(db: AsyncSession, source: Work, target: Work) -> int:
    """Runs inside merge_works after the editions moved and before the target is
    re-picked. Returns how many corrections now name the target."""
    carried = await _carry_cover_pins(db, source, target) + await _carry_metadata(db, source, target)
    await db.flush()
    return carried
```

- [ ] **Step 7: Run the tests**

Run: `PYTEST tests/test_librarian_metadata.py tests/test_catalog_loader.py tests/test_catalog_loader_cover_pin.py tests/test_cover_pin.py tests/test_librarian_undo.py -v`
Expected: all PASS.

- [ ] **Step 8: Commit**

```bash
git add backend/app/services/librarian/metadata.py backend/app/services/librarian/undo.py \
        backend/app/services/librarian/carry.py backend/app/services/librarian/__init__.py \
        backend/app/services/catalog_loader.py backend/tests/test_librarian_metadata.py
git commit -m "feat(librarian): set_metadata — a kept title or description no release or merge undoes"
```

---

### Task 3: `keep` on merge

**Files:**
- Create: `backend/tests/test_librarian_merge_keep.py`
- Modify: `backend/app/services/librarian/identity.py` (`merge`), `backend/app/schemas/librarian.py` (`KeepIn`, `MergeIn`), `backend/app/api/librarian.py` (`merge_work`), `backend/tests/test_librarian_api.py`

**Interfaces:**
- Consumes: `covers.shown_cover`, `covers.set_cover`, `covers.CoverChoice`, `metadata.set_metadata`, `works.load_work_presentation`, `works.merge_works(…, carry_fixes=False)`.
- Produces: `identity.KEEP_FIELDS = ("title", "cover", "description")`; `async identity.merge(db, user, source, target, *, reason, confirm=False, keep: dict[str, str] | None = None) -> CatalogCorrection`; merge payload gains `"keep": {title, cover, description}` and, when any were made, `"follow_ups": ["<correction uuid>", …]`. Schema `KeepIn {title, cover, description: Literal['source','target'] = 'target'}`; `MergeIn.keep: KeepIn`.

- [ ] **Step 1: Write the failing tests**

`backend/tests/test_librarian_merge_keep.py`:

```python
"""Roadmap 07: the surviving book shows what the librarian kept, and only that."""

from uuid import UUID

import pytest

from app.models import CatalogCorrection, CorrectionOp, Work
from app.services.librarian.errors import Invalid
from app.services.librarian.identity import merge
from app.services.librarian.undo import revert, undoable
from app.services.works import _refresh_work, load_work_presentation
from tests.librarian_factories import fresh, make_edition, make_user, make_work

SRC, TGT = "https://img.test/source.jpg", "https://img.test/target.jpg"
EVERYTHING = {"title": "source", "cover": "source", "description": "source"}


async def pair(db, *, source_language, target_language):
    lib = await make_user(db, librarian=True)
    source = await make_work(db, "Red Rising: A Novel", ol_id="OL31W", author="Pierce Brown")
    target = await make_work(db, "Red Rising", ol_id="OL30W", author="Pierce Brown")
    s = await make_edition(db, source, language=source_language, cover_url=SRC)
    t = await make_edition(db, target, language=target_language, cover_url=TGT)
    s.description, t.description = "The source's blurb.", "The target's blurb."
    await _refresh_work(db, source)
    await _refresh_work(db, target)
    return lib, source, target, s, t


async def shows(db, work):
    p = (await load_work_presentation(db, [work.id]))[work.id]
    return p.cover_url, p.description


async def follow_ups(db, c):
    return [(await db.get(CatalogCorrection, UUID(i))).op for i in c.payload.get("follow_ups", [])]


async def test_a_default_merge_keeps_what_the_target_showed(db_session):
    # The source brings an English edition, which edition_rank would put on the survivor.
    lib, source, target, s, t = await pair(db_session, source_language="en", target_language="es")
    c = await merge(db_session, lib, source, target, reason="same book", confirm=True)
    assert c.payload["keep"] == {"title": "target", "cover": "target", "description": "target"}
    assert await follow_ups(db_session, c) == [CorrectionOp.set_cover]
    assert await shows(db_session, target) == (TGT, "The target's blurb.")
    assert target.title == "Red Rising"


async def test_a_merge_that_changes_nothing_visible_records_nothing_extra(db_session):
    lib, source, target, s, t = await pair(db_session, source_language="es", target_language="en")
    c = await merge(db_session, lib, source, target, reason="same book", confirm=True)
    assert "follow_ups" not in c.payload
    assert await shows(db_session, target) == (TGT, "The target's blurb.")


async def test_keeping_everything_from_the_source(db_session):
    lib, source, target, s, t = await pair(db_session, source_language="es", target_language="en")
    c = await merge(db_session, lib, source, target, reason="same book", confirm=True, keep=EVERYTHING)
    # The cover pin brings the source edition's blurb with it, so only the title needs set_metadata.
    assert await follow_ups(db_session, c) == [CorrectionOp.set_cover, CorrectionOp.set_metadata]
    assert await shows(db_session, target) == (SRC, "The source's blurb.")
    assert await fresh(db_session, Work.title, target.id) == "Red Rising: A Novel"
    assert c.op is CorrectionOp.merge_works and not await undoable(db_session, c)


async def test_the_source_cover_with_the_target_description(db_session):
    lib, source, target, s, t = await pair(db_session, source_language="es", target_language="en")
    c = await merge(db_session, lib, source, target, reason="same book", confirm=True,
                    keep={"cover": "source"})
    assert await follow_ups(db_session, c) == [CorrectionOp.set_cover, CorrectionOp.set_metadata]
    assert await shows(db_session, target) == (SRC, "The target's blurb.")
    assert target.description_override == "The target's blurb."


async def test_follow_ups_undo_newest_first(db_session):
    lib, source, target, s, t = await pair(db_session, source_language="es", target_language="en")
    c = await merge(db_session, lib, source, target, reason="same book", confirm=True, keep=EVERYTHING)
    cover_fix, meta_fix = [await db_session.get(CatalogCorrection, UUID(i)) for i in c.payload["follow_ups"]]
    assert not await undoable(db_session, cover_fix) and await undoable(db_session, meta_fix)
    await revert(db_session, lib, meta_fix)
    assert await fresh(db_session, Work.title, target.id) == "Red Rising"
    await revert(db_session, lib, cover_fix)
    assert (await shows(db_session, target))[0] == TGT  # the ranking's English edition


async def test_keep_refusals_happen_before_anything_merges(db_session):
    lib = await make_user(db_session, librarian=True)
    target = await make_work(db_session, "Red Rising", ol_id="OL30W", author="Pierce Brown")
    bare = await make_work(db_session, "Red Rising (bare)", ol_id="OL31W", author="Pierce Brown")
    ol_only = await make_work(db_session, "Red Rising (OL art)", ol_id="OL32W", author="Pierce Brown")
    ol_only.ol_cover_id = 7316188
    await db_session.flush()

    for source, keep, message in [
        (bare, {"cover": "source"}, "has no cover to keep"),
        (ol_only, {"cover": "source"}, "Open Library's own image"),
        (bare, {"description": "source"}, "has no description to keep"),
        (bare, {"cover": "left"}, "must be 'source' or 'target'"),
        (bare, {"spine": "source"}, "must be 'source' or 'target'"),
    ]:
        for confirm in (False, True):  # refused before the confirmation step, not after it
            with pytest.raises(Invalid, match=message) as refused:
                await merge(db_session, lib, source, target, reason="r", confirm=confirm, keep=keep)
            assert refused.value.consequences is None
            assert await fresh(db_session, Work.merged_into_id, source.id) is None
```

In `backend/tests/test_librarian_api.py`, append:

```python
async def test_merge_takes_keep_through_the_route(client, db_session):
    lib = headers_for(await make_user(db_session, librarian=True))
    source = await make_work(db_session, "Red Rising: A Novel", ol_id="OL31W", author="Pierce Brown")
    target = await make_work(db_session, "Red Rising", ol_id="OL30W", author="Pierce Brown")
    bad = await client.post(f"/api/librarian/works/{source.id}/merge", headers=lib, json={
        "into_work_id": str(target.id), "reason": "r", "confirm": True, "keep": {"title": "left"}})
    assert bad.status_code == 422
    resp = await client.post(f"/api/librarian/works/{source.id}/merge", headers=lib, json={
        "into_work_id": str(target.id), "reason": "same book", "confirm": True, "keep": {"title": "source"}})
    assert resp.status_code == 201, resp.text
    assert resp.json()["op"] == "merge_works"
    page = (await client.get(f"/api/series/{resp.json()['room_slug']}")).json()
    assert [w["title"] for w in page["works"]] == ["Red Rising: A Novel"]
```

- [ ] **Step 2: Run them and watch them fail**

Run: `PYTEST tests/test_librarian_merge_keep.py tests/test_librarian_api.py::test_merge_takes_keep_through_the_route -v`
Expected: `TypeError: merge() got an unexpected keyword argument 'keep'`, and the route test FAILS because the title is still `Red Rising`.

- [ ] **Step 3: Implement `keep` in the service**

In `backend/app/services/librarian/identity.py`, add the imports:

```python
from app.services.librarian.covers import set_cover, shown_cover
from app.services.librarian.metadata import set_metadata
from app.services.works import load_work_presentation
```

Add above `merge`:

```python
KEEP_FIELDS = ("title", "cover", "description")
_SIDES = ("source", "target")


def _keep(keep: dict | None) -> dict[str, str]:
    chosen = {field: "target" for field in KEEP_FIELDS}
    for field, side in (keep or {}).items():
        if field not in chosen or side not in _SIDES:
            raise Invalid(f"keep.{field} must be 'source' or 'target'.")
        chosen[field] = side
    return chosen


async def _view(db: AsyncSession, work: Work) -> dict:
    """What a reader sees of ``work`` now — the values ``keep`` chooses between."""
    shown = (await load_work_presentation(db, [work.id])).get(work.id)
    return {"title": work.title, "cover": await shown_cover(db, work),
            "description": shown.description if shown else None}


def _check_keep(keep: dict[str, str], source: Work, view: dict) -> None:
    if keep["cover"] == "source":
        if view["cover"] is None:
            raise Invalid(f"{source.title} has no cover to keep.")
        if view["cover"].book_id is None:
            raise Invalid(f"{source.title}'s cover is Open Library's own image, which cannot move to another "
                          "record; merge, then pick a cover.")
    if keep["description"] == "source" and not view["description"]:
        raise Invalid(f"{source.title} has no description to keep.")


async def _keep_best(db: AsyncSession, user: User, target: Work, wanted: dict, reason: str) -> list[CatalogCorrection]:
    """Make the survivor show what was kept, recording a fix only where the
    merge alone would show something else. The cover goes first: it moves the
    representative, and with it the edition blurb the description compares to."""
    made: list[CatalogCorrection] = []
    if wanted["cover"] is not None and await shown_cover(db, target) != wanted["cover"]:
        made.append(await set_cover(db, user, target, wanted["cover"].book_id, reason=reason))
    fields: dict[str, str] = {}
    if wanted["title"] != target.title:
        fields["title"] = wanted["title"]
    shown = (await load_work_presentation(db, [target.id]))[target.id].description
    # A target that had no description gaining the source's is not a loss; nothing to keep.
    if wanted["description"] and wanted["description"] != shown:
        fields["description"] = wanted["description"]
    if fields:
        made.append(await set_metadata(db, user, target, reason=reason, **fields))
    return made
```

Replace `merge` with:

```python
async def merge(db: AsyncSession, user: User, source: Work, target: Work, *, reason: str,
                confirm: bool = False, keep: dict | None = None) -> CatalogCorrection:
    reason = clean_reason(reason)
    keep = _keep(keep)
    if source is not None and target is not None and source.id == target.id:
        raise Invalid("A book cannot merge into itself.")
    for work in sorted((w for w in (source, target) if w is not None), key=lambda w: w.id):
        await locked(db, work)  # id order, so two opposite merges cannot deadlock
    source, target = live_work(source), live_work(target)
    views = {"source": await _view(db, source), "target": await _view(db, target)}
    _check_keep(keep, source, views["source"])  # before confirmation: never confirm a merge that then fails
    wanted = {field: views[keep[field]][field] for field in KEEP_FIELDS}

    room = await db.get(Series, source.series_id)
    moving_threads = await _count(db, Thread, Thread.work_id == source.id)
    if room.kind is SeriesKind.singleton and room.id != target.series_id:
        # absorb_series tags a singleton's untagged threads with the book and carries them.
        moving_threads += await _count(db, Thread, Thread.series_id == room.id, Thread.work_id.is_(None))
    consequences = {
        "threads": moving_threads,
        "shelves": await _count(db, Shelf, Shelf.work_id == source.id),
        "editions": await _count(db, Book, Book.work_id == source.id),
    }
    if not confirm:
        raise NeedsConfirmation(f"Merging {source.title} into {target.title} cannot be undone.", consequences)
    entries, missing = exported(lambda: [{"merge_works": [work_key(target), work_key(source)]}])
    await merge_works(db, source, target, carry_fixes=False)
    c = await record(
        db, op=CorrectionOp.merge_works, user=user, reason=reason,
        payload={"source": str(source.id), "target": str(target.id), "consequences": consequences, "keep": keep},
        entries=entries, runtime_only_reason=missing, work=target,
        series=await db.get(Series, target.series_id),
    )
    # Recorded after the merge, so each follow-up is the latest fix on the survivor and undoable.
    made = await _keep_best(db, user, target, wanted, reason)
    if made:
        c.payload = {**c.payload, "follow_ups": [str(m.id) for m in made]}
        await db.flush()
    return c
```

Cycle check: `covers` and `metadata` import only `record`, `errors`, `works` and models, never `identity`.

- [ ] **Step 4: Schema and route**

In `backend/app/schemas/librarian.py`, add `from typing import Literal` and replace `MergeIn`:

```python
class KeepIn(BaseModel):
    """Which book's version the survivor keeps (roadmap 07)."""

    title: Literal["source", "target"] = "target"
    cover: Literal["source", "target"] = "target"
    description: Literal["source", "target"] = "target"


class MergeIn(_Reasoned):
    into_work_id: UUID
    confirm: bool = False
    keep: KeepIn = Field(default_factory=KeepIn)
```

In `backend/app/api/librarian.py`, `merge_work`:

```python
    c = await _run(librarian.merge(db, user, source, target, reason=body.reason, confirm=body.confirm,
                                   keep=body.keep.model_dump()))
```

- [ ] **Step 5: Run the tests**

Run: `PYTEST tests/test_librarian_merge_keep.py tests/test_librarian_identity.py tests/test_librarian_api.py tests/test_librarian_hardening.py -v`
Expected: all PASS. The v1 merge tests are unchanged: their editions have no covers or descriptions, so a default merge records no follow-up.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/librarian/identity.py backend/app/schemas/librarian.py backend/app/api/librarian.py \
        backend/tests/test_librarian_merge_keep.py backend/tests/test_librarian_api.py
git commit -m "feat(librarian): merge keeps the best of both — title, cover, description per side"
```

---

### Task 4: `MergeSide.cover_book_id`

**Files:**
- Modify: `backend/app/schemas/librarian.py` (`MergeSide`, from 04), the module where 04 builds `MergeSide` (find it in Step 3), `backend/tests/test_librarian_merge_keep.py`

**Interfaces:**
- Consumes: 04's `GET /api/librarian/works/{id}/merge-preview?into={id}` → `MergePreviewOut {source: MergeSide, target: MergeSide, …}`; 06's `covers.shown_cover`.
- Produces: `MergeSide.cover_book_id: UUID | None`, the edition behind `cover_url`. It is null when the cover is Open Library's own image or there is none. Task 5 reads it.

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_librarian_merge_keep.py`:

```python
from tests.librarian_factories import headers_for


async def test_the_preview_says_which_edition_each_cover_is(client, db_session):
    lib = headers_for(await make_user(db_session, librarian=True))
    source = await make_work(db_session, "Red Rising (OL art)", ol_id="OL32W", author="Pierce Brown")
    source.ol_cover_id = 7316188
    target = await make_work(db_session, "Red Rising", ol_id="OL30W", author="Pierce Brown")
    t = await make_edition(db_session, target, cover_url=TGT)
    await _refresh_work(db_session, target)
    await db_session.flush()

    preview = (await client.get(f"/api/librarian/works/{source.id}/merge-preview",
                                params={"into": str(target.id)}, headers=lib)).json()

    assert preview["target"]["cover_url"] == TGT and preview["target"]["cover_book_id"] == str(t.id)
    assert preview["source"]["cover_url"] is not None and preview["source"]["cover_book_id"] is None
```

- [ ] **Step 2: Run it and watch it fail**

Run: `PYTEST tests/test_librarian_merge_keep.py::test_the_preview_says_which_edition_each_cover_is -v`
Expected: FAIL, `KeyError: 'cover_book_id'`.

- [ ] **Step 3: Add the field where 04 builds a side**

Find the builder: `grep -rn "MergeSide(" backend/app`. Expected: one construction site (04's side builder, called once per side), plus the class in `schemas/librarian.py`.

In `backend/app/schemas/librarian.py`, `class MergeSide`, add as the last field:

```python
    # The edition behind cover_url; null when it is Open Library's own image or
    # there is none. Such a cover cannot be kept by the other book (roadmap 07).
    cover_book_id: UUID | None = None
```

In the builder module, import `from app.services.librarian.covers import shown_cover`. Just before the `MergeSide(` call (where the side's `work` is in scope; use the builder's own variable name for it), add:

```python
    choice = await shown_cover(db, work)
```

and add this keyword argument to the `MergeSide(...)` call:

```python
        cover_book_id=choice.book_id if choice is not None else None,
```

- [ ] **Step 4: Run the tests**

Run: `PYTEST tests/test_librarian_merge_keep.py tests/test_librarian_api.py -v` plus 04's own preview test module (`PYTEST -k merge_preview -v`).
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/schemas/librarian.py backend/app/api/librarian.py backend/app/services/librarian \
        backend/tests/test_librarian_merge_keep.py
git commit -m "feat(librarian): merge preview names the edition behind each cover"
```

---

### Task 5: `KeepChoices` inside `MergePreview`

**Files:**
- Create: `frontend/src/components/librarian/KeepChoices.jsx`, `frontend/src/components/librarian/KeepChoices.test.jsx`
- Modify: `frontend/src/components/librarian/MergePreview.jsx` (from 04), `frontend/src/components/librarian/MergePreview.test.jsx` (from 04)

**Interfaces:**
- Consumes: `MergePreviewOut` from 04, with `MergeSide.cover_book_id` from Task 4.
- Produces: exports from `KeepChoices.jsx`: default `KeepChoices({ preview, keep, onKeepChange })`, `KEEP_FIELDS = ['title', 'cover', 'description']`, `DEFAULT_KEEP = { title: 'target', cover: 'target', description: 'target' }`, `isDefaultKeep(keep) -> boolean`. `<MergePreview preview onSwap keep? onKeepChange? />`: with `keep` it renders `KeepChoices` and resets `keep` to `DEFAULT_KEEP` when the swap control is used. Without `keep` it renders exactly as before.

- [ ] **Step 1: Write the failing tests**

`frontend/src/components/librarian/KeepChoices.test.jsx`:

```jsx
import { describe, it, expect, vi } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import KeepChoices, { DEFAULT_KEEP, isDefaultKeep } from './KeepChoices'

const SIDE = { id: 'w', author: 'Pierce Brown', first_publish_year: 2014, edition_count: 1, thread_count: 0,
  shelf_count: 0, series_slug: 's', series_name: 'S' }
const PREVIEW = {
  source: { ...SIDE, id: 'w2', title: 'Red Rising: A Novel', cover_url: 'https://img.test/s.jpg', cover_book_id: 'e2', description: 'Source blurb.' },
  target: { ...SIDE, id: 'w1', title: 'Red Rising', cover_url: 'https://img.test/t.jpg', cover_book_id: 'e1', description: 'Target blurb.' },
  threads: 0, shelves: 0, editions: 1,
}

describe('KeepChoices', () => {
  it('offers each field from either side, the survivor by default', async () => {
    const onKeepChange = vi.fn()
    render(<KeepChoices preview={PREVIEW} keep={DEFAULT_KEEP} onKeepChange={onKeepChange} />)
    for (const field of ['title', 'cover', 'description']) {
      const group = screen.getByRole('radiogroup', { name: `Keep ${field}` })
      expect(within(group).getByRole('radio', { name: /surviving/ })).toBeChecked()
    }
    const title = screen.getByRole('radiogroup', { name: 'Keep title' })
    expect(within(title).getByText('Red Rising: A Novel')).toBeInTheDocument()
    await userEvent.click(within(title).getByRole('radio', { name: /merging away/ }))
    expect(onKeepChange).toHaveBeenCalledWith({ ...DEFAULT_KEEP, title: 'source' })
  })

  it('disables what the source cannot give', () => {
    const preview = { ...PREVIEW, source: { ...PREVIEW.source, cover_book_id: null, description: null } }
    render(<KeepChoices preview={preview} keep={DEFAULT_KEEP} onKeepChange={vi.fn()} />)
    const cover = screen.getByRole('radiogroup', { name: 'Keep cover' })
    expect(within(cover).getByRole('radio', { name: /merging away/ })).toBeDisabled()
    expect(within(cover).getByText(/Open Library's own image cannot move/)).toBeInTheDocument()
    const description = screen.getByRole('radiogroup', { name: 'Keep description' })
    expect(within(description).getByRole('radio', { name: /merging away/ })).toBeDisabled()
    expect(within(description).getByText(/no description/)).toBeInTheDocument()
  })

  it('knows the default', () => {
    expect(isDefaultKeep(DEFAULT_KEEP)).toBe(true)
    expect(isDefaultKeep({ ...DEFAULT_KEEP, cover: 'source' })).toBe(false)
  })
})
```

Append to `frontend/src/components/librarian/MergePreview.test.jsx` (04's file; keep its existing imports and tests):

```jsx
import { DEFAULT_KEEP } from './KeepChoices'

// Inline, not imported from KeepChoices.test.jsx: importing a test file re-runs its tests here.
const KEEP_SIDE = { author: 'Pierce Brown', first_publish_year: 2014, edition_count: 1, thread_count: 0,
  shelf_count: 0, series_slug: 's', series_name: 'S' }
const KEEP_PREVIEW = {
  source: { ...KEEP_SIDE, id: 'w2', title: 'Red Rising: A Novel', cover_url: 'https://img.test/s.jpg', cover_book_id: 'e2', description: 'Source blurb.' },
  target: { ...KEEP_SIDE, id: 'w1', title: 'Red Rising', cover_url: 'https://img.test/t.jpg', cover_book_id: 'e1', description: 'Target blurb.' },
  threads: 0, shelves: 0, editions: 1,
}

describe('MergePreview keep choices', () => {
  it('renders no choices without keep', () => {
    render(<MergePreview preview={KEEP_PREVIEW} onSwap={vi.fn()} />)
    expect(screen.queryByRole('radiogroup', { name: 'Keep cover' })).toBeNull()
  })

  it('resets the choices when the sides swap', async () => {
    const onSwap = vi.fn()
    const onKeepChange = vi.fn()
    render(<MergePreview preview={KEEP_PREVIEW} onSwap={onSwap} keep={{ ...DEFAULT_KEEP, cover: 'source' }}
                         onKeepChange={onKeepChange} />)
    expect(screen.getByRole('radiogroup', { name: 'Keep cover' })).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: /swap/i }))
    expect(onSwap).toHaveBeenCalled()
    expect(onKeepChange).toHaveBeenCalledWith(DEFAULT_KEEP)
  })
})
```

If 04 named its swap control something that `/swap/i` does not match, use 04's accessible name in the `getByRole` query. Keep the assertion.

- [ ] **Step 2: Run them and watch them fail**

Run: `cd frontend && npx vitest run src/components/librarian/KeepChoices.test.jsx src/components/librarian/MergePreview.test.jsx`
Expected: FAIL, `Failed to resolve import "./KeepChoices"`.

- [ ] **Step 3: Implement `KeepChoices`**

`frontend/src/components/librarian/KeepChoices.jsx`:

```jsx
/**
 * Per field, which book's version the survivor keeps (roadmap 07). "Merging
 * away" is the source, "surviving" the target, whichever way the preview is
 * swapped. The server refuses what the source cannot give; this disables it first.
 */
export const KEEP_FIELDS = ['title', 'cover', 'description']
export const DEFAULT_KEEP = { title: 'target', cover: 'target', description: 'target' }
export const isDefaultKeep = (keep) => KEEP_FIELDS.every((field) => keep[field] === 'target')

function unavailable(field, side) {
  if (field === 'cover' && !side.cover_url) return 'no cover'
  if (field === 'cover' && !side.cover_book_id) return "Open Library's own image cannot move"
  if (field === 'description' && !side.description) return 'no description'
  return null
}

function KeepChoices({ preview, keep, onKeepChange }) {
  const sides = { source: preview.source, target: preview.target }
  return (
    <fieldset className="flex flex-col gap-2 text-sm">
      <legend className="label">Keep</legend>
      {KEEP_FIELDS.map((field) => {
        const blocked = unavailable(field, sides.source)
        return (
          <div key={field} role="radiogroup" aria-label={`Keep ${field}`}
               className="flex flex-wrap items-baseline gap-x-4 gap-y-1">
            <span className="text-ink-dim">{field}</span>
            {['source', 'target'].map((side) => {
              const disabled = side === 'source' && !!blocked
              return (
                <label key={side} className="flex items-baseline gap-2">
                  <input type="radio" name={`keep-${field}`} checked={keep[field] === side} disabled={disabled}
                         onChange={() => onKeepChange({ ...keep, [field]: side })} />
                  <span className={disabled ? 'text-ink-dim' : 'text-ink'}>
                    {side === 'source' ? 'merging away' : 'surviving'}
                  </span>
                  {field === 'title' && <span className="font-serif text-ink">{sides[side].title}</span>}
                  {disabled && <span className="text-ink-dim">({blocked})</span>}
                </label>
              )
            })}
          </div>
        )
      })}
    </fieldset>
  )
}

export default KeepChoices
```

- [ ] **Step 4: Let `MergePreview` host it**

In `frontend/src/components/librarian/MergePreview.jsx` (04's component):

1. Import: `import KeepChoices, { DEFAULT_KEEP } from './KeepChoices'`.
2. Change the signature to `function MergePreview({ preview, onSwap, keep, onKeepChange })`.
3. At the top of the body, add:

```jsx
  // A choice about the old pairing would name the other book after a swap.
  const swap = () => {
    onSwap()
    if (keep) onKeepChange(DEFAULT_KEEP)
  }
```

4. On 04's swap control, replace `onClick={onSwap}` with `onClick={swap}`.
5. As the last child of the component's root element, add:

```jsx
      {keep && <KeepChoices preview={preview} keep={keep} onKeepChange={onKeepChange} />}
```

- [ ] **Step 5: Run the tests**

Run: `cd frontend && npx vitest run src/components/librarian`
Expected: all pass, including 04's existing `MergePreview` tests.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/librarian/KeepChoices.jsx frontend/src/components/librarian/KeepChoices.test.jsx \
        frontend/src/components/librarian/MergePreview.jsx frontend/src/components/librarian/MergePreview.test.jsx
git commit -m "feat(web): pick title, cover and description per side in the merge preview"
```

---

### Task 6: The merge panel sends `keep`, end to end

**Files:**
- Create: `frontend/e2e/librarian-merge-keep.spec.js`
- Modify: `frontend/src/components/LibrarianPanel.jsx`, `frontend/src/components/LibrarianPanel.test.jsx`

**Interfaces:**
- Consumes: `KeepChoices` exports, `<MergePreview … keep onKeepChange />`, 04's preview query in the panel.
- Produces: the merge request body carries `keep` whenever it differs from `DEFAULT_KEEP`. It is omitted otherwise, so the body of a default merge is unchanged. `fields.keep` resets when the merge target changes.

- [ ] **Step 1: Write the failing test**

Append to the `describe` in `frontend/src/components/LibrarianPanel.test.jsx`:

```jsx
  it('sends what the librarian kept', async () => {
    const side = { author: 'Pierce Brown', first_publish_year: 2014, edition_count: 1, thread_count: 0,
      shelf_count: 0, series_slug: 'rr', series_name: 'Red Rising', description: 'Blurb.' }
    const preview = {
      source: { ...side, id: 'w1', title: 'Dune', cover_url: 'https://img.test/s.jpg', cover_book_id: 'e2' },
      target: { ...side, id: 'w2', title: 'Dune', cover_url: 'https://img.test/t.jpg', cover_book_id: 'e1' },
      threads: 0, shelves: 0, editions: 1,
    }
    client.get.mockImplementation((url) => Promise.resolve({ data: url.includes('merge-preview')
      ? preview : [{ id: 'w2', title: 'Dune', author: 'Frank Herbert' }] }))
    client.post
      .mockRejectedValueOnce({ response: { status: 422, data: { detail: {
        message: 'm', consequences: { threads: 0, shelves: 0, editions: 1 } } } } })
      .mockResolvedValueOnce({ data: CORRECTION })
    const onDone = renderPanel({ kind: 'merge', work: BOOK })

    await userEvent.type(screen.getByLabelText('Find the book to keep'), 'dune')
    await userEvent.click(await screen.findByRole('radio', { name: /Frank Herbert/ }))
    const cover = await screen.findByRole('radiogroup', { name: 'Keep cover' })
    await userEvent.click(within(cover).getByRole('radio', { name: /merging away/ }))
    await userEvent.type(screen.getByLabelText('Reason'), 'same book')
    await userEvent.click(screen.getByRole('button', { name: 'Merge' }))
    expect(await screen.findByText(/Keeps the merging-away book's cover/)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Confirm merge' }))

    await waitFor(() => expect(onDone).toHaveBeenCalledWith(CORRECTION))
    expect(client.post).toHaveBeenLastCalledWith('/librarian/works/w1/merge', {
      reason: 'same book', into_work_id: 'w2', confirm: true,
      keep: { title: 'target', cover: 'source', description: 'target' } })
  })
```

Add `within` to the `@testing-library/react` import at the top of that file.

- [ ] **Step 2: Run it and watch it fail**

Run: `cd frontend && npx vitest run src/components/LibrarianPanel.test.jsx`
Expected: FAIL, `Unable to find role="radiogroup" and name "Keep cover"`.

- [ ] **Step 3: Wire the panel**

In `frontend/src/components/LibrarianPanel.jsx`:

1. Import: `import { DEFAULT_KEEP, KEEP_FIELDS, isDefaultKeep } from './librarian/KeepChoices'`.
2. In the initial `fields` state, add `keep: DEFAULT_KEEP,`.
3. In `request`, `case 'merge'`, keep whatever ids 04 reads there and append the `keep` spread to the body:

```jsx
    case 'merge':
      return { path: `works/${work.id}/merge`, body: {
        reason, into_work_id: f.into?.id, confirm, ...(isDefaultKeep(f.keep) ? {} : { keep: f.keep }) } }
```

4. Where the merge branch renders `WorkPicker`, reset the choices when a new book is picked:

```jsx
            {kind === 'merge' && <WorkPicker exclude={work.id} value={fields.into}
                                             onChange={(w) => { set('into')(w); set('keep')(DEFAULT_KEEP) }} />}
```

(If 03 moved `WorkPicker` into `components/librarian/pickers.jsx` and gave it a `label` prop, keep that element's props and change only `onChange`.)

5. On the `<MergePreview … />` element 04 renders in the merge branch, add:

```jsx
keep={fields.keep} onKeepChange={set('keep')}
```

6. In `Consequences`, merge branch, after the `…move.{' '}` text and before the `This cannot be undone.` span:

```jsx
        {KEEP_FIELDS.some((f) => fields.keep?.[f] === 'source') && (
          <>Keeps the merging-away book's {KEEP_FIELDS.filter((f) => fields.keep[f] === 'source').join(', ')}.{' '}</>
        )}
```

- [ ] **Step 4: Run the unit tests**

Run: `cd frontend && npm test`
Expected: every test passes. The v1 test `confirms a merge with the counts the server returned` still expects `{ reason, into_work_id, confirm }`, because a default `keep` is omitted.

- [ ] **Step 5: Write the e2e scenario**

`frontend/e2e/librarian-merge-keep.spec.js`:

```js
import { test, expect } from '@playwright/test'
import { grantLibrarian, openFirstSearchResult, registerViaUi } from './helpers'

// A librarian merges a book into another, keeping the merging-away book's
// title. The work search, preview and merge routes are mocked; the page is real.
test('a librarian keeps the merging-away title on merge', async ({ page }) => {
  const user = await registerViaUi(page)
  grantLibrarian(user)
  await page.reload()
  await openFirstSearchResult(page, 'the left hand of darkness')
  await page.getByRole('link', { name: '[edit]' }).click()
  const books = page.getByRole('list', { name: 'Books in this series' })
  const title = (await books.getByRole('heading').first().textContent()).trim()

  const side = { author: 'Ursula K. Le Guin', first_publish_year: 1969, edition_count: 1, thread_count: 0,
    shelf_count: 0, series_slug: 'hainish', series_name: 'Hainish', description: 'Genly Ai on Gethen.',
    cover_url: null, cover_book_id: null }
  await page.route('**/api/works/search*', (route) => route.fulfill({ json: [
    { id: 'e2e-target', title: 'The Left Hand of Darkness (Ace)', author: 'Ursula K. Le Guin' }] }))
  await page.route('**/api/librarian/works/*/merge-preview*', (route) => route.fulfill({ json: {
    source: { ...side, id: 'src', title }, target: { ...side, id: 'e2e-target', title: 'The Left Hand of Darkness (Ace)' },
    threads: 0, shelves: 0, editions: 1 } }))
  let body = null
  await page.route('**/api/librarian/works/*/merge', (route) => {
    body = route.request().postDataJSON()
    if (!body.confirm) {
      return route.fulfill({ status: 422, json: { detail: { message: 'm', consequences: { threads: 0, shelves: 0, editions: 1 } } } })
    }
    return route.fulfill({ status: 201, json: { id: 'c-e2e', op: 'merge_works', reason: body.reason,
      created_at: new Date().toISOString(), user: user.username, exportable: true, runtime_only_reason: null,
      undoable: false, reverted_at: null, room_slug: null, subject: title } })
  })

  await books.getByRole('button', { name: `merge into… ${title}`, exact: true }).click()
  await page.getByLabel('Find the book to keep').fill('left hand ace')
  await page.getByRole('radio', { name: /Ace/ }).check()
  const keepTitle = page.getByRole('radiogroup', { name: 'Keep title' })
  await keepTitle.getByRole('radio', { name: /merging away/ }).check()
  await expect(page.getByRole('radiogroup', { name: 'Keep cover' }).getByRole('radio', { name: /merging away/ })).toBeDisabled()
  await page.getByLabel('Reason', { exact: true }).fill('e2e: same book, better title')
  await page.getByRole('button', { name: 'Merge', exact: true }).click()
  await expect(page.getByText(/Keeps the merging-away book's title/)).toBeVisible()
  await page.getByRole('button', { name: 'Confirm merge' }).click()

  await expect(page.getByRole('group', { name: 'Librarian fix result' })).toBeVisible()
  expect(body.keep).toEqual({ title: 'source', cover: 'target', description: 'target' })
})
```

Run (stack up): `cd frontend && npx playwright test e2e/librarian-merge-keep.spec.js`
Expected: 1 passed.

- [ ] **Step 6: §36 check**

Open a merge in edit mode. The keep rows must read as a terminal form (label, two radios, a serif title), not as a comparison-shopping table. Book covers in the preview stay large and undimmed.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/components/LibrarianPanel.jsx frontend/src/components/LibrarianPanel.test.jsx \
        frontend/e2e/librarian-merge-keep.spec.js
git commit -m "feat(web): the merge panel sends what the librarian kept"
```

---

### Task 7: Docs and tracker

**Files:**
- Modify: `docs/librarian-ux-roadmap.md`, `ROADMAP.md`, `CLAUDE.md`

- [ ] **Step 1: Roadmap notes**

Append under `## Notes` in `docs/librarian-ux-roadmap.md`:

```markdown
- **2026-09-29 · 07 keep the best.** `keep` is honoured, not just recorded:
  after a merge the survivor shows each field's kept side, and a follow-up
  (`set_cover` / `set_metadata`) is recorded only where the merge alone would
  show something else — so a default merge can record one (it stops edition
  re-ranking changing the survivor's cover behind the librarian's back). A
  kept title is written in place (`works.title`; the loader's upsert skips it
  while unreverted); a kept description lives in `works.description_override`,
  read first by `load_work_presentation` and written only by
  `services/librarian`. Automatic merges carry `set_metadata` like 06 carries
  cover pins. A singleton page's name is its book's title. `MergeSide` gained
  `cover_book_id`: an Open Library-only cover cannot be kept by another book.
  Follow-up for 16: the merge payload's `follow_ups` must be undone (newest
  first) before the merge itself. Pre-existing, not fixed here: after any
  librarian merge the survivor holds editions whose key matches neither of its
  identity forms, and `repair_presentation` pass 1 would detach them.
```

- [ ] **Step 2: ROADMAP.md**

In `ROADMAP.md`, Phase 5 **Librarian tools** row, after `dissolve and cover choice`, add `; a merge keeps the best title, cover and description of both books`, and add `components/librarian/KeepChoices.jsx` to its *Touches* list.

- [ ] **Step 3: CLAUDE.md**

In `CLAUDE.md`:
- In the paragraph that begins "A work may have **zero editions**", change "description is the representative edition's before the work's, since Google's blurbs are richer." to "description is a librarian's kept one (`works.description_override`, written only by `services/librarian`) before the representative edition's before the work's, since Google's blurbs are richer."
- In the `services/` paragraph, extend the librarian module list with `metadata` (`(`keys`, `record`, `placement`, `identity`, `covers`, `carry`, `metadata`, `undo`, `export`)`).
- In the **Series** paragraph, after "a singleton renders with no series chrome.", add: "A singleton's page name is its book's title."
- In **Catalog releases**, after "Loading a release twice is a no-op;", add: "a librarian's kept title (`set_metadata`) and cover (`set_cover`) survive a load;".

- [ ] **Step 4: Tracker row (at merge time)**

When the PR merges: row 07 Status `✅`, Done `<YYYY-MM-DD>`, PR `#<n>`; tick the **Roadmap item** checkbox at the top of this plan.

- [ ] **Step 5: Commit**

```bash
git add docs/librarian-ux-roadmap.md ROADMAP.md CLAUDE.md
git commit -m "docs: keep-the-best merge in the roadmap, CLAUDE.md and ROADMAP.md"
```

---

## Self-review

- **Spec coverage.** Per-field choice in the merge preview: Tasks 5–6. `keep` on the merge body, defaults `target`, stored in the payload: Task 3. `cover: 'source'` records `set_cover` in the same transaction: Task 3 `_keep_best`, using 06's op. `title`/`description` from source as `set_metadata`, runtime-only: Tasks 2–3. Overrides not overwritten by enrichment: Task 1 (`description_override` is out of enrichment's reach; title is never written by enrichment). Overrides not overwritten by release loads: Task 2 (title `CASE`; releases carry no description; cover is 06's guard). Overrides not overwritten by automatic merges: Task 2 carry. `MergePreview` keeps its props and adds optional `keep`/`onKeepChange`: Task 5.
- **Types.** `keep` is the same `{title, cover, description}` of `'source'|'target'` in `KeepIn`, `identity._keep`, the payload, `DEFAULT_KEEP` and the request body. `set_metadata(db, user, work, *, reason, title=None, description=None)` is called with those exact kwargs in `_keep_best`. `shown_cover`/`CoverChoice`/`set_cover` are used as 06 defines them. `carry_fixes` keeps 06's signature.
- **Placeholders.** `<generated>` is the Alembic file name (roadmap rule). Task 4 Step 3 locates 04's builder by grep rather than by a path, because 04 chooses the module. The code to add there is given in full.
