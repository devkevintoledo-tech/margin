# Librarian Tools Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a trusted user fix the catalog where they see it (merge, split, move, reorder, rename, remove, dissolve) on a book's series page. Each fix goes live immediately, is logged with who, when and why, can be undone (except merge and split), and is exported to `pipeline/overrides/` so later releases keep it.

**Architecture:** A `catalog_corrections` table logs every fix together with the §5.4 override entries it exports as, and an undo snapshot. `services/librarian/` holds one module per concern (keys, recording, placement ops, identity ops, undo, export rendering). Each op applies the change through the existing series/works services and records its correction in the same `get_db` transaction. A thin `api/librarian.py` maps typed service errors to 404/409/422. `scripts/export_overrides.py` renders `pipeline/overrides/z-librarian.yaml` deterministically. The series page gets a librarian edit mode, and `/librarian` lists the log.

**Tech Stack:** FastAPI, async SQLAlchemy 2.0, Alembic, Pydantic v2, PyYAML (new backend dependency), React 18 + React Query + Tailwind tokens, Vitest + RTL, Playwright.

**Spec:** `docs/superpowers/specs/2026-09-28-librarian-tools-design.md`. Read it before starting; this plan argues from it and records every place it departs from it (see "Decisions this plan adds to the spec").

## Global Constraints

- Permissions: `users.is_librarian boolean not null default false`; `require_librarian` → 401 anonymous (as `get_current_user` does today), 403 signed-in non-librarian.
- Every write body carries `reason`; stripped, it must be non-empty (422 otherwise).
- `merge_works` and `split_work` need `confirm: true`; without it: 422 with `detail = {"message": ..., "consequences": {...}}`.
- `merge_works` and `split_work` are never undoable. Their `snapshot` is always null.
- Series slugs never change on rename.
- Every `series_members` row a correction writes has `provenance='override'`, `confidence='high'`. A correction-created series has `provenance='override'`.
- `assign_series` must not move a work that has an unreverted `set_series` / `remove_from_series` correction. `series_for_subjects` never returns a dissolved series.
- Export: `python -m scripts.export_overrides [--out pipeline/overrides/z-librarian.yaml] [--check]`. Output is deterministic: the same database gives the same bytes. Order is `created_at, id`. Each entry gets a `# <reason>  (<username>, <YYYY-MM-DD>, correction <first 8 of id>)` comment. `--check` writes nothing and exits 1 on a difference.
- Schemas are built explicitly. Never `model_validate` an ORM object whose schema has a relationship field (MissingGreenlet).
- A migration that adds an enum drops it explicitly in `downgrade()`.
- Frontend: tokens only. No new radii, shadows, font sizes or durations. `warning` marks mutated state, `ok` marks exported, `danger` marks the merge/split confirmation. Every glyph is `aria-hidden`. Serif is used only for book titles and series names.
- Backend tests run in the backend container against `margin_test`. The contract tests import `pipeline/`, so mount it:
  `docker compose run --rm --no-deps -v "$PWD/pipeline:/pipeline:ro" -e DATABASE_URL=postgresql+asyncpg://margin:margin@db:5432/margin_test backend pytest <args>`
  (from the repo root). Referred to below as **`PYTEST`**. After changing `backend/requirements.txt`, run `docker compose build backend` first.

## Decisions this plan adds to the spec

The spec left these open or, read literally, would break against the pipeline as it exists. Each was checked against `pipeline/overrides.py`:

1. **`override` is a *list* of §5.4 entries, not one entry.** Pipeline `set_series` only *adds* a membership (`decision.memberships[work][series] = …`). The room is then the largest top-level series among a work's memberships (`group/nesting.py:50`). A move exported as `set_series` alone would leave the old membership in place, and the book could stay in its old room. So a move exports its `remove_from_series` entries for the old room's release memberships *first*, then the `set_series`. `apply_series` applies entries in file order (confirmed), so a later entry for the same `(work, series)` wins, and export keeps every entry. The spec's fallback (keep only the latest per pair) is not needed.
2. **Series ops on a series that is not in a catalog release are runtime-only.** Pipeline `rename_series`, `reject_series` and `remove_from_series` call `_check_target`, which fails the build for a series the build does not know. A runtime tag series has a computable `ol:` key, but nothing guarantees the next build holds it. Only `set_series` can *create* a series (with `name:`), so it stays exportable into a runtime series. Reason text: `"<name> is not in a catalog release"`.
3. **A librarian-created series gets the pipeline's own id**: `uuid5(MARGIN_NS, "series:ol:<series_key(name)>")`. The next release's upsert (`ON CONFLICT (id)`) then lands on the same row instead of creating a second room beside it. `MARGIN_NS` is copied into `services/librarian/keys.py`, and a contract test asserts it equals `pipeline.config.MARGIN_NS` and that `release_series_id` equals `pipeline.ids.row_id(series_identity(key))`. If a series with that id or external id already exists, "new series: X" reuses it.
4. **Splitting a book out of a singleton gives the new work its own singleton**, not a share of the original's page. A singleton is one book's page. A `series_members` row is written only when the room is a real series.
5. **A heuristic (runtime-only) split is refused when the new title and author produce the original's own key.** `canonical_key` equality is how `_absorb_heuristic_twin` recognises a twin, so such a split would be merged straight back.
6. **Sub-series are not move targets.** `get_series_by_slug` renders a child series as its parent room, so a work whose `series_id` is a child disappears from every page. `series-search` excludes series with a `parent_series_id`, and `set_series` refuses one with 422.
7. **Membership edits act on the room's whole tree.** A move or remove deletes the work's memberships in the room *and* its nested sub-series. `set_position` edits the membership the page actually shows (the deepest one, the same rule `api/series._members` uses), or creates a room-level one. That rule moves from `api/series.py` into `services/series.py` (Task 2) so there is one copy.
8. **Two read endpoints the spec's UI needs but its API list omits:** `GET /api/librarian/works/{id}/editions` (the split checkboxes) and an `id` field on `SeriesOut` (librarian routes address series by id).
9. **Removing a work whose old singleton still exists as a tombstone revives that singleton** (`external_id = singleton:<work id>` is unique per source). Creating a second one would violate `uq_series_source_external_id`. Undo tombstones it again.
10. **`created_at` is set in Python** (`datetime.now(timezone.utc)`, ties broken by `id`). Postgres `now()` is constant within a transaction, and "latest correction" must still order two fixes made in one test session.
11. **JSONB columns use `none_as_null=True`**, so a null `override` is SQL `NULL` and not JSON `null`, and `override IS NULL` works.

## Review Focus

The inputs and failures most likely to hurt a real librarian that no single task's happy-path test covers. Each has a test in the task that owns the code:

1. **A stale tab acts on a book that was merged away in the meantime.** Every op on a tombstoned work (`merged_into_id` set) answers 409 and does nothing (Task 4 `test_ops_on_a_merged_work_conflict`, Task 6 `test_merge_refusals`).
2. **Undo after someone started a thread on the book's new singleton page.** Undoing `remove_from_series` would silently drag that thread into the series. It must answer 409 (Task 7 `test_undo_remove_refuses_when_the_singleton_gained_a_thread`).
3. **Moving the last book out of a singleton room.** The emptied singleton is retired into the target and its untagged threads are tagged with the book. Undo must revive the room and untag exactly those threads (Task 7 `test_undo_move_revives_a_retired_singleton`).
4. **A search re-ingest right after a librarian placed a book.** `assign_series` must leave it alone, and must stop protecting it once the fix is reverted (Task 8).
5. **A reason of only whitespace, or a merge sent twice.** The first is 422. The second is 409 on the second call, never a double merge (Task 3 `test_blank_reason_is_refused`, Task 9 `test_blank_reason_is_422` and `test_merge_asks_for_confirmation_then_refuses_a_second_merge`).

---

## File Structure

**Backend — create**
- `backend/alembic/versions/b4e8d2f6a0c9_librarian_tools.py` — the one migration.
- `backend/app/models/correction.py` — `CorrectionOp`, `CatalogCorrection`.
- `backend/app/services/librarian/__init__.py` — re-exports the public ops.
- `backend/app/services/librarian/errors.py` — `LibrarianError`, `NotFound`, `Conflict`, `Invalid`, `NeedsConfirmation`.
- `backend/app/services/librarian/keys.py` — export keys, `release_series_id`, `MissingKey`.
- `backend/app/services/librarian/record.py` — `clean_reason`, `record`, `latest_for_subject`, `live_work`, `live_series`, snapshot (de)serialisers.
- `backend/app/services/librarian/placement.py` — `set_series`, `set_position`, `rename_series`, `remove_from_series`, `reject_series`.
- `backend/app/services/librarian/identity.py` — `merge`, `split`.
- `backend/app/services/librarian/undo.py` — `revert`, `UNDOABLE`.
- `backend/app/services/librarian/export.py` — `exportable`, `runtime_only`, `render`.
- `backend/app/schemas/librarian.py` — request bodies, `CorrectionOut`, `SeriesHit`, `EditionOut`.
- `backend/app/api/librarian.py` — routes.
- `backend/scripts/grant_librarian.py`, `backend/scripts/export_overrides.py`.
- `backend/tests/librarian_factories.py` — shared row builders for librarian tests.
- `backend/tests/test_librarian_{permissions,placement,identity,undo,runtime,api,export}.py`.

**Backend — modify**
- `backend/requirements.txt` (PyYAML), `backend/app/models/{__init__,user,series,work}.py`, `backend/app/schemas/{user,series}.py`, `backend/app/services/{auth,series}.py`, `backend/app/api/series.py`, `backend/app/main.py`.

**Frontend — create**
- `frontend/src/api/librarian.js`, `frontend/src/components/LibrarianPanel.jsx`, `frontend/src/components/LibrarianPanel.test.jsx`, `frontend/src/pages/Librarian.jsx`, `frontend/src/pages/Librarian.test.jsx`, `frontend/e2e/librarian.spec.js`.

**Frontend — modify**
- `frontend/src/api/errors.js` (object `detail`), `frontend/src/pages/Series.jsx`, `frontend/src/pages/Series.test.jsx`, `frontend/src/App.jsx`, `frontend/src/components/Navbar.jsx`.

**Docs — modify:** `CLAUDE.md`, `README.md`, `ROADMAP.md`, `TODO.md`, `pipeline/overrides/README.md`.

---
### Task 1: Schema, librarian flag, permissions

**Files:**
- Create: `backend/app/models/correction.py`, `backend/alembic/versions/b4e8d2f6a0c9_librarian_tools.py`, `backend/scripts/grant_librarian.py`, `backend/tests/librarian_factories.py`, `backend/tests/test_librarian_permissions.py`
- Modify: `backend/app/models/__init__.py`, `backend/app/models/user.py`, `backend/app/models/series.py`, `backend/app/models/work.py`, `backend/app/schemas/user.py`, `backend/app/services/auth.py`, `backend/requirements.txt`

**Interfaces:**
- Produces: `CorrectionOp` (str enum: `merge_works, split_work, set_series, set_position, remove_from_series, reject_series, rename_series`); `CatalogCorrection` (columns per spec §4.1); `User.is_librarian: bool`; `Series.dissolved_at: datetime | None`; `WorkProvenance.override`; `UserOut.is_librarian: bool`; `require_librarian(user=Depends(get_current_user)) -> User`; `scripts.grant_librarian.grant(db, username, revoke=False) -> bool`.
- Produces (tests): `tests/librarian_factories.py` with `make_user`, `headers_for`, `make_series`, `make_work`, `make_member`, `make_thread`, `make_edition`, `make_release`, `fresh(db, Model.column, row_id)`. Every later backend task uses these.

- [ ] **Step 1: Add PyYAML and rebuild the image**

Append to `backend/requirements.txt` (same pin as `pipeline/requirements.txt`):

```
PyYAML==6.0.2
```

Run: `docker compose build backend`
Expected: build succeeds.

- [ ] **Step 2: Write the shared factories**

`backend/tests/librarian_factories.py`:

```python
"""Row builders for librarian tests. Plain functions, not fixtures, so a test
reads as the catalog state it sets up."""

import uuid
from datetime import datetime, timezone

from sqlalchemy import select

from app.models import (
    AuthProvider, Book, CatalogRelease, MembershipConfidence, Series, SeriesKind, SeriesMember,
    SeriesProvenance, SeriesSource, Thread, User, Work, WorkKind, WorkProvenance, WorkSource,
)
from app.services.auth import create_access_token
from app.services.series_identity import series_key, slugify
from app.services.work_identity import canonical_key, heuristic_external_id


async def make_user(db, *, librarian=False, username=None):
    name = username or f"u{uuid.uuid4().hex[:10]}"
    user = User(email=f"{name}@x.test", username=name, auth_provider=AuthProvider.email,
                password_hash="x", is_librarian=librarian)
    db.add(user)
    await db.flush()
    return user


def headers_for(user):
    return {"Authorization": f"Bearer {create_access_token({'sub': str(user.id)})}"}


async def make_release(db, version="2026.10.1"):
    found = await db.get(CatalogRelease, version)
    if found is None:
        found = CatalogRelease(version=version, manifest={})
        db.add(found)
        await db.flush()
    return found


async def make_series(db, name, *, key=None, release=None, kind=SeriesKind.series, parent=None):
    """A real series. ``release`` (a version string) makes it a catalog series
    whose ``external_id`` is its pipeline key (``key`` or ``ol:<name>``)."""
    if release is not None:
        await make_release(db, release)
    s = Series(
        source=SeriesSource.openlibrary if release else SeriesSource.heuristic,
        external_id=key or (f"ol:{series_key(name)}" if release else f"franchise:{series_key(name)}"),
        name=name, slug=f"{slugify(name)}-{uuid.uuid4().hex[:4]}", canonical_key=series_key(name),
        kind=kind, provenance=SeriesProvenance.ol_tag, catalog_release=release,
        parent_series_id=parent.id if parent else None,
    )
    db.add(s)
    await db.flush()
    return s


async def make_work(db, title, *, series=None, ol_id=None, author="A. Author", release=None):
    """An Open Library work when ``ol_id`` is given, otherwise a heuristic one.
    With no ``series`` the flush listener gives it a singleton."""
    key = canonical_key(title, author)
    w = Work(
        source=WorkSource.openlibrary if ol_id else WorkSource.heuristic,
        external_id=ol_id or heuristic_external_id(key),
        canonical_key=key, title=title, author=author, kind=WorkKind.single,
        identity_provenance=WorkProvenance.isbn if ol_id else WorkProvenance.heuristic,
        series_id=series.id if series else None, catalog_release=release,
        # Already enriched: opening a series page would otherwise call Google Books.
        enriched_at=datetime.now(timezone.utc),
    )
    db.add(w)
    await db.flush()
    return w


async def make_member(db, series, work, position=None, provenance=SeriesProvenance.ol_tag):
    m = SeriesMember(series_id=series.id, work_id=work.id, position=position,
                     provenance=provenance, confidence=MembershipConfidence.medium)
    db.add(m)
    await db.flush()
    return m


async def make_thread(db, user, series, work=None, title="A thread"):
    t = Thread(title=title, user_id=user.id, series_id=series.id, work_id=work.id if work else None)
    db.add(t)
    await db.flush()
    return t


async def fresh(db, column, row_id):
    """Read one column straight from the database. ``retire_series`` updates rows
    with raw SQL, so objects already in the session can be stale."""
    return await db.scalar(select(column).where(column.class_.id == row_id))


async def make_edition(db, work, *, ol_id=None, title=None, language="en"):
    """An Open Library edition when ``ol_id`` is given, otherwise a Google volume."""
    b = Book(source="openlibrary" if ol_id else "google_books",
             external_id=ol_id or uuid.uuid4().hex[:12], title=title or work.title,
             author=work.author, language=language, work_id=work.id)
    db.add(b)
    await db.flush()
    return b
```

Check `heuristic_external_id` is exported by `app/services/work_identity.py` (`services/works.py:37` imports it from there). If it lives elsewhere, import it from where `works.py` does.

- [ ] **Step 3: Write the failing permission and script tests**

`backend/tests/test_librarian_permissions.py`:

```python
import pytest
from fastapi import HTTPException

from app.models import User
from app.services.auth import require_librarian
from scripts.grant_librarian import grant
from tests.librarian_factories import headers_for, make_user


async def test_me_reports_the_librarian_flag(client, db_session):
    user = await make_user(db_session, librarian=True)
    resp = await client.get("/api/auth/me", headers=headers_for(user))
    assert resp.status_code == 200, resp.text
    assert resp.json()["is_librarian"] is True


async def test_require_librarian_refuses_readers(db_session):
    # Anonymous is refused upstream by get_current_user (401); Task 9 checks every
    # real route end to end. Here: the dependency itself.
    reader = await make_user(db_session)
    librarian = await make_user(db_session, librarian=True)
    with pytest.raises(HTTPException) as refused:
        await require_librarian(reader)
    assert refused.value.status_code == 403
    assert await require_librarian(librarian) is librarian


async def test_public_profile_does_not_reveal_the_flag(client, db_session):
    librarian = await make_user(db_session, librarian=True)
    body = (await client.get(f"/api/users/{librarian.username}")).json()
    assert "is_librarian" not in body


async def test_grant_and_revoke_are_idempotent(db_session):
    user = await make_user(db_session)
    assert await grant(db_session, user.username) is True
    assert await grant(db_session, user.username) is True
    assert (await db_session.get(User, user.id)).is_librarian is True
    assert await grant(db_session, user.username, revoke=True) is True
    assert (await db_session.get(User, user.id)).is_librarian is False


async def test_grant_unknown_username_fails(db_session):
    assert await grant(db_session, "nobody-by-this-name") is False
```

- [ ] **Step 4: Run to verify failure**

Run: `PYTEST tests/test_librarian_permissions.py -q`
Expected: collection error, `ImportError: cannot import name 'require_librarian'` (or `is_librarian` is an invalid keyword for `User`).

- [ ] **Step 5: Models**

`backend/app/models/user.py`: import `Boolean` from sqlalchemy and add after `password_hash`:

```python
    # Trusted to fix the catalog (librarian tools). Set from a shell with
    # `python -m scripts.grant_librarian`; a role enum can replace it later.
    is_librarian: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
```

`backend/app/models/series.py`, after `merged_into_id`:

```python
    # Set by a librarian's reject_series: the room keeps its slug and its
    # untagged threads, but holds no books and takes no new threads.
    dissolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
```

`backend/app/models/work.py`, in `WorkProvenance`:

```python
    # A librarian's split_work: the identity is the split's `OL…W~OL…M` id.
    override = "override"
```

`backend/app/models/correction.py`:

```python
import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import CheckConstraint, DateTime, Enum, ForeignKey, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class CorrectionOp(str, enum.Enum):
    merge_works = "merge_works"
    split_work = "split_work"
    set_series = "set_series"
    set_position = "set_position"  # exports as set_series with a position
    remove_from_series = "remove_from_series"
    reject_series = "reject_series"
    rename_series = "rename_series"


def _now() -> datetime:
    # Python, not now(): Postgres' now() is constant within a transaction, and
    # "latest correction" has to order two fixes made in one.
    return datetime.now(timezone.utc)


class CatalogCorrection(Base):
    """One librarian fix: what it did, why, how it exports, and how to undo it."""

    __tablename__ = "catalog_corrections"
    __table_args__ = (
        CheckConstraint("(override IS NULL) = (runtime_only_reason IS NOT NULL)",
                        name="ck_catalog_corrections_export_state"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()")
    )
    op: Mapped[CorrectionOp] = mapped_column(Enum(CorrectionOp, name="correction_op_enum"), nullable=False)
    # App ids the op acted on, as strings.
    payload: Mapped[dict] = mapped_column(JSONB(none_as_null=True), nullable=False)
    # The §5.4 entries this fix exports as, in order; null = runtime-only.
    override: Mapped[list | None] = mapped_column(JSONB(none_as_null=True), nullable=True)
    runtime_only_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    snapshot: Mapped[dict | None] = mapped_column(JSONB(none_as_null=True), nullable=True)
    work_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("works.id", ondelete="SET NULL"), nullable=True, index=True
    )
    series_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("series.id", ondelete="SET NULL"), nullable=True, index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, server_default=text("clock_timestamp()"), nullable=False
    )
    reverted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reverted_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
```

`backend/app/models/__init__.py`: add `from app.models.correction import CatalogCorrection, CorrectionOp` and both names to `__all__`.

- [ ] **Step 6: Migration**

`backend/alembic/versions/b4e8d2f6a0c9_librarian_tools.py`:

```python
"""librarian tools: corrections log, librarian flag, dissolved series

Revision ID: b4e8d2f6a0c9
Revises: a9d3e5f7c1b2
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b4e8d2f6a0c9"
down_revision: Union[str, None] = "a9d3e5f7c1b2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

OPS = ("merge_works", "split_work", "set_series", "set_position", "remove_from_series",
       "reject_series", "rename_series")


def upgrade() -> None:
    # ADD VALUE cannot run in a transaction block on older Postgres, and nothing
    # below uses the new value in this transaction.
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE work_provenance_enum ADD VALUE IF NOT EXISTS 'override'")

    op.add_column("users", sa.Column("is_librarian", sa.Boolean(), server_default=sa.text("false"),
                                     nullable=False))
    op.add_column("series", sa.Column("dissolved_at", sa.DateTime(timezone=True), nullable=True))

    op_enum = postgresql.ENUM(*OPS, name="correction_op_enum", create_type=False)
    op_enum.create(op.get_bind(), checkfirst=True)
    op.create_table(
        "catalog_corrections",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"),
                  nullable=False),
        sa.Column("op", op_enum, nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("override", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("runtime_only_reason", sa.Text(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("work_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("series_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("clock_timestamp()"),
                  nullable=False),
        sa.Column("reverted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reverted_by_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.CheckConstraint("(override IS NULL) = (runtime_only_reason IS NOT NULL)",
                           name="ck_catalog_corrections_export_state"),
        sa.ForeignKeyConstraint(["work_id"], ["works.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["series_id"], ["series.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["reverted_by_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_catalog_corrections_work_id", "catalog_corrections", ["work_id"])
    op.create_index("ix_catalog_corrections_series_id", "catalog_corrections", ["series_id"])
    op.create_index("ix_catalog_corrections_user_id", "catalog_corrections", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_catalog_corrections_user_id", table_name="catalog_corrections")
    op.drop_index("ix_catalog_corrections_series_id", table_name="catalog_corrections")
    op.drop_index("ix_catalog_corrections_work_id", table_name="catalog_corrections")
    op.drop_table("catalog_corrections")
    sa.Enum(name="correction_op_enum").drop(op.get_bind(), checkfirst=True)
    op.drop_column("series", "dissolved_at")
    op.drop_column("users", "is_librarian")
    # Postgres cannot drop an enum value. 'override' stays on
    # work_provenance_enum; nothing references it once split works are gone,
    # and ADD VALUE IF NOT EXISTS makes re-upgrading safe.
```

