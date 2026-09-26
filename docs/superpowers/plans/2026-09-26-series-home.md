# Series as the Book's Only Page — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every work belongs to a series (of one where it must); search cards carry their series and open the series page, which lists its books with only a shelf control, one description, and the whole series' discussion filterable by book. The work page is retired.

**Architecture:** A new `series` table sits above `works`. Detection is pure string work over Open Library subject tags (`services/series_identity.py`); `services/series.py` owns every write to `series` (get-or-create, singleton-to-series promotion, absorption on `merge_works`). Threads gain `series_id` (the room) and keep `work_id` as an optional book tag. A new `/api/series` router serves the page; the React `Series` page replaces `Work`, and `/works/:id` URLs become redirects.

**Tech Stack:** FastAPI, async SQLAlchemy 2.0, Alembic, Pydantic v2, pytest + respx; React 18, React Router, React Query, Tailwind, Vitest + RTL, Playwright.

**Spec:** `docs/superpowers/specs/2026-09-24-series-as-discussion-home-design.md` — slices 1, 3 and 4 as amended 2026-09-26 (Surfaces, API). Slice 2 (edition family, `blurb.py`, `preferred_publisher`) is **not** in this plan.

## Global Constraints

- Everything async; DB via `Depends(get_db)`; never `model_validate` an ORM object whose schema has a relationship field — build schemas explicitly from scalar columns (MissingGreenlet).
- Models are imported through `app.models` (its `__init__` must import `Series`).
- Services contain no FastAPI types. `services/series_identity.py` is pure: no I/O, no DB.
- Enum types added in a migration must be dropped explicitly in `downgrade()` with `sa.Enum(name=...).drop(op.get_bind(), checkfirst=True)`.
- New routers are `include_router(..., prefix="/api")` in `main.py`.
- Tests never touch the network: Google and Open Library are mocked with `respx`. Seeded works that a series page will render set `enriched_at` or mock Google.
- Frontend: tokens only (no raw `zinc-*`, hex, arbitrary colours); serif only for book titles; no new radii, shadows, font sizes or durations (`duration-fast`/`duration-base` only); measure in `ch` (`max-w-prose`, `max-w-table`, `max-w-shell`); `ink-muted` never for text, `ink-faint` only for `aria-hidden` glyphs; `path` colour = references; filled controls are `bg-accent text-bg`.
- Literal glyphs are limited to tree elbows, sort carets (`▾`/`▴`) and the float marker (`■`), all `aria-hidden`. **The spec's `⊂ ⟨series⟩` search tag is therefore rendered as text: `series` (ink-dim) followed by the name (path).** Task 11 corrects the spec line.
- No star ratings, no reviews. Series position ("book 3 of 6") is out of scope — order is `first_publish_year`, then title.
- Frontend components consume React Query hooks from `src/api/`, never `client` directly; errors go through `errorMessage()`.

## Review Focus

