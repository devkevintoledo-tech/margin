# Slice 0 — Language-Aware Presentation and Enrichment Repair

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** An English work shows an English cover and an English blurb, and enrichment stops attaching unrelated books to it.

**Architecture:** Replace the flat `completeness_score` sum with a lexicographic *dominance ladder* (`edition_rank`) whose top tier is language, so a richer translation can never speak for a work; invert the cover precedence in `load_work_presentation` so a verified edition cover beats Open Library's language-blind `cover_i`; gate `enrich_work`'s edition attachment on the existing `canonical_key` identity rule; and ship an idempotent repair script for rows already wrong.

**Tech Stack:** FastAPI · async SQLAlchemy 2.0 · Pydantic v2 · Alembic · pytest (`asyncio_mode=auto`) · respx

**Spec:** [`docs/superpowers/specs/2026-09-24-series-as-discussion-home-design.md`](../specs/2026-09-24-series-as-discussion-home-design.md) — this plan implements **slice 0** only. Slices 1–4 (series model, edition family, series pages, search polish) get their own plans.

## Global Constraints

- **No migration in this slice.** No schema changes — every fix is service-level or data repair.
- **Everything is async**: routes, services, DB access. Query with `await db.execute(select(...))` then `.scalar_one_or_none()` / `.scalars()`.
- **Tests never touch the network.** Google Books and Open Library are mocked with `respx`. Backend tests run against the separate `margin_test` database.
- **Test command**, from `backend/` (Postgres must be up: `docker compose up -d db`):
  `DATABASE_URL=postgresql+asyncpg://margin:margin@localhost:5432/margin_test pytest <path> -v`
  Equivalent inside the container:
  `docker compose exec -T backend env DATABASE_URL=postgresql+asyncpg://margin:margin@db:5432/margin_test pytest <path> -v`
- **Scripts** live in `backend/scripts/`, run as `python -m scripts.<name>`, open their own session via `AsyncSessionLocal`, and must be idempotent.
- **Language codes** come from Google Books and are IETF tags: `en`, `en-GB`, `pt-BR`, `de`. Match on the primary subtag only.
- **Ladder tiers deferred to slice 2:** publisher family (tier 2) and blurb quality (tier 4) are *not* in this slice. `edition_rank` implements language → cover → description → completeness; slice 2 inserts the two missing tiers into the same tuple.

---

### Task 1: `edition_rank` — the language-first dominance ladder

**Files:**
- Modify: `backend/app/services/works.py:40-58` (keep `completeness_score`, add `edition_rank` above it)
- Test: `backend/tests/test_edition_rank.py` (create)

**Interfaces:**
- Consumes: `app.models.book.Book` (fields `language`, `cover_url`, `description`, `isbn_13`, `page_count`, `ratings_count`)
- Produces: `edition_rank(edition: Book) -> tuple[int, int, int, int]` — a sort key, highest wins. `completeness_score(edition: Book) -> int` stays public and becomes the ladder's last tier.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_edition_rank.py`:

```python
"""The edition ladder: which edition is allowed to speak for a work.

Pure — no DB, no flush. `Book` instances are constructed in memory, which is
why nothing here needs the `db_session` fixture.
"""

from app.models import Book
from app.services.works import edition_rank


def edition(**kw):
    base = dict(
        source="google_books",
        external_id="x",
        title="Red Rising",
        author="Pierce Brown",
    )
    base.update(kw)
    return Book(**base)


def test_english_beats_a_richer_translation():
    english = edition(language="en")
    german = edition(
        language="de",
        cover_url="https://x/de.jpg",
        description="Der fulminante Auftakt ...",
        isbn_13="9783453316355",
        page_count=560,
        ratings_count=900,
    )
    assert max([german, english], key=edition_rank) is english


def test_unknown_language_loses_to_english_and_beats_a_translation():
    english = edition(language="en")
    unknown = edition(language=None)
    german = edition(language="de")
    assert max([unknown, english], key=edition_rank) is english
    assert max([german, unknown], key=edition_rank) is unknown


def test_regional_english_counts_as_english():
    british = edition(language="en-GB")
    portuguese = edition(language="pt-BR", cover_url="https://x/pt.jpg")
    assert max([portuguese, british], key=edition_rank) is british


def test_within_a_language_a_cover_wins():
    plain = edition(language="en", description="A boy from the mines.")
    illustrated = edition(language="en", cover_url="https://x/en.jpg")
    assert max([plain, illustrated], key=edition_rank) is illustrated


def test_with_equal_covers_a_description_wins():
    bare = edition(language="en", cover_url="https://x/a.jpg")
    described = edition(
        language="en", cover_url="https://x/b.jpg", description="A boy."
    )
    assert max([bare, described], key=edition_rank) is described


def test_completeness_breaks_a_tie_within_a_tier():
    thin = edition(language="en", cover_url="https://x/a.jpg", description="A boy.")
    rich = edition(
        language="en",
        cover_url="https://x/b.jpg",
        description="A boy.",
        isbn_13="9780345539786",
        page_count=382,
        ratings_count=1200,
    )
    assert max([thin, rich], key=edition_rank) is rich


def test_an_empty_language_string_is_treated_as_unknown():
    blank = edition(language="")
    german = edition(language="de", cover_url="https://x/de.jpg")
    assert max([german, blank], key=edition_rank) is blank
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `DATABASE_URL=postgresql+asyncpg://margin:margin@localhost:5432/margin_test pytest tests/test_edition_rank.py -v`
Expected: FAIL — `ImportError: cannot import name 'edition_rank' from 'app.services.works'`