- [ ] **Step 7: Schema, dependency, script**

`backend/app/schemas/user.py`, in `UserOut` (the signed-in user's own view; never on `PublicUserOut`):

```python
    # Decides what the frontend renders; the API enforces it (require_librarian).
    is_librarian: bool = False
```

`backend/app/services/auth.py`, after `get_current_user_optional`:

```python
async def require_librarian(user: User = Depends(get_current_user)) -> User:
    """A signed-in librarian: 401 for anonymous (via get_current_user), 403 for a reader."""
    if not user.is_librarian:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Librarians only.")
    return user
```

`backend/scripts/grant_librarian.py`:

```python
"""Grant or revoke librarian: ``python -m scripts.grant_librarian <username> [--revoke]``.

Idempotent. An unknown username exits 1.
"""

import argparse
import asyncio
import sys

from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.models import User


async def grant(db, username: str, revoke: bool = False) -> bool:
    user = (await db.execute(select(User).where(User.username == username))).scalar_one_or_none()
    if user is None:
        return False
    user.is_librarian = not revoke
    await db.flush()
    return True


async def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m scripts.grant_librarian")
    parser.add_argument("username")
    parser.add_argument("--revoke", action="store_true")
    args = parser.parse_args(argv)
    async with AsyncSessionLocal() as db:
        if not await grant(db, args.username, args.revoke):
            print(f"no user named {args.username!r}", file=sys.stderr)
            return 1
        await db.commit()
    print(f"{'revoked' if args.revoke else 'granted'} librarian: {args.username}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
```

- [ ] **Step 8: Run the tests, then check the migration round-trips**

Run: `PYTEST tests/test_librarian_permissions.py -q`
Expected: 5 passed.

Run against the dev database:
```bash
docker compose up -d db
docker compose run --rm --no-deps backend sh -c "alembic upgrade head && alembic downgrade -1 && alembic upgrade head"
```
Expected: no errors (in particular no "type correction_op_enum already exists").

- [ ] **Step 9: Full suite and commit**

Run: `PYTEST -q -p no:warnings`
Expected: everything passes. The `ck_catalog_corrections_export_state` constraint is unused so far.

```bash
git add backend/requirements.txt backend/app/models backend/alembic/versions/b4e8d2f6a0c9_librarian_tools.py \
  backend/app/schemas/user.py backend/app/services/auth.py backend/scripts/grant_librarian.py \
  backend/tests/librarian_factories.py backend/tests/test_librarian_permissions.py
git commit -m "feat(db): catalog corrections, librarian flag and dissolved series"
```

---

### Task 2: Room-tree helpers, dissolved series, series page fields

**Files:**
- Modify: `backend/app/services/series.py`, `backend/app/api/series.py`, `backend/app/schemas/series.py`
- Test: `backend/tests/test_series_api.py` (append), `backend/tests/test_series_service.py` (append)

**Interfaces:**
- Consumes: `Series.dissolved_at`, `User.is_librarian` (Task 1).
- Produces, in `app/services/series.py`:
  - `async def room_tree(db, room: Series) -> tuple[dict[UUID, Series], dict[UUID, int]]` — the room plus every live nested series (up to 5 levels), and each one's depth (room = 0).
  - `async def placed_memberships(db, room: Series, work_ids: list[UUID]) -> tuple[dict[UUID, SeriesMember], dict[UUID, Series]]` — for each work, the membership the page places it by (the deepest in the tree, name as tiebreak), plus the tree.
  - `async def tree_memberships(db, room: Series, work_id: UUID) -> list[SeriesMember]` — every membership of `work_id` in the room's tree.
- Produces, on the API: `SeriesOut.id: UUID`, `SeriesOut.dissolved: bool`, `SeriesWorkOut.provenance: SeriesProvenance | None` (set only for a librarian viewer); `POST /api/series/{slug}/threads` → 409 on a dissolved series.

- [ ] **Step 1: Failing tests**

Append to `backend/tests/test_series_service.py`:

```python
from datetime import datetime, timezone

from app.services.series import placed_memberships, series_for_subjects, tree_memberships
from tests.librarian_factories import make_member, make_series, make_work


async def test_placed_membership_is_the_deepest_in_the_room_tree(db_session):
    cosmere = await make_series(db_session, "Cosmere", release="2026.10.1")
    mistborn = await make_series(db_session, "Mistborn", release="2026.10.1", parent=cosmere)
    book = await make_work(db_session, "The Final Empire", series=cosmere, ol_id="OL1W")
    await make_member(db_session, cosmere, book, 3.0)
    deep = await make_member(db_session, mistborn, book, 1.0)
    placed, tree = await placed_memberships(db_session, cosmere, [book.id])
    assert placed[book.id] is deep and set(tree) == {cosmere.id, mistborn.id}
    assert {m.series_id for m in await tree_memberships(db_session, cosmere, book.id)} == {cosmere.id, mistborn.id}


async def test_a_dissolved_series_is_never_chosen_for_subjects(db_session):
    red = await series_for_subjects(db_session, "franchise:Red Rising")
    red.dissolved_at = datetime.now(timezone.utc)
    await db_session.flush()
    assert await series_for_subjects(db_session, "franchise:Red Rising") is None
```

Append to `backend/tests/test_series_api.py`:

```python
from datetime import datetime, timezone

from tests.librarian_factories import headers_for, make_member, make_series, make_user, make_work


async def test_series_page_carries_id_dissolved_and_librarian_provenance(client, db_session):
    saga = await make_series(db_session, "Saga", release="2026.10.1")
    book = await make_work(db_session, "Saga One", series=saga, ol_id="OL5W")
    await make_member(db_session, saga, book, 1.0)
    reader, librarian = await make_user(db_session), await make_user(db_session, librarian=True)

    as_reader = (await client.get(f"/api/series/{saga.slug}", headers=headers_for(reader))).json()
    assert as_reader["id"] == str(saga.id) and as_reader["dissolved"] is False
    assert as_reader["works"][0]["provenance"] is None

    as_librarian = (await client.get(f"/api/series/{saga.slug}", headers=headers_for(librarian))).json()
    assert as_librarian["works"][0]["provenance"] == "ol_tag"


async def test_a_dissolved_series_takes_no_new_threads(client, db_session):
    saga = await make_series(db_session, "Gone")
    saga.dissolved_at = datetime.now(timezone.utc)
    user = await make_user(db_session)
    await db_session.flush()
    resp = await client.post(f"/api/series/{saga.slug}/threads", json={"title": "hi"}, headers=headers_for(user))
    assert resp.status_code == 409, resp.text
    assert (await client.get(f"/api/series/{saga.slug}")).json()["dissolved"] is True
```

- [ ] **Step 2: Run to verify failure**

Run: `PYTEST tests/test_series_service.py tests/test_series_api.py -q`
Expected: ImportError for `placed_memberships`; after that is fixed, KeyError `'id'`.

- [ ] **Step 3: Move the tree rule into the service**

In `backend/app/services/series.py` add `SeriesMember` to the models import and:

```python
_MAX_NESTING = 5


async def room_tree(db: AsyncSession, room: Series) -> tuple[dict[uuid.UUID, Series], dict[uuid.UUID, int]]:
    """The room and every live series nested under it, with each one's depth."""
    tree, depth, frontier = {room.id: room}, {room.id: 0}, [room.id]
    for level in range(1, _MAX_NESTING + 1):
        children = (await db.execute(select(Series).where(
            Series.parent_series_id.in_(frontier), Series.merged_into_id.is_(None)))).scalars().all()
        frontier = [c.id for c in children if c.id not in tree]
        for child in children:
            tree.setdefault(child.id, child)
            depth.setdefault(child.id, level)
        if not frontier:
            break
    return tree, depth


async def placed_memberships(
    db: AsyncSession, room: Series, work_ids: list[uuid.UUID]
) -> tuple[dict[uuid.UUID, SeriesMember], dict[uuid.UUID, Series]]:
    """Each work's membership the room's page places it by: the deepest series
    of the tree, so *Mistborn* lists under its own heading inside the Cosmere."""
    tree, depth = await room_tree(db, room)
    placed: dict[uuid.UUID, SeriesMember] = {}
    if work_ids:
        rows = (await db.execute(select(SeriesMember).where(
            SeriesMember.work_id.in_(work_ids), SeriesMember.series_id.in_(list(tree))
        ))).scalars().all()
        for m in rows:
            best = placed.get(m.work_id)
            if best is None or (depth[m.series_id], tree[m.series_id].name) > (
                depth[best.series_id], tree[best.series_id].name
            ):
                placed[m.work_id] = m
    return placed, tree


async def tree_memberships(db: AsyncSession, room: Series, work_id: uuid.UUID) -> list[SeriesMember]:
    tree, _ = await room_tree(db, room)
    return list((await db.execute(select(SeriesMember).where(
        SeriesMember.work_id == work_id, SeriesMember.series_id.in_(list(tree))
    ).order_by(SeriesMember.series_id))).scalars().all())
```

In `series_for_subjects`, replace `return await canonical_series(db, existing)` with:

```python
        found = await canonical_series(db, existing)
        # A librarian dissolved it: its books stay on their own pages.
        return None if found.dissolved_at is not None else found
```

In `backend/app/api/series.py`, replace the body of `_members` up to `members = []` with:

```python
    works = list((await db.execute(
        select(Work).where(Work.series_id == series.id, Work.merged_into_id.is_(None))
    )).scalars().all())
    placed, tree = await placed_memberships(db, series, [w.id for w in works])
```

Then delete the module's `_MAX_NESTING` and import `placed_memberships` from `app.services.series`. Extend `_Member` with `provenance: SeriesProvenance | None` and build it as `_Member(w, m.position if m else None, child, m.provenance if m else None)`.

In `backend/app/schemas/series.py`: `SeriesOut` gains `id: UUID` (first field) and `dissolved: bool = False`. `SeriesWorkOut` gains:

```python
    # Librarian edit mode only: marks rows a correction placed ('override').
    provenance: SeriesProvenance | None = None
```

(import `SeriesProvenance` from `app.models.series`).

In `get_series`: pass `id=series.id`, `dissolved=series.dissolved_at is not None`, and per work `provenance=m.provenance if current_user is not None and current_user.is_librarian else None`.

In `create_series_thread`, right after `_series_or_404`:

```python
    if series.dissolved_at is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                            detail="This series was dissolved; its books have their own pages now.")
```

- [ ] **Step 4: Run the tests**

Run: `PYTEST tests/test_series_service.py tests/test_series_api.py -q`
Expected: all pass, including the existing ordering tests. The refactor must not change page order.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/series.py backend/app/api/series.py backend/app/schemas/series.py \
  backend/tests/test_series_service.py backend/tests/test_series_api.py
git commit -m "feat(series): room-tree helpers in the service; dissolved series take no threads"
```

---
### Task 3: Export keys, errors and the correction record

**Files:**
- Create: `backend/app/services/librarian/__init__.py`, `backend/app/services/librarian/errors.py`, `backend/app/services/librarian/keys.py`, `backend/app/services/librarian/record.py`, `backend/tests/test_librarian_record.py`
- Modify: `backend/app/services/series_identity.py`, `pipeline/_backend.py`, `pipeline/tests/test_backend_rules.py`

**Interfaces:**
- Produces, in `app/services/series_identity.py` (pure, importable by the pipeline): `CATALOG_NAMESPACE: uuid.UUID`, `new_series_key(name: str) -> str` (`"ol:<series_key(name)>"`), `release_series_id(key: str) -> uuid.UUID`.
- Produces, in `app/services/librarian/errors.py`: `LibrarianError(message, consequences=None)` with `.status_code`, `.message`, `.consequences`; subclasses `NotFound` (404), `Conflict` (409), `Invalid` (422), `NeedsConfirmation(message, consequences)` (422).
- Produces, in `app/services/librarian/keys.py`: `MissingKey(Exception)`; `work_key(work) -> str`; `edition_key(book) -> str`; `series_key_of(series) -> str`; `release_series_key(series) -> str` (each raises `MissingKey(reason)`); `exported(build) -> tuple[list[dict] | None, str | None]`.
- Produces, in `app/services/librarian/record.py`: `clean_reason(reason) -> str`; `live_work(work) -> Work`; `live_series(series) -> Series`; `member_state(m) -> dict`; `restore_member(state) -> SeriesMember`; `ids(items) -> list[str]`; `uuids(strings) -> list[UUID]`; `async record(db, *, op, user, reason, payload, entries, runtime_only_reason, snapshot=None, work=None, series=None) -> CatalogCorrection`; `SERIES_SUBJECT_OPS`; `async latest_for_subject(db, correction) -> CatalogCorrection | None`.

- [ ] **Step 1: Failing tests**

`backend/tests/test_librarian_record.py`:

```python
import pytest

from app.models import CorrectionOp, SeriesKind
from app.services.librarian.errors import Conflict, Invalid
from app.services.librarian.keys import (
    MissingKey, edition_key, exported, release_series_key, series_key_of, work_key,
)
from app.services.librarian.record import clean_reason, latest_for_subject, live_work, record
from app.services.series_identity import new_series_key
from tests.librarian_factories import make_edition, make_series, make_user, make_work


async def test_keys_for_open_library_and_release_rows(db_session):
    saga = await make_series(db_session, "Red Rising", release="2026.10.1")
    book = await make_work(db_session, "Golden Son", series=saga, ol_id="OL31W")
    edition = await make_edition(db_session, book, ol_id="OL300M")
    assert (work_key(book), edition_key(edition)) == ("OL31W", "OL300M")
    assert series_key_of(saga) == release_series_key(saga) == "ol:red rising"


async def test_missing_keys_name_what_is_missing(db_session):
    runtime = await make_series(db_session, "Dune Saga")  # external_id franchise:dune saga
    heuristic = await make_work(db_session, "Obscure Book", series=runtime)
    google = await make_edition(db_session, heuristic)
    assert series_key_of(runtime) == "ol:dune saga"
    with pytest.raises(MissingKey, match="no Open Library id"):
        work_key(heuristic)
    with pytest.raises(MissingKey, match="Google Books volume"):
        edition_key(google)
    with pytest.raises(MissingKey, match="not in a catalog release"):
        release_series_key(runtime)
    single = await make_series(db_session, "Lonely", kind=SeriesKind.singleton)
    with pytest.raises(MissingKey, match="single book"):
        series_key_of(single)


def test_exported_turns_a_missing_key_into_a_reason():
    def build():
        raise MissingKey("nope")
    assert exported(lambda: [{"reject_series": "ol:x"}]) == ([{"reject_series": "ol:x"}], None)
    assert exported(build) == (None, "nope")


def test_new_series_key_is_normalized():
    assert new_series_key("The Lord of the Rings!") == "ol:the lord of the rings"


def test_blank_reason_is_refused():
    assert clean_reason("  typo in title \n") == "typo in title"
    for blank in ("", "   ", None):
        with pytest.raises(Invalid):
            clean_reason(blank)


async def test_live_work_refuses_a_tombstone(db_session):
    a = await make_work(db_session, "A", ol_id="OL1W")
    b = await make_work(db_session, "B", ol_id="OL2W")
    a.merged_into_id = b.id
    with pytest.raises(Conflict):
        live_work(a)


async def test_latest_for_subject_orders_fixes_made_in_one_transaction(db_session):
    user = await make_user(db_session, librarian=True)
    saga = await make_series(db_session, "Saga", release="2026.10.1")
    book = await make_work(db_session, "One", series=saga, ol_id="OL9W")
    common = dict(user=user, reason="r", payload={}, entries=[{"x": 1}], runtime_only_reason=None)
    first = await record(db_session, op=CorrectionOp.set_position, work=book, series=saga, **common)
    second = await record(db_session, op=CorrectionOp.set_position, work=book, series=saga, **common)
    rename = await record(db_session, op=CorrectionOp.rename_series, series=saga, **common)
    assert (await latest_for_subject(db_session, first)).id == second.id
    assert (await latest_for_subject(db_session, rename)).id == rename.id
```

Append to `pipeline/tests/test_backend_rules.py`:

```python
def test_librarian_series_ids_are_the_pipelines():
    """A series a librarian creates in the app must be the row the next release upserts."""
    import pipeline._backend  # noqa: F401  (puts backend/ on sys.path)
    from app.services.series_identity import CATALOG_NAMESPACE, new_series_key, release_series_id

    from pipeline.config import MARGIN_NS
    from pipeline.ids import row_id, series_identity
    from pipeline.overrides import normalize_series_key

    assert CATALOG_NAMESPACE == MARGIN_NS
    key = new_series_key("The Lord of the Rings")
    assert key == normalize_series_key("ol:The Lord of the Rings")
    assert str(release_series_id(key)) == row_id(series_identity(key))
```

- [ ] **Step 2: Run to verify failure**

Run: `PYTEST tests/test_librarian_record.py -q`
Expected: `ModuleNotFoundError: No module named 'app.services.librarian'`.
Run: `cd pipeline && .venv/bin/python -m pytest tests/test_backend_rules.py -q` (create the venv first if missing: see CLAUDE.md)
Expected: ImportError for `CATALOG_NAMESPACE`.

- [ ] **Step 3: Pure id rules**

Append to `backend/app/services/series_identity.py` (add `import uuid` at the top; keep the module free of app/ORM imports because `test_pure_imports.py` enforces it):

```python
# The catalog pipeline's namespace (pipeline/config.py MARGIN_NS). Never change
# it: every release row id is derived from it. The pipeline suite asserts the two
# are equal.
CATALOG_NAMESPACE = uuid.UUID("7c1d0a4e-3b5f-4e2a-9d6c-8f4b2a1e0c37")


def new_series_key(name: str) -> str:
    """The pipeline key a librarian-named series exports under."""
    return f"ol:{series_key(name)}"


def release_series_id(key: str) -> uuid.UUID:
    """The id a release gives the series with this key (pipeline ids.row_id), so a
    series created in the app is the same row the next release upserts."""
    return uuid.uuid5(CATALOG_NAMESPACE, f"series:{key}")
```

In `pipeline/_backend.py` add `CATALOG_NAMESPACE, new_series_key, release_series_id` to the `app.services.series_identity` import list.

- [ ] **Step 4: Errors, keys, record**

`backend/app/services/librarian/errors.py`:

```python
"""Typed failures the librarian routes map to HTTP statuses (spec §8)."""


class LibrarianError(Exception):
    status_code = 400

    def __init__(self, message: str, consequences: dict | None = None):
        super().__init__(message)
        self.message = message
        self.consequences = consequences


class NotFound(LibrarianError):
    status_code = 404


class Conflict(LibrarianError):
    """The subject changed underneath the request."""

    status_code = 409


class Invalid(LibrarianError):
    """Impossible or incomplete."""

    status_code = 422


class NeedsConfirmation(Invalid):
    """Merge and split answer with what they would do; the client confirms."""

    def __init__(self, message: str, consequences: dict):
        super().__init__(message, consequences)
```

`backend/app/services/librarian/keys.py`:

```python
"""How app rows are named in pipeline/overrides (spec §5.1).

A fix is exportable only when every row it names has a key the next build
holds. Otherwise it applies in the app and is reported as runtime-only, with the
first missing key as the reason.
"""

from typing import Callable

from app.models import Book, Series, SeriesKind, Work, WorkSource


class MissingKey(Exception):
    pass


def work_key(work: Work) -> str:
    if work.source is WorkSource.openlibrary:
        return work.external_id  # includes a split's OL…W~OL…M
    raise MissingKey(f"{work.title} has no Open Library id (heuristic work)")


def edition_key(book: Book) -> str:
    if book.source == "openlibrary":
        return book.external_id
    raise MissingKey(f"edition {book.external_id} of {book.title} is a Google Books volume")


def series_key_of(series: Series) -> str:
    if series.kind is SeriesKind.singleton:
        raise MissingKey(f"{series.name} is a single book's page, not a series")
    if series.external_id.startswith(("wd:", "ol:")):
        return series.external_id
    return f"ol:{series.canonical_key}"


def release_series_key(series: Series) -> str:
    """The key of a series the next build is known to hold.

    rename, reject and remove fail the pipeline build for a series it does not
    know (overrides._check_target); only set_series can create one.
    """
    if series.catalog_release is None:
        raise MissingKey(f"{series.name} is not in a catalog release")
    return series_key_of(series)


def exported(build: Callable[[], list[dict]]) -> tuple[list[dict] | None, str | None]:
    """``(entries, None)``, or ``(None, reason)`` when a key is missing."""
    try:
        return build(), None
    except MissingKey as exc:
        return None, str(exc)
```

`backend/app/services/librarian/record.py`:

```python
"""Writing and reading the corrections log."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    CatalogCorrection, CorrectionOp, MembershipConfidence, Series, SeriesMember, SeriesProvenance, User, Work,
)
from app.services.librarian.errors import Conflict, Invalid, NotFound

# Corrections whose subject is a series; every other op's subject is a work.
SERIES_SUBJECT_OPS = (CorrectionOp.rename_series, CorrectionOp.reject_series)


def clean_reason(reason: str | None) -> str:
    cleaned = (reason or "").strip()
    if not cleaned:
        raise Invalid("Say why: a reason is required.")
    return cleaned


def live_work(work: Work | None) -> Work:
    if work is None:
        raise NotFound("Unknown book.")
    if work.merged_into_id is not None:
        raise Conflict(f"{work.title} was merged into another book; reload the page.")
    return work


def live_series(series: Series | None) -> Series:
    if series is None:
        raise NotFound("Unknown series.")
    if series.merged_into_id is not None:
        raise Conflict(f"{series.name} was merged into another series; reload the page.")
    return series


def ids(items) -> list[str]:
    return [str(i) for i in items]


def uuids(strings) -> list[UUID]:
    return [UUID(s) for s in strings]


def member_state(m: SeriesMember) -> dict:
    return {"series_id": str(m.series_id), "work_id": str(m.work_id), "position": m.position,
            "provenance": m.provenance.value, "confidence": m.confidence.value}


def restore_member(state: dict) -> SeriesMember:
    return SeriesMember(series_id=UUID(state["series_id"]), work_id=UUID(state["work_id"]),
                        position=state["position"], provenance=SeriesProvenance(state["provenance"]),
                        confidence=MembershipConfidence(state["confidence"]))


async def record(db: AsyncSession, *, op: CorrectionOp, user: User, reason: str, payload: dict,
                 entries: list[dict] | None, runtime_only_reason: str | None, snapshot: dict | None = None,
                 work: Work | None = None, series: Series | None = None) -> CatalogCorrection:
    correction = CatalogCorrection(
        op=op, user_id=user.id, reason=reason, payload=payload, override=entries,
        runtime_only_reason=runtime_only_reason, snapshot=snapshot,
        work_id=work.id if work is not None else None, series_id=series.id if series is not None else None,
    )
    db.add(correction)
    await db.flush()
    return correction


async def latest_for_subject(db: AsyncSession, correction: CatalogCorrection) -> CatalogCorrection | None:
    """The newest unreverted fix on the same subject: its work, or its series for
    rename and dissolve."""
    query = select(CatalogCorrection).where(CatalogCorrection.reverted_at.is_(None))
    if correction.op in SERIES_SUBJECT_OPS:
        if correction.series_id is None:
            return None
        query = query.where(CatalogCorrection.series_id == correction.series_id,
                            CatalogCorrection.op.in_(SERIES_SUBJECT_OPS))
    else:
        if correction.work_id is None:
            return None
        query = query.where(CatalogCorrection.work_id == correction.work_id)
    query = query.order_by(CatalogCorrection.created_at.desc(), CatalogCorrection.id.desc()).limit(1)
    return (await db.execute(query)).scalar_one_or_none()
```

`backend/app/services/librarian/__init__.py`:

```python
"""Librarian tools (spec 2026-09-28): catalog fixes, logged, undoable, exported."""
```

(Task 4 onwards add re-exports here.)

- [ ] **Step 5: Run the tests**

Run: `PYTEST tests/test_librarian_record.py tests/test_pure_imports.py -q`
Expected: all pass.
Run: `cd pipeline && .venv/bin/python -m pytest tests/test_backend_rules.py -q`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/librarian backend/app/services/series_identity.py backend/tests/test_librarian_record.py \
  pipeline/_backend.py pipeline/tests/test_backend_rules.py
git commit -m "feat(librarian): export keys, typed errors and the corrections record"
```

---
### Task 4: Move, reorder and rename

**Files:**
- Create: `backend/app/services/librarian/placement.py`, `backend/tests/test_librarian_placement.py`
- Modify: `backend/app/services/librarian/__init__.py`

**Interfaces:**
- Consumes: Task 2 `placed_memberships`, `tree_memberships`; Task 3 keys/record/errors; `catalog_loader.retire_series(db, old, survivor, book=None) -> int`; `series.unique_slug`, `series.canonical_series`, `series.singleton_series_for`.
- Produces, in `app/services/librarian/placement.py` (all return the `CatalogCorrection`):
  - `async set_series(db, user, work, *, reason, series=None, new_series_name=None, position=None)`
  - `async set_position(db, user, room, work, position, *, reason)`
  - `async rename_series(db, user, series, name, *, reason)`
  - Helpers Task 5 reuses: `_override_member(series_id, work_id, position)`, `async _move_tagged_threads(db, work_id, from_room, to_room) -> list[str]`, `async _live_count(db, room_id) -> int`.
- Snapshot shapes Task 7 relies on:
  - `set_series`: `{"old_room", "old_members": [member_state], "prior_target_member": member_state | None, "created_series": id | None, "moved_threads": [id], "retired": None | {"room", "parent", "threads", "tagged", "works", "repointed"}}`
  - `set_position`: `{"member_series": id, "prior": member_state | None}`
  - `rename_series`: `{"old_name": str}`
  - `payload` always carries `work` / `series` ids as strings, plus `position` (set_series, set_position) and `name` (rename).

- [ ] **Step 1: Failing tests**

`backend/tests/test_librarian_placement.py`:

```python
import pytest

from app.models import CorrectionOp, Series, SeriesKind, SeriesMember, SeriesProvenance, Thread, Work
from app.services.librarian.errors import Conflict, Invalid
from app.services.librarian.placement import rename_series, set_position, set_series
from app.services.series_identity import release_series_id
from tests.librarian_factories import (
    fresh, make_member, make_series, make_thread, make_user, make_work,
)

R = "2026.10.1"


async def members_of(db, work):
    return {(m.series_id, m.position, m.provenance) for m in
            (await db.execute(SeriesMember.__table__.select().where(SeriesMember.work_id == work.id))).all()}


async def test_move_into_an_existing_series_carries_tagged_threads(db_session):
    lib = await make_user(db_session, librarian=True)
    a = await make_series(db_session, "Alpha", release=R)
    b = await make_series(db_session, "Beta", release=R)
    x = await make_work(db_session, "Book X", series=a, ol_id="OL1W")
    y = await make_work(db_session, "Book Y", series=a, ol_id="OL2W")
    await make_member(db_session, a, x, 1.0)
    await make_member(db_session, a, y, 2.0)
    tagged = await make_thread(db_session, lib, a, x)
    untagged = await make_thread(db_session, lib, a)

    c = await set_series(db_session, lib, x, series=b, position=2, reason="Beta, per the author")

    assert c.op is CorrectionOp.set_series and c.work_id == x.id and c.series_id == b.id
    assert await fresh(db_session, Work.series_id, x.id) == b.id
    assert await fresh(db_session, Thread.series_id, tagged.id) == b.id
    assert await fresh(db_session, Thread.series_id, untagged.id) == a.id
    assert await members_of(db_session, x) == {(b.id, 2.0, SeriesProvenance.override)}
    assert c.override == [
        {"remove_from_series": {"work": "OL1W", "series": "ol:alpha"}},
        {"set_series": {"work": "OL1W", "series": "ol:beta", "position": 2}},
    ]
    assert c.runtime_only_reason is None
    assert c.snapshot["moved_threads"] == [str(tagged.id)] and c.snapshot["retired"] is None


async def test_move_into_a_new_series_uses_the_release_id_and_retires_the_singleton(db_session):
    lib = await make_user(db_session, librarian=True)
    x = await make_work(db_session, "The Fifth Season")  # heuristic, in its own singleton
    old_room = x.series_id
    about_it = await make_thread(db_session, lib, await db_session.get(Series, old_room))

    c = await set_series(db_session, lib, x, new_series_name="The Broken Earth", reason="trilogy")

    target = await db_session.get(Series, release_series_id("ol:the broken earth"))
    assert target is not None and target.kind is SeriesKind.series
    assert target.provenance is SeriesProvenance.override and target.external_id == "ol:the broken earth"
    assert await fresh(db_session, Work.series_id, x.id) == target.id
    # The emptied singleton follows its book; its untagged thread was about that book.
    assert await fresh(db_session, Series.merged_into_id, old_room) == target.id
    assert await fresh(db_session, Thread.series_id, about_it.id) == target.id
    assert await fresh(db_session, Thread.work_id, about_it.id) == x.id
    assert c.snapshot["created_series"] == str(target.id)
    assert c.snapshot["retired"]["tagged"] == [str(about_it.id)]
    assert c.override is None and "no Open Library id" in c.runtime_only_reason

    y = await make_work(db_session, "The Obelisk Gate")
    again = await set_series(db_session, lib, y, new_series_name="the broken earth", reason="book two")
    assert again.series_id == target.id and again.snapshot["created_series"] is None


async def test_a_move_into_a_runtime_series_exports_with_its_name(db_session):
    lib = await make_user(db_session, librarian=True)
    runtime = await make_series(db_session, "Dune Saga")  # franchise:dune saga, no release
    x = await make_work(db_session, "Dune", ol_id="OL8W")
    c = await set_series(db_session, lib, x, series=runtime, reason="it is Dune")
    assert c.override == [{"set_series": {"work": "OL8W", "series": "ol:dune saga", "name": "Dune Saga"}}]


async def test_move_refuses_impossible_targets(db_session):
    lib = await make_user(db_session, librarian=True)
    a = await make_series(db_session, "Alpha", release=R)
    child = await make_series(db_session, "Alpha Child", release=R, parent=a)
    gone = await make_series(db_session, "Gone")
    from datetime import datetime, timezone
    gone.dissolved_at = datetime.now(timezone.utc)
    x = await make_work(db_session, "Book X", series=a, ol_id="OL1W")
    lonely = await make_work(db_session, "Lonely")
    single = await db_session.get(Series, lonely.series_id)
    with pytest.raises(Invalid, match="already in"):
        await set_series(db_session, lib, x, series=a, reason="r")
    with pytest.raises(Invalid, match="single book"):
        await set_series(db_session, lib, x, series=single, reason="r")
    with pytest.raises(Invalid, match="sub-series"):
        await set_series(db_session, lib, x, series=child, reason="r")
    with pytest.raises(Conflict, match="dissolved"):
        await set_series(db_session, lib, x, series=gone, reason="r")
    with pytest.raises(Invalid):
        await set_series(db_session, lib, x, series=gone, new_series_name="Both", reason="r")
    with pytest.raises(Invalid, match="reason"):
        await set_series(db_session, lib, x, new_series_name="Fine", reason="   ")


async def test_ops_on_a_merged_work_conflict(db_session):
    lib = await make_user(db_session, librarian=True)
    a = await make_series(db_session, "Alpha", release=R)
    x = await make_work(db_session, "Book X", series=a, ol_id="OL1W")
    y = await make_work(db_session, "Book Y", series=a, ol_id="OL2W")
    x.merged_into_id = y.id
    await db_session.flush()
    with pytest.raises(Conflict, match="merged"):
        await set_series(db_session, lib, x, new_series_name="Elsewhere", reason="r")
    with pytest.raises(Conflict, match="merged"):
        await set_position(db_session, lib, a, x, 1, reason="r")


async def test_set_position_edits_the_membership_the_page_shows(db_session):
    lib = await make_user(db_session, librarian=True)
    cosmere = await make_series(db_session, "Cosmere", release=R)
    mistborn = await make_series(db_session, "Mistborn", release=R, parent=cosmere)
    book = await make_work(db_session, "The Well of Ascension", series=cosmere, ol_id="OL3W")
    await make_member(db_session, cosmere, book, 7.0)
    await make_member(db_session, mistborn, book, 3.0)

    c = await set_position(db_session, lib, cosmere, book, 2.0, reason="book two")

    assert await members_of(db_session, book) == {
        (cosmere.id, 7.0, SeriesProvenance.ol_tag), (mistborn.id, 2.0, SeriesProvenance.override)}
    assert c.override == [{"set_series": {"work": "OL3W", "series": "ol:mistborn", "position": 2.0}}]
    assert c.snapshot == {"member_series": str(mistborn.id),
                          "prior": {"series_id": str(mistborn.id), "work_id": str(book.id), "position": 3.0,
                                    "provenance": "ol_tag", "confidence": "medium"}}


async def test_set_position_creates_a_membership_in_a_runtime_series(db_session):
    lib = await make_user(db_session, librarian=True)
    runtime = await make_series(db_session, "Dune Saga")
    book = await make_work(db_session, "Dune Messiah", series=runtime, ol_id="OL9W")
    c = await set_position(db_session, lib, runtime, book, 2, reason="second")
    assert await members_of(db_session, book) == {(runtime.id, 2.0, SeriesProvenance.override)}
    assert c.override == [{"set_series": {"work": "OL9W", "series": "ol:dune saga", "position": 2,
                                          "name": "Dune Saga"}}]
    assert c.snapshot["prior"] is None


async def test_set_position_refuses_a_non_member_and_a_singleton(db_session):
    lib = await make_user(db_session, librarian=True)
    a = await make_series(db_session, "Alpha", release=R)
    outsider = await make_work(db_session, "Outsider", ol_id="OL4W")
    with pytest.raises(Invalid, match="not in"):
        await set_position(db_session, lib, a, outsider, 1, reason="r")
    with pytest.raises(Invalid, match="single book"):
        await set_position(db_session, lib, await db_session.get(Series, outsider.series_id), outsider, 1, reason="r")


async def test_rename_keeps_the_slug_and_exports_only_release_series(db_session):
    lib = await make_user(db_session, librarian=True)
    saga = await make_series(db_session, "Song of Ice", release=R, key="wd:Q45875")
    slug = saga.slug
    c = await rename_series(db_session, lib, saga, "  A Song of Ice and Fire ", reason="full title")
    assert (saga.name, saga.slug) == ("A Song of Ice and Fire", slug)
    assert c.override == [{"rename_series": {"series": "wd:Q45875", "name": "A Song of Ice and Fire"}}]
    assert c.snapshot == {"old_name": "Song of Ice"} and c.work_id is None

    runtime = await make_series(db_session, "Dune Saga")
    c2 = await rename_series(db_session, lib, runtime, "Dune Chronicles", reason="usual name")
    assert c2.override is None and c2.runtime_only_reason == "Dune Saga is not in a catalog release"
    with pytest.raises(Invalid):
        await rename_series(db_session, lib, runtime, " ", reason="r")
    with pytest.raises(Invalid, match="already"):
        await rename_series(db_session, lib, runtime, "Dune Chronicles", reason="r")
```

Note the `runtime_only_reason` for the runtime rename: `release_series_key` raises with the series' name at the time the override is built. Build the override *before* assigning the new name (see Step 3) so the message names the series as the librarian knew it.

- [ ] **Step 2: Run to verify failure**

Run: `PYTEST tests/test_librarian_placement.py -q`
Expected: `ModuleNotFoundError: No module named 'app.services.librarian.placement'`.

- [ ] **Step 3: Implement**

`backend/app/services/librarian/placement.py`:

```python
"""Where a book lives: move, reorder, rename (spec §5.2). Remove and dissolve are in Task 5."""

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    CatalogCorrection, CorrectionOp, MembershipConfidence, Series, SeriesKind, SeriesMember, SeriesProvenance,
    SeriesSource, Thread, User, Work,
)
from app.services.catalog_loader import retire_series
from app.services.librarian.errors import Conflict, Invalid
from app.services.librarian.keys import exported, release_series_key, series_key_of, work_key
from app.services.librarian.record import clean_reason, ids, live_series, live_work, member_state, record
from app.services.series import canonical_series, placed_memberships, tree_memberships, unique_slug
from app.services.series_identity import new_series_key, release_series_id, series_key


def _override_member(series_id, work_id, position) -> SeriesMember:
    return SeriesMember(series_id=series_id, work_id=work_id, position=position,
                        provenance=SeriesProvenance.override, confidence=MembershipConfidence.high)


async def _move_tagged_threads(db: AsyncSession, work_id, from_room, to_room) -> list[str]:
    """Threads tagged with the book follow it; untagged ones belong to the room."""
    moved = (await db.execute(select(Thread.id).where(
        Thread.work_id == work_id, Thread.series_id == from_room).order_by(Thread.id))).scalars().all()
    if moved:
        await db.execute(update(Thread).where(Thread.id.in_(moved)).values(series_id=to_room))
    return ids(moved)


async def _live_count(db: AsyncSession, room_id) -> int:
    return await db.scalar(select(func.count()).select_from(Work).where(
        Work.series_id == room_id, Work.merged_into_id.is_(None))) or 0


async def _target_for_name(db: AsyncSession, name: str | None) -> tuple[Series, bool]:
    """The series a librarian named: an existing one with that key, or a new one
    under the id the next release will give it."""
    name = (name or "").strip()
    if not name:
        raise Invalid("A new series needs a name.")
    key = new_series_key(name)
    found = await db.get(Series, release_series_id(key))
    if found is None:
        found = (await db.execute(select(Series).where(
            Series.external_id == key, Series.kind == SeriesKind.series))).scalars().first()
    if found is not None:
        return await canonical_series(db, found), False
    series = Series(
        id=release_series_id(key), source=SeriesSource.heuristic, external_id=key, name=name,
        slug=await unique_slug(db, name), canonical_key=series_key(name), kind=SeriesKind.series,
        provenance=SeriesProvenance.override,
    )
    db.add(series)
    await db.flush()
    return series, True


async def _ids_where(db: AsyncSession, column, *conditions) -> list[str]:
    return ids((await db.execute(select(column).where(*conditions).order_by(column))).scalars().all())


async def _retire_if_empty(db: AsyncSession, room: Series, target: Series, work: Work) -> dict | None:
    """A room the move emptied follows its book, as the catalog loader does."""
    if await _live_count(db, room.id):
        return None
    singleton = room.kind is SeriesKind.singleton
    state = {
        "room": str(room.id),
        "parent": str(room.parent_series_id) if room.parent_series_id else None,
        "threads": await _ids_where(db, Thread.id, Thread.series_id == room.id),
        "tagged": (await _ids_where(db, Thread.id, Thread.series_id == room.id, Thread.work_id.is_(None))
                   if singleton else []),
        "works": await _ids_where(db, Work.id, Work.series_id == room.id),
        "repointed": await _ids_where(db, Series.id, Series.merged_into_id == room.id),
    }
    await retire_series(db, room.id, target.id, work.id if singleton else None)
    await db.refresh(room)
    return state


async def set_series(db: AsyncSession, user: User, work: Work, *, reason: str, series: Series | None = None,
                     new_series_name: str | None = None, position: float | None = None) -> CatalogCorrection:
    reason = clean_reason(reason)
    work = live_work(work)
    if (series is None) == (new_series_name is None):
        raise Invalid("Pick a series, or name a new one, not both.")
    old_room = await db.get(Series, work.series_id)
    if series is not None:
        target, created = await canonical_series(db, live_series(series)), False
    else:
        target, created = await _target_for_name(db, new_series_name)
    if target.kind is SeriesKind.singleton:
        raise Invalid("A single book's page is not a series; pick a series or name a new one.")
    if target.parent_series_id is not None:
        raise Invalid(f"{target.name} is a sub-series; move the book to the series it belongs to.")
    if target.dissolved_at is not None:
        raise Conflict(f"{target.name} was dissolved.")
    if target.id == old_room.id:
        raise Invalid(f"{work.title} is already in {target.name}.")

    old_members = await tree_memberships(db, old_room, work.id)
    old_series = [await db.get(Series, m.series_id) for m in old_members]
    prior = await db.get(SeriesMember, (target.id, work.id))
    snapshot = {
        "old_room": str(old_room.id),
        "old_members": [member_state(m) for m in old_members],
        "prior_target_member": member_state(prior) if prior is not None else None,
        "created_series": str(target.id) if created else None,
    }
    for m in [*old_members, *([prior] if prior is not None else [])]:
        await db.delete(m)
    await db.flush()
    db.add(_override_member(target.id, work.id, position))
    snapshot["moved_threads"] = await _move_tagged_threads(db, work.id, old_room.id, target.id)
    work.series_id = target.id
    await db.flush()
    snapshot["retired"] = await _retire_if_empty(db, old_room, target, work)

    def build():
        wk = work_key(work)
        removes = [{"remove_from_series": {"work": wk, "series": release_series_key(s)}}
                   for s in sorted(old_series, key=lambda s: s.external_id) if s.catalog_release is not None]
        entry = {"work": wk, "series": series_key_of(target)}
        if position is not None:
            entry["position"] = position
        if target.catalog_release is None:
            entry["name"] = target.name  # lets the pipeline create it
        return [*removes, {"set_series": entry}]

    entries, missing = exported(build)
    return await record(
        db, op=CorrectionOp.set_series, user=user, reason=reason,
        payload={"work": str(work.id), "series": str(target.id), "position": position,
                 "new_series_name": new_series_name},
        entries=entries, runtime_only_reason=missing, snapshot=snapshot, work=work, series=target,
    )


async def set_position(db: AsyncSession, user: User, room: Series, work: Work, position: float | None, *,
                       reason: str) -> CatalogCorrection:
    reason = clean_reason(reason)
    room, work = live_series(room), live_work(work)
    if room.kind is SeriesKind.singleton:
        raise Invalid("A single book has no place in a series to set.")
    if work.series_id != room.id:
        raise Invalid(f"{work.title} is not in {room.name}.")
    placed, _ = await placed_memberships(db, room, [work.id])
    member = placed.get(work.id)
    prior = member_state(member) if member is not None else None
    if member is None:
        member = _override_member(room.id, work.id, position)
        db.add(member)
    else:
        member.position = position
        member.provenance, member.confidence = SeriesProvenance.override, MembershipConfidence.high
    await db.flush()
    member_series = await db.get(Series, member.series_id)

    def build():
        entry = {"work": work_key(work), "series": series_key_of(member_series), "position": position}
        if member_series.catalog_release is None:
            entry["name"] = member_series.name
        return [{"set_series": entry}]

    entries, missing = exported(build)
    return await record(
        db, op=CorrectionOp.set_position, user=user, reason=reason,
        payload={"work": str(work.id), "series": str(room.id), "member_series": str(member.series_id),
                 "position": position},
        entries=entries, runtime_only_reason=missing,
        snapshot={"member_series": str(member.series_id), "prior": prior}, work=work, series=room,
    )


async def rename_series(db: AsyncSession, user: User, series: Series, name: str, *,
                        reason: str) -> CatalogCorrection:
    reason = clean_reason(reason)
    series = live_series(series)
    if series.kind is SeriesKind.singleton:
        raise Invalid("A single book's page takes its book's title; it cannot be renamed.")
    if series.dissolved_at is not None:
        raise Conflict(f"{series.name} was dissolved.")
    name = (name or "").strip()
    if not name:
        raise Invalid("A series needs a name.")
    if name == series.name:
        raise Invalid(f"It is already called {name}.")
    # Built before the rename, so a runtime-only reason names the series as it was.
    entries, missing = exported(lambda: [{"rename_series": {"series": release_series_key(series), "name": name}}])
    old = series.name
    series.name = name  # the slug never changes: shared links keep working
    await db.flush()
    return await record(
        db, op=CorrectionOp.rename_series, user=user, reason=reason,
        payload={"series": str(series.id), "name": name}, entries=entries, runtime_only_reason=missing,
        snapshot={"old_name": old}, series=series,
    )
```

`backend/app/services/librarian/__init__.py`, append:

```python
from app.services.librarian.placement import rename_series, set_position, set_series  # noqa: E402,F401
```

- [ ] **Step 4: Run the tests**

Run: `PYTEST tests/test_librarian_placement.py -q`
Expected: all pass. If `test_set_position_edits_the_membership_the_page_shows` fails on `7.0`, check that `placed_memberships` picked the deeper (Mistborn) row. The cosmere row must be untouched.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/librarian backend/tests/test_librarian_placement.py
git commit -m "feat(librarian): move, reorder and rename, each logged with its override"
```

---
### Task 5: Remove from a series, and dissolve a series

**Files:**
- Modify: `backend/app/services/librarian/placement.py`, `backend/app/services/librarian/__init__.py`
- Test: `backend/tests/test_librarian_placement.py` (append)

**Interfaces:**
- Consumes: Task 4 `_move_tagged_threads`; `series.singleton_series_for(work) -> Series`.
- Produces: `async remove_from_series(db, user, room, work, *, reason)`, `async reject_series(db, user, series, *, reason)`, and `async _detach(db, room, work) -> dict`.
- Snapshot shapes Task 7 relies on:
  - `remove_from_series` snapshot = one detach state: `{"work", "members": [member_state], "threads": [id], "singleton": id, "revived": bool}`
  - `reject_series` snapshot = `{"members": [detach state, ...]}`

- [ ] **Step 1: Failing tests**

Append to `backend/tests/test_librarian_placement.py`:

```python
from app.services.librarian.placement import reject_series, remove_from_series


async def test_remove_gives_the_book_its_own_page_with_its_threads(db_session):
    lib = await make_user(db_session, librarian=True)
    a = await make_series(db_session, "Alpha", release=R)
    x = await make_work(db_session, "Book X", series=a, ol_id="OL1W")
    y = await make_work(db_session, "Book Y", series=a, ol_id="OL2W")
    await make_member(db_session, a, x, 1.0)
    await make_member(db_session, a, y, 2.0)
    tagged = await make_thread(db_session, lib, a, x)
    untagged = await make_thread(db_session, lib, a)

    c = await remove_from_series(db_session, lib, a, x, reason="not part of Alpha")

    own = await db_session.get(Series, await fresh(db_session, Work.series_id, x.id))
    assert own.kind is SeriesKind.singleton and own.external_id == f"singleton:{x.id}"
    assert await fresh(db_session, Thread.series_id, tagged.id) == own.id
    assert await fresh(db_session, Thread.series_id, untagged.id) == a.id
    assert await members_of(db_session, x) == set()
    assert c.override == [{"remove_from_series": {"work": "OL1W", "series": "ol:alpha"}}]
    assert c.snapshot["singleton"] == str(own.id) and c.snapshot["revived"] is False
    assert c.snapshot["threads"] == [str(tagged.id)]


async def test_remove_revives_the_books_old_singleton(db_session):
    lib = await make_user(db_session, librarian=True)
    x = await make_work(db_session, "Book X", ol_id="OL1W")
    old_single = x.series_id
    a = await make_series(db_session, "Alpha", release=R)
    await make_work(db_session, "Book Y", series=a, ol_id="OL2W")
    await set_series(db_session, lib, x, series=a, reason="joins Alpha")  # retires the singleton
    assert await fresh(db_session, Series.merged_into_id, old_single) == a.id

    c = await remove_from_series(db_session, lib, a, x, reason="it did not")

    assert await fresh(db_session, Work.series_id, x.id) == old_single
    assert await fresh(db_session, Series.merged_into_id, old_single) is None
    assert c.snapshot["revived"] is True


async def test_remove_from_a_runtime_series_is_runtime_only(db_session):
    lib = await make_user(db_session, librarian=True)
    runtime = await make_series(db_session, "Dune Saga")
    x = await make_work(db_session, "Dune", series=runtime, ol_id="OL8W")
    await make_work(db_session, "Dune Messiah", series=runtime, ol_id="OL9W")
    c = await remove_from_series(db_session, lib, runtime, x, reason="r")
    assert c.override is None and c.runtime_only_reason == "Dune Saga is not in a catalog release"


async def test_remove_refuses_a_singleton_and_a_non_member(db_session):
    lib = await make_user(db_session, librarian=True)
    a = await make_series(db_session, "Alpha", release=R)
    outsider = await make_work(db_session, "Outsider", ol_id="OL4W")
    with pytest.raises(Invalid, match="not in"):
        await remove_from_series(db_session, lib, a, outsider, reason="r")
    single = await db_session.get(Series, outsider.series_id)
    with pytest.raises(Invalid, match="single book"):
        await remove_from_series(db_session, lib, single, outsider, reason="r")


async def test_reject_dissolves_and_every_member_gets_its_own_page(db_session):
    lib = await make_user(db_session, librarian=True)
    imprint = await make_series(db_session, "Penguin Classics", release=R)
    books = [await make_work(db_session, f"Classic {i}", series=imprint, ol_id=f"OL{i}0W") for i in range(3)]
    for i, b in enumerate(books):
        await make_member(db_session, imprint, b, float(i))
    tagged = await make_thread(db_session, lib, imprint, books[0])
    general = await make_thread(db_session, lib, imprint)

    c = await reject_series(db_session, lib, imprint, reason="an imprint, not a series")

    assert imprint.dissolved_at is not None and imprint.slug
    for b in books:
        room = await db_session.get(Series, await fresh(db_session, Work.series_id, b.id))
        assert room.kind is SeriesKind.singleton
    assert await fresh(db_session, Thread.series_id, general.id) == imprint.id
    assert await fresh(db_session, Thread.series_id, tagged.id) != imprint.id
    assert c.override == [{"reject_series": "ol:penguin classics"}]
    assert len(c.snapshot["members"]) == 3 and c.work_id is None and c.series_id == imprint.id
    with pytest.raises(Conflict, match="already dissolved"):
        await reject_series(db_session, lib, imprint, reason="again")
```

- [ ] **Step 2: Run to verify failure**

Run: `PYTEST tests/test_librarian_placement.py -q`
Expected: ImportError for `reject_series`.

- [ ] **Step 3: Implement**

In `backend/app/services/librarian/placement.py`, add `from datetime import datetime, timezone`, add `MissingKey` to the keys import, add `singleton_series_for` to the series import, and append:

```python
async def _singleton_for(db: AsyncSession, work: Work) -> tuple[Series, bool]:
    """The book's own page: its old singleton brought back if it has one
    (external_id is unique per source), otherwise a new one."""
    old = (await db.execute(select(Series).where(
        Series.source == SeriesSource.heuristic, Series.external_id == f"singleton:{work.id}"
    ))).scalar_one_or_none()
    if old is not None:
        old.merged_into_id, old.dissolved_at, old.name = None, None, work.title
        await db.flush()
        return old, True
    single = singleton_series_for(work)
    db.add(single)
    await db.flush()
    return single, False


async def _detach(db: AsyncSession, room: Series, work: Work) -> dict:
    """Take ``work`` out of ``room`` onto its own page, with the threads about it."""
    members = await tree_memberships(db, room, work.id)
    state = {"work": str(work.id), "members": [member_state(m) for m in members]}
    for m in members:
        await db.delete(m)
    single, revived = await _singleton_for(db, work)
    state["threads"] = await _move_tagged_threads(db, work.id, room.id, single.id)
    state["singleton"], state["revived"] = str(single.id), revived
    work.series_id = single.id
    await db.flush()
    return state


async def remove_from_series(db: AsyncSession, user: User, room: Series, work: Work, *,
                             reason: str) -> CatalogCorrection:
    reason = clean_reason(reason)
    room, work = live_series(room), live_work(work)
    if room.kind is SeriesKind.singleton:
        raise Invalid("A single book's page cannot lose its book.")
    if room.dissolved_at is not None:
        raise Conflict(f"{room.name} was dissolved.")
    if work.series_id != room.id:
        raise Invalid(f"{work.title} is not in {room.name}.")
    member_series = [await db.get(Series, m.series_id) for m in await tree_memberships(db, room, work.id)]

    def build():
        wk = work_key(work)
        release_series_key(room)  # a room the build does not hold cannot be named
        entries = [{"remove_from_series": {"work": wk, "series": release_series_key(s)}}
                   for s in sorted(member_series, key=lambda s: s.external_id) if s.catalog_release is not None]
        if not entries:
            raise MissingKey(f"{work.title} has no catalog membership in {room.name}")
        return entries

    entries, missing = exported(build)
    state = await _detach(db, room, work)
    return await record(
        db, op=CorrectionOp.remove_from_series, user=user, reason=reason,
        payload={"work": str(work.id), "series": str(room.id)}, entries=entries,
        runtime_only_reason=missing, snapshot=state, work=work, series=room,
    )


async def reject_series(db: AsyncSession, user: User, series: Series, *, reason: str) -> CatalogCorrection:
    """Dissolve: every book goes to its own page; the room keeps its slug and its
    untagged threads, shows no books and takes no new threads."""
    reason = clean_reason(reason)
    series = live_series(series)
    if series.kind is SeriesKind.singleton:
        raise Invalid("A single book's page cannot be dissolved.")
    if series.dissolved_at is not None:
        raise Conflict(f"{series.name} was already dissolved.")
    entries, missing = exported(lambda: [{"reject_series": release_series_key(series)}])
    works = (await db.execute(select(Work).where(
        Work.series_id == series.id, Work.merged_into_id.is_(None)).order_by(Work.id))).scalars().all()
    detached = [await _detach(db, series, w) for w in works]
    series.dissolved_at = datetime.now(timezone.utc)
    await db.flush()
    return await record(
        db, op=CorrectionOp.reject_series, user=user, reason=reason, payload={"series": str(series.id)},
        entries=entries, runtime_only_reason=missing, snapshot={"members": detached}, series=series,
    )
```

Update the `__init__.py` re-export line to include `reject_series, remove_from_series`.

- [ ] **Step 4: Run the tests**

Run: `PYTEST tests/test_librarian_placement.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/librarian backend/tests/test_librarian_placement.py
git commit -m "feat(librarian): remove a book from a series, and dissolve a series"
```

---
### Task 6: Merge and split, with confirmation counts

**Files:**
- Create: `backend/app/services/librarian/identity.py`, `backend/tests/test_librarian_identity.py`
- Modify: `backend/app/services/librarian/__init__.py`

**Interfaces:**
- Consumes: `works.merge_works(db, source, target) -> Work`; `works._refresh_work(db, work)` (private, already imported by `enrichment.py` and two scripts: same precedent); `works.edition_rank`; `work_identity.display_title`, `canonical_key`, `heuristic_external_id`; Task 3 keys/record/errors.
- Produces:
  - `async merge(db, user, source, target, *, reason, confirm=False) -> CatalogCorrection`: without `confirm` it raises `NeedsConfirmation(message, {"threads", "shelves", "editions"})`. The correction's `work_id` is the *target*, and `payload` is `{"source", "target", "consequences"}`.
  - `async split(db, user, work, edition_ids, *, reason, confirm=False) -> CatalogCorrection`: without `confirm` it raises `NeedsConfirmation(message, {"editions", "remaining"})`. `work_id` is the original, and `payload` is `{"work", "new_work", "editions"}`.
  - Both record `snapshot=None`.

- [ ] **Step 1: Failing tests**

`backend/tests/test_librarian_identity.py`:

```python
import uuid

import pytest
from sqlalchemy import func, select

from app.models import Book, CorrectionOp, Series, SeriesKind, SeriesMember, Shelf, ShelfStatus, Thread, Work
from app.models import WorkProvenance, WorkSource
from app.services.librarian.errors import Conflict, Invalid, NeedsConfirmation, NotFound
from app.services.librarian.identity import merge, split
from tests.librarian_factories import (
    fresh, make_edition, make_member, make_series, make_thread, make_user, make_work,
)

R = "2026.10.1"


async def test_merge_asks_first_with_real_counts(db_session):
    lib = await make_user(db_session, librarian=True)
    source = await make_work(db_session, "Dune", ol_id="OL2W", author="Brian Herbert")
    target = await make_work(db_session, "Dune", ol_id="OL1W", author="Frank Herbert")
    await make_edition(db_session, source, ol_id="OL5M")
    await make_edition(db_session, source)
    await make_thread(db_session, lib, await db_session.get(Series, source.series_id))  # untagged, singleton
    await make_thread(db_session, lib, await db_session.get(Series, source.series_id), source)
    db_session.add(Shelf(user_id=lib.id, work_id=source.id, status=ShelfStatus.read))
    await db_session.flush()

    with pytest.raises(NeedsConfirmation) as asked:
        await merge(db_session, lib, source, target, reason="same book")
    assert asked.value.consequences == {"threads": 2, "shelves": 1, "editions": 2}
    assert await fresh(db_session, Work.merged_into_id, source.id) is None  # nothing happened

    c = await merge(db_session, lib, source, target, reason="same book", confirm=True)
    assert await fresh(db_session, Work.merged_into_id, source.id) == target.id
    assert c.op is CorrectionOp.merge_works and c.work_id == target.id and c.snapshot is None
    assert c.override == [{"merge_works": ["OL1W", "OL2W"]}]
    assert c.payload["consequences"] == {"threads": 2, "shelves": 1, "editions": 2}


async def test_merge_refusals(db_session):
    lib = await make_user(db_session, librarian=True)
    a = await make_work(db_session, "A", ol_id="OL1W")
    b = await make_work(db_session, "B", ol_id="OL2W")
    c = await make_work(db_session, "C", ol_id="OL3W")
    with pytest.raises(Invalid, match="itself"):
        await merge(db_session, lib, a, a, reason="r", confirm=True)
    await merge(db_session, lib, a, b, reason="r", confirm=True)
    with pytest.raises(Conflict, match="merged"):
        await merge(db_session, lib, a, c, reason="r", confirm=True)
    with pytest.raises(Conflict, match="merged"):
        await merge(db_session, lib, c, a, reason="r", confirm=True)


async def test_merge_of_a_heuristic_work_is_runtime_only(db_session):
    lib = await make_user(db_session, librarian=True)
    heuristic = await make_work(db_session, "Obscure")
    target = await make_work(db_session, "Obscure (OL)", ol_id="OL1W")
    c = await merge(db_session, lib, heuristic, target, reason="r", confirm=True)
    assert c.override is None and "no Open Library id" in c.runtime_only_reason


async def test_split_makes_an_open_library_work_named_by_the_pipeline(db_session):
    lib = await make_user(db_session, librarian=True)
    saga = await make_series(db_session, "Dune", release=R)
    work = await make_work(db_session, "Dune", series=saga, ol_id="OL100W", author="Frank Herbert")
    await make_member(db_session, saga, work, 1.0)
    keep = await make_edition(db_session, work, ol_id="OL1M", title="Dune")
    split_a = await make_edition(db_session, work, ol_id="OL7M", title="Dune: House Atreides")
    split_b = await make_edition(db_session, work, ol_id="OL3M", title="Dune: House Atreides (Deluxe Edition)")
    thread = await make_thread(db_session, lib, saga, work)

    with pytest.raises(NeedsConfirmation) as asked:
        await split(db_session, lib, work, [split_a.id, split_b.id], reason="prequel")
    assert asked.value.consequences == {"editions": 2, "remaining": 1}

    c = await split(db_session, lib, work, [split_a.id, split_b.id], reason="prequel", confirm=True)
    new = await db_session.get(Work, uuid.UUID(c.payload["new_work"]))
    assert (new.source, new.external_id) == (WorkSource.openlibrary, "OL100W~OL3M")
    assert new.identity_provenance is WorkProvenance.override
    assert new.series_id == saga.id and new.author == "Frank Herbert"
    assert await db_session.get(SeriesMember, (saga.id, new.id)) is not None
    assert {await fresh(db_session, Book.work_id, e.id) for e in (split_a, split_b)} == {new.id}
    assert await fresh(db_session, Book.work_id, keep.id) == work.id
    assert await fresh(db_session, Thread.work_id, thread.id) == work.id  # discussion stays
    assert await fresh(db_session, Work.representative_book_id, work.id) == keep.id
    assert await fresh(db_session, Work.representative_book_id, new.id) in {split_a.id, split_b.id}
    assert c.override == [{"split_work": {"work": "OL100W", "editions": ["OL3M", "OL7M"]}}]
    assert c.snapshot is None


async def test_splitting_out_of_a_singleton_gives_the_new_work_its_own_page(db_session):
    lib = await make_user(db_session, librarian=True)
    work = await make_work(db_session, "Collected Stories", ol_id="OL5W")
    await make_edition(db_session, work, ol_id="OL1M")
    other = await make_edition(db_session, work, ol_id="OL2M", title="Selected Stories")
    c = await split(db_session, lib, work, [other.id], reason="different book", confirm=True)
    new = await db_session.get(Work, uuid.UUID(c.payload["new_work"]))
    room = await db_session.get(Series, new.series_id)
    assert room.kind is SeriesKind.singleton and room.id != work.series_id
    assert (await db_session.execute(select(func.count()).select_from(SeriesMember)
                                     .where(SeriesMember.work_id == new.id))).scalar() == 0


async def test_split_refusals(db_session):
    lib = await make_user(db_session, librarian=True)
    work = await make_work(db_session, "Dune", ol_id="OL100W")
    only = await make_edition(db_session, work, ol_id="OL1M")
    stranger = await make_edition(db_session, await make_work(db_session, "Other", ol_id="OL200W"), ol_id="OL9M")
    with pytest.raises(Invalid, match="at least one"):
        await split(db_session, lib, work, [], reason="r", confirm=True)
    with pytest.raises(Invalid, match="every edition"):
        await split(db_session, lib, work, [only.id], reason="r", confirm=True)
    with pytest.raises(Invalid, match="not an edition"):
        await split(db_session, lib, work, [stranger.id], reason="r", confirm=True)
    with pytest.raises(NotFound):
        await split(db_session, lib, work, [uuid.uuid4()], reason="r", confirm=True)


async def test_a_heuristic_split_is_runtime_only_and_refuses_a_twin_key(db_session):
    lib = await make_user(db_session, librarian=True)
    work = await make_work(db_session, "Dune", ol_id="OL100W", author="Frank Herbert")
    await make_edition(db_session, work, ol_id="OL1M")
    google = await make_edition(db_session, work, title="Dune Messiah")
    c = await split(db_session, lib, work, [google.id], reason="sequel", confirm=True)
    assert c.override is None and "Google Books volume" in c.runtime_only_reason
    new = await db_session.get(Work, uuid.UUID(c.payload["new_work"]))
    assert new.source is WorkSource.heuristic and new.title == "Dune Messiah"

    twin = await make_edition(db_session, work, title="Dune (Deluxe Edition)")
    with pytest.raises(Invalid, match="merged straight back"):
        await split(db_session, lib, work, [twin.id], reason="r", confirm=True)
```

- [ ] **Step 2: Run to verify failure**

Run: `PYTEST tests/test_librarian_identity.py -q`
Expected: `ModuleNotFoundError: No module named 'app.services.librarian.identity'`.

- [ ] **Step 3: Implement**

`backend/app/services/librarian/identity.py`:

```python
"""Which book is which: merge and split (spec §5.2). Neither can be undone."""

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Book, CatalogCorrection, CorrectionOp, Series, SeriesKind, Shelf, Thread, User, Work, WorkProvenance, WorkSource,
)
from app.services.librarian.errors import Conflict, Invalid, NeedsConfirmation, NotFound
from app.services.librarian.keys import edition_key, exported, work_key
from app.services.librarian.placement import _override_member
from app.services.librarian.record import clean_reason, ids, live_work, record
from app.services.work_identity import canonical_key, display_title, heuristic_external_id
from app.services.works import _refresh_work, edition_rank, identity_keys, merge_works


async def _count(db: AsyncSession, model, *conditions) -> int:
    return await db.scalar(select(func.count()).select_from(model).where(*conditions)) or 0


async def merge(db: AsyncSession, user: User, source: Work, target: Work, *, reason: str,
                confirm: bool = False) -> CatalogCorrection:
    reason = clean_reason(reason)
    if source is not None and target is not None and source.id == target.id:
        raise Invalid("A book cannot merge into itself.")
    source, target = live_work(source), live_work(target)
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
    await merge_works(db, source, target)
    return await record(
        db, op=CorrectionOp.merge_works, user=user, reason=reason,
        payload={"source": str(source.id), "target": str(target.id), "consequences": consequences},
        entries=entries, runtime_only_reason=missing, work=target,
        series=await db.get(Series, target.series_id),
    )


async def split(db: AsyncSession, user: User, work: Work, edition_ids: list[UUID], *, reason: str,
                confirm: bool = False) -> CatalogCorrection:
    reason = clean_reason(reason)
    work = live_work(work)
    wanted = list(dict.fromkeys(edition_ids))
    if not wanted:
        raise Invalid("Pick at least one edition to split off.")
    editions = (await db.execute(select(Book).where(Book.id.in_(wanted)))).scalars().all()
    if len(editions) != len(wanted):
        raise NotFound("Unknown edition.")
    if any(e.work_id != work.id for e in editions):
        raise Invalid(f"That is not an edition of {work.title}.")
    total = await _count(db, Book, Book.work_id == work.id)
    if len(editions) == total:
        raise Invalid("Splitting off every edition leaves nothing behind; merge or move the book instead.")
    consequences = {"editions": len(editions), "remaining": total - len(editions)}
    if not confirm:
        raise NeedsConfirmation(f"Splitting {len(editions)} editions off {work.title} cannot be undone.",
                                consequences)

    title = display_title(max(editions, key=edition_rank).title) or work.title
    key = canonical_key(title, work.author)
    entries, missing = exported(lambda: [{"split_work": {
        "work": work_key(work), "editions": sorted(edition_key(e) for e in editions)}}])
    if entries is not None:
        # The pipeline's SplitWork.new_work, so the next release adopts this row.
        source, external_id = WorkSource.openlibrary, f"{work.external_id}~{min(edition_key(e) for e in editions)}"
        provenance = WorkProvenance.override
    else:
        if key in identity_keys(work):
            raise Invalid(f"The split-off editions are titled like {work.title} itself, so a runtime split "
                          "would be merged straight back; split Open Library editions instead.")
        source, external_id, provenance = WorkSource.heuristic, heuristic_external_id(key), WorkProvenance.heuristic
    if await _count(db, Work, Work.source == source, Work.external_id == external_id):
        raise Conflict("Those editions were already split off into their own book.")

    room = await db.get(Series, work.series_id)
    new = Work(
        source=source, external_id=external_id, canonical_key=key, title=title, author=work.author,
        kind=work.kind, identity_provenance=provenance, genre_id=work.genre_id,
        # A singleton is one book's page: the new book gets its own (flush listener).
        series_id=room.id if room.kind is SeriesKind.series else None,
    )
    db.add(new)
    await db.flush()
    if room.kind is SeriesKind.series:
        db.add(_override_member(room.id, new.id, None))
    for e in editions:
        e.work_id = new.id
    await db.flush()
    await _refresh_work(db, work)
    await _refresh_work(db, new)
    await db.flush()
    return await record(
        db, op=CorrectionOp.split_work, user=user, reason=reason,
        payload={"work": str(work.id), "new_work": str(new.id), "editions": ids(sorted(e.id for e in editions))},
        entries=entries, runtime_only_reason=missing, work=work, series=room,
    )
```

Append to `__init__.py`: `from app.services.librarian.identity import merge, split  # noqa: E402,F401`.

- [ ] **Step 4: Run the tests**

Run: `PYTEST tests/test_librarian_identity.py tests/test_works.py tests/test_work_resolution.py -q`
Expected: all pass. The existing `merge_works` tests are untouched.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/librarian backend/tests/test_librarian_identity.py
git commit -m "feat(librarian): merge and split books, confirmed from real counts"
```

---
### Task 7: Undo

**Files:**
- Create: `backend/app/services/librarian/undo.py`, `backend/tests/test_librarian_undo.py`
- Modify: `backend/app/services/librarian/__init__.py`

**Interfaces:**
- Consumes: the snapshot shapes from Tasks 4 and 5; `record.latest_for_subject`, `record.restore_member`, `record.uuids`; `placement._live_count`.
- Produces: `UNDOABLE: frozenset[CorrectionOp]`; `async revert(db, user, correction) -> CatalogCorrection`, which sets `reverted_at` / `reverted_by_id`, writes no new correction, and raises `Invalid` for merge/split and `Conflict` for already-reverted, not-latest or stale state.

- [ ] **Step 1: Failing tests**

`backend/tests/test_librarian_undo.py`:

```python
import uuid

import pytest
from sqlalchemy import update

from app.models import Series, SeriesMember, SeriesProvenance, Thread, Work
from app.services.librarian.errors import Conflict, Invalid
from app.services.librarian.identity import merge
from app.services.librarian.placement import (
    reject_series, remove_from_series, rename_series, set_position, set_series,
)
from app.services.librarian.undo import revert
from tests.librarian_factories import fresh, make_member, make_series, make_thread, make_user, make_work

R = "2026.10.1"


async def members_of(db, work):
    return {(m.series_id, m.position, m.provenance) for m in
            (await db.execute(SeriesMember.__table__.select().where(SeriesMember.work_id == work.id))).all()}


async def two_room_saga(db):
    lib = await make_user(db, librarian=True)
    a = await make_series(db, "Alpha", release=R)
    b = await make_series(db, "Beta", release=R)
    x = await make_work(db, "Book X", series=a, ol_id="OL1W")
    y = await make_work(db, "Book Y", series=a, ol_id="OL2W")
    await make_member(db, a, x, 1.0)
    await make_member(db, a, y, 2.0)
    return lib, a, b, x, y


async def test_undo_move_restores_room_membership_and_threads(db_session):
    lib, a, b, x, _ = await two_room_saga(db_session)
    tagged = await make_thread(db_session, lib, a, x)
    c = await set_series(db_session, lib, x, series=b, position=4, reason="r")

    undone = await revert(db_session, lib, c)

    assert undone.reverted_at is not None and undone.reverted_by_id == lib.id
    assert await fresh(db_session, Work.series_id, x.id) == a.id
    assert await fresh(db_session, Thread.series_id, tagged.id) == a.id
    assert await members_of(db_session, x) == {(a.id, 1.0, SeriesProvenance.ol_tag)}


async def test_undo_move_revives_a_retired_singleton(db_session):
    lib = await make_user(db_session, librarian=True)
    x = await make_work(db_session, "The Fifth Season")
    single = await db_session.get(Series, x.series_id)
    about_it = await make_thread(db_session, lib, single)
    c = await set_series(db_session, lib, x, new_series_name="The Broken Earth", reason="r")
    created = c.series_id

    await revert(db_session, lib, c)

    assert await fresh(db_session, Work.series_id, x.id) == single.id
    assert await fresh(db_session, Series.merged_into_id, single.id) is None
    assert await fresh(db_session, Thread.series_id, about_it.id) == single.id
    assert await fresh(db_session, Thread.work_id, about_it.id) is None  # untagged again
    assert await fresh(db_session, Series.merged_into_id, created) == single.id  # link still resolves


async def test_undo_refuses_stale_state(db_session):
    lib, a, b, x, _ = await two_room_saga(db_session)
    tagged = await make_thread(db_session, lib, a, x)
    c = await set_series(db_session, lib, x, series=b, reason="r")
    other = await make_series(db_session, "Gamma", release=R)
    await db_session.execute(update(Thread).where(Thread.id == tagged.id).values(series_id=other.id))
    with pytest.raises(Conflict, match="changed"):
        await revert(db_session, lib, c)


async def test_only_the_latest_fix_on_a_book_can_be_undone(db_session):
    lib, a, b, x, _ = await two_room_saga(db_session)
    move = await set_series(db_session, lib, x, series=b, reason="r")
    reorder = await set_position(db_session, lib, b, x, 3, reason="r")
    with pytest.raises(Conflict, match="later fix"):
        await revert(db_session, lib, move)
    await revert(db_session, lib, reorder)
    assert await members_of(db_session, x) == {(b.id, None, SeriesProvenance.override)}
    await revert(db_session, lib, move)
    with pytest.raises(Conflict, match="already undone"):
        await revert(db_session, lib, move)


async def test_merge_and_split_cannot_be_undone(db_session):
    lib = await make_user(db_session, librarian=True)
    a = await make_work(db_session, "A", ol_id="OL1W")
    b = await make_work(db_session, "B", ol_id="OL2W")
    c = await merge(db_session, lib, a, b, reason="r", confirm=True)
    with pytest.raises(Invalid, match="cannot be undone"):
        await revert(db_session, lib, c)


async def test_undo_rename_and_its_stale_check(db_session):
    lib = await make_user(db_session, librarian=True)
    saga = await make_series(db_session, "Old Name", release=R)
    c = await rename_series(db_session, lib, saga, "New Name", reason="r")
    await revert(db_session, lib, c)
    assert saga.name == "Old Name"

    c2 = await rename_series(db_session, lib, saga, "Newer", reason="r")
    saga.name = "Edited elsewhere"
    await db_session.flush()
    with pytest.raises(Conflict):
        await revert(db_session, lib, c2)


async def test_undo_remove_round_trip_tombstones_the_singleton(db_session):
    lib, a, _, x, _ = await two_room_saga(db_session)
    tagged = await make_thread(db_session, lib, a, x)
    c = await remove_from_series(db_session, lib, a, x, reason="r")
    single = c.snapshot["singleton"]

    await revert(db_session, lib, c)

    assert await fresh(db_session, Work.series_id, x.id) == a.id
    assert await fresh(db_session, Thread.series_id, tagged.id) == a.id
    assert await members_of(db_session, x) == {(a.id, 1.0, SeriesProvenance.ol_tag)}
    assert await fresh(db_session, Series.merged_into_id, uuid.UUID(single)) == a.id


async def test_undo_remove_refuses_when_the_singleton_gained_a_thread(db_session):
    lib, a, _, x, _ = await two_room_saga(db_session)
    c = await remove_from_series(db_session, lib, a, x, reason="r")
    own = await db_session.get(Series, await fresh(db_session, Work.series_id, x.id))
    await make_thread(db_session, lib, own)  # someone talks about it on its own page
    with pytest.raises(Conflict, match="own page"):
        await revert(db_session, lib, c)
    assert await fresh(db_session, Work.series_id, x.id) == own.id  # nothing moved


async def test_undo_reject_brings_every_book_back(db_session):
    lib, a, _, x, y = await two_room_saga(db_session)
    c = await reject_series(db_session, lib, a, reason="r")
    await revert(db_session, lib, c)
    assert a.dissolved_at is None
    for w, pos in ((x, 1.0), (y, 2.0)):
        assert await fresh(db_session, Work.series_id, w.id) == a.id
        assert await members_of(db_session, w) == {(a.id, pos, SeriesProvenance.ol_tag)}
```

- [ ] **Step 2: Run to verify failure**

Run: `PYTEST tests/test_librarian_undo.py -q`
Expected: `ModuleNotFoundError: No module named 'app.services.librarian.undo'`.

- [ ] **Step 3: Implement**

`backend/app/services/librarian/undo.py`:

```python
"""Undo (spec §6): only the latest unreverted fix on its subject, and only while
the catalog still looks the way that fix left it."""

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import CatalogCorrection, CorrectionOp, Series, SeriesMember, Thread, User, Work
from app.services.librarian.errors import Conflict, Invalid
from app.services.librarian.placement import _live_count
from app.services.librarian.record import latest_for_subject, restore_member, uuids

UNDOABLE = frozenset({CorrectionOp.set_series, CorrectionOp.set_position, CorrectionOp.rename_series,
                      CorrectionOp.remove_from_series, CorrectionOp.reject_series})
_STALE = "The book or series changed since this fix; it can no longer be undone."


async def revert(db: AsyncSession, user: User, correction: CatalogCorrection) -> CatalogCorrection:
    if correction.op not in UNDOABLE:
        raise Invalid("Merges and splits cannot be undone.")
    if correction.reverted_at is not None:
        raise Conflict("This fix was already undone.")
    latest = await latest_for_subject(db, correction)
    if latest is None or latest.id != correction.id:
        raise Conflict("A later fix to the same book or series came after this one; undo that first.")
    await _REVERT[correction.op](db, correction)
    correction.reverted_at = datetime.now(timezone.utc)
    correction.reverted_by_id = user.id
    await db.flush()
    return correction


async def _require_threads_in(db: AsyncSession, thread_ids: list[UUID], room_id: UUID) -> None:
    if not thread_ids:
        return
    rooms = (await db.execute(select(Thread.series_id).where(Thread.id.in_(thread_ids)))).scalars().all()
    if len(rooms) != len(thread_ids) or any(r != room_id for r in rooms):
        raise Conflict(_STALE)


async def _move_threads(db: AsyncSession, thread_ids: list[UUID], **values) -> None:
    if thread_ids:
        await db.execute(update(Thread).where(Thread.id.in_(thread_ids)).values(**values))


async def _undo_set_series(db: AsyncSession, c: CatalogCorrection) -> None:
    s = c.snapshot
    work, target = await db.get(Work, c.work_id), await db.get(Series, c.series_id)
    if work is None or target is None or work.merged_into_id is not None or work.series_id != target.id:
        raise Conflict(_STALE)
    member = await db.get(SeriesMember, (target.id, work.id))
    if member is None:
        raise Conflict(_STALE)
    moved = uuids(s["moved_threads"])
    await _require_threads_in(db, moved, target.id)
    old_room = await db.get(Series, UUID(s["old_room"]))
    if old_room is None:
        raise Conflict(_STALE)
    await db.refresh(old_room)
    retired = s["retired"]
    if retired is not None:
        if old_room.merged_into_id != target.id:
            raise Conflict(_STALE)
        await _require_threads_in(db, uuids(retired["threads"]), target.id)
        old_room.merged_into_id = None
        old_room.parent_series_id = UUID(retired["parent"]) if retired["parent"] else None
        await _move_threads(db, uuids(retired["threads"]), series_id=old_room.id)
        await _move_threads(db, uuids(retired["tagged"]), work_id=None)
        if retired["works"]:
            await db.execute(update(Work).where(Work.id.in_(uuids(retired["works"]))).values(series_id=old_room.id))
        if retired["repointed"]:
            await db.execute(update(Series).where(Series.id.in_(uuids(retired["repointed"])))
                             .values(merged_into_id=old_room.id))
    elif old_room.merged_into_id is not None or old_room.dissolved_at is not None:
        raise Conflict(_STALE)

    await _move_threads(db, moved, series_id=old_room.id)
    await db.delete(member)
    await db.flush()
    for state in [*s["old_members"], *([s["prior_target_member"]] if s["prior_target_member"] else [])]:
        db.add(restore_member(state))
    work.series_id = old_room.id
    await db.flush()
    if s["created_series"] and not await _live_count(db, target.id) and not await db.scalar(
        select(func.count()).select_from(Thread).where(Thread.series_id == target.id)
    ):
        target.merged_into_id = old_room.id  # a link shared in the meantime still resolves
        await db.flush()


async def _undo_set_position(db: AsyncSession, c: CatalogCorrection) -> None:
    s = c.snapshot
    member = await db.get(SeriesMember, (UUID(s["member_series"]), c.work_id))
    if member is None or member.position != c.payload["position"]:
        raise Conflict(_STALE)
    prior = s["prior"]
    if prior is None:
        await db.delete(member)
    else:
        restored = restore_member(prior)
        member.position, member.provenance, member.confidence = (
            restored.position, restored.provenance, restored.confidence)
    await db.flush()


async def _undo_rename(db: AsyncSession, c: CatalogCorrection) -> None:
    series = await db.get(Series, c.series_id)
    if series is None or series.name != c.payload["name"]:
        raise Conflict(_STALE)
    series.name = c.snapshot["old_name"]
    await db.flush()


async def _check_reattach(db: AsyncSession, state: dict) -> tuple[Work, Series]:
    work = await db.get(Work, UUID(state["work"]))
    single = await db.get(Series, UUID(state["singleton"]))
    if (work is None or single is None or work.merged_into_id is not None
            or work.series_id != single.id or single.merged_into_id is not None):
        raise Conflict(_STALE)
    if await _live_count(db, single.id) != 1:
        raise Conflict(_STALE)
    now = set((await db.execute(select(Thread.id).where(Thread.series_id == single.id))).scalars().all())
    if now != set(uuids(state["threads"])):
        raise Conflict(f"New discussion started on {work.title}'s own page since; undoing would move it.")
    return work, single


async def _reattach(db: AsyncSession, room: Series, state: dict, work: Work, single: Series) -> None:
    await _move_threads(db, uuids(state["threads"]), series_id=room.id)
    for member in state["members"]:
        db.add(restore_member(member))
    work.series_id = room.id
    single.merged_into_id = room.id  # a link shared in the meantime still resolves
    await db.flush()


async def _undo_remove(db: AsyncSession, c: CatalogCorrection) -> None:
    room = await db.get(Series, c.series_id)
    if room is None or room.merged_into_id is not None or room.dissolved_at is not None:
        raise Conflict(_STALE)
    work, single = await _check_reattach(db, c.snapshot)
    await _reattach(db, room, c.snapshot, work, single)


async def _undo_reject(db: AsyncSession, c: CatalogCorrection) -> None:
    series = await db.get(Series, c.series_id)
    if series is None or series.merged_into_id is not None or series.dissolved_at is None:
        raise Conflict(_STALE)
    # Check every member before touching any, so a refusal leaves nothing half-undone.
    checked = [await _check_reattach(db, state) for state in c.snapshot["members"]]
    series.dissolved_at = None
    for state, (work, single) in zip(c.snapshot["members"], checked):
        await _reattach(db, series, state, work, single)


_REVERT = {
    CorrectionOp.set_series: _undo_set_series,
    CorrectionOp.set_position: _undo_set_position,
    CorrectionOp.rename_series: _undo_rename,
    CorrectionOp.remove_from_series: _undo_remove,
    CorrectionOp.reject_series: _undo_reject,
}
```

Append to `__init__.py`: `from app.services.librarian.undo import UNDOABLE, revert  # noqa: E402,F401`.

- [ ] **Step 4: Run the tests**

Run: `PYTEST tests/test_librarian_undo.py tests/test_librarian_placement.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/librarian backend/tests/test_librarian_undo.py
git commit -m "feat(librarian): undo the latest fix while the catalog still matches it"
```

---

### Task 8: Runtime respects librarian placement

**Files:**
- Modify: `backend/app/services/series.py`
- Test: `backend/tests/test_librarian_runtime.py` (create)

**Interfaces:**
- Consumes: `CatalogCorrection`, `CorrectionOp` (Task 1); Task 4 `set_series`; Task 7 `revert`.
- Produces: `assign_series` returns `current` unchanged for a work with an unreverted `set_series` / `remove_from_series` correction.

- [ ] **Step 1: Failing tests**

`backend/tests/test_librarian_runtime.py`:

```python
from app.models import Series
from app.services.librarian.placement import remove_from_series, set_series
from app.services.librarian.undo import revert
from app.services.series import assign_series
from tests.librarian_factories import make_series, make_user, make_work


async def test_a_librarian_placed_book_is_not_re_roomed_by_search(db_session):
    lib = await make_user(db_session, librarian=True)
    x = await make_work(db_session, "Iron Gold", ol_id="OL40W")
    x.subjects = "franchise:Red Rising"
    await db_session.flush()
    c = await set_series(db_session, lib, x, new_series_name="Red Rising Saga Two", reason="r")

    room = await assign_series(db_session, x)  # what a search re-ingest does
    assert room.id == c.series_id and x.series_id == c.series_id

    await revert(db_session, lib, c)
    room = await assign_series(db_session, x)  # no longer protected: the tag wins again
    assert room.name == "Red Rising"


async def test_a_removed_book_stays_on_its_own_page(db_session):
    lib = await make_user(db_session, librarian=True)
    first = await make_work(db_session, "Red Rising", ol_id="OL30W")
    x = await make_work(db_session, "Not Red Rising", ol_id="OL41W")
    for w in (first, x):
        w.subjects = "franchise:Red Rising"
    await db_session.flush()
    saga = await assign_series(db_session, first)
    assert (await assign_series(db_session, x)).id == saga.id

    await remove_from_series(db_session, lib, saga, x, reason="mis-tagged")
    own = x.series_id
    assert own != saga.id
    assert (await assign_series(db_session, x)).id == own
```

- [ ] **Step 2: Run to verify failure**

Run: `PYTEST tests/test_librarian_runtime.py -q`
Expected: the first assertion fails (`assign_series` promoted the book into the tag series).

- [ ] **Step 3: Implement**

In `backend/app/services/series.py` add `CatalogCorrection, CorrectionOp` to the models import and:

```python
async def _placed_by_librarian(db: AsyncSession, work: Work) -> bool:
    return bool(await db.scalar(select(func.count()).select_from(CatalogCorrection).where(
        CatalogCorrection.work_id == work.id,
        CatalogCorrection.reverted_at.is_(None),
        CatalogCorrection.op.in_((CorrectionOp.set_series, CorrectionOp.remove_from_series)),
    )))
```

In `assign_series`, directly after the release-room early return:

```python
    # A librarian put it here; a search re-ingest must not undo that.
    if current is not None and await _placed_by_librarian(db, work):
        return current
```

Extend the docstring's last paragraph: "…and neither is a work a librarian placed (an unreverted set_series or remove_from_series correction)."

- [ ] **Step 4: Run the tests**

Run: `PYTEST tests/test_librarian_runtime.py tests/test_series_service.py tests/test_search.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/series.py backend/tests/test_librarian_runtime.py
git commit -m "feat(series): search ingest leaves librarian-placed books where they were put"
```

---
### Task 9: Librarian API

**Files:**
- Create: `backend/app/schemas/librarian.py`, `backend/app/api/librarian.py`, `backend/tests/test_librarian_api.py`
- Modify: `backend/app/main.py`

**Interfaces:**
- Consumes: every op from Tasks 4–7 via `app.services.librarian`; `require_librarian` (Task 1).
- Produces (paths under `/api/librarian`; writes answer 201 with `CorrectionOut`):
  ```
  POST /works/{id}/merge      {into_work_id, reason, confirm}
  POST /works/{id}/split      {edition_ids[], reason, confirm}
  POST /works/{id}/move       {series_id | new_series_name, position?, reason}
  GET  /works/{id}/editions   -> EditionOut[]
  POST /series/{id}/position  {work_id, position | null, reason}
  POST /series/{id}/remove    {work_id, reason}
  POST /series/{id}/rename    {name, reason}
  POST /series/{id}/dissolve  {reason}
  GET  /corrections           ?runtime_only=&work_id=&series_id=&limit=&offset=  -> CorrectionOut[]
  POST /corrections/{id}/revert  -> 200 CorrectionOut
  GET  /series-search?q=      -> SeriesHit[]
  ```
  `CorrectionOut = {id, op, reason, created_at, user, exportable, runtime_only_reason, undoable, reverted_at, room_slug, subject}`. `room_slug` is the room the subject work lives in now (or the subject series' slug), and `subject` is its title or name. A `LibrarianError` maps to its status with `detail` = message, or `{"message", "consequences"}` for a confirmation.

- [ ] **Step 1: Failing tests**

`backend/tests/test_librarian_api.py`:

```python
import uuid

import pytest

from app.models import Series
from tests.librarian_factories import (
    headers_for, make_edition, make_member, make_series, make_thread, make_user, make_work,
)

R = "2026.10.1"
ANY = "00000000-0000-0000-0000-000000000000"
WRITES = [
    (f"/api/librarian/works/{ANY}/merge", {"into_work_id": ANY, "reason": "r"}),
    (f"/api/librarian/works/{ANY}/split", {"edition_ids": [], "reason": "r"}),
    (f"/api/librarian/works/{ANY}/move", {"new_series_name": "x", "reason": "r"}),
    (f"/api/librarian/series/{ANY}/position", {"work_id": ANY, "position": 1, "reason": "r"}),
    (f"/api/librarian/series/{ANY}/remove", {"work_id": ANY, "reason": "r"}),
    (f"/api/librarian/series/{ANY}/rename", {"name": "x", "reason": "r"}),
    (f"/api/librarian/series/{ANY}/dissolve", {"reason": "r"}),
    (f"/api/librarian/corrections/{ANY}/revert", {}),
]
READS = ["/api/librarian/corrections", "/api/librarian/series-search?q=a", f"/api/librarian/works/{ANY}/editions"]


async def test_every_route_refuses_readers_and_anonymous(client, db_session):
    reader = headers_for(await make_user(db_session))
    for path, body in WRITES:
        assert (await client.post(path, json=body, headers=reader)).status_code == 403, path
        assert (await client.post(path, json=body)).status_code in (401, 403), path
    for path in READS:
        assert (await client.get(path, headers=reader)).status_code == 403, path


async def test_unknown_ids_are_404(client, db_session):
    lib = headers_for(await make_user(db_session, librarian=True))
    for path, body in WRITES:
        resp = await client.post(path, json=body, headers=lib)
        assert resp.status_code == 404, (path, resp.text)  # the route looks the row up first


async def test_move_lands_on_the_new_room_and_undo_restores(client, db_session):
    librarian = await make_user(db_session, librarian=True)
    lib = headers_for(librarian)
    book = await make_work(db_session, "The Fifth Season", ol_id="OL50W")

    resp = await client.post(f"/api/librarian/works/{book.id}/move",
                             json={"new_series_name": "The Broken Earth", "position": 1, "reason": "trilogy"},
                             headers=lib)
    assert resp.status_code == 201, resp.text
    out = resp.json()
    assert out["op"] == "set_series" and out["exportable"] is True and out["undoable"] is True
    assert out["user"] == librarian.username and out["subject"] == "The Fifth Season"
    page = (await client.get(f"/api/series/{out['room_slug']}")).json()
    assert [w["title"] for w in page["works"]] == ["The Fifth Season"]

    undone = await client.post(f"/api/librarian/corrections/{out['id']}/revert", headers=lib)
    assert undone.status_code == 200, undone.text
    assert undone.json()["reverted_at"] is not None and undone.json()["undoable"] is False


async def test_blank_reason_is_422(client, db_session):
    lib = headers_for(await make_user(db_session, librarian=True))
    book = await make_work(db_session, "Book", ol_id="OL1W")
    resp = await client.post(f"/api/librarian/works/{book.id}/move",
                             json={"new_series_name": "S", "reason": "   "}, headers=lib)
    assert resp.status_code == 422 and "reason" in resp.json()["detail"]


async def test_merge_asks_for_confirmation_then_refuses_a_second_merge(client, db_session):
    lib = headers_for(await make_user(db_session, librarian=True))
    source = await make_work(db_session, "Dune", ol_id="OL2W", author="Brian Herbert")
    target = await make_work(db_session, "Dune", ol_id="OL1W", author="Frank Herbert")
    await make_edition(db_session, source, ol_id="OL5M")
    path, body = f"/api/librarian/works/{source.id}/merge", {"into_work_id": str(target.id), "reason": "same"}

    ask = await client.post(path, json=body, headers=lib)
    assert ask.status_code == 422
    assert ask.json()["detail"]["consequences"] == {"threads": 0, "shelves": 0, "editions": 1}
    assert "cannot be undone" in ask.json()["detail"]["message"]

    done = await client.post(path, json={**body, "confirm": True}, headers=lib)
    assert done.status_code == 201 and done.json()["undoable"] is False
    again = await client.post(path, json={**body, "confirm": True}, headers=lib)
    assert again.status_code == 409


async def test_split_through_the_editions_listing(client, db_session):
    lib = headers_for(await make_user(db_session, librarian=True))
    work = await make_work(db_session, "Dune", ol_id="OL100W")
    await make_edition(db_session, work, ol_id="OL1M")
    await make_edition(db_session, work, ol_id="OL2M", title="Dune Messiah")
    editions = (await client.get(f"/api/librarian/works/{work.id}/editions", headers=lib)).json()
    assert {e["title"] for e in editions} == {"Dune", "Dune Messiah"}
    messiah = next(e["id"] for e in editions if e["title"] == "Dune Messiah")
    resp = await client.post(f"/api/librarian/works/{work.id}/split",
                             json={"edition_ids": [messiah], "reason": "sequel", "confirm": True}, headers=lib)
    assert resp.status_code == 201 and resp.json()["op"] == "split_work"


async def test_series_routes(client, db_session):
    lib = headers_for(await make_user(db_session, librarian=True))
    saga = await make_series(db_session, "Saga", release=R)
    x = await make_work(db_session, "X", series=saga, ol_id="OL1W")
    y = await make_work(db_session, "Y", series=saga, ol_id="OL2W")
    await make_member(db_session, saga, x, 1.0)
    await make_member(db_session, saga, y, 2.0)
    base = f"/api/librarian/series/{saga.id}"
    for path, body, op in [
        (f"{base}/position", {"work_id": str(x.id), "position": 3, "reason": "r"}, "set_position"),
        (f"{base}/rename", {"name": "The Saga", "reason": "r"}, "rename_series"),
        (f"{base}/remove", {"work_id": str(y.id), "reason": "r"}, "remove_from_series"),
        (f"{base}/dissolve", {"reason": "r"}, "reject_series"),
    ]:
        resp = await client.post(path, json=body, headers=lib)
        assert resp.status_code == 201, (path, resp.text)
        assert resp.json()["op"] == op


async def test_corrections_list_filters_runtime_only(client, db_session):
    lib = headers_for(await make_user(db_session, librarian=True))
    ol = await make_work(db_session, "Exportable", ol_id="OL1W")
    heuristic = await make_work(db_session, "Runtime Only")
    for w in (ol, heuristic):
        await client.post(f"/api/librarian/works/{w.id}/move",
                          json={"new_series_name": f"S {w.title}", "reason": "r"}, headers=lib)
    all_rows = (await client.get("/api/librarian/corrections", headers=lib)).json()
    assert len(all_rows) == 2 and all_rows[0]["subject"] == "Runtime Only"  # newest first
    runtime = (await client.get("/api/librarian/corrections?runtime_only=true", headers=lib)).json()
    assert [r["subject"] for r in runtime] == ["Runtime Only"]
    assert "no Open Library id" in runtime[0]["runtime_only_reason"]


async def test_series_search_offers_only_real_top_level_live_series(client, db_session):
    lib = headers_for(await make_user(db_session, librarian=True))
    top = await make_series(db_session, "Discworld", release=R)
    await make_series(db_session, "Discworld Death", release=R, parent=top)
    gone = await make_series(db_session, "Discworld Old")
    from datetime import datetime, timezone
    gone.dissolved_at = datetime.now(timezone.utc)
    await make_work(db_session, "Discworld")  # its singleton is named Discworld too
    await make_work(db_session, "Mort", series=top, ol_id="OL7W")
    await db_session.flush()
    hits = (await client.get("/api/librarian/series-search?q=discworld", headers=lib)).json()
    assert [(h["name"], h["book_count"]) for h in hits] == [("Discworld", 1)]
```

- [ ] **Step 2: Run to verify failure**

Run: `PYTEST tests/test_librarian_api.py -q`
Expected: 404s everywhere (no router), so the first test fails on `== 403`.

- [ ] **Step 3: Schemas**

`backend/app/schemas/librarian.py`:

```python
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from app.models import CorrectionOp


class _Reasoned(BaseModel):
    # Non-empty after strip is enforced by the service (clean_reason), so the
    # message is the same whichever route refuses it.
    reason: str


class MergeIn(_Reasoned):
    into_work_id: UUID
    confirm: bool = False


class SplitIn(_Reasoned):
    edition_ids: list[UUID]
    confirm: bool = False


class MoveIn(_Reasoned):
    series_id: UUID | None = None
    new_series_name: str | None = None
    position: float | None = None


class PositionIn(_Reasoned):
    work_id: UUID
    position: float | None = None


class RemoveIn(_Reasoned):
    work_id: UUID


class RenameIn(_Reasoned):
    name: str


class DissolveIn(_Reasoned):
    pass


class CorrectionOut(BaseModel):
    id: UUID
    op: CorrectionOp
    reason: str
    created_at: datetime
    user: str
    exportable: bool
    runtime_only_reason: str | None = None
    undoable: bool
    reverted_at: datetime | None = None
    room_slug: str | None = None  # where the subject lives now, so the page can follow it
    subject: str | None = None  # the subject work's title, or the series' name


class SeriesHit(BaseModel):
    id: UUID
    slug: str
    name: str
    book_count: int


class EditionOut(BaseModel):
    id: UUID
    title: str
    publisher: str | None = None
    published_year: int | None = None
    language: str | None = None
    source: str
```

- [ ] **Step 4: Routes**

`backend/app/api/librarian.py`:

```python
"""Librarian tools (spec §7). Thin: the services decide, these map errors."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Book, CatalogCorrection, Series, SeriesKind, User, Work
from app.schemas.librarian import (
    CorrectionOut, DissolveIn, EditionOut, MergeIn, MoveIn, PositionIn, RemoveIn, RenameIn, SeriesHit, SplitIn,
)
from app.services import librarian
from app.services.auth import require_librarian
from app.services.librarian.errors import LibrarianError
from app.services.librarian.record import latest_for_subject
from app.services.librarian.undo import UNDOABLE
from app.services.works import canonical_work

router = APIRouter(prefix="/librarian", tags=["librarian"])


async def _run(call):
    try:
        return await call
    except LibrarianError as exc:
        detail = exc.message if exc.consequences is None else {
            "message": exc.message, "consequences": exc.consequences}
        raise HTTPException(status_code=exc.status_code, detail=detail) from None


async def _work(db: AsyncSession, work_id: UUID) -> Work:
    work = await db.get(Work, work_id)
    if work is None:
        raise HTTPException(status_code=404, detail="Unknown book.")
    return work


async def _series(db: AsyncSession, series_id: UUID) -> Series:
    series = await db.get(Series, series_id)
    if series is None:
        raise HTTPException(status_code=404, detail="Unknown series.")
    return series


async def correction_out(db: AsyncSession, c: CatalogCorrection) -> CorrectionOut:
    user = await db.get(User, c.user_id)
    room_slug = subject = None
    if c.work_id is not None and (work := await db.get(Work, c.work_id)) is not None:
        work = await canonical_work(db, work)
        subject, room_slug = work.title, (await db.get(Series, work.series_id)).slug
    elif c.series_id is not None and (series := await db.get(Series, c.series_id)) is not None:
        subject, room_slug = series.name, series.slug
    undoable = False
    if c.op in UNDOABLE and c.reverted_at is None:
        latest = await latest_for_subject(db, c)
        undoable = latest is not None and latest.id == c.id
    return CorrectionOut(
        id=c.id, op=c.op, reason=c.reason, created_at=c.created_at, user=user.username,
        exportable=c.override is not None, runtime_only_reason=c.runtime_only_reason, undoable=undoable,
        reverted_at=c.reverted_at, room_slug=room_slug, subject=subject,
    )


_CREATED = {"response_model": CorrectionOut, "status_code": status.HTTP_201_CREATED}


@router.post("/works/{work_id}/merge", **_CREATED)
async def merge_work(work_id: UUID, body: MergeIn, db: AsyncSession = Depends(get_db),
                     user: User = Depends(require_librarian)):
    source, target = await _work(db, work_id), await _work(db, body.into_work_id)
    c = await _run(librarian.merge(db, user, source, target, reason=body.reason, confirm=body.confirm))
    return await correction_out(db, c)


@router.post("/works/{work_id}/split", **_CREATED)
async def split_work(work_id: UUID, body: SplitIn, db: AsyncSession = Depends(get_db),
                     user: User = Depends(require_librarian)):
    work = await _work(db, work_id)
    c = await _run(librarian.split(db, user, work, body.edition_ids, reason=body.reason, confirm=body.confirm))
    return await correction_out(db, c)


@router.post("/works/{work_id}/move", **_CREATED)
async def move_work(work_id: UUID, body: MoveIn, db: AsyncSession = Depends(get_db),
                    user: User = Depends(require_librarian)):
    work = await _work(db, work_id)
    series = await _series(db, body.series_id) if body.series_id is not None else None
    c = await _run(librarian.set_series(db, user, work, series=series, new_series_name=body.new_series_name,
                                        position=body.position, reason=body.reason))
    return await correction_out(db, c)


@router.get("/works/{work_id}/editions", response_model=list[EditionOut])
async def work_editions(work_id: UUID, db: AsyncSession = Depends(get_db),
                        user: User = Depends(require_librarian)):
    work = await _work(db, work_id)
    rows = (await db.execute(select(Book).where(Book.work_id == work.id)
                             .order_by(Book.published_year.nulls_last(), Book.title))).scalars().all()
    return [EditionOut(id=b.id, title=b.title, publisher=b.publisher, published_year=b.published_year,
                       language=b.language, source=b.source) for b in rows]


@router.post("/series/{series_id}/position", **_CREATED)
async def position_in_series(series_id: UUID, body: PositionIn, db: AsyncSession = Depends(get_db),
                             user: User = Depends(require_librarian)):
    room, work = await _series(db, series_id), await _work(db, body.work_id)
    c = await _run(librarian.set_position(db, user, room, work, body.position, reason=body.reason))
    return await correction_out(db, c)


@router.post("/series/{series_id}/remove", **_CREATED)
async def remove_from_series(series_id: UUID, body: RemoveIn, db: AsyncSession = Depends(get_db),
                             user: User = Depends(require_librarian)):
    room, work = await _series(db, series_id), await _work(db, body.work_id)
    c = await _run(librarian.remove_from_series(db, user, room, work, reason=body.reason))
    return await correction_out(db, c)


@router.post("/series/{series_id}/rename", **_CREATED)
async def rename(series_id: UUID, body: RenameIn, db: AsyncSession = Depends(get_db),
                 user: User = Depends(require_librarian)):
    series = await _series(db, series_id)
    c = await _run(librarian.rename_series(db, user, series, body.name, reason=body.reason))
    return await correction_out(db, c)


@router.post("/series/{series_id}/dissolve", **_CREATED)
async def dissolve(series_id: UUID, body: DissolveIn, db: AsyncSession = Depends(get_db),
                   user: User = Depends(require_librarian)):
    series = await _series(db, series_id)
    c = await _run(librarian.reject_series(db, user, series, reason=body.reason))
    return await correction_out(db, c)


@router.get("/corrections", response_model=list[CorrectionOut])
async def list_corrections(
    runtime_only: bool | None = None, work_id: UUID | None = None, series_id: UUID | None = None,
    limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db), user: User = Depends(require_librarian),
):
    query = select(CatalogCorrection)
    if runtime_only is not None:
        query = query.where(CatalogCorrection.override.is_(None) if runtime_only
                            else CatalogCorrection.override.is_not(None))
    if work_id is not None:
        query = query.where(CatalogCorrection.work_id == work_id)
    if series_id is not None:
        query = query.where(CatalogCorrection.series_id == series_id)
    rows = (await db.execute(query.order_by(CatalogCorrection.created_at.desc(), CatalogCorrection.id.desc())
                             .limit(limit).offset(offset))).scalars().all()
    return [await correction_out(db, c) for c in rows]


