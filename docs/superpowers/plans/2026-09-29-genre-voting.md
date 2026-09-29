# Genre Voting and Search Filters Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Readers tag books with genres from a curated two-level taxonomy. Those tags (or inferred genres, before anyone votes) drive book display, genre pages and search filters. Librarians can veto a wrong genre, and undo the veto.

**Architecture:** The taxonomy lives in `backend/app/data/genres.yaml`, parsed by a pure module (`genre_inference.py`) and synced into `genres` by a script. Three sources feed one derived table: reader votes (`genre_votes`), machine guesses (`genre_inferences`) and librarian vetoes (`catalog_corrections` with `op='veto_genre'`). The derived table is `work_genres`, and `services/genres.py` is its only writer, through a single set-based `recompute` SQL statement. One SQL view, `effective_work_genres`, holds the effective-genre rule, and every reader goes through it: display, genre pages, `top_genres` and the search filter.

**Tech Stack:** FastAPI, async SQLAlchemy 2.0, asyncpg, Alembic, PyYAML, pytest + respx; React 18, React Query 5, React Router 6, Tailwind, Vitest + RTL, Playwright.

**Spec:** `docs/superpowers/specs/2026-09-29-genre-voting-design.md`. Read it alongside this plan. The spec says *why*; this plan says *how*.

## Global Constraints

- Hierarchy is exactly two levels. A genre with a parent cannot be a parent.
- The eight existing genre rows keep their ids and slugs and become parents: `literary-fiction`, `science-fiction`, `fantasy`, `history`, `philosophy`, `biography`, `mystery`, `poetry`.
- A reader may hold at most **5** genre votes per book (`MAX_GENRES_PER_READER = 5`). The cap applies to new votes only.
- `slug` is globally unique and permanent. Renames change `name` only.
- A retired genre cannot be voted on, inferred, or used as a filter. It stays in the table.
- Vetoes are runtime-only: `runtime_only_reason = "the pipeline has no genre overrides"`. There is **no pipeline or release-contract change** (`pipeline/contract.py` and `COLUMNS` stay as they are).
- `effective_work_genres` is defined **once**, as `EFFECTIVE_WORK_GENRES_VIEW` in `models/genre.py`. The migration and a `Base.metadata` `after_create` listener both execute that constant.
- `author_doc` is declared in the model and in the migration with identical expressions: `to_tsvector('simple', coalesce(author, ''))`.
- `services/genres.py` is the only writer of `work_genres`, `genre_votes` and `genre_inferences`. `services/librarian/` stays the only writer of `catalog_corrections`.
- Tests never touch the network (`respx`). Filter-only search makes **zero** HTTP calls.
- Frontend: tokens only (no raw colors), JetBrains Mono, genres in `text-path`, counts in `text-ink-dim`, no shelf-style pills, no new radii, shadows, sizes or durations. Serif is for book titles only.
- Error sentences the UI shows verbatim:
  - `"You've tagged this book with 5 genres; remove one first."`
  - `"A librarian removed this genre from this book."`
  - `"{name} is no longer in the genre list."`
  - `"Box sets and omnibuses take their books' genres, not their own."`
- Error statuses:

  | Case | Status |
  |---|---|
  | anonymous vote or veto | 401 |
  | reader veto | 403 |
  | unknown work or slug | 404 |
  | cap, veto, retired, collection | 422 |
  | re-veto | 409 |
  | subgenre as a thread room | 422 |
  | bad search filter | 422 with `loc: ["query", <param>]` |

## Review Focus

These are the inputs the spec implies but doesn't spell out, most likely to bite first. Each one has a pinned test in the task named.

1. **Prefixed subjects** (`series:Fantasy Masterworks`, `place:Crimea`, `nyt:...`). OL's non-`genre:` prefixed tags name series, places and people, not genres. Only `genre:` and unprefixed subjects should ever infer. Test in Task 1.
2. **Undo on a book that has both a veto and a series move.** `latest_for_subject` currently treats every work-level fix as one queue. Without scoping, a veto blocks undoing an earlier move, and a move blocks undoing a veto. Scope vetoes to `(work, genre)` and keep them out of the work queue. Test in Task 10.
3. **A taxonomy edit that turns a genre with threads into a subgenre.** D9 says rooms are parents only. `sync_genres` must refuse that edit rather than strand the threads. Test in Task 3.
4. **A reader's votes on a genre that is later vetoed or retired.** Those votes are invisible to the reader and can't be withdrawn from the picker. They must not silently use up cap slots. Test in Task 6.
5. **Bad or odd search input**: a filter with a cold `q`, a punctuation-only `q` with a filter, and a repeated `genre=` value. Validate before ingest so a bad filter never costs an Open Library call. Punctuation-only `q` plus a filter is a browse, and duplicate genres collapse. Test in Task 12.

**Interpretations** (the spec is silent on these; the plan picks and tests them):

- Votes and inferences on a **vetoed** subgenre do not roll up into its parent. Otherwise a vetoed troll tag would still put the book on the parent's page. (Task 4)
- Taxonomy entries take an optional `exclude:` list. A subject containing an excluded phrase never infers that genre, which keeps "Great Britain -- History -- Fiction" off History. This extends the §5.1 file format. (Task 1)
- Google categories are inferred only if the work has no `open_library` **or `catalog`** inference. Catalog subjects are Open Library's, so they rank above Google's categories in the same way. (Task 5)
- `split_work`'s new book gets no copied genre. Its inference comes from its own editions' categories via `_refresh_work`. (Task 5)
- The own-vote marker `●` joins the closed glyph set, recorded in `docs/visual-identity.md`. (Task 14)

---

## File Structure

**Backend — create**
- `backend/app/data/genres.yaml`: the taxonomy.
- `backend/app/services/genre_inference.py`: pure. `Taxonomy`, `parse_taxonomy`, `load_taxonomy`, `shipped_taxonomy`, `infer_genres`.
- `backend/app/services/genre_taxonomy.py`: `sync_genres` (DB).
- `backend/app/services/genres.py`: `recompute`, `set_inferences`, `set_inferences_bulk`, `infer_from_categories`, `absorb`, `vote`, `unvote`, `work_genres_payload`, `top_genres`, `GenreRefused`.
- `backend/app/services/librarian/genres.py`: `veto_genre`, `repoint_vetoes`.
- `backend/app/schemas/genre.py`: `GenreRef`, `GenreChild`, `GenreOut`, `GenreNode`, `WorkGenreOut`, `WorkGenresOut`, `GenreWorkOut`.
- `backend/scripts/sync_genres.py` and `backend/scripts/rebuild_work_genres.py`, beside the existing scripts.
- Migrations: `backend/alembic/versions/c7d2e4f6a8b1_genre_taxonomy_and_votes.py` and `backend/alembic/versions/d8e3f5a7b9c2_retire_work_genre_id.py`.
- Tests:
  - `backend/tests/genre_factories.py`
  - `test_genre_inference.py`
  - `test_genre_taxonomy.py`
  - `test_genre_summary.py`
  - `test_genre_ingest.py`
  - `test_genre_votes.py`
  - `test_genre_api.py`
  - `test_genre_pages.py`
  - `test_genre_vetoes.py`
  - `test_search_filters.py`
  - `test_genre_migrations.py`

**Backend — modify**
- `models/genre.py`, `models/work.py`, `models/correction.py`, `models/__init__.py`
- `services/works.py`, `services/search.py`, `services/catalog_loader.py`, `services/open_library.py`, `services/google_books.py`
- `services/librarian/{__init__,identity,record,undo}.py`
- `api/works.py`, `api/genres.py`, `api/threads.py`, `api/librarian.py`
- `schemas/book.py`, `schemas/librarian.py`
- `tests/conftest.py`, `tests/test_pure_imports.py`
- The existing tests that assert `genre_id` (listed in Task 5)
- `docker-compose.yml`

**Frontend — create**
- `src/api/genres.js`
- `src/components/GenreLine.jsx`, `src/components/GenrePicker.jsx`, `src/components/SearchFilters.jsx`
- Tests beside each
- `e2e/genres.spec.js`

**Frontend — modify**
- `src/api/works.js`
- `src/pages/{Series,Genre,Home,Search}.jsx` and their tests
- `src/components/librarian/reasons.js`

**Docs**: `CLAUDE.md`, `ROADMAP.md`, `docs/visual-identity.md`.

---

### Task 1: Taxonomy file and pure inference

**Files:**
- Create: `backend/app/data/genres.yaml`
- Create: `backend/app/services/genre_inference.py`
- Test: `backend/tests/test_genre_inference.py`
- Modify: `backend/tests/test_pure_imports.py`

**Interfaces:**
- Produces:
  - `GenreEntry(slug: str, name: str, description: str | None, parent: str | None, position: int, match: tuple[str, ...], exclude: tuple[str, ...])`
  - `Taxonomy(entries: tuple[GenreEntry, ...])` with `.by_slug() -> dict[str, GenreEntry]` and `.slugs() -> set[str]`
  - `TaxonomyError(ValueError)`
  - `parse_taxonomy(data: object) -> Taxonomy`
  - `load_taxonomy(path: Path = TAXONOMY_PATH) -> Taxonomy`
  - `shipped_taxonomy() -> Taxonomy` (cached)
  - `infer_genres(subjects: Sequence[str], taxonomy: Taxonomy) -> set[str]`

- [ ] **Step 1: Write the failing tests**

`backend/tests/test_genre_inference.py`:

```python
import pytest

from app.services.genre_inference import (
    Taxonomy, TaxonomyError, infer_genres, load_taxonomy, parse_taxonomy, shipped_taxonomy,
)

TAX = parse_taxonomy([
    {"slug": "fantasy", "name": "Fantasy", "match": ["fantasy"], "children": [
        {"slug": "epic-fantasy", "name": "Epic Fantasy", "match": ["epic fantasy", "fantasy epic"]},
        {"slug": "grimdark", "name": "Grimdark", "match": ["grimdark", "dark fantasy"]},
    ]},
    {"slug": "mystery", "name": "Mystery", "match": ["crime", "mystery"]},
    {"slug": "history", "name": "History", "match": ["history"], "exclude": ["fiction"]},
    {"slug": "literary-fiction", "name": "Literary Fiction", "match": ["literary fiction"]},
])


def test_explicit_genre_tags_win_over_plain_subjects():
    assert infer_genres(["genre:epic fantasy", "Crime"], TAX) == {"epic-fantasy"}


def test_plain_subjects_are_used_when_no_explicit_tag_matches():
    assert infer_genres(["genre:space western", "Fiction, fantasy, epic"], TAX) == {"fantasy", "epic-fantasy"}


def test_needles_match_whole_words_only():
    assert infer_genres(["Crimea", "Crimean War"], TAX) == set()


def test_matching_is_case_and_punctuation_insensitive():
    # "dark fantasy" also contains the word "fantasy": both fire.
    assert infer_genres(["DARK-FANTASY"], TAX) == {"grimdark", "fantasy"}


def test_every_match_is_kept():
    assert infer_genres(["Fantasy", "Crime"], TAX) == {"fantasy", "mystery"}


def test_plain_fiction_infers_nothing():
    assert infer_genres(["Fiction", "Novels"], TAX) == set()


def test_prefixed_non_genre_subjects_never_infer():
    # Review Focus 1: series:, place:, person:, nyt: tags name things, not genres.
    assert infer_genres(["series:Fantasy Masterworks", "place:Crime Alley", "nyt:mystery"], TAX) == set()


def test_exclude_keeps_a_subject_from_inferring_that_genre():
    assert infer_genres(["Great Britain -- History -- Fiction"], TAX) == set()
    assert infer_genres(["Great Britain -- History"], TAX) == {"history"}


def test_an_empty_match_list_is_vote_only():
    tax = parse_taxonomy([{"slug": "cozy", "name": "Cozy", "match": []}])
    assert infer_genres(["cozy"], tax) == set()


@pytest.mark.parametrize("data, message", [
    ([], "non-empty list"),
    ([{"slug": "a", "name": "A"}, {"slug": "a", "name": "B"}], "duplicate slug a"),
    ([{"slug": "a", "name": "A", "children": [
        {"slug": "b", "name": "B", "children": [{"slug": "c", "name": "C"}]}]}], "cannot have subgenres"),
    ([{"slug": "Not A Slug", "name": "A"}], "bad slug"),
    ([{"slug": "a", "name": ""}], "needs a name"),
    ([{"slug": "a", "name": "A", "colour": "red"}], "unknown keys"),
    ([{"slug": "a", "name": "A", "match": ["!!!"]}], "empty match phrase"),
])
def test_validation_rejects_bad_files(data, message):
    with pytest.raises(TaxonomyError, match=message):
        parse_taxonomy(data)


def test_positions_follow_file_order_among_siblings():
    by = TAX.by_slug()
    assert (by["fantasy"].position, by["mystery"].position) == (0, 1)
    assert (by["epic-fantasy"].position, by["grimdark"].position) == (0, 1)
    assert by["grimdark"].parent == "fantasy"


def test_the_shipped_file_loads_and_keeps_the_eight_original_parents():
    tax = load_taxonomy()
    parents = {e.slug for e in tax.entries if e.parent is None}
    assert {"literary-fiction", "science-fiction", "fantasy", "history", "philosophy",
            "biography", "mystery", "poetry"} <= parents
    assert shipped_taxonomy() is shipped_taxonomy()  # cached
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && DATABASE_URL=postgresql+asyncpg://margin:margin@localhost:5432/margin_test pytest tests/test_genre_inference.py -v`
Expected: collection error, `ModuleNotFoundError: app.services.genre_inference`.

- [ ] **Step 3: Implement `genre_inference.py`**

```python
"""The genre taxonomy and subject → genre inference (spec 2026-09-29 §5–6).

Pure: PyYAML and the stdlib only. No settings, HTTP or ORM, so the offline
catalog pipeline can import it later (tests/test_pure_imports.py enforces it).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Sequence

import yaml

from app.services.text import normalize

TAXONOMY_PATH = Path(__file__).resolve().parents[1] / "data" / "genres.yaml"

_SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_KEYS = {"slug", "name", "description", "match", "exclude", "children"}
# OL tags like `series:`, `place:`, `person:`, `nyt:` name things, not genres.
_PREFIX = re.compile(r"^\s*[a-z_]+\s*:", re.IGNORECASE)
_GENRE_PREFIX = re.compile(r"^\s*genre\s*:", re.IGNORECASE)


class TaxonomyError(ValueError):
    """The taxonomy file is malformed; nothing is written."""


@dataclass(frozen=True)
class GenreEntry:
    slug: str
    name: str
    description: str | None
    parent: str | None
    position: int
    match: tuple[str, ...]
    exclude: tuple[str, ...]


@dataclass(frozen=True)
class Taxonomy:
    entries: tuple[GenreEntry, ...]

    def by_slug(self) -> dict[str, GenreEntry]:
        return {e.slug: e for e in self.entries}

    def slugs(self) -> set[str]:
        return {e.slug for e in self.entries}


def _phrases(raw: dict, key: str, slug: str) -> tuple[str, ...]:
    values = raw.get(key, [])
    if not isinstance(values, list) or not all(isinstance(v, str) for v in values):
        raise TaxonomyError(f"{slug}: {key} must be a list of strings")
    cleaned = tuple(normalize(v) for v in values)
    if any(not v for v in cleaned):
        raise TaxonomyError(f"{slug}: empty {key.rstrip('e')} phrase")
    return cleaned


def parse_taxonomy(data: object) -> Taxonomy:
    """Validate and flatten the YAML structure. Raises TaxonomyError."""
    if not isinstance(data, list) or not data:
        raise TaxonomyError("the taxonomy must be a non-empty list")
    entries: list[GenreEntry] = []
    seen: set[str] = set()

    def visit(raw: object, parent: str | None, position: int) -> None:
        if not isinstance(raw, dict):
            raise TaxonomyError(f"entry {raw!r} is not a mapping")
        slug = raw.get("slug")
        if not isinstance(slug, str) or not _SLUG.match(slug):
            raise TaxonomyError(f"bad slug {slug!r}")
        unknown = set(raw) - _KEYS
        if unknown:
            raise TaxonomyError(f"{slug}: unknown keys {sorted(unknown)}")
        if slug in seen:
            raise TaxonomyError(f"duplicate slug {slug}")
        name = raw.get("name")
        if not isinstance(name, str) or not name.strip():
            raise TaxonomyError(f"{slug} needs a name")
        seen.add(slug)
        entries.append(GenreEntry(
            slug=slug, name=name.strip(), description=raw.get("description"), parent=parent,
            position=position, match=_phrases(raw, "match", slug), exclude=_phrases(raw, "exclude", slug),
        ))
        children = raw.get("children", [])
        if not isinstance(children, list):
            raise TaxonomyError(f"{slug}: children must be a list")
        if children and parent is not None:
            raise TaxonomyError(f"{slug}: a subgenre cannot have subgenres")
        for i, child in enumerate(children):
            visit(child, slug, i)

    for i, raw in enumerate(data):
        visit(raw, None, i)
    return Taxonomy(tuple(entries))


def load_taxonomy(path: Path = TAXONOMY_PATH) -> Taxonomy:
    return parse_taxonomy(yaml.safe_load(path.read_text(encoding="utf-8")))


@lru_cache(maxsize=1)
def shipped_taxonomy() -> Taxonomy:
    """The taxonomy the app ships. Cached: the file only changes with a deploy."""
    return load_taxonomy()


def _has(haystack: str, needle: str) -> bool:
    # Both sides are normalize()d: lowercase words separated by single spaces,
    # so padding with spaces gives word-boundary matching ("crime" ∉ "crimea").
    return f" {needle} " in f" {haystack} "


def _matches(pool: list[str], taxonomy: Taxonomy) -> set[str]:
    found: set[str] = set()
    for entry in taxonomy.entries:
        for subject in pool:
            if any(_has(subject, x) for x in entry.exclude):
                continue
            if any(_has(subject, n) for n in entry.match):
                found.add(entry.slug)
                break
    return found


def infer_genres(subjects: Sequence[str], taxonomy: Taxonomy) -> set[str]:
    """Genre slugs a work's subjects (or Google categories) imply.

    Explicit ``genre:`` tags are matched first, and plain subjects only when
    they matched nothing. Other prefixed tags (``series:``, ``place:``…) never
    count. Every match is kept; there is no generic fallback.
    """
    explicit = [normalize(_GENRE_PREFIX.sub("", s)) for s in subjects if _GENRE_PREFIX.match(s)]
    plain = [normalize(s) for s in subjects if not _PREFIX.match(s)]
    for pool in (explicit, plain):
        found = _matches([s for s in pool if s], taxonomy)
        if found:
            return found
    return set()
```

- [ ] **Step 4: Write `backend/app/data/genres.yaml`**

This is Appendix A with `match` lists written, to be pruned in PR review. The eight original descriptions are copied verbatim from the seed migration. Use this content exactly:

```yaml
# MARGIN's genre taxonomy (docs/superpowers/specs/2026-09-29-genre-voting-design.md §5).
#
# slug     permanent and globally unique. Rename with `name`; never change a slug.
# match    subject phrases inference looks for, whole words, case- and
#          punctuation-insensitive. Empty = the genre is only ever reader-voted.
# exclude  a subject containing any of these never infers this genre
#          ("Great Britain -- History -- Fiction" is a novel, not History).
# Order in the file is the display order. Two levels only.
#
# After editing: `python -m scripts.sync_genres`; after changing a match or
# exclude list, also `python -m scripts.rebuild_work_genres --reinfer`.

- slug: literary-fiction
  name: Literary Fiction
  description: Character-driven stories with literary merit.
  match: [literary fiction, fiction literary, psychological fiction, fiction psychological]
  children:
    - {slug: contemporary-literary, name: Contemporary Literary, match: [contemporary fiction]}
    - {slug: historical-fiction, name: Historical Fiction, match: [historical fiction, fiction historical]}
    - {slug: experimental, name: Experimental, match: [experimental fiction]}
    - {slug: family-saga, name: Family Saga, match: [family saga, domestic fiction, fiction family life]}
    - {slug: satire, name: Satire, match: [satire, humorous fiction, fiction humorous]}
    - {slug: short-stories, name: Short Stories, match: [short stories]}
    - {slug: coming-of-age, name: Coming of Age, match: [coming of age, bildungsroman]}

- slug: science-fiction
  name: Science Fiction
  description: Speculative worlds, technology, and futures.
  match: [science fiction, sci fi]
  children:
    - {slug: space-opera, name: Space Opera, match: [space opera]}
    - {slug: hard-sf, name: Hard SF, match: [hard science fiction]}
    - {slug: cyberpunk, name: Cyberpunk, match: [cyberpunk]}
    - {slug: dystopian, name: Dystopian, match: [dystopias, dystopia, dystopian]}
    - {slug: post-apocalyptic, name: Post-Apocalyptic, match: [post apocalyptic, postapocalyptic]}
    - {slug: military-sf, name: Military SF, match: [military science fiction, science fiction military]}
    - {slug: time-travel, name: Time Travel, match: [time travel]}
    - {slug: first-contact, name: First Contact, match: [first contact, human alien encounters]}
    - {slug: climate-fiction, name: Climate Fiction, match: [climate fiction, cli fi]}
    - {slug: alternate-history, name: Alternate History, match: [alternative histories, alternate history, alternative history]}

- slug: fantasy
  name: Fantasy
  description: Magic, myth, and invented worlds.
  match: [fantasy]
  children:
    - {slug: epic-fantasy, name: Epic Fantasy, match: [epic fantasy, high fantasy, fantasy epic]}
    - {slug: grimdark, name: Grimdark, match: [grimdark, dark fantasy]}
    - {slug: urban-fantasy, name: Urban Fantasy, match: [urban fantasy, fantasy urban]}
    - {slug: sword-and-sorcery, name: Sword and Sorcery, match: [sword and sorcery]}
    - {slug: mythic-fantasy, name: Mythic Fantasy, match: [mythic fiction, mythic fantasy]}
    - {slug: fairy-tale-retellings, name: Fairy Tale Retellings, match: [fairy tale retellings, fairy tales adaptations]}
    - {slug: portal-fantasy, name: Portal Fantasy, match: [portal fantasy]}
    - {slug: cozy-fantasy, name: Cozy Fantasy, match: [cozy fantasy]}
    - {slug: magical-realism, name: Magical Realism, match: [magical realism, magic realism]}
    - {slug: historical-fantasy, name: Historical Fantasy, match: [historical fantasy, fantasy historical]}

- slug: horror
  name: Horror
  description: Dread, the uncanny, and what waits in the dark.
  match: [horror, horror tales]
  children:
    - {slug: cosmic-horror, name: Cosmic Horror, match: [cosmic horror, lovecraftian]}
    - {slug: gothic, name: Gothic, match: [gothic fiction, fiction gothic, gothic novels]}
    - {slug: supernatural-horror, name: Supernatural Horror, match: [ghost stories, haunted houses, supernatural horror]}
    - {slug: psychological-horror, name: Psychological Horror, match: [psychological horror]}
    - {slug: folk-horror, name: Folk Horror, match: [folk horror]}
    - {slug: body-horror, name: Body Horror, match: [body horror]}

- slug: mystery
  name: Mystery
  description: Puzzles, crimes, and revelations.
  match: [mystery, detective and mystery stories, mystery and detective stories]
  children:
    - {slug: detective, name: Detective, match: [private investigators, detective fiction]}
    - {slug: cozy-mystery, name: Cozy Mystery, match: [cozy mystery, cozy mysteries, mystery detective cozy]}
    - {slug: police-procedural, name: Police Procedural, match: [police procedural, police procedurals]}
    - {slug: noir, name: Noir, match: [noir, noir fiction]}
    - {slug: hardboiled, name: Hardboiled, match: [hardboiled, hard boiled]}
    - {slug: locked-room, name: Locked Room, match: [locked room, locked room mysteries]}
    - {slug: amateur-sleuth, name: Amateur Sleuth, match: [amateur sleuth, women sleuths]}

- slug: thriller
  name: Thriller
  description: Suspense, stakes, and a clock running down.
  match: [thriller, thrillers, suspense fiction]
  children:
    - {slug: psychological-thriller, name: Psychological Thriller, match: [psychological thriller, thrillers psychological]}
    - {slug: legal-thriller, name: Legal Thriller, match: [legal thriller, legal stories, thrillers legal]}
    - {slug: spy-thriller, name: Spy Thriller, match: [spy stories, espionage, spy thriller]}
    - {slug: techno-thriller, name: Techno-Thriller, match: [techno thriller, technothriller, thrillers technological]}
    - {slug: political-thriller, name: Political Thriller, match: [political thriller, thrillers political, political fiction]}

- slug: romance
  name: Romance
  description: Love stories, and everything in their way.
  match: [romance, love stories, romance fiction]
  children:
    - {slug: contemporary-romance, name: Contemporary Romance, match: [contemporary romance, romance contemporary]}
    - {slug: historical-romance, name: Historical Romance, match: [historical romance, romance historical]}
    - {slug: fantasy-romance, name: Fantasy Romance, match: [fantasy romance, romance fantasy, romantasy, romance paranormal]}
    - {slug: romantic-suspense, name: Romantic Suspense, match: [romantic suspense, romance suspense]}

- slug: adventure
  name: Adventure
  description: Journeys, danger, and the far side of the map.
  match: [adventure stories, adventure fiction, action and adventure]
  children:
    - {slug: nautical, name: Nautical, match: [sea stories, nautical fiction]}
    - {slug: survival, name: Survival, match: [survival fiction, wilderness survival]}
    - {slug: western, name: Western, match: [western stories, westerns, western fiction]}
    - {slug: swashbuckler, name: Swashbuckler, match: [swashbuckler, swashbucklers, pirates]}

- slug: classics
  name: Classics
  description: Books that outlived their century.
  match: [classics, classic literature]
  children:
    - {slug: ancient-classics, name: Ancient Classics, match: [classical literature, greek literature, latin literature]}
    - {slug: nineteenth-century, name: Nineteenth Century, match: [nineteenth century fiction, 19th century fiction, victorian fiction]}
    - {slug: modernist, name: Modernist, match: [modernism literature, modernist fiction]}
    - {slug: epic-poetry, name: Epic Poetry, match: [epic poetry]}

- slug: poetry
  name: Poetry
  description: Language compressed into meaning.
  match: [poetry, poems]
  children:
    - {slug: lyric-poetry, name: Lyric Poetry, match: [lyric poetry]}
    - {slug: narrative-poetry, name: Narrative Poetry, match: [narrative poetry]}
    - {slug: verse-novels, name: Verse Novels, match: [novels in verse, verse novels]}
    - {slug: anthologies, name: Anthologies, match: [poetry collections, poetry anthologies]}

- slug: drama
  name: Drama
  description: Plays, for the stage and the page.
  match: [drama, plays]
  children:
    - {slug: tragedy, name: Tragedy, match: [tragedy, tragedies]}
    - {slug: comedy, name: Comedy, match: [comedies, comedy drama]}
    - {slug: contemporary-drama, name: Contemporary Drama, match: [contemporary drama]}

- slug: graphic-novels
  name: Graphic Novels
  description: Stories told in panels.
  match: [graphic novels, comic books strips, comics]
  children:
    - {slug: superhero, name: Superhero, match: [superheroes, superhero]}
    - {slug: manga, name: Manga, match: [manga]}
    - {slug: graphic-memoir, name: Graphic Memoir, match: [graphic memoir, autobiographical comics]}
    - {slug: bande-dessinee, name: Bande Dessinée, match: [bande dessinee, bandes dessinees]}

- slug: history
  name: History
  description: Non-fiction explorations of the past.
  match: [history, historiography]
  exclude: [fiction]
  children:
    - {slug: ancient-history, name: Ancient History, match: [ancient history, history ancient, antiquities], exclude: [fiction]}
    - {slug: medieval-history, name: Medieval History, match: [medieval history, history medieval, middle ages], exclude: [fiction]}
    - {slug: modern-history, name: Modern History, match: [modern history, history modern], exclude: [fiction]}
    - {slug: military-history, name: Military History, match: [military history, history military], exclude: [fiction]}
    - {slug: social-history, name: Social History, match: [social history, history social], exclude: [fiction]}
    - {slug: history-of-science, name: History of Science, match: [history of science, science history], exclude: [fiction]}

- slug: biography
  name: Biography
  description: Lives examined and recorded.
  match: [biography, biographies]
  exclude: [fiction]
  children:
    - {slug: memoir, name: Memoir, match: [memoir, memoirs], exclude: [fiction]}
    - {slug: autobiography, name: Autobiography, match: [autobiography, autobiographies], exclude: [fiction]}
    - {slug: letters-and-diaries, name: Letters and Diaries, match: [correspondence, diaries, letters], exclude: [fiction]}

- slug: philosophy
  name: Philosophy
  description: Ideas, ethics, and ways of knowing.
  match: [philosophy]
  exclude: [fiction]
  children:
    - {slug: ethics, name: Ethics, match: [ethics], exclude: [fiction]}
    - {slug: political-philosophy, name: Political Philosophy, match: [political philosophy], exclude: [fiction]}
    - {slug: metaphysics, name: Metaphysics, match: [metaphysics], exclude: [fiction]}
    - {slug: epistemology, name: Epistemology, match: [epistemology, knowledge theory of], exclude: [fiction]}
    - {slug: existentialism, name: Existentialism, match: [existentialism], exclude: [fiction]}
    - {slug: eastern-philosophy, name: Eastern Philosophy, match: [eastern philosophy, buddhist philosophy, chinese philosophy, taoism, zen buddhism], exclude: [fiction]}
    - {slug: philosophy-of-mind, name: Philosophy of Mind, match: [philosophy of mind], exclude: [fiction]}

- slug: science
  name: Science
  description: How the world works, and how we found out.
  match: []
  children:
    - {slug: physics, name: Physics, match: [physics], exclude: [fiction]}
    - {slug: biology, name: Biology, match: [biology], exclude: [fiction]}
    - {slug: astronomy, name: Astronomy, match: [astronomy], exclude: [fiction]}
    - {slug: mathematics, name: Mathematics, match: [mathematics], exclude: [fiction]}
    - {slug: popular-science, name: Popular Science, match: [popular science, science popular works], exclude: [fiction]}
    - {slug: nature-writing, name: Nature Writing, match: [nature writing, natural history], exclude: [fiction]}

- slug: society-and-politics
  name: Society & Politics
  description: How people live together, and argue about it.
  match: []
  children:
    - {slug: politics, name: Politics, match: [politics and government, political science], exclude: [fiction]}
    - {slug: economics, name: Economics, match: [economics], exclude: [fiction]}
    - {slug: sociology, name: Sociology, match: [sociology], exclude: [fiction]}
    - {slug: true-crime, name: True Crime, match: [true crime], exclude: [fiction]}
    - {slug: journalism, name: Journalism, match: [journalism, reportage], exclude: [fiction]}
    - {slug: essays, name: Essays, match: [essays]}

- slug: religion-and-mythology
  name: Religion & Mythology
  description: Faith, scripture, and the oldest stories.
  match: [religion]
  exclude: [fiction]
  children:
    - {slug: mythology, name: Mythology, match: [mythology], exclude: [fiction]}
    - {slug: theology, name: Theology, match: [theology], exclude: [fiction]}
    - {slug: religious-texts, name: Religious Texts, match: [sacred books, bible, koran, quran], exclude: [fiction]}
    - {slug: spirituality, name: Spirituality, match: [spirituality, spiritual life], exclude: [fiction]}
```