- [ ] **Step 3: Implement the ladder**

In `backend/app/services/works.py`, replace the `completeness_score` block (lines 40–58) with:

```python
# Language tiers. Unknown sits between English and a known translation: a
# missing `language` is an absent fact, not evidence the edition is foreign,
# so it must not be punished as hard as a German printing.
_LANGUAGE_ENGLISH = 2
_LANGUAGE_UNKNOWN = 1
_LANGUAGE_OTHER = 0


def _language_rank(edition: Book) -> int:
    """Rank an edition's language. Google sends IETF tags: `en`, `en-GB`, `pt-BR`."""
    code = (edition.language or "").strip().lower()
    if not code:
        return _LANGUAGE_UNKNOWN
    return _LANGUAGE_ENGLISH if code.split("-")[0] == "en" else _LANGUAGE_OTHER


def completeness_score(edition: Book) -> int:
    """Higher = richer edition. The ladder's last tier, not its whole judgement.

    Once the flat version of this sum decided the representative outright, a
    German edition with cover, blurb, ISBN and page count outscored the English
    printing and put a translated blurb on an English work. It is now only
    consulted when `edition_rank` reaches a tie.
    """
    score = 0
    if edition.cover_url:
        score += 4
    if edition.description:
        score += 1
    if edition.isbn_13:
        score += 1
    if edition.page_count:
        score += 1
    if edition.ratings_count:
        score += 1
    return score


def edition_rank(edition: Book) -> tuple[int, int, int, int]:
    """Sort key for "which edition speaks for this work" — highest wins.

    A dominance ladder, not a sum: each tier is decided before the next is
    consulted, so no amount of richness lets a translation outrank a plain
    English printing. Tiers, in order: language, cover, description,
    completeness.

    The spec's publisher-family and blurb-quality tiers land in slice 2 and
    slot into this tuple between language and cover, and between cover and
    completeness, respectively.
    """
    return (
        _language_rank(edition),
        1 if edition.cover_url else 0,
        1 if edition.description else 0,
        completeness_score(edition),
    )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `DATABASE_URL=postgresql+asyncpg://margin:margin@localhost:5432/margin_test pytest tests/test_edition_rank.py -v`
Expected: PASS — 7 passed

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/works.py backend/tests/test_edition_rank.py
git commit -m "feat(api): rank editions by language before richness"
```

---

### Task 2: the representative edition uses the ladder

**Files:**
- Modify: `backend/app/services/works.py:306` (inside `_refresh_work`)
- Modify: `backend/app/services/enrichment.py:60-62` (comment refers to `completeness_score`)
- Test: `backend/tests/test_work_resolution.py` (append)

**Interfaces:**
- Consumes: `edition_rank` from Task 1
- Produces: no new names. `_refresh_work(db, work, genre_hints=None)` keeps its signature; only its choice of representative changes.

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_work_resolution.py`:

```python
async def test_representative_prefers_english_over_a_richer_translation(db_session):
    """The live Red Rising bug: Heyne (de) outscored Del Rey (en) on richness."""
    import uuid

    from app.models import Book, Work, WorkKind, WorkProvenance, WorkSource
    from app.services.works import _refresh_work

    work = Work(
        source=WorkSource.openlibrary,
        external_id=f"OL{uuid.uuid4().hex[:8]}W",
        canonical_key="red rising\x1fpierce brown",
        title="Red Rising",
        author="Pierce Brown",
        kind=WorkKind.single,
        identity_provenance=WorkProvenance.isbn,
    )
    db_session.add(work)
    await db_session.flush()

    heyne = Book(
        source="google_books",
        external_id="de1",
        title="Red Rising",
        author="Pierce Brown",
        language="de",
        publisher="Heyne Verlag",
        cover_url="https://x/de.jpg",
        description="Der fulminante Auftakt ...",
        isbn_13="9783453316355",
        page_count=560,
        ratings_count=900,
        work_id=work.id,
    )
    del_rey = Book(
        source="google_books",
        external_id="en1",
        title="Red Rising",
        author="Pierce Brown",
        language="en",
        publisher="Del Rey",
        cover_url="https://x/en.jpg",
        work_id=work.id,
    )
    db_session.add_all([heyne, del_rey])
    await db_session.flush()

    await _refresh_work(db_session, work)

    representative = await db_session.get(Book, work.representative_book_id)
    assert representative.external_id == "en1"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `DATABASE_URL=postgresql+asyncpg://margin:margin@localhost:5432/margin_test pytest tests/test_work_resolution.py::test_representative_prefers_english_over_a_richer_translation -v`
Expected: FAIL — `assert 'de1' == 'en1'` (the German edition wins the flat sum 8–4)

- [ ] **Step 3: Wire the ladder into `_refresh_work`**

In `backend/app/services/works.py`, line 306, change:

```python
    best = max(editions, key=completeness_score)
```

to:

```python
    best = max(editions, key=edition_rank)
```

In `backend/app/services/enrichment.py`, update the stale comment at lines 60–61:

```python
    # Re-pick the representative now that placeholder covers are gone, so the
    # edition with real art wins its tier of edition_rank.
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `DATABASE_URL=postgresql+asyncpg://margin:margin@localhost:5432/margin_test pytest tests/test_work_resolution.py -v`
Expected: PASS — the new test plus every existing test in the file.

- [ ] **Step 5: Run the enrichment suite, which also re-picks representatives**

Run: `DATABASE_URL=postgresql+asyncpg://margin:margin@localhost:5432/margin_test pytest tests/test_enrichment.py tests/test_backfill_covers.py -v`
Expected: PASS. `test_enrich_picks_a_representative_with_real_art` still passes — both fixtures are language-less, so the tie falls through to the cover tier exactly as before.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/works.py backend/app/services/enrichment.py backend/tests/test_work_resolution.py
git commit -m "feat(api): let an english edition speak for its work"
```

---

### Task 3: a verified edition cover outranks Open Library's

**Files:**
- Modify: `backend/app/services/works.py:369-422` (`load_work_presentation` — docstring and the `cover_url` expression)
- Modify: `backend/tests/test_works.py:244-265` (the test that asserts the old order)
- Modify: `CLAUDE.md` (the presentation-precedence paragraph in the works-vs-editions section)

**Interfaces:**
- Consumes: nothing new
- Produces: `WorkPresentation` unchanged — `cover_url`, `description`, `edition_count`. Only the precedence inside changes.

- [ ] **Step 1: Rewrite the failing test**

In `backend/tests/test_works.py`, replace `test_cover_prefers_open_library_over_the_representative_edition` (lines 244–265) with:

```python
async def test_cover_prefers_the_representative_edition_over_open_library(db_session):
    """OL's `cover_i` is one arbitrary edition's art — for Red Rising, the
    Spanish RBA printing. A representative that survived `covers.verify` is
    both real and language-checked, so it wins."""
    from app.models import Book
    from app.services.works import load_work_presentation

    work = bare_work(ol_cover_id=7316188)
    db_session.add(work)
    await db_session.flush()
    edition = Book(
        source="google_books",
        external_id="g1",
        title="Red Rising",
        author="Pierce Brown",
        language="en",
        work_id=work.id,
        cover_url="https://books.google.com/real.jpg",
    )
    db_session.add(edition)
    await db_session.flush()
    work.representative_book_id = edition.id
    await db_session.flush()

    got = await load_work_presentation(db_session, [work.id])
    assert got[work.id].cover_url == "https://books.google.com/real.jpg"