1. **Two series (or two singletons) with the same name** — "Dune" is three different Brian Herbert books. Each needs its own page; the second must get a distinct slug, never a 500 on the unique index. → Task 3 `test_unique_slug_suffixes_on_collision`, Task 2 `test_two_singletons_with_the_same_title_get_distinct_slugs`.
2. **A bookmarked singleton URL after its book is promoted into a real series** — the old slug must still open the page (the survivor's), not 404. → Task 3 `test_get_series_by_slug_follows_a_tombstone`, Task 7 `test_series_endpoint_answers_a_tombstoned_slug_with_the_survivor`, Task 9 `redirects when the API answers with a different slug`.
3. **Tagging a thread with a book outside the series** (stale tab, crafted request, or a merged-away work id of a member) — foreign book → 422; a tombstone of a member → accepted and canonicalized. → Task 7 `test_create_series_thread_rejects_a_book_from_another_series`, `test_create_series_thread_canonicalizes_a_merged_book_id`.
4. **Threads on a singleton when it is promoted** — they must land in the series room, tagged to that book so the book filter still finds them. → Task 3 `test_promotion_carries_threads_and_tags_untagged_ones`.
5. **`?book=` naming a work that is not on the page** (stale link, merged work) — the page renders normally with nothing highlighted, no crash. → Task 9 `ignores a ?book= that is not a member`.

---

## File Structure

**Backend — create**
- `backend/app/services/series_identity.py` — pure tag parsing, container choice, slug and key rules.
- `backend/app/models/series.py` — `Series`, `SeriesSource`, `SeriesKind`.
- `backend/app/services/series.py` — every write to `series`; the singleton-on-flush listener.
- `backend/app/services/threads.py` — shared thread listing query and creation.
- `backend/app/schemas/series.py` — `SeriesRef`, `SeriesWorkOut`, `SeriesOut`, `SeriesThreadCreate`.
- `backend/app/api/series.py` — `/api/series` router.
- `backend/scripts/backfill_series.py` — one-shot, idempotent backfill.
- `backend/alembic/versions/e7b3c9d2a1f4_add_series.py` — Migration A.
- `backend/alembic/versions/f8c4d0e3b2a5_require_work_series.py` — Migration B.
- Tests: `tests/test_series_identity.py`, `tests/test_series_model.py`, `tests/test_series_service.py`, `tests/test_backfill_series.py`, `tests/test_series_api.py`.

**Backend — modify**
- `app/models/work.py`, `app/models/thread.py`, `app/models/__init__.py`
- `app/services/works.py` (subjects storage, series on ingest, `merge_works`, `WorkPresentation`)
- `app/services/open_library.py` (`fetch_work_subjects`)
- `app/schemas/book.py` (`WorkOut.series`), `app/schemas/thread.py` (`ThreadOut.series_id`)
- `app/api/works.py` (drop enrichment on GET and the `/threads` listing), `app/api/threads.py`, `app/api/genres.py`, `app/main.py`
- `scripts/backfill_covers.py` (subjects separator)
- Tests: `test_votes.py`, `test_pagination.py`, `test_threads.py`, `test_work_resolution.py`, `test_resolve_works_script.py`, `test_enrichment.py`, `test_works.py`, `test_open_library.py`

**Frontend — create**
- `src/api/series.js`, `src/pages/Series.jsx`, `src/pages/Series.test.jsx`, `src/pages/WorkRedirect.jsx`, `src/pages/WorkRedirect.test.jsx`, `e2e/series.spec.js`

**Frontend — modify / delete**
- `src/api/works.js`, `src/api/threads.js`, `src/components/WorkCard.jsx` (+ test), `src/components/ThreadModal.jsx` (+ test), `src/pages/Thread.jsx`, `src/App.jsx`, `e2e/helpers.js`, `e2e/search.spec.js`
- Delete `src/pages/Work.jsx`.

**Docs:** `CLAUDE.md`, the spec (glyph line).

---

### Task 1: Pure series identity rules

**Files:**
- Create: `backend/app/services/series_identity.py`
- Test: `backend/tests/test_series_identity.py`

**Interfaces:**
- Produces:
  - `SUBJECT_SEPARATOR: str = "\n"`
  - `join_subjects(subjects: Sequence[str]) -> str | None`
  - `SeriesTags(NamedTuple)`: `franchises: tuple[str, ...]`, `series: tuple[str, ...]` — each element a normalized tag `"franchise:Red Rising"` / `"series:Red Rising Saga"`.
  - `parse_tags(subjects: str | None) -> SeriesTags`
  - `choose_container(tags: SeriesTags, counts: Mapping[str, int]) -> str | None`
  - `tag_name(tag: str) -> str` — `"series:Red Rising Saga"` → `"Red Rising Saga"`
  - `tag_external_id(tag: str) -> str` — `"series:red rising saga"` (prefix + `series_key(name)`)
  - `series_key(name: str) -> str` — lowercase, depunctuated, whitespace-collapsed
  - `slugify(name: str, max_length: int = 80) -> str` — never empty (falls back to `"series"`)

- [ ] **Step 1: Write the failing tests**

```python
"""Series detection is pure string work over Open Library subject tags."""

import pytest

from app.services.series_identity import (
    SeriesTags,
    choose_container,
    join_subjects,
    parse_tags,
    series_key,
    slugify,
    tag_external_id,
    tag_name,
)

RED_RISING = join_subjects(
    [
        "Science fiction",
        "franchise:Red Rising",
        "series:Red Rising Trilogy",
        "series:Red Rising Saga",
        "form:novel",
    ]
)


def test_join_subjects_keeps_tag_boundaries():
    assert join_subjects(["a b", "series:X Y"]) == "a b\nseries:X Y"
    assert join_subjects([]) is None


def test_parse_tags_reads_franchise_and_series_lines():
    assert parse_tags(RED_RISING) == SeriesTags(
        franchises=("franchise:Red Rising",),
        series=("series:Red Rising Trilogy", "series:Red Rising Saga"),
    )


@pytest.mark.parametrize(
    "subjects, expected",
    [
        (None, SeriesTags((), ())),
        ("", SeriesTags((), ())),
        ("Fiction\nFantasy", SeriesTags((), ())),
        # Underscored and oddly spaced forms normalize to one tag.
        ("series:Red_Rising_Saga", SeriesTags((), ("series:Red Rising Saga",))),
        ("SERIES:  Mistborn  ", SeriesTags((), ("series:Mistborn",))),
        # Duplicates collapse, order preserved.
        ("series:A\nseries:A\nseries:B", SeriesTags((), ("series:A", "series:B"))),
        # Empty names are not tags.
        ("series:\nfranchise: ", SeriesTags((), ())),
        # A legacy space-joined blob is one line with several tags in it: a tag
        # name never contains ':', so the line is ignored rather than misread.
        (
            "franchise:Red Rising series:Red Rising Trilogy genre:science fiction",
            SeriesTags((), ()),
        ),
    ],
)
def test_parse_tags_table(subjects, expected):
    assert parse_tags(subjects) == expected


def test_franchise_wins_over_series():
    assert choose_container(parse_tags(RED_RISING), {}) == "franchise:Red Rising"


def test_several_franchises_pick_by_name():
    tags = SeriesTags(("franchise:Zeta", "franchise:Alpha"), ())
    assert choose_container(tags, {}) == "franchise:Alpha"


def test_broadest_series_wins_without_a_franchise():
    tags = SeriesTags((), ("series:Red Rising Trilogy", "series:Red Rising Saga"))
    counts = {"series:Red Rising Trilogy": 3, "series:Red Rising Saga": 6}
    assert choose_container(tags, counts) == "series:Red Rising Saga"


def test_series_tie_breaks_on_name():
    tags = SeriesTags((), ("series:Beta", "series:Alpha"))
    assert choose_container(tags, {"series:Beta": 2, "series:Alpha": 2}) == "series:Alpha"
    # Missing counts are zero, still a tie.
    assert choose_container(tags, {}) == "series:Alpha"


def test_no_tags_means_no_container():
    assert choose_container(SeriesTags((), ()), {}) is None


def test_tag_name_and_external_id():
    assert tag_name("series:Red Rising Saga") == "Red Rising Saga"
    assert tag_external_id("series:Red Rising Saga") == "series:red rising saga"
    assert tag_external_id("franchise:Red  Rising!") == "franchise:red rising"


@pytest.mark.parametrize(
    "name, slug",
    [
        ("Red Rising", "red-rising"),
        ("The Hitchhiker's Guide to the Galaxy", "the-hitchhikers-guide-to-the-galaxy"),
        ("Café Society", "cafe-society"),
        ("  --Dune--  ", "dune"),
        ("Кровь", "series"),  # nothing ASCII survives: never an empty slug
        ("", "series"),
    ],
)
def test_slugify_table(name, slug):
    assert slugify(name) == slug


def test_slugify_caps_length_on_a_word_boundary():
    got = slugify("word " * 40, max_length=12)
    assert got == "word-word"
    assert len(got) <= 12


def test_series_key_normalizes():
    assert series_key("The Red-Rising  Saga!") == "the red rising saga"
```

- [ ] **Step 2: Run to verify it fails**

Run (from `backend/`): `DATABASE_URL=postgresql+asyncpg://margin:margin@localhost:5432/margin_test pytest tests/test_series_identity.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.series_identity'`.

- [ ] **Step 3: Implement**

```python
"""Series detection rules: pure string work over Open Library subject tags.

Open Library already carries the hierarchy a series page needs, in rows we
store: ``franchise:Red Rising`` spans the whole saga, ``series:Red Rising
Trilogy`` a run inside it. No I/O here — the same shape and the same reason as
``work_identity.py``: these rules decide which room a conversation lives in, so
they are tested as a table.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Mapping, NamedTuple, Sequence

# Subjects are stored one per line. They used to be space-joined, which erased
# the boundary between "franchise:Red Rising" and the next subject.
SUBJECT_SEPARATOR = "\n"

_PREFIXES = ("franchise", "series")
_NON_WORD = re.compile(r"[^\w\s]", re.UNICODE)
_SPACE = re.compile(r"\s+")


class SeriesTags(NamedTuple):
    franchises: tuple[str, ...]
    series: tuple[str, ...]


def join_subjects(subjects: Sequence[str]) -> str | None:
    return SUBJECT_SEPARATOR.join(subjects) or None


def _clean_name(raw: str) -> str:
    return _SPACE.sub(" ", raw.replace("_", " ")).strip()


def parse_tags(subjects: str | None) -> SeriesTags:
    """Pull franchise and series tags out of a stored subject blob.

    A tag name never contains ':'. A line that does is a legacy space-joined
    blob holding several tags, and guessing where one ends would put books in
    the wrong room — so it is ignored and the work stays a singleton until the
    backfill re-fetches its subjects.
    """
    found: dict[str, list[str]] = {p: [] for p in _PREFIXES}
    for line in (subjects or "").split(SUBJECT_SEPARATOR):
        prefix, sep, rest = line.strip().partition(":")
        prefix = prefix.lower()
        if not sep or prefix not in found or ":" in rest:
            continue
        name = _clean_name(rest)
        tag = f"{prefix}:{name}"
        if name and tag not in found[prefix]:
            found[prefix].append(tag)
    return SeriesTags(tuple(found["franchise"]), tuple(found["series"]))


def choose_container(tags: SeriesTags, counts: Mapping[str, int]) -> str | None:
    """The tag whose series becomes the work's room.

    A franchise is the whole saga, so it wins outright. Otherwise the series
    tag shared by the most works in the catalog wins — the broadest grouping is
    the one-room goal — with the name as a deterministic tiebreak.
    """
    if tags.franchises:
        return min(tags.franchises)
    if tags.series:
        return min(tags.series, key=lambda t: (-counts.get(t, 0), t))
    return None


def tag_name(tag: str) -> str:
    return tag.partition(":")[2]


def series_key(name: str) -> str:
    return _SPACE.sub(" ", _NON_WORD.sub(" ", name.lower())).strip()


def tag_external_id(tag: str) -> str:
    """Identity of a tag series: casing and punctuation variants are one series."""
    prefix, _, name = tag.partition(":")
    return f"{prefix}:{series_key(name)}"


def slugify(name: str, max_length: int = 80) -> str:
    ascii_name = (
        unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    )
    cleaned = re.sub(r"[^a-z0-9]+", "-", ascii_name.lower().replace("'", "")).strip("-")
    if len(cleaned) > max_length:
        window = cleaned[:max_length]
        if cleaned[max_length] != "-" and "-" in window:
            window = window[: window.rindex("-")]
        cleaned = window.strip("-")
    return cleaned or "series"
```

- [ ] **Step 4: Run to verify it passes**

Run: `DATABASE_URL=postgresql+asyncpg://margin:margin@localhost:5432/margin_test pytest tests/test_series_identity.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/series_identity.py backend/tests/test_series_identity.py
git commit -m "feat(api): pure series detection rules over open library tags"
```

---

### Task 2: Series model, columns, singleton-on-flush, Migration A

**Files:**
- Create: `backend/app/models/series.py`, `backend/app/services/series.py` (listener + `singleton_series_for` only in this task), `backend/alembic/versions/e7b3c9d2a1f4_add_series.py`, `backend/tests/test_series_model.py`
- Modify: `backend/app/models/work.py`, `backend/app/models/thread.py`, `backend/app/models/__init__.py`, `backend/app/services/works.py` (import only), `backend/tests/test_votes.py:28`, `backend/tests/test_pagination.py:36`, `backend/tests/test_work_resolution.py:205`, `backend/tests/test_resolve_works_script.py:122`

**Interfaces:**
- Consumes: `slugify`, `series_key` (Task 1).
- Produces:
  - `app.models.Series` with columns `id, source, external_id, name, slug, canonical_key, kind, merged_into_id, created_at, updated_at`; `SeriesSource.{openlibrary, heuristic}`; `SeriesKind.{series, singleton}`.
  - `Work.series_id: UUID` (NOT NULL in the model), `Work.series` relationship.
  - `Thread.series_id: UUID | None`, `Thread.series` relationship; check constraints `ck_threads_one_home`, `ck_threads_tag_needs_series`.
  - `app.services.series.singleton_series_for(work: Work) -> Series`
  - Invariant: any `Work` flushed without a series gets its own singleton.

- [ ] **Step 1: Write the failing tests** — `backend/tests/test_series_model.py`

```python
"""Every work has a series; a thread lives in exactly one room."""

import uuid

import pytest
from sqlalchemy.exc import IntegrityError

from app.models import (
    AuthProvider,
    Series,
    SeriesKind,
    SeriesSource,
    Thread,
    User,
    Work,
    WorkKind,
    WorkProvenance,
    WorkSource,
)


def _work(title="Dune", **kw) -> Work:
    return Work(
        source=WorkSource.openlibrary,
        external_id=f"OL{uuid.uuid4().hex[:8]}W",
        canonical_key=f"{title.lower()}\x1fauthor",
        title=title,
        author="Author",
        kind=WorkKind.single,
        identity_provenance=WorkProvenance.isbn,
        **kw,
    )


async def _user(db):
    u = User(
        email=f"s{uuid.uuid4().hex[:6]}@x.com",
        username=f"s{uuid.uuid4().hex[:6]}",
        password_hash="x",
        auth_provider=AuthProvider.email,
    )
    db.add(u)
    await db.flush()
    return u


async def test_a_work_flushed_without_a_series_gets_its_own_singleton(db_session):
    work = _work("Dune")
    db_session.add(work)
    await db_session.flush()

    series = await db_session.get(Series, work.series_id)
    assert series.kind is SeriesKind.singleton
    assert series.source is SeriesSource.heuristic
    assert series.name == "Dune"
    assert series.external_id == f"singleton:{work.id}"
    assert series.slug.startswith("dune-")


async def test_two_singletons_with_the_same_title_get_distinct_slugs(db_session):
    a, b = _work("Dune"), _work("Dune")
    db_session.add_all([a, b])
    await db_session.flush()
    sa = await db_session.get(Series, a.series_id)
    sb = await db_session.get(Series, b.series_id)
    assert sa.slug != sb.slug


async def test_a_work_given_a_series_keeps_it(db_session):
    series = Series(
        source=SeriesSource.openlibrary,
        external_id="franchise:red rising",
        name="Red Rising",
        slug="red-rising",
        canonical_key="red rising",
        kind=SeriesKind.series,
    )
    db_session.add(series)
    await db_session.flush()
    work = _work("Golden Son", series_id=series.id)
    db_session.add(work)
    await db_session.flush()
    assert work.series_id == series.id
    assert (await db_session.get(Series, work.series_id)).kind is SeriesKind.series


async def test_a_thread_needs_exactly_one_home(db_session):
    user = await _user(db_session)
    db_session.add(Thread(title="Homeless", user_id=user.id))
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_a_book_tag_needs_a_series(db_session, genre):
    work = _work()
    db_session.add(work)
    await db_session.flush()
    user = await _user(db_session)
    db_session.add(Thread(title="Tag in a genre", user_id=user.id, genre_id=genre.id, work_id=work.id))
    with pytest.raises(IntegrityError):
        await db_session.flush()
```

Check whether a `genre` fixture exists (`grep -n "def genre" backend/tests/*.py`). `test_pagination.py` defines one locally; if it is not in `conftest.py`, move it there unchanged so both files share it.

- [ ] **Step 2: Run to verify it fails**

Run: `DATABASE_URL=postgresql+asyncpg://margin:margin@localhost:5432/margin_test pytest tests/test_series_model.py -v`
Expected: FAIL — `ImportError: cannot import name 'Series' from 'app.models'`.

- [ ] **Step 3: Implement the model** — `backend/app/models/series.py`

```python
import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, String, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class SeriesSource(str, enum.Enum):
    """Where the grouping came from: an Open Library tag, or nothing (a singleton)."""

    openlibrary = "openlibrary"
    heuristic = "heuristic"


class SeriesKind(str, enum.Enum):
    series = "series"
    # A series of one. It exists so every book has exactly one room and one page
    # template; the page shows no series chrome for it.
    singleton = "singleton"


class Series(Base):
    """The discussion home: one room per saga, as r/redrising.

    Mirrors ``works`` on purpose — ``canonical_key`` for recognising the same
    series later, ``merged_into_id`` as a tombstone so a promoted singleton's
    URL keeps resolving.
    """

    __tablename__ = "series"
    __table_args__ = (
        UniqueConstraint("source", "external_id", name="uq_series_source_external_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()")
    )
    source: Mapped[SeriesSource] = mapped_column(
        Enum(SeriesSource, name="series_source_enum"), nullable=False
    )
    # The normalized tag ("franchise:red rising") or "singleton:<work id>".
    external_id: Mapped[str] = mapped_column(String(255), nullable=False)
    name: Mapped[str] = mapped_column(String(500), nullable=False)
    slug: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    canonical_key: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    kind: Mapped[SeriesKind] = mapped_column(
        Enum(SeriesKind, name="series_kind_enum"), nullable=False
    )
    merged_into_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("series.id", ondelete="SET NULL"), nullable=True, index=True
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

    works: Mapped[list["Work"]] = relationship(  # noqa: F821
        "Work", back_populates="series", foreign_keys="Work.series_id"
    )
    threads: Mapped[list["Thread"]] = relationship("Thread", back_populates="series")  # noqa: F821
```

In `backend/app/models/work.py`, after `genre_id`, add:

```python
    # The book's room. Every work has one — a singleton of its own when no
    # series is known — so a work page, a search card and a thread all resolve
    # to exactly one place. `services/series.py` fills it on flush.
    series_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("series.id"), nullable=False, index=True
    )
```

and among the relationships:

```python
    series: Mapped["Series"] = relationship(  # noqa: F821
        "Series", back_populates="works", foreign_keys=[series_id]
    )
```

In `backend/app/models/thread.py`, change the imports to
`from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String, text`, and add to the class:

```python
    __table_args__ = (
        # A thread lives in a series room or a genre room, never both, never
        # neither. The migration adds these NOT VALID: ten legacy threads
        # orphaned by the works migration have no home at all.
        CheckConstraint(
            "(series_id IS NOT NULL) <> (genre_id IS NOT NULL)", name="ck_threads_one_home"
        ),
        # work_id is the optional book tag inside a series room.
        CheckConstraint(
            "work_id IS NULL OR series_id IS NOT NULL", name="ck_threads_tag_needs_series"
        ),
    )
```

and, after `user_id`:

```python
    series_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("series.id", ondelete="CASCADE"), nullable=True, index=True
    )
```

plus the relationship `series: Mapped["Series | None"] = relationship("Series", back_populates="threads")  # noqa: F821`. Leave the `work_id` column as is, but add this comment above it: `# The optional book tag: which book of the series this thread is about.`

In `backend/app/models/__init__.py`, add `from app.models.series import Series, SeriesKind, SeriesSource` and list the three names in `__all__`.

- [ ] **Step 4: Implement the listener** — `backend/app/services/series.py`

```python
"""Series writes: the only module that inserts or moves ``series`` rows.

A work's room is decided here. Detection rules live in ``series_identity``;
this module applies them against the database.
"""

from __future__ import annotations

import uuid

from sqlalchemy import event
from sqlalchemy.orm import Session

from app.models import Series, SeriesKind, SeriesSource, Work
from app.services.series_identity import series_key, slugify


def singleton_series_for(work: Work) -> Series:
    """A series of one for ``work``.

    The slug carries a short id so it needs no uniqueness query — three
    different books are titled plain "Dune" — which is what lets this run
    inside a flush.
    """
    if work.id is None:
        work.id = uuid.uuid4()
    series_id = uuid.uuid4()
    return Series(
        id=series_id,
        source=SeriesSource.heuristic,
        external_id=f"singleton:{work.id}",
        name=work.title,
        slug=f"{slugify(work.title, max_length=60)}-{series_id.hex[:6]}",
        canonical_key=series_key(work.title),
        kind=SeriesKind.singleton,
    )


@event.listens_for(Session, "before_flush")
def _every_work_has_a_series(session, flush_context, instances) -> None:
    """Give any new work that arrives without a room a singleton of its own.

    This is the column default for a required foreign key that has to create
    its target. Checking ``__dict__`` rather than ``work.series`` avoids
    triggering a relationship load in the middle of a flush.
    """
    for obj in list(session.new):
        if (
            isinstance(obj, Work)
            and obj.series_id is None
            and obj.__dict__.get("series") is None
        ):
            obj.series = singleton_series_for(obj)
```

The listener is registered when this module is imported. In `backend/app/services/works.py`, add `from app.services import series as series_service  # noqa: F401  (registers the singleton listener)` beside the other service imports. Task 3 uses the name, which removes the noqa. Every entry point (the app, the scripts, the tests via `app.main`) reaches `works.py`.

- [ ] **Step 5: Give directly-built test threads their room**

In each of these, add `series_id=<work>.series_id` to the `Thread(...)` call:
- `tests/test_votes.py:28` → `Thread(title="A thread", user_id=user.id, series_id=work.series_id, work_id=work.id)`
- `tests/test_pagination.py:36` → `Thread(title=f"Thread {i}", user_id=user.id, series_id=work.series_id, work_id=work.id)`
- `tests/test_work_resolution.py:205` → `Thread(title="Is Darrow a hero?", user_id=user.id, series_id=source.series_id, work_id=source.id)`
- `tests/test_resolve_works_script.py:122` → `Thread(title="Legacy thread", user_id=user.id, series_id=heuristic.series_id, work_id=heuristic.id)`

- [ ] **Step 6: Write Migration A** — `backend/alembic/versions/e7b3c9d2a1f4_add_series.py`

```python
"""series: the discussion home above works

Revision ID: e7b3c9d2a1f4
Revises: d4e9b21c6f07

Nullable columns only. `scripts.backfill_series` fills them; Migration B
(f8c4d0e3b2a5) then requires works.series_id and adds the thread constraints.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "e7b3c9d2a1f4"
down_revision: Union[str, None] = "d4e9b21c6f07"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "series",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("source", sa.Enum("openlibrary", "heuristic", name="series_source_enum"), nullable=False),
        sa.Column("external_id", sa.String(length=255), nullable=False),
        sa.Column("name", sa.String(length=500), nullable=False),
        sa.Column("slug", sa.String(length=255), nullable=False),
        sa.Column("canonical_key", sa.Text(), nullable=False),
        sa.Column("kind", sa.Enum("series", "singleton", name="series_kind_enum"), nullable=False),
        sa.Column("merged_into_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["merged_into_id"], ["series.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source", "external_id", name="uq_series_source_external_id"),
    )
    op.create_index("ix_series_slug", "series", ["slug"], unique=True)
    op.create_index("ix_series_canonical_key", "series", ["canonical_key"])
    op.create_index("ix_series_merged_into_id", "series", ["merged_into_id"])

    op.add_column("works", sa.Column("series_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key("works_series_id_fkey", "works", "series", ["series_id"], ["id"])
    op.create_index("ix_works_series_id", "works", ["series_id"])

    op.add_column("threads", sa.Column("series_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key(
        "threads_series_id_fkey", "threads", "series", ["series_id"], ["id"], ondelete="CASCADE"
    )
    op.create_index("ix_threads_series_id", "threads", ["series_id"])


def downgrade() -> None:
    op.drop_index("ix_threads_series_id", table_name="threads")
    op.drop_constraint("threads_series_id_fkey", "threads", type_="foreignkey")
    op.drop_column("threads", "series_id")
    op.drop_index("ix_works_series_id", table_name="works")
    op.drop_constraint("works_series_id_fkey", "works", type_="foreignkey")
    op.drop_column("works", "series_id")
    op.drop_index("ix_series_merged_into_id", table_name="series")
    op.drop_index("ix_series_canonical_key", table_name="series")
    op.drop_index("ix_series_slug", table_name="series")
    op.drop_table("series")
    sa.Enum(name="series_kind_enum").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="series_source_enum").drop(op.get_bind(), checkfirst=True)
```

- [ ] **Step 7: Run the new tests and the full suite**

Run: `DATABASE_URL=postgresql+asyncpg://margin:margin@localhost:5432/margin_test pytest -q`
Expected: `test_series_model.py` passes; every pre-existing test still passes. If a test builds `Thread(work_id=...)` without `series_id` and now fails `ck_threads_one_home`, fix it the same way as Step 5.

- [ ] **Step 8: Commit**

```bash
git add backend/app/models backend/app/services/series.py backend/app/services/works.py \
        backend/alembic/versions/e7b3c9d2a1f4_add_series.py backend/tests
git commit -m "feat(api): series table; every work gets a room on flush"
```

---

### Task 3: Series assignment, promotion and absorption

**Files:**
- Modify: `backend/app/services/series.py`, `backend/app/services/works.py:306-359` (`upsert_work_from_ol`), `backend/app/services/works.py:401-444` (`merge_works`), `backend/scripts/backfill_covers.py:56`
- Test: `backend/tests/test_series_service.py`; extend `backend/tests/test_work_resolution.py` merge test

**Interfaces:**
- Consumes: Task 1 (`parse_tags`, `choose_container`, `tag_name`, `tag_external_id`, `series_key`, `slugify`, `join_subjects`); Task 2 (`Series`, `singleton_series_for`).
- Produces (in `app.services.series`):
  - `async canonical_series(db, series: Series) -> Series`: follows `merged_into_id`.
  - `async get_series_by_slug(db, slug: str) -> Series | None`: returns the canonical series.
  - `async unique_slug(db, name: str) -> str`
  - `async series_for_subjects(db, subjects: str | None) -> Series | None`: gets or creates the tag series.
  - `async assign_series(db, work: Work) -> Series`: may promote a singleton.
  - `async absorb_series(db, source: Work, target: Work) -> None`: for `merge_works`, called *before* its thread update.
- Behaviour change: `works.subjects` is stored with `join_subjects` (newline-separated).

- [ ] **Step 1: Write the failing tests** — `backend/tests/test_series_service.py`

```python
"""Assigning works to rooms, and moving rooms when we learn more."""

import uuid

from sqlalchemy import select

from app.models import (
    AuthProvider,
    Series,
    SeriesKind,
    Thread,
    User,
    Work,
    WorkKind,
    WorkProvenance,
    WorkSource,
)
from app.services import series as series_service
from app.services.open_library import OLWork
from app.services.series_identity import join_subjects
from app.services.works import merge_works, upsert_work_from_ol


def _ol(key, title, subjects=(), year=None) -> OLWork:
    return OLWork(
        key=key, title=title, author="Pierce Brown", first_publish_year=year,
        edition_count=1, isbn_13s=frozenset(), subjects=tuple(subjects),
    )


RR_TAGS = ("franchise:Red Rising", "series:Red Rising Trilogy", "series:Red Rising Saga")


async def _user(db):
    u = User(email=f"u{uuid.uuid4().hex[:6]}@x.com", username=f"u{uuid.uuid4().hex[:6]}",
             password_hash="x", auth_provider=AuthProvider.email)
    db.add(u)
    await db.flush()
    return u


async def test_ingest_stores_subjects_one_per_line(db_session):
    work = await upsert_work_from_ol(db_session, _ol("OL1W", "Red Rising", ["Fiction", "series:X"]))
    assert work.subjects == "Fiction\nseries:X"


async def test_franchise_siblings_share_one_room(db_session):
    red = await upsert_work_from_ol(db_session, _ol("OL1W", "Red Rising", RR_TAGS, 2014))
    gold = await upsert_work_from_ol(db_session, _ol("OL2W", "Iron Gold", ["franchise:Red Rising"], 2018))
    assert red.series_id == gold.series_id
    series = await db_session.get(Series, red.series_id)
    assert series.kind is SeriesKind.series
    assert series.name == "Red Rising"
    assert series.slug == "red-rising"


async def test_untagged_ingest_is_a_singleton(db_session):
    work = await upsert_work_from_ol(db_session, _ol("OL3W", "The Hobbit", ["Fantasy"]))
    assert (await db_session.get(Series, work.series_id)).kind is SeriesKind.singleton


async def test_broadest_series_tag_wins(db_session):
    # Two works already carry the Saga tag, one the Trilogy tag.
    await upsert_work_from_ol(db_session, _ol("OL4W", "A", ["series:Saga"]))
    await upsert_work_from_ol(db_session, _ol("OL5W", "B", ["series:Saga"]))
    await upsert_work_from_ol(db_session, _ol("OL6W", "C", ["series:Trilogy"]))
    both = await upsert_work_from_ol(db_session, _ol("OL7W", "D", ["series:Trilogy", "series:Saga"]))
    assert (await db_session.get(Series, both.series_id)).name == "Saga"


async def test_unique_slug_suffixes_on_collision(db_session):
    first = await series_service.series_for_subjects(db_session, "series:Dune")
    second = await series_service.series_for_subjects(db_session, "franchise:Dune")
    assert first.slug == "dune"
    assert second.slug == "dune-2"


async def test_promotion_carries_threads_and_tags_untagged_ones(db_session):
    """A singleton later learns its series: the room moves, nothing is lost."""
    work = await upsert_work_from_ol(db_session, _ol("OL8W", "Golden Son"))
    singleton = await db_session.get(Series, work.series_id)
    user = await _user(db_session)
    thread = Thread(title="Is Mustang right?", user_id=user.id, series_id=singleton.id)
    db_session.add(thread)
    await db_session.flush()

    # Re-ingest with tags, as a later search would.
    await upsert_work_from_ol(db_session, _ol("OL8W", "Golden Son", ["franchise:Red Rising"]))

    await db_session.refresh(thread)
    await db_session.refresh(singleton)
    target = await db_session.get(Series, work.series_id)
    assert target.kind is SeriesKind.series
    assert thread.series_id == target.id
    assert thread.work_id == work.id  # tagged, so the book filter still finds it
    assert singleton.merged_into_id == target.id


async def test_a_book_is_never_moved_between_two_real_series(db_session):
    work = await upsert_work_from_ol(db_session, _ol("OL9W", "X", ["series:First"]))
    first = work.series_id
    await upsert_work_from_ol(db_session, _ol("OL9W", "X", ["franchise:Other"]))
    assert work.series_id == first


async def test_get_series_by_slug_follows_a_tombstone(db_session):
    work = await upsert_work_from_ol(db_session, _ol("OL10W", "Morning Star"))
    old_slug = (await db_session.get(Series, work.series_id)).slug
    await upsert_work_from_ol(db_session, _ol("OL10W", "Morning Star", ["franchise:Red Rising"]))
    found = await series_service.get_series_by_slug(db_session, old_slug)
    assert found.id == work.series_id
    assert found.slug == "red-rising"
    assert await series_service.get_series_by_slug(db_session, "nope") is None


async def test_merge_moves_a_singletons_threads_into_the_targets_room(db_session):
    source = Work(source=WorkSource.heuristic, external_id="h1", canonical_key="red rising\x1fpierce brown",
                  title="Red Rising", author="Pierce Brown", kind=WorkKind.single,
                  identity_provenance=WorkProvenance.heuristic)
    db_session.add(source)
    await db_session.flush()
    source_series = await db_session.get(Series, source.series_id)
    user = await _user(db_session)
    untagged = Thread(title="Untagged", user_id=user.id, series_id=source.series_id)
    db_session.add(untagged)
    await db_session.flush()

    target = await upsert_work_from_ol(db_session, _ol("OL11W", "Red Rising", ["franchise:Red Rising"]))
    # upsert_work_from_ol absorbs the heuristic twin, which calls merge_works.
    await db_session.refresh(untagged)
    await db_session.refresh(source)
    await db_session.refresh(source_series)
    assert untagged.series_id == target.series_id
    assert untagged.work_id == target.id
    assert source.series_id == target.series_id
    assert source_series.merged_into_id == target.series_id
```

In `tests/test_work_resolution.py`, extend the existing merge test (after `assert source.merged_into_id == target.id`) with:

```python
    assert thread.series_id == target.series_id
```

- [ ] **Step 2: Run to verify it fails**

Run: `DATABASE_URL=postgresql+asyncpg://margin:margin@localhost:5432/margin_test pytest tests/test_series_service.py tests/test_work_resolution.py -v`
Expected: FAIL. `series_for_subjects` does not exist yet, and subjects are still space-joined.

- [ ] **Step 3: Implement the service functions.** Append to `backend/app/services/series.py` and extend its imports.

```python
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Series, SeriesKind, SeriesSource, Thread, Work
from app.services.series_identity import (
    choose_container,
    parse_tags,
    series_key,
    slugify,
    tag_external_id,
    tag_name,
)

_MAX_TOMBSTONE_HOPS = 10


async def canonical_series(db: AsyncSession, series: Series) -> Series:
    hops = 0
    while series.merged_into_id is not None and hops < _MAX_TOMBSTONE_HOPS:
        series = await db.get(Series, series.merged_into_id)
        hops += 1
    return series


async def get_series_by_slug(db: AsyncSession, slug: str) -> Series | None:
    found = (
        await db.execute(select(Series).where(Series.slug == slug))
    ).scalar_one_or_none()
    return await canonical_series(db, found) if found is not None else None


async def unique_slug(db: AsyncSession, name: str) -> str:
    base = slugify(name)
    taken = set(
        (
            await db.execute(
                select(Series.slug).where(
                    (Series.slug == base) | Series.slug.like(f"{base}-%")
                )
            )
        ).scalars()
    )
    if base not in taken:
        return base
    n = 2
    while f"{base}-{n}" in taken:
        n += 1
    return f"{base}-{n}"


async def _tag_counts(db: AsyncSession, tags: tuple[str, ...]) -> dict[str, int]:
    """How many live works carry each tag, as its own subject line.

    Spaces in the pattern become LIKE's single-character wildcard so a tag
    stored as ``series:Red_Rising_Saga`` counts the same as the spaced form.
    """
    padded = func.concat("\n", func.coalesce(Work.subjects, ""), "\n")
    counts: dict[str, int] = {}
    for tag in tags:
        escaped = tag.replace("\\", "\\\\").replace("%", "\\%").replace(" ", "_")
        counts[tag] = await db.scalar(
            select(func.count())
            .select_from(Work)
            .where(
                Work.merged_into_id.is_(None),
                padded.ilike(f"%\n{escaped}\n%", escape="\\"),
            )
        ) or 0
    return counts


async def series_for_subjects(db: AsyncSession, subjects: str | None) -> Series | None:
    """The tag series these subjects put a work in, created on first sight."""
    tags = parse_tags(subjects)
    counts = (
        await _tag_counts(db, tags.series)
        if not tags.franchises and len(tags.series) > 1
        else {}
    )
    tag = choose_container(tags, counts)
    if tag is None:
        return None

    external_id = tag_external_id(tag)
    existing = (
        await db.execute(
            select(Series).where(
                Series.source == SeriesSource.openlibrary,
                Series.external_id == external_id,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return await canonical_series(db, existing)

    name = tag_name(tag)
    series = Series(
        source=SeriesSource.openlibrary,
        external_id=external_id,
        name=name,
        slug=await unique_slug(db, name),
        canonical_key=series_key(name),
        kind=SeriesKind.series,
    )
    db.add(series)
    await db.flush()
    return series


async def _promote(db: AsyncSession, work: Work, singleton: Series, target: Series) -> None:
    """Move a singleton's room, and everything in it, into a real series.

    Every thread in a singleton was about its one book, so untagged threads
    are tagged with it on the way in. Without the tag they would sink into
    the series-wide feed and vanish from that book's filter.
    """
    await db.execute(
        update(Thread)
        .where(Thread.series_id == singleton.id, Thread.work_id.is_(None))
        .values(work_id=work.id)
    )
    await db.execute(
        update(Thread).where(Thread.series_id == singleton.id).values(series_id=target.id)
    )
    # Tombstoned works that pointed at the singleton follow too.
    await db.execute(
        update(Work).where(Work.series_id == singleton.id).values(series_id=target.id)
    )
    work.series_id = target.id
    singleton.merged_into_id = target.id
    await db.flush()


async def assign_series(db: AsyncSession, work: Work) -> Series:
    """Put ``work`` in the room its subjects name, promoting a singleton.

    A work already in a real series is never moved to another automatically.
    That would be a merge decision, like OL → OL work merges.
    """
    target = await series_for_subjects(db, work.subjects)
    current = await db.get(Series, work.series_id) if work.series_id else None

    if target is None:
        if current is None:
            current = singleton_series_for(work)
            db.add(current)
            await db.flush()
            work.series_id = current.id
            await db.flush()
        return current
    if current is None:
        work.series_id = target.id
        await db.flush()
        return target
    if current.id == target.id or current.kind is SeriesKind.series:
        return current
    await _promote(db, work, current, target)
    return target


async def absorb_series(db: AsyncSession, source: Work, target: Work) -> None:
    """Carry ``source``'s discussion into ``target``'s room ahead of a work merge.

    Must run before ``merge_works`` rewrites ``Thread.work_id``, because that
    rewrite is how threads tagged to ``source`` are found.
    """
    if source.series_id == target.series_id:
        return
    src = await db.get(Series, source.series_id)
    if src.kind is SeriesKind.singleton:
        await db.execute(
            update(Thread)
            .where(Thread.series_id == src.id, Thread.work_id.is_(None))
            .values(work_id=source.id)
        )
    await db.execute(
        update(Thread).where(Thread.work_id == source.id).values(series_id=target.series_id)
    )
    if src.kind is SeriesKind.singleton:
        await db.execute(
            update(Work).where(Work.series_id == src.id).values(series_id=target.series_id)
        )
        src.merged_into_id = target.series_id
    source.series_id = target.series_id
    await db.flush()
```

- [ ] **Step 4: Wire series detection into ingest and merge** in `backend/app/services/works.py`

Replace the `# noqa: F401` import from Task 2 with `from app.services import series as series_service` and add `from app.services.series_identity import join_subjects`.

In `upsert_work_from_ol`, replace the `if work is None:` block through `work.subjects = ...` with:

```python
    subjects = join_subjects(ol.subjects)

    if work is None:
        # Decide the room before the insert. Otherwise the flush would give the
        # work a throwaway singleton that is promoted and tombstoned a line later.
        series = await series_service.series_for_subjects(db, subjects)
        work = Work(
            source=WorkSource.openlibrary,
            external_id=ol.key,
            canonical_key=key,
            title=ol.title,
            author=author,
            first_publish_year=ol.first_publish_year,
            kind=WorkKind(classify_kind(ol.title)),
            # An OL search hit is an authority's own match for the query, the
            # same standard tier 1 applies to an ISBN lookup.
            identity_provenance=WorkProvenance.isbn,
            subjects=subjects,
            series_id=series.id if series is not None else None,
        )
        db.add(work)
        await db.flush()
        await _absorb_heuristic_twin(db, work)

    # Refreshed on every ingest: popularity drifts upward over time, and a
    # cover can appear on a work that had none.
    work.ol_cover_id = ol.cover_id or work.ol_cover_id
    work.ol_edition_count = ol.edition_count
    work.readinglog_count = ol.readinglog_count
    work.ratings_count = ol.ratings_count
    work.subjects = subjects
    # New tags on a re-ingest can promote a singleton into its series.
    await series_service.assign_series(db, work)
```

In `merge_works`, insert immediately before `await db.execute(update(Book)...`:

```python
    # Threads change rooms before their book tag is rewritten below: the tag
    # is how the ones about `source` are found.
    await series_service.absorb_series(db, source, target)
```

In `backend/scripts/backfill_covers.py:56`, change `" ".join(match.subjects) or work.subjects` to `join_subjects(match.subjects) or work.subjects`, and import `join_subjects` from `app.services.series_identity`.

- [ ] **Step 5: Run the tests**

Run: `DATABASE_URL=postgresql+asyncpg://margin:margin@localhost:5432/margin_test pytest -q`
Expected: all PASS, including `test_search_local.py`. The weight-C subject match still works because `to_tsvector` treats a newline as whitespace. If `test_backfill_covers.py` asserts a space-joined subject string, update that expectation to the newline form.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services backend/scripts/backfill_covers.py backend/tests
git commit -m "feat(api): assign works to series rooms; promote singletons; merge rooms"
```

---

### Task 4: Backfill existing data, Migration B

**Files:**
- Modify: `backend/app/services/open_library.py` (add `fetch_work_subjects`), `backend/tests/test_open_library.py`
- Create: `backend/scripts/backfill_series.py`, `backend/alembic/versions/f8c4d0e3b2a5_require_work_series.py`, `backend/tests/test_backfill_series.py`

**Interfaces:**
- Consumes: `assign_series`, `singleton_series_for` (Tasks 2–3), `canonical_work` (existing, `app.services.works`), `join_subjects`.
- Produces:
  - `async open_library.fetch_work_subjects(key: str) -> tuple[str, ...] | None`. Returns `None` on any failure and never raises.
  - `async scripts.backfill_series.backfill(session, *, fetch: bool = True, commit: bool = True) -> dict[str, int]` with keys `refetched, series, singletons, tombstones, threads, orphans`.

- [ ] **Step 1: Write the failing Open Library test** (append to `tests/test_open_library.py`)

```python
WORK_URL = "https://openlibrary.org/works/OL17076473W.json"


@respx.mock
async def test_fetch_work_subjects_returns_the_tag_list():
    respx.get(WORK_URL).mock(
        return_value=Response(200, json={"subjects": ["franchise:Red Rising", "Fiction"]})
    )
    assert await ol.fetch_work_subjects("OL17076473W") == ("franchise:Red Rising", "Fiction")


@respx.mock
async def test_fetch_work_subjects_survives_failure():
    respx.get(WORK_URL).mock(return_value=Response(503))
    assert await ol.fetch_work_subjects("OL17076473W") is None
```

- [ ] **Step 2: Write the failing backfill tests.** Create `tests/test_backfill_series.py`.

A pre-backfill database has works with `series_id` NULL, which the model forbids. The test simulates it with `ALTER TABLE works ALTER COLUMN series_id DROP NOT NULL` and raw updates.

```python
"""backfill_series gives every existing work and thread a room, idempotently."""

import uuid

import respx
from httpx import Response
from sqlalchemy import select, text

from app.models import (
    AuthProvider, Series, SeriesKind, Thread, User, Work, WorkKind, WorkProvenance, WorkSource,
)
from scripts.backfill_series import backfill


async def _legacy(db, title, subjects=None, external_id=None):
    w = Work(source=WorkSource.openlibrary, external_id=external_id or f"OL{uuid.uuid4().hex[:6]}W",
             canonical_key=f"{title.lower()}\x1fa", title=title, author="A", kind=WorkKind.single,
             identity_provenance=WorkProvenance.isbn, subjects=subjects)
    db.add(w)
    await db.flush()
    return w


async def _strip_series(db):
    """Make the rows look like they predate the series table."""
    await db.execute(text("ALTER TABLE works ALTER COLUMN series_id DROP NOT NULL"))
    await db.execute(text("UPDATE works SET series_id = NULL"))
    await db.execute(text("UPDATE threads SET series_id = NULL"))
    await db.execute(text("ALTER TABLE threads DROP CONSTRAINT ck_threads_one_home"))
    await db.execute(text("ALTER TABLE threads DROP CONSTRAINT ck_threads_tag_needs_series"))
    await db.execute(text("DELETE FROM series"))
    db.expire_all()


@respx.mock
async def test_backfill_assigns_rooms_and_moves_threads(db_session):
    route = respx.get("https://openlibrary.org/works/OLRRW.json").mock(
        return_value=Response(200, json={"subjects": ["franchise:Red Rising", "Fiction"]})
    )
    # Legacy space-joined blob: unparseable until re-fetched.
    red = await _legacy(db_session, "Red Rising", "Fiction franchise:Red Rising", external_id="OLRRW")
    # Already one-per-line: must not be re-fetched (and has no mocked route).
    gold = await _legacy(db_session, "Golden Son", "franchise:Red Rising\nFiction")
    hobbit = await _legacy(db_session, "The Hobbit", None)
    user = User(email="b@x.com", username="bf", password_hash="x", auth_provider=AuthProvider.email)
    db_session.add(user)
    await db_session.flush()
    thread = Thread(title="Legacy", user_id=user.id, series_id=red.series_id, work_id=red.id)
    db_session.add(thread)
    await db_session.flush()
    # Capture ids now: _strip_series expires every object, and touching an
    # expired attribute outside the greenlet raises MissingGreenlet.
    ids = (red.id, gold.id, hobbit.id, thread.id)
    await _strip_series(db_session)

    stats = await backfill(db_session, commit=False)

    assert route.called
    assert stats["refetched"] == 1
    red, gold, hobbit = [await db_session.get(Work, i) for i in ids[:3]]
    thread = await db_session.get(Thread, ids[3])
    assert red.series_id == gold.series_id
    assert (await db_session.get(Series, red.series_id)).kind is SeriesKind.series
    assert (await db_session.get(Series, hobbit.series_id)).kind is SeriesKind.singleton
    assert thread.series_id == red.series_id and thread.work_id == red.id
    assert stats["threads"] == 1


@respx.mock
async def test_backfill_is_idempotent_and_reports_orphans(db_session):
    await _legacy(db_session, "Dune")
    user = User(email="o@x.com", username="orph", password_hash="x", auth_provider=AuthProvider.email)
    db_session.add(user)
    await db_session.flush()
    await _strip_series(db_session)
    await db_session.execute(
        text("INSERT INTO threads (id, title, user_id) VALUES (gen_random_uuid(), 'orphan', :u)"),
        {"u": user.id},
    )

    first = await backfill(db_session, fetch=False, commit=False)
    second = await backfill(db_session, fetch=False, commit=False)

    assert first["orphans"] == second["orphans"] == 1
    assert second["threads"] == 0
    # The second run reuses the singleton rather than minting another.
    assert len((await db_session.execute(select(Series))).scalars().all()) == 1
```

- [ ] **Step 3: Run to verify they fail**

Run: `DATABASE_URL=postgresql+asyncpg://margin:margin@localhost:5432/margin_test pytest tests/test_open_library.py tests/test_backfill_series.py -v`
Expected: FAIL — no `fetch_work_subjects`, no `scripts.backfill_series`.

- [ ] **Step 4: Implement `fetch_work_subjects`** (add to `app/services/open_library.py`)

```python
async def fetch_work_subjects(key: str) -> tuple[str, ...] | None:
    """A work's subject tags from ``/works/{key}.json``, or None on any failure.

    Only the series backfill needs this: rows ingested before subjects were
    stored one per line lost their tag boundaries, and the work record carries
    the same ``franchise:``/``series:`` tags the search index does.
    """
    url = f"{settings.OPEN_LIBRARY_BASE_URL}/works/{key}.json"
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            response = await client.get(url)
            response.raise_for_status()
            body = response.json()
    except (httpx.HTTPStatusError, httpx.RequestError, ValueError):
        return None
    if not isinstance(body, dict):
        return None
    subjects = body.get("subjects")
    if not isinstance(subjects, list):
        return None
    return tuple(s for s in subjects if isinstance(s, str))
```

- [ ] **Step 5: Implement the script.** Create `backend/scripts/backfill_series.py`.

```python
"""Give every existing work a series and every work thread its room.

Run once between the two series migrations:

    alembic upgrade e7b3c9d2a1f4
    python -m scripts.backfill_series
    alembic upgrade head

Idempotent. Needs HTTP only to re-fetch the subjects of the few works whose
tags were stored space-joined, which is why this is a script rather than a
migration. Threads with neither a work nor a genre (orphaned by the works
migration) are reported and left alone; rehoming them is a product decision.
"""

from __future__ import annotations

import asyncio

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal
from app.models import SeriesKind, Thread, Work, WorkSource
from app.services import open_library
from app.services.series import assign_series
from app.services.series_identity import SUBJECT_SEPARATOR, join_subjects
from app.services.works import canonical_work


def _needs_refetch(work: Work) -> bool:
    subjects = (work.subjects or "").lower()
    return (
        work.source is WorkSource.openlibrary
        and SUBJECT_SEPARATOR not in subjects
        and ("series:" in subjects or "franchise:" in subjects)
    )


async def backfill(session: AsyncSession, *, fetch: bool = True, commit: bool = True) -> dict[str, int]:
    stats = dict.fromkeys(("refetched", "series", "singletons", "tombstones", "threads", "orphans"), 0)
    works = (await session.execute(select(Work).order_by(Work.created_at))).scalars().all()
    live = [w for w in works if w.merged_into_id is None]

    if fetch:
        for work in live:
            if _needs_refetch(work):
                subjects = await open_library.fetch_work_subjects(work.external_id)
                if subjects:
                    work.subjects = join_subjects(subjects)
                    stats["refetched"] += 1
        await session.flush()

    for work in live:
        series = await assign_series(session, work)
        stats["series" if series.kind is SeriesKind.series else "singletons"] += 1

    for work in works:
        if work.merged_into_id is not None and work.series_id is None:
            work.series_id = (await canonical_work(session, work)).series_id
            stats["tombstones"] += 1
    await session.flush()

    result = await session.execute(
        update(Thread)
        .where(Thread.series_id.is_(None), Thread.work_id.is_not(None))
        .values(
            series_id=select(Work.series_id).where(Work.id == Thread.work_id).scalar_subquery()
        )
        .execution_options(synchronize_session=False)
    )
    stats["threads"] = result.rowcount or 0
    stats["orphans"] = await session.scalar(
        select(func.count()).select_from(Thread).where(
            Thread.series_id.is_(None), Thread.genre_id.is_(None)
        )
    ) or 0

    if commit:
        await session.commit()
    return stats


async def main() -> None:
    async with AsyncSessionLocal() as session:
        stats = await backfill(session)
    print(stats)


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 6: Write Migration B** — `backend/alembic/versions/f8c4d0e3b2a5_require_work_series.py`

```python
"""require works.series_id; constrain a thread's home

Revision ID: f8c4d0e3b2a5
Revises: e7b3c9d2a1f4

Refuses to run until `python -m scripts.backfill_series` has given every work
a series. The same guard the works migration uses against unresolved editions.
The thread constraints are NOT VALID: ten legacy threads have no home at all,
and the constraint must still hold for every row written from now on.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f8c4d0e3b2a5"
down_revision: Union[str, None] = "e7b3c9d2a1f4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM works WHERE series_id IS NULL) THEN
                RAISE EXCEPTION
                    'works without a series remain; run python -m scripts.backfill_series first';
            END IF;
        END $$;
        """
    )
    op.alter_column("works", "series_id", existing_type=sa.UUID(), nullable=False)
    op.execute(
        "ALTER TABLE threads ADD CONSTRAINT ck_threads_one_home "
        "CHECK ((series_id IS NOT NULL) <> (genre_id IS NOT NULL)) NOT VALID"
    )
    op.execute(
        "ALTER TABLE threads ADD CONSTRAINT ck_threads_tag_needs_series "
        "CHECK (work_id IS NULL OR series_id IS NOT NULL) NOT VALID"
    )