- [ ] **Step 5: Add the module to the pure-import guard**

In `backend/tests/test_pure_imports.py`, change the import line inside `code` to:

```python
        "import app.services.work_identity, app.services.series_identity, app.services.text, app.services.genre_inference\n"
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `cd backend && pytest tests/test_genre_inference.py tests/test_pure_imports.py -v`
Expected: all PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/app/data/genres.yaml backend/app/services/genre_inference.py backend/tests/test_genre_inference.py backend/tests/test_pure_imports.py
git commit -m "feat(genres): curated taxonomy file and pure subject inference"
```

---

### Task 2: Schema — genre hierarchy, votes, inferences, summary, view, search columns

**Files:**
- Modify: `backend/app/models/genre.py`, `backend/app/models/work.py`, `backend/app/models/correction.py`, `backend/app/models/__init__.py`
- Create: `backend/alembic/versions/c7d2e4f6a8b1_genre_taxonomy_and_votes.py`
- Test: `backend/tests/test_genre_migrations.py` (the Alembic path), `backend/tests/test_genre_summary.py` (model smoke, grown in Task 4)

**Interfaces:**
- Produces:
  - Models: `Genre.parent_id`, `Genre.position`, `Genre.retired_at`
  - Models: `GenreVote(id, user_id, work_id, genre_id, created_at)`, `GenreInference(work_id, genre_id, source)`, `WorkGenre(work_id, genre_id, direct_votes, score, inferred, vetoed)`
  - `INFERENCE_SOURCES = ("open_library", "google", "catalog")`
  - `EFFECTIVE_WORK_GENRES_VIEW: str`
  - `effective_work_genres`: a lightweight `sqlalchemy.table` with columns `work_id, genre_id, score, source`
  - `CorrectionOp.veto_genre`
  - `Work.author_doc`
  - Indexes `ix_works_author_doc` (GIN) and `ix_works_first_publish_year`

- [ ] **Step 1: Write the failing smoke test**

`backend/tests/test_genre_summary.py` (Task 4 appends to it):

```python
from sqlalchemy import select, text

from app.models import CorrectionOp, Genre, GenreInference, WorkGenre, effective_work_genres
from tests.librarian_factories import make_work


async def test_the_view_exists_under_create_all_and_reads_empty(db_session):
    rows = (await db_session.execute(select(effective_work_genres))).all()
    assert rows == []


async def test_genre_hierarchy_columns(db_session):
    parent = Genre(name="Fantasy", slug="fantasy")
    db_session.add(parent)
    await db_session.flush()
    child = Genre(name="Grimdark", slug="grimdark", parent_id=parent.id, position=1)
    db_session.add(child)
    await db_session.flush()
    assert (child.parent_id, child.position, child.retired_at) == (parent.id, 1, None)


async def test_inference_source_is_checked(db_session):
    import pytest
    from sqlalchemy.exc import IntegrityError

    g = Genre(name="Fantasy", slug="fantasy")
    db_session.add(g)
    w = await make_work(db_session, "The Hobbit")
    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            db_session.add(GenreInference(work_id=w.id, genre_id=g.id, source="guess"))
            await db_session.flush()


async def test_author_doc_is_generated(db_session):
    w = await make_work(db_session, "Red Rising", author="Pierce Brown")
    hit = await db_session.scalar(text(
        "SELECT count(*) FROM works WHERE id = :id AND author_doc @@ plainto_tsquery('simple', 'brown')"),
        {"id": w.id})
    assert hit == 1


def test_veto_genre_is_a_correction_op():
    assert CorrectionOp.veto_genre.value == "veto_genre"
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && pytest tests/test_genre_summary.py -v`
Expected: ImportError on `GenreInference` / `effective_work_genres`.

- [ ] **Step 3: Extend `models/genre.py`**

Replace the file with the following. It keeps `Genre.works` for now; Task 5 removes it together with the column.

```python
import uuid
from datetime import datetime

from sqlalchemy import (
    DDL, Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, PrimaryKeyConstraint, String, Text,
    UniqueConstraint, Uuid, column, event, table, text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

INFERENCE_SOURCES = ("open_library", "google", "catalog")


class Genre(Base):
    """A taxonomy entry. Exactly two levels: a parent (a discussion room) or a
    subgenre of one. Rows are written by ``scripts.sync_genres`` from
    ``app/data/genres.yaml``; an entry that leaves the file is retired, not deleted."""

    __tablename__ = "genres"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("genres.id"), nullable=True, index=True)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    works: Mapped[list["Work"]] = relationship("Work", back_populates="genre")  # noqa: F821
    threads: Mapped[list["Thread"]] = relationship("Thread", back_populates="genre")  # noqa: F821


class GenreVote(Base):
    """One reader tagging one book with one genre. Withdrawing deletes the row."""

    __tablename__ = "genre_votes"
    __table_args__ = (UniqueConstraint("user_id", "work_id", "genre_id", name="uq_genre_votes_user_work_genre"),)

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()")
    )
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    work_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("works.id", ondelete="CASCADE"), nullable=False, index=True
    )
    genre_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("genres.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )


class GenreInference(Base):
    """What one ingest source's mapping produced for a work. No roll-up at rest;
    ``source`` lets one path replace its own rows without erasing another's."""

    __tablename__ = "genre_inferences"
    __table_args__ = (
        PrimaryKeyConstraint("work_id", "genre_id", "source", name="pk_genre_inferences"),
        CheckConstraint(
            "source IN ('open_library', 'google', 'catalog')", name="ck_genre_inferences_source"
        ),
    )

    work_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("works.id", ondelete="CASCADE"), nullable=False)
    genre_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("genres.id"), nullable=False)
    source: Mapped[str] = mapped_column(Text, nullable=False)


class WorkGenre(Base):
    """Derived summary. ``services/genres.recompute`` is the only writer."""

    __tablename__ = "work_genres"
    __table_args__ = (
        PrimaryKeyConstraint("work_id", "genre_id", name="pk_work_genres"),
        Index("ix_work_genres_genre_score", "genre_id", text("score DESC")),
    )

    work_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("works.id", ondelete="CASCADE"), nullable=False)
    genre_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("genres.id"), nullable=False)
    direct_votes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)  # readers who voted exactly this
    score: Mapped[int] = mapped_column(Integer, nullable=False, default=0)  # distinct readers, subgenres rolled up
    inferred: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)  # it, or a subgenre, is inferred
    vetoed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


# The effective-genre rule (spec §4.6), in one place. Readers' genres when any
# reader voted a live, unvetoed genre; otherwise the inferred ones. Vetoed and
# retired genres never appear. Executed verbatim by the migration and by the
# create_all listener below. No `%` characters: DDL() would format them.
EFFECTIVE_WORK_GENRES_VIEW = """
CREATE VIEW effective_work_genres AS
WITH voted AS (
    SELECT DISTINCT wg.work_id
    FROM work_genres wg JOIN genres g ON g.id = wg.genre_id
    WHERE wg.score > 0 AND NOT wg.vetoed AND g.retired_at IS NULL
)
SELECT wg.work_id, wg.genre_id, wg.score,
       CASE WHEN v.work_id IS NOT NULL THEN 'readers' ELSE 'inferred' END AS source
FROM work_genres wg
JOIN genres g ON g.id = wg.genre_id AND g.retired_at IS NULL
LEFT JOIN voted v ON v.work_id = wg.work_id
WHERE NOT wg.vetoed
  AND ((v.work_id IS NOT NULL AND wg.score > 0) OR (v.work_id IS NULL AND wg.inferred))
"""

event.listen(Base.metadata, "after_create", DDL(EFFECTIVE_WORK_GENRES_VIEW))
event.listen(Base.metadata, "before_drop", DDL("DROP VIEW IF EXISTS effective_work_genres"))

# For queries only: not a Table in Base.metadata, so create_all never makes it a table.
effective_work_genres = table(
    "effective_work_genres",
    column("work_id", Uuid),
    column("genre_id", Uuid),
    column("score", Integer),
    column("source", Text),
)
```

- [ ] **Step 4: Add `veto_genre` and the `works` search columns**

In `models/correction.py`, add to `CorrectionOp` after `rename_series`:

```python
    veto_genre = "veto_genre"  # runtime-only: the pipeline has no genre overrides
```

In `models/work.py`:
- Add to `__table_args__`:
  - `Index("ix_works_author_doc", "author_doc", postgresql_using="gin")`
  - `Index("ix_works_first_publish_year", "first_publish_year")`
- Add after `search_doc`:

```python
    # Author-only document for the search filter. 'simple', not 'english':
    # names are not words to stem. Declared twice, like search_doc — here for
    # create_all, in migration c7d2e4f6a8b1 for the real database — and the two
    # expressions must stay identical.
    author_doc: Mapped[str] = mapped_column(
        TSVECTOR,
        Computed("to_tsvector('simple', coalesce(author, ''))", persisted=True),
        nullable=False,
    )
```

In `models/__init__.py`:
- Change the genre import to `from app.models.genre import EFFECTIVE_WORK_GENRES_VIEW, INFERENCE_SOURCES, Genre, GenreInference, GenreVote, WorkGenre, effective_work_genres`
- Add those names to `__all__`.

- [ ] **Step 5: Write migration `c7d2e4f6a8b1`**

```python
"""genre taxonomy, votes, inferences, summary and search columns

Revision ID: c7d2e4f6a8b1
Revises: b4e8d2f6a0c9

Downgrade note: Postgres cannot drop an enum value, so `veto_genre` stays on
correction_op_enum after a downgrade. It is harmless: nothing writes it.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.models.genre import EFFECTIVE_WORK_GENRES_VIEW

revision: str = "c7d2e4f6a8b1"
down_revision: Union[str, None] = "b4e8d2f6a0c9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

UUID = postgresql.UUID(as_uuid=True)


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE correction_op_enum ADD VALUE IF NOT EXISTS 'veto_genre'")

    op.add_column("genres", sa.Column("parent_id", UUID, nullable=True))
    op.add_column("genres", sa.Column("position", sa.Integer(), server_default=sa.text("0"), nullable=False))
    op.add_column("genres", sa.Column("retired_at", sa.DateTime(timezone=True), nullable=True))
    op.create_foreign_key("genres_parent_id_fkey", "genres", "genres", ["parent_id"], ["id"])
    op.create_index("ix_genres_parent_id", "genres", ["parent_id"])

    op.create_table(
        "genre_votes",
        sa.Column("id", UUID, server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("user_id", UUID, nullable=False),
        sa.Column("work_id", UUID, nullable=False),
        sa.Column("genre_id", UUID, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["work_id"], ["works.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["genre_id"], ["genres.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "work_id", "genre_id", name="uq_genre_votes_user_work_genre"),
    )
    op.create_index("ix_genre_votes_work_id", "genre_votes", ["work_id"])

    op.create_table(
        "genre_inferences",
        sa.Column("work_id", UUID, nullable=False),
        sa.Column("genre_id", UUID, nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.CheckConstraint("source IN ('open_library', 'google', 'catalog')", name="ck_genre_inferences_source"),
        sa.ForeignKeyConstraint(["work_id"], ["works.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["genre_id"], ["genres.id"]),
        sa.PrimaryKeyConstraint("work_id", "genre_id", "source", name="pk_genre_inferences"),
    )

    op.create_table(
        "work_genres",
        sa.Column("work_id", UUID, nullable=False),
        sa.Column("genre_id", UUID, nullable=False),
        sa.Column("direct_votes", sa.Integer(), nullable=False),
        sa.Column("score", sa.Integer(), nullable=False),
        sa.Column("inferred", sa.Boolean(), nullable=False),
        sa.Column("vetoed", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(["work_id"], ["works.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["genre_id"], ["genres.id"]),
        sa.PrimaryKeyConstraint("work_id", "genre_id", name="pk_work_genres"),
    )
    op.create_index("ix_work_genres_genre_score", "work_genres", ["genre_id", sa.text("score DESC")])
    op.execute(EFFECTIVE_WORK_GENRES_VIEW)

    op.add_column("works", sa.Column(
        "author_doc", postgresql.TSVECTOR(),
        sa.Computed("to_tsvector('simple', coalesce(author, ''))", persisted=True), nullable=False))
    op.create_index("ix_works_author_doc", "works", ["author_doc"], postgresql_using="gin")
    op.create_index("ix_works_first_publish_year", "works", ["first_publish_year"])


def downgrade() -> None:
    op.drop_index("ix_works_first_publish_year", table_name="works")
    op.drop_index("ix_works_author_doc", table_name="works")
    op.drop_column("works", "author_doc")
    op.execute("DROP VIEW IF EXISTS effective_work_genres")
    op.drop_table("work_genres")
    op.drop_table("genre_inferences")
    op.drop_index("ix_genre_votes_work_id", table_name="genre_votes")
    op.drop_table("genre_votes")
    op.drop_index("ix_genres_parent_id", table_name="genres")
    op.drop_constraint("genres_parent_id_fkey", "genres", type_="foreignkey")
    op.drop_column("genres", "retired_at")
    op.drop_column("genres", "position")
    op.drop_column("genres", "parent_id")
    # veto_genre stays on correction_op_enum: Postgres cannot drop an enum value.
```

- [ ] **Step 6: Write the Alembic-path test**

`backend/tests/test_genre_migrations.py`. It builds a scratch database with real Alembic and is skipped when the role cannot `CREATE DATABASE`. Task 5 appends the `genre_id` copy test here.

```python
"""The genre migrations, run by Alembic against a scratch database (not create_all)."""

import os
import subprocess
import sys
import uuid
from pathlib import Path

import asyncpg
import pytest

BACKEND = Path(__file__).resolve().parents[1]


def _plain(url: str) -> str:
    return url.replace("postgresql+asyncpg://", "postgresql://")


@pytest.fixture
async def scratch_db():
    base = os.environ["DATABASE_URL"].rsplit("/", 1)[0]
    name = f"margin_migrate_{uuid.uuid4().hex[:8]}"
    try:
        admin = await asyncpg.connect(_plain(f"{base}/postgres"))
    except Exception as exc:  # pragma: no cover
        pytest.skip(f"cannot reach the postgres database: {exc}")
    try:
        await admin.execute(f'CREATE DATABASE "{name}"')
    except asyncpg.InsufficientPrivilegeError:  # pragma: no cover
        await admin.close()
        pytest.skip("role cannot CREATE DATABASE")
    try:
        yield f"{base}/{name}"
    finally:
        await admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
        await admin.close()


def alembic(url: str, *args: str) -> None:
    env = {**os.environ, "DATABASE_URL": url}
    done = subprocess.run([sys.executable, "-m", "alembic", *args], cwd=BACKEND, env=env,
                          capture_output=True, text=True)
    assert done.returncode == 0, done.stderr


async def test_genre_schema_upgrades_and_downgrades(scratch_db):
    alembic(scratch_db, "upgrade", "c7d2e4f6a8b1")
    conn = await asyncpg.connect(_plain(scratch_db))
    try:
        assert await conn.fetchval("SELECT count(*) FROM effective_work_genres") == 0
        assert await conn.fetchval("SELECT 'veto_genre'::correction_op_enum::text") == "veto_genre"
        assert await conn.fetchval("SELECT count(*) FROM genres WHERE parent_id IS NULL") == 8
    finally:
        await conn.close()
    alembic(scratch_db, "downgrade", "b4e8d2f6a0c9")
    alembic(scratch_db, "upgrade", "c7d2e4f6a8b1")  # re-upgrade must not trip on leftovers
```

- [ ] **Step 7: Run the tests**

Run: `cd backend && pytest tests/test_genre_summary.py tests/test_genre_migrations.py -v`
Expected: PASS. `test_genre_migrations` may SKIP only if the role lacks CREATEDB. The compose `margin` role is a superuser, so it should run.

- [ ] **Step 8: Run the whole backend suite**

Run: `cd backend && pytest -q`
Expected: all PASS. If the before-drop listener or the view breaks `drop_all`, it shows up here.

- [ ] **Step 9: Commit**

```bash
git add backend/app/models backend/alembic/versions/c7d2e4f6a8b1_genre_taxonomy_and_votes.py backend/tests/test_genre_summary.py backend/tests/test_genre_migrations.py
git commit -m "feat(genres): hierarchy, votes, inferences, work_genres summary and effective view"
```

---

### Task 3: `sync_genres` service and script

**Files:**
- Create: `backend/app/services/genre_taxonomy.py`
- Create: `backend/scripts/sync_genres.py`
- Modify: `docker-compose.yml` (the backend `command`)
- Modify: `backend/tests/conftest.py` (a `taxonomy` fixture)
- Test: `backend/tests/test_genre_taxonomy.py`

**Interfaces:**
- Consumes: `Taxonomy`, `shipped_taxonomy`, `TaxonomyError` (Task 1); the `Genre` columns (Task 2).
- Produces:
  - `async def sync_genres(db: AsyncSession, taxonomy: Taxonomy) -> list[str]`. It returns human-readable change lines and raises `TaxonomyError` before writing anything.
  - conftest fixture `taxonomy`: syncs the shipped file into the test DB and returns `dict[slug, Genre]`.

- [ ] **Step 1: Write the failing tests**

`backend/tests/test_genre_taxonomy.py`:

```python
import pytest
from sqlalchemy import select

from app.models import Genre, Thread
from app.services.genre_inference import TaxonomyError, parse_taxonomy, shipped_taxonomy
from app.services.genre_taxonomy import sync_genres
from tests.librarian_factories import make_user

TWO = parse_taxonomy([
    {"slug": "fantasy", "name": "Fantasy", "children": [{"slug": "grimdark", "name": "Grimdark"}]},
    {"slug": "mystery", "name": "Mystery"},
])


async def rows(db):
    return {g.slug: g for g in (await db.execute(select(Genre))).scalars()}


async def test_sync_creates_the_tree(db_session):
    changes = await sync_genres(db_session, TWO)
    got = await rows(db_session)
    assert got["grimdark"].parent_id == got["fantasy"].id
    assert (got["fantasy"].position, got["mystery"].position) == (0, 1)
    assert any("grimdark" in c for c in changes)


async def test_sync_is_idempotent(db_session):
    await sync_genres(db_session, TWO)
    assert await sync_genres(db_session, TWO) == []


async def test_existing_rows_keep_their_ids(db_session):
    old = Genre(name="Fantasy", slug="fantasy")
    db_session.add(old)
    await db_session.flush()
    await sync_genres(db_session, TWO)
    assert (await rows(db_session))["fantasy"].id == old.id


async def test_an_entry_missing_from_the_file_is_retired_then_unretired(db_session):
    await sync_genres(db_session, TWO)
    one = parse_taxonomy([{"slug": "fantasy", "name": "Fantasy", "children": [{"slug": "grimdark", "name": "Grimdark"}]}])
    changes = await sync_genres(db_session, one)
    assert (await rows(db_session))["mystery"].retired_at is not None
    assert any("retired mystery" in c for c in changes)
    await sync_genres(db_session, TWO)
    assert (await rows(db_session))["mystery"].retired_at is None


async def test_rename_changes_the_name_only(db_session):
    await sync_genres(db_session, TWO)
    before = (await rows(db_session))["mystery"].id
    renamed = parse_taxonomy([
        {"slug": "fantasy", "name": "Fantasy", "children": [{"slug": "grimdark", "name": "Grimdark"}]},
        {"slug": "mystery", "name": "Mystery & Crime"},
    ])
    await sync_genres(db_session, renamed)
    after = (await rows(db_session))["mystery"]
    assert (after.id, after.name) == (before, "Mystery & Crime")


async def test_a_genre_with_threads_cannot_become_a_subgenre(db_session):
    # Review Focus 3: rooms are parents only (D9).
    await sync_genres(db_session, TWO)
    user = await make_user(db_session)
    db_session.add(Thread(title="t", user_id=user.id, genre_id=(await rows(db_session))["mystery"].id))
    await db_session.flush()
    demoted = parse_taxonomy([{"slug": "fantasy", "name": "Fantasy", "children": [
        {"slug": "grimdark", "name": "Grimdark"}, {"slug": "mystery", "name": "Mystery"}]}])
    with pytest.raises(TaxonomyError, match="mystery has discussion threads"):
        await sync_genres(db_session, demoted)
    assert (await rows(db_session))["mystery"].parent_id is None  # nothing written


async def test_a_parent_with_subgenres_in_the_db_cannot_become_a_child(db_session):
    await sync_genres(db_session, TWO)
    flipped = parse_taxonomy([{"slug": "mystery", "name": "Mystery", "children": [
        {"slug": "fantasy", "name": "Fantasy"}]}, {"slug": "grimdark", "name": "Grimdark"}])
    # grimdark moves to top level in the same file, so this one is legal:
    await sync_genres(db_session, flipped)
    got = await rows(db_session)
    assert got["fantasy"].parent_id == got["mystery"].id and got["grimdark"].parent_id is None


async def test_the_shipped_taxonomy_syncs(db_session):
    await sync_genres(db_session, shipped_taxonomy())
    got = await rows(db_session)
    assert got["epic-fantasy"].parent_id == got["fantasy"].id
    assert all(g.parent_id is None or got_by_id(got, g.parent_id).parent_id is None for g in got.values())


def got_by_id(got, gid):
    return next(g for g in got.values() if g.id == gid)
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && pytest tests/test_genre_taxonomy.py -v`
Expected: `ModuleNotFoundError: app.services.genre_taxonomy`.