async def test_cover_falls_back_to_open_library_when_the_edition_has_none(db_session):
    """The unenriched majority: a work with an edition that carries no art."""
    from app.models import Book
    from app.services.works import load_work_presentation

    work = bare_work(ol_cover_id=7316188)
    db_session.add(work)
    await db_session.flush()
    edition = Book(
        source="google_books",
        external_id="g3",
        title="Red Rising",
        author="Pierce Brown",
        work_id=work.id,
        cover_url=None,
    )
    db_session.add(edition)
    await db_session.flush()
    work.representative_book_id = edition.id
    await db_session.flush()

    got = await load_work_presentation(db_session, [work.id])
    assert got[work.id].cover_url == "https://covers.openlibrary.org/b/id/7316188-L.jpg"
```

- [ ] **Step 2: Run the tests to verify the first fails**

Run: `DATABASE_URL=postgresql+asyncpg://margin:margin@localhost:5432/margin_test pytest tests/test_works.py -k cover -v`
Expected: `test_cover_prefers_the_representative_edition_over_open_library` FAILS (it gets the OL URL); the fallback tests pass.

- [ ] **Step 3: Invert the precedence**

In `backend/app/services/works.py`, in `load_work_presentation`, change the cover expression (line 417):

```python
            cover_url=ol_cover_url(row[1]) or row[2],
```

to:

```python
            cover_url=row[2] or ol_cover_url(row[1]),
```

and replace the cover bullet in the docstring (lines 377–379):

```python
    * cover — the representative edition's, then OL's curated image, then none.
      The edition wins because it has been through `covers.verify` (so Google's
      placeholder PNG is already gone) and through `edition_rank` (so it is the
      work's language, not an arbitrary printing's). OL's `cover_i` is neither:
      for Red Rising it is the Spanish RBA edition. It stays the fallback
      because a work may have no editions at all.
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `DATABASE_URL=postgresql+asyncpg://margin:margin@localhost:5432/margin_test pytest tests/test_works.py tests/test_work_resolution.py tests/test_genre_works.py -v`
Expected: PASS — all of them. `test_a_work_with_no_editions_still_presents` is the guard that the fallback survives.

- [ ] **Step 5: Update CLAUDE.md**

In the works-vs-editions section, replace the sentence beginning "cover is OL's curated image, then the representative edition's, then none" with:

```markdown
cover is the representative edition's (verified real, and in the work's
language), then OL's curated image, then none — OL's `cover_i` is one
arbitrary printing's art, which is how an English work wore a Spanish cover;
```

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/works.py backend/tests/test_works.py CLAUDE.md
git commit -m "feat(api): prefer a verified edition cover over open library's"
```

---

### Task 4: enrichment attaches only editions of the same book

**Files:**
- Modify: `backend/app/services/enrichment.py:41-54`
- Test: `backend/tests/test_enrichment.py` (append)
- Modify: `CLAUDE.md` (the `enrichment.py` entry in the services list)

**Interfaces:**
- Consumes: `canonical_key(title, author) -> str` from `app.services.work_identity`; `Work.canonical_key`, which is stored on *every* work including Open Library ones
- Produces: `enrich_work(db, work)` unchanged in signature; editions that fail the identity check keep `work_id = None`

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_enrichment.py`:

```python
@respx.mock
async def test_enrich_refuses_a_different_book_from_the_same_author(db_session):
    """`intitle:"Red Rising" inauthor:"Pierce Brown"` returns Iron Gold and the
    Sons of Ares graphic novels. None of them is an edition of Red Rising."""
    respx.get(GOOGLE_URL).mock(
        return_value=Response(
            200,
            json={
                "items": [
                    {
                        "id": "g1",
                        "volumeInfo": {
                            "title": "Red Rising",
                            "authors": ["Pierce Brown"],
                            "description": "A boy from the mines.",
                        },
                    },
                    {
                        "id": "g9",
                        "volumeInfo": {
                            "title": "Iron Gold",
                            "authors": ["Pierce Brown"],
                            "description": "A decade after the fall.",
                        },
                    },
                    {
                        "id": "g10",
                        "volumeInfo": {
                            "title": "Pierce Brown's Red Rising: Sons of Ares",
                            "authors": ["Pierce Brown", "Rik Hoskin"],
                            "description": "From the world of the series.",
                        },
                    },
                ]
            },
        )
    )
    work = await seed(db_session)
    await enrich_work(db_session, work)

    attached = {
        b.external_id
        for b in (
            await db_session.execute(select(Book).where(Book.work_id == work.id))
        ).scalars()
    }
    assert attached == {"g1"}


@respx.mock
async def test_enrich_keeps_an_edition_whose_title_is_only_packaging(db_session):
    """"Red Rising (Deluxe Slipcase Edition)" and "Red Rising 01" are the same
    book; `clean_title` strips exactly that packaging."""
    respx.get(GOOGLE_URL).mock(
        return_value=Response(
            200,
            json={
                "items": [
                    {
                        "id": "g2",
                        "volumeInfo": {
                            "title": "Red Rising (Deluxe Slipcase Edition)",
                            "authors": ["Pierce Brown"],
                        },
                    },
                    {
                        "id": "g3",
                        "volumeInfo": {
                            "title": "Red Rising 01",
                            "authors": ["Pierce Brown"],
                        },
                    },
                ]
            },
        )
    )
    work = await seed(db_session)
    await enrich_work(db_session, work)

    attached = {
        b.external_id
        for b in (
            await db_session.execute(select(Book).where(Book.work_id == work.id))
        ).scalars()
    }
    assert attached == {"g2", "g3"}


@respx.mock
async def test_enrich_takes_its_description_only_from_its_own_editions(db_session):
    """The live symptom: the Red Rising work's stored blurb was the Sons of Ares
    graphic novel's, because the wrong edition was attached first."""
    respx.get(GOOGLE_URL).mock(
        return_value=Response(
            200,
            json={
                "items": [
                    {
                        "id": "g9",
                        "volumeInfo": {
                            "title": "Pierce Brown's Red Rising: Sons of Ares",
                            "authors": ["Pierce Brown"],
                            "description": "From the world of the series.",
                        },
                    },
                    {
                        "id": "g1",
                        "volumeInfo": {
                            "title": "Red Rising",
                            "authors": ["Pierce Brown"],
                            "description": "A boy from the mines.",
                        },
                    },
                ]
            },
        )
    )
    work = await seed(db_session)
    await enrich_work(db_session, work)
    assert work.description == "A boy from the mines."
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `DATABASE_URL=postgresql+asyncpg://margin:margin@localhost:5432/margin_test pytest tests/test_enrichment.py -v`
Expected: `test_enrich_refuses_a_different_book_from_the_same_author` FAILS with `assert {'g1','g9','g10'} == {'g1'}`, and `test_enrich_takes_its_description_only_from_its_own_editions` FAILS with the Sons of Ares blurb. The packaging test passes already.

- [ ] **Step 3: Gate the attachment**

In `backend/app/services/enrichment.py`, add the import at the top with the other service imports:

```python
from app.services.work_identity import canonical_key
```

Then replace lines 41–50 (from the `# Imported here:` comment through the `mine = [...]` line) with:

```python
    # Imported here: api/works.py owns edition upsert, and importing it at
    # module scope would close an import cycle through the router.
    from app.api.works import _upsert_editions

    editions, _ = await _upsert_editions(db, results)

    # Google answers `intitle:/inauthor:` with everything the author wrote
    # under that phrase — Iron Gold, the Sons of Ares graphic novels — so an
    # unattached edition is not evidence that it belongs here. It is attached
    # only when it resolves to this work's identity, by the same rule ingest
    # uses. A volume that fails keeps `work_id = None` and is free to be
    # resolved into its own work by a later search.
    mine: list = []
    for edition in editions:
        if edition.work_id is not None:
            if edition.work_id == work.id:
                mine.append(edition)
            continue
        if canonical_key(edition.title, edition.author) != work.canonical_key:
            continue
        edition.work_id = work.id
        mine.append(edition)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `DATABASE_URL=postgresql+asyncpg://margin:margin@localhost:5432/margin_test pytest tests/test_enrichment.py -v`
Expected: PASS — all of them, including the pre-existing `test_enrich_attaches_editions_to_the_work` (both its volumes are titled "Red Rising" by "Pierce Brown", so both still match).

- [ ] **Step 5: Update CLAUDE.md**

In the backend services list, replace the `enrichment.py` clause — "`enrichment.py` fills a work's editions and description from Google on first view of its page" — with:

```markdown
`enrichment.py` fills a work's editions and description from Google on first
view of its page, attaching only volumes whose `canonical_key` matches the
work's — Google answers a title+author query with everything the author wrote,
so an unattached volume is not evidence that it belongs;
```

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/enrichment.py backend/tests/test_enrichment.py CLAUDE.md
git commit -m "feat(api): attach only true editions during enrichment"
```

---

### Task 5: `repair_presentation` — fix the rows already wrong

**Files:**
- Create: `backend/scripts/repair_presentation.py`
- Test: `backend/tests/test_repair_presentation.py` (create)
- Modify: `CLAUDE.md` (the `scripts/` paragraph)
- Modify: `ROADMAP.md` (Phase 1, the local-first search row)

**Interfaces:**
- Consumes: `canonical_key` from `app.services.work_identity`; `_refresh_work` from `app.services.works` (now ladder-driven, Task 2)
- Produces: `repair(session: AsyncSession, commit: bool = True) -> dict[str, int]` with keys `editions_detached`, `descriptions_cleared`, `representatives_repointed`, `representatives_changed`; and `main()` for `python -m scripts.repair_presentation`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_repair_presentation.py`:

```python
"""The repair pass. No network: every fix is a decision about rows we hold."""

import uuid

from sqlalchemy import select

from app.models import Book, Work, WorkKind, WorkProvenance, WorkSource
from scripts.repair_presentation import repair


def make_work(**kw):
    base = dict(
        source=WorkSource.openlibrary,
        external_id=f"OL{uuid.uuid4().hex[:8]}W",
        canonical_key="red rising\x1fpierce brown",
        title="Red Rising",
        author="Pierce Brown",
        kind=WorkKind.single,
        identity_provenance=WorkProvenance.isbn,
    )
    base.update(kw)
    return Work(**base)


def make_edition(**kw):
    base = dict(
        source="google_books",
        external_id=uuid.uuid4().hex[:8],
        title="Red Rising",
        author="Pierce Brown",
    )
    base.update(kw)
    return Book(**base)


async def test_detaches_an_edition_that_is_a_different_book(db_session):
    work = make_work()
    db_session.add(work)
    await db_session.flush()
    true_edition = make_edition(language="en", work_id=work.id)
    iron_gold = make_edition(title="Iron Gold", language="en", work_id=work.id)
    db_session.add_all([true_edition, iron_gold])
    await db_session.flush()

    summary = await repair(db_session, commit=False)

    await db_session.refresh(iron_gold)
    await db_session.refresh(true_edition)
    assert iron_gold.work_id is None
    assert true_edition.work_id == work.id
    assert summary["editions_detached"] == 1


async def test_clears_a_description_inherited_from_a_detached_edition(db_session):
    work = make_work(description="From the world of the series.")
    db_session.add(work)
    await db_session.flush()
    sons_of_ares = make_edition(
        title="Pierce Brown's Red Rising: Sons of Ares",
        description="From the world of the series.",
        work_id=work.id,
    )
    db_session.add(sons_of_ares)
    await db_session.flush()

    summary = await repair(db_session, commit=False)

    await db_session.refresh(work)
    assert work.description is None
    assert summary["descriptions_cleared"] == 1


async def test_repicks_an_english_representative(db_session):
    work = make_work()
    db_session.add(work)
    await db_session.flush()
    heyne = make_edition(
        language="de",
        cover_url="https://x/de.jpg",
        description="Der fulminante Auftakt ...",
        isbn_13="9783453316355",
        page_count=560,
        ratings_count=900,
        work_id=work.id,
    )
    del_rey = make_edition(
        language="en", cover_url="https://x/en.jpg", work_id=work.id
    )
    db_session.add_all([heyne, del_rey])
    await db_session.flush()
    work.representative_book_id = heyne.id
    await db_session.flush()

    summary = await repair(db_session, commit=False)

    await db_session.refresh(work)
    assert work.representative_book_id == del_rey.id
    assert summary["representatives_changed"] == 1


async def test_nulls_a_representative_belonging_to_another_work(db_session):
    """Two works sharing one representative — seen live on the duplicate
    Red Rising rows, where a work with no editions of its own pointed at
    another work's German edition."""
    owner = make_work()
    squatter = make_work(external_id=f"OL{uuid.uuid4().hex[:8]}W")
    db_session.add_all([owner, squatter])
    await db_session.flush()
    edition = make_edition(language="de", work_id=owner.id)
    db_session.add(edition)
    await db_session.flush()
    owner.representative_book_id = edition.id
    squatter.representative_book_id = edition.id
    await db_session.flush()

    summary = await repair(db_session, commit=False)

    await db_session.refresh(squatter)
    assert squatter.representative_book_id is None
    assert summary["representatives_repointed"] == 1


async def test_is_idempotent(db_session):
    work = make_work()
    db_session.add(work)
    await db_session.flush()
    db_session.add_all(
        [
            make_edition(language="en", cover_url="https://x/en.jpg", work_id=work.id),
            make_edition(title="Iron Gold", work_id=work.id),
        ]
    )
    await db_session.flush()

    first = await repair(db_session, commit=False)
    second = await repair(db_session, commit=False)

    assert first["editions_detached"] == 1
    assert second == {
        "editions_detached": 0,
        "descriptions_cleared": 0,
        "representatives_repointed": 0,
        "representatives_changed": 0,
    }


async def test_leaves_a_work_with_no_editions_alone(db_session):
    work = make_work(ol_cover_id=7316188)
    db_session.add(work)
    await db_session.flush()

    summary = await repair(db_session, commit=False)

    await db_session.refresh(work)
    assert work.representative_book_id is None
    assert summary["representatives_changed"] == 0


async def test_detached_editions_are_not_deleted(db_session):
    """A detached volume is a real book we hold; a later search resolves it
    into its own work. Nothing here destroys a row."""
    work = make_work()
    db_session.add(work)
    await db_session.flush()
    iron_gold = make_edition(title="Iron Gold", work_id=work.id)
    db_session.add(iron_gold)
    await db_session.flush()

    await repair(db_session, commit=False)

    still_there = (
        await db_session.execute(
            select(Book).where(Book.external_id == iron_gold.external_id)
        )
    ).scalar_one_or_none()
    assert still_there is not None
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `DATABASE_URL=postgresql+asyncpg://margin:margin@localhost:5432/margin_test pytest tests/test_repair_presentation.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'scripts.repair_presentation'`