def downgrade() -> None:
    op.drop_constraint("ck_threads_tag_needs_series", "threads", type_="check")
    op.drop_constraint("ck_threads_one_home", "threads", type_="check")
    op.alter_column("works", "series_id", existing_type=sa.UUID(), nullable=True)
```

- [ ] **Step 7: Run the tests, then do a round-trip on the dev database**

Run: `DATABASE_URL=postgresql+asyncpg://margin:margin@localhost:5432/margin_test pytest -q`
Expected: all PASS.

Then, with `docker compose up -d db backend`:

```bash
docker compose exec backend alembic upgrade e7b3c9d2a1f4
docker compose exec backend alembic upgrade head        # expect: RAISE 'works without a series remain'
docker compose exec backend python -m scripts.backfill_series   # prints stats; orphans == 10
docker compose exec backend alembic upgrade head        # succeeds
docker compose exec backend alembic downgrade -2
docker compose exec backend alembic upgrade e7b3c9d2a1f4
docker compose exec backend python -m scripts.backfill_series
docker compose exec backend alembic upgrade head
```

Expected: each command succeeds except the second, which is the guard. The second backfill run reports `threads: 0`.

- [ ] **Step 8: Commit**

```bash
git add backend/app/services/open_library.py backend/scripts/backfill_series.py \
        backend/alembic/versions/f8c4d0e3b2a5_require_work_series.py backend/tests
git commit -m "feat(api): backfill series for existing works and threads"
```