@router.post("/corrections/{correction_id}/revert", response_model=CorrectionOut)
async def revert_correction(correction_id: UUID, db: AsyncSession = Depends(get_db),
                            user: User = Depends(require_librarian)):
    c = await db.get(CatalogCorrection, correction_id)
    if c is None:
        raise HTTPException(status_code=404, detail="Unknown fix.")
    await _run(librarian.revert(db, user, c))
    return await correction_out(db, c)


@router.get("/series-search", response_model=list[SeriesHit])
async def series_search(q: str = Query(..., min_length=1), db: AsyncSession = Depends(get_db),
                        user: User = Depends(require_librarian)):
    """Move targets: real, live, top-level series. Singletons, dissolved series and
    sub-series are never offered (see set_series)."""
    escaped = q.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    books = (select(func.count()).select_from(Work)
             .where(Work.series_id == Series.id, Work.merged_into_id.is_(None))
             .correlate(Series).scalar_subquery())
    rows = (await db.execute(
        select(Series, books.label("books")).where(
            Series.name.ilike(f"%{escaped}%", escape="\\"), Series.kind == SeriesKind.series,
            Series.dissolved_at.is_(None), Series.merged_into_id.is_(None), Series.parent_series_id.is_(None),
        ).order_by(Series.name).limit(10)
    )).all()
    return [SeriesHit(id=s.id, slug=s.slug, name=s.name, book_count=n) for s, n in rows]