- [ ] **Step 3: Write the script**

Create `backend/scripts/repair_presentation.py`:

```python
"""Repair works whose presentation predates the language-aware edition ladder.

Four idempotent passes over rows we already hold — no HTTP, so this is safe to
run at any time and as often as you like:

1. Detach editions whose identity does not match their work. Google answered a
   title+author query with everything the author wrote, and enrichment attached
   all of it: *Iron Gold* and five *Sons of Ares* graphic novels became editions
   of *Red Rising*. Detached rows are kept — a later search resolves them into
   their own works.
2. Clear a work description that came from an edition pass 1 detached, so the
   work stops describing a different book.
3. Null a ``representative_book_id`` pointing at an edition that belongs to
   another work, which duplicate works left behind.
4. Re-pick every work's representative under ``edition_rank``, so an English
   edition speaks for an English work.

Run with::

    python -m scripts.repair_presentation
    # or:
    docker compose exec backend python -m scripts.repair_presentation
"""

from __future__ import annotations

import asyncio
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal
from app.models import Book, Work
from app.services.work_identity import canonical_key
from app.services.works import _refresh_work


async def repair(session: AsyncSession, commit: bool = True) -> dict[str, int]:
    """Repair edition attachment and representative choice. Returns counts."""
    works = {
        work.id: work
        for work in (await session.execute(select(Work))).scalars()
    }
    before: dict[UUID, UUID | None] = {
        work_id: work.representative_book_id for work_id, work in works.items()
    }

    editions = (
        await session.execute(select(Book).where(Book.work_id.is_not(None)))
    ).scalars().all()

    editions_detached = 0
    descriptions_cleared = 0
    for edition in editions:
        work = works.get(edition.work_id)
        if work is None:
            continue
        if canonical_key(edition.title, edition.author) == work.canonical_key:
            continue
        if work.description and work.description == edition.description:
            work.description = None
            descriptions_cleared += 1
        edition.work_id = None
        editions_detached += 1

    await session.flush()

    representatives_repointed = 0
    for work in works.values():
        if work.representative_book_id is None:
            continue
        representative = await session.get(Book, work.representative_book_id)
        if representative is None or representative.work_id != work.id:
            work.representative_book_id = None
            representatives_repointed += 1

    await session.flush()

    for work in works.values():
        await _refresh_work(session, work)

    await session.flush()

    representatives_changed = sum(
        1
        for work_id, work in works.items()
        if work.representative_book_id != before[work_id]
    )

    if commit:
        await session.commit()

    return {
        "editions_detached": editions_detached,
        "descriptions_cleared": descriptions_cleared,
        "representatives_repointed": representatives_repointed,
        "representatives_changed": representatives_changed,
    }


async def main() -> None:
    async with AsyncSessionLocal() as session:
        summary = await repair(session)
    print(
        "Presentation repair complete: "
        f"{summary['editions_detached']} editions detached, "
        f"{summary['descriptions_cleared']} descriptions cleared, "
        f"{summary['representatives_repointed']} stale representatives nulled, "
        f"{summary['representatives_changed']} representatives changed."
    )


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `DATABASE_URL=postgresql+asyncpg://margin:margin@localhost:5432/margin_test pytest tests/test_repair_presentation.py -v`
Expected: PASS — 7 passed