---

### Task 5: Series on every work payload (search tag data)

**Files:**
- Create: `backend/app/schemas/series.py`
- Modify: `backend/app/services/works.py:447-511` (`WorkPresentation`, `load_work_presentation`), `backend/app/schemas/book.py` (`WorkOut`, `work_out`)
- Test: `backend/tests/test_search_local.py` or `backend/tests/test_works.py` (add one test each, see below)

**Interfaces:**
- Consumes: `Series`, `SeriesKind`.
- Produces:
  - `app.schemas.series.SeriesRef(slug: str, name: str, kind: SeriesKind)`
  - `SeriesWorkOut(id, title, author, first_publish_year: int | None, cover_url: str | None, shelf_status: ShelfStatus | None)`
  - `SeriesOut(slug, name, kind, description: str | None, works: list[SeriesWorkOut])`
  - `SeriesThreadCreate(title: str, work_id: UUID | None, body: str | None  # alias "content")`
  - `WorkPresentation` gains `series: SeriesRef | None`, still a NamedTuple built in services. `services` may import `schemas`, per `book.py`'s layering note: services → schemas → models.
  - `WorkOut.series: SeriesRef | None`, which is present on search, genre and `GET /api/works/{id}` responses.

- [ ] **Step 1: Write the failing test** (append to `tests/test_works.py`)