- [ ] **Step 3: Implement `services/genre_taxonomy.py`**

```python
"""Syncing ``app/data/genres.yaml`` into the ``genres`` table (spec §5.2)."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Genre, Thread
from app.services.genre_inference import Taxonomy, TaxonomyError


async def sync_genres(db: AsyncSession, taxonomy: Taxonomy) -> list[str]:
    """Upsert every entry by slug, retire rows missing from the file, unretire
    ones that reappear. Idempotent. Validates everything before writing."""
    existing = {g.slug: g for g in (await db.execute(select(Genre))).scalars()}
    entries = taxonomy.by_slug()

    # A thread's room must stay a parent (D9): refuse, don't strand discussion.
    for entry in taxonomy.entries:
        row = existing.get(entry.slug)
        if entry.parent is not None and row is not None and row.parent_id is None:
            threads = await db.scalar(select(func.count()).select_from(Thread).where(Thread.genre_id == row.id))
            if threads:
                raise TaxonomyError(f"{entry.slug} has discussion threads and cannot become a subgenre")

    changes: list[str] = []
    now = datetime.now(timezone.utc)
    # Parents first, so a child can point at its parent's id.
    for entry in sorted(taxonomy.entries, key=lambda e: e.parent is not None):
        row = existing.get(entry.slug)
        parent_id = existing[entry.parent].id if entry.parent else None
        if row is None:
            row = Genre(slug=entry.slug, name=entry.name, description=entry.description,
                        parent_id=parent_id, position=entry.position)
            db.add(row)
            await db.flush()
            existing[entry.slug] = row
            changes.append(f"+ {entry.slug}")
            continue
        wanted = {"name": entry.name, "description": entry.description,
                  "parent_id": parent_id, "position": entry.position}
        diff = [k for k, v in wanted.items() if getattr(row, k) != v]
        for key in diff:
            setattr(row, key, wanted[key])
        if row.retired_at is not None:
            row.retired_at = None
            diff.append("unretired")
        if diff:
            changes.append(f"~ {entry.slug} ({', '.join(diff)})")

    for slug, row in existing.items():
        if slug not in entries and row.retired_at is None:
            row.retired_at = now
            changes.append(f"- retired {slug}")
    await db.flush()
    return changes
```

- [ ] **Step 4: Write `backend/scripts/sync_genres.py`**

Match the other scripts' shape. Read `backend/scripts/grant_librarian.py` first and copy its `asyncio.run(main())` / `AsyncSessionLocal` pattern.

```python
"""Sync app/data/genres.yaml into the genres table. Idempotent.

    python -m scripts.sync_genres

Compose runs it after `alembic upgrade head`. After changing a `match` or
`exclude` list, or moving a genre to another parent, also run
`python -m scripts.rebuild_work_genres --reinfer`.
"""

import asyncio
import sys

from app.database import AsyncSessionLocal
from app.services.genre_inference import TaxonomyError, load_taxonomy
from app.services.genre_taxonomy import sync_genres


async def main() -> int:
    try:
        taxonomy = load_taxonomy()
    except TaxonomyError as exc:
        print(f"genres.yaml is invalid: {exc}", file=sys.stderr)
        return 1
    async with AsyncSessionLocal() as session:
        try:
            changes = await sync_genres(session, taxonomy)
        except TaxonomyError as exc:
            print(f"refused: {exc}", file=sys.stderr)
            return 1
        await session.commit()
    print("\n".join(changes) if changes else "genres already in sync")
    if any("parent_id" in c for c in changes):
        print("a genre changed parent: run `python -m scripts.rebuild_work_genres`")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
```

- [ ] **Step 5: Wire compose and the test fixture**

In `docker-compose.yml`, change the backend command to:

```yaml
      sh -c "alembic upgrade head && python -m scripts.sync_genres && uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload"
```

In `backend/tests/conftest.py`, append:

```python
@pytest_asyncio.fixture
async def taxonomy(db_session):
    """The shipped taxonomy, synced: ``{slug: Genre}``. Opt-in — most tests need no genres."""
    from sqlalchemy import select as _select

    from app.services.genre_inference import shipped_taxonomy
    from app.services.genre_taxonomy import sync_genres

    await sync_genres(db_session, shipped_taxonomy())
    return {g.slug: g for g in (await db_session.execute(_select(Genre))).scalars()}
```

- [ ] **Step 6: Run the tests**

Run: `cd backend && pytest tests/test_genre_taxonomy.py -v`
Expected: PASS.

Then run it by hand against the dev DB: `docker compose exec backend python -m scripts.sync_genres`
Expected: a list of `+ …` lines, then `genres already in sync` on a second run.

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/genre_taxonomy.py backend/scripts/sync_genres.py backend/tests/test_genre_taxonomy.py backend/tests/conftest.py docker-compose.yml
git commit -m "feat(genres): sync the taxonomy file into genres, retiring removed entries"
```

---

### Task 4: `services/genres.py` core — recompute and inferences

**Files:**
- Create: `backend/app/services/genres.py`
- Create: `backend/tests/genre_factories.py`
- Test: `backend/tests/test_genre_summary.py` (append)

**Interfaces:**
- Consumes: the models (Task 2), `shipped_taxonomy`, `infer_genres`.
- Produces:
  - `async def recompute(db, work_ids: Iterable[UUID] | None) -> None`. `None` means every work.
  - `async def set_inferences(db, work: Work, slugs: Iterable[str], source: str) -> None`
  - `async def set_inferences_bulk(db, slugs_by_work: Mapping[UUID, Iterable[str]], source: str) -> None`
  - `async def infer_from_subjects(db, work: Work, subjects: Sequence[str], source: str) -> None`
  - `async def infer_from_categories(db, work: Work, categories: Sequence[str]) -> None`
- Test helpers (`tests/genre_factories.py`):
  - `make_genre(db, slug, parent=None, retired=False) -> Genre`
  - `add_vote(db, user, work, genre) -> GenreVote`
  - `add_veto(db, librarian, work, genre) -> CatalogCorrection`
  - `effective(db, work) -> dict[str, tuple[int, str]]`
  - `summary(db) -> set[tuple]`

- [ ] **Step 1: Write the factories**

`backend/tests/genre_factories.py`:

```python
"""Row builders for genre tests. Votes and vetoes are inserted directly here so
the effective-genre rule can be tested before the services that write them."""

from datetime import datetime, timezone

from sqlalchemy import select

from app.models import CatalogCorrection, CorrectionOp, Genre, GenreVote, WorkGenre, effective_work_genres


async def make_genre(db, slug, parent=None, retired=False, position=0):
    g = Genre(name=slug.replace("-", " ").title(), slug=slug, parent_id=parent.id if parent else None,
              position=position, retired_at=datetime.now(timezone.utc) if retired else None)
    db.add(g)
    await db.flush()
    return g


async def add_vote(db, user, work, genre):
    v = GenreVote(user_id=user.id, work_id=work.id, genre_id=genre.id)
    db.add(v)
    await db.flush()
    return v


async def add_veto(db, librarian, work, genre, reverted=False):
    c = CatalogCorrection(
        op=CorrectionOp.veto_genre, user_id=librarian.id, reason="wrong genre",
        payload={"work_id": str(work.id), "genre_id": str(genre.id)}, override=None,
        runtime_only_reason="the pipeline has no genre overrides", work_id=work.id,
        reverted_at=datetime.now(timezone.utc) if reverted else None,
    )
    db.add(c)
    await db.flush()
    return c


async def effective(db, work):
    """``{slug: (score, source)}`` straight from the view."""
    rows = (await db.execute(
        select(Genre.slug, effective_work_genres.c.score, effective_work_genres.c.source)
        .join(Genre, Genre.id == effective_work_genres.c.genre_id)
        .where(effective_work_genres.c.work_id == work.id))).all()
    return {slug: (score, source) for slug, score, source in rows}


async def summary(db):
    rows = (await db.execute(select(WorkGenre))).scalars().all()
    return {(r.work_id, r.genre_id, r.direct_votes, r.score, r.inferred, r.vetoed) for r in rows}
```

- [ ] **Step 2: Write the failing rule tests**

Append to `backend/tests/test_genre_summary.py`:

```python
from app.services import genres as genres_service
from tests.genre_factories import add_veto, add_vote, effective, make_genre, summary
from tests.librarian_factories import make_user


async def tree(db):
    fantasy = await make_genre(db, "fantasy")
    epic = await make_genre(db, "epic-fantasy", parent=fantasy)
    grim = await make_genre(db, "grimdark", parent=fantasy, position=1)
    mystery = await make_genre(db, "mystery", position=1)
    return fantasy, epic, grim, mystery


async def test_inferred_genres_show_when_nobody_voted(db_session):
    fantasy, epic, grim, mystery = await tree(db_session)
    w = await make_work(db_session, "The Hobbit")
    await genres_service.set_inferences(db_session, w, {"epic-fantasy"}, "open_library")
    assert await effective(db_session, w) == {"epic-fantasy": (0, "inferred"), "fantasy": (0, "inferred")}


async def test_votes_beat_inference(db_session):
    fantasy, epic, grim, mystery = await tree(db_session)
    w = await make_work(db_session, "The Hobbit")
    reader = await make_user(db_session)
    await genres_service.set_inferences(db_session, w, {"mystery"}, "open_library")
    await add_vote(db_session, reader, w, grim)
    await genres_service.recompute(db_session, [w.id])
    assert await effective(db_session, w) == {"grimdark": (1, "readers"), "fantasy": (1, "readers")}


async def test_roll_up_counts_one_reader_once(db_session):
    fantasy, epic, grim, _ = await tree(db_session)
    w = await make_work(db_session, "The Hobbit")
    a, b = await make_user(db_session), await make_user(db_session)
    for genre in (fantasy, epic, grim):
        await add_vote(db_session, a, w, genre)
    await add_vote(db_session, b, w, epic)
    await genres_service.recompute(db_session, [w.id])
    got = await effective(db_session, w)
    assert got["fantasy"] == (2, "readers")
    assert got["epic-fantasy"] == (2, "readers")
    row = next(r for r in await summary(db_session) if r[1] == fantasy.id)
    assert row[2] == 1  # direct_votes: only `a` voted fantasy itself


async def test_a_veto_hides_a_genre_from_both_branches(db_session):
    fantasy, epic, grim, mystery = await tree(db_session)
    lib = await make_user(db_session, librarian=True)
    inferred_only = await make_work(db_session, "Inferred")
    await genres_service.set_inferences(db_session, inferred_only, {"mystery", "grimdark"}, "open_library")
    await add_veto(db_session, lib, inferred_only, mystery)
    await genres_service.recompute(db_session, [inferred_only.id])
    assert "mystery" not in await effective(db_session, inferred_only)

    voted = await make_work(db_session, "Voted")
    await add_vote(db_session, await make_user(db_session), voted, mystery)
    await add_vote(db_session, await make_user(db_session), voted, grim)
    await add_veto(db_session, lib, voted, mystery)
    await genres_service.recompute(db_session, [voted.id])
    assert set(await effective(db_session, voted)) == {"grimdark", "fantasy"}


async def test_a_vetoed_subgenre_does_not_roll_up(db_session):
    fantasy, epic, grim, _ = await tree(db_session)
    lib = await make_user(db_session, librarian=True)
    w = await make_work(db_session, "Cookbook")
    await add_vote(db_session, await make_user(db_session), w, grim)
    await add_veto(db_session, lib, w, grim)
    await genres_service.recompute(db_session, [w.id])
    assert await effective(db_session, w) == {}


async def test_only_votes_on_vetoed_genres_fall_back_to_inference(db_session):
    fantasy, epic, grim, mystery = await tree(db_session)
    lib = await make_user(db_session, librarian=True)
    w = await make_work(db_session, "Troll target")
    await genres_service.set_inferences(db_session, w, {"mystery"}, "open_library")
    await add_vote(db_session, await make_user(db_session), w, grim)
    await add_veto(db_session, lib, w, grim)
    await genres_service.recompute(db_session, [w.id])
    assert await effective(db_session, w) == {"mystery": (0, "inferred")}


async def test_a_reverted_veto_does_not_hold(db_session):
    fantasy, *_ = await tree(db_session)
    lib = await make_user(db_session, librarian=True)
    w = await make_work(db_session, "Back again")
    await genres_service.set_inferences(db_session, w, {"fantasy"}, "open_library")
    await add_veto(db_session, lib, w, fantasy, reverted=True)
    await genres_service.recompute(db_session, [w.id])
    assert "fantasy" in await effective(db_session, w)


async def test_retired_genres_drop_out(db_session):
    fantasy, epic, grim, mystery = await tree(db_session)
    old = await make_genre(db_session, "weird-west", retired=True)
    w = await make_work(db_session, "Weird")
    await add_vote(db_session, await make_user(db_session), w, old)
    await genres_service.set_inferences(db_session, w, {"mystery"}, "open_library")
    assert await effective(db_session, w) == {"mystery": (0, "inferred")}


async def test_set_inferences_ignores_retired_and_unknown_slugs(db_session):
    await make_genre(db_session, "weird-west", retired=True)
    w = await make_work(db_session, "Weird")
    await genres_service.set_inferences(db_session, w, {"weird-west", "no-such"}, "open_library")
    assert await summary(db_session) == set()


async def test_one_source_replaces_only_its_own_rows(db_session):
    fantasy, epic, grim, mystery = await tree(db_session)
    w = await make_work(db_session, "Two sources")
    await genres_service.set_inferences(db_session, w, {"mystery"}, "google")
    await genres_service.set_inferences(db_session, w, {"grimdark"}, "open_library")
    await genres_service.set_inferences(db_session, w, set(), "open_library")
    assert await effective(db_session, w) == {"mystery": (0, "inferred")}


async def test_recompute_everything_matches_per_work_recompute(db_session):
    fantasy, epic, grim, mystery = await tree(db_session)
    works = [await make_work(db_session, f"Book {i}") for i in range(3)]
    reader = await make_user(db_session)
    await add_vote(db_session, reader, works[0], epic)
    await genres_service.set_inferences(db_session, works[1], {"mystery"}, "catalog")
    await genres_service.recompute(db_session, [w.id for w in works])
    incremental = await summary(db_session)
    await genres_service.recompute(db_session, None)
    assert await summary(db_session) == incremental
```

- [ ] **Step 3: Run to verify they fail**

Run: `cd backend && pytest tests/test_genre_summary.py -v`
Expected: `ModuleNotFoundError: app.services.genres`.

- [ ] **Step 4: Implement `services/genres.py` (core half)**

```python
"""Genres on works (spec 2026-09-29 §4.5–7).

The only writer of ``work_genres``, ``genre_votes`` and ``genre_inferences``.
Every change to a source — a vote, an inference, a veto, a merge — ends in
``recompute`` in the caller's transaction, so the summary is never stale.
Readers never re-derive the effective-genre rule: they read the
``effective_work_genres`` view.
"""

from __future__ import annotations

from typing import Iterable, Mapping, Sequence
from uuid import UUID

from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import INFERENCE_SOURCES, GenreInference, Work
from app.services.genre_inference import infer_genres, shipped_taxonomy

# One statement pair for one work, many, or all (:all). Votes and inferences
# on a vetoed genre count for that genre's own row (a librarian sees them) but
# never roll up into its parent.
_SCOPE = "(CAST(:all AS boolean) OR {col} = ANY(CAST(:ids AS uuid[])))"

_DELETE = text(f"DELETE FROM work_genres WHERE {_SCOPE.format(col='work_id')}")

_INSERT = text(f"""
WITH vetoes AS (
    SELECT DISTINCT c.work_id, CAST(c.payload ->> 'genre_id' AS uuid) AS genre_id
    FROM catalog_corrections c
    WHERE c.op = 'veto_genre' AND c.reverted_at IS NULL AND c.work_id IS NOT NULL
      AND {_SCOPE.format(col='c.work_id')}
),
credits AS (
    SELECT v.work_id, v.user_id, v.genre_id, true AS direct
    FROM genre_votes v WHERE {_SCOPE.format(col='v.work_id')}
    UNION ALL
    SELECT v.work_id, v.user_id, g.parent_id, false
    FROM genre_votes v JOIN genres g ON g.id = v.genre_id
    WHERE g.parent_id IS NOT NULL AND {_SCOPE.format(col='v.work_id')}
      AND NOT EXISTS (SELECT 1 FROM vetoes x WHERE x.work_id = v.work_id AND x.genre_id = v.genre_id)
),
scores AS (
    SELECT work_id, genre_id, count(DISTINCT user_id) AS score,
           count(*) FILTER (WHERE direct) AS direct_votes
    FROM credits GROUP BY work_id, genre_id
),
inferred AS (
    SELECT i.work_id, i.genre_id FROM genre_inferences i WHERE {_SCOPE.format(col='i.work_id')}
    UNION
    SELECT i.work_id, g.parent_id
    FROM genre_inferences i JOIN genres g ON g.id = i.genre_id
    WHERE g.parent_id IS NOT NULL AND {_SCOPE.format(col='i.work_id')}
      AND NOT EXISTS (SELECT 1 FROM vetoes x WHERE x.work_id = i.work_id AND x.genre_id = i.genre_id)
),
keys AS (
    SELECT work_id, genre_id FROM scores
    UNION SELECT work_id, genre_id FROM inferred
    UNION SELECT work_id, genre_id FROM vetoes
)
INSERT INTO work_genres (work_id, genre_id, direct_votes, score, inferred, vetoed)
SELECT k.work_id, k.genre_id, coalesce(s.direct_votes, 0), coalesce(s.score, 0),
       i.work_id IS NOT NULL, x.work_id IS NOT NULL
FROM keys k
JOIN works w ON w.id = k.work_id AND w.merged_into_id IS NULL
LEFT JOIN scores s ON s.work_id = k.work_id AND s.genre_id = k.genre_id
LEFT JOIN inferred i ON i.work_id = k.work_id AND i.genre_id = k.genre_id
LEFT JOIN vetoes x ON x.work_id = k.work_id AND x.genre_id = k.genre_id
""")


async def recompute(db: AsyncSession, work_ids: Iterable[UUID] | None) -> None:
    """Rewrite ``work_genres`` for these works (``None`` = every work)."""
    ids = [] if work_ids is None else list(dict.fromkeys(work_ids))
    if work_ids is not None and not ids:
        return
    params = {"all": work_ids is None, "ids": ids}
    await db.flush()
    await db.execute(_DELETE, params)
    await db.execute(_INSERT, params)


_INSERT_INFERENCES = text("""
INSERT INTO genre_inferences (work_id, genre_id, source)
SELECT r.work_id, g.id, :source
FROM unnest(CAST(:work_ids AS uuid[]), CAST(:slugs AS text[])) AS r(work_id, slug)
JOIN genres g ON g.slug = r.slug AND g.retired_at IS NULL
ON CONFLICT DO NOTHING
""")


async def set_inferences_bulk(
    db: AsyncSession, slugs_by_work: Mapping[UUID, Iterable[str]], source: str
) -> None:
    """Replace ``source``'s inferences for every work in the mapping, then recompute them."""
    if source not in INFERENCE_SOURCES:
        raise ValueError(f"unknown inference source {source!r}")
    if not slugs_by_work:
        return
    ids = list(slugs_by_work)
    await db.flush()
    await db.execute(delete(GenreInference).where(
        GenreInference.work_id.in_(ids), GenreInference.source == source))
    pairs = [(w, s) for w, slugs in slugs_by_work.items() for s in sorted(set(slugs))]
    if pairs:
        await db.execute(_INSERT_INFERENCES, {
            "source": source, "work_ids": [w for w, _ in pairs], "slugs": [s for _, s in pairs]})
    await recompute(db, ids)


async def set_inferences(db: AsyncSession, work: Work, slugs: Iterable[str], source: str) -> None:
    """Replace ``source``'s inferences for one work, then recompute it."""
    await set_inferences_bulk(db, {work.id: slugs}, source)


async def infer_from_subjects(db: AsyncSession, work: Work, subjects: Sequence[str], source: str) -> None:
    await set_inferences(db, work, infer_genres(subjects, shipped_taxonomy()), source)


async def infer_from_categories(db: AsyncSession, work: Work, categories: Sequence[str]) -> None:
    """Google's categories, only for a work Open Library's subjects said nothing about."""
    has_ol = await db.scalar(select(GenreInference.work_id).where(
        GenreInference.work_id == work.id, GenreInference.source.in_(("open_library", "catalog"))).limit(1))
    if has_ol is not None:
        return
    await set_inferences(db, work, infer_genres(categories, shipped_taxonomy()), "google")
```

In `test_genre_summary.py`, `test_set_inferences_ignores_retired_and_unknown_slugs` expects an empty summary, which the unknown-slug join gives. The view excludes retired genres, and `_INSERT_INFERENCES` never stores them.

- [ ] **Step 5: Run the tests**

Run: `cd backend && pytest tests/test_genre_summary.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/genres.py backend/tests/genre_factories.py backend/tests/test_genre_summary.py
git commit -m "feat(genres): work_genres recompute and per-source inferences"
```

---

### Task 5: Switch ingest, loader and merges to inferences; drop `works.genre_id`

**Files:**
- Modify:
  - `backend/app/services/works.py`, `backend/app/api/works.py`, `backend/app/services/search.py`, `backend/app/services/enrichment.py`
  - `backend/app/services/catalog_loader.py`, `backend/app/services/open_library.py`, `backend/app/services/google_books.py`
  - `backend/app/services/librarian/identity.py`, `backend/app/api/genres.py`
  - `backend/app/models/work.py`, `backend/app/models/genre.py`, `backend/app/schemas/book.py`
  - `backend/scripts/resolve_works.py` (only if it passes `genre_hints`; it does not today)
- Modify: `backend/app/services/genres.py` (add `absorb`)
- Create: `backend/app/services/librarian/genres.py` (`repoint_vetoes` only; Task 10 adds `veto_genre`)
- Create: `backend/scripts/rebuild_work_genres.py`
- Create: `backend/alembic/versions/d8e3f5a7b9c2_retire_work_genre_id.py`
- Test:
  - Create `backend/tests/test_genre_ingest.py`
  - Append to `backend/tests/test_genre_migrations.py`
  - Update `test_works.py`, `test_work_resolution.py`, `test_catalog_loader.py`, `test_genre_works.py`, `test_open_library.py`, `test_google_books.py`

**Interfaces:**
- Consumes: `set_inferences`, `set_inferences_bulk`, `infer_from_subjects`, `infer_from_categories`, `recompute` (Task 4).
- Produces:
  - `async def absorb(db, source: Work, target: Work) -> None` in `services/genres.py`
  - `async def repoint_vetoes(db, source_id: UUID, target_id: UUID) -> None` in `services/librarian/genres.py`
  - `resolve_editions(db, editions)`: the `genre_hints` parameter is **removed**
  - `_upsert_editions(db, results) -> list[Book]`: **no second tuple element**
  - `WorkOut` no longer has `genre_id`

- [ ] **Step 1: Write the failing ingest tests**

`backend/tests/test_genre_ingest.py`:

```python
import uuid

import respx
from httpx import Response
from sqlalchemy import select

from app.models import Book, GenreInference, GenreVote, Work, WorkGenre
from app.services import genres as genres_service
from app.services.catalog_loader import load_release
from app.services.librarian.identity import split
from app.services.works import merge_works, resolve_editions, upsert_work_from_ol
from tests.genre_factories import add_veto, add_vote, effective
from tests.librarian_factories import make_edition, make_user, make_work
from tests.test_work_resolution import ol_work  # the OLWork builder used by the upsert tests


async def sources(db, work):
    rows = (await db.execute(select(GenreInference).where(GenreInference.work_id == work.id))).scalars()
    return {(r.source) for r in rows}


async def test_open_library_ingest_infers_from_subjects(db_session, taxonomy):
    work = await upsert_work_from_ol(db_session, ol_work(subjects=("genre:science fiction", "Space opera")))
    assert set(await effective(db_session, work)) == {"science-fiction"}
    assert await sources(db_session, work) == {"open_library"}


async def test_a_release_work_is_not_reinferred_by_search(db_session, taxonomy):
    from app.models import CatalogRelease

    work = await upsert_work_from_ol(db_session, ol_work(subjects=("Fantasy",)))
    db_session.add(CatalogRelease(version="2026.10.1", manifest={}))
    await db_session.flush()
    work.catalog_release = "2026.10.1"
    await genres_service.set_inferences(db_session, work, {"mystery"}, "catalog")
    await upsert_work_from_ol(db_session, ol_work(subjects=("Horror",)))
    assert "horror" not in await effective(db_session, work)


async def test_google_categories_infer_only_without_an_open_library_inference(db_session, taxonomy):
    bare = await make_work(db_session, "Bare")
    await genres_service.infer_from_categories(db_session, bare, ["Fiction / Fantasy / Epic"])
    assert set(await effective(db_session, bare)) == {"fantasy", "epic-fantasy"}

    known = await make_work(db_session, "Known")
    await genres_service.set_inferences(db_session, known, {"mystery"}, "open_library")
    await genres_service.infer_from_categories(db_session, known, ["Fiction / Fantasy"])
    assert set(await effective(db_session, known)) == {"mystery"}