```

In `backend/app/main.py` add `librarian` to the `from app.api import …` line and, after the users router:

```python
app.include_router(librarian.router, prefix="/api")
```

- [ ] **Step 5: Run the tests**

Run: `PYTEST tests/test_librarian_api.py tests/test_openapi.py -q`
Expected: all pass. If `test_openapi.py` asserts a tag list, add `librarian` to `openapi_tags` in `main.py` with the description "Catalog fixes by trusted users."

- [ ] **Step 6: Commit**

```bash
git add backend/app/schemas/librarian.py backend/app/api/librarian.py backend/app/main.py backend/tests/test_librarian_api.py
git commit -m "feat(api): librarian routes for catalog fixes, the fix log and undo"
```

---
### Task 10: Export to pipeline overrides

**Files:**
- Create: `backend/app/services/librarian/export.py`, `backend/scripts/export_overrides.py`, `backend/tests/test_librarian_export.py`
- Modify: `pipeline/overrides/README.md`

**Interfaces:**
- Consumes: `CatalogCorrection.override` lists (Tasks 4–6); `pipeline.overrides.load_overrides(directory)` (contract test only); `catalog_loader.read_release` / `load_release` and the `write_release` fixture (round-trip test).
- Produces: `export.HEADER`; `async exportable(db) -> list[tuple[CatalogCorrection, str]]`; `async runtime_only(db) -> list[tuple[CatalogCorrection, str]]` (both unreverted, ordered `created_at, id`, paired with the username); `render(rows) -> str`; `scripts.export_overrides.run(db, out: Path, check: bool) -> int`; `DEFAULT_OUT`.

- [ ] **Step 1: Failing tests**

`backend/tests/test_librarian_export.py`:

```python
import re
import sys
import uuid
from pathlib import Path