```python
@respx.mock
async def test_search_results_carry_their_series(client, db_session):
    from app.services.open_library import OLWork
    from app.services.works import upsert_work_from_ol
    from app.models import SearchQuery
    from datetime import datetime, timezone

    await upsert_work_from_ol(db_session, OLWork(
        key="OLRR1W", title="Red Rising", author="Pierce Brown", first_publish_year=2014,
        edition_count=26, isbn_13s=frozenset(), subjects=("franchise:Red Rising",)))
    await upsert_work_from_ol(db_session, OLWork(
        key="OLHB1W", title="Red Hobbit", author="Someone", first_publish_year=1937,
        edition_count=3, isbn_13s=frozenset(), subjects=("Fantasy",)))
    # Mark the query resolved so search stays local.
    db_session.add(SearchQuery(normalized_query="red", resolved_at=datetime.now(timezone.utc), result_count=2))
    await db_session.flush()

    rows = (await client.get("/api/works/search", params={"q": "red"})).json()
    by_title = {r["title"]: r for r in rows}
    assert by_title["Red Rising"]["series"] == {"slug": "red-rising", "name": "Red Rising", "kind": "series"}
    assert by_title["Red Hobbit"]["series"]["kind"] == "singleton"
```

Before writing this, check how `normalize` shapes the stored query (`app/services/google_books.py`) and use exactly that form for `normalized_query`. Also check the imports already at the top of `test_works.py` and reuse them.

- [ ] **Step 2: Run to verify it fails**

Run: `DATABASE_URL=postgresql+asyncpg://margin:margin@localhost:5432/margin_test pytest tests/test_works.py -k series -v`
Expected: FAIL — `KeyError: 'series'`.

- [ ] **Step 3: Implement**

`backend/app/schemas/series.py`:

```python
from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.series import SeriesKind
from app.models.shelf import ShelfStatus


class SeriesRef(BaseModel):
    """Enough of a series to link to it and label a card."""

    slug: str
    name: str
    kind: SeriesKind


class SeriesWorkOut(BaseModel):
    """One book row on a series page: identity, art, and the shelf control's state."""

    id: UUID
    title: str
    author: str
    first_publish_year: int | None = None
    cover_url: str | None = None
    shelf_status: ShelfStatus | None = None


class SeriesOut(BaseModel):
    slug: str
    name: str
    kind: SeriesKind
    # One description for the page: the singleton's own book, otherwise the
    # first member's. Per-book blurbs are deliberately absent.
    description: str | None = None
    works: list[SeriesWorkOut] = []


class SeriesThreadCreate(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    title: str = Field(min_length=1)
    work_id: UUID | None = None
    body: str | None = Field(default=None, alias="content")
```

In `app/services/works.py`, import `Series` from `app.models.series` and `SeriesRef` from `app.schemas.series`. Add `series: SeriesRef | None` as the last field of `WorkPresentation`. In `load_work_presentation`, add `Series.slug, Series.name, Series.kind` to the select, add `.outerjoin(Series, Work.series_id == Series.id)`, and build:

```python
            series=SeriesRef(slug=row[7], name=row[8], kind=row[9]) if row[7] else None,
```

In the docstring, add one bullet: `* series — the room the work's card links to; singletons included.`

In `app/schemas/book.py`, add `from app.schemas.series import SeriesRef`, add `series: SeriesRef | None = None` to `WorkOut`, and in `work_out` add `series=presentation.series if presentation else None,`.

- [ ] **Step 4: Run all backend tests**

Run: `DATABASE_URL=postgresql+asyncpg://margin:margin@localhost:5432/margin_test pytest -q`
Expected: all PASS. If `test_openapi.py` snapshots schemas, update its expectation to include `series`.

- [ ] **Step 5: Commit**

```bash
git add backend/app/schemas backend/app/services/works.py backend/tests
git commit -m "feat(api): every work payload names its series"
```

---

### Task 6: Shared thread service; threads carry their room

**Files:**
- Create: `backend/app/services/threads.py`
- Modify: `backend/app/api/threads.py`, `backend/app/api/genres.py:65-101`, `backend/app/schemas/thread.py` (`ThreadOut`)
- Test: `backend/tests/test_threads.py`

**Interfaces:**
- Consumes: `SeriesRef` (Task 5), `Series`.
- Produces (in `app.services.threads`):
  - `async thread_summaries(db, *conditions, current_user: User | None, limit: int, offset: int) -> list[ThreadSummary]`: ordered by score descending.
  - `async create_thread(db, *, user: User, title: str, body: str | None = None, series_id: UUID | None = None, work_id: UUID | None = None, genre_id: UUID | None = None) -> Thread`
  - `thread_out(thread: Thread, *, author: str | None, my_vote: int = 0, score: int | None = None) -> ThreadOut`
- `ThreadOut.series_id: UUID | None`, and `ThreadWithPosts.series: SeriesRef | None` (defined in `api/threads.py`).
- `POST /api/threads/` with `work_id` still works: the thread lands in that work's series, tagged with it.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_threads.py`)

```python
async def test_a_work_thread_lands_in_the_works_series_tagged(client, auth_headers, work):
    resp = await client.post(
        "/api/threads/", json={"title": "Legacy path", "work_id": str(work.id)}, headers=auth_headers
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["series_id"] == str(work.series_id)
    assert body["work_id"] == str(work.id)

    detail = (await client.get(f"/api/threads/{body['id']}")).json()
    assert detail["series"]["kind"] == "singleton"
    assert detail["series"]["slug"]


async def test_a_genre_thread_has_no_series(client, auth_headers, genre):
    resp = await client.post(
        "/api/threads/", json={"title": "Genre talk", "genre_slug": genre.slug}, headers=auth_headers
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["series_id"] is None
    assert (await client.get(f"/api/threads/{resp.json()['id']}")).json()["series"] is None
```

(`genre` is the fixture moved to `conftest.py` in Task 2.)

- [ ] **Step 2: Run to verify they fail**

Run: `DATABASE_URL=postgresql+asyncpg://margin:margin@localhost:5432/margin_test pytest tests/test_threads.py -v`
Expected: FAIL — `KeyError: 'series_id'`.

- [ ] **Step 3: Implement `app/services/threads.py`**

```python
"""Thread listing and creation shared by the series and genre rooms.

One query builds every thread list so the series feed, its per-book filter and
the genre feed can never drift in shape or ordering.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, literal, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Genre, Post, Thread, User, Vote
from app.schemas.thread import ThreadOut, ThreadSummary


async def thread_summaries(
    db: AsyncSession, *conditions, current_user: User | None, limit: int, offset: int
) -> list[ThreadSummary]:
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
        .where(*conditions)
        .group_by(Thread.id, User.username, Genre.slug)
        .order_by(Thread.score.desc())
        .limit(limit)
        .offset(offset)
    )
    rows = (await db.execute(stmt)).all()
    return [ThreadSummary.model_validate(row) for row in rows]


async def create_thread(
    db: AsyncSession,
    *,
    user: User,
    title: str,
    body: str | None = None,
    series_id: UUID | None = None,
    work_id: UUID | None = None,
    genre_id: UUID | None = None,
) -> Thread:
    thread = Thread(
        title=title, user_id=user.id, series_id=series_id, work_id=work_id, genre_id=genre_id
    )
    db.add(thread)
    await db.flush()
    # Optional opening post seeds the thread with its first message.
    if body:
        db.add(Post(thread_id=thread.id, user_id=user.id, content=body))
        await db.flush()
    await db.refresh(thread)
    return thread


def thread_out(
    thread: Thread, *, author: str | None, my_vote: int = 0, score: int | None = None
) -> ThreadOut:
    """Build from scalar columns — model_validate would lazy-load relationships."""
    return ThreadOut(
        id=thread.id,
        title=thread.title,
        user_id=thread.user_id,
        series_id=thread.series_id,
        work_id=thread.work_id,
        genre_id=thread.genre_id,
        score=thread.score if score is None else score,
        my_vote=my_vote,
        created_at=thread.created_at,
        author=author,
    )
```

In `app/schemas/thread.py`, add `series_id: UUID | None = None` to `ThreadOut`, right after `user_id`.

In `app/api/threads.py`:
- In `create_thread`, keep the genre and work resolution, and track the resolved `Work` object. After canonicalizing, set `series_id = work.series_id`. Then replace the `Thread(...)`/`Post`/`refresh`/`ThreadOut(...)` block with:

```python
    thread = await threads_service.create_thread(
        db, user=current_user, title=payload.title, body=payload.body,
        series_id=series_id, work_id=work_id, genre_id=genre_id,
    )
    return threads_service.thread_out(thread, author=current_user.username)
```

  Initialize `series_id: UUID | None = None` before the work branch. Import it as `from app.services import threads as threads_service`.
- Add `series: SeriesRef | None = None` to `ThreadWithPosts` and import `SeriesRef`. In `get_thread`, after the genre ref:

```python
    series_ref = None
    if thread.series_id is not None:
        row = (
            await db.execute(
                select(Series.slug, Series.name, Series.kind).where(Series.id == thread.series_id)
            )
        ).first()
        if row is not None:
            series_ref = SeriesRef(slug=row.slug, name=row.name, kind=row.kind)
```

  Pass `series=series_ref, series_id=thread.series_id` into `ThreadWithPosts(...)`.
- In `vote_thread`, return `threads_service.thread_out(thread, author=..., my_vote=payload.value, score=score)`.

In `app/api/genres.py`, replace the body of `get_genre_threads` after `genre = ...` with:

```python
    return await thread_summaries(
        db, Thread.genre_id == genre.id, current_user=current_user, limit=limit, offset=offset
    )
```

Then remove the imports that are now unused (`literal`, `Vote`, `Post`, `User`, and `func` if nothing else uses it).

- [ ] **Step 4: Run all backend tests**

Run: `DATABASE_URL=postgresql+asyncpg://margin:margin@localhost:5432/margin_test pytest -q`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app backend/tests
git commit -m "feat(api): threads live in a series room; share the listing query"
```

---

### Task 7: The `/api/series` router; retire the work thread listing

**Files:**
- Create: `backend/app/api/series.py`, `backend/tests/test_series_api.py`
- Modify: `backend/app/main.py`, `backend/app/api/works.py` (drop `enrich_work` from `get_work`, delete `get_work_threads`), `backend/tests/test_enrichment.py:134-140`, `backend/tests/test_pagination.py` (work-thread cases), `backend/tests/test_votes.py:327-333`, `backend/tests/test_threads.py:173,211`, `backend/tests/test_works.py:218`

**Interfaces:**
- Consumes: `get_series_by_slug`, `canonical_work`, `load_work_presentation`, `enrich_work`, `thread_summaries`, `create_thread`, `thread_out`, `SeriesOut`, `SeriesWorkOut`, `SeriesThreadCreate`.
- Produces:
  - `GET /api/series/{slug}` → `SeriesOut`. Members are live works ordered by `first_publish_year` (nulls last), then title. It enriches up to 10 unenriched members, and answers a tombstoned slug with the survivor, whose `slug` differs from the one requested.
  - `GET /api/series/{slug}/threads?work_id=&limit=&offset=` → `list[ThreadSummary]`
  - `POST /api/series/{slug}/threads` (auth), with body `{title, content?, work_id?}` → `ThreadOut` 201. It returns 422 when `work_id` is not a member.
  - `GET /api/works/{id}` no longer enriches. `GET /api/works/{id}/threads` is removed (404).

- [ ] **Step 1: Write the failing tests** — `backend/tests/test_series_api.py`

```python
"""The series page: its books, its description, its room."""

import uuid
from datetime import datetime, timezone

import respx
from httpx import Response

from app.models import Series, Work
from app.services.open_library import OLWork
from app.services.works import upsert_work_from_ol

# The same URL `tests/test_enrichment.py` mocks (tests/ is not a package, so
# it is repeated rather than imported).
GOOGLE_URL = "https://www.googleapis.com/books/v1/volumes"


async def _saga(db):
    books = []
    for key, title, year in [("OLA1W", "Golden Son", 2015), ("OLA0W", "Red Rising", 2014), ("OLA2W", "Morning Star", 2016)]:
        w = await upsert_work_from_ol(db, OLWork(
            key=key, title=title, author="Pierce Brown", first_publish_year=year,
            edition_count=1, isbn_13s=frozenset(), subjects=("franchise:Red Rising",)))
        w.enriched_at = datetime.now(timezone.utc)
        w.description = f"About {title}."
        books.append(w)
    await db.flush()
    return books


async def test_series_page_lists_books_in_publication_order(client, db_session):
    await _saga(db_session)
    resp = await client.get("/api/series/red-rising")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["kind"] == "series"
    assert body["name"] == "Red Rising"
    assert [w["title"] for w in body["works"]] == ["Red Rising", "Golden Son", "Morning Star"]
    assert body["description"] == "About Red Rising."
    assert set(body["works"][0]) == {"id", "title", "author", "first_publish_year", "cover_url", "shelf_status"}


async def test_series_page_reports_the_callers_shelf(client, db_session, auth_headers):
    red, *_ = await _saga(db_session)
    await client.post(f"/api/works/{red.id}/shelf", json={"status": "reading"}, headers=auth_headers)
    body = (await client.get("/api/series/red-rising", headers=auth_headers)).json()
    shelves = {w["title"]: w["shelf_status"] for w in body["works"]}
    assert shelves == {"Red Rising": "reading", "Golden Son": None, "Morning Star": None}


async def test_singleton_page_uses_its_books_description(client, db_session, work):
    series = await db_session.get(Series, work.series_id)
    work.description = "Just the one."
    await db_session.flush()
    body = (await client.get(f"/api/series/{series.slug}")).json()
    assert body["kind"] == "singleton"
    assert [w["id"] for w in body["works"]] == [str(work.id)]
    assert body["description"] == "Just the one."


async def test_unknown_series_is_404(client):
    assert (await client.get("/api/series/nope")).status_code == 404