async def test_refresh_work_infers_from_edition_categories(db_session, taxonomy):
    work = await make_work(db_session, "Heuristic")
    edition = await make_edition(db_session, work)
    edition.categories = ["Fiction / Horror"]
    from app.services.works import _refresh_work
    await _refresh_work(db_session, work)
    assert set(await effective(db_session, work)) == {"horror"}


async def test_merge_combines_votes_carries_inferences_and_vetoes(db_session, taxonomy):
    lib = await make_user(db_session, librarian=True)
    a, b = await make_user(db_session), await make_user(db_session)
    source, target = await make_work(db_session, "Dup A", ol_id="OL1W"), await make_work(db_session, "Dup B", ol_id="OL2W")
    await add_vote(db_session, a, source, taxonomy["grimdark"])
    await add_vote(db_session, a, target, taxonomy["grimdark"])  # same reader, same genre: deduped
    await add_vote(db_session, b, source, taxonomy["epic-fantasy"])
    await genres_service.set_inferences(db_session, source, {"horror"}, "open_library")
    veto = await add_veto(db_session, lib, source, taxonomy["mystery"])
    await genres_service.recompute(db_session, [source.id, target.id])

    await merge_works(db_session, source, target)

    votes = (await db_session.execute(select(GenreVote.user_id, GenreVote.genre_id).where(
        GenreVote.work_id == target.id))).all()
    assert sorted(votes) == sorted([(a.id, taxonomy["grimdark"].id), (b.id, taxonomy["epic-fantasy"].id)])
    assert await sources(db_session, target) == {"open_library"}
    await db_session.refresh(veto)
    assert veto.work_id == target.id and veto.payload["work_id"] == str(target.id)
    assert (await db_session.execute(select(WorkGenre).where(WorkGenre.work_id == source.id))).first() is None
    assert await effective(db_session, target) == {
        "grimdark": (1, "readers"), "epic-fantasy": (1, "readers"), "fantasy": (2, "readers")}


async def test_split_off_book_starts_with_no_votes(db_session, taxonomy):
    lib = await make_user(db_session, librarian=True)
    work = await make_work(db_session, "Omnibus")
    keep, move = await make_edition(db_session, work, title="Omnibus"), await make_edition(db_session, work, title="Sequel")
    move.categories = ["Fiction / Horror"]
    await add_vote(db_session, await make_user(db_session), work, taxonomy["fantasy"])
    await genres_service.recompute(db_session, [work.id])
    c = await split(db_session, lib, work, [move.id], reason="sequel", confirm=True)
    new = await db_session.get(Work, uuid.UUID(c.payload["new_work"]))
    assert (await db_session.execute(select(GenreVote).where(GenreVote.work_id == new.id))).first() is None
    assert set(await effective(db_session, new)) == {"horror"}
    assert "fantasy" in await effective(db_session, work)
```

Before running, check how `make_edition` in `tests/librarian_factories.py` takes a title (its signature is `make_edition(db, work, *, ol_id=None, title=None, language="en")`, as shown above) and how `ol_work(...)` in `tests/test_work_resolution.py` takes subjects. Adjust the keyword if `OLWork.subjects` is named differently.

Append the catalog loader case to `backend/tests/test_catalog_loader.py`, replacing `assert red.genre_id is not None` in `test_loads_every_table_and_stamps_the_release`:

```python
    from app.models import GenreInference
    inferred = (await db_session.execute(select(GenreInference.source).where(GenreInference.work_id == RED))).scalars().all()
    assert inferred == ["catalog"]
```

That test adds `Genre(slug="science-fiction")` and its release subjects carry `genre:science fiction`. If `v1()`'s subjects for `RED` differ, open `v1` in that file and assert against its actual genre subject.

- [ ] **Step 2: Update the tests that asserted `genre_id`**

- `tests/test_works.py::test_search_maps_a_genre_onto_the_work`: replace the last line with
  ```python
      from app.models import GenreInference
      rows = (await db_session.execute(select(GenreInference.source))).scalars().all()
      assert rows == ["open_library"]
  ```
  and add `from sqlalchemy import select` at the top if it is missing.
- `tests/test_work_resolution.py::test_genre_comes_from_the_hint_not_from_the_edition`: delete it. Hints are gone, and Google categories are covered in `test_genre_ingest.py`.
- `tests/test_work_resolution.py::test_upsert_assigns_a_genre_from_the_open_library_subject_tag`: replace `assert work.genre_id == genre.id` with
  ```python
      from app.models import GenreInference
      assert (await db_session.execute(select(GenreInference.genre_id).where(GenreInference.work_id == work.id))).scalars().all() == [genre.id]
  ```
- `tests/test_genre_works.py::seed_work`: drop the `genre_id=genre.id` kwarg. After the flush, call `await genres_service.set_inferences(db_session, work, {genre.slug}, "open_library")`, with `from app.services import genres as genres_service`.
- `tests/test_pagination.py` (the genre-works seeder, around line 46): drop `genre_id=genre.id` from the `Work(...)`. After the flush, add `await genres_service.set_inferences_bulk(db_session, {w.id: {genre.slug} for w in works}, "open_library")`, with `from app.services import genres as genres_service`.
- `tests/test_open_library.py`: delete the three `genre_slug` tests.
- `tests/test_google_books.py`: delete the two `m["genre_slug"]` assertions (lines 48 and 59).

- [ ] **Step 3: Run to verify the new tests fail**

Run: `cd backend && pytest tests/test_genre_ingest.py -v`
Expected: FAIL, because nothing infers yet and `merge_works` doesn't absorb.

- [ ] **Step 4: Add `absorb` and `repoint_vetoes`**

`backend/app/services/librarian/genres.py`:

```python
"""Librarian genre fixes (spec 2026-09-29 §7.2). The corrections log's only writer
stays this package, so the merge path's veto re-pointing lives here too."""

from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def repoint_vetoes(db: AsyncSession, source_id: UUID, target_id: UUID) -> None:
    """A merged book's live vetoes keep holding on the survivor."""
    await db.execute(text("""
        UPDATE catalog_corrections
        SET work_id = :dst, payload = jsonb_set(payload, '{work_id}', to_jsonb(CAST(:dst AS text)))
        WHERE op = 'veto_genre' AND reverted_at IS NULL AND work_id = :src"""),
        {"src": source_id, "dst": target_id})
```

Append to `services/genres.py`:

```python
async def absorb(db: AsyncSession, source: Work, target: Work) -> None:
    """``merge_works``' genre half: votes (deduped per reader and genre),
    inferences (union) and vetoes follow the book; the tombstone keeps no summary."""
    # Imported here: the librarian package imports works.py, which imports this module.
    from app.services.librarian.genres import repoint_vetoes

    params = {"src": source.id, "dst": target.id}
    await db.flush()
    await db.execute(text("""
        DELETE FROM genre_votes s USING genre_votes t
        WHERE s.work_id = :src AND t.work_id = :dst AND t.user_id = s.user_id AND t.genre_id = s.genre_id"""), params)
    await db.execute(text("UPDATE genre_votes SET work_id = :dst WHERE work_id = :src"), params)
    await db.execute(text("""
        INSERT INTO genre_inferences (work_id, genre_id, source)
        SELECT :dst, genre_id, source FROM genre_inferences WHERE work_id = :src
        ON CONFLICT DO NOTHING"""), params)
    await db.execute(text("DELETE FROM genre_inferences WHERE work_id = :src"), params)
    await repoint_vetoes(db, source.id, target.id)
    await db.execute(text("DELETE FROM work_genres WHERE work_id = :src"), params)
    await recompute(db, [target.id])
```

- [ ] **Step 5: Switch `works.py`**

- Remove `from app.models.genre import Genre` and the `genre_slug as ol_genre_slug` import.
- Add `from app.services import genres as genres_service`.
- `resolve_editions(db, editions)`: delete the `genre_hints` parameter and its docstring paragraph, and call `await _refresh_work(db, work)`.
- `upsert_work_from_ol`: replace the whole `if work.genre_id is None and ol.subjects:` block with

  ```python
      # A release work's genres are the catalog's, as its subjects are.
      if work.catalog_release is None:
          await genres_service.infer_from_subjects(db, work, ol.subjects or (), "open_library")
  ```

- `_refresh_work(db, work)`: drop the `genre_hints` parameter and its block. After `work.representative_book_id = best.id`, add

  ```python
      categories = [c for e in editions for c in (e.categories or [])]
      if categories:
          await genres_service.infer_from_categories(db, work, categories)
  ```

- `merge_works`: after `await series_service.absorb_series(db, source, target)`, add `await genres_service.absorb(db, source, target)`. Delete `source.genre_id = None`.

- [ ] **Step 6: Switch the edition upsert, search fallback and enrichment**

`api/works.py::_upsert_editions`:
- Return `list[Book]`.
- Delete the `slugs`/`genre_ids`/`hints` code and the `Genre` import.
- Update the docstring: "Upsert every volume as an edition; return them in relevance order."

`services/search.py::_ingest_from_google`:

```python
    editions = await _upsert_editions(db, results)
    await resolve_editions(db, editions)
```

`services/enrichment.py`: change `editions, _ = await _upsert_editions(db, results)` to `editions = await _upsert_editions(db, results)`.

`services/google_books.py`:
- Delete `_CATEGORY_SLUGS`, `_category_to_slug`, and the `"genre_slug": …` key in the normalized dict.
- Keep `"categories"`.

`services/open_library.py`: delete `genre_slug`.

`services/librarian/identity.py::split`: delete `genre_id=work.genre_id,` from the `Work(...)` constructor. `_refresh_work(db, new)` then infers from the new book's own editions.

- [ ] **Step 7: Switch the catalog loader**

In `services/catalog_loader.py`:
- Replace `from app.services.open_library import genre_slug` with `from app.services.genre_inference import infer_genres, shipped_taxonomy` and `from app.services import genres as genres_service`.
- In `_stage`, change the works extra column to `extra = [("genre_slugs", "text[]")] if name == "works" else []`. Change the append to
  ```python
                      record.append(sorted(infer_genres([s for s in subjects if s], shipped_taxonomy())))
  ```
  and load the taxonomy once per call (`taxonomy = shipped_taxonomy()` at the top of `_stage`).
- In the works `INSERT ... SELECT` in `_UPSERTS`:
  - drop `genre_id` from the column list
  - drop `g.id` from the select list
  - drop `LEFT JOIN genres g ON g.slug = t.genre_slug`
  - drop `genre_id = coalesce(works.genre_id, EXCLUDED.genre_id),` from the `DO UPDATE`
- In `load_release`, after `await _settle_absent(...)` and before the final `db.flush()`, add

  ```python
      # Genres last: adoption merges have already carried runtime votes onto release works.
      rows = (await db.execute(text("SELECT id, genre_slugs FROM stage_works"))).all()
      await genres_service.set_inferences_bulk(db, {wid: slugs or [] for wid, slugs in rows}, "catalog")
  ```

- [ ] **Step 8: Migration `d8e3f5a7b9c2` — copy then drop `works.genre_id`**

```python
"""retire works.genre_id: its values become open_library inferences

Revision ID: d8e3f5a7b9c2
Revises: c7d2e4f6a8b1
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "d8e3f5a7b9c2"
down_revision: Union[str, None] = "c7d2e4f6a8b1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        INSERT INTO genre_inferences (work_id, genre_id, source)
        SELECT id, genre_id, 'open_library' FROM works WHERE genre_id IS NOT NULL
        ON CONFLICT DO NOTHING""")
    # The eight seeded genres are parents, so there is nothing to roll up, and
    # no votes or vetoes exist yet: an inferred row per copied value is the summary.
    op.execute("""
        INSERT INTO work_genres (work_id, genre_id, direct_votes, score, inferred, vetoed)
        SELECT id, genre_id, 0, 0, true, false FROM works
        WHERE genre_id IS NOT NULL AND merged_into_id IS NULL
        ON CONFLICT (work_id, genre_id) DO UPDATE SET inferred = true""")
    op.drop_column("works", "genre_id")  # drops its index and FK with it