import pytest
from sqlalchemy import func, select

from app.models import Series, Work
from app.services.catalog_loader import load_release, read_release
from app.services.librarian.export import exportable, render, runtime_only
from app.services.librarian.identity import merge, split
from app.services.librarian.placement import rename_series, set_series
from app.services.librarian.undo import revert
from app.services.series_identity import release_series_id
from scripts.export_overrides import run
from tests.librarian_factories import make_member, make_series, make_user, make_work

R = "2026.10.1"
REPO = Path(__file__).resolve().parents[2]


async def some_fixes(db):
    lib = await make_user(db, librarian=True, username="ada")
    saga = await make_series(db, "Song of Ice", release=R, key="wd:Q45875")
    await rename_series(db, lib, saga, "A Song of Ice and Fire", reason="full title\nper the cover")
    book = await make_work(db, "A Game of Thrones", ol_id="OL10W")
    await set_series(db, lib, book, series=saga, position=1, reason="book one")
    await set_series(db, lib, await make_work(db, "Heuristic"), new_series_name="Nowhere", reason="runtime")
    undone = await set_series(db, lib, await make_work(db, "Undone", ol_id="OL11W"), series=saga, reason="oops")
    await revert(db, lib, undone)
    return lib


async def test_render_is_deterministic_ordered_and_commented(db_session):
    await some_fixes(db_session)
    rows = await exportable(db_session)
    text = render(rows)
    assert text == render(await exportable(db_session))
    assert [c.reason for c, _ in rows] == ["full title\nper the cover", "book one"]  # no runtime-only, no reverted
    assert re.search(r"^# full title  \(ada, \d{4}-\d{2}-\d{2}, correction [0-9a-f]{8}\)$", text, re.M)
    assert "\n# per the cover\n" in text
    assert text.index("rename_series") < text.index("set_series")
    assert [c.reason for c, _ in await runtime_only(db_session)] == ["runtime"]