async def test_series_endpoint_answers_a_tombstoned_slug_with_the_survivor(client, db_session):
    w = await upsert_work_from_ol(db_session, OLWork(
        key="OLT1W", title="Dark Age", author="Pierce Brown", first_publish_year=2019,
        edition_count=1, isbn_13s=frozenset(), subjects=()))
    w.enriched_at = datetime.now(timezone.utc)
    old_slug = (await db_session.get(Series, w.series_id)).slug
    await upsert_work_from_ol(db_session, OLWork(
        key="OLT1W", title="Dark Age", author="Pierce Brown", first_publish_year=2019,
        edition_count=1, isbn_13s=frozenset(), subjects=("franchise:Red Rising",)))
    body = (await client.get(f"/api/series/{old_slug}")).json()
    assert body["slug"] == "red-rising"


@respx.mock
async def test_first_view_of_a_series_enriches_its_books(client, db_session):
    route = respx.get(GOOGLE_URL).mock(return_value=Response(200, json={"items": []}))
    await upsert_work_from_ol(db_session, OLWork(
        key="OLE1W", title="Fresh", author="New Author", first_publish_year=2020,
        edition_count=1, isbn_13s=frozenset(), subjects=()))
    series = (await db_session.execute(Series.__table__.select())).first()
    resp = await client.get(f"/api/series/{series.slug}")
    assert resp.status_code == 200
    assert route.called


async def test_series_threads_filter_by_book_tag(client, db_session, auth_headers):
    red, gold, _ = await _saga(db_session)
    for title, work_id in [("general", None), ("about golden son", gold.id), ("about red rising", red.id)]:
        payload = {"title": title}
        if work_id:
            payload["work_id"] = str(work_id)
        resp = await client.post("/api/series/red-rising/threads", json=payload, headers=auth_headers)
        assert resp.status_code == 201, resp.text

    everything = (await client.get("/api/series/red-rising/threads")).json()
    assert {t["title"] for t in everything} == {"general", "about golden son", "about red rising"}
    only_gold = (await client.get(f"/api/series/red-rising/threads?work_id={gold.id}")).json()
    assert [t["title"] for t in only_gold] == ["about golden son"]


async def test_create_series_thread_rejects_a_book_from_another_series(client, db_session, auth_headers, work):
    await _saga(db_session)
    resp = await client.post(
        "/api/series/red-rising/threads", json={"title": "wrong room", "work_id": str(work.id)},
        headers=auth_headers,
    )
    assert resp.status_code == 422


async def test_create_series_thread_canonicalizes_a_merged_book_id(client, db_session, auth_headers):
    from app.models import WorkKind, WorkProvenance, WorkSource
    red, *_ = await _saga(db_session)
    tomb = Work(source=WorkSource.heuristic, external_id="tomb", canonical_key="x", title="Red Rising",
                author="Pierce Brown", kind=WorkKind.single, identity_provenance=WorkProvenance.heuristic,
                merged_into_id=red.id, series_id=red.series_id)
    db_session.add(tomb)
    await db_session.flush()
    resp = await client.post(
        "/api/series/red-rising/threads", json={"title": "old id", "work_id": str(tomb.id)},
        headers=auth_headers,
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["work_id"] == str(red.id)
    assert resp.json()["series_id"] == str(red.series_id)


async def test_create_series_thread_requires_auth(client, db_session):
    await _saga(db_session)
    resp = await client.post("/api/series/red-rising/threads", json={"title": "anon"})
    assert resp.status_code in (401, 403)


async def test_series_threads_pagination_limits(client, db_session):
    await _saga(db_session)
    assert (await client.get("/api/series/red-rising/threads?limit=999")).status_code == 422
    assert (await client.get("/api/series/red-rising/threads?offset=-1")).status_code == 422


async def test_work_thread_listing_is_gone(client, work):
    assert (await client.get(f"/api/works/{work.id}/threads")).status_code == 404
```

- [ ] **Step 2: Run to verify they fail**

Run: `DATABASE_URL=postgresql+asyncpg://margin:margin@localhost:5432/margin_test pytest tests/test_series_api.py -v`
Expected: FAIL — 404s on `/api/series/...`.

- [ ] **Step 3: Implement the router** — `backend/app/api/series.py`

```python
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Series, Shelf, Thread, User, Work
from app.schemas.series import SeriesOut, SeriesThreadCreate, SeriesWorkOut
from app.schemas.thread import ThreadOut, ThreadSummary
from app.services.auth import get_current_user, get_current_user_optional
from app.services.enrichment import enrich_work
from app.services.series import get_series_by_slug
from app.services.threads import create_thread, thread_out, thread_summaries
from app.services.works import canonical_work, load_work_presentation

router = APIRouter(prefix="/series", tags=["series"])

# First view of a series pays for Google Books on its members, which used to
# happen on each work page. Capped so one huge series cannot stall a request.
_ENRICH_CAP = 10


async def _series_or_404(db: AsyncSession, slug: str) -> Series:
    series = await get_series_by_slug(db, slug)
    if series is None:
        raise HTTPException(status_code=404, detail="Series not found")
    return series


async def _members(db: AsyncSession, series: Series) -> list[Work]:
    stmt = (
        select(Work)
        .where(Work.series_id == series.id, Work.merged_into_id.is_(None))
        .order_by(Work.first_publish_year.asc().nulls_last(), Work.title)
    )
    return list((await db.execute(stmt)).scalars().all())


@router.get("/{slug}", response_model=SeriesOut)
async def get_series(
    slug: str,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(get_current_user_optional),
) -> SeriesOut:
    """A tombstoned slug answers with the survivor; the client redirects on
    seeing a different ``slug`` than it asked for."""
    series = await _series_or_404(db, slug)
    works = await _members(db, series)
    for work in [w for w in works if w.enriched_at is None][:_ENRICH_CAP]:
        await enrich_work(db, work)

    presentation = await load_work_presentation(db, [w.id for w in works])
    shelves: dict[UUID, str] = {}
    if current_user is not None and works:
        rows = await db.execute(
            select(Shelf.work_id, Shelf.status).where(
                Shelf.user_id == current_user.id, Shelf.work_id.in_([w.id for w in works])
            )
        )
        shelves = {row.work_id: row.status for row in rows}

    first = presentation.get(works[0].id) if works else None
    return SeriesOut(
        slug=series.slug,
        name=series.name,
        kind=series.kind,
        description=first.description if first else None,
        works=[
            SeriesWorkOut(
                id=w.id,
                title=w.title,
                author=w.author,
                first_publish_year=w.first_publish_year,
                cover_url=presentation[w.id].cover_url if w.id in presentation else None,
                shelf_status=shelves.get(w.id),
            )
            for w in works
        ],
    )


@router.get("/{slug}/threads", response_model=list[ThreadSummary])
async def get_series_threads(
    slug: str,
    work_id: UUID | None = None,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(get_current_user_optional),
):
    series = await _series_or_404(db, slug)
    conditions = [Thread.series_id == series.id]
    if work_id is not None:
        conditions.append(Thread.work_id == work_id)
    return await thread_summaries(
        db, *conditions, current_user=current_user, limit=limit, offset=offset
    )


@router.post("/{slug}/threads", response_model=ThreadOut, status_code=status.HTTP_201_CREATED)
async def create_series_thread(
    slug: str,
    payload: SeriesThreadCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ThreadOut:
    series = await _series_or_404(db, slug)
    work_id = None
    if payload.work_id is not None:
        # Canonicalize first: a stale tab can hold a merged member's id.
        work = await db.get(Work, payload.work_id)
        work = await canonical_work(db, work) if work is not None else None
        if work is None or work.series_id != series.id:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="That book is not part of this series.",
            )
        work_id = work.id
    thread = await create_thread(
        db, user=current_user, title=payload.title, body=payload.body,
        series_id=series.id, work_id=work_id,
    )
    return thread_out(thread, author=current_user.username)
```

In `app/main.py`: add `series` to `from app.api import ...`, add `app.include_router(series.router, prefix="/api")`, and add the tag `{"name": "series", "description": "Series pages: member books and the series discussion room."}`.

In `app/api/works.py`: delete `get_work_threads` entirely. In `get_work`, delete the `await enrich_work(db, work)` line and its comment. Remove the imports that are now unused (`enrich_work`, `ThreadSummary`, `literal`, `func` if unused, `Genre`/`Post`/`Thread`/`User`/`Vote` if unused; keep what `_upsert_editions` and the shelf routes use). Update the docstring of `get_work` to: `"""Catalog lookup by id. The frontend only uses it to redirect a legacy /works/:id URL to its series."""`

- [ ] **Step 4: Repoint the old tests**
- `tests/test_enrichment.py` `test_get_work_triggers_enrichment` → rename to `test_series_view_triggers_enrichment`. Look up the seeded work's series slug (`(await db_session.get(Series, work.series_id)).slug`), GET `/api/series/{slug}`, and assert `resp.json()["description"] == "A boy from the mines."`.
- `tests/test_pagination.py`: in `test_work_threads_limit_and_offset` and `test_limit_constraints`, replace `/api/works/{work.id}/threads` with `/api/series/{slug}/threads`, where `slug = (await db_session.get(Series, work.series_id)).slug`.
- `tests/test_votes.py:327,333`, `tests/test_threads.py:173,211` and `tests/test_works.py:218`: make the same replacement.

- [ ] **Step 5: Run all backend tests**

Run: `DATABASE_URL=postgresql+asyncpg://margin:margin@localhost:5432/margin_test pytest -q`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app backend/tests
git commit -m "feat(api): series page and room endpoints; retire work thread listing"
```

---

### Task 8: Frontend API hooks and the search card

**Files:**
- Create: `frontend/src/api/series.js`
- Modify: `frontend/src/api/works.js`, `frontend/src/api/threads.js`, `frontend/src/components/WorkCard.jsx`, `frontend/src/components/WorkCard.test.jsx`

**Interfaces:**
- Consumes: `WorkOut.series` `{slug, name, kind}`, and the `/series` endpoints (Task 7).
- Produces:
  - `useSeries(slug)`, with query key `['series', slug]`.
  - `useSeriesThreads(slug, workId)`, with query key `['series', slug, 'threads', workId ?? 'all']`, fetching `GET /series/:slug/threads` with `params: workId ? { work_id: workId } : {}`.
  - `useCreateSeriesThread(slug)`, a mutation posting `{title, content, work_id?}` that invalidates `['series', slug, 'threads']`.
  - `seriesHref(work)`, which returns `/series/${work.series.slug}?book=${work.id}` when `work.series` is set and `/works/${work.id}` otherwise (the legacy redirect).
  - `useVoteThread` accepts `{ id, value, seriesSlug?, genreSlug? }`. Shelf mutations also invalidate `['series']`.
  - `useWorkThreads` is removed.

- [ ] **Step 1: Write the failing tests.** Add to `WorkCard.test.jsx` and replace the first `it` block.

```jsx
  const inSeries = { ...work, series: { slug: 'red-rising', name: 'Red Rising', kind: 'series' } }
  const alone = { ...work, series: { slug: 'the-hobbit-a1b2c3', name: 'The Hobbit', kind: 'singleton' } }

  it('opens the series page at this book', () => {
    renderCard(inSeries)
    expect(screen.getByRole('link')).toHaveAttribute('href', '/series/red-rising?book=w1')
  })

  it('opens a singleton at its own series page', () => {
    renderCard(alone)
    expect(screen.getByRole('link')).toHaveAttribute('href', '/series/the-hobbit-a1b2c3?book=w1')
  })

  it('falls back to the legacy work URL when no series is known', () => {
    renderCard(work)
    expect(screen.getByRole('link')).toHaveAttribute('href', '/works/w1')
  })

  it('names the series a book belongs to', () => {
    renderCard(inSeries)
    expect(screen.getByText('series')).toBeInTheDocument()
    expect(screen.getByText('Red Rising', { selector: '.text-path' })).toBeInTheDocument()
  })

  it('shows no series tag for a book that stands alone', () => {
    renderCard(alone)
    expect(screen.queryByText('series')).not.toBeInTheDocument()
  })
```

- [ ] **Step 2: Run to verify they fail**

Run (from `frontend/`): `npm test -- WorkCard`
Expected: FAIL — the href is still `/works/w1` and there is no series text.

- [ ] **Step 3: Implement**

`frontend/src/api/series.js`:

```js
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import client from './client'

export function seriesHref(work) {
  // A work without a series predates the backfill; its legacy URL redirects.
  return work.series ? `/series/${work.series.slug}?book=${work.id}` : `/works/${work.id}`
}

export function useSeries(slug) {
  return useQuery({
    queryKey: ['series', slug],
    queryFn: () => client.get(`/series/${slug}`).then((r) => r.data),
    enabled: !!slug,
  })
}

export function useSeriesThreads(slug, workId) {
  return useQuery({
    queryKey: ['series', slug, 'threads', workId ?? 'all'],
    queryFn: () =>
      client
        .get(`/series/${slug}/threads`, { params: workId ? { work_id: workId } : {} })
        .then((r) => r.data),
    enabled: !!slug,
  })
}

export function useCreateSeriesThread(slug) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (payload) => client.post(`/series/${slug}/threads`, payload).then((r) => r.data),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['series', slug, 'threads'] }),
  })
}
```

`frontend/src/api/works.js`: delete `useWorkThreads`. In each of the three shelf mutations' `onSuccess`, add `queryClient.invalidateQueries({ queryKey: ['series'] })` because the series page shows `shelf_status`.

`frontend/src/api/threads.js`:
- `useCreateThread` `onSuccess`: delete the `data.work_id` branch and keep the genre branch.
- `useVoteThread` `onSuccess: (_, { id, seriesSlug, genreSlug })`: replace the `workId` branch with `if (seriesSlug) queryClient.invalidateQueries({ queryKey: ['series', seriesSlug, 'threads'] })`.

`frontend/src/components/WorkCard.jsx`: import `seriesHref` from `../api/series`, destructure `series`, set `<Link to={seriesHref(work)} ...>`, and after the author line add:

```jsx
        {/* A reference to the book's room, so it takes the path colour. Text,
            not a glyph: the literal-glyph set is closed. */}
        {series?.kind === 'series' && (
          <p className="text-xs lowercase line-clamp-1">
            <span className="text-ink-dim">series </span>
            <span className="text-path">{series.name}</span>
          </p>
        )}
```

- [ ] **Step 4: Run the frontend tests**

Run: `npm test`
Expected: all PASS. `Work.jsx` still imports `useWorkThreads` until Task 10, so the suite may fail to import it. If it does, stub `Work.jsx` now to `export { default } from './WorkRedirect'` and do Task 10 immediately afterwards, or run Tasks 8–10 before this check. Vitest only imports files that tests touch, so it should pass. Also run `npm run build`, which will fail until Task 10. Record that expected failure in the task report and do not fix it here.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/api frontend/src/components/WorkCard.jsx frontend/src/components/WorkCard.test.jsx
git commit -m "feat(web): search cards name their series and open it"
```