def downgrade() -> None:
    op.add_column("works", sa.Column("genre_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key("works_genre_id_fkey", "works", "genres", ["genre_id"], ["id"], ondelete="SET NULL")
    op.create_index("ix_works_genre_id", "works", ["genre_id"])
    op.execute("""
        UPDATE works w SET genre_id = sub.genre_id FROM (
            SELECT DISTINCT ON (i.work_id) i.work_id, i.genre_id
            FROM genre_inferences i JOIN genres g ON g.id = i.genre_id
            WHERE i.source = 'open_library' AND g.parent_id IS NULL
            ORDER BY i.work_id, g.position) sub
        WHERE w.id = sub.work_id""")
```

Remove `genre_id` and the `genre` relationship from `models/work.py`, and `works` from `Genre` in `models/genre.py`. Remove `genre_id` from `WorkOut` and `work_out` in `schemas/book.py`. `BookOut.genre_id` stays: `books.genre_id` was dropped long ago, so check `grep -rn "BookOut" backend/app`. If `BookOut` has no users, delete its `genre_id` field; otherwise leave it.

Append to `tests/test_genre_migrations.py`:

```python
async def test_work_genre_ids_become_open_library_inferences(scratch_db):
    alembic(scratch_db, "upgrade", "c7d2e4f6a8b1")
    conn = await asyncpg.connect(_plain(scratch_db))
    try:
        series = await conn.fetchval("""
            INSERT INTO series (source, external_id, name, slug, canonical_key, kind, provenance)
            VALUES ('heuristic', 'x', 'Dune', 'dune', 'dune', 'singleton', 'heuristic') RETURNING id""")
        genre = await conn.fetchval("SELECT id FROM genres WHERE slug = 'science-fiction'")
        work = await conn.fetchval("""
            INSERT INTO works (source, external_id, canonical_key, title, author, kind, identity_provenance,
                               series_id, genre_id)
            VALUES ('openlibrary', 'OL1W', 'dune', 'Dune', 'Frank Herbert', 'single', 'isbn', $1, $2)
            RETURNING id""", series, genre)
    finally:
        await conn.close()
    alembic(scratch_db, "upgrade", "d8e3f5a7b9c2")
    conn = await asyncpg.connect(_plain(scratch_db))
    try:
        assert await conn.fetch("SELECT genre_id, source FROM genre_inferences WHERE work_id = $1", work) == [
            (genre, "open_library")]
        assert await conn.fetchval(
            "SELECT source FROM effective_work_genres WHERE work_id = $1", work) == "inferred"
        assert await conn.fetchval(
            "SELECT count(*) FROM information_schema.columns WHERE table_name='works' AND column_name='genre_id'") == 0
    finally:
        await conn.close()
    alembic(scratch_db, "downgrade", "c7d2e4f6a8b1")
```

The series and works enum literals (`'heuristic'`, `'singleton'`, `'heuristic'` provenance) must be valid enum values. Check `SeriesSource`, `SeriesKind` and `SeriesProvenance` in `models/series.py` and correct them if they differ.

- [ ] **Step 9: Switch the genre page reader**

`api/genres.py::get_genre_works` now reads the view. Task 8 adds sorting and the tree; this step keeps the current shape.

```python
    stmt = (
        select(Work)
        .join(effective_work_genres, effective_work_genres.c.work_id == Work.id)
        .where(
            effective_work_genres.c.genre_id == genre.id,
            Work.kind == WorkKind.single,
            Work.merged_into_id.is_(None),  # tombstones are reachable, not listed
        )
        .order_by(Work.title)
        .limit(limit)
        .offset(offset)
    )
```

Import `effective_work_genres` from `app.models`.

- [ ] **Step 10: Write `backend/scripts/rebuild_work_genres.py`**

```python
"""Rebuild work_genres from its sources. Idempotent; batched.

    python -m scripts.rebuild_work_genres            # recompute every summary row
    python -m scripts.rebuild_work_genres --reinfer  # first redo open_library/catalog
                                                     # inferences from works.subjects

Run --reinfer after changing a `match`/`exclude` list in app/data/genres.yaml.
"""

import argparse
import asyncio

from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.models import Work
from app.services import genres as genres_service
from app.services.genre_inference import infer_genres, shipped_taxonomy
from app.services.series_identity import SUBJECT_SEPARATOR

_BATCH = 2000


async def main(reinfer: bool) -> None:
    async with AsyncSessionLocal() as session:
        ids = (await session.execute(select(Work.id).where(Work.merged_into_id.is_(None))
                                     .order_by(Work.id))).scalars().all()
    taxonomy = shipped_taxonomy()
    for start in range(0, len(ids), _BATCH):
        chunk = ids[start:start + _BATCH]
        async with AsyncSessionLocal() as session:
            if reinfer:
                rows = (await session.execute(select(Work.id, Work.subjects, Work.catalog_release)
                                              .where(Work.id.in_(chunk)))).all()
                for source in ("open_library", "catalog"):
                    await genres_service.set_inferences_bulk(session, {
                        wid: infer_genres([s for s in (subjects or "").split(SUBJECT_SEPARATOR) if s], taxonomy)
                        for wid, subjects, release in rows
                        if (release is not None) == (source == "catalog")}, source)
            await genres_service.recompute(session, chunk)
            await session.commit()
        print(f"{min(start + _BATCH, len(ids))}/{len(ids)} works")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--reinfer", action="store_true")
    asyncio.run(main(parser.parse_args().reinfer))
```

- [ ] **Step 11: Run the full backend suite**

Run: `cd backend && pytest -q`
Expected: all PASS. Fix any remaining `genre_id` or `genre_hints` references that `grep -rn "genre_id\|genre_hints\|genre_slug\|_CATEGORY_SLUGS" backend/app backend/scripts backend/tests` finds. Leave the thread-level `genre_id` and `genre_slug` usages alone: `Thread.genre_id`, `ThreadCreate.genre_slug` and `thread_summaries`' `genre_slug` are rooms, not book genres.

- [ ] **Step 12: Upgrade the dev database**

Run:
```bash
docker compose exec backend alembic upgrade head
docker compose exec backend python -m scripts.sync_genres
docker compose exec backend python -m scripts.rebuild_work_genres --reinfer
```
Expected: the progress lines end in `N/N works`. The `effective_work_genres` count is non-zero:
```bash
docker compose exec db psql -U margin -c "select count(*) from effective_work_genres"
```

- [ ] **Step 13: Commit**

```bash
git add -A backend
git commit -m "feat(genres): ingest, loader and merges write inferences; retire works.genre_id"
```

---

### Task 6: Voting service, the book-genres API and `top_genres`

**Files:**
- Modify: `backend/app/services/genres.py`
- Create: `backend/app/schemas/genre.py`
- Modify: `backend/app/api/works.py`, `backend/app/schemas/book.py`, `backend/app/services/works.py` (`WorkPresentation`, `load_work_presentation`)
- Test: `backend/tests/test_genre_votes.py`, `backend/tests/test_genre_api.py`

**Interfaces:**
- Consumes: `recompute` (Task 4), `effective_work_genres`.
- Produces:
  - `MAX_GENRES_PER_READER = 5`
  - `class GenreRefused(Exception)` with `.message`
  - `async def vote(db, user, work, genre) -> Work`. Returns the live work.
  - `async def unvote(db, user, work, genre) -> Work`
  - `async def work_genres_payload(db, work, user) -> WorkGenresOut`
  - `async def top_genres(db, work_ids) -> dict[UUID, list[GenreRef]]`
  - Schemas: `GenreRef(slug, name)`, `WorkGenreOut`, `WorkGenresOut`
  - `WorkOut.top_genres: list[GenreRef]`
  - `WorkPresentation.top_genres: tuple[GenreRef, ...] = ()`
  - Routes:
    - `GET /api/works/{id}/genres`
    - `PUT /api/works/{id}/genres/{slug}`
    - `DELETE /api/works/{id}/genres/{slug}`

- [ ] **Step 1: Write the failing service tests**

`backend/tests/test_genre_votes.py`:

```python
import asyncio
import random

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.models import Genre, User, Work, WorkKind
from app.services import genres as genres_service
from app.services.genres import GenreRefused, MAX_GENRES_PER_READER, unvote, vote
from tests.conftest import TEST_DB_URL
from tests.genre_factories import add_veto, effective, make_genre, summary
from tests.librarian_factories import make_user, make_work


async def test_vote_and_unvote(db_session, taxonomy):
    reader, w = await make_user(db_session), await make_work(db_session, "Dune")
    await vote(db_session, reader, w, taxonomy["space-opera"])
    assert await effective(db_session, w) == {"space-opera": (1, "readers"), "science-fiction": (1, "readers")}
    await vote(db_session, reader, w, taxonomy["space-opera"])  # no-op
    assert (await effective(db_session, w))["space-opera"] == (1, "readers")
    await unvote(db_session, reader, w, taxonomy["space-opera"])
    assert await effective(db_session, w) == {}


async def test_the_sixth_genre_is_refused(db_session, taxonomy):
    reader, w = await make_user(db_session), await make_work(db_session, "Dune")
    slugs = ["space-opera", "hard-sf", "cyberpunk", "dystopian", "science-fiction", "fantasy"]
    for slug in slugs[:MAX_GENRES_PER_READER]:
        await vote(db_session, reader, w, taxonomy[slug])
    with pytest.raises(GenreRefused, match="You've tagged this book with 5 genres"):
        await vote(db_session, reader, w, taxonomy["fantasy"])


async def test_votes_on_vetoed_or_retired_genres_do_not_use_cap_slots(db_session, taxonomy):
    # Review Focus 4.
    lib, reader, w = await make_user(db_session, librarian=True), await make_user(db_session), await make_work(db_session, "Dune")
    for slug in ["space-opera", "hard-sf", "cyberpunk", "dystopian", "time-travel"]:
        await vote(db_session, reader, w, taxonomy[slug])
    await add_veto(db_session, lib, w, taxonomy["time-travel"])
    await genres_service.recompute(db_session, [w.id])
    await vote(db_session, reader, w, taxonomy["science-fiction"])  # a slot freed by the veto


async def test_refusals(db_session, taxonomy):
    lib, reader = await make_user(db_session, librarian=True), await make_user(db_session)
    w = await make_work(db_session, "Dune")
    await add_veto(db_session, lib, w, taxonomy["horror"])
    await genres_service.recompute(db_session, [w.id])
    with pytest.raises(GenreRefused, match="A librarian removed this genre from this book."):
        await vote(db_session, reader, w, taxonomy["horror"])
    old = await make_genre(db_session, "weird-west", retired=True)
    with pytest.raises(GenreRefused, match="no longer in the genre list"):
        await vote(db_session, reader, w, old)
    box = await make_work(db_session, "Dune Box Set")
    box.kind = WorkKind.collection
    with pytest.raises(GenreRefused, match="Box sets and omnibuses"):
        await vote(db_session, reader, box, taxonomy["fantasy"])


async def test_a_tombstone_resolves_to_its_survivor(db_session, taxonomy):
    reader = await make_user(db_session)
    keeper, gone = await make_work(db_session, "Dune"), await make_work(db_session, "Dune (1965)")
    gone.merged_into_id = keeper.id
    await db_session.flush()
    live = await vote(db_session, reader, gone, taxonomy["space-opera"])
    assert live.id == keeper.id and "space-opera" in await effective(db_session, keeper)


async def test_two_concurrent_sixth_votes_cannot_both_land(db_session, taxonomy):
    reader, w = await make_user(db_session), await make_work(db_session, "Dune")
    for slug in ["space-opera", "hard-sf", "cyberpunk", "dystopian"]:
        await vote(db_session, reader, w, taxonomy[slug])
    await db_session.commit()

    engine = create_async_engine(TEST_DB_URL, poolclass=NullPool)
    make = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with make() as a, make() as b:
            ua, wa = await a.get(User, reader.id), await a.get(Work, w.id)
            ub, wb = await b.get(User, reader.id), await b.get(Work, w.id)
            await vote(a, ua, wa, await a.get(Genre, taxonomy["time-travel"].id))  # 5th, holds the row lock
            second = asyncio.create_task(vote(b, ub, wb, await b.get(Genre, taxonomy["first-contact"].id)))
            await asyncio.sleep(0.3)
            assert not second.done()  # blocked on FOR UPDATE
            await a.commit()
            with pytest.raises(GenreRefused):
                await second
            await b.rollback()
    finally:
        await engine.dispose()


async def test_drift_guard_incremental_equals_rebuild(db_session, taxonomy):
    rng = random.Random(20260929)
    readers = [await make_user(db_session) for _ in range(3)]
    works = [await make_work(db_session, f"Book {i}") for i in range(3)]
    pool = [taxonomy[s] for s in ("fantasy", "epic-fantasy", "grimdark", "mystery", "noir", "horror")]
    for _ in range(60):
        r, w, g = rng.choice(readers), rng.choice(works), rng.choice(pool)
        roll = rng.random()
        if roll < 0.5:
            try:
                await vote(db_session, r, w, g)
            except GenreRefused:
                pass
        elif roll < 0.8:
            await unvote(db_session, r, w, g)
        else:
            await genres_service.set_inferences(
                db_session, w, {x.slug for x in rng.sample(pool, 2)}, rng.choice(["open_library", "google"]))
    incremental = await summary(db_session)
    await genres_service.recompute(db_session, None)
    assert await summary(db_session) == incremental
```

In `test_two_concurrent_sixth_votes_cannot_both_land`, the reader already holds 4 votes and both sessions try to add one more. Session A's `time-travel` takes the reader to 5, which makes session B's `first-contact` the sixth, so B must be refused.

- [ ] **Step 2: Write the failing API tests**

`backend/tests/test_genre_api.py`:

```python
from tests.genre_factories import add_veto
from tests.librarian_factories import headers_for, make_user, make_work
from app.services import genres as genres_service


async def test_get_is_public_and_reports_inferred(client, db_session, taxonomy):
    w = await make_work(db_session, "Dune")
    await genres_service.set_inferences(db_session, w, {"space-opera"}, "open_library")
    await db_session.commit()
    body = (await client.get(f"/api/works/{w.id}/genres")).json()
    assert body["source"] == "inferred"
    assert {g["slug"] for g in body["genres"]} == {"science-fiction", "space-opera"}
    assert body["my_vote_count"] is None and body["genres"][0]["my_vote"] is None


async def test_none_when_nothing_is_known(client, db_session, taxonomy):
    w = await make_work(db_session, "Mystery Box")
    await db_session.commit()
    assert (await client.get(f"/api/works/{w.id}/genres")).json() == {
        "source": "none", "genres": [], "my_vote_count": None}


async def test_put_and_delete_return_the_payload(client, db_session, taxonomy):
    reader, w = await make_user(db_session), await make_work(db_session, "Dune")
    await db_session.commit()
    h = headers_for(reader)
    body = (await client.put(f"/api/works/{w.id}/genres/space-opera", headers=h)).json()
    assert body["source"] == "readers" and body["my_vote_count"] == 1
    opera = next(g for g in body["genres"] if g["slug"] == "space-opera")
    assert (opera["score"], opera["direct_votes"], opera["my_vote"], opera["parent_slug"]) == (1, 1, True, "science-fiction")
    parent = next(g for g in body["genres"] if g["slug"] == "science-fiction")
    assert (parent["score"], parent["direct_votes"], parent["my_vote"]) == (1, 0, False)
    body = (await client.delete(f"/api/works/{w.id}/genres/space-opera", headers=h)).json()
    assert body["source"] == "none" and body["my_vote_count"] == 0


async def test_status_codes(client, db_session, taxonomy):
    lib, reader, w = await make_user(db_session, librarian=True), await make_user(db_session), await make_work(db_session, "Dune")
    await add_veto(db_session, lib, w, taxonomy["horror"])
    await genres_service.recompute(db_session, [w.id])
    await db_session.commit()
    h = headers_for(reader)
    assert (await client.put(f"/api/works/{w.id}/genres/space-opera")).status_code == 401
    assert (await client.put(f"/api/works/{w.id}/genres/no-such", headers=h)).status_code == 404
    assert (await client.put("/api/works/00000000-0000-0000-0000-000000000000/genres/fantasy",
                             headers=h)).status_code == 404
    refused = await client.put(f"/api/works/{w.id}/genres/horror", headers=h)
    assert refused.status_code == 422
    assert refused.json()["detail"] == "A librarian removed this genre from this book."


async def test_search_results_carry_top_genres(client, db_session, taxonomy):
    reader, w = await make_user(db_session), await make_work(db_session, "Dune")
    await db_session.commit()
    await client.put(f"/api/works/{w.id}/genres/space-opera", headers=headers_for(reader))
    body = (await client.get(f"/api/works/{w.id}")).json()
    assert {g["slug"] for g in body["top_genres"]} == {"space-opera", "science-fiction"}
    assert set(body["top_genres"][0]) == {"slug", "name"}
```

- [ ] **Step 3: Run to verify they fail**

Run: `cd backend && pytest tests/test_genre_votes.py tests/test_genre_api.py -v`
Expected: ImportError on `GenreRefused`, then 404/405 on the routes.

- [ ] **Step 4: Schemas**

`backend/app/schemas/genre.py`:

```python
from typing import Literal
from uuid import UUID

from pydantic import BaseModel


class GenreRef(BaseModel):
    slug: str
    name: str


class WorkGenreOut(BaseModel):
    slug: str
    name: str
    parent_slug: str | None = None
    score: int  # distinct readers, subgenres rolled up; 0 for an inferred genre
    direct_votes: int
    my_vote: bool | None = None  # null for anonymous callers
    vetoed: bool = False  # librarians only
    veto_id: UUID | None = None  # the correction to undo; librarians only


class WorkGenresOut(BaseModel):
    source: Literal["readers", "inferred", "none"]
    genres: list[WorkGenreOut]
    my_vote_count: int | None = None
```

In `schemas/book.py`:
- `from app.schemas.genre import GenreRef`
- add `top_genres: list[GenreRef] = []` to `WorkOut`
- in `work_out`: `top_genres=list(presentation.top_genres) if presentation else [],`

- [ ] **Step 5: Implement voting and the payload in `services/genres.py`**

Add these imports:

```python
from sqlalchemy import and_, cast, func
from sqlalchemy.orm import aliased

from app.models import CatalogCorrection, CorrectionOp, Genre, GenreVote, User, WorkGenre, WorkKind, effective_work_genres as ewg
from app.schemas.genre import GenreRef, WorkGenreOut, WorkGenresOut
```

Then append:

```python
MAX_GENRES_PER_READER = 5


class GenreRefused(Exception):
    """A vote the rules refuse. ``message`` is shown to the reader verbatim (422)."""

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


async def _live(db: AsyncSession, work: Work) -> Work:
    # One hop, like canonical_work (tombstone chains are flattened on merge).
    # Not imported from works.py: that module imports this one.
    if work.merged_into_id is None:
        return work
    return await db.get(Work, work.merged_into_id) or work


async def _vetoed(db: AsyncSession, work_id: UUID, genre_id: UUID) -> bool:
    return bool(await db.scalar(select(WorkGenre.vetoed).where(
        WorkGenre.work_id == work_id, WorkGenre.genre_id == genre_id)))


async def _my_live_votes(db: AsyncSession, user_id: UUID, work_id: UUID) -> set[UUID]:
    """The reader's votes that count: on live genres a librarian hasn't vetoed."""
    rows = await db.execute(
        select(GenreVote.genre_id)
        .join(Genre, Genre.id == GenreVote.genre_id)
        .join(WorkGenre, and_(WorkGenre.work_id == GenreVote.work_id, WorkGenre.genre_id == GenreVote.genre_id))
        .where(GenreVote.user_id == user_id, GenreVote.work_id == work_id,
               Genre.retired_at.is_(None), WorkGenre.vetoed.is_(False)))
    return set(rows.scalars())


async def vote(db: AsyncSession, user: User, work: Work, genre: Genre) -> Work:
    work = await _live(db, work)
    if work.kind is WorkKind.collection:
        raise GenreRefused("Box sets and omnibuses take their books' genres, not their own.")
    if genre.retired_at is not None:
        raise GenreRefused(f"{genre.name} is no longer in the genre list.")
    if await _vetoed(db, work.id, genre.id):
        raise GenreRefused("A librarian removed this genre from this book.")
    # Serialises one reader's concurrent votes on a book, so the cap holds.
    await db.execute(select(Work.id).where(Work.id == work.id).with_for_update())
    existing = await db.scalar(select(GenreVote.id).where(
        GenreVote.user_id == user.id, GenreVote.work_id == work.id, GenreVote.genre_id == genre.id))
    if existing is not None:
        return work
    if len(await _my_live_votes(db, user.id, work.id)) >= MAX_GENRES_PER_READER:
        raise GenreRefused(f"You've tagged this book with {MAX_GENRES_PER_READER} genres; remove one first.")
    db.add(GenreVote(user_id=user.id, work_id=work.id, genre_id=genre.id))
    await recompute(db, [work.id])
    return work


async def unvote(db: AsyncSession, user: User, work: Work, genre: Genre) -> Work:
    work = await _live(db, work)
    await db.execute(delete(GenreVote).where(
        GenreVote.user_id == user.id, GenreVote.work_id == work.id, GenreVote.genre_id == genre.id))
    await recompute(db, [work.id])
    return work


async def work_genres_payload(db: AsyncSession, work: Work, user: User | None) -> WorkGenresOut:
    parent = aliased(Genre)
    rows = (await db.execute(
        select(Genre.id, Genre.slug, Genre.name, parent.slug, ewg.c.score, WorkGenre.direct_votes, ewg.c.source)
        .select_from(ewg)
        .join(Genre, Genre.id == ewg.c.genre_id)
        .outerjoin(parent, parent.id == Genre.parent_id)
        .join(WorkGenre, and_(WorkGenre.work_id == ewg.c.work_id, WorkGenre.genre_id == ewg.c.genre_id))
        .where(ewg.c.work_id == work.id)
        .order_by(ewg.c.score.desc(), Genre.position, Genre.slug))).all()
    mine = await _my_live_votes(db, user.id, work.id) if user is not None else None
    genres = [
        WorkGenreOut(slug=slug, name=name, parent_slug=parent_slug, score=score, direct_votes=direct,
                     my_vote=None if mine is None else gid in mine)
        for gid, slug, name, parent_slug, score, direct, _ in rows
    ]
    if user is not None and user.is_librarian:
        genres += await _vetoed_rows(db, work.id)
    return WorkGenresOut(source=rows[0][6] if rows else "none", genres=genres,
                         my_vote_count=None if mine is None else len(mine))


async def _vetoed_rows(db: AsyncSession, work_id: UUID) -> list[WorkGenreOut]:
    parent = aliased(Genre)
    rows = (await db.execute(
        select(Genre.slug, Genre.name, parent.slug, WorkGenre.score, WorkGenre.direct_votes, CatalogCorrection.id)
        .select_from(WorkGenre)
        .join(Genre, Genre.id == WorkGenre.genre_id)
        .outerjoin(parent, parent.id == Genre.parent_id)
        .join(CatalogCorrection, and_(
            CatalogCorrection.work_id == WorkGenre.work_id,
            CatalogCorrection.op == CorrectionOp.veto_genre,
            CatalogCorrection.reverted_at.is_(None),
            CatalogCorrection.payload["genre_id"].astext == cast(WorkGenre.genre_id, Text)))
        .where(WorkGenre.work_id == work_id, WorkGenre.vetoed.is_(True))
        .order_by(Genre.position, Genre.slug))).all()
    return [WorkGenreOut(slug=s, name=n, parent_slug=p, score=sc, direct_votes=d, vetoed=True, veto_id=cid)
            for s, n, p, sc, d, cid in rows]


async def top_genres(db: AsyncSession, work_ids: Sequence[UUID], limit: int = 3) -> dict[UUID, list[GenreRef]]:
    """The top ``limit`` effective genres per work, in one query."""
    if not work_ids:
        return {}
    rank = func.row_number().over(
        partition_by=ewg.c.work_id, order_by=(ewg.c.score.desc(), Genre.position, Genre.slug)).label("rn")
    ranked = (select(ewg.c.work_id, Genre.slug, Genre.name, rank)
              .join(Genre, Genre.id == ewg.c.genre_id)
              .where(ewg.c.work_id.in_(list(work_ids))).subquery())
    rows = (await db.execute(select(ranked.c.work_id, ranked.c.slug, ranked.c.name)
                             .where(ranked.c.rn <= limit).order_by(ranked.c.work_id, ranked.c.rn))).all()
    out: dict[UUID, list[GenreRef]] = {}
    for work_id, slug, name in rows:
        out.setdefault(work_id, []).append(GenreRef(slug=slug, name=name))
    return out
```

Add `Text` to the `sqlalchemy` import.

- [ ] **Step 6: `top_genres` in `load_work_presentation`**

In `services/works.py`:
- Add the field `top_genres: tuple[GenreRef, ...] = ()` as the **last** field of `WorkPresentation`, with `from app.schemas.genre import GenreRef`.
- At the end of `load_work_presentation`, before building the dict, add `tops = await genres_service.top_genres(db, work_ids)`.
- Pass `top_genres=tuple(tops.get(row[0], ()))` to each `WorkPresentation(...)`.
- Add a line to its docstring: "* top genres — up to three effective genres, the badges a result row shows."

- [ ] **Step 7: Routes in `api/works.py`**

Add these imports:

```python
from app.models import Genre
from app.schemas.genre import WorkGenresOut
from app.services import genres as genres_service
```

Then add the routes:

```python
async def _genre_or_404(slug: str, db: AsyncSession) -> Genre:
    genre = (await db.execute(select(Genre).where(Genre.slug == slug))).scalar_one_or_none()
    if genre is None:
        raise HTTPException(status_code=404, detail="Genre not found")
    return genre


@router.get("/{work_id}/genres", response_model=WorkGenresOut)
async def get_work_genres(work_id: UUID, db: AsyncSession = Depends(get_db),
                          current_user=Depends(get_current_user_optional)):
    """The book's effective genres; for a librarian, also the vetoed ones."""
    work = await _get_work_or_404(work_id, db)
    return await genres_service.work_genres_payload(db, work, current_user)


@router.put("/{work_id}/genres/{slug}", response_model=WorkGenresOut)
async def vote_genre(work_id: UUID, slug: str, db: AsyncSession = Depends(get_db),
                     current_user=Depends(get_current_user)):
    """Tag the book with a genre from the taxonomy. Idempotent; at most 5 per reader per book."""
    work, genre = await _get_work_or_404(work_id, db), await _genre_or_404(slug, db)
    try:
        work = await genres_service.vote(db, current_user, work, genre)
    except genres_service.GenreRefused as exc:
        raise HTTPException(status_code=422, detail=exc.message) from None
    return await genres_service.work_genres_payload(db, work, current_user)


@router.delete("/{work_id}/genres/{slug}", response_model=WorkGenresOut)
async def unvote_genre(work_id: UUID, slug: str, db: AsyncSession = Depends(get_db),
                       current_user=Depends(get_current_user)):
    work, genre = await _get_work_or_404(work_id, db), await _genre_or_404(slug, db)
    work = await genres_service.unvote(db, current_user, work, genre)
    return await genres_service.work_genres_payload(db, work, current_user)
```

Check whether `tests/test_openapi.py` requires request-body examples. These routes have no body, so nothing is needed.

- [ ] **Step 8: Run the tests**

Run: `cd backend && pytest tests/test_genre_votes.py tests/test_genre_api.py tests/test_openapi.py -v && pytest -q`
Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add -A backend
git commit -m "feat(genres): readers tag books with genres; top_genres on every work"
```

---

### Task 7: `GenreLine` and `GenrePicker` on series pages

**Files:**
- Create: `frontend/src/api/genres.js`, `frontend/src/components/GenrePicker.jsx`, `frontend/src/components/GenreLine.jsx`
- Test: `frontend/src/components/GenrePicker.test.jsx`, `frontend/src/components/GenreLine.test.jsx`
- Modify: `frontend/src/pages/Series.jsx` (`BookRow`), `frontend/src/pages/Series.test.jsx` (mock the new GET)

**Interfaces:**
- Consumes:
  - `GET /api/genres/`. **Until Task 8 it returns a flat list.** `useGenreTree` must accept both shapes: an item without `children` is treated as a parent with `children: []`.
  - `GET/PUT/DELETE /api/works/{id}/genres[/{slug}]` (Task 6)
- Produces:
  - `useGenreTree()`, `useWorkGenres(workId)`, `useVoteGenre(workId)`, `useUnvoteGenre(workId)` from `api/genres.js`. Task 8 adds `useGenre`, `useGenreWorks` and `useGenreThreads`; Task 10 adds `useVetoGenre`.
  - `<GenrePicker tree selected onToggle onClose max? label />`
  - `<GenreLine workId title editing? />`

- [ ] **Step 1: Write the failing picker tests**

`frontend/src/components/GenrePicker.test.jsx`:

```jsx
import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import GenrePicker from './GenrePicker'

const TREE = [
  { slug: 'fantasy', name: 'Fantasy', children: [
    { slug: 'epic-fantasy', name: 'Epic Fantasy' }, { slug: 'grimdark', name: 'Grimdark' }] },
  { slug: 'mystery', name: 'Mystery', children: [{ slug: 'noir', name: 'Noir' }] },
]

function setup(props = {}) {
  const onToggle = vi.fn()
  render(<GenrePicker tree={TREE} selected={new Set()} onToggle={onToggle} onClose={() => {}}
                      label="tag Dune" {...props} />)
  return { onToggle, input: screen.getByRole('combobox', { name: 'filter genres' }) }
}

describe('GenrePicker', () => {
  it('filters the tree and keeps a matching subgenre’s parent as context', async () => {
    const { input } = setup()
    await userEvent.type(input, 'grim')
    const names = screen.getAllByRole('option').map((o) => o.textContent)
    expect(names.join('|')).toMatch(/fantasy/)
    expect(names.join('|')).toMatch(/grimdark/)
    expect(names.join('|')).not.toMatch(/mystery/)
  })

  it('says the list is curated when nothing matches, and Enter submits nothing', async () => {
    const { input, onToggle } = setup()
    await userEvent.type(input, 'space western{Enter}')
    expect(screen.getByText('no such genre — the list is curated')).toBeInTheDocument()
    expect(onToggle).not.toHaveBeenCalled()
  })

  it('puts Enter on the first real match, not its context parent', async () => {
    const { input, onToggle } = setup()
    await userEvent.type(input, 'grim{Enter}')
    expect(onToggle).toHaveBeenCalledWith('grimdark', true, 'Grimdark')
  })

  it('moves with the arrow keys and toggles with Enter', async () => {
    const { input, onToggle } = setup()
    await userEvent.click(input)
    await userEvent.keyboard('{ArrowDown}{ArrowDown}{Enter}')
    expect(onToggle).toHaveBeenCalledWith('grimdark', true, 'Grimdark')
  })

  it('shows the cap counter and blocks a sixth genre', async () => {
    const { input, onToggle } = setup({
      max: 5, selected: new Set(['fantasy', 'epic-fantasy', 'grimdark', 'mystery', 'noir']) })
    expect(screen.getByText('5/5 tagged')).toBeInTheDocument()
    await userEvent.click(input)
    await userEvent.keyboard('{Enter}') // first option is selected: untagging is allowed
    expect(onToggle).toHaveBeenCalledWith('fantasy', false, 'Fantasy')
  })

  it('disables unselected options at the cap', () => {
    setup({ max: 1, selected: new Set(['fantasy']) })
    expect(screen.getByRole('option', { name: /mystery/ })).toHaveAttribute('aria-disabled', 'true')
  })
})
```

Check `package.json` for `@testing-library/user-event`. If it is absent, run `npm i -D @testing-library/user-event` and commit the lockfile change in this task. The existing Navbar test already uses `userEvent`, so it is most likely present.

- [ ] **Step 2: Write the failing line tests**

`frontend/src/components/GenreLine.test.jsx`:

```jsx
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

vi.mock('../api/client', () => ({ default: { get: vi.fn(), put: vi.fn(), delete: vi.fn(), post: vi.fn() } }))

import client from '../api/client'
import useAuthStore from '../store/auth'
import GenreLine from './GenreLine'

const TREE = [{ slug: 'fantasy', name: 'Fantasy', children: [{ slug: 'grimdark', name: 'Grimdark' }] }]

function mock(payload) {
  client.get.mockImplementation((url) => {
    if (url === '/works/w1/genres') return Promise.resolve({ data: payload })
    if (url === '/genres/') return Promise.resolve({ data: TREE })
    return Promise.reject(new Error(`unexpected GET ${url}`))
  })
}

function renderLine() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter><GenreLine workId="w1" title="Dune" /></MemoryRouter>
    </QueryClientProvider>,
  )
}

const READERS = {
  source: 'readers', my_vote_count: 1,
  genres: [
    { slug: 'fantasy', name: 'Fantasy', parent_slug: null, score: 19, direct_votes: 4, my_vote: false },
    { slug: 'grimdark', name: 'Grimdark', parent_slug: 'fantasy', score: 7, direct_votes: 7, my_vote: true },
  ],
}

beforeEach(() => {
  vi.clearAllMocks()
  useAuthStore.setState({ user: { id: 'u1', username: 'r' }, token: 't' })
})

describe('GenreLine', () => {
  it('shows reader genres as links with counts and marks my vote', async () => {
    mock(READERS)
    renderLine()
    const link = await screen.findByRole('link', { name: 'grimdark' })
    expect(link).toHaveAttribute('href', '/genres/grimdark')
    expect(screen.getByText('19')).toBeInTheDocument()
    expect(screen.getByText('you tagged this')).toHaveClass('sr-only')
  })

  it('labels inferred genres and shows no counts', async () => {
    mock({ source: 'inferred', my_vote_count: 0, genres: [
      { slug: 'fantasy', name: 'Fantasy', parent_slug: null, score: 0, direct_votes: 0, my_vote: false }] })
    renderLine()
    expect(await screen.findByText('genres (inferred)')).toBeInTheDocument()
    expect(screen.queryByText('0')).toBeNull()
  })

  it('shows a dash and the tag control when nothing is known', async () => {
    mock({ source: 'none', my_vote_count: 0, genres: [] })
    renderLine()
    expect(await screen.findByText('no genres yet')).toHaveClass('sr-only')
    expect(screen.getByRole('button', { name: 'tag genres of Dune' })).toBeInTheDocument()
  })

  it('hides the tag control from anonymous readers', async () => {
    useAuthStore.setState({ user: null, token: null })
    mock(READERS)
    renderLine()
    await screen.findByRole('link', { name: 'grimdark' })
    expect(screen.queryByRole('button', { name: 'tag genres of Dune' })).toBeNull()
  })

  it('rolls back and shows the server’s sentence when a vote is refused', async () => {
    mock(READERS)
    client.put.mockRejectedValue({ response: { status: 422, data: {
      detail: "You've tagged this book with 5 genres; remove one first." } } })
    renderLine()
    await userEvent.click(await screen.findByRole('button', { name: 'tag genres of Dune' }))
    await userEvent.click(await screen.findByRole('option', { name: /fantasy/ }))
    expect(await screen.findByRole('alert')).toHaveTextContent('5 genres')
    await waitFor(() => expect(screen.getByText('19')).toBeInTheDocument())
  })
})
```

- [ ] **Step 3: Run to verify they fail**

Run: `cd frontend && npx vitest run src/components/GenrePicker.test.jsx src/components/GenreLine.test.jsx`
Expected: fails to resolve `./GenrePicker` and `./GenreLine`.

- [ ] **Step 4: `api/genres.js`**

```js
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import client from './client'

// Until the tree API lands, /genres/ is flat; a flat item is a parent with no children.
const asTree = (items) => items.map((g) => ({ ...g, children: g.children ?? [] }))

export function useGenreTree() {
  return useQuery({
    queryKey: ['genres'],
    queryFn: () => client.get('/genres/').then((r) => asTree(r.data)),
    staleTime: 10 * 60 * 1000, // the taxonomy changes with a deploy, not a click
  })
}

export function useWorkGenres(workId) {
  return useQuery({
    queryKey: ['work-genres', workId],
    queryFn: () => client.get(`/works/${workId}/genres`).then((r) => r.data),
    enabled: !!workId,
  })
}

// Optimistic: flip my_vote and nudge the count, then take the server's payload.
function toggled(payload, slug, name, on) {
  const found = payload.genres.some((g) => g.slug === slug)
  const genres = found
    ? payload.genres.map((g) => (g.slug === slug
      ? { ...g, my_vote: on, score: g.score + (on ? 1 : -1), direct_votes: g.direct_votes + (on ? 1 : -1) }
      : g))
    : on ? [...payload.genres, { slug, name, parent_slug: null, score: 1, direct_votes: 1, my_vote: true }] : payload.genres
  return {
    ...payload,
    source: on ? 'readers' : payload.source,
    genres,
    my_vote_count: (payload.my_vote_count ?? 0) + (on ? 1 : -1),
  }
}

function useGenreToggle(workId, on) {
  const queryClient = useQueryClient()
  const key = ['work-genres', workId]
  return useMutation({
    mutationFn: ({ slug }) => (on ? client.put : client.delete)(`/works/${workId}/genres/${slug}`).then((r) => r.data),
    onMutate: async ({ slug, name }) => {
      await queryClient.cancelQueries({ queryKey: key })
      const previous = queryClient.getQueryData(key)
      if (previous) queryClient.setQueryData(key, toggled(previous, slug, name, on))
      return { previous }
    },
    onError: (_error, _vars, context) => {
      if (context?.previous) queryClient.setQueryData(key, context.previous)
    },
    onSuccess: (data) => queryClient.setQueryData(key, data),
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: ['series'] })
      queryClient.invalidateQueries({ queryKey: ['works'] })
    },
  })
}

export const useVoteGenre = (workId) => useGenreToggle(workId, true)
export const useUnvoteGenre = (workId) => useGenreToggle(workId, false)
```

- [ ] **Step 5: `components/GenrePicker.jsx`**

```jsx
import { useEffect, useId, useMemo, useState } from 'react'

/**
 * A curated-list picker: the input only filters the taxonomy, it never
 * submits text. Controlled — the parent owns `selected` and decides what a
 * toggle does (vote, or add a search filter).
 */
function GenrePicker({ tree, selected, onToggle, onClose, max, label }) {
  const [query, setQuery] = useState('')
  const [active, setActive] = useState(0)
  const listId = useId()

  const rows = useMemo(() => {
    const q = query.trim().toLowerCase()
    const hit = (g) => !q || g.slug.includes(q.replace(/\s+/g, '-')) || g.name.toLowerCase().includes(q)
    const out = []
    for (const parent of tree) {
      const kids = parent.children.filter(hit)
      // A parent shown only as context for a matching subgenre is not a hit.
      if (hit(parent) || kids.length) out.push({ ...parent, depth: 0, hit: hit(parent) })
      kids.forEach((kid, i) => out.push({ ...kid, depth: 1, hit: true, last: i === kids.length - 1 }))
    }
    return out
  }, [tree, query])

  // Enter acts on the first real match, never on a context-only parent row.
  useEffect(() => setActive(Math.max(0, rows.findIndex((r) => r.hit))), [rows])

  const full = max != null && selected.size >= max
  const disabled = (row) => full && !selected.has(row.slug)
  const toggle = (row) => {
    if (!row || disabled(row)) return
    onToggle(row.slug, !selected.has(row.slug), row.name)
  }

  const onKeyDown = (e) => {
    if (e.key === 'ArrowDown') { e.preventDefault(); setActive((a) => Math.min(a + 1, rows.length - 1)) }
    else if (e.key === 'ArrowUp') { e.preventDefault(); setActive((a) => Math.max(a - 1, 0)) }
    else if (e.key === 'Enter') { e.preventDefault(); toggle(rows[active]) }
    else if (e.key === 'Escape') { e.preventDefault(); onClose() }
  }

  return (
    <div className="float p-3 flex flex-col gap-2 w-[36ch] max-w-full" role="dialog" aria-label={label}>
      <div className="flex items-baseline justify-between gap-3 text-xs">
        <span className="text-ink-dim">{label}</span>
        {max != null && <span className="text-ink-dim tabular-nums">{selected.size}/{max} tagged</span>}
      </div>
      <input
        autoFocus
        role="combobox"
        aria-label="filter genres"
        aria-expanded="true"
        aria-controls={listId}
        aria-activedescendant={rows[active] ? `${listId}-${rows[active].slug}` : undefined}
        className="input"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        onKeyDown={onKeyDown}
      />
      {rows.length === 0 ? (
        <p className="text-ink-dim text-xs">no such genre — the list is curated</p>
      ) : (
        <ul id={listId} role="listbox" aria-multiselectable="true" className="max-h-72 overflow-y-auto text-sm">
          {rows.map((row, i) => (
            <li
              key={row.slug}
              id={`${listId}-${row.slug}`}
              role="option"
              aria-selected={selected.has(row.slug)}
              aria-disabled={disabled(row) ? 'true' : undefined}
              onMouseDown={(e) => e.preventDefault()}
              onClick={() => toggle(row)}
              className={`flex gap-2 px-1 cursor-pointer ${i === active ? 'bg-highlight' : ''} ${
                disabled(row) ? 'text-ink-dim cursor-not-allowed' : ''}`}
            >
              {row.depth === 1 && <span aria-hidden="true" className="text-ink-faint">{row.last ? '└─' : '├─'}</span>}
              <span className={selected.has(row.slug) ? 'text-accent underline underline-offset-4' : 'text-path'}>
                {row.slug}
              </span>
            </li>
          ))}
        </ul>
      )}
      {full && <p className="text-ink-dim text-xs">remove one to add another</p>}
      <div className="flex justify-end">
        <button type="button" className="btn-ghost text-xs" onClick={onClose}>[done]</button>
      </div>
    </div>
  )
}

export default GenrePicker
```

- [ ] **Step 6: `components/GenreLine.jsx`**

```jsx
import { Fragment, useState } from 'react'
import { Link } from 'react-router-dom'
import { useGenreTree, useUnvoteGenre, useVoteGenre, useWorkGenres } from '../api/genres'
import { errorMessage } from '../api/errors'
import useAuthStore from '../store/auth'
import GenrePicker from './GenrePicker'

/** One line of a book's genres: `genres  grimdark 7 · fantasy 19  [tag]`. */
function GenreLine({ workId, title }) {
  const user = useAuthStore((s) => s.user)
  const { data } = useWorkGenres(workId)
  const { data: tree = [] } = useGenreTree()
  const vote = useVoteGenre(workId)
  const unvote = useUnvoteGenre(workId)
  const [open, setOpen] = useState(false)
  const [error, setError] = useState(null)

  if (!data) return null
  const readers = data.source === 'readers'
  const shown = data.genres.filter((g) => !g.vetoed)
  const mine = new Set(shown.filter((g) => g.my_vote).map((g) => g.slug))

  const onToggle = (slug, on, name) => {
    setError(null)
    ;(on ? vote : unvote).mutate({ slug, name }, { onError: (e) => setError(errorMessage(e)) })
  }

  return (
    <div className="relative text-xs flex flex-col gap-1">
      <p className="flex flex-wrap items-baseline gap-x-2">
        <span className="text-ink-dim">{data.source === 'inferred' ? 'genres (inferred)' : 'genres'}</span>
        {shown.length === 0 && (
          <>
            <span aria-hidden="true" className="text-ink-dim">—</span>
            <span className="sr-only">no genres yet</span>
          </>
        )}
        {shown.map((g, i) => (
          <Fragment key={g.slug}>
            {i > 0 && <span aria-hidden="true" className="text-ink-faint">·</span>}
            <span>
              {g.my_vote && (
                <>
                  <span aria-hidden="true" className="text-accent">● </span>
                  <span className="sr-only">you tagged this</span>
                </>
              )}
              <Link to={`/genres/${g.slug}`} className="text-path hover:text-accent transition-colors duration-fast">
                {g.slug}
              </Link>
              {readers && <span className="text-ink-dim tabular-nums"> {g.score}</span>}
            </span>
          </Fragment>
        ))}
        {user && (
          <button type="button" className="btn-ghost text-xs" aria-label={`tag genres of ${title}`}
                  aria-expanded={open} onClick={() => setOpen((v) => !v)}>
            [tag]
          </button>
        )}
      </p>
      {error && <p role="alert" className="text-danger">{error}</p>}
      {open && (
        <div className="absolute z-10 top-full left-0 mt-1">
          <GenrePicker tree={tree} selected={mine} max={5} label={`tag ${title}`}
                       onToggle={onToggle} onClose={() => setOpen(false)} />
        </div>
      )}
    </div>
  )
}

export default GenreLine
```

`●` is the own-vote marker from spec §9.1. Task 14 records it in the glyph set. `text-danger` must be an existing token utility: check `tailwind.config.js` for `danger`. `.alert-danger` exists, so `text-danger` almost certainly does too.

- [ ] **Step 7: Put it on the series page**

In `pages/Series.jsx`:
- `import GenreLine from '../components/GenreLine'`
- in `BookRow`, after `<ShelfButton … />`, add `<GenreLine workId={work.id} title={work.title} />`

In `pages/Series.test.jsx`, make the client mock answer the new GETs. In its `get` implementation, add before the fallthrough:

```js
    if (/^\/works\/[^/]+\/genres$/.test(url)) return Promise.resolve({ data: { source: 'none', genres: [], my_vote_count: null } })
    if (url === '/genres/') return Promise.resolve({ data: [] })
```

- [ ] **Step 8: Run the frontend tests**

Run: `cd frontend && npm test`
Expected: all PASS.

- [ ] **Step 9: Check it in the browser**

With `docker compose up`, open `http://localhost:5173/series/red-rising`. Each book row shows `genres (inferred) …` or `genres —`. Sign in, click `[tag]`, filter "space", press Enter. The line shows `● space-opera 1`. Click the option again to untag. Apply the §36 test from CLAUDE.md: no pills, genres in the path colour, and the cover still dominant.

- [ ] **Step 10: Commit**

```bash
git add -A frontend
git commit -m "feat(web): genre line and curated genre picker on series pages"
```

---

### Task 8: Genre pages API — tree, roll-up listing, subgenre rooms

**Files:**
- Modify: `backend/app/api/genres.py`, `backend/app/api/threads.py`, `backend/app/schemas/genre.py`, `backend/app/schemas/book.py`
- Test: create `backend/tests/test_genre_pages.py`; update `backend/tests/test_pagination.py` (Task 5 already touched it) if its genre-works expectations assume title order

**Interfaces:**
- Consumes: `effective_work_genres`, `load_work_presentation`, `work_out`.
- Produces:
  - `GET /api/genres/` → `list[GenreNode]` with `{id, slug, name, description, children: [{slug, name}]}`
  - `GET /api/genres/{slug}` → `GenreOut` with `{id, slug, name, description, parent: {slug,name}|null, children: [{slug, name, book_count}], retired, room_slug}`
  - `GET /api/genres/{slug}/works?sort=top|title&limit&offset` → `list[GenreWorkOut]` (a `WorkOut` plus `inferred: bool`)
  - `GET /api/genres/{slug}/threads`: the room's threads (the parent's, for a subgenre)
  - `POST /api/threads/` with a subgenre or a retired genre → 422

- [ ] **Step 1: Write the failing tests**

`backend/tests/test_genre_pages.py`:

```python
from datetime import datetime, timezone

from app.models import Thread
from app.services import genres as genres_service
from tests.librarian_factories import headers_for, make_user, make_work


async def test_tree_lists_live_parents_with_children_in_order(client, db_session, taxonomy):
    taxonomy["noir"].retired_at = datetime.now(timezone.utc)
    await db_session.commit()
    tree = (await client.get("/api/genres/")).json()
    assert tree[0]["slug"] == "literary-fiction"
    fantasy = next(g for g in tree if g["slug"] == "fantasy")
    assert [c["slug"] for c in fantasy["children"]][:2] == ["epic-fantasy", "grimdark"]
    mystery = next(g for g in tree if g["slug"] == "mystery")
    assert "noir" not in [c["slug"] for c in mystery["children"]]
    assert all("children" not in c for c in fantasy["children"])


async def test_a_subgenre_names_its_parent_and_room(client, db_session, taxonomy):
    await db_session.commit()
    body = (await client.get("/api/genres/grimdark")).json()
    assert body["parent"] == {"slug": "fantasy", "name": "Fantasy"}
    assert (body["room_slug"], body["children"], body["retired"]) == ("fantasy", [], False)


async def test_a_parent_counts_books_per_subgenre(client, db_session, taxonomy):
    w = await make_work(db_session, "Prince of Thorns")
    await genres_service.set_inferences(db_session, w, {"grimdark"}, "open_library")
    await db_session.commit()
    body = (await client.get("/api/genres/fantasy")).json()
    grim = next(c for c in body["children"] if c["slug"] == "grimdark")
    assert grim["book_count"] == 1 and body["room_slug"] == "fantasy"


async def test_a_retired_slug_still_answers(client, db_session, taxonomy):
    taxonomy["noir"].retired_at = datetime.now(timezone.utc)
    await db_session.commit()
    resp = await client.get("/api/genres/noir")
    assert resp.status_code == 200 and resp.json()["retired"] is True


async def test_parent_page_rolls_up_and_sorts_voted_books_first(client, db_session, taxonomy):
    voted, inferred = await make_work(db_session, "Zzz Voted"), await make_work(db_session, "Aaa Inferred")
    await genres_service.set_inferences(db_session, inferred, {"epic-fantasy"}, "open_library")
    await db_session.commit()
    await client.put(f"/api/works/{voted.id}/genres/grimdark", headers=headers_for(await make_user(db_session)))

    top = (await client.get("/api/genres/fantasy/works")).json()
    assert [(w["title"], w["inferred"]) for w in top] == [("Zzz Voted", False), ("Aaa Inferred", True)]
    by_title = (await client.get("/api/genres/fantasy/works", params={"sort": "title"})).json()
    assert [w["title"] for w in by_title] == ["Aaa Inferred", "Zzz Voted"]
    assert (await client.get("/api/genres/fantasy/works", params={"sort": "new"})).status_code == 422


async def test_a_subgenre_shows_its_parents_threads(client, db_session, taxonomy):
    user = await make_user(db_session)
    db_session.add(Thread(title="Is grimdark over?", user_id=user.id, genre_id=taxonomy["fantasy"].id))
    await db_session.commit()
    titles = [t["title"] for t in (await client.get("/api/genres/grimdark/threads")).json()]
    assert titles == ["Is grimdark over?"]


async def test_a_subgenre_cannot_be_a_thread_room(client, db_session, taxonomy):
    user = await make_user(db_session)
    await db_session.commit()
    resp = await client.post("/api/threads/", headers=headers_for(user),
                             json={"title": "t", "genre_slug": "grimdark", "content": "c"})
    assert resp.status_code == 422
    assert resp.json()["detail"] == "Discussion about Grimdark happens in Fantasy."
```

Check `tests/test_threads.py` for the exact thread-create payload (`content` vs `body`) and match it.

- [ ] **Step 2: Run to verify they fail**

Run: `cd backend && pytest tests/test_genre_pages.py -v`
Expected: FAIL on the missing `parent`, `room_slug`, `inferred` and `sort`.

- [ ] **Step 3: Schemas**

Append to `schemas/genre.py`:

```python
class GenreChild(GenreRef):
    book_count: int = 0


class GenreNode(BaseModel):
    """A top-level genre on the home page, with its subgenres."""

    id: UUID
    slug: str
    name: str
    description: str | None = None
    children: list[GenreRef] = []


class GenreOut(BaseModel):
    id: UUID
    slug: str
    name: str
    description: str | None = None
    parent: GenreRef | None = None
    children: list[GenreChild] = []
    retired: bool = False
    room_slug: str  # where this genre's discussion lives: itself, or its parent
```

In `schemas/book.py`:
- delete the old `GenreOut`
- add after `WorkOut`:

```python
class GenreWorkOut(WorkOut):
    """A book on a genre page; ``inferred`` when no reader has voted its genres yet."""

    inferred: bool = False
```

- [ ] **Step 4: Rewrite `api/genres.py`**

```python
from __future__ import annotations

from collections import defaultdict
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Genre, Thread, Work, WorkKind, effective_work_genres as ewg
from app.schemas.book import GenreWorkOut, work_out
from app.schemas.genre import GenreChild, GenreNode, GenreOut, GenreRef
from app.schemas.thread import ThreadSummary
from app.services.auth import get_current_user_optional
from app.services.threads import thread_summaries
from app.services.works import load_work_presentation

router = APIRouter(prefix="/genres", tags=["genres"])

_LISTED = (Work.kind == WorkKind.single, Work.merged_into_id.is_(None))  # tombstones are reachable, not listed


async def _get_genre_or_404(slug: str, db: AsyncSession) -> Genre:
    genre = (await db.execute(select(Genre).where(Genre.slug == slug))).scalars().first()
    if genre is None:
        raise HTTPException(status_code=404, detail="Genre not found")
    return genre


async def _room(db: AsyncSession, genre: Genre) -> Genre:
    """Subgenres have no rooms of their own (D9): their discussion is the parent's."""
    return await db.get(Genre, genre.parent_id) if genre.parent_id else genre


@router.get("/", response_model=list[GenreNode])
async def list_genres(db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(Genre).where(Genre.retired_at.is_(None))
                             .order_by(Genre.position, Genre.name))).scalars().all()
    children: dict[UUID, list[GenreRef]] = defaultdict(list)
    for g in rows:
        if g.parent_id is not None:
            children[g.parent_id].append(GenreRef(slug=g.slug, name=g.name))
    return [GenreNode(id=g.id, slug=g.slug, name=g.name, description=g.description, children=children[g.id])
            for g in rows if g.parent_id is None]


@router.get("/{slug}", response_model=GenreOut)
async def get_genre(slug: str, db: AsyncSession = Depends(get_db)):
    genre = await _get_genre_or_404(slug, db)
    room = await _room(db, genre)
    kids = [] if genre.parent_id else (await db.execute(
        select(Genre).where(Genre.parent_id == genre.id, Genre.retired_at.is_(None))
        .order_by(Genre.position, Genre.name))).scalars().all()
    counts = dict((await db.execute(
        select(ewg.c.genre_id, func.count()).join(Work, Work.id == ewg.c.work_id)
        .where(ewg.c.genre_id.in_([k.id for k in kids]), *_LISTED).group_by(ewg.c.genre_id))).all()) if kids else {}
    return GenreOut(
        id=genre.id, slug=genre.slug, name=genre.name, description=genre.description,
        parent=GenreRef(slug=room.slug, name=room.name) if room.id != genre.id else None,
        children=[GenreChild(slug=k.slug, name=k.name, book_count=counts.get(k.id, 0)) for k in kids],
        retired=genre.retired_at is not None, room_slug=room.slug,
    )


@router.get("/{slug}/works", response_model=list[GenreWorkOut])
async def get_genre_works(
    slug: str,
    db: AsyncSession = Depends(get_db),
    sort: Literal["top", "title"] = Query("top"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    """Books whose effective genres include this one; a parent includes its
    subgenres' books through the roll-up. ``top`` puts voted books first."""
    genre = await _get_genre_or_404(slug, db)
    order = ((ewg.c.score.desc(), Work.readinglog_count.desc(), Work.title, Work.id) if sort == "top"
             else (Work.title, Work.id))
    rows = (await db.execute(
        select(Work, ewg.c.source).join(ewg, ewg.c.work_id == Work.id)
        .where(ewg.c.genre_id == genre.id, *_LISTED).order_by(*order).limit(limit).offset(offset))).all()
    presentation = await load_work_presentation(db, [w.id for w, _ in rows])
    return [GenreWorkOut(**work_out(w, presentation.get(w.id)).model_dump(), inferred=source == "inferred")
            for w, source in rows]


@router.get("/{slug}/threads", response_model=list[ThreadSummary])
async def get_genre_threads(
    slug: str,
    db: AsyncSession = Depends(get_db),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current_user=Depends(get_current_user_optional),
):
    room = await _room(db, await _get_genre_or_404(slug, db))
    return await thread_summaries(
        db, Thread.genre_id == room.id, current_user=current_user, limit=limit, offset=offset
    )
```

- [ ] **Step 5: Refuse subgenre and retired rooms in `api/threads.py`**

Replace the `genre_id` resolution block (`genre_id = payload.genre_id` … `genre_id = genre.id`) with:

```python
    genre = None
    if payload.genre_slug and payload.genre_id is None:
        genre = (await db.execute(select(Genre).where(Genre.slug == payload.genre_slug))).scalars().first()
    elif payload.genre_id is not None:
        genre = await db.get(Genre, payload.genre_id)
    if (payload.genre_slug or payload.genre_id) and genre is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Genre not found")
    if genre is not None:
        # Rooms are parents only (spec D9); a subgenre's discussion is its parent's.
        if genre.parent_id is not None:
            parent = await db.get(Genre, genre.parent_id)
            raise HTTPException(status_code=422, detail=f"Discussion about {genre.name} happens in {parent.name}.")
        if genre.retired_at is not None:
            raise HTTPException(status_code=422, detail=f"{genre.name} is no longer in the genre list.")
    genre_id = genre.id if genre is not None else None
```

Read the surrounding function first so the variable names match (`genre_id` is later passed to `create_thread`).

- [ ] **Step 6: Run the tests**

Run: `cd backend && pytest tests/test_genre_pages.py tests/test_genre_works.py tests/test_pagination.py tests/test_threads.py -v && pytest -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add -A backend
git commit -m "feat(genres): genre tree, subgenre roll-up listing, parent-only rooms"
```

---

### Task 9: Genre page and Home on the tree

**Files:**
- Modify: `frontend/src/api/genres.js` (add `useGenre`, `useGenreWorks`, `useGenreThreads`), `frontend/src/pages/Genre.jsx`, `frontend/src/pages/Home.jsx`
- Test: `frontend/src/pages/Genre.test.jsx`, `frontend/src/pages/Home.test.jsx`

**Interfaces:**
- Consumes: the Task 8 endpoints.
- Produces:
  - `useGenre(slug)` → `['genres', slug]`
  - `useGenreWorks(slug, sort)` → `['genres', slug, 'works', sort]`
  - `useGenreThreads(slug)` → `['genres', slug, 'threads']`. This is the same key `api/threads.js` invalidates, so keep it exactly.

- [ ] **Step 1: Write the failing tests**

Update `mockApi` in `Genre.test.jsx` so the genre payload carries the new fields, and add cases:

```jsx
const GENRE = {
  slug: 'fantasy', name: 'Fantasy', description: 'Magic, myth, and invented worlds.',
  parent: null, retired: false, room_slug: 'fantasy',
  children: [{ slug: 'grimdark', name: 'Grimdark', book_count: 3 }],
}
const SUB = { slug: 'grimdark', name: 'Grimdark', description: null, parent: { slug: 'fantasy', name: 'Fantasy' },
              retired: false, room_slug: 'fantasy', children: [] }

function mockApi({ genre = GENRE, threads = [THREAD], works = [], slug = 'fantasy' } = {}) {
  client.get.mockImplementation((url) => {
    if (url === `/genres/${slug}`) {
      return genre ? Promise.resolve({ data: genre }) : Promise.reject({ response: { status: 404 } })
    }
    if (url === `/genres/${slug}/works`) return Promise.resolve({ data: works })
    if (url === `/genres/${slug}/threads`) return Promise.resolve({ data: threads })
    return Promise.reject(new Error(`unexpected GET ${url}`))
  })
}
```

Make `renderPage(path = '/genres/fantasy')` take the path.

```jsx
  it('indexes a parent’s subgenres with book counts', async () => {
    mockApi()
    renderPage()
    const sub = await screen.findByRole('link', { name: /grimdark/ })
    expect(sub).toHaveAttribute('href', '/genres/grimdark')
    expect(sub).toHaveTextContent('3')
  })

  it('sends a subgenre’s discussion to its parent', async () => {
    mockApi({ genre: SUB, slug: 'grimdark' })
    renderPage('/genres/grimdark')
    expect(await screen.findByText(/discussion lives in/)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'fantasy' })).toHaveAttribute('href', '/genres/fantasy')
    expect(screen.queryByRole('button', { name: 'Start a Discussion' })).toBeNull()
    expect(client.get).not.toHaveBeenCalledWith('/genres/grimdark/threads', expect.anything())
  })

  it('marks inferred books and toggles the sort', async () => {
    mockApi({ works: [{ id: 'w1', title: 'Prince of Thorns', author: 'Mark Lawrence', kind: 'single',
                        edition_count: 1, inferred: true, top_genres: [] }] })
    renderPage()
    expect(await screen.findByText('inferred')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'title' }))
    await waitFor(() => expect(client.get).toHaveBeenCalledWith('/genres/fantasy/works', { params: { sort: 'title' } }))
  })
```

Import `userEvent`, and `waitFor` from RTL. In `Home.test.jsx`, add a case: the mocked `/genres/` returns `[{ slug: 'fantasy', name: 'Fantasy', description: 'd', children: [{ slug: 'grimdark', name: 'Grimdark' }] }]`, and a link named `grimdark` with href `/genres/grimdark` renders.

- [ ] **Step 2: Run to verify they fail**

Run: `cd frontend && npx vitest run src/pages/Genre.test.jsx src/pages/Home.test.jsx`
Expected: FAIL.

- [ ] **Step 3: Hooks**

Append to `api/genres.js`:

```js
export function useGenre(slug) {
  return useQuery({
    queryKey: ['genres', slug],
    queryFn: () => client.get(`/genres/${slug}`).then((r) => r.data),
    enabled: !!slug,
  })
}

export function useGenreWorks(slug, sort = 'top') {
  return useQuery({
    queryKey: ['genres', slug, 'works', sort],
    queryFn: () => client.get(`/genres/${slug}/works`, { params: { sort } }).then((r) => r.data),
    enabled: !!slug,
  })
}

// Keyed like api/threads.js invalidates it: ['genres', roomSlug, 'threads'].
export function useGenreThreads(slug) {
  return useQuery({
    queryKey: ['genres', slug, 'threads'],
    queryFn: () => client.get(`/genres/${slug}/threads`).then((r) => r.data),
    enabled: !!slug,
  })
}
```

- [ ] **Step 4: `pages/Genre.jsx`**

Replace the three inline `useQuery` calls with the hooks. Add the sort state, the subgenre index, the inferred marker and the room rule. The changed parts are below; `columns` and the modal stay as they are.

```jsx
import { useGenre, useGenreThreads, useGenreWorks } from '../api/genres'
// …
  const [sort, setSort] = useState('top')
  const { data: genre, isLoading, isError } = useGenre(genreSlug)
  const { data: works } = useGenreWorks(genreSlug, sort)
  const isRoom = !!genre && !genre.parent
  const { data: threads } = useGenreThreads(isRoom ? genreSlug : null)
// …
  const path = [{ label: 'genres', to: '/' }]
  if (genre.parent) path.push({ label: genre.parent.slug, to: `/genres/${genre.parent.slug}` })
  path.push({ label: genre.slug })
```

JSX, in order after the header:

```jsx
      <PathHeader segments={path} />
      {/* header unchanged */}
      {genre.retired && <p className="alert-muted">This genre was retired from the list; its books and threads stay reachable.</p>}

      {genre.children.length > 0 && (
        <section className="flex flex-col gap-3" aria-labelledby="subgenres">
          <h2 id="subgenres" className="text-xs uppercase tracking-eyebrow text-ink-dim border-b border-line pb-2">
            Subgenres
          </h2>
          <ul className="grid sm:grid-cols-2 lg:grid-cols-3 gap-x-8">
            {genre.children.map((child) => (
              <li key={child.slug}>
                <Link to={`/genres/${child.slug}`}
                      className="flex justify-between gap-3 py-1 px-2 -mx-2 hover:bg-highlight transition-colors duration-fast">
                  <span className="text-path">{child.slug}</span>
                  <span className="text-ink-dim tabular-nums">{child.book_count}</span>
                </Link>
              </li>
            ))}
          </ul>
        </section>
      )}

      {works && works.length > 0 && (
        <section className="flex flex-col gap-4">
          <div className="flex items-baseline justify-between border-b border-line pb-2">
            <h2 className="text-xs uppercase tracking-eyebrow text-ink-dim">Books</h2>
            <div role="group" aria-label="Sort books" className="flex gap-3 text-xs">
              {['top', 'title'].map((s) => (
                <button key={s} type="button" aria-pressed={sort === s} onClick={() => setSort(s)}
                        className={sort === s ? 'text-accent underline underline-offset-4' : 'text-ink-dim hover:text-accent'}>
                  {s}
                </button>
              ))}
            </div>
          </div>
          <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 gap-5">
            {works.map((work) => (
              <div key={work.id} className="flex flex-col gap-1">
                {work.inferred && <p className="text-xs uppercase tracking-eyebrow text-ink-dim">inferred</p>}
                <WorkCard work={work} />
              </div>
            ))}
          </div>
        </section>
      )}

      {isRoom ? (
        <section className="panel p-5 pt-6">{/* the Discussions panel, unchanged */}</section>
      ) : (
        <p className="text-ink-dim text-sm">
          discussion lives in{' '}
          <Link to={`/genres/${genre.room_slug}`} className="text-path hover:text-accent">{genre.room_slug}</Link>
        </p>
      )}
```

The inferred marker is `text-ink-dim`, not `.eyebrow`: `.eyebrow` is accent-coloured, and accent means interactive. Remove the `useQuery` and `client` imports if nothing else uses them.

- [ ] **Step 5: `pages/Home.jsx`**

- Use `useGenreTree()`.
- Map `FALLBACK_GENRES` to `{ ...g, children: [] }` as the fallback.
- Under each parent's `<Link>`, render up to three subgenres:

```jsx
              {genre.children.length > 0 && (
                <ul className="pl-4 sm:pl-52 text-sm">
                  {genre.children.slice(0, 3).map((child, i) => (
                    <li key={child.slug}>
                      <Link to={`/genres/${child.slug}`}
                            className="flex gap-2 px-2 -mx-2 hover:bg-highlight transition-colors duration-fast">
                        <span aria-hidden="true" className="text-ink-faint">
                          {i === 2 || i === genre.children.length - 1 ? '└─' : '├─'}
                        </span>
                        <span className="text-path">{child.slug}</span>
                      </Link>
                    </li>
                  ))}
                </ul>
              )}
```

The parent row stays as it is today. The subgenres list sits inside the same `<li>`.

- [ ] **Step 6: Run the tests, then look at it**

Run: `cd frontend && npm test`
Expected: PASS.

Open `http://localhost:5173/`, `/genres/fantasy` and `/genres/grimdark`, and apply the §36 test.

- [ ] **Step 7: Commit**

```bash
git add -A frontend
git commit -m "feat(web): genre tree on home; subgenre pages defer discussion to the parent"
```

---

### Task 10: Vetoes — service, undo, API, merge preview count

**Files:**
- Modify:
  - `backend/app/services/librarian/genres.py` (add `veto_genre`)
  - `backend/app/services/librarian/__init__.py`, `backend/app/services/librarian/record.py`, `backend/app/services/librarian/undo.py`, `backend/app/services/librarian/identity.py`
  - `backend/app/api/librarian.py`, `backend/app/schemas/librarian.py`
- Test: create `backend/tests/test_genre_vetoes.py`

**Interfaces:**
- Consumes: `record`, `clean_reason`, `live_work`, `locked` (librarian/record); `genres.recompute`, `work_genres_payload`.
- Produces:
  - `async def veto_genre(db, user, work, genre, *, reason: str) -> CatalogCorrection`
  - `POST /api/librarian/works/{id}/genres/{slug}/veto` `{reason}` → 201 `CorrectionOut`
  - Undo through the existing `POST /api/librarian/corrections/{id}/revert`
  - `MergePreviewOut.genre_votes: int`

- [ ] **Step 1: Write the failing tests**

`backend/tests/test_genre_vetoes.py`:

```python
import pytest

from app.models import CatalogCorrection, CorrectionOp
from app.services import genres as genres_service
from app.services.librarian import revert, set_series, veto_genre
from app.services.librarian.errors import Conflict, Invalid
from tests.genre_factories import effective
from tests.librarian_factories import headers_for, make_series, make_user, make_work


async def test_veto_hides_and_undo_restores_exactly(db_session, taxonomy):
    lib, reader = await make_user(db_session, librarian=True), await make_user(db_session)
    w = await make_work(db_session, "Dune")
    await genres_service.vote(db_session, reader, w, taxonomy["space-opera"])
    before = await effective(db_session, w)
    c = await veto_genre(db_session, lib, w, taxonomy["space-opera"], reason="troll tagging")
    assert (c.op, c.override, c.runtime_only_reason) == (
        CorrectionOp.veto_genre, None, "the pipeline has no genre overrides")
    assert await effective(db_session, w) == {}
    await revert(db_session, lib, c)
    assert await effective(db_session, w) == before


async def test_vetoing_twice_is_a_conflict_and_a_reason_is_required(db_session, taxonomy):
    lib, w = await make_user(db_session, librarian=True), await make_work(db_session, "Dune")
    with pytest.raises(Invalid):
        await veto_genre(db_session, lib, w, taxonomy["horror"], reason="  ")
    await veto_genre(db_session, lib, w, taxonomy["horror"], reason="wrong genre")
    with pytest.raises(Conflict):
        await veto_genre(db_session, lib, w, taxonomy["horror"], reason="wrong genre")


async def test_vetoing_a_parent_leaves_its_subgenres(db_session, taxonomy):
    lib, reader, w = await make_user(db_session, librarian=True), await make_user(db_session), await make_work(db_session, "Dune")
    await genres_service.vote(db_session, reader, w, taxonomy["space-opera"])
    await veto_genre(db_session, lib, w, taxonomy["science-fiction"], reason="too broad for this book")
    assert set(await effective(db_session, w)) == {"space-opera"}


async def test_a_veto_and_a_move_on_one_book_undo_independently(db_session, taxonomy):
    # Review Focus 2: vetoes are their own (work, genre) queue.
    lib = await make_user(db_session, librarian=True)
    saga = await make_series(db_session, "Dune Saga")
    w = await make_work(db_session, "Dune")
    veto = await veto_genre(db_session, lib, w, taxonomy["horror"], reason="wrong genre")
    move = await set_series(db_session, lib, w, series=saga, reason="belongs to this series")
    await revert(db_session, lib, veto)   # not blocked by the later move
    await revert(db_session, lib, move)   # not blocked by a veto
    second = await veto_genre(db_session, lib, w, taxonomy["mystery"], reason="wrong genre")
    await veto_genre(db_session, lib, w, taxonomy["noir"], reason="wrong genre")
    await revert(db_session, lib, second)  # different genre: its own queue


async def test_api_status_codes(client, db_session, taxonomy):
    lib, reader, w = await make_user(db_session, librarian=True), await make_user(db_session), await make_work(db_session, "Dune")
    await db_session.commit()
    url = f"/api/librarian/works/{w.id}/genres/horror/veto"
    assert (await client.post(url, json={"reason": "r"})).status_code == 401
    assert (await client.post(url, json={"reason": "r"}, headers=headers_for(reader))).status_code == 403
    assert (await client.post(f"/api/librarian/works/{w.id}/genres/nope/veto", json={"reason": "r"},
                              headers=headers_for(lib))).status_code == 404
    made = await client.post(url, json={"reason": "wrong genre"}, headers=headers_for(lib))
    assert made.status_code == 201 and made.json()["op"] == "veto_genre" and made.json()["undoable"] is True
    assert (await client.post(url, json={"reason": "again"}, headers=headers_for(lib))).status_code == 409
    vote = await client.put(f"/api/works/{w.id}/genres/horror", headers=headers_for(reader))
    assert (vote.status_code, vote.json()["detail"]) == (422, "A librarian removed this genre from this book.")


async def test_librarians_see_vetoed_genres_with_the_fix_to_undo(client, db_session, taxonomy):
    lib, reader, w = await make_user(db_session, librarian=True), await make_user(db_session), await make_work(db_session, "Dune")
    await genres_service.vote(db_session, reader, w, taxonomy["horror"])
    c = await veto_genre(db_session, lib, w, taxonomy["horror"], reason="wrong genre")
    await db_session.commit()
    as_lib = (await client.get(f"/api/works/{w.id}/genres", headers=headers_for(lib))).json()
    vetoed = [g for g in as_lib["genres"] if g["vetoed"]]
    assert [(g["slug"], g["veto_id"]) for g in vetoed] == [("horror", str(c.id))]
    as_reader = (await client.get(f"/api/works/{w.id}/genres", headers=headers_for(reader))).json()
    assert not any(g["vetoed"] for g in as_reader["genres"]) and as_reader["source"] == "none"


async def test_merge_preview_counts_genre_votes(client, db_session, taxonomy):
    lib, reader = await make_user(db_session, librarian=True), await make_user(db_session)
    a, b = await make_work(db_session, "Dune", ol_id="OL1W"), await make_work(db_session, "Dune (1965)", ol_id="OL2W")
    await genres_service.vote(db_session, reader, a, taxonomy["space-opera"])
    await db_session.commit()
    body = (await client.get(f"/api/librarian/works/{a.id}/merge-preview", params={"into": b.id},
                             headers=headers_for(lib))).json()
    assert body["genre_votes"] == 1
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd backend && pytest tests/test_genre_vetoes.py -v`
Expected: ImportError on `veto_genre`.

- [ ] **Step 3: The service**

Append to `services/librarian/genres.py`:

```python
from sqlalchemy import select

from app.models import CatalogCorrection, CorrectionOp, Genre, User, Work
from app.services import genres as genres_service
from app.services.librarian.errors import Conflict, Invalid
from app.services.librarian.record import clean_reason, live_work, locked, record

RUNTIME_ONLY = "the pipeline has no genre overrides"


async def live_veto(db, work_id, genre_id) -> CatalogCorrection | None:
    return (await db.execute(select(CatalogCorrection).where(
        CatalogCorrection.op == CorrectionOp.veto_genre, CatalogCorrection.reverted_at.is_(None),
        CatalogCorrection.work_id == work_id,
        CatalogCorrection.payload["genre_id"].astext == str(genre_id)))).scalars().first()


async def veto_genre(db, user: User, work: Work, genre: Genre, *, reason: str) -> CatalogCorrection:
    """Hide a genre on a book from every reader. Votes are kept, so undo
    restores the book exactly; the veto only ever sets ``reverted_at``."""
    reason = clean_reason(reason)
    work = live_work(await locked(db, work))
    if genre.retired_at is not None:
        raise Invalid(f"{genre.name} is no longer in the genre list.")
    if await live_veto(db, work.id, genre.id) is not None:
        raise Conflict(f"{genre.name} is already vetoed on {work.title}.")
    correction = await record(
        db, op=CorrectionOp.veto_genre, user=user, reason=reason,
        payload={"work_id": str(work.id), "genre_id": str(genre.id)},
        entries=None, runtime_only_reason=RUNTIME_ONLY, work=work,
    )
    await genres_service.recompute(db, [work.id])
    return correction
```

Merge the two import blocks at the top of the file (the `text` import from Task 5 stays). Add `veto_genre` to `services/librarian/__init__.py`:

```python
from app.services.librarian.genres import veto_genre  # noqa: E402,F401
```

- [ ] **Step 4: Scope undo to `(work, genre)`**

In `services/librarian/record.py`, add `GENRE_SUBJECT_OPS = (CorrectionOp.veto_genre,)` and replace the `else:` branch of `latest_for_subject` with:

```python
    elif correction.op in GENRE_SUBJECT_OPS:
        # A veto's subject is (book, genre): it neither blocks nor is blocked by
        # fixes to the book's series, or by vetoes of other genres.
        if correction.work_id is None:
            return None
        query = query.where(CatalogCorrection.work_id == correction.work_id,
                            CatalogCorrection.op == CorrectionOp.veto_genre,
                            CatalogCorrection.payload["genre_id"].astext == correction.payload["genre_id"])
    else:
        if correction.work_id is None:
            return None
        query = query.where(CatalogCorrection.work_id == correction.work_id,
                            CatalogCorrection.op.not_in(GENRE_SUBJECT_OPS))
```

Update its docstring: "…its work (excluding genre vetoes), its (work, genre) for a veto, or its series for rename and dissolve."

In `services/librarian/undo.py`:
- Add `CorrectionOp.veto_genre` to `UNDOABLE`.
- `from app.services import genres as genres_service`
- Add:

```python
async def _undo_veto(db: AsyncSession, c: CatalogCorrection) -> None:
    work = await db.get(Work, c.work_id) if c.work_id else None
    if work is None or work.merged_into_id is not None:
        raise Conflict(_STALE)
    # Nothing to restore: the veto never touched a vote. revert() sets
    # reverted_at, then the summary is recomputed.
```

- Register it with `CorrectionOp.veto_genre: _undo_veto` in `_REVERT`.
- In `revert`, after `await db.flush()`, add:

```python
    if correction.op is CorrectionOp.veto_genre:
        await genres_service.recompute(db, [correction.work_id])
```

- Change the refusal message: `"Merges and splits cannot be undone."` is still right, because veto is now in `UNDOABLE`.

- [ ] **Step 5: The route and the merge count**

In `schemas/librarian.py`, add:

```python
class VetoIn(_Reasoned):
    model_config = ConfigDict(json_schema_extra={"examples": [{"reason": "troll tagging"}]})
```

and `genre_votes: int = 0` on `MergePreviewOut`.

In `services/librarian/identity.py::merge_consequences`:
- import `GenreVote` from `app.models`
- add `"genre_votes": await _count(db, GenreVote, GenreVote.work_id == source.id),` to the returned dict

In `api/librarian.py`:

```python
@router.post("/works/{work_id}/genres/{slug}/veto", **_CREATED)
async def veto_work_genre(work_id: UUID, slug: str, body: VetoIn, db: AsyncSession = Depends(get_db),
                          user: User = Depends(require_librarian)):
    """Hide a genre on a book from readers, with a reason. Undo via the corrections log."""
    work = await _work(db, work_id)
    genre = (await db.execute(select(Genre).where(Genre.slug == slug))).scalar_one_or_none()
    if genre is None:
        raise HTTPException(status_code=404, detail="Unknown genre.")
    c = await _run(librarian.veto_genre(db, user, work, genre, reason=body.reason))
    return await correction_out(db, c)
```

Import `Genre` and `VetoIn`. The merge 422 confirmation now carries `genre_votes` too. `LibrarianPanel.test.jsx` builds those dicts by hand, so nothing there breaks.

- [ ] **Step 6: Run the tests**

Run: `cd backend && pytest tests/test_genre_vetoes.py tests/test_librarian_undo.py tests/test_librarian_api.py tests/test_librarian_merge_preview.py tests/test_librarian_export.py tests/test_openapi.py -v && pytest -q`
Expected: PASS. If `test_librarian_merge_preview.py` compares the whole consequences dict, add `"genre_votes": 0` to its expectation. `test_librarian_export.py` must still show vetoes as not exported.

Extend the drift guard in `tests/test_genre_votes.py`. In its loop, add a branch with `roll >= 0.9` that calls `veto_genre(db_session, lib, w, g, reason="r")` (ignoring `Conflict`), or reverts a random live veto with `revert`. Create `lib = await make_user(db_session, librarian=True)` before the loop. Re-run it.

- [ ] **Step 7: Commit**

```bash
git add -A backend
git commit -m "feat(librarian): veto a book's genre, undoably, scoped to (book, genre)"
```

---

### Task 11: Vetoes in edit mode; merge preview counts genre votes

**Files:**
- Modify:
  - `frontend/src/api/genres.js` (add `useVetoGenre`)
  - `frontend/src/components/GenreLine.jsx` (`editing` prop)
  - `frontend/src/pages/Series.jsx` (pass `editing` to `GenreLine`)
  - `frontend/src/components/librarian/reasons.js`
  - `frontend/src/components/librarian/MergePreview.jsx`
- Test: `frontend/src/components/GenreLine.test.jsx`, `frontend/src/components/librarian/MergePreview.test.jsx`, `frontend/src/components/librarian/reasons.test.js` (if it lists kinds)

**Interfaces:**
- Consumes: `POST /librarian/works/{id}/genres/{slug}/veto`, `useRevertCorrection()` from `api/librarian.js`, `ReasonField`, and `veto_id`/`vetoed` on the payload (Task 10).
- Produces: `useVetoGenre(workId)` and `<GenreLine workId title editing />`.

- [ ] **Step 1: Write the failing tests**

Append to `GenreLine.test.jsx`:

```jsx
const WITH_VETO = {
  ...READERS,
  genres: [...READERS.genres,
    { slug: 'horror', name: 'Horror', parent_slug: null, score: 2, direct_votes: 2, my_vote: false,
      vetoed: true, veto_id: 'c1' }],
}

function renderEditing() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter><GenreLine workId="w1" title="Dune" editing /></MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('GenreLine in edit mode', () => {
  beforeEach(() => useAuthStore.setState({ user: { id: 'l', username: 'lib', is_librarian: true }, token: 't' }))

  it('shows vetoed genres struck through with undo, only in edit mode', async () => {
    mock(WITH_VETO)
    renderEditing()
    const vetoed = await screen.findByText('horror')
    expect(vetoed).toHaveClass('line-through', 'text-warning')
    client.post.mockResolvedValue({ data: {} })
    await userEvent.click(screen.getByRole('button', { name: 'undo veto of horror' }))
    expect(client.post).toHaveBeenCalledWith('/librarian/corrections/c1/revert')
  })

  it('vetoes a genre with a reason', async () => {
    mock(READERS)
    client.post.mockResolvedValue({ data: { id: 'c2' } })
    renderEditing()
    await userEvent.click(await screen.findByRole('button', { name: 'veto grimdark' }))
    await userEvent.click(screen.getByRole('button', { name: 'troll tagging' }))
    await userEvent.click(screen.getByRole('button', { name: 'veto' }))
    expect(client.post).toHaveBeenCalledWith('/librarian/works/w1/genres/grimdark/veto', { reason: 'troll tagging' })
  })

  it('never shows vetoed genres outside edit mode', async () => {
    mock(WITH_VETO)
    renderLine()
    await screen.findByRole('link', { name: 'grimdark' })
    expect(screen.queryByText('horror')).toBeNull()
  })
})
```

`useRevertCorrection()` (in `api/librarian.js`) is `mutate(id)` → `POST /librarian/corrections/{id}/revert`.

In `MergePreview.test.jsx`, change the "states what moves" case to:

```jsx
    render(<MergePreview preview={{ ...PREVIEW, threads: 1, shelves: 2, genre_votes: 3, editions: 0 }} />)
    expect(screen.getByText('1 thread, 2 shelf entries, 3 genre votes and 0 editions move to the survivor.')).toBeInTheDocument()
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd frontend && npx vitest run src/components/GenreLine.test.jsx src/components/librarian/MergePreview.test.jsx`
Expected: FAIL.

- [ ] **Step 3: Implement**

`reasons.js`: add `veto_genre: ['wrong genre', 'troll tagging', 'too broad for this book'],` to `REASONS`.

`api/genres.js`:

```js
export function useVetoGenre(workId) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ slug, reason }) =>
      client.post(`/librarian/works/${workId}/genres/${slug}/veto`, { reason }).then((r) => r.data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['work-genres', workId] })
      queryClient.invalidateQueries({ queryKey: ['genres'] })
      queryClient.invalidateQueries({ queryKey: ['librarian', 'corrections'] })
    },
  })
}
```

`GenreLine.jsx`:
- Accept `editing = false`.
- `const librarian = !!user?.is_librarian && editing`
- `shown` is `data.genres.filter((g) => !g.vetoed)`, as before.
- `const vetoed = librarian ? data.genres.filter((g) => g.vetoed) : []`
- Add the state `const [vetoing, setVetoing] = useState(null)` and `const [reason, setReason] = useState('')`.
- Add `const veto = useVetoGenre(workId)` and `const revertFix = useRevertCorrection()`.

After each shown genre's count, when `librarian`:

```jsx
              {librarian && (
                <button type="button" className="btn-ghost text-xs" aria-label={`veto ${g.slug}`}
                        onClick={() => { setVetoing(g.slug); setReason('') }}>[veto]</button>
              )}
```

After the shown list:

```jsx
        {vetoed.map((g) => (
          <span key={g.slug} className="flex items-baseline gap-1">
            <span className="line-through text-warning">{g.slug}</span>
            <span className="sr-only">vetoed</span>
            <button type="button" className="btn-ghost text-xs" aria-label={`undo veto of ${g.slug}`}
                    onClick={() => revertFix.mutate(g.veto_id)}>
              [undo]
            </button>
          </span>
        ))}
```

`useRevertCorrection` takes the correction id (`mutate(id)`) and already invalidates every query.

Below the line, when `vetoing`:

```jsx
      {vetoing && (
        <form className="float p-3 flex flex-col gap-2 max-w-prose" aria-label={`veto ${vetoing} on ${title}`}
              onSubmit={(e) => {
                e.preventDefault()
                veto.mutate({ slug: vetoing, reason: reason.trim() }, {
                  onSuccess: () => setVetoing(null),
                  onError: (err) => setError(errorMessage(err)),
                })
              }}>
          <ReasonField kind="veto_genre" value={reason} onChange={setReason} id={`veto-${workId}`} />
          <div className="flex gap-3 justify-end">
            <button type="button" className="btn-ghost text-xs" onClick={() => setVetoing(null)}>cancel</button>
            <button type="submit" className="btn-secondary text-xs" disabled={!reason.trim() || veto.isPending}>veto</button>
          </div>
        </form>
      )}
```

Import `ReasonField` from `./librarian/ReasonField`, `useRevertCorrection` from `../api/librarian`, and `useVetoGenre`.

`Series.jsx`: pass `editing={editing}` to `GenreLine` in `BookRow` (`BookRow` already receives `editing`).

`MergePreview.jsx`:
- destructure `genre_votes = 0`
- change the sentence to

```jsx
          {plural(threads, 'thread')}, {plural(shelves, 'shelf entry', 'shelf entries')},{' '}
          {plural(genre_votes, 'genre vote')} and {plural(editions, 'edition')} move to the survivor.
```

If `reasons.test.js` asserts the exact set of `REASONS` keys, add `veto_genre` to it.

- [ ] **Step 4: Run the tests and look at it**

Run: `cd frontend && npm test`
Expected: PASS.

In the browser as a librarian (`docker compose exec backend python -m scripts.grant_librarian <you>`), open a series with `?edit=1`, veto a genre, see it struck through, then undo it.

- [ ] **Step 5: Commit**

```bash
git add -A frontend
git commit -m "feat(web): veto and undo a book's genre from edit mode"
```

---

### Task 12: Search filters — service and API

**Files:**
- Modify: `backend/app/services/search.py`, `backend/app/api/works.py`
- Test: create `backend/tests/test_search_filters.py`

**Interfaces:**
- Consumes: `effective_work_genres`, `Work.author_doc`.
- Produces:
  - `SearchFilters(genres: tuple[str, ...] = (), author: str | None = None, year_from: int | None = None, year_to: int | None = None)` with an `.active` property
  - `InvalidFilter(ValueError)` with `.param`
  - `async def search(db, query: str | None, filters: SearchFilters | None = None, limit=20)`
  - `async def search_local(db, query: str | None, limit=20, filters: SearchFilters | None = None)`
  - `GET /api/works/search?q&genre&genre&author&year_from&year_to`

- [ ] **Step 1: Write the failing tests**

`backend/tests/test_search_filters.py`:

```python
import respx
from httpx import Response

from app.services import genres as genres_service
from tests.librarian_factories import headers_for, make_user
from tests.test_search import DOCS, OL_URL
from tests.test_search_local import make_work


async def seed(db, taxonomy):
    dune = make_work("Dune", "Frank Herbert", first_publish_year=1965, readinglog_count=4402)
    hyperion = make_work("Hyperion", "Dan Simmons", first_publish_year=1989, readinglog_count=900)
    thorns = make_work("Prince of Thorns", "Mark Lawrence", first_publish_year=2011, readinglog_count=300)
    undated = make_work("Undated Opera", "Anon", readinglog_count=10)
    db.add_all([dune, hyperion, thorns, undated])
    await db.flush()
    await genres_service.set_inferences(db, dune, {"space-opera"}, "open_library")
    await genres_service.set_inferences(db, hyperion, {"space-opera", "time-travel"}, "open_library")
    await genres_service.set_inferences(db, thorns, {"grimdark"}, "open_library")
    await genres_service.set_inferences(db, undated, {"space-opera"}, "open_library")
    await db.commit()
    return dune, hyperion, thorns, undated


def titles(resp):
    assert resp.status_code == 200, resp.text
    return [w["title"] for w in resp.json()]


@respx.mock
async def test_a_genre_filter_alone_browses_locally_with_zero_http(client, db_session, taxonomy):
    await seed(db_session, taxonomy)
    got = titles(await client.get("/api/works/search", params={"genre": "space-opera"}))
    assert got == ["Dune", "Hyperion", "Undated Opera"]  # score ties → readinglog_count
    assert respx.calls.call_count == 0


@respx.mock
async def test_a_parent_slug_matches_subgenre_books(client, db_session, taxonomy):
    await seed(db_session, taxonomy)
    assert titles(await client.get("/api/works/search", params={"genre": "fantasy"})) == ["Prince of Thorns"]


@respx.mock
async def test_every_genre_must_match(client, db_session, taxonomy):
    await seed(db_session, taxonomy)
    got = titles(await client.get("/api/works/search", params=[("genre", "space-opera"), ("genre", "time-travel")]))
    assert got == ["Hyperion"]


@respx.mock
async def test_browse_orders_by_the_requested_genres_score(client, db_session, taxonomy):
    dune, hyperion, *_ = await seed(db_session, taxonomy)
    await client.put(f"/api/works/{hyperion.id}/genres/space-opera", headers=headers_for(await make_user(db_session)))
    assert titles(await client.get("/api/works/search", params={"genre": "space-opera"}))[0] == "Hyperion"


@respx.mock
async def test_author_and_year_filters(client, db_session, taxonomy):
    await seed(db_session, taxonomy)
    assert titles(await client.get("/api/works/search", params={"author": "simmons"})) == ["Hyperion"]
    got = titles(await client.get("/api/works/search", params={"genre": "space-opera", "year_from": 1965, "year_to": 1989}))
    assert got == ["Dune", "Hyperion"]  # inclusive, and the undated book is out
    assert titles(await client.get("/api/works/search", params={"year_to": 1970})) == ["Dune"]


@respx.mock
async def test_bad_filters_are_422_naming_the_parameter(client, db_session, taxonomy):
    await seed(db_session, taxonomy)
    for params, param in [({"genre": "no-such"}, "genre"), ({"year_from": 2000, "year_to": 1990}, "year_to"),
                          ({}, "q"), ({"year_from": "soon"}, "year_from")]:
        resp = await client.get("/api/works/search", params=params)
        assert resp.status_code == 422, params
        assert resp.json()["detail"][0]["loc"][-1] == param


@respx.mock
async def test_a_retired_genre_is_refused(client, db_session, taxonomy):
    from datetime import datetime, timezone
    taxonomy["noir"].retired_at = datetime.now(timezone.utc)
    await db_session.commit()
    assert (await client.get("/api/works/search", params={"genre": "noir"})).status_code == 422


@respx.mock
async def test_a_cold_query_with_filters_ingests_once_then_filters_locally(client, db_session, taxonomy):
    route = respx.get(OL_URL).mock(return_value=Response(200, json={"docs": DOCS}))
    await db_session.commit()
    first = titles(await client.get("/api/works/search", params={"q": "red rising", "genre": "science-fiction"}))
    assert first == ["Red Rising"]  # Iron Gold has no genre: subject
    both = titles(await client.get("/api/works/search", params={"q": "red rising"}))
    assert set(both) == {"Red Rising", "Iron Gold"}
    assert route.call_count == 1


@respx.mock
async def test_odd_input(client, db_session, taxonomy):
    # Review Focus 5.
    route = respx.get(OL_URL).mock(return_value=Response(200, json={"docs": DOCS}))
    await seed(db_session, taxonomy)
    bad = await client.get("/api/works/search", params={"q": "never searched", "genre": "no-such"})
    assert bad.status_code == 422 and route.call_count == 0  # validated before any upstream call
    assert titles(await client.get("/api/works/search", params={"q": "!!!", "genre": "grimdark"})) == ["Prince of Thorns"]
    assert route.call_count == 0  # punctuation-only q is a browse
    dup = await client.get("/api/works/search", params=[("genre", "grimdark"), ("genre", "grimdark")])
    assert titles(dup) == ["Prince of Thorns"]
```

`make_work` in `tests/test_search_local.py` returns an unsaved `Work` with a random OL id, and `first_publish_year`/`readinglog_count` pass through `**kw`. It has no `series_id`; the flush listener gives each work a singleton, as in that file's own tests.

- [ ] **Step 2: Run to verify they fail**

Run: `cd backend && pytest tests/test_search_filters.py -v`
Expected: FAIL (422 on the missing `q`, unknown params ignored).

- [ ] **Step 3: Implement the filters in `services/search.py`**

Add these imports:

```python
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import literal

from app.models import Genre, effective_work_genres as ewg
```

Then:

```python
@dataclass(frozen=True)
class SearchFilters:
    """Filters narrow the local query only. Open Library is never asked to
    filter: its subjects are not our genres, and gating stays keyed on ``q``."""

    genres: tuple[str, ...] = ()
    author: str | None = None
    year_from: int | None = None
    year_to: int | None = None

    @property
    def active(self) -> bool:
        return bool(self.genres or self.author or self.year_from is not None or self.year_to is not None)


class InvalidFilter(ValueError):
    def __init__(self, param: str, message: str):
        super().__init__(message)
        self.param = param


async def _genre_ids(db: AsyncSession, filters: SearchFilters) -> list[UUID]:
    """Resolve and validate the filter up front, so a bad one never costs an upstream call."""
    if filters.year_from is not None and filters.year_to is not None and filters.year_from > filters.year_to:
        raise InvalidFilter("year_to", "year_to is before year_from.")
    if not filters.genres:
        return []
    found = dict((await db.execute(select(Genre.slug, Genre.id).where(
        Genre.slug.in_(filters.genres), Genre.retired_at.is_(None)))).all())
    for slug in filters.genres:
        if slug not in found:
            raise InvalidFilter("genre", f"Unknown genre: {slug}.")
    return [found[s] for s in filters.genres]


def _narrow(stmt, filters: SearchFilters, genre_ids: list[UUID]):
    for genre_id in genre_ids:  # every requested genre must be effective
        stmt = stmt.where(select(ewg.c.work_id).where(
            ewg.c.work_id == Work.id, ewg.c.genre_id == genre_id).exists())
    if filters.author:
        stmt = stmt.where(Work.author_doc.op("@@")(func.plainto_tsquery("simple", filters.author)))
    if filters.year_from is not None:
        stmt = stmt.where(Work.first_publish_year >= filters.year_from)  # NULL years drop out
    if filters.year_to is not None:
        stmt = stmt.where(Work.first_publish_year <= filters.year_to)
    return stmt
```

Replace `search_local` with:

```python
async def search_local(
    db: AsyncSession, query: str | None, limit: int = _DEFAULT_LIMIT, filters: SearchFilters | None = None
) -> list[Work]:
    """Rank the local catalog against a query, narrowed by filters.

    With a query: ``ts_rank_cd`` over the weighted document (title A, author B,
    subjects C), multiplied by popularity — a multiplier, so a famous but
    irrelevant book cannot outrank a relevant one; it bottoms out at 1.0. With
    filters alone: a browse, ordered by the summed score of the requested
    genres, then popularity.
    """
    filters = filters or SearchFilters()
    genre_ids = await _genre_ids(db, filters)
    stmt = select(Work).where(Work.kind == WorkKind.single, Work.merged_into_id.is_(None))
    if normalize(query or ""):
        tsquery = func.plainto_tsquery("english", query)
        score = func.ts_rank_cd(Work.search_doc, tsquery) * (1 + func.ln(1 + Work.readinglog_count))
        stmt = stmt.where(Work.search_doc.op("@@")(tsquery)).order_by(
            score.desc(), Work.ol_edition_count.desc(), Work.first_publish_year.asc().nulls_last())
    elif filters.active:
        genre_score = (select(func.coalesce(func.sum(ewg.c.score), 0))
                       .where(ewg.c.work_id == Work.id, ewg.c.genre_id.in_(genre_ids)).scalar_subquery()
                       if genre_ids else literal(0))
        stmt = stmt.order_by(genre_score.desc(), Work.readinglog_count.desc(), Work.title, Work.id)
    else:
        return []
    stmt = _narrow(stmt, filters, genre_ids).limit(limit)
    return list((await db.execute(stmt)).scalars().all())
```

Replace `search` with:

```python
async def search(
    db: AsyncSession, query: str | None, filters: SearchFilters | None = None, limit: int = _DEFAULT_LIMIT
) -> list[Work]:
    """Answer a search, filling the catalog from Open Library on a cold ``q``.

    Filters never reach upstream: a cold ``q`` ingests once, whatever filters
    accompany it, and a filter-only search is a local browse with no HTTP call.
    """
    filters = filters or SearchFilters()
    await _genre_ids(db, filters)  # a bad filter fails before any upstream call
    normalized = normalize(query or "")
    if not normalized and not filters.active:
        return []
    if normalized and not await _is_fresh(db, normalized):
        ol_works = await open_library.search_works(query, limit=limit)
        if ol_works:
            for ol in ol_works:
                await upsert_work_from_ol(db, ol)
            await _record(db, normalized, len(ol_works))
        else:
            await _ingest_from_google(db, query)
    return await search_local(db, query, limit=limit, filters=filters)
```

- [ ] **Step 4: The route**

In `api/works.py`, replace `search_works`:

```python
def _query_error(param: str, message: str) -> HTTPException:
    # FastAPI's own 422 shape, so api/errors.js shows `msg` and a client can read `loc`.
    return HTTPException(status_code=422, detail=[{"loc": ["query", param], "msg": message, "type": "value_error"}])


@router.get("/search", response_model=list[WorkOut])
async def search_works(
    q: str | None = Query(None, description="Text query. Optional when any filter is set."),
    genre: list[str] = Query([], description="Genre slug; repeat for several (all must match)."),
    author: str | None = Query(None, max_length=200),
    year_from: int | None = Query(None, ge=0, le=9999),
    year_to: int | None = Query(None, ge=0, le=9999),
    db: AsyncSession = Depends(get_db),
):
    """Answer from the local catalog, filling it from Open Library when ``q`` is cold.

    No upstream call happens on a query the database has already resolved, and
    none ever happens for filters: a filter-only search is a local browse.
    """
    filters = search.SearchFilters(
        genres=tuple(dict.fromkeys(g.strip() for g in genre if g.strip())),
        author=(author or "").strip() or None, year_from=year_from, year_to=year_to,
    )
    if not (q or "").strip() and not filters.active:
        raise _query_error("q", "Search needs a query or a filter.")
    try:
        works = await search.search(db, q, filters)
    except search.InvalidFilter as exc:
        raise _query_error(exc.param, str(exc)) from None
    return await _to_work_outs(db, works)
```

- [ ] **Step 5: Run the tests**

Run: `cd backend && pytest tests/test_search_filters.py tests/test_search.py tests/test_search_local.py tests/test_works.py -v && pytest -q`
Expected: PASS. If an existing test asserted that a missing `q` gives FastAPI's own `missing` error shape, update it to the new `loc: ["query", "q"]` detail.

- [ ] **Step 6: Commit**

```bash
git add -A backend
git commit -m "feat(search): filter by genre, author and year; filters alone browse locally"
```

---

### Task 13: Search page filter bar and genre badges on results

**Files:**
- Create: `frontend/src/components/SearchFilters.jsx`, `frontend/src/components/SearchFilters.test.jsx`
- Modify: `frontend/src/api/works.js`, `frontend/src/pages/Search.jsx`, `frontend/src/pages/Search.test.jsx`, `frontend/src/components/WorkCard.jsx`, `frontend/src/components/WorkCard.test.jsx`

**Interfaces:**
- Consumes: `GenrePicker`, `useGenreTree` (Task 7), the search params (Task 12), and `top_genres` (Task 6).
- Produces:
  - `useSearchWorks(query, filters = {})` with filters `{ genres: string[], author, yearFrom, yearTo }`. The one-argument form used by `components/librarian/pickers.jsx` still works.
  - `<SearchFilters genres author yearFrom yearTo onChange(patch) />`

- [ ] **Step 1: Write the failing tests**

`frontend/src/components/SearchFilters.test.jsx`:

```jsx
import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

vi.mock('../api/client', () => ({ default: { get: vi.fn(() => Promise.resolve({ data: [
  { slug: 'science-fiction', name: 'Science Fiction', children: [{ slug: 'space-opera', name: 'Space Opera' }] }] })) } }))

import SearchFilters from './SearchFilters'

function renderBar(props) {
  const onChange = vi.fn()
  render(
    <QueryClientProvider client={new QueryClient()}>
      <SearchFilters genres={[]} author="" yearFrom="" yearTo="" onChange={onChange} {...props} />
    </QueryClientProvider>,
  )
  return onChange
}

describe('SearchFilters', () => {
  it('removes a genre chip', async () => {
    const onChange = renderBar({ genres: ['space-opera'] })
    await userEvent.click(screen.getByRole('button', { name: 'remove genre space-opera' }))
    expect(onChange).toHaveBeenCalledWith({ genres: [] })
  })

  it('adds a genre through the curated picker', async () => {
    const onChange = renderBar()
    await userEvent.click(screen.getByRole('button', { name: 'add a genre filter' }))
    await userEvent.click(await screen.findByRole('option', { name: /space-opera/ }))
    expect(onChange).toHaveBeenCalledWith({ genres: ['space-opera'] })
  })

  it('applies author and years on Enter', async () => {
    const onChange = renderBar()
    await userEvent.type(screen.getByRole('textbox', { name: 'author' }), 'herbert')
    await userEvent.type(screen.getByRole('spinbutton', { name: 'from year' }), '1960{Enter}')
    expect(onChange).toHaveBeenLastCalledWith({ author: 'herbert', yearFrom: '1960', yearTo: '' })
  })
})
```

In `Search.test.jsx`, add the URL round trip:

```jsx
function LocationProbe() {
  const location = useLocation()
  return <output data-testid="search">{location.search}</output>
}
// render <Routes><Route path="/search" element={<><Search /><LocationProbe /></>} /></Routes>

  it('reads filters from the URL and writes changes back', async () => {
    renderAt('/search?q=dune&genre=space-opera&year_from=1960')
    await waitFor(() => expect(client.get).toHaveBeenCalledWith('/works/search', expect.objectContaining({
      params: { q: 'dune', genre: ['space-opera'], year_from: '1960' } })))
    await userEvent.click(screen.getByRole('button', { name: 'remove genre space-opera' }))
    expect(screen.getByTestId('search')).toHaveTextContent('?q=dune&year_from=1960')
  })

  it('browses with filters and no query', async () => {
    renderAt('/search?genre=space-opera')
    await waitFor(() => expect(client.get).toHaveBeenCalledWith('/works/search', expect.objectContaining({
      params: { genre: ['space-opera'] } })))
  })
```

Adapt `renderAt` to the file's existing render helper. Also:
- Change existing `toHaveBeenCalledWith('/works/search', { params: { q } })` assertions to `expect.objectContaining({ params: { q } })`.
- Make the client mock answer `'/genres/'` with `[]`.

In `WorkCard.test.jsx`:

```jsx
  it('names the top genres as text', () => {
    renderCard({ ...WORK, top_genres: [{ slug: 'space-opera', name: 'Space Opera' }, { slug: 'science-fiction', name: 'Science Fiction' }] })
    expect(screen.getByText('space-opera · science-fiction')).toHaveClass('text-path')
  })
```

Use the file's existing render helper and fixture names.

- [ ] **Step 2: Run to verify they fail**

Run: `cd frontend && npx vitest run src/components/SearchFilters.test.jsx src/pages/Search.test.jsx src/components/WorkCard.test.jsx`
Expected: FAIL.

- [ ] **Step 3: `api/works.js`**

```js
export function useSearchWorks(query, { genres = [], author = '', yearFrom = '', yearTo = '' } = {}) {
  const filtered = genres.length > 0 || !!author || !!yearFrom || !!yearTo
  const params = {
    ...(query ? { q: query } : {}),
    ...(genres.length ? { genre: genres } : {}),
    ...(author ? { author } : {}),
    ...(yearFrom ? { year_from: yearFrom } : {}),
    ...(yearTo ? { year_to: yearTo } : {}),
  }
  return useQuery({
    queryKey: ['works', 'search', params],
    // indexes: null → genre=a&genre=b, the repeated form FastAPI reads as a list.
    queryFn: () => client.get('/works/search', { params, paramsSerializer: { indexes: null } }).then((r) => r.data),
    enabled: query.length > 1 || filtered,
  })
}
```

- [ ] **Step 4: `components/SearchFilters.jsx`**

```jsx
import { useEffect, useState } from 'react'
import { useGenreTree } from '../api/genres'
import GenrePicker from './GenrePicker'

/**
 * `genre [space-opera ×] [+]   author [____]   year [____]–[____]`.
 * Controlled by the URL: the page owns the values and applies each patch.
 * Text fields apply on Enter or blur, so typing doesn't search per keystroke.
 */
function SearchFilters({ genres, author, yearFrom, yearTo, onChange }) {
  const { data: tree = [] } = useGenreTree()
  const [picking, setPicking] = useState(false)
  const [draft, setDraft] = useState({ author, yearFrom, yearTo })
  useEffect(() => setDraft({ author, yearFrom, yearTo }), [author, yearFrom, yearTo])

  const field = (key) => ({
    value: draft[key],
    onChange: (e) => setDraft((d) => ({ ...d, [key]: e.target.value })),
    onBlur: () => { if (draft[key].trim() !== { author, yearFrom, yearTo }[key]) onChange({ [key]: draft[key].trim() }) },
  })

  return (
    <form
      aria-label="Filter results"
      className="flex flex-wrap items-baseline gap-x-6 gap-y-2 text-xs"
      onSubmit={(e) => {
        e.preventDefault()
        onChange({ author: draft.author.trim(), yearFrom: draft.yearFrom.trim(), yearTo: draft.yearTo.trim() })
      }}
    >
      <div className="relative flex flex-wrap items-baseline gap-2">
        <span className="text-ink-dim">genre</span>
        {genres.map((slug) => (
          <span key={slug} className="flex items-baseline gap-1">
            <span className="text-path">{slug}</span>
            <button type="button" className="btn-ghost text-xs" aria-label={`remove genre ${slug}`}
                    onClick={() => onChange({ genres: genres.filter((g) => g !== slug) })}>
              <span aria-hidden="true">×</span>
            </button>
          </span>
        ))}
        <button type="button" className="btn-ghost text-xs" aria-label="add a genre filter" aria-expanded={picking}
                onClick={() => setPicking((v) => !v)}>[+]</button>
        {picking && (
          <div className="absolute z-10 top-full left-0 mt-1">
            <GenrePicker tree={tree} selected={new Set(genres)} label="filter by genre"
                         onToggle={(slug, on) => onChange({ genres: on ? [...genres, slug] : genres.filter((g) => g !== slug) })}
                         onClose={() => setPicking(false)} />
          </div>
        )}
      </div>
      <label className="flex items-baseline gap-2">
        <span className="text-ink-dim">author</span>
        <input type="text" aria-label="author" className="input w-[24ch]" {...field('author')} />
      </label>
      <span className="flex items-baseline gap-2">
        <span className="text-ink-dim">year</span>
        <input type="number" inputMode="numeric" aria-label="from year" className="input w-[8ch]" {...field('yearFrom')} />
        <span aria-hidden="true" className="text-ink-faint">–</span>
        <input type="number" inputMode="numeric" aria-label="to year" className="input w-[8ch]" {...field('yearTo')} />
      </span>
      <button type="submit" className="sr-only">apply filters</button>
    </form>
  )
}

export default SearchFilters
```

- [ ] **Step 5: `pages/Search.jsx`**

```jsx
import SearchFilters from '../components/SearchFilters'
// …
  const [searchParams, setSearchParams] = useSearchParams()
  const q = searchParams.get('q') || ''
  const filters = {
    genres: searchParams.getAll('genre'),
    author: searchParams.get('author') || '',
    yearFrom: searchParams.get('year_from') || '',
    yearTo: searchParams.get('year_to') || '',
  }
  const filtered = filters.genres.length > 0 || !!filters.author || !!filters.yearFrom || !!filters.yearTo
  const { data: works, isLoading, isError } = useSearchWorks(q, filters)

  // Filter state lives in the URL, so results are shareable and survive back/forward.
  const applyFilters = (patch) => setSearchParams((prev) => {
    const next = new URLSearchParams(prev)
    if ('genres' in patch) {
      next.delete('genre')
      patch.genres.forEach((g) => next.append('genre', g))
    }
    for (const [key, param] of [['author', 'author'], ['yearFrom', 'year_from'], ['yearTo', 'year_to']]) {
      if (key in patch) (patch[key] ? next.set(param, patch[key]) : next.delete(param))
    }
    return next
  })
```

Render `<SearchFilters {...filters} onChange={applyFilters} />` directly under the header block. Then update the messages:
- `!q && !filtered` → "Enter a search term to find books."
- `q.length === 1 && !filtered` → the two-character hint
- the loading skeleton shows when `isLoading && (q.length > 1 || filtered)`
- empty: `q ? <>No books found for &quot;{q}&quot;.</> : 'No books match these filters.'`

Change the status bar path to `` `~/search${searchParams.toString() ? `?${searchParams}` : ''}` ``, and give the `h1` the filtered case: `search {q && …}{!q && filtered && <span className="text-ink-dim">filtered</span>}`.

- [ ] **Step 6: `WorkCard.jsx`**

After the series line, add:

```jsx
        {/* Plain text, not links: the whole card is already one. */}
        {work.top_genres?.length > 0 && (
          <p className="text-xs lowercase line-clamp-1">
            <span className="text-ink-dim">genres </span>
            <span className="text-path">{work.top_genres.map((g) => g.slug).join(' · ')}</span>
          </p>
        )}
```

The test asserts on the inner `text-path` span, so `getByText('space-opera · science-fiction')` must find that span.

- [ ] **Step 7: Run the tests and check the page**

Run: `cd frontend && npm test && npm run build`
Expected: PASS, then a clean build.

Open `/search?genre=space-opera`, add an author, remove the genre, and use back/forward. Each step should restore the filters.

- [ ] **Step 8: Commit**

```bash
git add -A frontend
git commit -m "feat(web): search filter bar with URL state; genre badges on results"
```

---

### Task 14: End-to-end test, docs, full verification

**Files:**
- Create: `frontend/e2e/genres.spec.js`
- Modify: `CLAUDE.md`, `ROADMAP.md`, `docs/visual-identity.md`, `docs/superpowers/specs/2026-09-29-genre-voting-design.md` (status line only)

- [ ] **Step 1: Write the e2e spec**

```js
import { test, expect } from '@playwright/test'
import { registerViaUi } from './helpers'

// A reader tags Red Rising as space opera and finds it by that genre, on the
// genre page and through the search filter. Uses live Open Library for the
// first search; needs the full stack with the taxonomy synced (compose runs
// `scripts.sync_genres` on start).
test('a reader tags a book and finds it by that genre', async ({ page }) => {
  await registerViaUi(page)
  await page.goto('/search?q=red%20rising')
  await page.locator('a[href^="/series/red-rising"]').first().click()

  const books = page.getByRole('list', { name: 'Books in this series' })
  const row = books.getByRole('listitem').filter({ has: page.getByRole('heading', { name: 'Red Rising', exact: true }) })
  await expect(row).toBeVisible({ timeout: 30_000 })

  await row.getByRole('button', { name: 'tag genres of Red Rising' }).click()
  await page.getByRole('combobox', { name: 'filter genres' }).fill('space opera')
  await page.getByRole('option', { name: 'space-opera' }).click()
  await page.getByRole('button', { name: '[done]' }).click()
  await expect(row.getByRole('link', { name: 'space-opera' })).toBeVisible()
  await expect(row.getByText('you tagged this')).toBeAttached()

  await page.goto('/genres/space-opera')
  await expect(page.getByText('Red Rising', { exact: true }).first()).toBeVisible()

  await page.goto('/search?genre=space-opera')
  await expect(page.locator('a[href^="/series/red-rising"]').first()).toBeVisible()
})
```

- [ ] **Step 2: Run it**

Run: `docker compose up --build` in one terminal, then `cd frontend && npm run test:e2e -- genres.spec.js`
Expected: PASS. If it fails on a live-data assumption (for example the series slug), read the page in the Playwright trace and fix the locator, not the product.

- [ ] **Step 3: Update the docs**

**`CLAUDE.md`**
- In the `services/` bullet, add:
  - `genre_inference.py` is the pure taxonomy loader and subject → genre rules (`infer_genres`: `genre:` tags first, word-boundary, `exclude`, no fallback).
  - `genre_taxonomy.py` syncs `app/data/genres.yaml`.
  - `genres.py` is the only writer of `genre_votes`, `genre_inferences` and `work_genres`: `recompute` after every vote, inference, veto, revert and merge; the 5-per-reader cap under `FOR UPDATE`; `absorb` for `merge_works`.
  - `librarian/genres.py` holds `veto_genre` and `repoint_vetoes`.
- Add a **Genres** paragraph after "Series":
  - The taxonomy is `backend/app/data/genres.yaml` (two levels, permanent slugs), synced by `python -m scripts.sync_genres`, which compose runs after migrations.
  - A work's effective genres are the `effective_work_genres` view: readers' when any reader voted a live unvetoed genre, else the inferred ones. Its SQL is one constant, `EFFECTIVE_WORK_GENRES_VIEW`, executed by the migration and by a `create_all` listener.
  - Never re-derive the rule; read the view.
  - Vetoes are `veto_genre` corrections, runtime-only, undone per `(work, genre)`.
  - `works.genre_id` is gone. Rooms (`threads.genre_id`) are parent genres only.
  - After a `match` change, run `python -m scripts.rebuild_work_genres --reinfer`.
- In **Search is local-first**, add: filters (`genre`, `author`, `year_from`, `year_to`) only narrow the local query; a filter-only search is a browse with no upstream call; `author_doc` is declared twice like `search_doc`.
- In **Known remaining gaps**, change the librarian list to include genre vetoes. Note that the taxonomy has no in-app editor (the YAML is the editor).

**`ROADMAP.md`**
- Mark Phase 3 "Search filters — book search by genre/author/year" done.
- Mark Phase 5 "Genre CRUD" as partly done: taxonomy via YAML, in-app editing open.

**`docs/visual-identity.md`**
- Add `●` (own genre vote) and `×` (remove a filter) to the closed literal-glyph set. Both are `aria-hidden` with sr-only or `aria-label` text.

**The spec**
- Change `**Status:**` to `implemented (plan: docs/superpowers/plans/2026-09-29-genre-voting.md)`.

- [ ] **Step 4: Run the full verification**

Run:
```bash
cd backend && DATABASE_URL=postgresql+asyncpg://margin:margin@localhost:5432/margin_test pytest -q
cd ../frontend && npm test && npm run build
cd ../pipeline && .venv/bin/python -m pytest -q   # pure-import guard + unchanged contract
```
Expected: all green. Report any failure verbatim rather than calling the work done.

- [ ] **Step 5: Commit**

```bash
git add -A frontend/e2e CLAUDE.md ROADMAP.md docs
git commit -m "docs(genres): e2e for tagging and filtering; record the genre model"
```

---

## Self-review notes (for the executor)

| Spec section | Implemented by |
|---|---|
| §4.1 | Tasks 2, 3 |
| §4.2–4.5 | Tasks 2, 4 |
| §4.6 | Task 2 (view) and Task 4 (rule tests) |
| §4.7 | Task 5 |
| §4.8 | Task 2 |
| §5 | Tasks 1, 3 |
| §6 | Tasks 1, 5 |
| §7.1 | Task 6 |
| §7.2 | Task 10 |
| §7.3 | Tasks 5, 10 (preview count) |
| §8.1–8.2 | Task 8 |
| §8.3 | Task 6 |
| §8.4 | Task 10 |
| §8.5, §10 | Task 12 |
| §9.1 | Task 7 |
| §9.2 | Task 11 |
| §9.3–9.4 | Task 9 |
| §9.5 | Task 13 |
| §9.6 | Tasks 7, 9, 11 |
| §11 | Error table: Tasks 6, 8, 10, 12 |
| §12 | Test list: each task's Step 1 |
| §13 | Rollout order: task order |

- Task 7 ships before Task 8, so `useGenreTree` accepts the old flat `/genres/` list. Don't remove that shim until Task 8 is merged.
- Stop and ask if you are tempted to:
  - write `work_genres` anywhere but `services/genres.py`
  - write `catalog_corrections` anywhere but `services/librarian/`
  - add a second copy of the effective-genre SQL

  All three are the drift this design exists to prevent.