async def test_run_writes_and_checks(db_session, tmp_path, capsys):
    await some_fixes(db_session)
    out = tmp_path / "z-librarian.yaml"
    assert await run(db_session, out, check=True) == 1  # missing
    assert await run(db_session, out, check=False) == 0
    assert await run(db_session, out, check=True) == 0
    assert "runtime-only" in capsys.readouterr().out
    out.write_text(out.read_text() + "# edited\n")
    assert await run(db_session, out, check=True) == 1


def _load_overrides():
    if not (REPO / "pipeline" / "overrides.py").exists():
        pytest.skip("pipeline/ is not present next to backend/ (mount it; see the plan's PYTEST)")
    sys.path.insert(0, str(REPO))
    try:
        from pipeline import overrides
    finally:
        sys.path.remove(str(REPO))
    return overrides


async def test_the_pipeline_reads_the_export(db_session, tmp_path):
    overrides = _load_overrides()
    await some_fixes(db_session)
    saga = (await db_session.execute(select(Series).where(Series.external_id == "wd:Q45875"))).scalar_one()
    merged_into = await make_work(db_session, "Target", ol_id="OL1W")
    lib = await make_user(db_session, librarian=True)
    await merge(db_session, lib, await make_work(db_session, "Loser", ol_id="OL2W"), merged_into,
                reason="dup", confirm=True)
    (tmp_path / "z-librarian.yaml").write_text(render(await exportable(db_session)))

    parsed = overrides.load_overrides(tmp_path)

    assert [type(o).__name__ for o in parsed] == ["RenameSeries", "SetSeries", "MergeWorks"]
    assert (parsed[0].series, parsed[0].name) == ("wd:Q45875", "A Song of Ice and Fire")
    assert (parsed[1].work, parsed[1].series, parsed[1].position) == ("OL10W", "wd:Q45875", 1.0)
    assert (parsed[2].survivor, parsed[2].losers) == ("OL1W", ("OL2W",))
    assert saga.name == "A Song of Ice and Fire"


async def test_a_release_that_applied_the_fixes_adopts_the_runtime_rows(db_session, write_release):
    """Export a merge, a split and a move; load a release built from them: the
    runtime rows are adopted, not duplicated."""
    A = uuid.uuid4()
    W10, W11, E1, E2, E3 = (uuid.uuid4() for _ in range(5))
    series = [{"id": A, "name": "Alpha", "slug": "alpha", "key": "ol:alpha"}]
    works = [{"id": W10, "ol_work_id": "OL10W", "title": "Ten", "series_id": A},
             {"id": W11, "ol_work_id": "OL11W", "title": "Eleven", "series_id": A}]
    editions = [{"id": e, "ol_edition_id": f"OL{i}M", "work_id": W10, "title": t}
                for i, (e, t) in enumerate([(E1, "Ten"), (E2, "Ten"), (E3, "Ten Prequel")], start=1)]
    members = [{"series_id": A, "work_id": W10, "position": 1.0}, {"series_id": A, "work_id": W11, "position": 2.0}]
    await load_release(db_session, read_release(write_release(
        R, series=series, works=works, editions=editions, series_members=members)))

    lib = await make_user(db_session, librarian=True)
    ten, eleven = await db_session.get(Work, W10), await db_session.get(Work, W11)
    await merge(db_session, lib, eleven, ten, reason="dup", confirm=True)
    cut = await split(db_session, lib, ten, [E3], reason="prequel", confirm=True)
    runtime_split = uuid.UUID(cut.payload["new_work"])
    await set_series(db_session, lib, ten, new_series_name="Beta", reason="own saga")

    BETA, S = release_series_id("ol:beta"), uuid.uuid4()
    v2 = read_release(write_release(
        "2026.11.1",
        series=[*series, {"id": BETA, "name": "Beta", "slug": "beta", "key": "ol:beta"}],
        works=[{"id": W10, "ol_work_id": "OL10W", "title": "Ten", "series_id": BETA},
               {"id": S, "ol_work_id": "OL10W~OL3M", "title": "Ten Prequel", "series_id": A}],
        editions=[{**editions[0]}, {**editions[1]}, {**editions[2], "work_id": S}],
        series_members=[{"series_id": BETA, "work_id": W10, "position": None},
                        {"series_id": A, "work_id": S, "position": None}],
        work_aliases=[{"ol_work_id": "OL11W", "work_id": W10}],
    ))
    await load_release(db_session, v2)

    assert await db_session.scalar(select(func.count()).select_from(Series)
                                   .where(Series.canonical_key == "beta")) == 1
    assert await db_session.scalar(select(Work.series_id).where(Work.id == W10)) == BETA
    live_splits = (await db_session.execute(select(Work.id).where(
        Work.title == "Ten Prequel", Work.merged_into_id.is_(None)))).scalars().all()
    assert live_splits == [S]
    assert await db_session.scalar(select(Work.merged_into_id).where(Work.id == runtime_split)) == S
    assert await db_session.scalar(select(Work.merged_into_id).where(Work.id == W11)) == W10