---

### Task 9: The series page and a book-aware thread composer

**Files:**
- Create: `frontend/src/pages/Series.jsx`, `frontend/src/pages/Series.test.jsx`
- Modify: `frontend/src/components/ThreadModal.jsx`, `frontend/src/components/ThreadModal.test.jsx`

**Interfaces:**
- Consumes: `useSeries`, `useSeriesThreads`, `useCreateSeriesThread` (Task 8), `useVoteThread`, `ShelfButton({ workId, currentStatus })`, `PathHeader`, `DataTable`, `VoteControl`, `relativeTime`, `useStatusBar`.
- Produces:
  - `<Series />` at route `/series/:slug`. It reads `?book=`.
  - `ThreadModal` new props:
    - `seriesSlug?: string`: when set, it posts through `useCreateSeriesThread(seriesSlug)` and ignores `target`.
    - `books?: {id, title}[]`: when non-empty, it renders a `<select aria-label="About which book">` with a first option `all books`, value `""`.
    - `defaultBookId?: string`.
  - The payload adds `work_id` only when a book is chosen.

- [ ] **Step 1: Write the failing tests**

Add to `ThreadModal.test.jsx`. Mock the client in the same style as `ResetPassword.test.jsx`: `vi.mock('../api/client', () => ({ default: { post: vi.fn() } }))`, then `import client from '../api/client'`. Place it at the top of the file; if existing tests break because of it, give them a resolved `client.post`.

```jsx
  it('offers a book tag inside a series and sends it', async () => {
    client.post.mockResolvedValue({ data: { id: 't1' } })
    const onCreated = vi.fn()
    renderModal({
      seriesSlug: 'red-rising',
      books: [{ id: 'b1', title: 'Red Rising' }, { id: 'b2', title: 'Golden Son' }],
      onCreated,
    })
    await userEvent.type(screen.getByPlaceholderText(/thread title/i), 'Mustang')
    await userEvent.selectOptions(screen.getByLabelText('About which book'), 'b2')
    await userEvent.click(screen.getByRole('button', { name: 'Create Thread' }))
    expect(client.post).toHaveBeenCalledWith('/series/red-rising/threads', {
      title: 'Mustang', content: '', work_id: 'b2',
    })
  })

  it('sends no tag when "all books" stays selected', async () => {
    client.post.mockResolvedValue({ data: { id: 't1' } })
    renderModal({ seriesSlug: 'red-rising', books: [{ id: 'b1', title: 'Red Rising' }] })
    await userEvent.type(screen.getByPlaceholderText(/thread title/i), 'General')
    await userEvent.click(screen.getByRole('button', { name: 'Create Thread' }))
    expect(client.post).toHaveBeenCalledWith('/series/red-rising/threads', { title: 'General', content: '' })
  })

  it('hides the book select without books', () => {
    renderModal({ seriesSlug: 'the-hobbit-a1b2c3', books: [] })
    expect(screen.queryByLabelText('About which book')).not.toBeInTheDocument()
  })
```

Create `Series.test.jsx`:

```jsx
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Routes, Route, useLocation } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

vi.mock('../api/client', () => ({ default: { get: vi.fn(), post: vi.fn(), put: vi.fn() } }))

import client from '../api/client'
import useAuthStore from '../store/auth'
import Series from './Series'

const SAGA = {
  slug: 'red-rising',
  name: 'Red Rising',
  kind: 'series',
  description: 'A boy from the mines.',
  works: [
    { id: 'b1', title: 'Red Rising', author: 'Pierce Brown', first_publish_year: 2014, cover_url: null, shelf_status: null },
    { id: 'b2', title: 'Golden Son', author: 'Pierce Brown', first_publish_year: 2015, cover_url: null, shelf_status: 'reading' },
  ],
}
const SINGLE = {
  slug: 'the-hobbit-a1b2c3',
  name: 'The Hobbit',
  kind: 'singleton',
  description: 'There and back again.',
  works: [{ id: 'h1', title: 'The Hobbit', author: 'J. R. R. Tolkien', first_publish_year: 1937, cover_url: null, shelf_status: null }],
}
const THREADS = [
  { id: 't1', title: 'Is Mustang right?', score: 3, my_vote: 0, post_count: 2, author: 'reader', created_at: new Date().toISOString(), work_id: 'b2' },
  { id: 't2', title: 'Best book?', score: 1, my_vote: 0, post_count: 0, author: 'reader', created_at: new Date().toISOString(), work_id: null },
]

function mockApi(series, threads = THREADS) {
  client.get.mockImplementation((url, config) => {
    if (url.endsWith('/threads')) {
      const workId = config?.params?.work_id
      return Promise.resolve({ data: workId ? threads.filter((t) => t.work_id === workId) : threads })
    }
    return Promise.resolve({ data: series })
  })
}

function Where() {
  const loc = useLocation()
  return <p data-testid="where">{loc.pathname}</p>
}

function renderPage(entry) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[entry]}>
        <Where />
        <Routes>
          <Route path="/series/:slug" element={<Series />} />
          <Route path="/series/:slug/threads/:threadId" element={<p>thread page</p>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  vi.clearAllMocks()
  // Signed in, so ShelfButton renders its status rather than a login link.
  useAuthStore.setState({ token: 't', user: { id: 'u1', username: 'reader' } })
})

describe('Series page', () => {
  it('lists its books in order with only a shelf control each', async () => {
    mockApi(SAGA)
    renderPage('/series/red-rising')
    const list = await screen.findByRole('list', { name: 'Books in this series' })
    const rows = within(list).getAllByRole('listitem')
    expect(rows.map((r) => within(r).getByRole('heading').textContent)).toEqual(['Red Rising', 'Golden Son'])
    // Rows are not links to a book page; the only control is the shelf button.
    rows.forEach((r) => expect(within(r).queryByRole('link', { name: /red rising|golden son/i })).toBeNull())
    expect(within(rows[1]).getByText('reading')).toBeInTheDocument()
  })

  it('shows one description for the series', async () => {
    mockApi(SAGA)
    renderPage('/series/red-rising')
    expect(await screen.findByText('A boy from the mines.')).toBeInTheDocument()
  })

  it('filters the discussion by book', async () => {
    mockApi(SAGA)
    renderPage('/series/red-rising')
    expect(await screen.findByText('Best book?')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Golden Son' }))
    await waitFor(() => expect(screen.queryByText('Best book?')).not.toBeInTheDocument())
    expect(screen.getByText('Is Mustang right?')).toBeInTheDocument()
    expect(client.get).toHaveBeenCalledWith('/series/red-rising/threads', { params: { work_id: 'b2' } })
  })

  it('highlights the book named by ?book=', async () => {
    mockApi(SAGA)
    renderPage('/series/red-rising?book=b2')
    const list = await screen.findByRole('list', { name: 'Books in this series' })
    const [first, second] = within(list).getAllByRole('listitem')
    expect(second).toHaveAttribute('aria-current', 'true')
    expect(first).not.toHaveAttribute('aria-current')
  })

  it('ignores a ?book= that is not a member', async () => {
    mockApi(SAGA)
    renderPage('/series/red-rising?book=zzz')
    const list = await screen.findByRole('list', { name: 'Books in this series' })
    within(list).getAllByRole('listitem').forEach((r) => expect(r).not.toHaveAttribute('aria-current'))
  })

  it('drops series chrome for a singleton', async () => {
    mockApi(SINGLE, [])
    renderPage('/series/the-hobbit-a1b2c3')
    expect(await screen.findByRole('heading', { level: 1, name: 'The Hobbit' })).toBeInTheDocument()
    expect(screen.queryByText(/books? in this series/i)).not.toBeInTheDocument()
    expect(screen.queryByRole('group', { name: 'Filter by book' })).not.toBeInTheDocument()
  })

  it('redirects when the API answers with a different slug', async () => {
    mockApi({ ...SAGA, slug: 'red-rising' })
    renderPage('/series/dark-age-a1b2c3')
    await waitFor(() => expect(screen.getByTestId('where')).toHaveTextContent('/series/red-rising'))
  })
})
```

- [ ] **Step 2: Run to verify they fail**

Run: `npm test -- Series ThreadModal`
Expected: FAIL — `Series` does not exist, and ThreadModal has no book select.

- [ ] **Step 3: Implement ThreadModal changes**

In `ThreadModal.jsx`, import `useCreateSeriesThread` from `../api/series`, and add the props `seriesSlug`, `books = []` and `defaultBookId = ''`. Call both hooks unconditionally, as the rules of hooks require:

```jsx
  const [bookId, setBookId] = useState(defaultBookId)
  const genericMutation = useCreateThread()
  const seriesMutation = useCreateSeriesThread(seriesSlug)
  const mutation = seriesSlug ? seriesMutation : genericMutation

  const handleSubmit = (e) => {
    e.preventDefault()
    if (!threadTitle.trim()) return
    const payload = seriesSlug
      ? { title: threadTitle.trim(), content: body.trim(), ...(bookId ? { work_id: bookId } : {}) }
      : { ...target, title: threadTitle.trim(), content: body.trim() }
    mutation.mutate(payload, { onSuccess: (data) => onCreated(data) })
  }
```

Between the title input and the textarea:

```jsx
          {books.length > 0 && (
            <select
              aria-label="About which book"
              value={bookId}
              onChange={(e) => setBookId(e.target.value)}
              className="input"
            >
              <option value="">all books</option>
              {books.map((b) => (
                <option key={b.id} value={b.id}>
                  {b.title}
                </option>
              ))}
            </select>
          )}
```

Update the doc comment. `target` is used for genres; `seriesSlug` and `books` are used for series, and the optional book tag is used as a spoiler filter.

- [ ] **Step 4: Implement `frontend/src/pages/Series.jsx`**

```jsx
import { useEffect, useRef, useState } from 'react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { useSeries, useSeriesThreads } from '../api/series'
import { useVoteThread } from '../api/threads'
import ShelfButton from '../components/ShelfButton'
import PathHeader from '../components/PathHeader'
import DataTable from '../components/DataTable'
import ThreadModal from '../components/ThreadModal'
import VoteControl from '../components/VoteControl'
import { relativeTime } from '../components/Post'
import { useStatusBar } from '../store/status'
import useAuthStore from '../store/auth'

/**
 * A book's only page. A series lists its books — each with nothing but a
 * shelf control — above one description and the whole series' discussion.
 * A singleton is the same page with the series chrome removed.
 */
function BookRow({ work, current, rowRef }) {
  const [coverFailed, setCoverFailed] = useState(false)
  return (
    <li
      ref={rowRef}
      aria-current={current ? 'true' : undefined}
      className={`flex gap-5 py-4 px-2 -mx-2 ${current ? 'bg-highlight' : ''}`}
    >
      {/* Covers carry the colour; large, full colour, never dimmed. */}
      <div className="shrink-0 w-28">
        {work.cover_url && !coverFailed ? (
          <img src={work.cover_url} alt={work.title} onError={() => setCoverFailed(true)} className="w-full border border-line" />
        ) : (
          <div className="w-full aspect-[2/3] bg-panel border border-line flex items-center justify-center p-2">
            <span className="font-serif italic text-ink-dim text-xs text-center">{work.title}</span>
          </div>
        )}
      </div>
      <div className="flex flex-col gap-2 min-w-0">
        <h3 className="font-serif text-xl text-ink leading-tight">{work.title}</h3>
        <p className="text-user text-xs lowercase tracking-eyebrow">{work.author}</p>
        {work.first_publish_year && (
          <p className="text-ink-dim text-xs tabular-nums">{work.first_publish_year}</p>
        )}
        <ShelfButton workId={work.id} currentStatus={work.shelf_status} />
      </div>
    </li>
  )
}

function Series() {
  const { slug } = useParams()
  const [searchParams] = useSearchParams()
  const navigate = useNavigate()
  const user = useAuthStore((s) => s.user)
  const voteMutation = useVoteThread()
  const [showModal, setShowModal] = useState(false)
  const [expanded, setExpanded] = useState(false)
  const [filter, setFilter] = useState(null) // a work id, or null for all books
  const currentRef = useRef(null)

  const { data: series, isLoading, isError } = useSeries(slug)
  const { data: threads, isLoading: threadsLoading } = useSeriesThreads(series?.slug, filter)

  // A promoted singleton's old slug answers with its survivor.
  useEffect(() => {
    if (series && series.slug !== slug) {
      navigate(`/series/${series.slug}?${searchParams}`, { replace: true })
    }
  }, [series, slug, navigate, searchParams])

  const bookParam = searchParams.get('book')
  const currentId = series?.works.some((w) => w.id === bookParam) ? bookParam : null
  useEffect(() => {
    currentRef.current?.scrollIntoView?.({ block: 'center' })
  }, [currentId])

  const isSeries = series?.kind === 'series'
  const threadCount = threads?.length ?? 0
  useStatusBar({
    mode: 'SERIES',
    path: series ? `~/series/${series.slug}` : '~/series',
    facts: [`${threadCount} ${threadCount === 1 ? 'thread' : 'threads'}`],
  })

  if (isLoading) {
    return (
      <main className="max-w-shell mx-auto px-4 py-8">
        <div className="animate-pulse flex flex-col gap-4">
          <div className="h-10 bg-panel w-1/2" />
          <div className="h-20 bg-panel w-full" />
        </div>
      </main>
    )
  }
  if (isError || !series) {
    return (
      <main className="max-w-shell mx-auto px-4 py-8">
        <p className="alert-danger">Failed to load this book.</p>
      </main>
    )
  }

  const titleOf = Object.fromEntries(series.works.map((w) => [w.id, w.title]))
  const columns = [
    {
      key: 'score', label: 'Score', align: 'right', width: 8,
      render: (row) => (
        <VoteControl
          variant="row"
          score={row.score ?? 0}
          myVote={row.my_vote ?? 0}
          onVote={(value) => user && voteMutation.mutate({ id: row.id, value, seriesSlug: series.slug })}
          disabled={!user}
          pending={voteMutation.isPending}
        />
      ),
    },
    {
      key: 'title', label: 'Thread',
      render: (row) => (
        <Link to={`/series/${series.slug}/threads/${row.id}`} className="text-ink hover:text-accent transition-colors duration-fast">
          {row.title}
        </Link>
      ),
    },
    ...(isSeries
      ? [{
          key: 'book', label: 'Book', width: 20,
          render: (row) =>
            row.work_id ? <span className="font-serif text-ink-dim">{titleOf[row.work_id] ?? ''}</span> : null,
        }]
      : []),
    { key: 'author', label: 'By', width: 16, render: (row) => <span className="text-user">{row.author}</span> },
    { key: 'post_count', label: 'Repl', align: 'right', width: 6, render: (row) => <span className="text-ink-dim tabular-nums">{row.post_count ?? 0}</span> },
    { key: 'created_at', label: 'Age', align: 'right', width: 6, render: (row) => <span className="text-ink-dim tabular-nums">{relativeTime(row.created_at)}</span> },
  ]

  const filterButton = (id, label) => (
    <button
      key={id ?? 'all'}
      type="button"
      aria-pressed={filter === id}
      onClick={() => setFilter(id)}
      className={`text-xs px-1 transition-colors duration-fast ${
        filter === id ? 'text-accent' : 'text-ink-dim hover:text-accent'
      }`}
    >
      {label}
    </button>
  )

  return (
    <main className="max-w-shell mx-auto px-4 py-6 flex flex-col gap-10">
      <PathHeader segments={[{ label: 'series', to: '/' }, { label: series.name }]} />

      <header className="flex flex-col gap-3 border-b border-line pb-6">
        {/* Serif is reserved for book titles; a series name is one. */}
        <h1 className="font-serif text-3xl md:text-4xl text-ink leading-tight">{series.name}</h1>
        {isSeries && (
          <p className="text-ink-dim text-xs tabular-nums">
            {series.works.length} {series.works.length === 1 ? 'book' : 'books'} in this series
          </p>
        )}
        {series.description && (
          <div className="flex flex-col gap-1 max-w-prose">
            <p className={`text-ink-dim text-sm leading-relaxed ${expanded ? '' : 'line-clamp-4'}`}>
              {series.description}
            </p>
            <button type="button" onClick={() => setExpanded((v) => !v)} className="btn-ghost self-start text-xs">
              {expanded ? 'less' : 'more'}
            </button>
          </div>
        )}
      </header>

      <ul aria-label="Books in this series" className="flex flex-col divide-y divide-line">
        {series.works.map((work) => (
          <BookRow
            key={work.id}
            work={work}
            current={work.id === currentId}
            rowRef={work.id === currentId ? currentRef : undefined}
          />
        ))}
      </ul>

      <section className="panel p-5 pt-6">
        <h2 className="panel-title">Discussions</h2>
        <div className="flex flex-wrap items-center justify-between gap-3 mb-3">
          {isSeries ? (
            <div role="group" aria-label="Filter by book" className="flex flex-wrap items-center gap-2">
              {filterButton(null, 'all')}
              {series.works.map((w) => filterButton(w.id, w.title))}
            </div>
          ) : (
            <span />
          )}
          {user && (
            <button onClick={() => setShowModal(true)} className="btn-secondary text-xs">
              Start a Thread
            </button>
          )}
        </div>
        {threadsLoading ? (
          <div className="flex flex-col gap-2">
            {[1, 2, 3].map((i) => <div key={i} className="h-8 border border-line bg-panel animate-pulse" />)}
          </div>
        ) : (
          <DataTable
            columns={columns}
            rows={threads || []}
            caption={`Discussions about ${series.name}`}
            emptyMessage={user ? 'No discussions yet. Start the first one.' : 'No discussions yet.'}
          />
        )}
      </section>

      {showModal && (
        <ThreadModal
          seriesSlug={series.slug}
          books={isSeries ? series.works.map((w) => ({ id: w.id, title: w.title })) : []}
          defaultBookId={filter ?? currentId ?? ''}
          onClose={() => setShowModal(false)}
          onCreated={(thread) => navigate(`/series/${series.slug}/threads/${thread.id}`)}
        />
      )}
    </main>
  )
}

export default Series
```