- [ ] **Step 5: Run the whole backend suite**

Run: `DATABASE_URL=postgresql+asyncpg://margin:margin@localhost:5432/margin_test pytest -q`
Expected: PASS. If `test_resolve_works_script.py` or `test_backfill_covers.py` fail, they are asserting a representative chosen by the old flat score — read the failure and fix the assertion, not the ladder.

- [ ] **Step 6: Update the docs**

In `CLAUDE.md`, in the `scripts/` bullet, add `repair_presentation` beside `backfill_cover_urls`:

```markdown
- **`scripts/`** — standalone maintenance entrypoints run with `python -m
  scripts.<name>` (e.g. `backfill_cover_urls`, `repair_presentation`, which
  detaches editions enrichment wrongly attached and re-picks every
  representative under the language ladder). They open their own session via
  `AsyncSessionLocal` and must stay idempotent.
```

In `ROADMAP.md`, append to the **Local-first search & covers** row's description:

```markdown
Edition choice is a language-first dominance ladder (`edition_rank`), so an
English work never shows a translated cover or blurb; `scripts.repair_presentation`
fixes rows that predate it.
```

- [ ] **Step 7: Commit**

```bash
git add backend/scripts/repair_presentation.py backend/tests/test_repair_presentation.py CLAUDE.md ROADMAP.md
git commit -m "feat(api): repair mis-attached editions and stale representatives"
```

---

### Task 6: run the repair against the dev database and verify the page

**Files:** none — this task changes data, not code.

**Interfaces:**
- Consumes: `scripts.repair_presentation` from Task 5

- [ ] **Step 1: Record the current state**

```bash
docker compose exec -T db psql -U margin -d margin -c "
SELECT b.language, count(*) FROM works w JOIN books b ON b.id = w.representative_book_id
GROUP BY 1 ORDER BY 2 DESC;"
```
Expected before repair: `en 198, pt-BR 10, fr 3, de 2, it 1, da 1`.

- [ ] **Step 2: Run the repair**

```bash
docker compose exec backend python -m scripts.repair_presentation
```
Expected: a summary line reporting detached editions (the *Iron Gold* and *Sons of Ares* rows under the Red Rising work) and changed representatives.

- [ ] **Step 3: Re-check the distribution**

```bash
docker compose exec -T db psql -U margin -d margin -c "
SELECT b.language, count(*) FROM works w JOIN books b ON b.id = w.representative_book_id
GROUP BY 1 ORDER BY 2 DESC;"
```
Expected: no non-English representative remains for any work that owns an English edition. A work whose only editions are foreign keeps a foreign representative — that is the ladder falling through, not a failure.

- [ ] **Step 4: Verify the work in the bug report**

```bash
curl -s http://localhost:8000/api/works/d8a75898-627c-4269-8781-06b84fb5345f | python3 -m json.tool
```
Expected: `description` is English, and `cover_url` is no longer `covers.openlibrary.org/b/id/7316188-L.jpg` if an English edition with verified art is attached. If every attached edition lacks a cover, the OL fallback is still correct behaviour — note it and move on; slice 2's `editions.json` switch is what gets real English art.

- [ ] **Step 5: Look at the page**

Open `http://localhost:5173/works/d8a75898-627c-4269-8781-06b84fb5345f` and confirm the title, cover and blurb agree with each other.

---

## Self-review notes

- **Spec coverage (slice 0 only):** language ladder → Tasks 1–2; cover precedence inversion → Task 3; enrichment identity gate → Task 4; `repair_presentation` → Tasks 5–6. Slice 0's spec text also promises the ladder's *shape* accommodates family and blurb tiers — `edition_rank` returns a tuple and its docstring names where they insert.
- **Deliberately out of this plan:** `blurb.py`, `preferred_publisher`, the `editions.json` enrichment switch, the `series` table, and the 10 orphaned threads. All belong to slices 1–2 or are explicitly out of scope in the spec.
- **Naming consistency:** `edition_rank` (Tasks 1, 2, 5 docstring), `completeness_score` (retained, Task 1), `_refresh_work` (Tasks 2, 5), `canonical_key` (Tasks 4, 5), `repair(session, commit=True)` (Tasks 5, 6).