```

- [ ] **Step 2: Run to verify failure**

Run: `PYTEST tests/test_librarian_export.py -q`
Expected: `ModuleNotFoundError: No module named 'app.services.librarian.export'`.

- [ ] **Step 3: Implement**

`backend/app/services/librarian/export.py`:

```python
"""Corrections as pipeline/overrides YAML (spec §9). Same database, same bytes."""

import yaml
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import CatalogCorrection, User

HEADER = (
    "# In-app librarian fixes, written by `python -m scripts.export_overrides`.\n"
    "# Do not edit by hand: undo the fix in the app and export again.\n"
)


async def _unreverted(db: AsyncSession, *, exportable: bool) -> list[tuple[CatalogCorrection, str]]:
    query = (
        select(CatalogCorrection, User.username)
        .join(User, User.id == CatalogCorrection.user_id)
        .where(CatalogCorrection.reverted_at.is_(None),
               CatalogCorrection.override.is_not(None) if exportable else CatalogCorrection.override.is_(None))
        .order_by(CatalogCorrection.created_at, CatalogCorrection.id)
    )
    return [(c, username) for c, username in (await db.execute(query)).all()]


async def exportable(db: AsyncSession) -> list[tuple[CatalogCorrection, str]]:
    return await _unreverted(db, exportable=True)


async def runtime_only(db: AsyncSession) -> list[tuple[CatalogCorrection, str]]:
    return await _unreverted(db, exportable=False)


def _comment(c: CatalogCorrection, username: str) -> str:
    lines = c.reason.splitlines() or [""]
    stamp = f"  ({username}, {c.created_at:%Y-%m-%d}, correction {str(c.id)[:8]})"
    out = [f"# {lines[0]}{stamp}\n"]
    out += [f"# {line}\n" if line else "#\n" for line in lines[1:]]
    return "".join(out)


def render(rows: list[tuple[CatalogCorrection, str]]) -> str:
    """The whole file. The pipeline reads overrides in name order and applies
    entries in order, so a later fix to the same book wins."""
    parts = [HEADER]
    for c, username in rows:
        parts.append("\n")
        parts.append(_comment(c, username))
        for entry in c.override:
            parts.append(yaml.safe_dump([entry], default_flow_style=None, sort_keys=False,
                                        allow_unicode=True, width=4096))
    return "".join(parts)
```

`backend/scripts/export_overrides.py`:

```python
"""Write in-app librarian fixes as pipeline overrides.

``python -m scripts.export_overrides [--out pipeline/overrides/z-librarian.yaml] [--check]``

Run from a workstation against the production DATABASE_URL, then review and
commit the file like any other change. ``--check`` writes nothing and exits 1
when the file on disk differs. Runtime-only fixes are listed, not exported.
"""

import argparse
import asyncio
import sys
from pathlib import Path

from app.database import AsyncSessionLocal
from app.services.librarian.export import exportable, render, runtime_only

DEFAULT_OUT = Path(__file__).resolve().parents[2] / "pipeline" / "overrides" / "z-librarian.yaml"


async def run(db, out: Path, check: bool) -> int:
    text = render(await exportable(db))
    for c, username in await runtime_only(db):
        print(f"runtime-only  {str(c.id)[:8]}  {c.op.value}  {username}: {c.runtime_only_reason}")
    if check:
        current = out.read_text(encoding="utf-8") if out.exists() else None
        if current != text:
            print(f"{out} is out of date; run without --check to rewrite it", file=sys.stderr)
            return 1
        print(f"{out} is up to date")
        return 0
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    print(f"wrote {out}")
    return 0


async def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m scripts.export_overrides")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    async with AsyncSessionLocal() as db:
        return await run(db, args.out, args.check)


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
```

Append to `pipeline/overrides/README.md`:

```markdown
## `z-librarian.yaml`

Written by `python -m scripts.export_overrides` (from `backend/`) from fixes
librarians made in the app; never edit it by hand. Its name sorts it last, so
an in-app fix wins over a hand-written one. When a release no longer holds a
book it names, the build fails like any stale override: undo the fix in the
app and export again, or delete the entry.
```

- [ ] **Step 4: Run the tests**

Run: `PYTEST tests/test_librarian_export.py -q`
Expected: 4 passed. Without the `-v "$PWD/pipeline:/pipeline:ro"` mount, the contract test skips; with it, it must pass.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/librarian/export.py backend/scripts/export_overrides.py \
  backend/tests/test_librarian_export.py pipeline/overrides/README.md
git commit -m "feat(librarian): export fixes to pipeline overrides, deterministically"
```

---
### Task 11: Frontend hooks and the action panel

**Files:**
- Create: `frontend/src/api/librarian.js`, `frontend/src/components/LibrarianPanel.jsx`, `frontend/src/components/LibrarianPanel.test.jsx`
- Modify: `frontend/src/api/errors.js` (its new case is tested in `LibrarianPanel.test.jsx`)

**Interfaces:**
- Consumes: the Task 9 routes; `useSearchWorks(query)` from `api/works.js` (enabled for `query.length > 1`).
- Produces, in `api/librarian.js`: `confirmationOf(error) -> object | null`; `useLibrarianAction()` (mutation of `{ path, body }` → `CorrectionOut`; invalidates `['series']` and `['librarian']`); `useRevertCorrection()` (mutation of a correction id); `useSeriesSearch(q)`; `useWorkEditions(workId)`; `useCorrections({ runtimeOnly })`.
- Produces: `<LibrarianPanel action={{ kind, work?, series }} onClose={fn} onDone={(correction) => …} />`, where `kind` is one of `move | position | remove | merge | split | rename | dissolve`, `work` is `{ id, title, author, position }` and `series` is `{ id, name, slug, kind }`. `errorMessage` now reads `detail.message` from an object `detail`.

- [ ] **Step 1: Failing tests**

`frontend/src/components/LibrarianPanel.test.jsx`:

```jsx
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

vi.mock('../api/client', () => ({ default: { get: vi.fn(), post: vi.fn() } }))

import client from '../api/client'
import { errorMessage } from '../api/errors'
import LibrarianPanel from './LibrarianPanel'

const SERIES = { id: 's1', name: 'Dune', slug: 'dune', kind: 'series' }
const BOOK = { id: 'w1', title: 'Dune', author: 'Brian Herbert', position: null }
const CORRECTION = { id: 'c1', op: 'set_series', exportable: true, undoable: true, room_slug: 'dune' }

function renderPanel(action, onDone = vi.fn()) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={qc}>
      <LibrarianPanel action={{ series: SERIES, ...action }} onClose={vi.fn()} onDone={onDone} />
    </QueryClientProvider>,
  )
  return onDone
}

beforeEach(() => vi.clearAllMocks())

describe('LibrarianPanel', () => {
  it('will not submit without a reason', async () => {
    renderPanel({ kind: 'rename' })
    const submit = screen.getByRole('button', { name: 'Rename' })
    await userEvent.type(screen.getByLabelText('New name'), 'Dune Chronicles')
    expect(submit).toBeDisabled()
    await userEvent.type(screen.getByLabelText('Reason'), '   ')
    expect(submit).toBeDisabled()
    await userEvent.type(screen.getByLabelText('Reason'), 'the usual name')
    expect(submit).toBeEnabled()
  })

  it('confirms a merge with the counts the server returned', async () => {
    client.get.mockResolvedValue({ data: [{ id: 'w2', title: 'Dune', author: 'Frank Herbert' }] })
    client.post
      .mockRejectedValueOnce({ response: { status: 422, data: { detail: {
        message: 'Merging Dune into Dune cannot be undone.', consequences: { threads: 3, shelves: 12, editions: 4 } } } } })
      .mockResolvedValueOnce({ data: CORRECTION })
    const onDone = renderPanel({ kind: 'merge', work: BOOK })

    await userEvent.type(screen.getByLabelText('Find the book to keep'), 'dune')
    await userEvent.click(await screen.findByRole('radio', { name: /Frank Herbert/ }))
    await userEvent.type(screen.getByLabelText('Reason'), 'same book')
    await userEvent.click(screen.getByRole('button', { name: 'Merge' }))

    expect(await screen.findByText(/3 threads and 12 shelf entries move/)).toBeInTheDocument()
    expect(screen.getByText(/This cannot be undone/)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Confirm merge' }))
    await waitFor(() => expect(onDone).toHaveBeenCalledWith(CORRECTION))
    expect(client.post).toHaveBeenLastCalledWith('/librarian/works/w1/merge',
      { reason: 'same book', into_work_id: 'w2', confirm: true })
  })

  it('moves a book into a series it names', async () => {
    client.get.mockResolvedValue({ data: [] })
    client.post.mockResolvedValue({ data: CORRECTION })
    renderPanel({ kind: 'move', work: BOOK })
    await userEvent.type(screen.getByLabelText('Find a series'), 'Legends of Dune')
    await userEvent.click(await screen.findByRole('radio', { name: 'new series: Legends of Dune' }))
    await userEvent.type(screen.getByLabelText('Position (optional)'), '1')
    await userEvent.type(screen.getByLabelText('Reason'), 'prequel trilogy')
    await userEvent.click(screen.getByRole('button', { name: 'Move' }))
    await waitFor(() => expect(client.post).toHaveBeenCalledWith('/librarian/works/w1/move',
      { reason: 'prequel trilogy', new_series_name: 'Legends of Dune', position: 1 }))
  })

  it('splits the checked editions', async () => {
    client.get.mockResolvedValue({ data: [
      { id: 'e1', title: 'Dune', published_year: 1965, language: 'en', source: 'openlibrary' },
      { id: 'e2', title: 'Dune Messiah', published_year: 1969, language: 'en', source: 'openlibrary' },
    ] })
    client.post.mockRejectedValueOnce({ response: { status: 422, data: { detail: {
      message: 'm', consequences: { editions: 1, remaining: 1 } } } } })
    renderPanel({ kind: 'split', work: BOOK })
    await userEvent.click(await screen.findByRole('checkbox', { name: /Dune Messiah/ }))
    await userEvent.type(screen.getByLabelText('Reason'), 'sequel')
    await userEvent.click(screen.getByRole('button', { name: 'Split' }))
    expect(await screen.findByText(/1 edition of/)).toBeInTheDocument()
    expect(client.post).toHaveBeenCalledWith('/librarian/works/w1/split',
      { reason: 'sequel', edition_ids: ['e2'], confirm: false })
  })

  it('reads a message out of an object detail', () => {
    expect(errorMessage({ response: { data: { detail: { message: 'Nope.', consequences: {} } } } })).toBe('Nope.')
  })
})
```

- [ ] **Step 2: Run to verify failure**

Run: `cd frontend && npx vitest run src/components/LibrarianPanel.test.jsx`
Expected: fails to resolve `./LibrarianPanel`.

- [ ] **Step 3: Hooks and error helper**

`frontend/src/api/errors.js`: before the final `return fallback`, add:

```js
  // Librarian merge/split confirmations answer { detail: { message, consequences } }.
  if (detail && typeof detail.message === 'string') return detail.message
```

`frontend/src/api/librarian.js`:

```js
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import client from './client'

/** The counts a merge or split would affect, when the server asked to confirm. */
export function confirmationOf(error) {
  if (error?.response?.status !== 422) return null
  const detail = error.response.data?.detail
  return detail && !Array.isArray(detail) && typeof detail === 'object' ? detail.consequences ?? null : null
}

function useInvalidateCatalog() {
  const queryClient = useQueryClient()
  return () => {
    // A fix can move a book between rooms, so every series page may be stale.
    queryClient.invalidateQueries({ queryKey: ['series'] })
    queryClient.invalidateQueries({ queryKey: ['librarian'] })
  }
}

export function useLibrarianAction() {
  const invalidate = useInvalidateCatalog()
  return useMutation({
    mutationFn: ({ path, body }) => client.post(`/librarian/${path}`, body).then((r) => r.data),
    onSuccess: invalidate,
  })
}

export function useRevertCorrection() {
  const invalidate = useInvalidateCatalog()
  return useMutation({
    mutationFn: (id) => client.post(`/librarian/corrections/${id}/revert`).then((r) => r.data),
    onSuccess: invalidate,
  })
}

export function useSeriesSearch(q) {
  return useQuery({
    queryKey: ['librarian', 'series-search', q],
    queryFn: () => client.get('/librarian/series-search', { params: { q } }).then((r) => r.data),
    enabled: q.trim().length > 1,
  })
}

export function useWorkEditions(workId) {
  return useQuery({
    queryKey: ['librarian', 'editions', workId],
    queryFn: () => client.get(`/librarian/works/${workId}/editions`).then((r) => r.data),
    enabled: !!workId,
  })
}

export function useCorrections({ runtimeOnly = false } = {}) {
  return useQuery({
    queryKey: ['librarian', 'corrections', runtimeOnly],
    queryFn: () =>
      client.get('/librarian/corrections', { params: runtimeOnly ? { runtime_only: true } : {} }).then((r) => r.data),
  })
}
```

- [ ] **Step 4: The panel**

`frontend/src/components/LibrarianPanel.jsx`:

```jsx
import { useState } from 'react'
import { confirmationOf, useLibrarianAction, useSeriesSearch, useWorkEditions } from '../api/librarian'
import { useSearchWorks } from '../api/works'
import { errorMessage } from '../api/errors'

/**
 * One librarian fix, as a float over the series page: the fields the action
 * needs, a required reason, and, for merge and split, a second step stating
 * what the server says will happen. Nothing here decides anything; the API does.
 */
const TITLES = {
  move: 'Move', position: 'Set position', remove: 'Remove from series', merge: 'Merge',
  split: 'Split', rename: 'Rename', dissolve: 'Dissolve',
}
const plural = (n, one, many = `${one}s`) => `${n} ${n === 1 ? one : many}`

function request(action, f, confirm) {
  const { kind, work, series } = action
  const reason = f.reason.trim()
  const position = f.position === '' ? null : Number(f.position)
  switch (kind) {
    case 'move':
      return { path: `works/${work.id}/move`, body: {
        reason, ...(f.target?.id ? { series_id: f.target.id } : { new_series_name: f.target?.name }),
        ...(position === null ? {} : { position }) } }
    case 'position':
      return { path: `series/${series.id}/position`, body: { reason, work_id: work.id, position } }
    case 'remove':
      return { path: `series/${series.id}/remove`, body: { reason, work_id: work.id } }
    case 'merge':
      return { path: `works/${work.id}/merge`, body: { reason, into_work_id: f.into?.id, confirm } }
    case 'split':
      return { path: `works/${work.id}/split`, body: { reason, edition_ids: f.editions, confirm } }
    case 'rename':
      return { path: `series/${series.id}/rename`, body: { reason, name: f.name.trim() } }
    default:
      return { path: `series/${series.id}/dissolve`, body: { reason } }
  }
}

function ready(kind, f) {
  if (!f.reason.trim()) return false
  if (kind === 'move') return !!f.target
  if (kind === 'merge') return !!f.into
  if (kind === 'split') return f.editions.length > 0
  if (kind === 'rename') return !!f.name.trim()
  return true
}

function SeriesPicker({ value, onChange }) {
  const [q, setQ] = useState('')
  const { data: hits = [] } = useSeriesSearch(q)
  const named = q.trim()
  return (
    <div className="flex flex-col gap-2">
      <label className="label" htmlFor="lib-series">Find a series</label>
      <input id="lib-series" className="input" value={q} onChange={(e) => setQ(e.target.value)} />
      <div role="radiogroup" aria-label="Series" className="flex flex-col gap-1 text-sm">
        {hits.map((s) => (
          <label key={s.id} className="flex items-center gap-2">
            <input type="radio" name="lib-series" checked={value?.id === s.id} onChange={() => onChange(s)} />
            <span className="font-serif text-ink">{s.name}</span>
            <span className="text-ink-dim tabular-nums">{plural(s.book_count, 'book')}</span>
          </label>
        ))}
        {named.length > 1 && !hits.some((s) => s.name.toLowerCase() === named.toLowerCase()) && (
          <label className="flex items-center gap-2">
            <input type="radio" name="lib-series" checked={!value?.id && value?.name === named}
                   onChange={() => onChange({ name: named })} />
            <span className="text-warning">new series: {named}</span>
          </label>
        )}
      </div>
    </div>
  )
}

function WorkPicker({ exclude, value, onChange }) {
  const [q, setQ] = useState('')
  const { data: works = [] } = useSearchWorks(q)
  return (
    <div className="flex flex-col gap-2">
      <label className="label" htmlFor="lib-work">Find the book to keep</label>
      <input id="lib-work" className="input" value={q} onChange={(e) => setQ(e.target.value)} />
      <div role="radiogroup" aria-label="Book to keep" className="flex flex-col gap-1 text-sm">
        {works.filter((w) => w.id !== exclude).map((w) => (
          <label key={w.id} className="flex items-center gap-2">
            <input type="radio" name="lib-work" checked={value?.id === w.id} onChange={() => onChange(w)} />
            <span className="font-serif text-ink">{w.title}</span>
            <span className="text-user text-xs">{w.author}</span>
          </label>
        ))}
      </div>
    </div>
  )
}

function EditionPicker({ workId, value, onChange }) {
  const { data: editions = [] } = useWorkEditions(workId)
  const toggle = (id) => onChange(value.includes(id) ? value.filter((v) => v !== id) : [...value, id])
  return (
    <fieldset className="flex flex-col gap-1 text-sm">
      <legend className="label">Editions to split off</legend>
      {editions.map((e) => (
        <label key={e.id} className="flex items-center gap-2">
          <input type="checkbox" checked={value.includes(e.id)} onChange={() => toggle(e.id)} />
          <span className="font-serif text-ink">{e.title}</span>
          <span className="text-ink-dim tabular-nums">{[e.published_year, e.language, e.source].filter(Boolean).join(' · ')}</span>
        </label>
      ))}
    </fieldset>
  )
}

function Consequences({ action, fields, counts }) {
  const { work } = action
  if (action.kind === 'merge') {
    return (
      <p className="text-sm text-ink">
        <span className="font-serif italic">{work.title}</span> ({work.author}) will merge into{' '}
        <span className="font-serif italic">{fields.into.title}</span> ({fields.into.author}).{' '}
        {plural(counts.threads, 'thread')} and {plural(counts.shelves, 'shelf entry', 'shelf entries')} move.{' '}
        <span className="text-danger">This cannot be undone.</span>
      </p>
    )
  }
  return (
    <p className="text-sm text-ink">
      {plural(counts.editions, 'edition')} of <span className="font-serif italic">{work.title}</span> become a
      book of their own; {counts.remaining} stay. <span className="text-danger">This cannot be undone.</span>
    </p>
  )
}

function LibrarianPanel({ action, onClose, onDone }) {
  const { kind, work, series } = action
  const [fields, setFields] = useState({
    reason: '', name: '', target: null, into: null, editions: [],
    position: work?.position == null ? '' : String(work.position),
  })
  const [counts, setCounts] = useState(null)
  const mutation = useLibrarianAction()
  const set = (key) => (value) => setFields((f) => ({ ...f, [key]: value }))
  const title = `${TITLES[kind]}${work ? ` ${work.title}` : ` ${series.name}`}`

  const submit = (confirm) => {
    mutation.mutate(request(action, fields, confirm), {
      onSuccess: (correction) => onDone(correction),
      onError: (error) => setCounts(confirmationOf(error)),
    })
  }

  return (
    <div className="fixed inset-0 bg-bg/90 flex items-center justify-center z-50 p-4">
      <div role="dialog" aria-modal="true" aria-label={title} className="float w-full max-w-lg flex flex-col gap-4 p-5">
        <div className="flex items-center justify-between">
          <h2 className="text-sm uppercase tracking-eyebrow text-ink">{title}</h2>
          <button type="button" onClick={onClose} aria-label="Close" className="text-ink-dim hover:text-danger">
            <span aria-hidden="true">✕</span>
          </button>
        </div>

        {counts ? (
          <div className="flex flex-col gap-3">
            <Consequences action={action} fields={fields} counts={counts} />
            <div className="flex gap-3">
              <button type="button" className="btn-primary text-xs" onClick={() => submit(true)} disabled={mutation.isPending}>
                {`Confirm ${kind}`}
              </button>
              <button type="button" className="btn-ghost text-xs" onClick={() => setCounts(null)}>back</button>
            </div>
          </div>
        ) : (
          <form className="flex flex-col gap-3" onSubmit={(e) => { e.preventDefault(); submit(false) }}>
            {kind === 'move' && <SeriesPicker value={fields.target} onChange={set('target')} />}
            {(kind === 'move' || kind === 'position') && (
              <div>
                <label className="label" htmlFor="lib-position">{kind === 'move' ? 'Position (optional)' : 'Position (blank clears)'}</label>
                <input id="lib-position" type="number" step="0.5" className="input" value={fields.position}
                       onChange={(e) => set('position')(e.target.value)} />
              </div>
            )}
            {kind === 'merge' && <WorkPicker exclude={work.id} value={fields.into} onChange={set('into')} />}
            {kind === 'split' && <EditionPicker workId={work.id} value={fields.editions} onChange={set('editions')} />}
            {kind === 'rename' && (
              <div>
                <label className="label" htmlFor="lib-name">New name</label>
                <input id="lib-name" className="input" value={fields.name} onChange={(e) => set('name')(e.target.value)} />
              </div>
            )}
            <div>
              <label className="label" htmlFor="lib-reason">Reason</label>
              <textarea id="lib-reason" rows={2} className="input" value={fields.reason}
                        onChange={(e) => set('reason')(e.target.value)} />
            </div>
            {mutation.isError && !confirmationOf(mutation.error) && (
              <p className="alert-danger">{errorMessage(mutation.error)}</p>
            )}
            <button type="submit" className="btn-primary text-xs self-start"
                    disabled={!ready(kind, fields) || mutation.isPending}>
              {TITLES[kind]}
            </button>
          </form>
        )}
      </div>
    </div>
  )
}

export default LibrarianPanel
```