Check that `tracking-eyebrow`, `line-clamp-4`, `divide-line` and `bg-highlight` resolve in `tailwind.config.js`. `divide-line` and `bg-highlight` are already used elsewhere. If `line-clamp-4` is not generated, use the core `line-clamp-*` utility (Tailwind ≥3.3). Do not add arbitrary values.

- [ ] **Step 5: Run the frontend tests**

Run: `npm test -- Series ThreadModal`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/pages/Series.jsx frontend/src/pages/Series.test.jsx frontend/src/components/ThreadModal.jsx frontend/src/components/ThreadModal.test.jsx
git commit -m "feat(web): series page with shelf-only book rows and a book-filtered room"
```

---

### Task 10: Routing: retire the work page, redirect legacy URLs

**Files:**
- Create: `frontend/src/pages/WorkRedirect.jsx`, `frontend/src/pages/WorkRedirect.test.jsx`
- Modify: `frontend/src/App.jsx`, `frontend/src/pages/Thread.jsx:51-62`
- Delete: `frontend/src/pages/Work.jsx`

**Interfaces:**
- Consumes: `useWork(id)` (existing; its response now has `series`), `ThreadWithPosts.series` (Task 6).
- Produces the routes:
  - `/series/:slug` → `Series`
  - `/series/:slug/threads/:threadId` → `Thread`
  - `/works/:id` and `/works/:id/threads/:threadId` → `WorkRedirect`

- [ ] **Step 1: Write the failing test** — `WorkRedirect.test.jsx`

```jsx
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter, Routes, Route, useLocation } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

vi.mock('../api/client', () => ({ default: { get: vi.fn() } }))
import client from '../api/client'
import WorkRedirect from './WorkRedirect'

function Where() {
  const loc = useLocation()
  return <p>at {loc.pathname + loc.search}</p>
}

function renderAt(entry) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[entry]}>
        <Routes>
          <Route path="/works/:id" element={<WorkRedirect />} />
          <Route path="/works/:id/threads/:threadId" element={<WorkRedirect />} />
          <Route path="*" element={<Where />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

beforeEach(() => vi.clearAllMocks())

describe('WorkRedirect', () => {
  it('sends an old work URL to its series, at that book', async () => {
    client.get.mockResolvedValue({ data: { id: 'w1', series: { slug: 'red-rising', name: 'Red Rising', kind: 'series' } } })
    renderAt('/works/w1')
    expect(await screen.findByText('at /series/red-rising?book=w1')).toBeInTheDocument()
  })

  it('sends an old thread URL to the same thread in the series room', async () => {
    client.get.mockResolvedValue({ data: { id: 'w1', series: { slug: 'red-rising', name: 'Red Rising', kind: 'series' } } })
    renderAt('/works/w1/threads/t9')
    expect(await screen.findByText('at /series/red-rising/threads/t9')).toBeInTheDocument()
  })

  it('says so when the work does not exist', async () => {
    client.get.mockRejectedValue({ response: { status: 404, data: { detail: 'Work not found' } } })
    renderAt('/works/nope')
    expect(await screen.findByText(/could not find this book/i)).toBeInTheDocument()
  })
})
```

- [ ] **Step 2: Run to verify it fails**

Run: `npm test -- WorkRedirect`
Expected: FAIL — the module does not exist.

- [ ] **Step 3: Implement**

`frontend/src/pages/WorkRedirect.jsx`:

```jsx
import { useEffect } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useWork } from '../api/works'

/**
 * The work page is retired: a book's page is its series. Old links — search
 * history, shared URLs, threads started before series existed — land here and
 * are replaced with their series URL, so the back button skips this hop.
 */
function WorkRedirect() {
  const { id, threadId } = useParams()
  const navigate = useNavigate()
  const { data: work, isError } = useWork(id)

  useEffect(() => {
    if (!work?.series) return
    const target = threadId
      ? `/series/${work.series.slug}/threads/${threadId}`
      : `/series/${work.series.slug}?book=${work.id}`
    navigate(target, { replace: true })
  }, [work, threadId, navigate])

  if (isError) {
    return (
      <main className="max-w-shell mx-auto px-4 py-8">
        <p className="alert-danger">Could not find this book.</p>
      </main>
    )
  }
  return (
    <main className="max-w-shell mx-auto px-4 py-8">
      <div className="animate-pulse h-10 bg-panel w-1/2" />
    </main>
  )
}

export default WorkRedirect
```

In `App.jsx`, replace the `Work` import with `Series` and `WorkRedirect`. Replace the two `/works` routes with:

```jsx
          <Route path="/series/:slug" element={<Series />} />
          <Route path="/series/:slug/threads/:threadId" element={<Thread />} />
          {/* Legacy URLs: the work page is retired; these redirect to the series. */}
          <Route path="/works/:id" element={<WorkRedirect />} />
          <Route path="/works/:id/threads/:threadId" element={<WorkRedirect />} />
```

In `Thread.jsx`:
- The `anchor` becomes `thread?.series?.name || thread?.genre?.name || ''`.
- The segments block becomes:

```jsx
  if (thread.series) {
    segments.push({ label: 'series', to: '/' })
    segments.push({ label: thread.series.name, to: `/series/${thread.series.slug}` })
  } else if (thread.genre) {
```

Delete `frontend/src/pages/Work.jsx`. Then `grep -rn "pages/Work'\|useWorkThreads\|/works/\${" frontend/src` should find only `WorkRedirect.jsx`, the `seriesHref` fallback, and `api/works.js`.

- [ ] **Step 4: Run all frontend tests and the build**

Run: `npm test && npm run build`
Expected: all tests PASS and the build succeeds.

- [ ] **Step 5: Commit**

```bash
git add -A frontend/src
git commit -m "feat(web): retire the work page; legacy work URLs redirect to the series"
```

---

### Task 11: End-to-end pass and docs

**Files:**
- Create: `frontend/e2e/series.spec.js`
- Modify: `frontend/e2e/helpers.js:35-42`, `frontend/e2e/search.spec.js:10,52,56`, `CLAUDE.md`, `docs/superpowers/specs/2026-09-24-series-as-discussion-home-design.md`

**Interfaces:**
- Consumes: the whole stack.

- [ ] **Step 1: Repoint the existing e2e locators**

`e2e/helpers.js` `openFirstSearchResult`: use the locator `a[href^="/series/"]`, and expect the URL to match `/\/series\//`. Update the comment to say "waits for the book's series page". In `e2e/search.spec.js`, replace every `a[href^="/works/"]` with `a[href^="/series/"]`.

- [ ] **Step 2: Write the series e2e** — `frontend/e2e/series.spec.js`

```js
import { test, expect } from '@playwright/test'
import { registerViaUi } from './helpers'

// Search → series page → a thread tagged to book two shows under book two's
// filter and not book three's. Uses live Open Library (Red Rising carries
// `franchise:Red Rising`), so it needs the full stack and network.
test('a thread tagged to one book of a series filters by that book', async ({ page }) => {
  await registerViaUi(page)
  await page.goto('/search?q=red%20rising')
  await page.locator('a[href^="/series/red-rising"]').first().click()
  await expect(page).toHaveURL(/\/series\/red-rising/)

  const books = page.getByRole('list', { name: 'Books in this series' })
  await expect(books.getByRole('heading', { name: 'Golden Son' })).toBeVisible({ timeout: 30_000 })

  await page.getByRole('button', { name: 'Start a Thread' }).click()
  const title = `Golden Son thread ${Date.now()}`
  await page.getByPlaceholder('Thread title').fill(title)
  await page.getByLabel('About which book').selectOption({ label: 'Golden Son' })
  await page.getByRole('button', { name: 'Create Thread' }).click()
  await expect(page).toHaveURL(/\/series\/red-rising\/threads\//)

  await page.goBack()
  const filters = page.getByRole('group', { name: 'Filter by book' })
  await filters.getByRole('button', { name: 'Golden Son' }).click()
  await expect(page.getByRole('link', { name: title })).toBeVisible()
  await filters.getByRole('button', { name: 'Morning Star' }).click()
  await expect(page.getByRole('link', { name: title })).toHaveCount(0)
})
```

- [ ] **Step 3: Run the e2e suite**

With `docker compose up --build` running, and the backfill and migrations from Task 4 applied to the dev DB, run `npm run test:e2e` from `frontend/`.
Expected: `auth`, `search`, `thread`, `reply` and `series` all pass. If Open Library's "red rising" results do not put *Golden Son* and *Morning Star* in the franchise, report that rather than weakening the assertions.

- [ ] **Step 4: Update docs**

In the spec's amended **Surfaces → Search** bullet, replace `carries a \`⊂ ⟨series name⟩\` tag under the author, in \`path\`` with `carries a \`series ⟨name⟩\` line under the author — the word in \`ink-dim\`, the name in \`path\`; text rather than a glyph, because the literal-glyph set is closed`.

In `CLAUDE.md`:
- **Architecture → Backend services.** Add `series_identity.py` (pure tag rules), `series.py` (the only writer of `series`; gives any flushed work a singleton; promotes singletons; `absorb_series` runs inside `merge_works`) and `threads.py` (the shared listing query).
- **Works vs editions.** Add a paragraph after this section:
  - **Series** are the discussion home and a book's only page.
  - `threads.series_id` is the room, and `threads.work_id` is an optional book tag that must be a member of it.
  - Every work has a series; a singleton has no series chrome.
  - Detection order is franchise tag, then the broadest series tag, then singleton.
  - A work in a real series is never moved to another automatically.
  - `works.subjects` is stored one per line (`join_subjects`), because space-joining erased tag boundaries.
- **Upgrading.** Add the series sequence: `alembic upgrade e7b3c9d2a1f4`, then `python -m scripts.backfill_series`, then `alembic upgrade head`. The last migration refuses to run while any work lacks a series, and the thread constraints are `NOT VALID` because of the 10 legacy orphaned threads.
- **Frontend.** `/series/:slug` replaces `/works/:id`, and `/works/...` URLs redirect through `WorkRedirect`.

- [ ] **Step 5: Run everything once more**

Run: from `backend/`, `DATABASE_URL=postgresql+asyncpg://margin:margin@localhost:5432/margin_test pytest -q`; from `frontend/`, `npm test && npm run build`.
Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add frontend/e2e CLAUDE.md docs/superpowers/specs/2026-09-24-series-as-discussion-home-design.md
git commit -m "test(e2e): search to series to book-tagged thread; document series"
```

---

## Known adjacent issues (not in this plan)

- `Profile.jsx` renders shelf rows (`{id, work_id, status}`) through `WorkCard`, which expects a work: the cards have no title or cover and link by the shelf row's id. This predates this plan and is unchanged by it.
- Detection tier 3 (`editions.json` series names) and the whole of slice 2 are deferred. Most works stay singletons until either their Open Library subjects carry a tag or slice 2 lands.
- The 10 orphaned threads are reported by the backfill and left alone.
