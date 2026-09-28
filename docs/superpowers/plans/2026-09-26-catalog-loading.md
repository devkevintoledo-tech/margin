# Catalog Pipeline — Implementation Plan (2 of 2: load a release)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The app loads a versioned catalog release as seed data — adopting the works, threads and shelves that searches created at runtime — and the series page shows each book's position and its sub-series.

**Architecture:** One Alembic migration adds `catalog_releases`, `series_members`, `work_aliases`, and the release/nesting/provenance columns. `services/catalog_loader.py` verifies a release folder, COPYs its Parquet files into temp staging tables and, inside the caller's single transaction, upserts by the release's deterministic ids, adopts runtime rows with `merge_works`, and settles rows a newer release dropped; `scripts/load_catalog_release.py` is its CLI. Runtime code learns two rules: never re-room a release work, and resolve aliased OL ids. `GET /api/series/{slug}` returns `position` and `subseries`, and the React page renders them.

**Tech Stack:** FastAPI, async SQLAlchemy 2.0, asyncpg (`copy_records_to_table`), Alembic, pyarrow 18.1.0; pytest + respx; React 18, Vitest + React Testing Library.

**Spec:** `docs/superpowers/specs/2026-09-26-catalog-pipeline-design.md` — §6 (schema, loader, runtime behaviour) and the loader half of §8–§9. **Plan 1** (`docs/superpowers/plans/2026-09-26-catalog-pipeline.md`) builds the releases this plan loads. The plans meet only at the release contract; this plan's tests build their own fixture releases, so it can run first. `test_catalog_contract.py` compares the loader with `pipeline/contract.py` and skips until plan 1 has landed.

Every code block below was run before this plan was written: the backend suite passes (364 tests: 337 existing + 27 new), the migration round-trips upgrade → downgrade → upgrade on a scratch database with `alembic check` clean, the frontend suite passes (95), and a release built by plan 1's pipeline from its fixture world loads through this loader.

## Global Constraints

- Everything async; DB via `Depends(get_db)` in routes and `AsyncSessionLocal` in scripts. Never `model_validate` an ORM object whose schema has a relationship field — build schemas from scalars (MissingGreenlet).
- Models are imported through `app.models`; its `__init__` must import the new ones.
- Schema is Alembic's. Enum types a migration creates are dropped explicitly in `downgrade()` (`sa.Enum(name=...).drop(op.get_bind(), checkfirst=True)`).
- The loader runs in **one transaction**; any failure rolls back completely. Loading the same release twice is a **no-op**; a release older than the latest loaded is refused without `--force`.
- Release rows upsert **by id**; ids are the pipeline's deterministic UUIDs. `threads.work_id` and `shelves.work_id` point at works only.
- Release slugs win; a colliding non-release series is re-slugged with a numeric suffix.
- Runtime code never moves a work out of a release room.
- Release editions arrive as `books` rows with `source='openlibrary'`, `external_id='OL…M'`; no `books` column changes.
- Tests never touch the network: tag downloads are mocked with respx.
- Frontend: tokens only (no raw colours); serif only for book titles (a series name counts); no new radii, shadows, font sizes or durations; `accent` means interactive, so a heading is never accent; components consume React Query hooks from `src/api/`.
- No star ratings, no reviews.

## Review Focus

1. **A runtime work people already discuss is also in the release** — its threads, shelves and editions must move to the release work and its old URL keep resolving. → Task 3 `test_a_runtime_work_is_adopted_with_its_threads_and_shelves`.
2. **A runtime series already owns the slug a release series needs** ("red-rising") — no unique-index crash; the release wins, and the old room's threads follow its books. → Task 3 `test_a_runtime_tag_room_follows_its_books_and_frees_its_slug`.
3. **A second release moves a book to another room, drops a shelved book, and merges another** — tagged threads follow the book, untagged ones stay, the shelved book survives, the merged one tombstones. → Task 3 `test_a_second_release_moves_tagged_threads_and_settles_absent_rows`.
4. **A search after the load returns an OL id the release merged away** — it must land on the survivor, not stand up a duplicate card; and fresh subject tags must not pull a release book out of its room. → Task 2 `test_a_search_hit_for_a_merged_ol_id_lands_on_the_release_work`, `test_a_release_singleton_is_never_promoted_by_runtime_tags`.
5. **A corrupted or hostile release** — a tampered Parquet file, a newer schema, a tarball with `../` paths — refused before anything is written. → Task 3 `test_a_tampered_file_is_refused`, `test_a_newer_schema_is_refused`; Task 4 `test_a_tarball_escaping_its_folder_is_refused`.

## Decisions this plan makes where the spec is silent