Notes for the implementer:
- `btn-primary` is `bg-accent text-bg` (fills invert). Do not add a danger-filled button: white on colour fails AA, and `text-danger` on the sentence carries the warning.
- The ✕ close glyph is `aria-hidden`, and the button has `aria-label="Close"`, matching `ThreadModal`.
- The "Remove from series" and "Dissolve" kinds need only the reason.

- [ ] **Step 5: Run the tests**

Run: `cd frontend && npx vitest run src/components/LibrarianPanel.test.jsx src/design/tokens.test.js`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/api/librarian.js frontend/src/api/errors.js frontend/src/components/LibrarianPanel.jsx \
  frontend/src/components/LibrarianPanel.test.jsx
git commit -m "feat(web): librarian action panel with reason and merge/split confirmation"
```

---
### Task 12: Series page edit mode

**Files:**
- Modify: `frontend/src/pages/Series.jsx`, `frontend/src/pages/Series.test.jsx`

**Interfaces:**
- Consumes: `LibrarianPanel` and `useRevertCorrection` (Task 11); `SeriesOut.id`, `.dissolved`, `works[].provenance` (Task 2); `user.is_librarian` (Task 1, via `/auth/me` into the auth store).
- Produces: `?edit=1` edit mode (librarians only); per-row actions `move · position · remove · merge into… · split` (a singleton shows `move · merge into… · split`); header actions `rename · dissolve` (real series only); none on a dissolved series; a result line (`role="status"`) with export status, `undo`, and a link to the room the book now lives in. The link carries the correction in `location.state.correction`, so the result line (and undo) survives the navigation.

- [ ] **Step 1: Failing tests**

Append inside the `describe('Series page', …)` block of `frontend/src/pages/Series.test.jsx`:

```jsx
  it('offers edit mode only to librarians', async () => {
    mockApi(SAGA)
    renderPage('/series/red-rising?edit=1')
    await screen.findByRole('list', { name: 'Books in this series' })
    expect(screen.queryByRole('link', { name: '[edit]' })).toBeNull()
    expect(screen.queryByRole('button', { name: /^move/ })).toBeNull()
  })

  it('shows row and header actions in edit mode, and marks librarian-placed books', async () => {
    useAuthStore.setState({ token: 't', user: { id: 'u1', username: 'lib', is_librarian: true } })
    mockApi({ ...SAGA, id: 's1', works: [{ ...SAGA.works[0], provenance: 'override' }, SAGA.works[1]] })
    renderPage('/series/red-rising?edit=1')
    const list = await screen.findByRole('list', { name: 'Books in this series' })
    const [first] = within(list).getAllByRole('listitem')
    for (const name of ['move', 'position', 'remove', 'merge into…', 'split']) {
      expect(within(first).getByRole('button', { name: `${name} Red Rising` })).toBeInTheDocument()
    }
    expect(within(first).getByText('librarian-placed')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'rename series' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: '[done]' })).toBeInTheDocument()
  })

  it('reports a fix and undoes it', async () => {
    useAuthStore.setState({ token: 't', user: { id: 'u1', username: 'lib', is_librarian: true } })
    mockApi({ ...SAGA, id: 's1' })
    client.post
      .mockResolvedValueOnce({ data: { id: 'c1', op: 'remove_from_series', exportable: false,
        runtime_only_reason: 'Red Rising is not in a catalog release', undoable: true, room_slug: 'golden-son-abc' } })
      .mockResolvedValueOnce({ data: { id: 'c1', undoable: false, reverted_at: '2026-09-28T00:00:00Z' } })
    renderPage('/series/red-rising?edit=1')
    const list = await screen.findByRole('list', { name: 'Books in this series' })
    await userEvent.click(within(list).getByRole('button', { name: 'remove Golden Son' }))
    await userEvent.type(screen.getByLabelText('Reason'), 'not a sequel')
    await userEvent.click(screen.getByRole('button', { name: 'Remove from series' }))

    const status = await screen.findByRole('status')
    expect(within(status).getByText(/runtime-only: Red Rising is not in a catalog release/)).toBeInTheDocument()
    expect(within(status).getByRole('link', { name: /go to its page/ })).toHaveAttribute('href', '/series/golden-son-abc?edit=1')
    await userEvent.click(within(status).getByRole('button', { name: 'undo' }))
    expect(client.post).toHaveBeenLastCalledWith('/librarian/corrections/c1/revert')
    expect(await within(status).findByText('undone')).toBeInTheDocument()
  })

  it('shows a dissolved series as a notice with no books and no new threads', async () => {
    mockApi({ ...SAGA, id: 's1', dissolved: true, works: [] })
    renderPage('/series/red-rising')
    expect(await screen.findByText(/This series was dissolved/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Start a Thread' })).toBeNull()
  })
```

`mockApi` sends every non-`/threads` GET to the series payload, so the panel's search hooks receive it too. They only render the arrays they get, and `remove` needs none.

- [ ] **Step 2: Run to verify failure**

Run: `cd frontend && npx vitest run src/pages/Series.test.jsx`
Expected: the three new librarian tests fail (no `[done]` link, no actions). The first new test already passes.

- [ ] **Step 3: Implement**

In `frontend/src/pages/Series.jsx`:

1. Imports: add `useLocation` to the react-router import, plus `import LibrarianPanel from '../components/LibrarianPanel'` and `import { useRevertCorrection } from '../api/librarian'`.

2. Give `BookRow` two new props, `editing` and `onAction(kind)`. After the `ShelfButton`, render:

```jsx
        {editing && (
          <div className="flex flex-wrap gap-x-3 text-xs" aria-label={`Fix ${work.title}`}>
            {(isSeries ? ['move', 'position', 'remove', 'merge into…', 'split'] : ['move', 'merge into…', 'split']).map((name) => (
              <button key={name} type="button" className="btn-ghost text-xs" onClick={() => onAction(name)}
                      aria-label={`${name} ${work.title}`}>
                {name}
              </button>
            ))}
          </div>
        )}
```

   Pass `isSeries` into `BookRow` as well. Next to the position line, when `editing && work.provenance === 'override'`:

```jsx
          <span className="text-xs">
            <span aria-hidden="true" className="text-warning">■</span>
            <span className="sr-only">librarian-placed</span>
          </span>
```

3. A `ResultLine` component in the same file:

```jsx
const KIND_OF = { 'merge into…': 'merge' }

function ResultLine({ correction, currentSlug, onUndone }) {
  const revert = useRevertCorrection()
  const [state, setState] = useState(correction)
  return (
    <p role="status" className="text-xs flex flex-wrap items-center gap-3 border-b border-line pb-3">
      {state.exportable
        ? <span className="text-ok">exported</span>
        : <span className="text-warning">runtime-only: {state.runtime_only_reason}</span>}
      {state.reverted_at ? (
        <span className="text-ink-dim">undone</span>
      ) : state.undoable && (
        <button type="button" className="btn-ghost text-xs" disabled={revert.isPending}
                onClick={() => revert.mutate(state.id, { onSuccess: (c) => { setState({ ...state, ...c }); onUndone?.() } })}>
          undo
        </button>
      )}
      {state.room_slug && state.room_slug !== currentSlug && !state.reverted_at && (
        <Link to={`/series/${state.room_slug}?edit=1`} state={{ correction: state }} className="text-path hover:text-accent">
          go to its page
        </Link>
      )}
    </p>
  )
}
```

4. In `Series()`:

```jsx
  const location = useLocation()
  const editing = !!user?.is_librarian && searchParams.get('edit') === '1'
  const [action, setAction] = useState(null) // { kind, work? } while the panel is open
  const [result, setResult] = useState(location.state?.correction ?? null)
  const editHref = (() => {
    const next = new URLSearchParams(searchParams)
    if (editing) next.delete('edit')
    else next.set('edit', '1')
    const qs = next.toString()
    return `/series/${slug}${qs ? `?${qs}` : ''}`
  })()
```

   Replace the lone `<PathHeader … />` with:

```jsx
      <div className="flex items-center justify-between gap-3">
        <PathHeader segments={[{ label: 'series', to: '/' }, { label: series.name }]} />
        {user?.is_librarian && (
          <Link to={editHref} className="text-xs text-accent hover:text-accent-hover">{editing ? '[done]' : '[edit]'}</Link>
        )}
      </div>
      {result && <ResultLine key={result.id} correction={result} currentSlug={series.slug} />}
```

   In the header, after the book count line:

```jsx
        {editing && isSeries && !series.dissolved && (
          <div className="flex gap-3 text-xs">
            <button type="button" className="btn-ghost text-xs" onClick={() => setAction({ kind: 'rename' })}>rename series</button>
            <button type="button" className="btn-ghost text-xs" onClick={() => setAction({ kind: 'dissolve' })}>dissolve series</button>
          </div>
        )}
        {series.dissolved && (
          <p className="alert-muted">This series was dissolved; its books have their own pages now.</p>
        )}
```

   Pass `editing={editing && !series.dissolved}`, `isSeries={isSeries}` and `onAction={(name) => setAction({ kind: KIND_OF[name] ?? name, work })}` to each `BookRow`. Hide "Start a Thread" when `series.dissolved`. Before `</main>`:

```jsx
      {action && (
        <LibrarianPanel
          action={{ ...action, series }}
          onClose={() => setAction(null)}
          onDone={(correction) => { setAction(null); setResult(correction) }}
        />
      )}
```

- [ ] **Step 4: Run the tests**

Run: `cd frontend && npx vitest run src/pages/Series.test.jsx src/design/tokens.test.js`
Expected: all pass, including the existing Series tests.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/Series.jsx frontend/src/pages/Series.test.jsx
git commit -m "feat(web): librarian edit mode on the series page"
```

---

### Task 13: The fix log page

**Files:**
- Create: `frontend/src/pages/Librarian.jsx`, `frontend/src/pages/Librarian.test.jsx`
- Modify: `frontend/src/App.jsx`, `frontend/src/components/Navbar.jsx`

**Interfaces:**
- Consumes: `useCorrections`, `useRevertCorrection` (Task 11); `DataTable`, `DiagnosticFloat`, `PathHeader`, `relativeTime` (from `components/Post`), `NotFound`.
- Produces: route `/librarian`; a `librarian` link in the navbar for librarians.

- [ ] **Step 1: Failing tests**

`frontend/src/pages/Librarian.test.jsx`:

```jsx
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

vi.mock('../api/client', () => ({ default: { get: vi.fn(), post: vi.fn() } }))

import client from '../api/client'
import useAuthStore from '../store/auth'
import Librarian from './Librarian'

const ROWS = [
  { id: 'c2', op: 'set_series', subject: 'Iron Gold', room_slug: 'red-rising', reason: 'book four', user: 'ada',
    created_at: new Date().toISOString(), exportable: true, runtime_only_reason: null, undoable: true, reverted_at: null },
  { id: 'c1', op: 'merge_works', subject: 'Dune', room_slug: 'dune', reason: 'dup', user: 'ada',
    created_at: new Date().toISOString(), exportable: false, runtime_only_reason: 'Dune has no Open Library id',
    undoable: false, reverted_at: null },
]

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}><MemoryRouter><Librarian /></MemoryRouter></QueryClientProvider>,
  )
}

beforeEach(() => {
  vi.clearAllMocks()
  client.get.mockResolvedValue({ data: ROWS })
})

describe('Librarian log', () => {
  it('is a 404 for readers', () => {
    useAuthStore.setState({ token: 't', user: { id: 'u', username: 'reader' } })
    renderPage()
    expect(screen.getByText(/not found/i)).toBeInTheDocument()
    expect(client.get).not.toHaveBeenCalled()
  })

  it('lists fixes with export status, links and undo', async () => {
    useAuthStore.setState({ token: 't', user: { id: 'u', username: 'ada', is_librarian: true } })
    client.post.mockResolvedValue({ data: { ...ROWS[0], undoable: false, reverted_at: new Date().toISOString() } })
    renderPage()
    expect(await screen.findByRole('link', { name: 'Iron Gold' })).toHaveAttribute('href', '/series/red-rising')
    expect(screen.getByText('exported')).toBeInTheDocument()
    expect(screen.getByText('runtime-only')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'undo Iron Gold' }))
    expect(client.post).toHaveBeenCalledWith('/librarian/corrections/c2/revert')
  })

  it('filters to runtime-only fixes', async () => {
    useAuthStore.setState({ token: 't', user: { id: 'u', username: 'ada', is_librarian: true } })
    renderPage()
    await screen.findByRole('link', { name: 'Iron Gold' })
    await userEvent.click(screen.getByRole('button', { name: 'runtime-only only' }))
    expect(client.get).toHaveBeenLastCalledWith('/librarian/corrections', { params: { runtime_only: true } })
  })
})
```

`NotFound.jsx` renders an `sr-only` "Page not found" heading, which `/not found/i` matches.

- [ ] **Step 2: Run to verify failure**

Run: `cd frontend && npx vitest run src/pages/Librarian.test.jsx`
Expected: fails to resolve `./Librarian`.

- [ ] **Step 3: Implement**

`frontend/src/pages/Librarian.jsx`:

```jsx
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useCorrections, useRevertCorrection } from '../api/librarian'
import DataTable from '../components/DataTable'
import DiagnosticFloat from '../components/DiagnosticFloat'
import PathHeader from '../components/PathHeader'
import { relativeTime } from '../components/Post'
import { useStatusBar } from '../store/status'
import useAuthStore from '../store/auth'
import NotFound from './NotFound'

/** The log of catalog fixes: what, why, who, whether it exports, and undo. */
function Log() {
  const [runtimeOnly, setRuntimeOnly] = useState(false)
  const { data: rows = [], isLoading } = useCorrections({ runtimeOnly })
  const revert = useRevertCorrection()
  useStatusBar({ mode: 'LIBRARIAN', path: '~/librarian', facts: [`${rows.length} fixes`] })

  const columns = [
    { key: 'created_at', label: 'Age', align: 'right', width: 6,
      render: (r) => <span className="text-ink-dim tabular-nums">{relativeTime(r.created_at)}</span> },
    { key: 'op', label: 'Op', width: 18, render: (r) => <span className="text-ink-dim">{r.op}</span> },
    { key: 'subject', label: 'Subject',
      render: (r) => r.room_slug
        ? <Link to={`/series/${r.room_slug}`} className="font-serif text-ink hover:text-accent">{r.subject}</Link>
        : <span className="font-serif text-ink-dim">{r.subject}</span> },
    { key: 'reason', label: 'Why', render: (r) => <span className="text-ink">{r.reason}</span> },
    { key: 'user', label: 'By', width: 12, render: (r) => <span className="text-user">{r.user}</span> },
    { key: 'export', label: 'Export', width: 14,
      render: (r) => r.exportable
        ? <span className="text-ok">exported</span>
        : <DiagnosticFloat severity="warn" message={r.runtime_only_reason}><span className="text-warning">runtime-only</span></DiagnosticFloat> },
    { key: 'undo', label: '', width: 6,
      render: (r) => r.reverted_at ? <span className="text-ink-dim">undone</span> : r.undoable && (
        <button type="button" className="btn-ghost text-xs" aria-label={`undo ${r.subject}`}
                disabled={revert.isPending} onClick={() => revert.mutate(r.id)}>undo</button>
      ) },
  ]

  return (
    <main className="max-w-shell mx-auto px-4 py-6 flex flex-col gap-6">
      <PathHeader segments={[{ label: 'librarian' }]} />
      <div className="flex items-center justify-between">
        <h1 className="text-sm uppercase tracking-eyebrow text-ink">Catalog fixes</h1>
        <button type="button" aria-pressed={runtimeOnly} onClick={() => setRuntimeOnly((v) => !v)}
                className={`text-xs ${runtimeOnly ? 'text-accent underline underline-offset-4' : 'text-ink-dim hover:text-accent'}`}>
          runtime-only only
        </button>
      </div>
      {isLoading
        ? <div className="h-8 border border-line bg-panel animate-pulse" />
        : <DataTable columns={columns} rows={rows} caption="Catalog fixes" emptyMessage="No fixes yet." />}
    </main>
  )
}

function Librarian() {
  const user = useAuthStore((s) => s.user)
  return user?.is_librarian ? <Log /> : <NotFound />
}

export default Librarian
```

`frontend/src/App.jsx`: add `const Librarian = React.lazy(() => import('./pages/Librarian'))` and `<Route path="/librarian" element={<Librarian />} />` before the `*` route.

`frontend/src/components/Navbar.jsx`: for `user?.is_librarian`, add a link to `/librarian` labelled `librarian`, placed before the profile link and styled like the navbar's other text links (`text-sm text-ink-dim hover:text-ink transition-colors duration-fast`).

- [ ] **Step 4: Run the tests**

Run: `cd frontend && npm test`
Expected: the whole unit suite passes (Navbar tests included).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/Librarian.jsx frontend/src/pages/Librarian.test.jsx frontend/src/App.jsx frontend/src/components/Navbar.jsx
git commit -m "feat(web): librarian fix log with export status and undo"
```

---

### Task 14: End-to-end: move a book and undo it

**Files:**
- Create: `frontend/e2e/librarian.spec.js`
- Modify: `frontend/e2e/helpers.js`

**Interfaces:**
- Consumes: the whole stack; `scripts.grant_librarian` run through `docker compose exec`.
- Produces: `grantLibrarian(user)` in `e2e/helpers.js`.

- [ ] **Step 1: Helper**

Append to `frontend/e2e/helpers.js`:

```js
import { execSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'
import path from 'node:path'

const REPO = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..')

// Librarians are granted from a shell (spec §3); e2e does the same through compose.
export function grantLibrarian(user) {
  execSync(`docker compose exec -T backend python -m scripts.grant_librarian ${user.username}`, {
    cwd: REPO, stdio: 'pipe',
  })
}
```

(Move the new imports to the top of the file next to the existing `import { expect } from '@playwright/test'`.)

- [ ] **Step 2: The spec**

`frontend/e2e/librarian.spec.js`:

```js
import { test, expect } from '@playwright/test'
import { grantLibrarian, openFirstSearchResult, registerViaUi } from './helpers'

// A librarian moves a book into a new series, lands on the new room, sees the
// book there, and undoes the move. Needs the full stack and live Open Library.
test('a librarian moves a book into a new series and undoes it', async ({ page }) => {
  const user = await registerViaUi(page)
  grantLibrarian(user)
  await page.reload() // useMe refreshes the stored user, now a librarian

  await openFirstSearchResult(page, 'the left hand of darkness')
  await page.getByRole('link', { name: '[edit]' }).click()
  const books = page.getByRole('list', { name: 'Books in this series' })
  const title = await books.getByRole('heading').first().textContent()

  await books.getByRole('button', { name: `move ${title}` }).click()
  const saga = `E2E Saga ${Date.now()}`
  await page.getByLabel('Find a series').fill(saga)
  await page.getByRole('radio', { name: `new series: ${saga}` }).check()
  await page.getByLabel('Reason').fill('e2e: checking the move flow')
  await page.getByRole('button', { name: 'Move', exact: true }).click()

  const status = page.getByRole('status')
  await expect(status).toBeVisible()
  await status.getByRole('link', { name: /go to its page/ }).click()
  await expect(page.getByRole('heading', { level: 1, name: saga })).toBeVisible()
  await expect(books.getByRole('heading', { name: title })).toBeVisible()

  await page.getByRole('status').getByRole('button', { name: 'undo' }).click()
  await expect(page.getByRole('status').getByText('undone')).toBeVisible()
})
```

- [ ] **Step 3: Run it**

Run (stack up in another terminal via `docker compose up --build`, then from `frontend/`): `npm run test:e2e -- librarian.spec.js`
Expected: 1 passed. If search returns a series rather than a singleton, the flow still holds, because the test moves whichever book is listed first.

- [ ] **Step 4: Commit**

```bash
git add frontend/e2e/librarian.spec.js frontend/e2e/helpers.js
git commit -m "test(e2e): a librarian moves a book into a new series and undoes it"
```

---

### Task 15: Docs

**Files:**
- Modify: `CLAUDE.md`, `README.md`, `ROADMAP.md`, `TODO.md`

- [ ] **Step 1: Write them**

- `CLAUDE.md`, backend architecture: add `services/librarian/` to the services list. It is the only writer of `catalog_corrections`, and each op records its override entries and undo snapshot in the op's own transaction. `override` is a *list* because a move exports its `remove_from_series` entries before its `set_series`. Under **Series**, add: "`assign_series` also leaves a work alone while it has an unreverted `set_series`/`remove_from_series` correction; a dissolved series (`dissolved_at`) is never chosen and takes no threads." Replace the Known-gaps bullet "No admin merge/split UI" with: "Librarian tools cover merge/split/move/reorder/rename/remove/dissolve in-app; `python -m scripts.export_overrides` writes them to `pipeline/overrides/z-librarian.yaml`, which a person reviews and commits. Librarians are granted with `python -m scripts.grant_librarian`."
- `README.md`: add both scripts to the Maintenance scripts table, the `/api/librarian/*` routes to Key API routes, and `CatalogCorrection` to Core data models. Remove the "No in-app catalog fixes" known gap.
- `ROADMAP.md`: mark **Librarian tools** ✅ with the files touched.
- `TODO.md`: tick **Librarian tools**, and link the plan.

- [ ] **Step 2: Verify everything, then commit**

Run the full backend suite with the pipeline mounted: `PYTEST -q -p no:warnings`. Then `cd frontend && npm test && npm run build`, and `cd pipeline && .venv/bin/python -m pytest -q`.
Expected: all green.

```bash
git add CLAUDE.md README.md ROADMAP.md TODO.md
git commit -m "docs: librarian tools"
```