- **Adopted runtime works** keep their row as a tombstone whose `external_id` becomes `merged:<uuid hex>`, which frees `uq_works_source_external_id` for the release row.
- **Emptied runtime rooms** (every book adopted) are tombstoned into the room most of their books joined, taking their untagged threads with them. The same rule retires a release series a newer release dropped while threads still point at it.
- **Release works** get `identity_provenance = 'isbn'` (an authority's match, as `upsert_work_from_ol` already records) and a genre from their subjects via `open_library.genre_slug`; an existing genre or representative edition is never overwritten.
- **The series API stays flat**: each work gains `position` and `subseries` (the child series' name), already in reading order; the page groups consecutive rows under a heading.
- **Tag downloads** use the public release URL (`CATALOG_RELEASES_URL`); for a private repository, `gh release download` and pass the folder.
- **`load_release` expires the session's objects** (it rewrites rows in SQL); callers must not hold ORM objects across it.

## File Structure

```
backend/alembic/versions/a9d3e5f7c1b2_catalog_releases.py   the migration
backend/app/models/catalog.py          CatalogRelease, SeriesMember, WorkAlias, MembershipConfidence
backend/app/services/catalog_loader.py read_release, load_release, retire_series, COLUMNS
backend/scripts/load_catalog_release.py  CLI + tag download
backend/tests/test_catalog_model.py  test_catalog_runtime.py  test_catalog_loader.py
backend/tests/test_catalog_contract.py  test_load_catalog_release_script.py
```
Modified: `backend/app/models/{series,work,__init__}.py`, `backend/app/services/{series,works}.py`, `backend/app/config.py`, `backend/app/api/series.py`, `backend/app/schemas/series.py`, `backend/requirements.txt`, `backend/tests/{conftest,test_series_model,test_series_api}.py`, `frontend/src/pages/Series.jsx`, `frontend/src/pages/Series.test.jsx`, `CLAUDE.md`.

The backend commands assume Postgres is up (`docker compose up -d db`) and `margin_test` exists (see CLAUDE.md).

---

### Task 1: Catalog schema: models and migration

**Files:**
- Create: `backend/app/models/catalog.py`, `backend/alembic/versions/a9d3e5f7c1b2_catalog_releases.py`
- Modify: `backend/app/models/series.py`, `backend/app/models/work.py`, `backend/app/models/__init__.py`
- Modify: `backend/app/services/series.py` (runtime series record their provenance)
- Modify: `backend/tests/test_series_model.py` (its hand-built `Series` needs a provenance)
- Test: `backend/tests/test_catalog_model.py`

**Interfaces:**
- Produces (`app.models`): `CatalogRelease(version PK String(32), manifest JSONB, loaded_at)`; `MembershipConfidence` (`high|medium|low`); `SeriesMember(series_id, work_id` composite PK`, position Numeric → float | None, provenance, confidence)`; `WorkAlias(ol_work_id PK String(64), work_id)`; `SeriesProvenance` (`wikidata|ol_tag|ol_edition_series|title_pattern|single|override`); `SeriesSource.wikidata`.
- Produces columns: `series.provenance` (NOT NULL), `series.catalog_release`, `series.parent_series_id` (self-FK, `ON DELETE SET NULL`), `works.catalog_release` — both release columns FK → `catalog_releases.version`, null = created at runtime.
- Enum types: `series_provenance_enum`, `membership_confidence_enum` (new), `series_source_enum` gains `wikidata`.

The migration backfills `provenance` for existing rows (`single` for singletons, `ol_tag` otherwise) before making it NOT NULL. Postgres cannot drop an enum value, so `downgrade()` relabels any Wikidata series and rebuilds `series_source_enum`.

- [ ] **Step 1: Write the failing test**

`backend/tests/test_catalog_model.py`:

```python
"""The catalog tables: releases, series nesting and membership, work aliases."""

import uuid

import pytest
from sqlalchemy.exc import IntegrityError

from app.models import (
    CatalogRelease, MembershipConfidence, Series, SeriesKind, SeriesMember, SeriesProvenance, SeriesSource,
    Work, WorkAlias, WorkKind, WorkProvenance, WorkSource,
)


def _series(name, **kw):
    return Series(source=kw.pop("source", SeriesSource.wikidata), external_id=f"wd:{uuid.uuid4().hex[:6]}",
                  name=name, slug=f"{name.lower().replace(' ', '-')}-{uuid.uuid4().hex[:4]}",
                  canonical_key=name.lower(), kind=SeriesKind.series,
                  provenance=kw.pop("provenance", SeriesProvenance.wikidata), **kw)


async def _work(db, series):
    w = Work(source=WorkSource.openlibrary, external_id=f"OL{uuid.uuid4().hex[:6]}W", canonical_key="k",
             title="Mistborn", author="Brandon Sanderson", kind=WorkKind.single,
             identity_provenance=WorkProvenance.isbn, series_id=series.id)
    db.add(w)
    await db.flush()
    return w


async def test_a_release_stamps_series_and_works(db_session):
    db_session.add(CatalogRelease(version="2026.10.1", manifest={"version": "2026.10.1"}))
    await db_session.flush()
    cosmere = _series("Cosmere", catalog_release="2026.10.1")
    db_session.add(cosmere)
    await db_session.flush()
    mistborn = _series("Mistborn", catalog_release="2026.10.1", parent_series_id=cosmere.id)
    db_session.add(mistborn)
    await db_session.flush()
    work = await _work(db_session, cosmere)
    work.catalog_release = "2026.10.1"
    db_session.add(SeriesMember(series_id=mistborn.id, work_id=work.id, position=2.5,
                                provenance=SeriesProvenance.wikidata, confidence=MembershipConfidence.high))
    db_session.add(WorkAlias(ol_work_id="OL1W", work_id=work.id))
    await db_session.flush()
    member = await db_session.get(SeriesMember, (mistborn.id, work.id))
    assert member.position == 2.5
    assert (await db_session.get(Series, mistborn.id)).parent_series_id == cosmere.id
    assert (await db_session.get(WorkAlias, "OL1W")).work_id == work.id


async def test_a_work_is_a_member_of_a_series_once(db_session):
    series = _series("Red Rising")
    db_session.add(series)
    await db_session.flush()
    work = await _work(db_session, series)
    for _ in range(2):
        db_session.add(SeriesMember(series_id=series.id, work_id=work.id, position=1,
                                    provenance=SeriesProvenance.ol_tag, confidence=MembershipConfidence.medium))
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_a_stamp_must_name_a_loaded_release(db_session):
    db_session.add(_series("Dune", catalog_release="1999.01.1"))
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_runtime_series_record_their_provenance(db_session):
    work = Work(source=WorkSource.openlibrary, external_id="OL9W", canonical_key="k", title="Dune",
                author="Frank Herbert", kind=WorkKind.single, identity_provenance=WorkProvenance.isbn)
    db_session.add(work)
    await db_session.flush()
    assert (await db_session.get(Series, work.series_id)).provenance is SeriesProvenance.single
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd backend && DATABASE_URL=postgresql+asyncpg://margin:margin@localhost:5432/margin_test python -m pytest tests/test_catalog_model.py -v`
Expected: FAIL — `ImportError: cannot import name 'CatalogRelease' from 'app.models'`.

- [ ] **Step 3: Create the catalog models**

`backend/app/models/catalog.py`:

```python
import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Numeric, String, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.models.series import SeriesProvenance


class CatalogRelease(Base):
    """One loaded catalog release (spec §6.1). The highest version is the catalog's."""

    __tablename__ = "catalog_releases"

    version: Mapped[str] = mapped_column(String(32), primary_key=True)  # "2026.10.1"
    manifest: Mapped[dict] = mapped_column(JSONB, nullable=False)
    loaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )


class MembershipConfidence(str, enum.Enum):
    high = "high"
    medium = "medium"
    low = "low"


class SeriesMember(Base):
    """A work's place in a series: the order a room lists its books in.

    A work is a member of every series the catalog knows it in — *Mort* is in
    Discworld and in its Death sub-series — while ``works.series_id`` stays
    the one room its discussion lives in.
    """

    __tablename__ = "series_members"

    series_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("series.id", ondelete="CASCADE"), primary_key=True
    )
    work_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("works.id", ondelete="CASCADE"), primary_key=True, index=True
    )
    # Numeric so a novella sits at 2.5; null for unnumbered members and collections.
    position: Mapped[float | None] = mapped_column(Numeric(asdecimal=False), nullable=True)
    provenance: Mapped[SeriesProvenance] = mapped_column(
        Enum(SeriesProvenance, name="series_provenance_enum"), nullable=False
    )
    confidence: Mapped[MembershipConfidence] = mapped_column(
        Enum(MembershipConfidence, name="membership_confidence_enum"), nullable=False
    )


class WorkAlias(Base):
    """An Open Library work id that now names another work: a merge loser or an OL redirect."""

    __tablename__ = "work_aliases"

    ol_work_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    work_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("works.id", ondelete="CASCADE"), nullable=False, index=True
    )
```

- [ ] **Step 4: Extend `Series` and `Work`, export the new models**

Apply with `git apply` (save the block to a file first), or make the same edits by hand.

```diff
--- a/backend/app/models/series.py
+++ b/backend/app/models/series.py
@@ -9,10 +9,22 @@
 
 
 class SeriesSource(str, enum.Enum):
-    """Where the grouping came from: an Open Library tag, or nothing (a singleton)."""
+    """Where the grouping came from: Wikidata, an Open Library tag, or nothing (a singleton)."""
 
     openlibrary = "openlibrary"
     heuristic = "heuristic"
+    wikidata = "wikidata"
+
+
+class SeriesProvenance(str, enum.Enum):
+    """Which evidence decided the grouping — the catalog pipeline's ladder rung."""
+
+    wikidata = "wikidata"
+    ol_tag = "ol_tag"
+    ol_edition_series = "ol_edition_series"
+    title_pattern = "title_pattern"
+    single = "single"
+    override = "override"
 
 
 class SeriesKind(str, enum.Enum):
@@ -49,6 +61,18 @@
     kind: Mapped[SeriesKind] = mapped_column(
         Enum(SeriesKind, name="series_kind_enum"), nullable=False
     )
+    provenance: Mapped[SeriesProvenance] = mapped_column(
+        Enum(SeriesProvenance, name="series_provenance_enum"), nullable=False
+    )
+    # Null for series created at runtime. A release series is never moved or
+    # re-roomed by runtime code; only the next release changes it.
+    catalog_release: Mapped[str | None] = mapped_column(
+        ForeignKey("catalog_releases.version"), nullable=True, index=True
+    )
+    # Wikidata nesting: Mistborn Era One inside the Cosmere. The room is the top.
+    parent_series_id: Mapped[uuid.UUID | None] = mapped_column(
+        ForeignKey("series.id", ondelete="SET NULL"), nullable=True, index=True
+    )
     merged_into_id: Mapped[uuid.UUID | None] = mapped_column(
         ForeignKey("series.id", ondelete="SET NULL"), nullable=True, index=True
     )
@@ -65,4 +89,6 @@
     works: Mapped[list["Work"]] = relationship(  # noqa: F821
         "Work", back_populates="series", foreign_keys="Work.series_id"
     )
+    # Two self-FKs (merged_into_id, parent_series_id): no relationship on
+    # either, so nothing needs `foreign_keys` disambiguation.
     threads: Mapped[list["Thread"]] = relationship("Thread", back_populates="series")  # noqa: F821
```

```diff
--- a/backend/app/models/work.py
+++ b/backend/app/models/work.py
@@ -141,6 +141,10 @@
         ),
         nullable=False,
     )
+    # The catalog release this row came from; null = created at runtime by search.
+    catalog_release: Mapped[str | None] = mapped_column(
+        ForeignKey("catalog_releases.version"), nullable=True, index=True
+    )
     # Tombstone pointer: a merged work keeps resolving so its URLs survive.
     merged_into_id: Mapped[uuid.UUID | None] = mapped_column(
         ForeignKey("works.id", ondelete="SET NULL"), nullable=True, index=True
```

```diff
--- a/backend/app/models/__init__.py
+++ b/backend/app/models/__init__.py
@@ -9,7 +9,8 @@
 from app.models.password_reset import PasswordResetToken
 from app.models.work import Work, WorkKind, WorkProvenance, WorkSource
 from app.models.search_query import SearchQuery
-from app.models.series import Series, SeriesKind, SeriesSource
+from app.models.series import Series, SeriesKind, SeriesProvenance, SeriesSource
+from app.models.catalog import CatalogRelease, MembershipConfidence, SeriesMember, WorkAlias
 
 __all__ = [
     "Base",
@@ -31,4 +32,9 @@
     "Series",
     "SeriesKind",
     "SeriesSource",
+    "SeriesProvenance",
+    "CatalogRelease",
+    "MembershipConfidence",
+    "SeriesMember",
+    "WorkAlias",
 ]
```

- [ ] **Step 5: Record provenance on runtime series; fix the hand-built series in the model test**

Apply with `git apply`, or make the same edits by hand.

```diff
--- a/backend/app/services/series.py
+++ b/backend/app/services/series.py
@@ -12,7 +12,7 @@
 from sqlalchemy.ext.asyncio import AsyncSession
 from sqlalchemy.orm import Session
 
-from app.models import Series, SeriesKind, SeriesSource, Thread, Work
+from app.models import Series, SeriesKind, SeriesProvenance, SeriesSource, Thread, Work
 from app.services.series_identity import (
     choose_container,
     parse_tags,
@@ -41,6 +41,7 @@
         slug=f"{slugify(work.title, max_length=60)}-{series_id.hex[:6]}",
         canonical_key=series_key(work.title),
         kind=SeriesKind.singleton,
+        provenance=SeriesProvenance.single,
     )
 
 
@@ -151,6 +152,7 @@
         slug=await unique_slug(db, name),
         canonical_key=series_key(name),
         kind=SeriesKind.series,
+        provenance=SeriesProvenance.ol_tag,
     )
     db.add(series)
     await db.flush()
```

```diff
--- a/backend/tests/test_series_model.py
+++ b/backend/tests/test_series_model.py
@@ -9,6 +9,7 @@
     AuthProvider,
     Series,
     SeriesKind,
+    SeriesProvenance,
     SeriesSource,
     Thread,
     User,
@@ -74,6 +75,7 @@
         slug="red-rising",
         canonical_key="red rising",
         kind=SeriesKind.series,
+        provenance=SeriesProvenance.ol_tag,
     )
     db_session.add(series)
     await db_session.flush()
```

- [ ] **Step 6: Write the migration**

`backend/alembic/versions/a9d3e5f7c1b2_catalog_releases.py`:

```python
"""catalog releases: release bookkeeping, series membership, nesting, aliases

Revision ID: a9d3e5f7c1b2
Revises: f8c4d0e3b2a5

Everything the catalog loader (scripts.load_catalog_release) writes. Existing
runtime series get a provenance from what created them: a singleton is
`single`, a tag series `ol_tag`.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "a9d3e5f7c1b2"
down_revision: Union[str, None] = "f8c4d0e3b2a5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

PROVENANCE = ("wikidata", "ol_tag", "ol_edition_series", "title_pattern", "single", "override")


def upgrade() -> None:
    op.create_table(
        "catalog_releases",
        sa.Column("version", sa.String(length=32), nullable=False),
        sa.Column("manifest", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("loaded_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("version"),
    )

    # ADD VALUE cannot run inside a transaction block on older Postgres, and the
    # new value cannot be used in the transaction that adds it — nothing here does.
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE series_source_enum ADD VALUE IF NOT EXISTS 'wikidata'")

    provenance = postgresql.ENUM(*PROVENANCE, name="series_provenance_enum", create_type=False)
    provenance.create(op.get_bind(), checkfirst=True)
    op.add_column("series", sa.Column("provenance", provenance, nullable=True))
    op.execute("UPDATE series SET provenance = CASE WHEN kind = 'singleton' "
               "THEN 'single' ELSE 'ol_tag' END::series_provenance_enum")
    op.alter_column("series", "provenance", nullable=False)
    op.add_column("series", sa.Column("catalog_release", sa.String(length=32), nullable=True))
    op.create_foreign_key("series_catalog_release_fkey", "series", "catalog_releases",
                          ["catalog_release"], ["version"])
    op.create_index("ix_series_catalog_release", "series", ["catalog_release"])
    op.add_column("series", sa.Column("parent_series_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key("series_parent_series_id_fkey", "series", "series",
                          ["parent_series_id"], ["id"], ondelete="SET NULL")
    op.create_index("ix_series_parent_series_id", "series", ["parent_series_id"])

    op.add_column("works", sa.Column("catalog_release", sa.String(length=32), nullable=True))
    op.create_foreign_key("works_catalog_release_fkey", "works", "catalog_releases",
                          ["catalog_release"], ["version"])
    op.create_index("ix_works_catalog_release", "works", ["catalog_release"])

    op.create_table(
        "series_members",
        sa.Column("series_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("work_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("position", sa.Numeric(), nullable=True),
        sa.Column("provenance", provenance, nullable=False),
        sa.Column("confidence", sa.Enum("high", "medium", "low", name="membership_confidence_enum"), nullable=False),
        sa.ForeignKeyConstraint(["series_id"], ["series.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["work_id"], ["works.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("series_id", "work_id"),
    )
    op.create_index("ix_series_members_work_id", "series_members", ["work_id"])

    op.create_table(
        "work_aliases",
        sa.Column("ol_work_id", sa.String(length=64), nullable=False),
        sa.Column("work_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(["work_id"], ["works.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("ol_work_id"),
    )
    op.create_index("ix_work_aliases_work_id", "work_aliases", ["work_id"])


def downgrade() -> None:
    op.drop_index("ix_work_aliases_work_id", table_name="work_aliases")
    op.drop_table("work_aliases")
    op.drop_index("ix_series_members_work_id", table_name="series_members")
    op.drop_table("series_members")
    op.drop_index("ix_works_catalog_release", table_name="works")
    op.drop_constraint("works_catalog_release_fkey", "works", type_="foreignkey")
    op.drop_column("works", "catalog_release")
    op.drop_index("ix_series_parent_series_id", table_name="series")
    op.drop_constraint("series_parent_series_id_fkey", "series", type_="foreignkey")
    op.drop_column("series", "parent_series_id")
    op.drop_index("ix_series_catalog_release", table_name="series")
    op.drop_constraint("series_catalog_release_fkey", "series", type_="foreignkey")
    op.drop_column("series", "catalog_release")
    op.drop_column("series", "provenance")
    op.drop_table("catalog_releases")
    sa.Enum(name="membership_confidence_enum").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="series_provenance_enum").drop(op.get_bind(), checkfirst=True)

    # Postgres cannot drop an enum value: rebuild the type without 'wikidata'.
    # Wikidata series only exist via a catalog load; downgrading past this
    # revision relabels them rather than losing their rows.
    op.execute("UPDATE series SET source = 'openlibrary' WHERE source = 'wikidata'")
    op.execute("ALTER TYPE series_source_enum RENAME TO series_source_enum_old")
    op.execute("CREATE TYPE series_source_enum AS ENUM ('openlibrary', 'heuristic')")
    op.execute("ALTER TABLE series ALTER COLUMN source TYPE series_source_enum "
               "USING source::text::series_source_enum")
    op.execute("DROP TYPE series_source_enum_old")
```

- [ ] **Step 7: Run the model tests and the whole suite**

Run: `cd backend && DATABASE_URL=postgresql+asyncpg://margin:margin@localhost:5432/margin_test python -m pytest -q`
Expected: all pass (+4).

- [ ] **Step 8: Round-trip the migration on a scratch database**

```bash
docker compose exec db psql -U margin -c "CREATE DATABASE margin_mig;"
cd backend
export DATABASE_URL=postgresql+asyncpg://margin:margin@localhost:5432/margin_mig SECRET_KEY=x
alembic upgrade f8c4d0e3b2a5
docker compose exec db psql -U margin -d margin_mig -c \
  "INSERT INTO series (source, external_id, name, slug, canonical_key, kind) VALUES
   ('heuristic','singleton:x','X','x','x','singleton'), ('openlibrary','franchise:y','Y','y','y','series');"
alembic upgrade head      # backfills provenance: x=single, y=ol_tag
alembic downgrade -1
alembic upgrade head      # re-upgrade must not fail with "type already exists"
alembic check             # "No new upgrade operations detected."
docker compose exec db psql -U margin -c "DROP DATABASE margin_mig;"
```

Expected: each command succeeds; `alembic check` reports no operations (it also warns that `works.search_doc`'s computed default cannot be modified — that warning predates this plan).

- [ ] **Step 9: Commit**

```bash
git add backend/app/models backend/alembic/versions/a9d3e5f7c1b2_catalog_releases.py backend/app/services/series.py backend/tests/test_catalog_model.py backend/tests/test_series_model.py
git commit -m "feat(db): catalog releases, series membership and nesting, work aliases"
```

---

### Task 2: Runtime respects the release

**Files:**
- Modify: `backend/app/services/series.py` (`assign_series` returns early for a release room)
- Modify: `backend/app/services/works.py` (`upsert_work_from_ol` resolves `work_aliases`)
- Test: `backend/tests/test_catalog_runtime.py`

**Interfaces:**
- Consumes: Task 1's `CatalogRelease`, `WorkAlias`, `Series.catalog_release`.
- Changes: `assign_series(db, work)` returns the current room unchanged when `current.catalog_release is not None`; `upsert_work_from_ol(db, ol)` finds the aliased work when no work has `external_id == ol.key` but `work_aliases` maps it.

Spec §6.3: "Runtime code never moves a work out of a release series." A release *singleton* is exactly what the old promotion rule would move, so the guard covers singletons too. The third test is a control: a runtime singleton still promotes.

- [ ] **Step 1: Write the failing test**

`backend/tests/test_catalog_runtime.py`:

```python
"""Runtime code after a catalog load: search and series assignment respect the release."""

import uuid

from sqlalchemy import func, select

from app.models import (
    CatalogRelease, Series, SeriesKind, SeriesProvenance, SeriesSource, Work, WorkAlias, WorkKind,
    WorkProvenance, WorkSource,
)
from app.services.open_library import OLWork
from app.services.series import assign_series
from app.services.works import upsert_work_from_ol


async def _release_work(db, ol_id, title, kind=SeriesKind.singleton):
    db.add(CatalogRelease(version="2026.10.1", manifest={}))
    await db.flush()
    room = Series(source=SeriesSource.heuristic, external_id=f"single:{ol_id}", name=title,
                  slug=f"release-{ol_id.lower()}", canonical_key=title.lower(), kind=kind,
                  provenance=SeriesProvenance.single, catalog_release="2026.10.1")
    db.add(room)
    await db.flush()
    work = Work(source=WorkSource.openlibrary, external_id=ol_id, canonical_key=f"{title.lower()}\x1fpierce brown",
                title=title, author="Pierce Brown", kind=WorkKind.single, identity_provenance=WorkProvenance.isbn,
                series_id=room.id, catalog_release="2026.10.1")
    db.add(work)
    await db.flush()
    return work, room


async def test_a_release_singleton_is_never_promoted_by_runtime_tags(db_session):
    work, room = await _release_work(db_session, "OL33W", "Iron Gold")
    work.subjects = "franchise:Red Rising"
    assert (await assign_series(db_session, work)).id == room.id
    assert work.series_id == room.id
    assert (await db_session.get(Series, room.id)).merged_into_id is None


async def test_a_runtime_singleton_is_still_promoted(db_session):
    work = Work(source=WorkSource.openlibrary, external_id="OL1W", canonical_key="x\x1fy", title="Golden Son",
                author="Pierce Brown", kind=WorkKind.single, identity_provenance=WorkProvenance.isbn)
    db_session.add(work)
    await db_session.flush()
    work.subjects = "franchise:Red Rising"
    series = await assign_series(db_session, work)
    assert series.kind is SeriesKind.series


async def test_a_search_hit_for_a_merged_ol_id_lands_on_the_release_work(db_session):
    work, _ = await _release_work(db_session, "OL30W", "Red Rising")
    db_session.add(WorkAlias(ol_work_id="OL36W", work_id=work.id))
    await db_session.flush()
    found = await upsert_work_from_ol(db_session, OLWork(
        key="OL36W", title="Red Rising", author="Pierce Brown", first_publish_year=2014,
        edition_count=3, isbn_13s=frozenset(), subjects=("franchise:Red Rising",)))
    assert found.id == work.id
    assert await db_session.scalar(select(func.count()).select_from(Work)) == 1
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd backend && DATABASE_URL=postgresql+asyncpg://margin:margin@localhost:5432/margin_test python -m pytest tests/test_catalog_runtime.py -v`
Expected: 2 FAIL (`test_a_release_singleton_is_never_promoted_by_runtime_tags`, `test_a_search_hit_for_a_merged_ol_id_lands_on_the_release_work`), 1 pass.

- [ ] **Step 3: Implement both guards**

Apply with `git apply`, or make the same edits by hand.

```diff
--- a/backend/app/services/series.py
+++ b/backend/app/services/series.py
@@ -187,10 +187,14 @@
     """Put ``work`` in the room its subjects name, promoting a singleton.
 
     A work already in a real series is never moved to another automatically.
-    That would be a merge decision, like OL → OL work merges.
-    """
+    That would be a merge decision, like OL → OL work merges. Neither is a
+    work in a catalog release's room, singleton or not: the release decided
+    it from whole-catalog evidence, and only the next release changes it.
+    """
+    current = await db.get(Series, work.series_id) if work.series_id else None
+    if current is not None and current.catalog_release is not None:
+        return current
     target = await series_for_subjects(db, work.subjects)
-    current = await db.get(Series, work.series_id) if work.series_id else None
 
     if target is None:
         if current is None:
```

```diff
--- a/backend/app/services/works.py
+++ b/backend/app/services/works.py
@@ -19,6 +19,7 @@
 from app.models.shelf import Shelf
 from app.models.thread import Thread
 from app.models.series import Series
+from app.models.catalog import WorkAlias
 from app.models.work import Work, WorkKind, WorkProvenance, WorkSource
 from app.schemas.series import SeriesRef
 from app.services import open_library
@@ -324,6 +325,11 @@
             )
         )
     ).scalar_one_or_none()
+    if existing is None:
+        # A catalog release merged this OL id into another work; a search hit
+        # for it must land on that work, not stand up a duplicate beside it.
+        alias = await db.get(WorkAlias, ol.key)
+        existing = await db.get(Work, alias.work_id) if alias is not None else None
 
     work = await canonical_work(db, existing) if existing is not None else None
 
```

- [ ] **Step 4: Run the tests**

Run: `cd backend && DATABASE_URL=postgresql+asyncpg://margin:margin@localhost:5432/margin_test python -m pytest tests/test_catalog_runtime.py tests/test_series_service.py tests/test_search_local.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/series.py backend/app/services/works.py backend/tests/test_catalog_runtime.py
git commit -m "feat: runtime search and series assignment defer to the loaded catalog"
```

---

### Task 3: The catalog loader service

**Files:**
- Create: `backend/app/services/catalog_loader.py`
- Modify: `backend/requirements.txt` (pyarrow), `backend/tests/conftest.py` (`write_release` fixture)
- Test: `backend/tests/test_catalog_loader.py`, `backend/tests/test_catalog_contract.py`

**Interfaces:**
- Consumes: Task 1's models, `works.merge_works`, `open_library.genre_slug`, `series_identity.SUBJECT_SEPARATOR`; the release layout from plan 1 Task 19 (`manifest.json` with `version, schema_version, files{name: sha256}`; five Parquet files).
- Produces: `SCHEMA_VERSION = 1`; `COLUMNS: dict[str, list[tuple[column, staged_sql_type]]]` (must equal `pipeline/contract.py`); `CatalogLoadError`; `Release(path, manifest)` with `.version`; `LoadStats(version, noop, rows, reslugged, adopted, retired_series, moved_threads, deleted_works, kept_works, deleted_series)`; `version_key(v) -> (y, m, n)`; `read_release(path) -> Release`; `retire_series(db, old, survivor) -> moved_threads`; `load_release(db, release, *, force=False) -> LoadStats`.
- Produces (tests): the `write_release(version, **tables)` fixture — rows as dicts, unspecified columns defaulted — returning the folder.

Order inside the transaction matters and is the heart of this task:

1. **Stage** — each Parquet file is COPYed in 50k-row batches into `stage_<name>` (temp, `ON COMMIT DROP`); works gain a `genre_slug`.
2. **Before any upsert** — re-slug non-release series a release slug collides with; find runtime works to adopt and rename their `external_id`; remember every release work's current room.
3. **Upsert** series → works → books → representatives → parents → members (stale ones deleted) → aliases, with the `catalog_releases` row inserted first (both stamps are FKs to it).
4. **After** — tagged threads follow a book whose room changed; runtime works merge into their release twins (`merge_works` also runs `absorb_series`); emptied runtime rooms retire; rows the previous release had and this one lacks are settled.

`test_catalog_contract.py` skips inside the backend container (only `backend/` is mounted) and whenever plan 1 has not landed.

- [ ] **Step 1: Add pyarrow and the release fixture**

Install it: `pip install pyarrow==18.1.0` (or rebuild the backend image).

Apply with `git apply` (save the block to a file first), or make the same edits by hand.

```diff
--- a/backend/requirements.txt
+++ b/backend/requirements.txt
@@ -10,6 +10,8 @@
 authlib==1.3.0
 itsdangerous==2.2.0
 httpx==0.27.0
+# Catalog releases are Parquet (scripts.load_catalog_release).
+pyarrow==18.1.0
 aiosmtplib==3.0.2
 python-dotenv==1.0.1
 python-multipart==0.0.9
```

```diff
--- a/backend/tests/conftest.py
+++ b/backend/tests/conftest.py
@@ -132,3 +132,57 @@
     await db_session.flush()
     await db_session.refresh(g)
     return g
+
+
+_ARROW = {"uuid": "string", "text": "string", "int": "int32", "bigint": "int64", "numeric": "float64"}
+
+
+@pytest.fixture
+def write_release(tmp_path):
+    """Write a catalog release folder the way the pipeline's publish stage does.
+
+    ``write_release("2026.10.1", works=[...], series=[...], ...)`` takes rows as
+    dicts; unspecified columns are filled with neutral values. Returns the folder.
+    """
+    import hashlib
+    import json
+
+    import pyarrow as pa
+    import pyarrow.parquet as pq
+
+    from app.services.catalog_loader import COLUMNS
+
+    defaults = {
+        "works": {"subtitle": None, "author": "A. Author", "first_publish_year": None, "kind": "single",
+                  "ol_cover_id": None, "ol_edition_count": 1, "readinglog_count": 0, "ratings_count": 0,
+                  "subjects": None, "representative_edition_id": None},
+        "editions": {"subtitle": None, "author": "A. Author", "publisher": None, "published_year": None,
+                     "isbn_13": None, "page_count": None, "cover_url": None, "language": "en"},
+        "series": {"source": "openlibrary", "provenance": "ol_tag", "kind": "series", "parent_series_id": None},
+        "series_members": {"position": None, "provenance": "ol_tag", "confidence": "medium"},
+        "work_aliases": {},
+    }
+
+    def write(version, **tables):
+        folder = tmp_path / f"catalog-{version}"
+        folder.mkdir()
+        files = {}
+        for name, columns in COLUMNS.items():
+            schema = pa.schema([(c, getattr(pa, _ARROW[t])()) for c, t in columns])
+            rows = []
+            for row in tables.get(name, []):
+                full = {**defaults[name], **row}
+                if name == "works":
+                    full.setdefault("canonical_key", f"{full['title'].lower()}\x1f{full['author'].lower()}")
+                if name == "series":
+                    full.setdefault("canonical_key", full["name"].lower())
+                    full.setdefault("key", f"ol:{full['name'].lower()}")
+                rows.append({c: (str(full[c]) if t == "uuid" and full.get(c) is not None else full.get(c))
+                             for c, t in columns})
+            pq.write_table(pa.Table.from_pylist(rows, schema=schema), folder / f"{name}.parquet")
+            files[f"{name}.parquet"] = hashlib.sha256((folder / f"{name}.parquet").read_bytes()).hexdigest()
+        (folder / "manifest.json").write_text(json.dumps(
+            {"version": version, "schema_version": 1, "files": files, "sources": [], "row_counts": {}}))
+        return folder
+
+    return write
```

- [ ] **Step 2: Write the failing tests**

`backend/tests/test_catalog_loader.py`:

```python
"""Loading a catalog release (spec §6.2): upserts, adoption, absent rows, idempotence."""

import json
import uuid

import pytest
from sqlalchemy import func, select

from app.models import (
    AuthProvider, Book, CatalogRelease, Genre, Series, SeriesKind, SeriesMember, SeriesProvenance,
    SeriesSource, Shelf, ShelfStatus, Thread, User, Work, WorkAlias, WorkKind, WorkProvenance, WorkSource,
)
from app.services.catalog_loader import CatalogLoadError, load_release, read_release
from app.services.series import get_series_by_slug

RR, ASOIAF = uuid.uuid4(), uuid.uuid4()
RED, GOLD, DARK, GAME = (uuid.uuid4() for _ in range(4))
ED_RED = uuid.uuid4()

SERIES = [
    {"id": RR, "name": "Red Rising", "slug": "red-rising", "key": "ol:red rising"},
    {"id": ASOIAF, "name": "A Song of Ice and Fire", "slug": "a-song-of-ice-and-fire", "key": "wd:Q45875",
     "source": "wikidata", "provenance": "wikidata"},
]
WORKS = [
    {"id": RED, "ol_work_id": "OL30W", "title": "Red Rising", "author": "Pierce Brown", "series_id": RR,
     "first_publish_year": 2014, "subjects": "franchise:Red Rising\nScience fiction", "representative_edition_id": ED_RED},
    {"id": GOLD, "ol_work_id": "OL31W", "title": "Golden Son", "author": "Pierce Brown", "series_id": RR},
    {"id": DARK, "ol_work_id": "OL34W", "title": "Dark Age", "author": "Pierce Brown", "series_id": RR,
     "first_publish_year": 2015},
    {"id": GAME, "ol_work_id": "OL10W", "title": "A Game of Thrones", "author": "George R. R. Martin",
     "series_id": ASOIAF},
]
MEMBERS = [
    {"series_id": RR, "work_id": RED, "position": 1.0},
    {"series_id": RR, "work_id": GOLD, "position": 2.0},
    {"series_id": RR, "work_id": DARK, "position": 5.0},
    {"series_id": ASOIAF, "work_id": GAME, "position": 1.0, "provenance": "wikidata", "confidence": "high"},
]
EDITIONS = [{"id": ED_RED, "ol_edition_id": "OL300M", "work_id": RED, "title": "Red Rising",
             "cover_url": "https://covers.openlibrary.org/b/id/1-L.jpg"}]
ALIASES = [{"ol_work_id": "OL36W", "work_id": RED}]


def v1(write_release, **changes):
    tables = {"series": SERIES, "works": WORKS, "series_members": MEMBERS, "editions": EDITIONS,
              "work_aliases": ALIASES, **changes}
    return read_release(write_release("2026.10.1", **tables))


async def count(db, model):
    return await db.scalar(select(func.count()).select_from(model))


async def user(db):
    u = User(email=f"{uuid.uuid4().hex[:8]}@x.test", username=uuid.uuid4().hex[:10],
             auth_provider=AuthProvider.email, password_hash="x")
    db.add(u)
    await db.flush()
    return u


async def runtime_work(db, external_id, title="Red Rising", source=WorkSource.openlibrary, key=None):
    w = Work(source=source, external_id=external_id, canonical_key=key or f"{title.lower()}\x1fpierce brown",
             title=title, author="Pierce Brown", kind=WorkKind.single, identity_provenance=WorkProvenance.isbn)
    db.add(w)
    await db.flush()
    return w


async def test_loads_every_table_and_stamps_the_release(db_session, write_release):
    db_session.add(Genre(name="Science Fiction", slug="science-fiction"))
    await db_session.flush()
    stats = await load_release(db_session, v1(write_release))
    assert stats.rows == {"works": 4, "editions": 1, "series": 2, "series_members": 4, "work_aliases": 1}
    red = await db_session.get(Work, RED)
    assert (red.catalog_release, red.series_id, red.external_id) == ("2026.10.1", RR, "OL30W")
    assert red.representative_book_id == ED_RED
    assert red.genre_id is not None
    asoiaf = await db_session.get(Series, ASOIAF)
    assert (asoiaf.source, asoiaf.provenance, asoiaf.external_id) == (
        SeriesSource.wikidata, SeriesProvenance.wikidata, "wd:Q45875")
    member = await db_session.get(SeriesMember, (RR, DARK))
    assert member.position == 5.0
    assert (await db_session.get(WorkAlias, "OL36W")).work_id == RED
    assert (await db_session.get(Book, ED_RED)).source == "openlibrary"
    assert (await db_session.get(CatalogRelease, "2026.10.1")) is not None


async def test_loading_the_same_release_twice_is_a_no_op(db_session, write_release):
    release = v1(write_release)
    await load_release(db_session, release)
    again = await load_release(db_session, release)
    assert again.noop
    assert await count(db_session, Work) == 4


async def test_an_older_release_is_refused(db_session, write_release, tmp_path):
    await load_release(db_session, v1(write_release))
    older = read_release(write_release("2026.09.1", series=SERIES, works=WORKS))
    with pytest.raises(CatalogLoadError, match="older"):
        await load_release(db_session, older)


def test_a_tampered_file_is_refused(write_release):
    folder = write_release("2026.10.1", series=SERIES, works=WORKS)
    (folder / "works.parquet").write_bytes(b"not parquet")
    with pytest.raises(CatalogLoadError, match="checksum"):
        read_release(folder)


def test_a_newer_schema_is_refused(write_release):
    folder = write_release("2026.10.1")
    manifest = json.loads((folder / "manifest.json").read_text())
    (folder / "manifest.json").write_text(json.dumps({**manifest, "schema_version": 2}))
    with pytest.raises(CatalogLoadError, match="schema"):
        read_release(folder)


async def test_a_runtime_work_is_adopted_with_its_threads_and_shelves(db_session, write_release):
    reader = await user(db_session)
    runtime = await runtime_work(db_session, "OL30W")  # gets a runtime singleton room
    room = runtime.series_id
    db_session.add_all([
        Thread(title="Is Darrow right?", user_id=reader.id, series_id=room),
        Shelf(user_id=reader.id, work_id=runtime.id, status=ShelfStatus.reading),
    ])
    await db_session.flush()

    stats = await load_release(db_session, v1(write_release))
    assert stats.adopted == 1
    await db_session.refresh(runtime)
    assert runtime.merged_into_id == RED
    thread = (await db_session.execute(select(Thread))).scalar_one()
    assert (thread.series_id, thread.work_id) == (RR, RED)  # a singleton's thread is about its book
    shelf = (await db_session.execute(select(Shelf))).scalar_one()
    assert shelf.work_id == RED
    assert (await db_session.get(Series, room)).merged_into_id == RR


async def test_a_runtime_work_is_adopted_through_an_alias(db_session, write_release):
    runtime = await runtime_work(db_session, "OL36W")
    await load_release(db_session, v1(write_release))
    await db_session.refresh(runtime)
    assert runtime.merged_into_id == RED


async def test_a_heuristic_work_is_adopted_by_title_and_author(db_session, write_release):
    runtime = await runtime_work(db_session, "abc123", title="Golden Son", source=WorkSource.heuristic)
    await load_release(db_session, v1(write_release))
    await db_session.refresh(runtime)
    assert runtime.merged_into_id == GOLD


async def test_a_runtime_tag_room_follows_its_books_and_frees_its_slug(db_session, write_release):
    reader = await user(db_session)
    tag_room = Series(source=SeriesSource.openlibrary, external_id="franchise:red rising", name="Red Rising",
                      slug="red-rising", canonical_key="red rising", kind=SeriesKind.series,
                      provenance=SeriesProvenance.ol_tag)
    db_session.add(tag_room)
    await db_session.flush()
    for ol in ("OL30W", "OL31W"):
        w = await runtime_work(db_session, ol)
        w.series_id = tag_room.id
    db_session.add(Thread(title="Best book?", user_id=reader.id, series_id=tag_room.id))
    await db_session.flush()

    stats = await load_release(db_session, v1(write_release))
    assert stats.reslugged == 1
    await db_session.refresh(tag_room)
    assert tag_room.slug == "red-rising-2"
    assert tag_room.merged_into_id == RR
    thread = (await db_session.execute(select(Thread))).scalar_one()
    assert (thread.series_id, thread.work_id) == (RR, None)  # untagged stays series-wide
    assert (await get_series_by_slug(db_session, "red-rising")).id == RR
    assert (await get_series_by_slug(db_session, "red-rising-2")).id == RR


async def test_a_second_release_moves_tagged_threads_and_settles_absent_rows(db_session, write_release):
    reader_id = (await user(db_session)).id  # the load expires every object the session holds
    await load_release(db_session, v1(write_release))
    db_session.add_all([
        Thread(title="Dark Age ending", user_id=reader_id, series_id=RR, work_id=DARK),
        Thread(title="Whole saga", user_id=reader_id, series_id=RR),
        Shelf(user_id=reader_id, work_id=GAME, status=ShelfStatus.read),
    ])
    await db_session.flush()

    new_room = uuid.uuid4()
    v2 = read_release(write_release(
        "2026.11.1",
        # Dark Age moves to its own sub-series room; Golden Son is now a merged alias of Red Rising;
        # A Game of Thrones is gone but shelved; A Song of Ice and Fire is gone and empty.
        series=[SERIES[0], {"id": new_room, "name": "Red God", "slug": "red-god", "key": "ol:red god"}],
        works=[{**WORKS[0], "title": "Red Rising (renamed)"}, {**WORKS[2], "series_id": new_room}],
        series_members=[MEMBERS[0], {"series_id": new_room, "work_id": DARK, "position": 1.0}],
        work_aliases=[*ALIASES, {"ol_work_id": "OL31W", "work_id": RED}],
    ))
    stats = await load_release(db_session, v2)

    db_session.expire_all()
    assert (await db_session.get(Work, RED)).title == "Red Rising (renamed)"
    tagged = (await db_session.execute(select(Thread).where(Thread.work_id == DARK))).scalar_one()
    untagged = (await db_session.execute(select(Thread).where(Thread.work_id.is_(None)))).scalar_one()
    assert tagged.series_id == new_room
    assert untagged.series_id == RR
    assert (await db_session.get(Work, GOLD)).merged_into_id == RED
    assert (await db_session.get(Work, GAME)) is not None and stats.kept_works == 1
    assert await db_session.get(SeriesMember, (RR, GOLD)) is None
    assert (await db_session.get(Series, ASOIAF)) is not None  # still the kept book's room
```

`backend/tests/test_catalog_contract.py`:

```python
"""The loader reads exactly what the pipeline writes (pipeline/contract.py)."""

import sys
from pathlib import Path

import pyarrow as pa
import pytest

from app.services.catalog_loader import COLUMNS, SCHEMA_VERSION

REPO = Path(__file__).resolve().parents[2]
ARROW_FOR = {"uuid": pa.string(), "text": pa.string(), "int": pa.int32(), "bigint": pa.int64(), "numeric": pa.float64()}


def _pipeline_contract():
    if not (REPO / "pipeline" / "contract.py").exists():
        # Inside the backend container only backend/ is mounted; CI checks out everything.
        pytest.skip("pipeline/ is not present next to backend/")
    sys.path.insert(0, str(REPO))
    try:
        from pipeline import contract
    finally:
        sys.path.remove(str(REPO))
    return contract.SCHEMA_VERSION, contract.SCHEMAS


def test_loader_columns_match_the_pipeline_schemas():
    version, schemas = _pipeline_contract()
    assert version == SCHEMA_VERSION
    assert set(schemas) == set(COLUMNS)
    for name, columns in COLUMNS.items():
        assert [(f.name, f.type) for f in schemas[name]] == [(c, ARROW_FOR[t]) for c, t in columns], name
```

- [ ] **Step 3: Run them to verify they fail**

Run: `cd backend && DATABASE_URL=postgresql+asyncpg://margin:margin@localhost:5432/margin_test python -m pytest tests/test_catalog_loader.py -v`
Expected: FAIL — `No module named 'app.services.catalog_loader'`.

- [ ] **Step 4: Implement the loader**

`backend/app/services/catalog_loader.py`:

```python
"""Load a catalog release into the app database (spec §6.2).

A release is a folder of Parquet files written by the offline pipeline
(``pipeline/release.py`` holds the other half of this contract). Loading runs
in the caller's transaction, so any failure rolls everything back:

1. verify checksums and schema version; refuse an older release;
2. COPY each file into a temp staging table;
3. re-slug runtime series a release slug collides with, and free the
   ``(source, external_id)`` of runtime works the release adopts;
4. upsert series, works, editions, parents, members and aliases by id;
5. carry tagged threads when a book changes rooms, adopt runtime works
   (``merge_works``), retire the runtime rooms that emptied, and settle rows
   the new release no longer contains.

Loading the same release twice is a no-op.
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import pyarrow.parquet as pq
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import CatalogRelease, Work
from app.services.open_library import genre_slug
from app.services.series_identity import SUBJECT_SEPARATOR
from app.services.works import merge_works

SCHEMA_VERSION = 1
_VERSION = re.compile(r"^(\d{4})\.(\d{2})\.(\d+)$")

# Staging columns, in Parquet order, with the SQL type each is staged as.
# Mirrors pipeline/release.py SCHEMAS; the loader refuses a file that differs.
COLUMNS: dict[str, list[tuple[str, str]]] = {
    "works": [
        ("id", "uuid"), ("ol_work_id", "text"), ("canonical_key", "text"), ("title", "text"),
        ("subtitle", "text"), ("author", "text"), ("first_publish_year", "int"), ("kind", "text"),
        ("series_id", "uuid"), ("ol_cover_id", "bigint"), ("ol_edition_count", "int"),
        ("readinglog_count", "int"), ("ratings_count", "int"), ("subjects", "text"),
        ("representative_edition_id", "uuid"),
    ],
    "editions": [
        ("id", "uuid"), ("ol_edition_id", "text"), ("work_id", "uuid"), ("title", "text"),
        ("subtitle", "text"), ("author", "text"), ("publisher", "text"), ("published_year", "int"),
        ("isbn_13", "text"), ("page_count", "int"), ("cover_url", "text"), ("language", "text"),
    ],
    "series": [
        ("id", "uuid"), ("key", "text"), ("source", "text"), ("provenance", "text"), ("name", "text"),
        ("slug", "text"), ("canonical_key", "text"), ("kind", "text"), ("parent_series_id", "uuid"),
    ],
    "series_members": [
        ("series_id", "uuid"), ("work_id", "uuid"), ("position", "numeric"), ("provenance", "text"),
        ("confidence", "text"),
    ],
    "work_aliases": [("ol_work_id", "text"), ("work_id", "uuid")],
}
_BATCH = 50_000


class CatalogLoadError(RuntimeError):
    pass


@dataclass(frozen=True)
class Release:
    path: Path
    manifest: dict

    @property
    def version(self) -> str:
        return self.manifest["version"]


@dataclass
class LoadStats:
    version: str
    noop: bool = False
    rows: dict[str, int] = field(default_factory=dict)
    reslugged: int = 0
    adopted: int = 0
    retired_series: int = 0
    moved_threads: int = 0
    deleted_works: int = 0
    kept_works: int = 0
    deleted_series: int = 0


def version_key(version: str) -> tuple[int, int, int]:
    match = _VERSION.match(version)
    if not match:
        raise CatalogLoadError(f"bad release version {version!r}")
    return tuple(int(g) for g in match.groups())  # type: ignore[return-value]


def read_release(path: Path) -> Release:
    """Open a release folder, verifying every checksum and the schema version."""
    manifest_path = path / "manifest.json"
    if not manifest_path.exists():
        raise CatalogLoadError(f"{path} has no manifest.json")
    manifest = json.loads(manifest_path.read_text())
    if manifest.get("schema_version") != SCHEMA_VERSION:
        raise CatalogLoadError(
            f"release schema {manifest.get('schema_version')} is not {SCHEMA_VERSION}; upgrade the loader")
    version_key(manifest.get("version", ""))
    for name, expected in manifest["files"].items():
        file = path / name
        if not file.exists() or hashlib.sha256(file.read_bytes()).hexdigest() != expected:
            raise CatalogLoadError(f"{name} is missing or does not match its checksum")
    for name, columns in COLUMNS.items():
        actual = pq.read_schema(path / f"{name}.parquet").names
        if actual != [c for c, _ in columns]:
            raise CatalogLoadError(f"{name}.parquet columns {actual} do not match the contract")
    return Release(path, manifest)


def _convert(kind: str, value):
    if value is None:
        return None
    return uuid.UUID(value) if kind == "uuid" else value


async def _stage(db: AsyncSession, release: Release) -> dict[str, int]:
    connection = await db.connection()
    raw = (await connection.get_raw_connection()).driver_connection
    counts = {}
    for name, columns in COLUMNS.items():
        extra = [("genre_slug", "text")] if name == "works" else []
        ddl = ", ".join(f"{c} {t}" for c, t in columns + extra)
        await db.execute(text(f"DROP TABLE IF EXISTS stage_{name}"))
        await db.execute(text(f"CREATE TEMP TABLE stage_{name} ({ddl}) ON COMMIT DROP"))
        counts[name] = 0
        for batch in pq.ParquetFile(release.path / f"{name}.parquet").iter_batches(batch_size=_BATCH):
            records = []
            for row in batch.to_pylist():
                record = [_convert(t, row[c]) for c, t in columns]
                if name == "works":
                    subjects = (row["subjects"] or "").split(SUBJECT_SEPARATOR)
                    record.append(genre_slug([s for s in subjects if s]))
                records.append(tuple(record))
            await raw.copy_records_to_table(
                f"stage_{name}", records=records, columns=[c for c, _ in columns + extra])
            counts[name] += len(records)
    for name in COLUMNS:
        await db.execute(text(f"ANALYZE stage_{name}"))
    return counts


async def _reslug_collisions(db: AsyncSession) -> int:
    """Release slugs win. A different series holding one moves to ``<slug>-N``."""
    rows = (await db.execute(text("""
        SELECT s.id, s.slug FROM series s JOIN stage_series t ON t.slug = s.slug
        WHERE s.id <> t.id ORDER BY s.slug"""))).all()
    for series_id, slug in rows:
        taken = set((await db.execute(text(
            "SELECT slug FROM series WHERE slug LIKE :p UNION SELECT slug FROM stage_series WHERE slug LIKE :p"),
            {"p": f"{slug}-%"})).scalars())
        n = 2
        while f"{slug}-{n}" in taken:
            n += 1
        await db.execute(text("UPDATE series SET slug = :new WHERE id = :id"), {"new": f"{slug}-{n}", "id": series_id})
    return len(rows)


async def _adoptions(db: AsyncSession) -> dict[uuid.UUID, uuid.UUID]:
    """Runtime works (``catalog_release IS NULL``) that are release works: ``{runtime id: release id}``.

    By Open Library id, directly or through an alias; a heuristic work by its
    ``canonical_key`` when exactly one release work carries that key (the key
    embeds the primary author, so this is title plus author).
    """
    rows = (await db.execute(text("""
        SELECT w.id, coalesce(t.id, a.work_id) FROM works w
        LEFT JOIN stage_works t ON t.ol_work_id = w.external_id
        LEFT JOIN stage_work_aliases a ON a.ol_work_id = w.external_id
        WHERE w.catalog_release IS NULL AND w.merged_into_id IS NULL AND w.source = 'openlibrary'
          AND coalesce(t.id, a.work_id) IS NOT NULL
        UNION ALL
        SELECT w.id, t.id FROM works w
        JOIN (SELECT canonical_key, min(id::text)::uuid AS id FROM stage_works
              GROUP BY canonical_key HAVING count(*) = 1) t ON t.canonical_key = w.canonical_key
        WHERE w.catalog_release IS NULL AND w.merged_into_id IS NULL AND w.source = 'heuristic'
    """))).all()
    adoptions = {runtime: target for runtime, target in rows}
    if adoptions:
        # Frees uq_works_source_external_id for the release row. The tombstone
        # still resolves by id; nothing looks a tombstone up by external id.
        await db.execute(text("""
            UPDATE works SET external_id = 'merged:' || replace(id::text, '-', '')
            WHERE id = ANY(:ids)"""), {"ids": list(adoptions)})
    return adoptions


_UPSERTS = (
    """INSERT INTO series (id, source, external_id, name, slug, canonical_key, kind, provenance, catalog_release)
       SELECT id, source::series_source_enum, key, name, slug, canonical_key, kind::series_kind_enum,
              provenance::series_provenance_enum, :version FROM stage_series
       ON CONFLICT (id) DO UPDATE SET source = EXCLUDED.source, external_id = EXCLUDED.external_id,
           name = EXCLUDED.name, slug = EXCLUDED.slug, canonical_key = EXCLUDED.canonical_key,
           kind = EXCLUDED.kind, provenance = EXCLUDED.provenance, catalog_release = EXCLUDED.catalog_release,
           merged_into_id = NULL, updated_at = now()""",
    """INSERT INTO works (id, source, external_id, canonical_key, title, subtitle, author, first_publish_year,
                          kind, identity_provenance, series_id, ol_cover_id, ol_edition_count, readinglog_count,
                          ratings_count, subjects, genre_id, catalog_release)
       SELECT t.id, 'openlibrary', t.ol_work_id, t.canonical_key, t.title, t.subtitle, t.author,
              t.first_publish_year, t.kind::work_kind_enum, 'isbn', t.series_id, t.ol_cover_id,
              t.ol_edition_count, t.readinglog_count, t.ratings_count, t.subjects, g.id, :version
       FROM stage_works t LEFT JOIN genres g ON g.slug = t.genre_slug
       ON CONFLICT (id) DO UPDATE SET external_id = EXCLUDED.external_id, canonical_key = EXCLUDED.canonical_key,
           title = EXCLUDED.title, subtitle = EXCLUDED.subtitle, author = EXCLUDED.author,
           first_publish_year = EXCLUDED.first_publish_year, kind = EXCLUDED.kind, series_id = EXCLUDED.series_id,
           ol_cover_id = EXCLUDED.ol_cover_id, ol_edition_count = EXCLUDED.ol_edition_count,
           readinglog_count = EXCLUDED.readinglog_count, ratings_count = EXCLUDED.ratings_count,
           subjects = EXCLUDED.subjects, genre_id = coalesce(works.genre_id, EXCLUDED.genre_id),
           catalog_release = EXCLUDED.catalog_release, merged_into_id = NULL, updated_at = now()""",
    """INSERT INTO books (id, source, external_id, title, subtitle, author, cover_url, publisher,
                          published_year, isbn_13, page_count, language, work_id)
       SELECT id, 'openlibrary', ol_edition_id, title, subtitle, author, cover_url, publisher,
              published_year, isbn_13, page_count, language, work_id FROM stage_editions
       ON CONFLICT (id) DO UPDATE SET title = EXCLUDED.title, subtitle = EXCLUDED.subtitle,
           author = EXCLUDED.author, cover_url = EXCLUDED.cover_url, publisher = EXCLUDED.publisher,
           published_year = EXCLUDED.published_year, isbn_13 = EXCLUDED.isbn_13,
           page_count = EXCLUDED.page_count, language = EXCLUDED.language, work_id = EXCLUDED.work_id""",
    # Enrichment may have picked a better representative since; keep it.
    """UPDATE works w SET representative_book_id = t.representative_edition_id
       FROM stage_works t WHERE w.id = t.id AND w.representative_book_id IS NULL
         AND t.representative_edition_id IS NOT NULL""",
    """UPDATE series s SET parent_series_id = t.parent_series_id
       FROM stage_series t WHERE s.id = t.id AND s.parent_series_id IS DISTINCT FROM t.parent_series_id""",
    """DELETE FROM series_members m USING series s
       WHERE m.series_id = s.id AND s.catalog_release IS NOT NULL
         AND NOT EXISTS (SELECT 1 FROM stage_series_members t WHERE t.series_id = m.series_id AND t.work_id = m.work_id)""",
    """INSERT INTO series_members (series_id, work_id, position, provenance, confidence)
       SELECT series_id, work_id, position, provenance::series_provenance_enum,
              confidence::membership_confidence_enum FROM stage_series_members
       ON CONFLICT (series_id, work_id) DO UPDATE SET position = EXCLUDED.position,
           provenance = EXCLUDED.provenance, confidence = EXCLUDED.confidence""",
    """INSERT INTO work_aliases (ol_work_id, work_id) SELECT ol_work_id, work_id FROM stage_work_aliases
       ON CONFLICT (ol_work_id) DO UPDATE SET work_id = EXCLUDED.work_id""",
)


async def retire_series(db: AsyncSession, old: uuid.UUID, survivor: uuid.UUID) -> int:
    """Move a room's threads and remaining (tombstoned) works into ``survivor``, then tombstone it."""
    moved = (await db.execute(text("UPDATE threads SET series_id = :new WHERE series_id = :old"),
                              {"new": survivor, "old": old})).rowcount or 0
    await db.execute(text("UPDATE works SET series_id = :new WHERE series_id = :old"), {"new": survivor, "old": old})
    await db.execute(text("UPDATE series SET merged_into_id = :new, parent_series_id = NULL WHERE id = :old"),
                     {"new": survivor, "old": old})
    return moved


async def _merge(db: AsyncSession, source_id: uuid.UUID, target_id: uuid.UUID) -> None:
    source, target = await db.get(Work, source_id), await db.get(Work, target_id)
    if source is not None and target is not None:
        await merge_works(db, source, target)


async def _retire_emptied_rooms(db: AsyncSession, former: dict[uuid.UUID, list[uuid.UUID]]) -> tuple[int, int]:
    """A runtime room whose every book was adopted follows most of them into the release."""
    retired = moved = 0
    for old, targets in sorted(former.items()):
        still_live = await db.scalar(text(
            "SELECT count(*) FROM works WHERE series_id = :s AND merged_into_id IS NULL"), {"s": old})
        merged = await db.scalar(text("SELECT merged_into_id FROM series WHERE id = :s"), {"s": old})
        if still_live or merged is not None:
            continue
        rooms = Counter((await db.execute(text("SELECT series_id FROM works WHERE id = ANY(:ids)"),
                                          {"ids": targets})).scalars())
        survivor = min(rooms, key=lambda r: (-rooms[r], str(r)))
        moved += await retire_series(db, old, survivor)
        retired += 1
    return retired, moved


async def _settle_absent(db: AsyncSession, version: str, stats: LoadStats,
                         old_rooms: dict[uuid.UUID, uuid.UUID]) -> None:
    """Rows an earlier release loaded that this one no longer contains."""
    absent = (await db.execute(text("""
        SELECT w.id, a.work_id FROM works w LEFT JOIN stage_work_aliases a ON a.ol_work_id = w.external_id
        WHERE w.catalog_release IS NOT NULL AND w.catalog_release <> :v AND w.merged_into_id IS NULL
          AND NOT EXISTS (SELECT 1 FROM stage_works t WHERE t.id = w.id)"""), {"v": version})).all()
    for work_id, alias_target in absent:
        if alias_target is not None:
            await _merge(db, work_id, alias_target)
            continue
        referenced = await db.scalar(text("""
            SELECT EXISTS (SELECT 1 FROM threads WHERE work_id = :w) OR EXISTS (SELECT 1 FROM shelves WHERE work_id = :w)
        """), {"w": work_id})
        if referenced:
            stats.kept_works += 1
        else:
            await db.execute(text("DELETE FROM works WHERE id = :w"), {"w": work_id})
            stats.deleted_works += 1

    gone = (await db.execute(text("""
        SELECT s.id FROM series s WHERE s.catalog_release IS NOT NULL AND s.catalog_release <> :v
          AND s.merged_into_id IS NULL AND NOT EXISTS (SELECT 1 FROM stage_series t WHERE t.id = s.id)
        ORDER BY s.id"""), {"v": version})).scalars().all()
    for series_id in gone:
        used = await db.scalar(text("""
            SELECT EXISTS (SELECT 1 FROM works WHERE series_id = :s) OR EXISTS (SELECT 1 FROM threads WHERE series_id = :s)
        """), {"s": series_id})
        if not used:
            await db.execute(text("DELETE FROM series WHERE id = :s"), {"s": series_id})
            stats.deleted_series += 1
            continue
        former = [w for w, room in old_rooms.items() if room == series_id]
        rooms = Counter((await db.execute(text("SELECT series_id FROM works WHERE id = ANY(:ids)"),
                                          {"ids": former})).scalars()) if former else Counter()
        rooms.pop(series_id, None)
        if rooms:
            survivor = min(rooms, key=lambda r: (-rooms[r], str(r)))
            stats.moved_threads += await retire_series(db, series_id, survivor)
            stats.retired_series += 1


async def load_release(db: AsyncSession, release: Release, *, force: bool = False) -> LoadStats:
    """Load ``release`` inside the caller's transaction. See the module docstring."""
    stats = LoadStats(release.version)
    if await db.get(CatalogRelease, release.version) is not None:
        stats.noop = True
        return stats
    loaded = (await db.execute(select(CatalogRelease.version))).scalars().all()
    latest = max(loaded, key=version_key, default=None)
    if latest and version_key(release.version) < version_key(latest) and not force:
        raise CatalogLoadError(f"{release.version} is older than loaded {latest}; pass --force to load it anyway")

    stats.rows = await _stage(db, release)
    stats.reslugged = await _reslug_collisions(db)
    adoptions = await _adoptions(db)
    former_rooms: dict[uuid.UUID, list[uuid.UUID]] = {}
    for runtime, target in adoptions.items():
        room = await db.scalar(text("SELECT series_id FROM works WHERE id = :w"), {"w": runtime})
        former_rooms.setdefault(room, []).append(target)
    old_rooms = dict((await db.execute(text(
        "SELECT w.id, w.series_id FROM works w WHERE w.catalog_release IS NOT NULL"))).all())

    db.add(CatalogRelease(version=release.version, manifest=release.manifest))
    await db.flush()
    for statement in _UPSERTS:
        await db.execute(text(statement), {"version": release.version})

    # A book that changed rooms takes the threads tagged to it; untagged ones stay.
    for work_id, old in old_rooms.items():
        new = await db.scalar(text("SELECT series_id FROM works WHERE id = :w"), {"w": work_id})
        if new != old:
            stats.moved_threads += (await db.execute(text(
                "UPDATE threads SET series_id = :new WHERE work_id = :w AND series_id = :old"),
                {"new": new, "old": old, "w": work_id})).rowcount or 0

    db.expire_all()  # the SQL above changed rows the session may hold
    for runtime, target in sorted(adoptions.items(), key=lambda kv: str(kv[0])):
        await _merge(db, runtime, target)
    stats.adopted = len(adoptions)
    retired, moved = await _retire_emptied_rooms(db, former_rooms)
    stats.retired_series += retired
    stats.moved_threads += moved
    await _settle_absent(db, release.version, stats, old_rooms)
    await db.flush()
    for table in ("works", "series", "books", "series_members", "work_aliases"):
        await db.execute(text(f"ANALYZE {table}"))
    return stats
```

- [ ] **Step 5: Run the tests**

Run: `cd backend && DATABASE_URL=postgresql+asyncpg://margin:margin@localhost:5432/margin_test python -m pytest tests/test_catalog_loader.py tests/test_catalog_contract.py -v`
Expected: PASS (10 loader tests; the contract test passes when `pipeline/contract.py` exists, otherwise skips).

- [ ] **Step 6: Run the whole suite**

Run: `cd backend && DATABASE_URL=postgresql+asyncpg://margin:margin@localhost:5432/margin_test python -m pytest -q`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/catalog_loader.py backend/requirements.txt backend/tests/conftest.py backend/tests/test_catalog_loader.py backend/tests/test_catalog_contract.py
git commit -m "feat: load catalog releases in one transaction, adopting runtime works"
```

---

### Task 4: The loader CLI and tag download

**Files:**
- Create: `backend/scripts/load_catalog_release.py`
- Modify: `backend/app/config.py` (`CATALOG_RELEASES_URL`, `CATALOG_RELEASES_DIR`)
- Test: `backend/tests/test_load_catalog_release_script.py`

**Interfaces:**
- Consumes: `read_release`, `load_release`, `CatalogLoadError`; `AsyncSessionLocal`.
- Produces: `resolve_release(arg, releases_dir, client=None) -> Path` — a folder is used as is; `catalog-YYYY.MM.N` (or bare `YYYY.MM.N`) is looked up in `releases_dir`, else downloaded from `<CATALOG_RELEASES_URL>/<tag>/<tag>.tar.gz` and unpacked with `tarfile`'s `data` filter; `main(argv) -> exit code`.
- CLI: `python -m scripts.load_catalog_release <folder | tag> [--force]` (exit 1 with `refused: …` on any `CatalogLoadError`).

- [ ] **Step 1: Write the failing test**

`backend/tests/test_load_catalog_release_script.py`:

```python
import io
import tarfile

import httpx
import pytest
import respx

from app.services.catalog_loader import CatalogLoadError
from scripts.load_catalog_release import resolve_release

URL = "https://github.com/devkevintoledo-tech/margin/releases/download/catalog-2026.10.1/catalog-2026.10.1.tar.gz"


def tarball(members: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        for name, data in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


def test_a_folder_is_used_as_is(tmp_path):
    assert resolve_release(str(tmp_path), tmp_path / "releases") == tmp_path


@respx.mock
def test_a_tag_is_downloaded_and_unpacked(tmp_path):
    respx.get(URL).mock(return_value=httpx.Response(200, content=tarball({"catalog-2026.10.1/manifest.json": b"{}"})))
    with httpx.Client() as client:
        folder = resolve_release("catalog-2026.10.1", tmp_path, client)
    assert (folder / "manifest.json").read_bytes() == b"{}"


def test_an_already_downloaded_tag_is_not_fetched_again(tmp_path):
    (tmp_path / "catalog-2026.10.1").mkdir()
    assert resolve_release("2026.10.1", tmp_path).name == "catalog-2026.10.1"


@respx.mock
def test_a_tarball_escaping_its_folder_is_refused(tmp_path):
    respx.get(URL).mock(return_value=httpx.Response(200, content=tarball({"../evil": b"x"})))
    with httpx.Client() as client, pytest.raises(tarfile.TarError):
        resolve_release("catalog-2026.10.1", tmp_path / "releases", client)
    assert not (tmp_path / "evil").exists()


@respx.mock
def test_a_missing_release_is_a_clean_refusal(tmp_path):
    respx.get(URL).mock(return_value=httpx.Response(404))
    with httpx.Client() as client, pytest.raises(CatalogLoadError, match="could not download"):
        resolve_release("catalog-2026.10.1", tmp_path, client)


def test_nonsense_is_refused(tmp_path):
    with pytest.raises(CatalogLoadError):
        resolve_release("latest", tmp_path)
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd backend && DATABASE_URL=postgresql+asyncpg://margin:margin@localhost:5432/margin_test python -m pytest tests/test_load_catalog_release_script.py -v`
Expected: FAIL — `No module named 'scripts.load_catalog_release'`.

- [ ] **Step 3: Add the settings**

Apply with `git apply` (save the block to a file first), or make the same edits by hand.

```diff
--- a/backend/app/config.py
+++ b/backend/app/config.py
@@ -20,6 +20,11 @@
     FRONTEND_BASE_URL: str = "http://localhost:5173"
     PASSWORD_RESET_TOKEN_TTL_MINUTES: int = 30
 
+    # Catalog releases (scripts.load_catalog_release). A tag is fetched from
+    # <CATALOG_RELEASES_URL>/<tag>/<tag>.tar.gz into CATALOG_RELEASES_DIR.
+    CATALOG_RELEASES_URL: str = "https://github.com/devkevintoledo-tech/margin/releases/download"
+    CATALOG_RELEASES_DIR: str = "releases"
+
     model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")
 
 
```

- [ ] **Step 4: Implement the script**

`backend/scripts/load_catalog_release.py`:

```python
"""Load a catalog release: ``python -m scripts.load_catalog_release <folder | tag> [--force]``.

A tag (``catalog-2026.10.1``) is downloaded from the GitHub Release of that
name unless ``CATALOG_RELEASES_DIR`` already holds its folder. The whole load
is one transaction: any failure leaves the database exactly as it was.
Idempotent: loading a release that is already loaded does nothing.

For a private repository, download the asset with
``gh release download <tag> -D releases/`` and pass the extracted folder.
"""

from __future__ import annotations

import argparse
import asyncio
import re
import sys
import tarfile
from pathlib import Path

import httpx

from app.config import settings
from app.database import AsyncSessionLocal
from app.services.catalog_loader import CatalogLoadError, load_release, read_release

_TAG = re.compile(r"^catalog-\d{4}\.\d{2}\.\d+$")


def resolve_release(arg: str, releases_dir: Path, client: httpx.Client | None = None) -> Path:
    """A release folder for ``arg``: a folder path, or a tag fetched and unpacked."""
    path = Path(arg)
    if path.is_dir():
        return path
    tag = arg if arg.startswith("catalog-") else f"catalog-{arg}"
    if not _TAG.match(tag):
        raise CatalogLoadError(f"{arg!r} is neither a release folder nor a catalog-YYYY.MM.N tag")
    folder = releases_dir / tag
    if folder.is_dir():
        return folder
    releases_dir.mkdir(parents=True, exist_ok=True)
    tarball = releases_dir / f"{tag}.tar.gz"
    url = f"{settings.CATALOG_RELEASES_URL}/{tag}/{tag}.tar.gz"
    owns_client = client is None
    client = client or httpx.Client(timeout=httpx.Timeout(30.0, read=600.0))
    try:
        with client.stream("GET", url, follow_redirects=True) as response:
            response.raise_for_status()
            with tarball.open("wb") as fh:
                for chunk in response.iter_bytes(1 << 20):
                    fh.write(chunk)
    except httpx.HTTPError as exc:
        tarball.unlink(missing_ok=True)
        raise CatalogLoadError(f"could not download {url}: {exc}") from exc
    finally:
        if owns_client:
            client.close()
    with tarfile.open(tarball) as tar:
        tar.extractall(releases_dir, filter="data")  # refuses absolute paths and ../ escapes
    if not folder.is_dir():
        raise CatalogLoadError(f"{tarball.name} did not contain a {tag}/ folder")
    return folder


async def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m scripts.load_catalog_release")
    parser.add_argument("release", help="release folder, or tag such as catalog-2026.10.1")
    parser.add_argument("--force", action="store_true", help="load even if older than the loaded release")
    args = parser.parse_args(argv)
    try:
        release = read_release(resolve_release(args.release, Path(settings.CATALOG_RELEASES_DIR)))
        async with AsyncSessionLocal() as db:
            async with db.begin():
                stats = await load_release(db, release, force=args.force)
    except CatalogLoadError as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 1
    if stats.noop:
        print(f"{stats.version} is already loaded; nothing to do")
    else:
        print(f"loaded {stats.version}: {stats}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
```

- [ ] **Step 5: Run the test**

Run: `cd backend && DATABASE_URL=postgresql+asyncpg://margin:margin@localhost:5432/margin_test python -m pytest tests/test_load_catalog_release_script.py -v`
Expected: PASS (6 tests).

- [ ] **Step 6: Commit**

```bash
git add backend/scripts/load_catalog_release.py backend/app/config.py backend/tests/test_load_catalog_release_script.py
git commit -m "feat: load_catalog_release CLI with tag download"
```

---

### Task 5: Series API: positions and sub-series

**Files:**
- Modify: `backend/app/schemas/series.py` (`SeriesWorkOut.position`, `.subseries`)
- Modify: `backend/app/api/series.py` (`_members` returns placed, ordered members)
- Test: `backend/tests/test_series_api.py`

**Interfaces:**
- Consumes: `SeriesMember`, `Series.parent_series_id`.
- Produces: `GET /api/series/{slug}` → each `works[]` item gains `position: float | null` and `subseries: string | null` (child series name). Order: members of the room itself first, then each sub-series by its earliest book; within a group, `position` (nulls last), then `first_publish_year`, then title. A runtime series (no memberships) keeps publication order.
- Internal: `_Member(work, position, subseries)`; `_members(db, series) -> list[_Member]`; `_MAX_NESTING = 5`.

A book is placed by its membership in the *deepest* series of the room's tree, so *Mistborn* lists under "Mistborn" inside the Cosmere room. The existing row-shape assertion in `test_series_page_lists_books_in_publication_order` is widened deliberately: the spec adds these two fields.

- [ ] **Step 1: Write the failing tests**

Apply with `git apply`, or make the same edits by hand.

```diff
--- a/backend/tests/test_series_api.py
+++ b/backend/tests/test_series_api.py
@@ -6,7 +6,10 @@
 import respx
 from httpx import Response
 
-from app.models import Series, Work
+from app.models import (
+    MembershipConfidence, Series, SeriesKind, SeriesMember, SeriesProvenance, SeriesSource, Work, WorkKind,
+    WorkProvenance, WorkSource,
+)
 from app.services.open_library import OLWork
 from app.services.works import upsert_work_from_ol
 
@@ -38,7 +41,8 @@
     assert body["name"] == "Red Rising"
     assert [w["title"] for w in body["works"]] == ["Red Rising", "Golden Son", "Morning Star"]
     assert body["description"] == "About Red Rising."
-    assert set(body["works"][0]) == {"id", "title", "author", "first_publish_year", "cover_url", "shelf_status"}
+    assert set(body["works"][0]) == {"id", "title", "author", "first_publish_year", "cover_url", "shelf_status",
+                                     "position", "subseries"}
 
 
 async def test_series_page_reports_the_callers_shelf(client, db_session, auth_headers):
@@ -163,3 +167,52 @@
     await client.get("/api/series/outage")
     assert route.call_count == one_lookup
     assert one_lookup <= 2
+
+
+async def _room(db, name, slug, parent=None, kind=SeriesKind.series):
+    s = Series(source=SeriesSource.wikidata, external_id=f"wd:{slug}", name=name, slug=slug,
+               canonical_key=name.lower(), kind=kind, provenance=SeriesProvenance.wikidata,
+               parent_series_id=parent.id if parent else None)
+    db.add(s)
+    await db.flush()
+    return s
+
+
+async def _book(db, room, title, year, member_of=None, position=None):
+    w = Work(source=WorkSource.openlibrary, external_id=f"OL{uuid.uuid4().hex[:8]}W", canonical_key=title.lower(),
+             title=title, author="Brandon Sanderson", first_publish_year=year, kind=WorkKind.single,
+             identity_provenance=WorkProvenance.isbn, series_id=room.id, enriched_at=datetime.now(timezone.utc))
+    db.add(w)
+    await db.flush()
+    if member_of is not None:
+        db.add(SeriesMember(series_id=member_of.id, work_id=w.id, position=position,
+                            provenance=SeriesProvenance.wikidata, confidence=MembershipConfidence.high))
+        await db.flush()
+    return w
+
+
+async def test_catalog_positions_beat_publication_year(client, db_session):
+    room = await _room(db_session, "Red Rising", "red-rising")
+    await _book(db_session, room, "Dark Age", 2015, room, 5)  # stored with the wrong year
+    await _book(db_session, room, "Red Rising", 2014, room, 1)
+    await _book(db_session, room, "Morning Star", 2016, room, 3)
+    body = (await client.get("/api/series/red-rising")).json()
+    assert [(w["title"], w["position"]) for w in body["works"]] == [
+        ("Red Rising", 1.0), ("Morning Star", 3.0), ("Dark Age", 5.0)]
+
+
+async def test_child_series_group_under_the_room(client, db_session):
+    cosmere = await _room(db_session, "Cosmere", "cosmere")
+    stormlight = await _room(db_session, "The Stormlight Archive", "stormlight", parent=cosmere)
+    mistborn = await _room(db_session, "Mistborn", "mistborn", parent=cosmere)
+    await _book(db_session, cosmere, "The Way of Kings", 2010, stormlight, 1)
+    await _book(db_session, cosmere, "The Well of Ascension", 2007, mistborn, 2)
+    await _book(db_session, cosmere, "Elantris", 2005, cosmere)
+    await _book(db_session, cosmere, "Mistborn", 2006, mistborn, 1)
+    await _book(db_session, cosmere, "Novella", 2016, mistborn, 2.5)
+    body = (await client.get("/api/series/cosmere")).json()
+    assert [(w["title"], w["subseries"], w["position"]) for w in body["works"]] == [
+        ("Elantris", None, None),
+        ("Mistborn", "Mistborn", 1.0), ("The Well of Ascension", "Mistborn", 2.0), ("Novella", "Mistborn", 2.5),
+        ("The Way of Kings", "The Stormlight Archive", 1.0),
+    ]
```

- [ ] **Step 2: Run them to verify they fail**

Run: `cd backend && DATABASE_URL=postgresql+asyncpg://margin:margin@localhost:5432/margin_test python -m pytest tests/test_series_api.py -v`
Expected: 3 FAIL — the widened shape assertion, `test_catalog_positions_beat_publication_year` and `test_child_series_group_under_the_room`.

- [ ] **Step 3: Implement**

Apply with `git apply` (save the block to a file first), or make the same edits by hand.

```diff
--- a/backend/app/schemas/series.py
+++ b/backend/app/schemas/series.py
@@ -25,6 +25,12 @@
     first_publish_year: int | None = None
     cover_url: str | None = None
     shelf_status: ShelfStatus | None = None
+    # Place in the series, from the catalog: 2.0, or 2.5 for a novella. Null
+    # when unknown — the page falls back to publication order.
+    position: float | None = None
+    # The child series this book sits in (Mistborn inside the Cosmere), or
+    # null when it belongs to the room directly.
+    subseries: str | None = None
 
 
 class SeriesOut(BaseModel):
```

```diff
--- a/backend/app/api/series.py
+++ b/backend/app/api/series.py
@@ -1,5 +1,6 @@
 from __future__ import annotations
 
+from typing import NamedTuple
 from uuid import UUID
 
 from fastapi import APIRouter, Depends, HTTPException, Query, status
@@ -7,7 +8,7 @@
 from sqlalchemy.ext.asyncio import AsyncSession
 
 from app.database import get_db
-from app.models import Series, Shelf, Thread, User, Work
+from app.models import Series, SeriesMember, Shelf, Thread, User, Work
 from app.schemas.series import SeriesOut, SeriesThreadCreate, SeriesWorkOut
 from app.schemas.thread import ThreadOut, ThreadSummary
 from app.services.auth import get_current_user, get_current_user_optional
@@ -21,6 +22,7 @@
 # First view of a series pays for Google Books on its members, which used to
 # happen on each work page. Capped so one huge series cannot stall a request.
 _ENRICH_CAP = 10
+_MAX_NESTING = 5
 
 
 async def _series_or_404(db: AsyncSession, slug: str) -> Series:
@@ -30,13 +32,65 @@
     return series
 
 
-async def _members(db: AsyncSession, series: Series) -> list[Work]:
-    stmt = (
-        select(Work)
-        .where(Work.series_id == series.id, Work.merged_into_id.is_(None))
-        .order_by(Work.first_publish_year.asc().nulls_last(), Work.title)
-    )
-    return list((await db.execute(stmt)).scalars().all())
+class _Member(NamedTuple):
+    work: Work
+    position: float | None
+    subseries: Series | None  # None: a member of the room itself
+
+
+async def _members(db: AsyncSession, series: Series) -> list[_Member]:
+    """The room's books in reading order: sub-series, then position, then publication.
+
+    Each book is placed by its membership in the deepest series of the room's
+    tree, so *Mistborn* lists under its own heading inside the Cosmere. Books
+    in the room directly come first; sub-series follow in order of their
+    earliest book. Runtime series have no memberships and keep publication
+    order.
+    """
+    works = list((await db.execute(
+        select(Work).where(Work.series_id == series.id, Work.merged_into_id.is_(None))
+    )).scalars().all())
+    tree, depth, frontier = {series.id: series}, {series.id: 0}, [series.id]
+    for level in range(1, _MAX_NESTING + 1):
+        children = (await db.execute(select(Series).where(
+            Series.parent_series_id.in_(frontier), Series.merged_into_id.is_(None)))).scalars().all()
+        frontier = [c.id for c in children if c.id not in tree]
+        for child in children:
+            tree.setdefault(child.id, child)
+            depth.setdefault(child.id, level)
+        if not frontier:
+            break
+
+    placed: dict[UUID, SeriesMember] = {}
+    if works:
+        rows = (await db.execute(select(SeriesMember).where(
+            SeriesMember.work_id.in_([w.id for w in works]), SeriesMember.series_id.in_(list(tree))
+        ))).scalars().all()
+        for m in rows:
+            best = placed.get(m.work_id)
+            if best is None or (depth[m.series_id], tree[m.series_id].name) > (depth[best.series_id], tree[best.series_id].name):
+                placed[m.work_id] = m
+
+    members = []
+    for w in works:
+        m = placed.get(w.id)
+        child = tree[m.series_id] if m is not None and m.series_id != series.id else None
+        members.append(_Member(w, m.position if m is not None else None, child))
+
+    def book_order(m: _Member):
+        return (m.position is None, m.position or 0.0,
+                m.work.first_publish_year is None, m.work.first_publish_year or 0, m.work.title)
+
+    earliest: dict[UUID, tuple] = {}
+    for m in members:
+        if m.subseries is not None:
+            year = m.work.first_publish_year or 9999
+            earliest[m.subseries.id] = min(earliest.get(m.subseries.id, (9999, m.subseries.name)), (year, m.subseries.name))
+
+    def group_order(m: _Member):
+        return (0, ()) if m.subseries is None else (1, earliest[m.subseries.id])
+
+    return sorted(members, key=lambda m: (group_order(m), book_order(m)))
 
 
 @router.get("/{slug}", response_model=SeriesOut)
@@ -48,7 +102,8 @@
     """A tombstoned slug answers with the survivor; the client redirects on
     seeing a different ``slug`` than it asked for."""
     series = await _series_or_404(db, slug)
-    works = await _members(db, series)
+    members = await _members(db, series)
+    works = [m.work for m in members]
     for work in [w for w in works if w.enriched_at is None][:_ENRICH_CAP]:
         await enrich_work(db, work)
         # Still unenriched means Google failed (enrich_work swallows it so the
@@ -81,8 +136,11 @@
                 first_publish_year=w.first_publish_year,
                 cover_url=presentation[w.id].cover_url if w.id in presentation else None,
                 shelf_status=shelves.get(w.id),
+                position=m.position,
+                subseries=m.subseries.name if m.subseries is not None else None,
             )
-            for w in works
+            for m in members
+            for w in [m.work]
         ],
     )
 
```

- [ ] **Step 4: Run the tests**

Run: `cd backend && DATABASE_URL=postgresql+asyncpg://margin:margin@localhost:5432/margin_test python -m pytest tests/test_series_api.py -v`
Expected: PASS (15 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/app/schemas/series.py backend/app/api/series.py backend/tests/test_series_api.py
git commit -m "feat(api): series members carry position and sub-series, in reading order"
```

---

### Task 6: Series page: positions and sub-series headings

**Files:**
- Modify: `frontend/src/pages/Series.jsx`
- Test: `frontend/src/pages/Series.test.jsx`

**Interfaces:**
- Consumes: Task 5's `position` and `subseries` fields (absent fields render exactly as today).
- Produces: `formatPosition(position) -> "#2" | "#2.5" | null` (exported); `groupBySubseries(works)`; the book list keeps `aria-label="Books in this series"`; each sub-series renders as an `<li>` holding an `h2` and a nested `<ul aria-label={name}>`.

No visual redesign (spec §6.3). The position is metadata in `text-ink-dim` above the title. The sub-series heading is serif — a series name is a book title here, exactly as the page's `h1` treats it — at the book-title size, dimmed and ruled so it reads as a heading over books rather than another book. `.eyebrow` was considered and rejected: it is `text-accent`, and accent means interactive.

- [ ] **Step 1: Write the failing tests**

Apply with `git apply`, or make the same edits by hand.

```diff
--- a/frontend/src/pages/Series.test.jsx
+++ b/frontend/src/pages/Series.test.jsx
@@ -118,6 +118,45 @@
     expect(first).not.toHaveAttribute('aria-current')
   })
 
+  it('shows each book\'s place in the series', async () => {
+    mockApi({ ...SAGA, works: [{ ...SAGA.works[0], position: 1 }, { ...SAGA.works[1], position: 2.5 }] })
+    renderPage('/series/red-rising')
+    const list = await screen.findByRole('list', { name: 'Books in this series' })
+    const [first, second] = within(list).getAllByRole('listitem')
+    expect(within(first).getByText('#1')).toBeInTheDocument()
+    expect(within(second).getByText('#2.5')).toBeInTheDocument()
+  })
+
+  it('shows no position when the catalog has none', async () => {
+    mockApi(SAGA)
+    renderPage('/series/red-rising')
+    const list = await screen.findByRole('list', { name: 'Books in this series' })
+    expect(within(list).queryByText(/^#/)).toBeNull()
+  })
+
+  it('groups books under their sub-series heading', async () => {
+    const book = (id, title, subseries, position) => ({
+      id, title, author: 'Brandon Sanderson', first_publish_year: 2006, cover_url: null,
+      shelf_status: null, position, subseries,
+    })
+    mockApi({
+      slug: 'cosmere', name: 'Cosmere', kind: 'series', description: null,
+      works: [
+        book('e', 'Elantris', null, null),
+        book('m1', 'Mistborn', 'Mistborn', 1),
+        book('m2', 'The Well of Ascension', 'Mistborn', 2),
+        book('s1', 'The Way of Kings', 'The Stormlight Archive', 1),
+      ],
+    })
+    renderPage('/series/cosmere')
+    const mistborn = await screen.findByRole('list', { name: 'Mistborn' })
+    expect(within(mistborn).getAllByRole('heading', { level: 3 }).map((h) => h.textContent)).toEqual([
+      'Mistborn', 'The Well of Ascension'])
+    expect(screen.getByRole('heading', { level: 2, name: 'The Stormlight Archive' })).toBeInTheDocument()
+    // A book in the room itself has no heading above it.
+    expect(screen.queryByRole('heading', { level: 2, name: 'Cosmere' })).toBeNull()
+  })
+
   it('ignores a ?book= that is not a member', async () => {
     mockApi(SAGA)
     renderPage('/series/red-rising?book=zzz')
```

- [ ] **Step 2: Run them to verify they fail**

Run: `cd frontend && npx vitest run src/pages/Series.test.jsx`
Expected: 2 FAIL (`shows each book's place in the series`, `groups books under their sub-series heading`); the rest pass.

- [ ] **Step 3: Implement**

Apply with `git apply` (save the block to a file first), or make the same edits by hand.

```diff
--- a/frontend/src/pages/Series.jsx
+++ b/frontend/src/pages/Series.jsx
@@ -16,6 +16,22 @@
  * shelf control — above one description and the whole series' discussion.
  * A singleton is the same page with the series chrome removed.
  */
+/** "#2", "#2.5" — a place in the series; nothing when the catalog has none. */
+export function formatPosition(position) {
+  return position == null ? null : `#${position}`
+}
+
+/** Consecutive books sharing a sub-series, in API order: [{ name, works }]. */
+function groupBySubseries(works) {
+  const groups = []
+  for (const work of works) {
+    const name = work.subseries ?? null
+    if (groups.length === 0 || groups[groups.length - 1].name !== name) groups.push({ name, works: [] })
+    groups[groups.length - 1].works.push(work)
+  }
+  return groups
+}
+
 function BookRow({ work, current, rowRef }) {
   const [coverFailed, setCoverFailed] = useState(false)
   return (
@@ -35,6 +51,9 @@
         )}
       </div>
       <div className="flex flex-col gap-2 min-w-0">
+        {work.position != null && (
+          <p className="text-ink-dim text-xs tabular-nums">{formatPosition(work.position)}</p>
+        )}
         <h3 className="font-serif text-xl text-ink leading-tight">{work.title}</h3>
         <p className="text-user text-xs lowercase tracking-eyebrow">{work.author}</p>
         {work.first_publish_year && (
@@ -174,14 +193,25 @@
       </header>
 
       <ul aria-label="Books in this series" className="flex flex-col divide-y divide-line">
-        {series.works.map((work) => (
-          <BookRow
-            key={work.id}
-            work={work}
-            current={work.id === currentId}
-            rowRef={work.id === currentId ? currentRef : undefined}
-          />
-        ))}
+        {groupBySubseries(series.works).map((group) => {
+          const rows = group.works.map((work) => (
+            <BookRow
+              key={work.id}
+              work={work}
+              current={work.id === currentId}
+              rowRef={work.id === currentId ? currentRef : undefined}
+            />
+          ))
+          if (!group.name) return rows
+          // A sub-series inside the room (Mistborn in the Cosmere) gets a heading.
+          return (
+            <li key={`group-${group.name}`} className="flex flex-col pt-6">
+              {/* Serif: a series name is a book title here too. Dim, so it reads as a heading over books. */}
+              <h2 className="font-serif text-xl text-ink-dim border-b border-line pb-2">{group.name}</h2>
+              <ul aria-label={group.name} className="flex flex-col divide-y divide-line">{rows}</ul>
+            </li>
+          )
+        })}
       </ul>
 
       <section className="panel p-5 pt-6">
```

- [ ] **Step 4: Run the frontend suite**

Run: `cd frontend && npm test`
Expected: 95 passed.

- [ ] **Step 5: Check it in the browser**

With the stack up (`docker compose up`), load a release (Task 7) or insert a member by hand, open `/series/<slug>`, and run the §36 test from CLAUDE.md: positions read as quiet metadata, headings as structure, covers still dominate, nothing looks like Goodreads.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/pages/Series.jsx frontend/src/pages/Series.test.jsx
git commit -m "feat(web): series page shows positions and sub-series"
```

---

### Task 7: Documentation and the first real load (manual)

**Files:**
- Modify: `CLAUDE.md`

**Interfaces:**
- Consumes: everything above; plan 1's first release (plan 1 Task 21) for the load step.

- [ ] **Step 1: Document the loader**

This diff applies on top of plan 1's `CLAUDE.md` change; if plan 1 has not landed, make the two edits by hand (a **Catalog releases** paragraph before **Email**, and the reworded *No admin merge/split UI* gap).

```diff
--- a/CLAUDE.md
+++ b/CLAUDE.md
@@ -193,6 +193,22 @@
 thread constraints (`ck_threads_one_home`, `ck_threads_tag_needs_series`) are
 added `NOT VALID` because 10 legacy threads orphaned by the works migration have
 no home; the backfill reports them and leaves them alone.
+
+**Catalog releases** are the catalog's seed data. `python -m
+scripts.load_catalog_release <folder | tag>` (service:
+`services/catalog_loader.py`) verifies checksums and schema, then in one
+transaction upserts series, works, editions, `series_members` and
+`work_aliases` by their deterministic ids, stamping `catalog_release`. It
+*adopts* runtime works the release also holds (by OL id, alias, or
+`canonical_key` for heuristic works) with `merge_works`, retires runtime rooms
+that emptied into the room most of their books joined, carries tagged threads
+when a book changes rooms, and settles rows a newer release dropped (deleted
+when unreferenced, kept when a thread or shelf points at them, merged when an
+alias names a survivor). Loading a release twice is a no-op; an older one is
+refused without `--force`. Runtime code never moves a work out of a release
+room (`assign_series` returns early), and a search hit for an aliased OL id
+lands on the alias target. A room's page orders books by sub-series, then
+`series_members.position`, then `first_publish_year`.
 
 **Email**: routes depend on `email_sender_dep`, never on a concrete sender — that's the seam tests override via `app.dependency_overrides`. `get_email_sender()` picks `SmtpEmailSender` when `SMTP_HOST` is set and `ConsoleEmailSender` (logs the link) otherwise, so local dev needs no SMTP server.
 
@@ -285,8 +301,9 @@
 ## Known remaining gaps
 
 - **No token revocation**: `POST /auth/logout` is a stateless no-op — the frontend just clears the persisted JWT, and a stolen token stays valid until expiry. A password reset does not invalidate existing sessions either. Anything relying on server-side session invalidation needs a refresh/denylist design first.
-- **No admin merge/split UI**: `merge_works()` and `scripts.resolve_works
-  --upgrade` are the only repair tools; a mis-grouped work needs a shell.
+- **No admin merge/split UI**: catalog fixes are `pipeline/overrides/*.yaml`
+  entries picked up by the next release; runtime works still need
+  `merge_works()` / `scripts.resolve_works --upgrade` from a shell.
 - Content is immutable (no edit/delete for threads or posts). See `ROADMAP.md` for the tracked list.
 
 ## Environment
```

- [ ] **Step 2: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: document catalog release loading"
```

- [ ] **Step 3: Back up the dev database, then load the first release into it**

```bash
docker compose exec db pg_dump -U margin margin > /tmp/margin-before-catalog.sql
docker compose exec backend alembic upgrade head
docker compose exec backend pip install pyarrow==18.1.0          # until the image is rebuilt
docker compose exec backend python -m scripts.load_catalog_release catalog-2026.10.1
```

Expected: `loaded 2026.10.1: LoadStats(...)` with `adopted` > 0 (the dev database's searched works). A second run prints `2026.10.1 is already loaded; nothing to do`. If the repository is private, the download 404s: run `gh release download catalog-2026.10.1 -D backend/releases/` (NordVPN off), unpack it there, and pass `releases/catalog-2026.10.1`.

- [ ] **Step 4: Verify the migration path of the dev data**

Open `/series/red-rising` and `/series/a-song-of-ice-and-fire`: books in position order, *A Feast for Crows* and *A Dance with Dragons* present. Open a thread that existed before the load — it must still resolve, under the release room. `SELECT count(*) FROM works WHERE catalog_release IS NULL AND merged_into_id IS NULL;` lists the runtime works the release did not know; they keep today's behaviour until the next release absorbs them. If anything is wrong, restore with `psql -U margin margin < /tmp/margin-before-catalog.sql` and file an override (plan 1) rather than editing rows.
