# Catalog Pipeline — Implementation Plan (1 of 2: build a release)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A new offline `pipeline/` package that turns Open Library dumps and Wikidata into a versioned, byte-reproducible catalog release (`releases/catalog-YYYY.MM.N/`: five Parquet files, a manifest and a quality report), gated on a golden set of series.

**Architecture:** Five stages — `fetch → select → extract → group → publish` — each reading the previous stage's DuckDB tables in `build/catalog.duckdb` and writing `tmp_*` tables it swaps in only on success. Every grouping decision (author clusters, duplicate works, the four-rung series ladder and its guards, nesting, overrides) is a pure function in `pipeline/group/`, tested as tables; the stage modules are thin DuckDB wrappers. The pipeline reuses the backend's pure identity rules through `pipeline/_backend.py` and never touches the app database.

**Tech Stack:** Python 3.12+, DuckDB 1.1.3, pyarrow 18.1.0, httpx 0.27.0, PyYAML 6.0.2; pytest 8.2.2 + respx 0.21.1.

**Spec:** `docs/superpowers/specs/2026-09-26-catalog-pipeline-design.md` — §1–§5, §7, §8, §9 (pipeline side). **Plan 2** (`docs/superpowers/plans/2026-09-26-catalog-loading.md`) covers §6 (schema, loader, API, series page). The two plans meet only at the release contract, `pipeline/contract.py`; plan 2 pins it with a test, so either plan can run first.

Every code block below was run before this plan was written: the pipeline suite (153 tests) passes on Python 3.13 with the pinned versions, and a release built from the fixture world loads through plan 2's loader and serves *Red Rising* and *A Song of Ice and Fire* in the right order.

## Global Constraints

- The pipeline **never connects to the app database** and imports only `app.services.work_identity`, `app.services.series_identity` and `app.services.text` from the backend, via `pipeline/_backend.py`.
- **No test touches the network.** Dumps and Wikidata are served by respx from `pipeline/tests/fixtures/`.
- Every row id is `uuid5(MARGIN_NS, <identity string>)` with `MARGIN_NS = 7c1d0a4e-3b5f-4e2a-9d6c-8f4b2a1e0c37`. Never change it.
- Identity strings: `work:ol:<OL…W>`, `edition:ol:<OL…M>`, `series:wd:<Q…>`, `series:ol:<series_key(name)>`, `series:single:<OL…W>`.
- Output is sorted by identity; the same inputs produce **byte-identical Parquet**.
- A stage writes only `tmp_<name>` tables and calls `db.swap_in` at its end.
- Rules are data: `pipeline/rules/junk.yaml`, `pipeline/rules/imprints.yaml`, `pipeline/overrides/*.yaml`, `pipeline/golden/series.yaml`.
- An invalid override **fails the run**; it is never skipped.
- `publish` fails below **95%** exact golden membership or **95%** exact golden order, and never overwrites an existing release folder.
- Imprint threshold: a rung 2–4 series spanning **more than 3** author clusters is rejected. Junk: all English editions under **40** pages.
- Parent series become rooms only with **≥2 direct works or ≥2 child series**. Folding threshold: **≥50%**.
- English only: an edition is English when its `languages` include `/languages/eng`.
- The build machine has ~20 GB free: the editions dump is streamed and filtered, never written to disk.
- `python -m pipeline run` is run from the **repository root**; tests are run from `pipeline/`.

## Review Focus

1. **Real books whose titles look like junk** — *The Diary of a Young Girl*, *Diary of a Wimpy Kid*, *A Dissertation upon Roast Pig*, *The Colour of Magic* must survive `select`. → Task 5 `test_real_books_are_kept`.
2. **Same author, same work title, different books** — Open Library titles three Brian Herbert books plain "Dune"; merging them would erase two books and their discussions. → Task 12 `test_editions_with_no_shared_title_are_different_books`.
3. **A download or the editions stream dying part-way** (the dumps are multi-GB) — a partial file must resume, a truncated gzip must never be loaded as if complete. → Task 6 `test_resumes_a_partial_download_with_a_range_request`, `test_a_corrupt_file_is_deleted_and_fails_the_stage`; Task 7 `test_a_truncated_stream_restarts_from_the_beginning`.
4. **A common author name** ("John Smith") on many unrelated OL records — unioning them would make the adaptation filter and duplicate merge compare strangers. → Task 11 `test_a_common_name_joins_nobody`.
5. **An override that no longer matches the build** (work merged away, series renamed upstream) — must fail loudly with its file and index, not silently do nothing. → Task 16 `test_malformed_entries_fail_with_their_location`, `test_series_overrides_reject_unknown_series`.

## Decisions this plan makes where the spec is silent

Flagged so a reviewer can overrule them; each is small and local.

- **OL→OL folding.** The spec folds rung 2–4 series into Wikidata. The same ≥50% rule also folds a lower-rung OL series into a *stronger* OL series (edition string "Red Rising Saga ; 5" into the `franchise:Red Rising` tag its siblings carry); without it one saga splits into two rooms.
- **Duplicate guard.** Besides distinct Wikidata items, two works whose English editions share no cleaned title are different books.
- **A lone title pattern is not a series**: a rung-4 series with one member dissolves to a singleton.
- **Name-based author unions** need a distinctive name (≥2 words or non-Latin) carried by at most 3 records.
- **Adaptations** dropped by the filter become singletons (they do not fall to a lower rung).
- **Overrides:** `reject_series` acts at the imprint step so members fall to their next rung; `set_series` may create an `ol:` series when given a `name`; a split-off work's id is `<work>~<first edition>`.
- **Representative edition** is chosen by the pipeline (curated cover, any cover, ISBN, pages, lowest id).
- **OL redirects** are followed everywhere, and a redirected id that someone read becomes a `work_aliases` row.
- **Wikidata endpoint** is configurable (`WIKIDATA_SPARQL_URL`); QLever serves the same SPARQL without the public service's 60-second limit.
- **The editions stream restarts from zero** on failure (a gzip stream cannot resume mid-member); the other dumps resume with HTTP Range.

## File Structure

```
pipeline/
  requirements.txt  pytest.ini  __init__.py  __main__.py
  _backend.py       the backend's pure rules, importable without app settings
  config.py         paths, source URLs, MARGIN_NS, BuildContext
  contract.py       the release Parquet schemas + SCHEMA_VERSION (pyarrow only)
  db.py             DuckDB connect, tmp_/swap discipline, write_table, iter_rows
  runner.py         runs a contiguous range of stages
  ids.py            uuid5 ids, deterministic slugs
  select_rules.py   junk rules loader/matcher
  overrides.py      override parsing, validation, application
  golden.py         golden set: load, evaluate, gate, draft
  release.py        build the five release tables
  report.py         report.md
  parse/series_strings.py   edition series strings, title patterns
  sources/  records.py http.py ol_dumps.py editions.py wikidata.py load_raw.py ol_records.py
  group/    types.py authors.py duplicates.py ladder.py guards.py decide.py nesting.py
  stages/   fetch.py select.py extract.py group.py publish.py
  rules/    junk.yaml imprints.yaml
  overrides/README.md
  golden/   series.yaml README.md
  tests/    __init__.py conftest.py fixtures/{__init__,dumps,world}.py test_*.py
backend/app/services/text.py            normalize(), moved out of google_books
backend/tests/test_pure_imports.py
```
Modified: `backend/app/services/google_books.py`, `backend/app/services/work_identity.py`, `.gitignore`, `.github/workflows/ci.yml`, `CLAUDE.md`.

Set up the pipeline's virtualenv once (Task 2 creates `requirements.txt`):

```bash
cd pipeline && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
```

---

### Task 1: Make the identity rules importable without the app

**Files:**
- Create: `backend/app/services/text.py`
- Modify: `backend/app/services/google_books.py` (move `normalize` out, re-export it)
- Modify: `backend/app/services/work_identity.py:14` (import `normalize` from `text`)
- Test: `backend/tests/test_pure_imports.py`

**Interfaces:**
- Produces: `app.services.text.normalize(text: str | None) -> str` — identical behaviour to today's `google_books.normalize`, which stays importable from `google_books` (re-export) so `search.py`, `open_library.py` and `SearchQuery` are untouched.
- Produces: the guarantee that `import app.services.work_identity, app.services.series_identity, app.services.text` loads neither `app.config`, `httpx` nor `sqlalchemy`.

Today `work_identity` imports `normalize` from `google_books`, which imports `httpx` and `app.config` — and `Settings()` raises without `DATABASE_URL` and `SECRET_KEY`. The pipeline must import these rules with no app configured.

- [ ] **Step 1: Write the failing test**

`backend/tests/test_pure_imports.py`:

```python
"""The identity rules must import without the app: the catalog pipeline runs offline."""

import os
import subprocess
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]


def test_identity_rules_import_without_settings_or_http():
    env = {k: v for k, v in os.environ.items() if k not in ("DATABASE_URL", "SECRET_KEY")}
    code = (
        "import sys\n"
        "import app.services.work_identity, app.services.series_identity, app.services.text\n"
        "leaked = {'app.config', 'httpx', 'sqlalchemy'} & set(sys.modules)\n"
        "assert not leaked, leaked\n"
    )
    result = subprocess.run([sys.executable, "-c", code], cwd=BACKEND, env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd backend && DATABASE_URL=postgresql+asyncpg://margin:margin@localhost:5432/margin_test python -m pytest tests/test_pure_imports.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.text'`.

- [ ] **Step 3: Create `text.py`**

The function body is moved verbatim from `google_books.py`.

`backend/app/services/text.py`:

```python
"""String canonicalization shared by every matching rule. Pure: stdlib only.

It lives apart from ``google_books`` so the identity rules can be imported
without the app's settings: the offline catalog pipeline imports them with no
database or secrets configured.
"""

from __future__ import annotations

import re
import unicodedata


def normalize(text: str | None) -> str:
    """Canonicalize a string for duplicate matching.

    NFKD-strip accents, lowercase, drop punctuation, collapse whitespace.
    """
    if not text:
        return ""
    decomposed = unicodedata.normalize("NFKD", text)
    no_accents = "".join(c for c in decomposed if not unicodedata.combining(c))
    lowered = no_accents.lower()
    no_punct = re.sub(r"[^\w\s]", " ", lowered)
    return re.sub(r"\s+", " ", no_punct).strip()
```

- [ ] **Step 4: Point `google_books` and `work_identity` at it**

Apply with `git apply` (save the block to a file first), or make the same edits by hand.

```diff
--- a/backend/app/services/google_books.py
+++ b/backend/app/services/google_books.py
@@ -8,6 +8,8 @@
 import httpx
 
 from app.config import settings
+# Re-exported: search, open_library and SearchQuery import it from here.
+from app.services.text import normalize  # noqa: F401
 
 # Maps a substring (checked against the lowercased category string) to a seeded
 # Genre slug. Order matters — more specific terms first; generic "fiction" last.
@@ -25,20 +27,6 @@
     ("literary", "literary-fiction"),
     ("fiction", "literary-fiction"),  # generic fiction fallback (last)
 ]
-
-
-def normalize(text: str | None) -> str:
-    """Canonicalize a string for duplicate matching.
-
-    NFKD-strip accents, lowercase, drop punctuation, collapse whitespace.
-    """
-    if not text:
-        return ""
-    decomposed = unicodedata.normalize("NFKD", text)
-    no_accents = "".join(c for c in decomposed if not unicodedata.combining(c))
-    lowered = no_accents.lower()
-    no_punct = re.sub(r"[^\w\s]", " ", lowered)
-    return re.sub(r"\s+", " ", no_punct).strip()
 
 
 def _category_to_slug(categories: list[str] | None) -> str | None:
```

```diff
--- a/backend/app/services/work_identity.py
+++ b/backend/app/services/work_identity.py
@@ -11,7 +11,7 @@
 import hashlib
 import re
 
-from app.services.google_books import normalize
+from app.services.text import normalize
 
 # A parenthetical or bracketed group is always edition packaging:
 # "(Deluxe Slipcase Edition)", "[Hardcover]".
```

- [ ] **Step 5: Run the test and the whole backend suite**

Run: `cd backend && DATABASE_URL=postgresql+asyncpg://margin:margin@localhost:5432/margin_test python -m pytest -q`
Expected: all pass (337 before this plan, 338 with this test).

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/text.py backend/app/services/google_books.py backend/app/services/work_identity.py backend/tests/test_pure_imports.py
git commit -m "refactor: move normalize into a pure text module so identity rules import without settings"
```

---

### Task 2: Pipeline scaffold: package, build context, stage runner

**Files:**
- Create: `pipeline/requirements.txt`, `pipeline/pytest.ini`, `pipeline/__init__.py`, `pipeline/_backend.py`, `pipeline/contract.py`, `pipeline/config.py`, `pipeline/db.py`, `pipeline/runner.py`, `pipeline/__main__.py`
- Create: `pipeline/tests/__init__.py`, `pipeline/parse/__init__.py`, `pipeline/group/__init__.py`, `pipeline/sources/__init__.py`, `pipeline/stages/__init__.py` (all empty)
- Modify: `.gitignore`
- Test: `pipeline/tests/test_backend_rules.py`, `pipeline/tests/test_runner.py`

**Interfaces:**
- Consumes: Task 1's pure imports.
- Produces (`pipeline.config`): `REPO: Path`, `PIPELINE_DIR: Path`, `MARGIN_NS: uuid.UUID`, `STAGES = ("fetch", "select", "extract", "group", "publish")`, `OL_DUMPS: dict[str, str]` (keys `ratings`, `reading_log`, `works`, `authors`, `editions`), `WIKIDATA_SPARQL_URL`, `USER_AGENT`, and
  `BuildContext(build_dir, con, ol_dumps, sparql_url, rules_dir, overrides_dir, golden_path, releases_dir, version=None, upload=False, sleep=time.sleep)` with property `raw_dir`.
- Produces (`pipeline.contract`): `SCHEMA_VERSION = 1`, `SCHEMAS: dict[str, pa.Schema]` for `works`, `editions`, `series`, `series_members`, `work_aliases`.
- Produces (`pipeline.db`): `TMP_PREFIX = "tmp_"`, `connect(build_dir) -> DuckDBPyConnection`, `sql_path(path) -> str`, `table_names(con) -> set[str]`, `drop_temp_tables(con)`, `write_table(con, name, table: pa.Table)` (creates `tmp_<name>`), `swap_in(con, names)`, `iter_rows(con, sql, params=None, batch=10_000)`.
- Produces (`pipeline.runner`): `load_stage(name) -> module` (each stage module exposes `run(ctx: BuildContext) -> None`), `stage_range(start, stop) -> tuple[str, ...]`, `run(ctx, start="fetch", stop="publish")`.
- Produces (`pipeline._backend`): re-exports `SUBJECT_SEPARATOR, canonical_key, choose_container, classify_kind, clean_title, display_title, join_subjects, normalize, normalize_isbn, parse_tags, series_key, slugify, tag_name`.

`contract.py` is pyarrow-only on purpose: plan 2's backend test imports it to prove the loader reads exactly what `publish` writes. Stages are loaded by name (`importlib`), so the runner works before any stage exists.

- [ ] **Step 1: Write the failing tests**

`pipeline/tests/test_backend_rules.py`:

```python
import subprocess
import sys

from pipeline.config import REPO


def test_backend_rules_import_without_app_settings():
    code = (
        "import sys\n"
        "import pipeline._backend\n"
        "assert 'app.config' not in sys.modules, 'rules pulled in app settings'\n"
        "assert 'sqlalchemy' not in sys.modules\n"
    )
    env = {"PATH": "/usr/bin:/bin"}
    result = subprocess.run([sys.executable, "-c", code], cwd=REPO, env=env,
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_backend_rules_are_the_apps():
    from pipeline._backend import canonical_key, display_title

    assert display_title("The Hobbit (Deluxe Edition)") == "The Hobbit"
    assert canonical_key("Red Rising 01", "Pierce Brown") == "red rising\x1fpierce brown"
```

`pipeline/tests/test_runner.py`:

```python
import types

import duckdb
import pytest

from pipeline import runner
from pipeline.config import BuildContext
from pipeline.db import swap_in, table_names


@pytest.fixture
def ctx(tmp_path):
    return BuildContext(build_dir=tmp_path, con=duckdb.connect())


def _fake_stages(monkeypatch, calls, fail=None):
    def load(name):
        def run(ctx):
            calls.append(name)
            if name == fail:
                raise RuntimeError(f"{name} failed")
        return types.SimpleNamespace(run=run)
    monkeypatch.setattr(runner, "load_stage", load)


def test_runs_every_stage_in_order(ctx, monkeypatch):
    calls = []
    _fake_stages(monkeypatch, calls)
    runner.run(ctx)
    assert calls == ["fetch", "select", "extract", "group", "publish"]


def test_resumes_from_a_stage(ctx, monkeypatch):
    calls = []
    _fake_stages(monkeypatch, calls)
    runner.run(ctx, start="group")
    assert calls == ["group", "publish"]


def test_rejects_a_backwards_range():
    with pytest.raises(ValueError):
        runner.stage_range("group", "select")


def test_a_failed_stage_leaves_the_previous_tables(ctx):
    ctx.con.execute("CREATE TABLE works AS SELECT 1 AS v")
    ctx.con.execute("CREATE TABLE tmp_works AS SELECT 2 AS v")
    ctx.con.execute("CREATE TABLE tmp_editions AS SELECT 3 AS v")
    # tmp_series does not exist, so the swap fails part-way and must roll back.
    with pytest.raises(Exception):
        swap_in(ctx.con, ["works", "series"])
    assert ctx.con.execute("SELECT v FROM works").fetchone() == (1,)


def test_a_new_run_drops_a_crashed_stages_temp_tables(ctx, monkeypatch):
    ctx.con.execute("CREATE TABLE tmp_half_written AS SELECT 1 AS v")
    _fake_stages(monkeypatch, [])
    runner.run(ctx, start="publish")
    assert "tmp_half_written" not in table_names(ctx.con)


def test_swap_replaces_tables(ctx):
    ctx.con.execute("CREATE TABLE works AS SELECT 1 AS v")
    ctx.con.execute("CREATE TABLE tmp_works AS SELECT 2 AS v")
    swap_in(ctx.con, ["works"])
    assert ctx.con.execute("SELECT v FROM works").fetchone() == (2,)
    assert "tmp_works" not in table_names(ctx.con)
```

- [ ] **Step 2: Add the requirements and test config, then create the virtualenv**

`pythonpath = ..` puts the repository root on `sys.path`, so tests import `pipeline.*`. Then run `cd pipeline && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt`.

`pipeline/requirements.txt`:

```text
duckdb==1.1.3
pyarrow==18.1.0
httpx==0.27.0
PyYAML==6.0.2

# --- testing ---
pytest==8.2.2
respx==0.21.1
```

`pipeline/pytest.ini`:

```ini
[pytest]
testpaths = tests
pythonpath = ..
```

- [ ] **Step 3: Run to verify they fail**

Run: `cd pipeline && .venv/bin/python -m pytest -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'pipeline._backend'` (and `pipeline.runner`).

- [ ] **Step 4: Write the package modules**

Also create the empty `__init__.py` files listed above.

`pipeline/__init__.py`:

```python
"""MARGIN catalog pipeline: Open Library dumps + Wikidata -> a versioned release.

Runs offline, never touches the app database. See
docs/superpowers/specs/2026-09-26-catalog-pipeline-design.md.
"""
```

`pipeline/_backend.py`:

```python
"""The backend's pure identity rules, importable without the app.

The pipeline must group works exactly as the app does, so it reuses the rule
modules rather than copying them. Only modules with no I/O and no settings are
re-exported here; importing anything else from ``app`` would drag in the
database configuration.
"""

from __future__ import annotations

import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[1] / "backend"
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from app.services.series_identity import (  # noqa: E402
    SUBJECT_SEPARATOR,
    choose_container,
    join_subjects,
    parse_tags,
    series_key,
    slugify,
    tag_name,
)
from app.services.text import normalize  # noqa: E402
from app.services.work_identity import (  # noqa: E402
    canonical_key,
    classify_kind,
    clean_title,
    display_title,
    normalize_isbn,
)

__all__ = [
    "SUBJECT_SEPARATOR",
    "canonical_key",
    "choose_container",
    "classify_kind",
    "clean_title",
    "display_title",
    "join_subjects",
    "normalize",
    "normalize_isbn",
    "parse_tags",
    "series_key",
    "slugify",
    "tag_name",
]
```

`pipeline/contract.py`:

```python
"""The release contract: the Parquet schemas production loads (spec §4.5).

The other half is ``COLUMNS`` in ``backend/app/services/catalog_loader.py``;
``backend/tests/test_catalog_contract.py`` fails if the two drift. Changing a
column means bumping ``SCHEMA_VERSION`` and teaching the
loader the new version. Deliberately pyarrow-only, so the backend's test can
import it without the pipeline's other dependencies.
"""

from __future__ import annotations

import pyarrow as pa

SCHEMA_VERSION = 1

_S, _I32, _I64, _F64 = pa.string(), pa.int32(), pa.int64(), pa.float64()
SCHEMAS = {
    "works": pa.schema([
        ("id", _S), ("ol_work_id", _S), ("canonical_key", _S), ("title", _S), ("subtitle", _S),
        ("author", _S), ("first_publish_year", _I32), ("kind", _S), ("series_id", _S),
        ("ol_cover_id", _I64), ("ol_edition_count", _I32), ("readinglog_count", _I32),
        ("ratings_count", _I32), ("subjects", _S), ("representative_edition_id", _S),
    ]),
    "editions": pa.schema([
        ("id", _S), ("ol_edition_id", _S), ("work_id", _S), ("title", _S), ("subtitle", _S),
        ("author", _S), ("publisher", _S), ("published_year", _I32), ("isbn_13", _S),
        ("page_count", _I32), ("cover_url", _S), ("language", _S),
    ]),
    "series": pa.schema([
        ("id", _S), ("key", _S), ("source", _S), ("provenance", _S), ("name", _S), ("slug", _S),
        ("canonical_key", _S), ("kind", _S), ("parent_series_id", _S),
    ]),
    "series_members": pa.schema([
        ("series_id", _S), ("work_id", _S), ("position", _F64), ("provenance", _S), ("confidence", _S),
    ]),
    "work_aliases": pa.schema([("ol_work_id", _S), ("work_id", _S)]),
}
```

`pipeline/config.py`:

```python
"""Paths, source URLs and the build context every stage receives."""

from __future__ import annotations

import os
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import duckdb

from pipeline.contract import SCHEMA_VERSION  # noqa: F401  (re-exported for stages)

REPO = Path(__file__).resolve().parents[1]
PIPELINE_DIR = REPO / "pipeline"

# Never change: every release id is derived from it, so a new namespace would
# give every book a new UUID and orphan every thread and shelf.
MARGIN_NS = uuid.UUID("7c1d0a4e-3b5f-4e2a-9d6c-8f4b2a1e0c37")
STAGES = ("fetch", "select", "extract", "group", "publish")

_OL_DATA = "https://openlibrary.org/data"
OL_DUMPS = {
    "ratings": f"{_OL_DATA}/ol_dump_ratings_latest.txt.gz",
    "reading_log": f"{_OL_DATA}/ol_dump_reading-log_latest.txt.gz",
    "works": f"{_OL_DATA}/ol_dump_works_latest.txt.gz",
    "authors": f"{_OL_DATA}/ol_dump_authors_latest.txt.gz",
    "editions": f"{_OL_DATA}/ol_dump_editions_latest.txt.gz",
}
WIKIDATA_SPARQL_URL = os.environ.get("WIKIDATA_SPARQL_URL", "https://query.wikidata.org/sparql")
USER_AGENT = "MARGIN-catalog-pipeline/1.0 (https://github.com/devkevintoledo-tech/margin)"


@dataclass
class BuildContext:
    build_dir: Path
    con: duckdb.DuckDBPyConnection
    ol_dumps: dict[str, str] = field(default_factory=lambda: dict(OL_DUMPS))
    sparql_url: str = WIKIDATA_SPARQL_URL
    rules_dir: Path = PIPELINE_DIR / "rules"
    overrides_dir: Path = PIPELINE_DIR / "overrides"
    golden_path: Path = PIPELINE_DIR / "golden" / "series.yaml"
    releases_dir: Path = REPO / "releases"
    version: str | None = None
    upload: bool = False
    sleep: Callable[[float], None] = time.sleep

    @property
    def raw_dir(self) -> Path:
        return self.build_dir / "raw"
```

`pipeline/db.py`:

```python
"""DuckDB helpers: the build database and the stage-swap discipline.

A stage writes only ``tmp_<name>`` tables and calls :func:`swap_in` once it
has finished, so a crash leaves the previous stage's tables untouched.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

import duckdb
import pyarrow as pa

TMP_PREFIX = "tmp_"


def connect(build_dir: Path) -> duckdb.DuckDBPyConnection:
    build_dir.mkdir(parents=True, exist_ok=True)
    return duckdb.connect(str(build_dir / "catalog.duckdb"))


def sql_path(path: Path) -> str:
    """A filesystem path as a quoted SQL string literal."""
    return "'" + str(path).replace("'", "''") + "'"


def table_names(con: duckdb.DuckDBPyConnection) -> set[str]:
    return {row[0] for row in con.execute("SELECT table_name FROM information_schema.tables").fetchall()}


def drop_temp_tables(con: duckdb.DuckDBPyConnection) -> None:
    """Remove what a crashed stage left behind."""
    for name in sorted(table_names(con)):
        if name.startswith(TMP_PREFIX):
            con.execute(f'DROP TABLE "{name}"')


def write_table(con: duckdb.DuckDBPyConnection, name: str, table: pa.Table) -> None:
    """Materialize an Arrow table as ``tmp_<name>``."""
    con.register("_incoming", table)
    try:
        con.execute(f'CREATE OR REPLACE TABLE "{TMP_PREFIX}{name}" AS SELECT * FROM _incoming')
    finally:
        con.unregister("_incoming")


def swap_in(con: duckdb.DuckDBPyConnection, names: Iterable[str]) -> None:
    """Replace each table with its ``tmp_`` twin, all or nothing."""
    con.execute("BEGIN TRANSACTION")
    try:
        for name in names:
            con.execute(f'DROP TABLE IF EXISTS "{name}"')
            con.execute(f'ALTER TABLE "{TMP_PREFIX}{name}" RENAME TO "{name}"')
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise


def iter_rows(con: duckdb.DuckDBPyConnection, sql: str, params=None, batch: int = 10_000):
    """Stream a query's rows without materializing the whole result in Python."""
    cursor = con.execute(sql, params or [])
    while rows := cursor.fetchmany(batch):
        yield from rows
```

`pipeline/runner.py`:

```python
"""Runs a contiguous range of stages, in order."""

from __future__ import annotations

import importlib
import logging
from types import ModuleType

from pipeline.config import STAGES, BuildContext
from pipeline.db import drop_temp_tables

log = logging.getLogger("pipeline")


def load_stage(name: str) -> ModuleType:
    return importlib.import_module(f"pipeline.stages.{name}")


def stage_range(start: str = STAGES[0], stop: str = STAGES[-1]) -> tuple[str, ...]:
    if start not in STAGES or stop not in STAGES:
        raise ValueError(f"stages are {', '.join(STAGES)}")
    first, last = STAGES.index(start), STAGES.index(stop)
    if first > last:
        raise ValueError(f"--from {start} comes after --to {stop}")
    return STAGES[first : last + 1]


def run(ctx: BuildContext, start: str = STAGES[0], stop: str = STAGES[-1]) -> None:
    for name in stage_range(start, stop):
        drop_temp_tables(ctx.con)
        log.info("stage %s: start", name)
        load_stage(name).run(ctx)
        log.info("stage %s: done", name)
```

- [ ] **Step 5: Write the CLI**

This is the final file; the `golden-draft` subcommand it dispatches to arrives in Task 18. Until then, only use `run`.

`pipeline/__main__.py`:

```python
"""``python -m pipeline run [--from STAGE] [--to STAGE] --version YYYY.MM.N [--upload]``"""

from __future__ import annotations

import argparse
import logging
import re
import sys
from pathlib import Path

from pipeline import runner
from pipeline.config import STAGES, BuildContext
from pipeline.db import connect

VERSION = re.compile(r"^\d{4}\.\d{2}\.\d+$")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m pipeline")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="run a range of stages")
    run.add_argument("--from", dest="start", choices=STAGES, default=STAGES[0])
    run.add_argument("--to", dest="stop", choices=STAGES, default=STAGES[-1])
    run.add_argument("--build-dir", type=Path, default=Path("build"))
    run.add_argument("--version", help="release version, e.g. 2026.10.1 (required for publish)")
    run.add_argument("--upload", action="store_true", help="attach the release to a GitHub Release")
    draft = sub.add_parser("golden-draft", help="draft a golden entry from a Wikidata series")
    draft.add_argument("qid", help="Wikidata series item, e.g. Q45875")
    draft.add_argument("--build-dir", type=Path, default=Path("build"))
    args = parser.parse_args(argv)

    if args.command == "golden-draft":
        from pipeline.golden import draft_from_wikidata

        con = connect(args.build_dir)
        try:
            sys.stdout.write(draft_from_wikidata(con, args.qid))
        finally:
            con.close()
        return 0

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    stages = runner.stage_range(args.start, args.stop)
    if "publish" in stages and not (args.version and VERSION.match(args.version)):
        parser.error("publish needs --version YYYY.MM.N")
    ctx = BuildContext(build_dir=args.build_dir, con=connect(args.build_dir),
                       version=args.version, upload=args.upload)
    try:
        runner.run(ctx, args.start, args.stop)
    finally:
        ctx.con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 6: Ignore build state and releases**

Apply with `git apply` (save the block to a file first), or make the same edits by hand.

```diff
--- a/.gitignore
+++ b/.gitignore
@@ -22,3 +22,8 @@
 .DS_Store
 .idea/
 .vscode/
+
+# Catalog pipeline working state and releases (published as GitHub Releases)
+/build/
+/releases/
+backend/releases/
```

- [ ] **Step 7: Run the tests**

Run: `cd pipeline && .venv/bin/python -m pytest -v`
Expected: PASS (8 tests). `test_a_failed_stage_leaves_the_previous_tables` proves `swap_in` rolls back when one rename fails.

- [ ] **Step 8: Commit**

```bash
git add pipeline/ .gitignore
git commit -m "feat(pipeline): package scaffold, build context and stage runner"
```

---

### Task 3: Deterministic ids and slugs

**Files:**
- Create: `pipeline/ids.py`
- Test: `pipeline/tests/test_ids.py`

**Interfaces:**
- Consumes: `pipeline.config.MARGIN_NS`, `pipeline._backend.slugify`.
- Produces: `row_id(identity: str) -> str` (UUID string), `work_identity(ol_id) -> "work:ol:…"`, `edition_identity(ol_id) -> "edition:ol:…"`, `series_identity(key) -> "series:" + key`, `assign_slugs(names: Mapping[identity, name]) -> dict[identity, slug]`.

The UUID literals in the test are the contract: if they ever change, every release id changes and every thread and shelf is orphaned.

- [ ] **Step 1: Write the failing test**

`pipeline/tests/test_ids.py`:

```python
from pipeline.ids import assign_slugs, row_id, series_identity, work_identity


def test_row_ids_are_stable_across_runs_and_machines():
    # Literal on purpose: if this changes, every release id changes with it.
    assert row_id(work_identity("OL27448W")) == "24be4984-41f0-5f91-a993-a720b03ad937"
    assert row_id(series_identity("wd:Q45875")) == "0d206ae4-ee28-5ecc-957d-0d1aaca7e028"


def test_distinct_identities_get_distinct_ids():
    assert row_id("work:ol:OL1W") != row_id("edition:ol:OL1W")


def test_slugs_break_collisions_by_identity_order():
    slugs = assign_slugs({"series:single:OL9W": "Dune", "series:single:OL1W": "Dune", "series:wd:Q1": "Dune"})
    assert slugs == {"series:single:OL1W": "dune", "series:single:OL9W": "dune-2", "series:wd:Q1": "dune-3"}


def test_a_suffix_never_takes_another_names_base():
    slugs = assign_slugs({"a": "Dune", "b": "Dune", "c": "Dune 2"})
    assert slugs == {"a": "dune", "b": "dune-3", "c": "dune-2"}


def test_slugs_do_not_depend_on_input_order():
    names = {"x": "Red Rising", "y": "Red Rising", "z": "Golden Son"}
    assert assign_slugs(names) == assign_slugs(dict(reversed(list(names.items()))))
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd pipeline && .venv/bin/python -m pytest tests/test_ids.py -v`
Expected: FAIL — `No module named 'pipeline.ids'`.

- [ ] **Step 3: Implement**

`pipeline/ids.py`:

```python
"""Deterministic row ids and slugs (spec §4.6).

The same book gets the same UUID in every environment and every release,
which is what lets a new release update rows in place under live threads.
"""

from __future__ import annotations

import uuid
from typing import Mapping

from pipeline._backend import slugify
from pipeline.config import MARGIN_NS


def row_id(identity: str) -> str:
    return str(uuid.uuid5(MARGIN_NS, identity))


def work_identity(ol_id: str) -> str:
    return f"work:ol:{ol_id}"


def edition_identity(ol_id: str) -> str:
    return f"edition:ol:{ol_id}"


def series_identity(key: str) -> str:
    """``key`` is ``wd:Q45875``, ``ol:<series_key>`` or ``single:OL27448W``."""
    return f"series:{key}"


def assign_slugs(names: Mapping[str, str]) -> dict[str, str]:
    """Map each identity to a unique slug of its name.

    Identities sharing a slug base are sorted; the first keeps the bare base
    and the rest take ``-2``, ``-3``… skipping any suffix that is itself some
    other name's base, so "Dune" and "Dune 2" never collide.
    """
    by_base: dict[str, list[str]] = {}
    for identity in sorted(names):
        by_base.setdefault(slugify(names[identity]), []).append(identity)
    taken = set(by_base)
    slugs: dict[str, str] = {}
    for base in sorted(by_base):
        first, *rest = by_base[base]
        slugs[first] = base
        n = 2
        for identity in rest:
            while f"{base}-{n}" in taken:
                n += 1
            slugs[identity] = f"{base}-{n}"
            taken.add(slugs[identity])
    return slugs
```

- [ ] **Step 4: Run the test**

Run: `cd pipeline && .venv/bin/python -m pytest tests/test_ids.py -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add pipeline/ids.py pipeline/tests/test_ids.py
git commit -m "feat(pipeline): deterministic uuid5 ids and collision-safe slugs"
```

---

### Task 4: Series evidence written as text

**Files:**
- Create: `pipeline/parse/series_strings.py`
- Test: `pipeline/tests/test_series_strings.py`

**Interfaces:**
- Produces: `SeriesRef(name: str, position: float | None)` (NamedTuple); `parse_series_string(raw: str | None) -> SeriesRef | None` for edition `series` fields (rung 3); `parse_title_series(title: str | None) -> SeriesRef | None` for titles (rung 4, requires a position).

- [ ] **Step 1: Write the failing test**

`pipeline/tests/test_series_strings.py`:

```python
import pytest

from pipeline.parse.series_strings import SeriesRef, parse_series_string, parse_title_series


@pytest.mark.parametrize("raw,expected", [
    ("A Song of Ice and Fire ; 3", SeriesRef("A Song of Ice and Fire", 3.0)),
    ("Red Rising Saga, #2", SeriesRef("Red Rising Saga", 2.0)),
    ("The Expanse (5)", SeriesRef("The Expanse", 5.0)),
    ("Discworld, book 12", SeriesRef("Discworld", 12.0)),
    ("Discworld #12", SeriesRef("Discworld", 12.0)),
    ("Mistborn ; v. 2.5", SeriesRef("Mistborn", 2.5)),
    ("Wheel of time, bk. 4", SeriesRef("Wheel of time", 4.0)),
    ("Harry Potter ; 7.", SeriesRef("Harry Potter", 7.0)),
    ("Remembrance of Earth's Past, #3", SeriesRef("Remembrance of Earth's Past", 3.0)),
    ("Penguin classics", SeriesRef("Penguin classics", None)),
    ("1984", None),
    ("; 3", None),
    ("   ", None),
    (None, None),
])
def test_edition_series_strings(raw, expected):
    assert parse_series_string(raw) == expected


@pytest.mark.parametrize("title,expected", [
    ("The Dark Forest (Remembrance of Earth's Past Series Book 2)", SeriesRef("Remembrance of Earth's Past", 2.0)),
    ("Golden Son (Red Rising Saga, #2)", SeriesRef("Red Rising Saga", 2.0)),
    ("The Two Towers (The Lord of the Rings, Part 2)", SeriesRef("The Lord of the Rings", 2.0)),
    ("Red Rising #1", SeriesRef("Red Rising", 1.0)),
    ("Death's End: Book 3 of the Remembrance of Earth's Past", SeriesRef("Remembrance of Earth's Past", 3.0)),
    ("Book 2 of 3", None),
    ("Catch-22", None),
    ("Fahrenheit 451", None),
    ("The Hobbit", None),
    ("Carrie (Signet Classics)", None),
])
def test_title_patterns(title, expected):
    assert parse_title_series(title) == expected
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd pipeline && .venv/bin/python -m pytest tests/test_series_strings.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement**

`pipeline/parse/series_strings.py`:

```python
"""Series evidence written as text: edition ``series`` fields and titles.

Pure string rules, tested as tables. Two sources, one result type:

* an Open Library edition's ``series`` field — ``Name ; 2``, ``Name, #2``,
  ``Name (2)``, ``Name, book 2``, or a bare name with no position (ladder rung 3);
* a title that carries its series — ``(X Series Book 2)``, ``X #2``,
  ``Book 2 of X`` (rung 4).
"""

from __future__ import annotations

import re
from typing import NamedTuple


class SeriesRef(NamedTuple):
    name: str
    position: float | None


_POS = r"(?P<pos>\d{1,3}(?:\.\d{1,2})?)"
_MARK = r"(?:#|no\.?|v\.|vol\.?|volume|book|bk\.?|part)"
_SERIES_FORMS = (
    re.compile(rf"^(?P<name>.+?)\s*;\s*(?:{_MARK}\s*)?{_POS}$", re.I),
    re.compile(rf"^(?P<name>.+?),\s*{_MARK}\s*{_POS}$", re.I),
    re.compile(rf"^(?P<name>.+?)\s*\(\s*(?:{_MARK}\s*)?{_POS}\s*\)$", re.I),
    re.compile(rf"^(?P<name>.+?)\s+{_MARK}\s*{_POS}$", re.I),
)
_TITLE_FORMS = (
    re.compile(rf"\((?P<name>[^()]+?)(?:\s+series)?,?\s+{_MARK}\s*{_POS}\s*\)", re.I),
    re.compile(
        r"\b(?:book|volume|part)\s+(?P<pos>\d{1,3})\s+of\s+(?:the\s+)?"
        r"(?P<name>[^():]+?)(?:\s+series)?\s*\)?\s*$",
        re.I,
    ),
    re.compile(rf"^(?P<name>[^()#]+?)\s*#\s*{_POS}\s*$"),
)
_LETTER = re.compile(r"[^\W\d_]")
_SPACE = re.compile(r"\s+")


def _clean_name(raw: str) -> str | None:
    """A usable series name, or None. "Book 2 of 3" names nothing."""
    name = _SPACE.sub(" ", raw).strip(" ,;:-")
    if not _LETTER.search(name) or len(name) > 150:
        return None
    return name


def parse_series_string(raw: str | None) -> SeriesRef | None:
    text = _SPACE.sub(" ", raw or "").strip().rstrip(".").strip()
    if not text:
        return None
    for form in _SERIES_FORMS:
        match = form.match(text)
        if match:
            name = _clean_name(match.group("name"))
            return SeriesRef(name, float(match.group("pos"))) if name else None
    name = _clean_name(text)
    return SeriesRef(name, None) if name else None


def parse_title_series(title: str | None) -> SeriesRef | None:
    """Series named inside a title. A title without a position names none."""
    text = _SPACE.sub(" ", title or "").strip()
    for form in _TITLE_FORMS:
        match = form.search(text)
        if match:
            name = _clean_name(match.group("name"))
            if name:
                return SeriesRef(name, float(match.group("pos")))
    return None
```

- [ ] **Step 4: Run the test**

Run: `cd pipeline && .venv/bin/python -m pytest tests/test_series_strings.py -v`
Expected: PASS (24 cases). *Fahrenheit 451*, *Catch-22* and "Book 2 of 3" name no series.

- [ ] **Step 5: Commit**

```bash
git add pipeline/parse pipeline/tests/test_series_strings.py
git commit -m "feat(pipeline): parse edition series strings and title patterns"
```

---

### Task 5: Junk rules as data

**Files:**
- Create: `pipeline/rules/junk.yaml`, `pipeline/select_rules.py`
- Test: `pipeline/tests/test_junk.py`

**Interfaces:**
- Produces: `WorkForSelect(ol_id, title, subjects: tuple[str, ...], author_ids: tuple[str, ...], max_pages: int | None, publishers: tuple[str, ...])`; `JunkRules.load(path) -> JunkRules`; `JunkRules.reason(work) -> str | None` returning `"no_author"`, `"short"`, or a rule name from the YAML (`calendar`, `colouring_book`, `thesis`, `government_document`, `study_guide`).

No rule matches a bare "diary" or a title beginning "A Dissertation": the `KEEP` list in the test is the guard for every future edit of the YAML (Review Focus 1). An unknown page count keeps the work.

- [ ] **Step 1: Write the failing test**

`pipeline/tests/test_junk.py`:

```python
import pytest

from pipeline.config import PIPELINE_DIR
from pipeline.select_rules import JunkRules, WorkForSelect

RULES = JunkRules.load(PIPELINE_DIR / "rules" / "junk.yaml")


def work(title="A Book", subjects=(), authors=("OL1A",), max_pages=300, publishers=()):
    return WorkForSelect("OL1W", title, tuple(subjects), tuple(authors), max_pages, tuple(publishers))


# Real books whose titles brush against a junk pattern. Every rule change must keep them.
KEEP = [
    work("The Diary of a Young Girl"),
    work("Diary of a Wimpy Kid"),
    work("A Journal of the Plague Year"),
    work("The Colour of Magic"),
    work("A Dissertation upon Roast Pig"),
    work("The Summer Book"),
    work("Analysis"),
]


@pytest.mark.parametrize("keep", KEEP, ids=[w.title for w in KEEP])
def test_real_books_are_kept(keep):
    assert RULES.reason(keep) is None


@pytest.mark.parametrize("candidate,reason", [
    (work(authors=()), "no_author"),
    (work(max_pages=24), "short"),
    (work("Red Rising 2027 Wall Calendar"), "calendar"),
    (work("2026 Diary"), "calendar"),
    (work("Blank", subjects=["Calendars"]), "calendar"),
    (work("The Hobbit Colouring Book"), "colouring_book"),
    (work("Stellar Winds", subjects=["Dissertations, Academic"]), "thesis"),
    (work("Annual Report", publishers=["U.S. Government Printing Office"]), "government_document"),
    (work("Summary of Atomic Habits"), "study_guide"),
    (work("Analysis of The Great Gatsby"), "study_guide"),
    (work("The Great Gatsby Study Guide"), "study_guide"),
    (work("Macbeth", subjects=["Study guides"]), "study_guide"),
])
def test_junk_is_dropped_with_its_rule(candidate, reason):
    assert RULES.reason(candidate) == reason


def test_unknown_page_count_is_kept():
    assert RULES.reason(work(max_pages=None)) is None
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd pipeline && .venv/bin/python -m pytest tests/test_junk.py -v`
Expected: FAIL — `No module named 'pipeline.select_rules'`.

- [ ] **Step 3: Implement**

`pipeline/rules/junk.yaml`:

```yaml
# Junk rules for the select stage (spec §4.2). A work is dropped when any
# pattern of a rule matches. Patterns are Python regexes matched
# case-insensitively: `title` against the work's title, `subject` against each
# subject line, `publisher` against each English edition's publisher.
#
# Every change must keep tests/test_junk.py::KEEP passing — "The Diary of a
# Young Girl" and "Diary of a Wimpy Kid" are why no rule matches a bare "diary".
min_pages: 40
rules:
  - name: calendar
    title:
      - '\bcalendars?\b'
      - '\b(?:planner|desk diary|pocket diary)\b'
      - '\b(?:19|20)\d\d\s+(?:diary|journal|planner)\b'
    subject:
      - '^calendars?$'
      - '^diaries \(blank-books\)$'
      - '^blank[- ]books?$'
  - name: colouring_book
    title:
      - '\bcolou?ring\s+book\b'
      - '\bcolou?ring\s+(?:and|&)\s+activity\b'
    subject:
      - '^colou?ring books?$'
  - name: thesis
    subject:
      - '^(?:theses|dissertations)\b'
      - '^dissertations, academic$'
    publisher:
      - '\buniversity microfilms\b'
      - '\bproquest\b'
  - name: government_document
    subject:
      - '^government publications\b'
    publisher:
      - '\bgovernment printing office\b'
      - '\bstationery office\b'
      - '^g\.?p\.?o\.?$'
      - '^h\.?m\.?s\.?o\.?$'
  - name: study_guide
    title:
      - '^(?:summary|analysis|study guide|workbook)\s+(?:of|for|&|and)\b'
      - '\bstudy guide\b'
      - '^(?:sparknotes|cliffsnotes|cliffs notes|bookrags)\b'
    subject:
      - '^study guides?$'
```

`pipeline/select_rules.py`:

```python
"""Junk rules for the select stage, loaded from ``rules/junk.yaml``."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass(frozen=True)
class WorkForSelect:
    ol_id: str
    title: str
    subjects: tuple[str, ...]
    author_ids: tuple[str, ...]
    max_pages: int | None  # largest page count among English editions; None = unknown
    publishers: tuple[str, ...]


@dataclass(frozen=True)
class JunkRule:
    name: str
    title: tuple[re.Pattern[str], ...]
    subject: tuple[re.Pattern[str], ...]
    publisher: tuple[re.Pattern[str], ...]

    def matches(self, work: WorkForSelect) -> bool:
        return (
            any(p.search(work.title) for p in self.title)
            or any(p.search(s) for p in self.subject for s in work.subjects)
            or any(p.search(pub) for p in self.publisher for pub in work.publishers)
        )


def _compile(patterns: list[str] | None) -> tuple[re.Pattern[str], ...]:
    return tuple(re.compile(p, re.IGNORECASE) for p in patterns or ())


@dataclass(frozen=True)
class JunkRules:
    min_pages: int
    rules: tuple[JunkRule, ...]

    @classmethod
    def load(cls, path: Path) -> "JunkRules":
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        return cls(
            min_pages=int(data["min_pages"]),
            rules=tuple(
                JunkRule(
                    name=r["name"],
                    title=_compile(r.get("title")),
                    subject=_compile(r.get("subject")),
                    publisher=_compile(r.get("publisher")),
                )
                for r in data["rules"]
            ),
        )

    def reason(self, work: WorkForSelect) -> str | None:
        """The name of the first rule that drops ``work``, or None to keep it.

        A work with no known page count is kept: absence of a fact is not
        evidence of a pamphlet.
        """
        if not work.author_ids:
            return "no_author"
        if work.max_pages is not None and work.max_pages < self.min_pages:
            return "short"
        for rule in self.rules:
            if rule.matches(work):
                return rule.name
        return None
```

- [ ] **Step 4: Run the test**

Run: `cd pipeline && .venv/bin/python -m pytest tests/test_junk.py -v`
Expected: PASS (20 cases).

- [ ] **Step 5: Commit**

```bash
git add pipeline/rules/junk.yaml pipeline/select_rules.py pipeline/tests/test_junk.py
git commit -m "feat(pipeline): reviewable junk rules for the select stage"
```

---

### Task 6: Resumable, verified dump downloads

**Files:**
- Create: `pipeline/sources/records.py`, `pipeline/sources/http.py`, `pipeline/sources/ol_dumps.py`
- Create: `pipeline/tests/fixtures/__init__.py` (empty), `pipeline/tests/fixtures/dumps.py`
- Test: `pipeline/tests/test_ol_dumps.py`

**Interfaces:**
- Produces (`records`): `SourceRecord(name, url, retrieved, size, sha256)`; `dump_date(url) -> str | None`; `sha256_file(path)`; `write_record(dest, record)` / `read_record(dest)` (a `<file>.source.json` sidecar).
- Produces (`http`): `RETRYABLE_STATUS`, `RetryableError`, `with_retries(action, *, attempts, sleep, give_up)` (backoff 1s, 2s, 4s…), `check_status(response)`.
- Produces (`ol_dumps`): `DownloadError`; `verify_gzip(path)`; `download(client, name, url, dest, *, attempts=5, sleep) -> SourceRecord` — follows OL's `latest` redirect, resumes a `.part` with `Range`, verifies the gzip end to end, records the source, and returns the recorded source without fetching when `dest` already exists.
- Produces (`tests/fixtures/dumps`): `gz(lines) -> bytes`, `dump_line(type_, key, record)`, `edition_line(ol_id, work, languages=("eng",), **fields)`, `sparql_json(rows)`, `entity(qid)`.

Checksum verification is the gzip trailer (CRC-32 and length): decompressing the whole file proves it intact without trusting a second download. The SHA-256 is recorded for provenance, not compared.

- [ ] **Step 1: Write the fixture builders and the failing test**

`pipeline/tests/fixtures/dumps.py`:

```python
"""Builders for tiny Open Library dumps and Wikidata responses."""

from __future__ import annotations

import gzip
import json
from typing import Iterable


def gz(lines: Iterable[str]) -> bytes:
    # mtime=0 keeps the bytes identical run to run.
    return gzip.compress(("\n".join(lines) + "\n").encode("utf-8"), mtime=0)


def dump_line(type_: str, key: str, record: dict) -> str:
    """One row of an OL entity dump: type, key, revision, last_modified, JSON."""
    return "\t".join([type_, key, "1", "2026-08-31T00:00:00", json.dumps(record)])


def edition_line(ol_id: str, work: str, languages=("eng",), **fields) -> str:
    record = {"key": f"/books/{ol_id}", "works": [{"key": f"/works/{work}"}],
              "languages": [{"key": f"/languages/{lang}"} for lang in languages], **fields}
    return dump_line("/type/edition", f"/books/{ol_id}", record)


def sparql_json(rows: list[dict[str, str]]) -> dict:
    def value(v: str) -> dict:
        kind = "uri" if v.startswith("http://www.wikidata.org/entity/") else "literal"
        return {"type": kind, "value": v}
    return {"results": {"bindings": [{k: value(v) for k, v in row.items()} for row in rows]}}


def entity(q: str) -> str:
    return f"http://www.wikidata.org/entity/{q}"
```

`pipeline/tests/test_ol_dumps.py`:

```python
import hashlib

import httpx
import pytest
import respx

from pipeline.sources.ol_dumps import DownloadError, download
from pipeline.tests.fixtures.dumps import gz

LATEST = "https://dumps.test/ol_dump_works_latest.txt.gz"
DATED = "https://archive.test/ol_dump_works_2026-08-31.txt.gz"
DATA = gz([f"/type/work\t/works/OL{i}W\t1\t2026\t{{}}" for i in range(500)])


@respx.mock
def test_downloads_through_the_redirect_and_records_the_source(tmp_path):
    respx.get(LATEST).mock(return_value=httpx.Response(302, headers={"Location": DATED}))
    respx.get(DATED).mock(return_value=httpx.Response(200, content=DATA))
    with httpx.Client() as client:
        record = download(client, "works", LATEST, tmp_path / "works.txt.gz", sleep=lambda s: None)
    assert (tmp_path / "works.txt.gz").read_bytes() == DATA
    assert record.url == DATED
    assert record.retrieved == "2026-08-31"
    assert record.sha256 == hashlib.sha256(DATA).hexdigest()
    assert record.size == len(DATA)


@respx.mock
def test_resumes_a_partial_download_with_a_range_request(tmp_path):
    half = len(DATA) // 2
    (tmp_path / "works.txt.gz.part").write_bytes(DATA[:half])

    def serve(request):
        assert request.headers["Range"] == f"bytes={half}-"
        return httpx.Response(206, content=DATA[half:])

    respx.get(DATED).mock(side_effect=serve)
    with httpx.Client() as client:
        download(client, "works", DATED, tmp_path / "works.txt.gz", sleep=lambda s: None)
    assert (tmp_path / "works.txt.gz").read_bytes() == DATA


@respx.mock
def test_retries_a_server_error_with_backoff(tmp_path):
    respx.get(DATED).mock(side_effect=[httpx.Response(503), httpx.Response(200, content=DATA)])
    sleeps = []
    with httpx.Client() as client:
        download(client, "works", DATED, tmp_path / "works.txt.gz", sleep=sleeps.append)
    assert sleeps == [1]


@respx.mock
def test_a_corrupt_file_is_deleted_and_fails_the_stage(tmp_path):
    respx.get(DATED).mock(return_value=httpx.Response(200, content=DATA[:-20]))
    with httpx.Client() as client, pytest.raises(DownloadError, match="verification"):
        download(client, "works", DATED, tmp_path / "works.txt.gz", sleep=lambda s: None)
    assert list(tmp_path.iterdir()) == []


@respx.mock
def test_a_finished_download_is_not_fetched_again(tmp_path):
    route = respx.get(DATED).mock(return_value=httpx.Response(200, content=DATA))
    with httpx.Client() as client:
        first = download(client, "works", DATED, tmp_path / "works.txt.gz", sleep=lambda s: None)
        second = download(client, "works", DATED, tmp_path / "works.txt.gz", sleep=lambda s: None)
    assert route.call_count == 1
    assert first == second
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd pipeline && .venv/bin/python -m pytest tests/test_ol_dumps.py -v`
Expected: FAIL — `No module named 'pipeline.sources.ol_dumps'`.

- [ ] **Step 3: Implement**

`pipeline/sources/records.py`:

```python
"""Provenance for every input: what was fetched, from where, and its hash."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path

_DUMP_DATE = re.compile(r"(\d{4}-\d{2}-\d{2})")


@dataclass(frozen=True)
class SourceRecord:
    name: str
    url: str  # the final URL, after Open Library's "latest" redirect
    retrieved: str  # the dump date from the file name, else an ISO timestamp
    size: int
    sha256: str


def dump_date(url: str) -> str | None:
    match = _DUMP_DATE.search(url.rsplit("/", 1)[-1])
    return match.group(1) if match else None


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_record(dest: Path, record: SourceRecord) -> None:
    """Sidecar next to a downloaded file, so a re-run can skip the download."""
    dest.with_name(dest.name + ".source.json").write_text(json.dumps(asdict(record), sort_keys=True))


def read_record(dest: Path) -> SourceRecord | None:
    sidecar = dest.with_name(dest.name + ".source.json")
    if not (dest.exists() and sidecar.exists()):
        return None
    return SourceRecord(**json.loads(sidecar.read_text()))
```

`pipeline/sources/http.py`:

```python
"""Retry policy shared by every fetch."""

from __future__ import annotations

from typing import Callable, TypeVar

import httpx

RETRYABLE_STATUS = {429, 500, 502, 503, 504}
T = TypeVar("T")


class RetryableError(RuntimeError):
    """A failure worth another attempt: a 5xx/429, a dropped connection, a truncated stream."""


def with_retries(action: Callable[[], T], *, attempts: int, sleep: Callable[[float], None],
                 give_up: Callable[[Exception], Exception]) -> T:
    """Run ``action``, backing off 1s, 2s, 4s… between retryable failures."""
    for attempt in range(attempts):
        try:
            return action()
        except (RetryableError, httpx.TransportError) as exc:
            if attempt == attempts - 1:
                raise give_up(exc) from exc
            sleep(2 ** attempt)
    raise AssertionError("unreachable")


def check_status(response: httpx.Response) -> None:
    if response.status_code in RETRYABLE_STATUS:
        raise RetryableError(f"HTTP {response.status_code} from {response.url}")
    response.raise_for_status()
```

`pipeline/sources/ol_dumps.py`:

```python
"""Open Library dump downloads: resumable, verified, recorded."""

from __future__ import annotations

import gzip
from pathlib import Path
from typing import Callable

import httpx

from pipeline.sources.http import check_status, with_retries
from pipeline.sources.records import SourceRecord, dump_date, read_record, sha256_file, write_record


class DownloadError(RuntimeError):
    pass


def _fetch_into(client: httpx.Client, url: str, part: Path) -> str:
    """Append the rest of ``url`` to ``part`` (HTTP Range); return the final URL."""
    offset = part.stat().st_size if part.exists() else 0
    headers = {"Range": f"bytes={offset}-"} if offset else {}
    with client.stream("GET", url, headers=headers, follow_redirects=True) as response:
        if response.status_code == 416:  # nothing left to send: the part is complete
            return str(response.url)
        check_status(response)
        mode = "ab" if response.status_code == 206 else "wb"
        with part.open(mode) as fh:
            for chunk in response.iter_bytes(1 << 20):
                fh.write(chunk)
        return str(response.url)


def verify_gzip(path: Path) -> None:
    """Decompress end to end: gzip's CRC-32 and length trailer catch corruption."""
    try:
        with gzip.open(path, "rb") as fh:
            while fh.read(1 << 24):
                pass
    except (OSError, EOFError) as exc:
        path.unlink(missing_ok=True)
        raise DownloadError(f"{path.name} failed verification: {exc}") from exc


def download(client: httpx.Client, name: str, url: str, dest: Path, *,
             attempts: int = 5, sleep: Callable[[float], None]) -> SourceRecord:
    """Download ``url`` to ``dest`` once; later calls return the recorded source."""
    existing = read_record(dest)
    if existing is not None:
        return existing
    part = dest.with_name(dest.name + ".part")
    final_url = with_retries(
        lambda: _fetch_into(client, url, part),
        attempts=attempts, sleep=sleep,
        give_up=lambda exc: DownloadError(f"{name}: {exc}"),
    )
    verify_gzip(part)
    part.rename(dest)
    record = SourceRecord(name, final_url, dump_date(final_url) or "", dest.stat().st_size, sha256_file(dest))
    write_record(dest, record)
    return record
```

- [ ] **Step 4: Run the test**

Run: `cd pipeline && .venv/bin/python -m pytest tests/test_ol_dumps.py -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add pipeline/sources pipeline/tests/fixtures pipeline/tests/test_ol_dumps.py
git commit -m "feat(pipeline): resumable, gzip-verified dump downloads"
```

---

### Task 7: Stream-filter the editions dump

**Files:**
- Create: `pipeline/sources/editions.py`
- Test: `pipeline/tests/test_editions_stream.py`

**Interfaces:**
- Consumes: `http.with_retries`, `http.check_status`, `http.RetryableError`, `ol_dumps.DownloadError`, `records.SourceRecord`, `records.dump_date`.
- Produces: `EDITION_SCHEMA: pa.Schema` (`ol_id, work_ol_id, is_english, title, subtitle, publishers, publish_date, isbn_13, isbn_10, number_of_pages, covers, series`); `EditionSink` protocol (`reset()`, `write(batch: pa.Table)`); `edition_row(ol_id, work, is_english, record) -> dict`;
  `stream_editions(client, url, candidates: set[str], wd_editions: set[str], sink, *, resolve: Mapping[str, str] | None = None, attempts=3, sleep, batch_size=50_000) -> tuple[SourceRecord, Counter[str]]` — keeps English editions of candidate works plus every Wikidata-linked edition, and counts every candidate's editions in all languages.

A regex and a substring test decide each line before any JSON is parsed — the dump holds tens of millions of editions. A failure calls `sink.reset()` and restarts: a gzip stream cannot resume mid-member (Review Focus 3).

- [ ] **Step 1: Write the failing test**

`pipeline/tests/test_editions_stream.py`:

```python
import httpx
import pyarrow as pa
import respx

from pipeline.sources.editions import stream_editions
from pipeline.tests.fixtures.dumps import edition_line, gz

URL = "https://dumps.test/ol_dump_editions_2026-08-31.txt.gz"
LINES = [
    edition_line("OL1M", "OL10W", title="A Game of Thrones", series=["A Song of Ice and Fire ; 1"]),
    edition_line("OL2M", "OL10W", languages=("fre",), title="Le Trône de fer"),
    edition_line("OL3M", "OL77W", title="Not selected"),
    edition_line("OL4M", "OL77W", languages=("ger",), title="Linked by Wikidata"),
    edition_line("OL5M", "OL99W", title="Redirected work"),
    "garbage line without tabs",
]


class ListSink:
    def __init__(self):
        self.batches, self.resets = [], 0

    def reset(self):
        self.batches, self.resets = [], self.resets + 1

    def write(self, batch):
        self.batches.append(batch)

    def rows(self):
        return pa.concat_tables(self.batches).to_pylist() if self.batches else []


@respx.mock
def test_keeps_english_editions_of_candidates_and_wikidata_editions(tmp_path):
    respx.get(URL).mock(return_value=httpx.Response(200, content=gz(LINES)))
    sink = ListSink()
    with httpx.Client() as client:
        record, counts = stream_editions(client, URL, {"OL10W", "OL30W"}, {"OL4M"}, sink,
                                         resolve={"OL99W": "OL30W"}, sleep=lambda s: None, batch_size=2)
    kept = {r["ol_id"]: r for r in sink.rows()}
    assert set(kept) == {"OL1M", "OL4M", "OL5M"}
    assert kept["OL1M"]["series"] == ["A Song of Ice and Fire ; 1"]
    assert kept["OL4M"]["is_english"] is False
    assert kept["OL5M"]["work_ol_id"] == "OL30W"
    assert counts == {"OL10W": 2, "OL30W": 1}
    assert record.retrieved == "2026-08-31"
    assert list(tmp_path.iterdir()) == []  # nothing written to disk


@respx.mock
def test_a_truncated_stream_restarts_from_the_beginning():
    data = gz(LINES)
    respx.get(URL).mock(side_effect=[httpx.Response(200, content=data[:-30]), httpx.Response(200, content=data)])
    sink = ListSink()
    with httpx.Client() as client:
        stream_editions(client, URL, {"OL10W"}, set(), sink, sleep=lambda s: None)
    assert sink.resets == 2
    assert [r["ol_id"] for r in sink.rows()] == ["OL1M"]
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd pipeline && .venv/bin/python -m pytest tests/test_editions_stream.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement**

`pipeline/sources/editions.py`:

```python
"""Stream the editions dump through a filter; the unfiltered file never lands on disk.

The editions dump is larger than the build machine's free space, so it is
decompressed in memory and only English editions of selected works (plus
editions Wikidata links to) are kept.
"""

from __future__ import annotations

import hashlib
import json
import re
import zlib
from collections import Counter
from typing import Callable, Iterable, Mapping, Protocol

import httpx
import pyarrow as pa

from pipeline.sources.http import RetryableError, check_status, with_retries
from pipeline.sources.ol_dumps import DownloadError
from pipeline.sources.records import SourceRecord, dump_date

EDITION_SCHEMA = pa.schema([
    ("ol_id", pa.string()),
    ("work_ol_id", pa.string()),
    ("is_english", pa.bool_()),
    ("title", pa.string()),
    ("subtitle", pa.string()),
    ("publishers", pa.list_(pa.string())),
    ("publish_date", pa.string()),
    ("isbn_13", pa.list_(pa.string())),
    ("isbn_10", pa.list_(pa.string())),
    ("number_of_pages", pa.int64()),
    ("covers", pa.list_(pa.int64())),
    ("series", pa.list_(pa.string())),
])
# Cheap pre-filters: a regex and a substring test instead of parsing ~50M JSON documents.
_WORK_KEY = re.compile(r'"works":\s*\[\s*\{\s*"key":\s*"/works/(OL\d+W)"')
_ENGLISH = '"/languages/eng"'


class EditionSink(Protocol):
    def reset(self) -> None: ...
    def write(self, batch: pa.Table) -> None: ...


def _strings(value) -> list[str]:
    return [v for v in value if isinstance(v, str)] if isinstance(value, list) else []


def _ints(value) -> list[int]:
    return [v for v in value if isinstance(v, int) and v > 0] if isinstance(value, list) else []


def edition_row(ol_id: str, work: str | None, is_english: bool, record: dict) -> dict:
    pages = record.get("number_of_pages")
    return {
        "ol_id": ol_id,
        "work_ol_id": work,
        "is_english": is_english,
        "title": record.get("title") if isinstance(record.get("title"), str) else None,
        "subtitle": record.get("subtitle") if isinstance(record.get("subtitle"), str) else None,
        "publishers": _strings(record.get("publishers")),
        "publish_date": record.get("publish_date") if isinstance(record.get("publish_date"), str) else None,
        "isbn_13": _strings(record.get("isbn_13")),
        "isbn_10": _strings(record.get("isbn_10")),
        "number_of_pages": pages if isinstance(pages, int) and pages > 0 else None,
        "covers": _ints(record.get("covers")),
        "series": _strings(record.get("series")),
    }


def _lines(chunks: Iterable[bytes], on_chunk: Callable[[bytes], None]) -> Iterable[bytes]:
    decomp = zlib.decompressobj(zlib.MAX_WBITS | 16)
    buffer = b""
    for chunk in chunks:
        on_chunk(chunk)
        data = decomp.decompress(chunk)
        while decomp.unused_data:  # a multi-member gzip starts a new member
            rest = decomp.unused_data
            decomp = zlib.decompressobj(zlib.MAX_WBITS | 16)
            data += decomp.decompress(rest)
        buffer += data
        *complete, buffer = buffer.split(b"\n")
        yield from complete
    if buffer:
        yield buffer
    if not decomp.eof:
        raise RetryableError("editions stream ended before the gzip trailer")


def stream_editions(client: httpx.Client, url: str, candidates: set[str], wd_editions: set[str],
                    sink: EditionSink, *, resolve: Mapping[str, str] | None = None,
                    attempts: int = 3, sleep: Callable[[float], None],
                    batch_size: int = 50_000) -> tuple[SourceRecord, Counter[str]]:
    """Keep English editions of ``candidates`` and every edition in ``wd_editions``.

    Returns the source record and, for every candidate work, its edition count
    in all languages (Open Library's total, which the app shows). ``resolve``
    maps a redirected work id to its target. A failure restarts the stream
    from the beginning: a gzip stream cannot resume mid-member.
    """
    resolve = resolve or {}

    def attempt() -> tuple[SourceRecord, Counter[str]]:
        sink.reset()
        counts: Counter[str] = Counter()
        digest = hashlib.sha256()
        size = 0
        rows: list[dict] = []

        def on_chunk(chunk: bytes) -> None:
            nonlocal size
            digest.update(chunk)
            size += len(chunk)

        with client.stream("GET", url, follow_redirects=True) as response:
            check_status(response)
            final_url = str(response.url)
            for raw in _lines(response.iter_bytes(1 << 20), on_chunk):
                line = raw.decode("utf-8", errors="replace")
                parts = line.split("\t", 4)
                if len(parts) < 5:
                    continue
                ol_id = parts[1].rsplit("/", 1)[-1]
                match = _WORK_KEY.search(parts[4])
                work = resolve.get(match.group(1), match.group(1)) if match else None
                if work in candidates:
                    counts[work] += 1
                english = _ENGLISH in parts[4]
                if not ((english and work in candidates) or ol_id in wd_editions):
                    continue
                try:
                    record = json.loads(parts[4])
                except json.JSONDecodeError:
                    continue
                rows.append(edition_row(ol_id, work, english, record))
                if len(rows) >= batch_size:
                    sink.write(pa.Table.from_pylist(rows, schema=EDITION_SCHEMA))
                    rows.clear()
        if rows:
            sink.write(pa.Table.from_pylist(rows, schema=EDITION_SCHEMA))
        return SourceRecord("editions", final_url, dump_date(final_url) or "", size, digest.hexdigest()), counts

    return with_retries(attempt, attempts=attempts, sleep=sleep,
                        give_up=lambda exc: DownloadError(f"editions: {exc}"))
```

- [ ] **Step 4: Run the test**

Run: `cd pipeline && .venv/bin/python -m pytest tests/test_editions_stream.py -v`
Expected: PASS (2 tests); the first also asserts nothing was written to disk.

- [ ] **Step 5: Commit**

```bash
git add pipeline/sources/editions.py pipeline/tests/test_editions_stream.py
git commit -m "feat(pipeline): stream-filter the editions dump without landing it on disk"
```

---

### Task 8: Wikidata over paged SPARQL

**Files:**
- Create: `pipeline/group/types.py`, `pipeline/sources/wikidata.py`
- Test: `pipeline/tests/test_wikidata.py`

**Interfaces:**
- Produces (`group/types`): `OVERRIDE_RUNG = 0`; `PROVENANCE` and `CONFIDENCE` maps from rung (0–4) to the app's enum strings; frozen dataclasses `GWork(ol_id, titles, primary_author, kind, subjects, edition_series, wd_items, first_publish_year=None)`, `WdMembership(item, series, ordinal)`, `WdSeries(qid, label, aliases=(), parents=())`, `Candidate(key, name, position, rung)`, `Membership(key, position, rung)`.
- Produces (`wikidata`): `WikidataError`; `qid(uri)`; `sparql(client, url, query, *, sleep, attempts=5) -> list[dict[str, str]]`; `paged(...)`;
  `fetch_memberships(client, url, *, sleep, page_size=10_000) -> list[tuple[WdMembership, str]]` (the `str` is the OL work or edition id);
  `fetch_series(client, url, series, *, sleep, batch=200) -> dict[str, WdSeries]` (climbs parents to depth 5);
  `fetch_author_ids(...) -> list[tuple[qid, ol_author_id]]`; `fetch_author_names(client, url, items, *, sleep, batch=200) -> list[tuple[qid, name]]`.

The grouping value types are created here because Wikidata rows are parsed straight into them. Queries are restricted to items carrying an OL id (P648), which keeps TV episodes and scholarly articles — the bulk of P179 — out.

- [ ] **Step 1: Write the failing test**

`pipeline/tests/test_wikidata.py`:

```python
import json
from urllib.parse import parse_qs

import httpx
import pytest
import respx

from pipeline.group.types import WdMembership, WdSeries
from pipeline.sources.wikidata import WikidataError, fetch_memberships, fetch_series
from pipeline.tests.fixtures.dumps import entity, sparql_json

URL = "https://sparql.test/sparql"


def query_of(request) -> str:
    return parse_qs(request.content.decode())["query"][0]


@respx.mock
def test_pages_until_a_short_page():
    rows = [{"item": entity(f"Q{i}"), "olid": f"OL{i}W", "series": entity("Q45875"), "ordinal": str(i)}
            for i in range(1, 6)]

    def serve(request):
        q = query_of(request)
        offset = int(q.rsplit("OFFSET", 1)[1])
        return httpx.Response(200, json=sparql_json(rows[offset:offset + 2]))

    route = respx.post(URL).mock(side_effect=serve)
    with httpx.Client() as client:
        found = fetch_memberships(client, URL, sleep=lambda s: None, page_size=2)
    assert route.call_count == 3
    assert found[0] == (WdMembership("Q1", "Q45875", "1"), "OL1W")
    assert len(found) == 5


@respx.mock
def test_a_page_that_keeps_failing_aborts():
    respx.post(URL).mock(return_value=httpx.Response(503))
    with httpx.Client() as client, pytest.raises(WikidataError):
        fetch_memberships(client, URL, sleep=lambda s: None)


@respx.mock
def test_series_details_climb_to_parents():
    def serve(request):
        q = query_of(request)
        if "wd:Q15228" in q:
            return httpx.Response(200, json=sparql_json([
                {"series": entity("Q15228"), "label": "The Lord of the Rings", "parent": entity("Q81")}]))
        return httpx.Response(200, json=sparql_json([{"series": entity("Q81"), "label": "Middle-earth"}]))

    respx.post(URL).mock(side_effect=serve)
    with httpx.Client() as client:
        series = fetch_series(client, URL, {"Q15228"}, sleep=lambda s: None)
    assert series == {
        "Q15228": WdSeries("Q15228", "The Lord of the Rings", (), ("Q81",)),
        "Q81": WdSeries("Q81", "Middle-earth", (), ()),
    }
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd pipeline && .venv/bin/python -m pytest tests/test_wikidata.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement**

`pipeline/group/types.py`:

```python
"""Plain value types the grouping rules pass between each other."""

from __future__ import annotations

from dataclasses import dataclass

# Ladder rungs (spec §5.3). 0 marks a membership set by an override.
OVERRIDE_RUNG = 0
PROVENANCE = {0: "override", 1: "wikidata", 2: "ol_tag", 3: "ol_edition_series", 4: "title_pattern"}
CONFIDENCE = {0: "high", 1: "high", 2: "medium", 3: "medium", 4: "low"}


@dataclass(frozen=True)
class GWork:
    """A work as the ladder sees it."""

    ol_id: str
    titles: tuple[str, ...]  # the work's raw title first, then its English editions' raw titles
    primary_author: str | None  # author cluster id
    kind: str  # "single" | "collection"
    subjects: str | None  # one subject per line
    edition_series: tuple[tuple[str, ...], ...]  # each English edition's raw `series` strings
    wd_items: frozenset[str]  # Wikidata items linked by P648 to the work or one of its editions
    first_publish_year: int | None = None


@dataclass(frozen=True)
class WdMembership:
    item: str  # Q-id of the book
    series: str  # Q-id of the series
    ordinal: str | None  # raw P1545 value


@dataclass(frozen=True)
class WdSeries:
    qid: str
    label: str | None
    aliases: tuple[str, ...] = ()
    parents: tuple[str, ...] = ()  # Q-ids via P179 or P361


@dataclass(frozen=True)
class Candidate:
    """One rung's claim that a work belongs to a series."""

    key: str  # "wd:Q45875" or "ol:<series_key>"
    name: str
    position: float | None
    rung: int


@dataclass(frozen=True)
class Membership:
    key: str
    position: float | None
    rung: int
```

`pipeline/sources/wikidata.py`:

```python
"""Wikidata over SPARQL: series membership, ordinals, nesting, author ids.

Set ``WIKIDATA_SPARQL_URL`` to another endpoint (QLever serves the same
SPARQL without the public service's 60-second limit) if pages time out.
"""

from __future__ import annotations

from typing import Callable, Iterable, Iterator

import httpx

from pipeline.config import USER_AGENT
from pipeline.group.types import WdMembership, WdSeries
from pipeline.sources.http import RetryableError, check_status, with_retries

MEMBERSHIPS = """
SELECT ?item ?olid ?series ?ordinal WHERE {{
  ?item wdt:P648 ?olid .
  ?item p:P179 ?st . ?st ps:P179 ?series .
  OPTIONAL {{ ?st pq:P1545 ?ordinal . }}
  FILTER(REGEX(?olid, "^OL[0-9]+[WM]$"))
}} ORDER BY ?item ?series ?olid ?ordinal LIMIT {limit} OFFSET {offset}
"""
AUTHOR_IDS = """
SELECT ?item ?olid WHERE {{
  ?item wdt:P648 ?olid .
  FILTER(REGEX(?olid, "^OL[0-9]+A$"))
}} ORDER BY ?item ?olid LIMIT {limit} OFFSET {offset}
"""
SERIES_DETAILS = """
SELECT ?series ?label ?alias ?parent WHERE {{
  VALUES ?series {{ {values} }}
  OPTIONAL {{ ?series rdfs:label ?label . FILTER(LANG(?label) = "en") }}
  OPTIONAL {{ ?series skos:altLabel ?alias . FILTER(LANG(?alias) = "en") }}
  OPTIONAL {{ {{ ?series wdt:P179 ?parent }} UNION {{ ?series wdt:P361 ?parent }} }}
}}
"""
AUTHOR_NAMES = """
SELECT ?item ?name WHERE {{
  VALUES ?item {{ {values} }}
  {{ ?item rdfs:label ?name }} UNION {{ ?item skos:altLabel ?name }}
  FILTER(LANG(?name) IN ("en", "mul", "zh", "ja", "ko", "ru"))
}}
"""
_MAX_PARENT_DEPTH = 5


class WikidataError(RuntimeError):
    pass


def qid(uri: str) -> str:
    return uri.rsplit("/", 1)[-1]


def sparql(client: httpx.Client, url: str, query: str, *, sleep: Callable[[float], None],
           attempts: int = 5) -> list[dict[str, str]]:
    def attempt() -> list[dict[str, str]]:
        response = client.post(url, data={"query": query}, timeout=120,
                               headers={"Accept": "application/sparql-results+json", "User-Agent": USER_AGENT})
        check_status(response)
        try:
            bindings = response.json()["results"]["bindings"]
        except (ValueError, KeyError) as exc:
            raise RetryableError(f"unreadable SPARQL response: {exc}") from exc
        return [{k: v["value"] for k, v in b.items()} for b in bindings]

    return with_retries(attempt, attempts=attempts, sleep=sleep,
                        give_up=lambda exc: WikidataError(f"SPARQL page failed: {exc}"))


def paged(client: httpx.Client, url: str, template: str, *, sleep: Callable[[float], None],
          page_size: int = 10_000) -> Iterator[dict[str, str]]:
    offset = 0
    while True:
        rows = sparql(client, url, template.format(limit=page_size, offset=offset), sleep=sleep)
        yield from rows
        if len(rows) < page_size:
            return
        offset += page_size


def _batches(values: Iterable[str], size: int) -> Iterator[list[str]]:
    batch: list[str] = []
    for value in sorted(values):
        batch.append(value)
        if len(batch) == size:
            yield batch
            batch = []
    if batch:
        yield batch


def fetch_memberships(client, url, *, sleep, page_size=10_000) -> list[tuple[WdMembership, str]]:
    """``(membership, ol_id)`` pairs; ``ol_id`` is an OL work or edition id."""
    return [
        (WdMembership(qid(r["item"]), qid(r["series"]), r.get("ordinal")), r["olid"])
        for r in paged(client, url, MEMBERSHIPS, sleep=sleep, page_size=page_size)
    ]


def fetch_series(client, url, series: Iterable[str], *, sleep, batch=200) -> dict[str, WdSeries]:
    """Labels, aliases and parents for ``series``, climbing parents to depth 5."""
    found: dict[str, dict] = {}
    frontier = set(series)
    for _ in range(_MAX_PARENT_DEPTH + 1):
        frontier -= set(found)
        if not frontier:
            break
        for chunk in _batches(frontier, batch):
            values = " ".join(f"wd:{q}" for q in chunk)
            for q in chunk:
                found.setdefault(q, {"label": None, "aliases": set(), "parents": set()})
            for r in sparql(client, url, SERIES_DETAILS.format(values=values), sleep=sleep):
                entry = found[qid(r["series"])]
                entry["label"] = entry["label"] or r.get("label")
                if r.get("alias"):
                    entry["aliases"].add(r["alias"])
                if r.get("parent"):
                    entry["parents"].add(qid(r["parent"]))
        frontier = {p for e in found.values() for p in e["parents"]}
    return {
        q: WdSeries(q, e["label"], tuple(sorted(e["aliases"])), tuple(sorted(e["parents"])))
        for q, e in found.items()
    }


def fetch_author_ids(client, url, *, sleep, page_size=10_000) -> list[tuple[str, str]]:
    return [(qid(r["item"]), r["olid"]) for r in paged(client, url, AUTHOR_IDS, sleep=sleep, page_size=page_size)]


def fetch_author_names(client, url, items: Iterable[str], *, sleep, batch=200) -> list[tuple[str, str]]:
    names: set[tuple[str, str]] = set()
    for chunk in _batches(set(items), batch):
        values = " ".join(f"wd:{q}" for q in chunk)
        for r in sparql(client, url, AUTHOR_NAMES.format(values=values), sleep=sleep):
            names.add((qid(r["item"]), r["name"]))
    return sorted(names)
```

- [ ] **Step 4: Run the test**

Run: `cd pipeline && .venv/bin/python -m pytest tests/test_wikidata.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add pipeline/group/types.py pipeline/sources/wikidata.py pipeline/tests/test_wikidata.py
git commit -m "feat(pipeline): Wikidata series, ordinals, nesting and author ids over SPARQL"
```

---

### Task 9: The fetch stage and the fixture world

**Files:**
- Create: `pipeline/sources/load_raw.py`, `pipeline/sources/ol_records.py`, `pipeline/stages/fetch.py`
- Create: `pipeline/tests/fixtures/world.py`, `pipeline/tests/conftest.py`
- Test: `pipeline/tests/test_stage_fetch.py`

**Interfaces:**
- Consumes: Tasks 2, 6, 7, 8.
- Produces (`load_raw`): `resolver(redirects) -> Callable[[str], str]`; `load_redirects(con, dump, table, suffix) -> dict`; `load_popularity(con, ratings, reading_log, resolve) -> set[str]`; `load_entities(con, dump, table, type_, suffix, ids)`; `DuckSink(con, table="raw_editions")`.
- Produces (`ol_records`): `year_of(text) -> int | None`, `author_ids(record) -> list[str]`, `strings(value) -> list[str]`, `text(value) -> str | None`.
- Produces (`stages.fetch`): `TABLES` and `run(ctx)`, writing `raw_popularity(ol_id, ratings_count, readinglog_count)`, `raw_work_redirects(from_ol, to_ol)`, `raw_work_aliases(from_ol, to_ol)`, `raw_editions` (EDITION_SCHEMA), `raw_edition_counts(ol_id, edition_count)`, `raw_works(ol_id, json)`, `raw_author_redirects`, `raw_authors(ol_id, json)`, `wd_memberships(item, series, ordinal, ol_id)`, `wd_series(qid, label, aliases, parents)`, `wd_author_ids(qid, ol_author_id)`, `wd_author_names(qid, name)`, `sources(name, url, retrieved, size, sha256)`.
- Produces (tests): `world.DUMPS`, `world.SPARQL`, `world.GOLDEN`, `world.serve(router)`; `conftest.make_ctx(tmp_path, *, version="2026.10.1", releases=None)` and the `world_ctx` fixture.

The read set is every work someone rated or shelved plus every work Wikidata links, resolved through OL redirects; editions linked by Wikidata pull their works in too. The fixture world is shared by every later stage test and the end-to-end test — read its docstring: each work in it exists to exercise one rule.

- [ ] **Step 1: Write the fixture world, the conftest and the failing test**

`pipeline/tests/fixtures/world.py`:

```python
"""A tiny catalog that exercises every grouping rule, served over respx.

ASOIAF has three Wikidata members (one linked through an edition) and a
fourth found only in an edition's series string; Remembrance of Earth's Past
spans two spellings of its author; Red Rising needs positions to fix Dark
Age's wrong year, an adaptation to keep out, a duplicate record to merge and
a redirect to follow; Penguin Classics is an imprint; The Lord of the Rings
sits under a universe too thin to become its room.
"""

from __future__ import annotations

from urllib.parse import parse_qs

import httpx

from pipeline.tests.fixtures.dumps import dump_line, edition_line, entity, gz, sparql_json

DUMPS = {name: f"https://dumps.test/ol_dump_{name}_2026-08-31.txt.gz"
         for name in ("ratings", "reading_log", "works", "authors", "editions")}
SPARQL = "https://sparql.test/sparql"

AUTHORS = {
    "OL1A": {"name": "George R. R. Martin"},
    "OL2A": {"name": "Cixin Liu", "alternate_names": ["Liu Cixin", "刘慈欣"]},
    "OL3A": {"name": "刘慈欣"},
    "OL4A": {"name": "Pierce Brown"},
    "OL5A": {"name": "J. R. R. Tolkien", "remote_ids": {"wikidata": "Q892"}},
    "OL6A": {"name": "Rik Hoskin"},
    **{f"OL{i}A": {"name": f"Classic Author {i}"} for i in range(7, 11)},
}
# ol_id: (title, author ids, subjects, first_publish_date)
WORKS = {
    "OL10W": ("A Game of Thrones", ["OL1A"], [], "1996"),
    "OL11W": ("A Clash of Kings", ["OL1A"], [], "1998"),
    "OL12W": ("A Storm of Swords", ["OL1A"], [], "2000"),
    "OL13W": ("A Feast for Crows", ["OL1A"], [], "2005"),
    "OL20W": ("The Three-Body Problem", ["OL2A"], ["series:Remembrance of Earth's Past"], "2006"),
    "OL21W": ("The Dark Forest", ["OL3A"], [], "2008"),
    "OL22W": ("Death's End", ["OL3A"], [], "2010"),
    "OL30W": ("Red Rising", ["OL4A"], ["franchise:Red Rising"], "2014"),
    "OL31W": ("Golden Son", ["OL4A"], ["franchise:Red Rising"], "2015"),
    "OL32W": ("Morning Star", ["OL4A"], ["franchise:Red Rising"], "2016"),
    "OL33W": ("Iron Gold", ["OL4A"], ["franchise:Red Rising"], "2018"),
    "OL34W": ("Dark Age", ["OL4A"], ["franchise:Red Rising"], "2015"),
    "OL35W": ("Red Rising: Sons of Ares", ["OL6A"], ["franchise:Red Rising"], "2017"),
    "OL36W": ("Red Rising", ["OL4A"], [], None),
    "OL40W": ("Red Rising 2027 Wall Calendar", ["OL4A"], [], "2026"),
    "OL41W": ("Le Petit Livre", ["OL4A"], [], "2020"),
    "OL42W": ("A Pamphlet", ["OL4A"], [], "2020"),
    **{f"OL5{i}W": (f"Classic {i}", [f"OL{7 + i}A"], ["series:Penguin Classics"], "1900") for i in range(4)},
    "OL60W": ("The Fellowship of the Ring", ["OL5A"], [], "1954"),
    "OL61W": ("The Two Towers", ["OL5A"], [], "1954"),
    "OL62W": ("The Return of the King", ["OL5A"], [], "1955"),
    "OL63W": ("The Hobbit", ["OL5A"], [], "1937"),
    "OL70W": ("Nobody Read This", ["OL4A"], [], "2001"),
}
REDIRECTS = {"OL99W": "OL30W"}
# edition id: (work, title, extra fields)
EDITIONS = {
    "OL100M": ("OL10W", "A Game of Thrones", {}),
    "OL110M": ("OL11W", "A Clash of Kings", {}),
    "OL120M": ("OL12W", "A Storm of Swords", {}),
    "OL130M": ("OL13W", "A Feast for Crows", {"series": ["A Song of Ice and Fire ; 4"]}),
    "OL200M": ("OL20W", "The Three-Body Problem", {"series": ["Remembrance of Earth's Past ; 1"]}),
    "OL210M": ("OL21W", "The Dark Forest (Remembrance of Earth's Past Series Book 2)", {}),
    "OL220M": ("OL22W", "Death's End", {"series": ["Remembrance of Earth's Past, #3"]}),
    **{f"OL3{i}0M": (f"OL3{i}W", WORKS[f"OL3{i}W"][0], {"series": [f"Red Rising Saga ; {i + 1}"]}) for i in range(5)},
    "OL350M": ("OL35W", "Red Rising: Sons of Ares", {}),
    "OL360M": ("OL36W", "Red Rising", {}),
    "OL400M": ("OL40W", "Red Rising 2027 Wall Calendar", {}),
    "OL420M": ("OL42W", "A Pamphlet", {"number_of_pages": 20}),
    **{f"OL5{i}0M": (f"OL5{i}W", f"Classic {i}", {}) for i in range(4)},
    "OL600M": ("OL60W", "The Fellowship of the Ring", {}),
    "OL610M": ("OL61W", "The Two Towers", {}),
    "OL620M": ("OL62W", "The Return of the King", {}),
    "OL630M": ("OL63W", "The Hobbit", {}),
}
FRENCH = {"OL410M": ("OL41W", "Le Petit Livre"), "OL101M": ("OL10W", "Le Trône de fer")}
# Every selected work is shelved once; Red Rising is the popular one, and two
# ratings arrive under its redirected id.
LOGS = [w for w in WORKS if w != "OL70W"] + ["OL30W"] * 4
RATINGS = ["OL99W", "OL99W"]

MEMBERSHIPS = [  # (item, OL id, series, ordinal)
    ("Q1001", "OL10W", "Q45875", "1"),
    ("Q1002", "OL11W", "Q45875", "2"),
    ("Q1003", "OL120M", "Q45875", "3"),
    ("Q2001", "OL60W", "Q15228", "1"),
    ("Q2002", "OL61W", "Q15228", "2"),
    ("Q2003", "OL62W", "Q15228", "3"),
]
SERIES = {
    "Q45875": {"label": "A Song of Ice and Fire", "aliases": ["ASOIAF"], "parents": []},
    "Q15228": {"label": "The Lord of the Rings", "aliases": [], "parents": ["Q81"]},
    "Q81": {"label": "Middle-earth legendarium", "aliases": [], "parents": []},
}
AUTHOR_LINKS = [("Q892", "OL5A"), ("Q5", "OL2A")]
AUTHOR_NAMES = [("Q5", "刘慈欣"), ("Q892", "J.R.R. Tolkien")]

GOLDEN = """
- name: A Song of Ice and Fire
  members: [OL10W, OL11W, OL12W, OL13W]
- name: Remembrance of Earth's Past
  members: [OL20W, OL21W, OL22W]
- name: Red Rising
  members: [OL30W, OL31W, OL32W, OL33W, OL34W]
- name: The Lord of the Rings
  members: [OL60W, OL61W, OL62W]
"""


def dumps() -> dict[str, bytes]:
    works = [dump_line("/type/work", f"/works/{ol}", {
        "key": f"/works/{ol}", "title": title, "subjects": subjects,
        "authors": [{"author": {"key": f"/authors/{a}"}, "type": {"key": "/type/author_role"}} for a in authors],
        **({"first_publish_date": year} if year else {}), "covers": [int(ol[2:-1]) * 10],
    }) for ol, (title, authors, subjects, year) in WORKS.items()]
    works += [dump_line("/type/redirect", f"/works/{a}", {"location": f"/works/{b}"}) for a, b in REDIRECTS.items()]
    authors = [dump_line("/type/author", f"/authors/{ol}", {"key": f"/authors/{ol}", **rec}) for ol, rec in AUTHORS.items()]
    editions = [edition_line(ol, work, title=title, **{
        "number_of_pages": 300, "isbn_13": [f"97800000{ol[2:-1]:0>5}"], "covers": [int(ol[2:-1])], **extra,
    }) for ol, (work, title, extra) in EDITIONS.items()]
    editions += [edition_line(ol, work, languages=("fre",), title=title) for ol, (work, title) in FRENCH.items()]
    log = lambda ids: [f"/works/{w}\t\twant-to-read\t2026-01-01" for w in ids]  # noqa: E731
    return {
        "works": gz(works), "authors": gz(authors), "editions": gz(editions),
        "reading_log": gz(log(LOGS)), "ratings": gz(log(RATINGS)),
    }


def _sparql(request: httpx.Request) -> httpx.Response:
    query = parse_qs(request.content.decode())["query"][0]
    if "p:P179" in query:
        rows = [{"item": entity(i), "olid": ol, "series": entity(s), "ordinal": o} for i, ol, s, o in MEMBERSHIPS]
    elif "[0-9]+A$" in query:
        rows = [{"item": entity(q), "olid": ol} for q, ol in AUTHOR_LINKS]
    elif "VALUES ?series" in query:
        rows = []
        for q, s in SERIES.items():
            if f"wd:{q} " not in query + " ":
                continue
            rows.append({"series": entity(q), "label": s["label"]})
            rows += [{"series": entity(q), "alias": a} for a in s["aliases"]]
            rows += [{"series": entity(q), "parent": entity(p)} for p in s["parents"]]
    elif "VALUES ?item" in query:
        rows = [{"item": entity(q), "name": n} for q, n in AUTHOR_NAMES if f"wd:{q} " in query + " "]
    else:
        raise AssertionError(f"unexpected query: {query}")
    if "OFFSET" in query and int(query.rsplit("OFFSET", 1)[1]) > 0:
        rows = []
    return httpx.Response(200, json=sparql_json(rows))


def serve(router) -> None:
    """Install the world's routes on a respx router."""
    data = dumps()
    for name, url in DUMPS.items():
        router.get(url).mock(return_value=httpx.Response(200, content=data[name]))
    router.post(SPARQL).mock(side_effect=_sparql)
```

`pipeline/tests/conftest.py`:

```python
import duckdb
import pytest
import respx

from pipeline.config import PIPELINE_DIR, BuildContext
from pipeline.tests.fixtures import world


def make_ctx(tmp_path, *, version="2026.10.1", releases=None) -> BuildContext:
    golden = tmp_path / "golden.yaml"
    golden.write_text(world.GOLDEN, encoding="utf-8")
    overrides = tmp_path / "overrides"
    overrides.mkdir(exist_ok=True)
    return BuildContext(
        build_dir=tmp_path / "build", con=duckdb.connect(), ol_dumps=dict(world.DUMPS),
        sparql_url=world.SPARQL, rules_dir=PIPELINE_DIR / "rules", overrides_dir=overrides,
        golden_path=golden, releases_dir=releases or tmp_path / "releases", version=version,
        sleep=lambda s: None,
    )


@pytest.fixture
def world_ctx(tmp_path):
    """A build context whose sources are the fixture world."""
    with respx.mock(assert_all_called=False) as router:
        world.serve(router)
        yield make_ctx(tmp_path)
```

`pipeline/tests/test_stage_fetch.py`:

```python
from pipeline.db import table_names
from pipeline.stages import fetch


def rows(con, sql):
    return con.execute(sql).fetchall()


def test_fetch_loads_the_read_set_and_its_sources(world_ctx):
    fetch.run(world_ctx)
    con = world_ctx.con
    assert set(fetch.TABLES) <= table_names(con)
    works = {w for (w,) in rows(con, "SELECT ol_id FROM raw_works")}
    assert "OL70W" not in works  # nobody read it and Wikidata does not know it
    assert {"OL10W", "OL12W", "OL30W", "OL41W", "OL63W"} <= works
    # Two ratings under the redirected id count toward the survivor.
    assert rows(con, "SELECT ratings_count, readinglog_count FROM raw_popularity WHERE ol_id = 'OL30W'") == [(2, 5)]
    assert rows(con, "SELECT from_ol, to_ol FROM raw_work_aliases") == [("OL99W", "OL30W")]
    assert rows(con, "SELECT edition_count FROM raw_edition_counts WHERE ol_id = 'OL10W'") == [(2,)]
    authors = {a for (a,) in rows(con, "SELECT ol_id FROM raw_authors")}
    assert {"OL1A", "OL2A", "OL3A", "OL5A"} <= authors
    assert rows(con, "SELECT name FROM wd_author_names WHERE qid = 'Q5'") == [("刘慈欣",)]
    assert rows(con, "SELECT parents FROM wd_series WHERE qid = 'Q15228'") == [(["Q81"],)]
    assert sorted(n for (n,) in rows(con, "SELECT name FROM sources")) == [
        "authors", "editions", "ratings", "reading_log", "wikidata", "works"]


def test_fetch_never_writes_the_editions_dump(world_ctx):
    fetch.run(world_ctx)
    assert not any("editions" in p.name for p in world_ctx.raw_dir.iterdir())
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd pipeline && .venv/bin/python -m pytest tests/test_stage_fetch.py -v`
Expected: FAIL — `No module named 'pipeline.stages.fetch'`.

- [ ] **Step 3: Implement**

`pipeline/sources/ol_records.py`:

```python
"""Reading fields out of Open Library JSON records, defensively.

Dump records span twenty years of schema drift: authors appear as
``{"author": {"key": …}}`` or bare ``{"key": …}``, dates are free text.
"""

from __future__ import annotations

import re

_YEAR = re.compile(r"\b(1[0-9]{3}|20[0-9]{2})\b")
_AUTHOR_KEY = re.compile(r"OL[0-9]+A")


def year_of(text) -> int | None:
    match = _YEAR.search(text) if isinstance(text, str) else None
    return int(match.group(1)) if match else None


def author_ids(record: dict) -> list[str]:
    """The work's author ids, in listed order, without duplicates."""
    found: list[str] = []
    for entry in record.get("authors") or []:
        if not isinstance(entry, dict):
            continue
        ref = entry.get("author", entry)
        key = ref.get("key") if isinstance(ref, dict) else None
        match = _AUTHOR_KEY.search(key) if isinstance(key, str) else None
        if match and match.group() not in found:
            found.append(match.group())
    return found


def strings(value) -> list[str]:
    return [v for v in value if isinstance(v, str)] if isinstance(value, list) else []


def text(value) -> str | None:
    return value.strip() or None if isinstance(value, str) else None
```

`pipeline/sources/load_raw.py`:

```python
"""Load the downloaded dumps into ``tmp_raw_*`` tables with DuckDB.

DuckDB reads the gzipped TSVs directly, so the works and authors dumps are
filtered in SQL rather than parsed line by line in Python.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Iterable, Mapping

import duckdb
import pyarrow as pa

from pipeline.db import TMP_PREFIX, sql_path
from pipeline.sources.editions import EDITION_SCHEMA

# The OL entity dumps: type, key, revision, last_modified, JSON. No quoting:
# the JSON column is full of double quotes.
_ENTITY_TSV = (
    "delim='\t', header=false, quote='', escape='', compression='gzip', "
    "max_line_size=20000000, "
    "columns={'type': 'VARCHAR', 'key': 'VARCHAR', 'revision': 'VARCHAR', "
    "'modified': 'VARCHAR', 'json': 'VARCHAR'}"
)
# Ratings and reading-log dumps: work key, edition key, value, date.
_LOG_TSV = (
    "delim='\t', header=false, quote='', escape='', compression='gzip', null_padding=true, "
    "columns={'work': 'VARCHAR', 'edition': 'VARCHAR', 'value': 'VARCHAR', 'date': 'VARCHAR'}"
)
_MAX_HOPS = 5


def resolver(redirects: Mapping[str, str]) -> Callable[[str], str]:
    """Follow OL redirects (merged records) to the surviving id."""
    def resolve(ol_id: str) -> str:
        seen = {ol_id}
        for _ in range(_MAX_HOPS):
            target = redirects.get(ol_id)
            if target is None or target in seen:
                break
            ol_id = target
            seen.add(target)
        return ol_id
    return resolve


def load_redirects(con: duckdb.DuckDBPyConnection, dump: Path, table: str, suffix: str) -> dict[str, str]:
    """``tmp_<table>(from_ol, to_ol)`` for every redirect record; returned as a dict."""
    pattern = f"OL[0-9]+{suffix}"
    con.execute(f"""
        CREATE OR REPLACE TABLE {TMP_PREFIX}{table} AS
        SELECT regexp_extract(key, '{pattern}') AS from_ol,
               regexp_extract(json_extract_string(json, '$.location'), '{pattern}') AS to_ol
        FROM read_csv({sql_path(dump)}, {_ENTITY_TSV})
        WHERE type = '/type/redirect' AND to_ol <> '' AND from_ol <> ''
    """)
    return dict(con.execute(f"SELECT from_ol, to_ol FROM {TMP_PREFIX}{table}").fetchall())


def load_popularity(con: duckdb.DuckDBPyConnection, ratings: Path, reading_log: Path,
                    resolve: Callable[[str], str]) -> set[str]:
    """``tmp_raw_popularity(ol_id, ratings_count, readinglog_count)``, keyed by surviving id.

    Returns the raw ids seen, redirected or not — the read set's seed.
    """
    raw = con.execute(f"""
        SELECT ol_id, sum(r)::INTEGER, sum(l)::INTEGER FROM (
            SELECT regexp_extract(work, 'OL[0-9]+W') AS ol_id, 1 AS r, 0 AS l
            FROM read_csv({sql_path(ratings)}, {_LOG_TSV})
            UNION ALL
            SELECT regexp_extract(work, 'OL[0-9]+W'), 0, 1
            FROM read_csv({sql_path(reading_log)}, {_LOG_TSV})
        ) WHERE ol_id <> '' GROUP BY ol_id
    """).fetchall()
    totals: dict[str, list[int]] = {}
    for ol_id, ratings_count, logs in raw:
        entry = totals.setdefault(resolve(ol_id), [0, 0])
        entry[0] += ratings_count
        entry[1] += logs
    ids = sorted(totals)
    con.register("_pop", pa.table({
        "ol_id": ids,
        "ratings_count": pa.array([totals[i][0] for i in ids], pa.int32()),
        "readinglog_count": pa.array([totals[i][1] for i in ids], pa.int32()),
    }))
    con.execute(f"CREATE OR REPLACE TABLE {TMP_PREFIX}raw_popularity AS SELECT * FROM _pop")
    con.unregister("_pop")
    return {row[0] for row in raw}


def load_entities(con: duckdb.DuckDBPyConnection, dump: Path, table: str, type_: str,
                  suffix: str, ids: Iterable[str]) -> None:
    """``tmp_<table>(ol_id, json)`` for the records of ``type_`` whose id is in ``ids``."""
    con.register("_ids", pa.table({"ol_id": sorted(set(ids))}))
    con.execute(f"""
        CREATE OR REPLACE TABLE {TMP_PREFIX}{table} AS
        SELECT regexp_extract(key, 'OL[0-9]+{suffix}') AS ol_id, json
        FROM read_csv({sql_path(dump)}, {_ENTITY_TSV})
        WHERE type = '{type_}' AND regexp_extract(key, 'OL[0-9]+{suffix}') IN (SELECT ol_id FROM _ids)
    """)
    con.unregister("_ids")


class DuckSink:
    """Where the editions stream lands: ``tmp_raw_editions``."""

    def __init__(self, con: duckdb.DuckDBPyConnection, table: str = "raw_editions") -> None:
        self.con, self.table = con, f"{TMP_PREFIX}{table}"

    def reset(self) -> None:
        self.con.register("_empty", EDITION_SCHEMA.empty_table())
        self.con.execute(f"CREATE OR REPLACE TABLE {self.table} AS SELECT * FROM _empty")
        self.con.unregister("_empty")

    def write(self, batch: pa.Table) -> None:
        self.con.register("_batch", batch)
        self.con.execute(f"INSERT INTO {self.table} SELECT * FROM _batch")
        self.con.unregister("_batch")
```

`pipeline/stages/fetch.py`:

```python
"""fetch (spec §4.1): download, pull Wikidata, stream editions, load raw tables."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

import httpx
import pyarrow as pa

from pipeline.config import USER_AGENT, BuildContext
from pipeline.db import TMP_PREFIX, swap_in, write_table
from pipeline.sources import load_raw, wikidata
from pipeline.sources.editions import stream_editions
from pipeline.sources.ol_dumps import download
from pipeline.sources.records import SourceRecord

TABLES = (
    "raw_popularity", "raw_work_redirects", "raw_work_aliases", "raw_editions",
    "raw_edition_counts", "raw_works", "raw_author_redirects", "raw_authors",
    "wd_memberships", "wd_series", "wd_author_ids", "wd_author_names", "sources",
)


def _wikidata_record(url: str, *parts) -> SourceRecord:
    blob = json.dumps(parts, sort_keys=True, default=list).encode()
    stamp = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    return SourceRecord("wikidata", url, stamp, len(blob), hashlib.sha256(blob).hexdigest())


def run(ctx: BuildContext) -> None:
    con, raw = ctx.con, ctx.raw_dir
    raw.mkdir(parents=True, exist_ok=True)
    timeout = httpx.Timeout(60.0, read=300.0)
    with httpx.Client(timeout=timeout, headers={"User-Agent": USER_AGENT}) as client:
        records = [
            download(client, name, ctx.ol_dumps[name], raw / f"{name}.txt.gz", sleep=ctx.sleep)
            for name in ("ratings", "reading_log", "works", "authors")
        ]

        memberships = wikidata.fetch_memberships(client, ctx.sparql_url, sleep=ctx.sleep)
        series = wikidata.fetch_series(client, ctx.sparql_url, {m.series for m, _ in memberships}, sleep=ctx.sleep)
        author_ids = wikidata.fetch_author_ids(client, ctx.sparql_url, sleep=ctx.sleep)

        # The read set: works someone has rated or shelved, plus Wikidata's books.
        redirects = load_raw.load_redirects(con, raw / "works.txt.gz", "raw_work_redirects", "W")
        resolve = load_raw.resolver(redirects)
        seen = load_raw.load_popularity(con, raw / "ratings.txt.gz", raw / "reading_log.txt.gz", resolve)
        wd_works = {ol for _, ol in memberships if ol.endswith("W")}
        wd_editions = {ol for _, ol in memberships if ol.endswith("M")}
        candidates = {resolve(ol) for ol in seen | wd_works}
        aliases = sorted((ol, resolve(ol)) for ol in seen | wd_works if resolve(ol) != ol)
        write_table(con, "raw_work_aliases", pa.table({
            "from_ol": [a for a, _ in aliases], "to_ol": [b for _, b in aliases]}, schema=pa.schema(
            [("from_ol", pa.string()), ("to_ol", pa.string())])))

        resolved = {k: resolve(k) for k in redirects}
        edition_record, counts = stream_editions(
            client, ctx.ol_dumps["editions"], candidates, wd_editions,
            load_raw.DuckSink(con), resolve=resolved, sleep=ctx.sleep)
        records.append(edition_record)
        ids = sorted(counts)
        write_table(con, "raw_edition_counts", pa.table({
            "ol_id": pa.array(ids, pa.string()), "edition_count": pa.array([counts[i] for i in ids], pa.int32())}))
        candidates |= {w for (w,) in con.execute(
            f"SELECT DISTINCT work_ol_id FROM {TMP_PREFIX}raw_editions "
            f"WHERE work_ol_id IS NOT NULL AND list_contains(?, ol_id)", [sorted(wd_editions)]).fetchall()}

        load_raw.load_entities(con, raw / "works.txt.gz", "raw_works", "/type/work", "W", candidates)
        author_redirects = load_raw.load_redirects(con, raw / "authors.txt.gz", "raw_author_redirects", "A")
        resolve_author = load_raw.resolver(author_redirects)
        referenced = {resolve_author(a) for (a,) in con.execute(
            f"SELECT DISTINCT unnest(regexp_extract_all(json, 'OL[0-9]+A')) FROM {TMP_PREFIX}raw_works").fetchall()}
        load_raw.load_entities(con, raw / "authors.txt.gz", "raw_authors", "/type/author", "A", referenced)

        wd_author_items = sorted({q for q, ol in author_ids if resolve_author(ol) in referenced})
        names = wikidata.fetch_author_names(client, ctx.sparql_url, wd_author_items, sleep=ctx.sleep)
        records.append(_wikidata_record(ctx.sparql_url, sorted((m.item, m.series, m.ordinal or "", ol) for m, ol in memberships),
                                        sorted(series), author_ids, names))

    write_table(con, "wd_memberships", pa.table({
        "item": pa.array([m.item for m, _ in memberships], pa.string()),
        "series": pa.array([m.series for m, _ in memberships], pa.string()),
        "ordinal": pa.array([m.ordinal for m, _ in memberships], pa.string()),
        "ol_id": pa.array([ol for _, ol in memberships], pa.string()),
    }))
    keys = sorted(series)
    write_table(con, "wd_series", pa.table({
        "qid": pa.array(keys, pa.string()),
        "label": pa.array([series[k].label for k in keys], pa.string()),
        "aliases": pa.array([list(series[k].aliases) for k in keys], pa.list_(pa.string())),
        "parents": pa.array([list(series[k].parents) for k in keys], pa.list_(pa.string())),
    }))
    write_table(con, "wd_author_ids", pa.table({
        "qid": pa.array([q for q, _ in author_ids], pa.string()),
        "ol_author_id": pa.array([ol for _, ol in author_ids], pa.string())}))
    write_table(con, "wd_author_names", pa.table({
        "qid": pa.array([q for q, _ in names], pa.string()),
        "name": pa.array([n for _, n in names], pa.string())}))
    write_table(con, "sources", pa.Table.from_pylist([r.__dict__ for r in records], schema=pa.schema([
        ("name", pa.string()), ("url", pa.string()), ("retrieved", pa.string()),
        ("size", pa.int64()), ("sha256", pa.string())])))
    swap_in(con, TABLES)
```

- [ ] **Step 4: Run the test**

Run: `cd pipeline && .venv/bin/python -m pytest tests/test_stage_fetch.py -v`
Expected: PASS (2 tests). Two ratings under the redirected `OL99W` count toward `OL30W`.

- [ ] **Step 5: Commit**

```bash
git add pipeline/sources pipeline/stages/fetch.py pipeline/tests
git commit -m "feat(pipeline): fetch stage — downloads, Wikidata, editions stream, raw tables"
```

---

### Task 10: The select and extract stages

**Files:**
- Create: `pipeline/stages/select.py`, `pipeline/stages/extract.py`
- Test: `pipeline/tests/test_stage_select_extract.py`

**Interfaces:**
- Consumes: fetch's tables; `JunkRules`, `WorkForSelect`; `ol_records.*`; `db.iter_rows`; `_backend.canonical_key/classify_kind/display_title/join_subjects/normalize_isbn`.
- Produces (`select`): tables `selected(ol_id)` and `select_drops(ol_id, rule)` (`rule` = `not_english` or a junk reason).
- Produces (`extract`): `WORKS_SCHEMA`, `EDITIONS_SCHEMA`, `AUTHORS_SCHEMA`; `AuthorRow(name, alternate_names, wikidata)`; `author_row(record)`; `extract_work(ol_id, record, authors, resolve_author=…, popularity=(0, 0), edition_count=0, edition_years=()) -> dict`; `extract_edition(row) -> dict`; tables `works` (`ol_id, raw_title, title, subtitle, author, author_ids, first_publish_year, subjects, cover_id, ratings_count, readinglog_count, edition_count, canonical_key, kind`), `editions` (`ol_id, work_ol_id, title, subtitle, publisher, publish_year, isbn_13, page_count, cover_id, series`), `authors` (`ol_id, name, alternate_names, wikidata`).

`title` is `display_title` (what a reader sees); `raw_title` keeps the packaging because rung 4 reads series out of it. `canonical_key` uses the first author's name, as the app does.

- [ ] **Step 1: Write the failing test**

`pipeline/tests/test_stage_select_extract.py`:

```python
import pytest

from pipeline.stages import extract, fetch, select
from pipeline.stages.extract import AuthorRow, extract_work


@pytest.fixture
def selected(world_ctx):
    fetch.run(world_ctx)
    select.run(world_ctx)
    return world_ctx


def test_select_keeps_english_read_works_and_names_each_drop(selected):
    con = selected.con
    kept = {w for (w,) in con.execute("SELECT ol_id FROM selected").fetchall()}
    drops = dict(con.execute("SELECT ol_id, rule FROM select_drops").fetchall())
    assert drops == {"OL40W": "calendar", "OL41W": "not_english", "OL42W": "short"}
    assert {"OL10W", "OL30W", "OL36W", "OL50W", "OL63W"} <= kept


def test_extract_normalises_works_editions_and_authors(selected):
    extract.run(selected)
    con = selected.con
    row = con.execute("SELECT title, author, author_ids, first_publish_year, readinglog_count, ratings_count, "
                      "edition_count, subjects FROM works WHERE ol_id = 'OL30W'").fetchone()
    assert row == ("Red Rising", "Pierce Brown", ["OL4A"], 2014, 5, 2, 1, "franchise:Red Rising")
    assert con.execute("SELECT count(*) FROM editions WHERE work_ol_id = 'OL10W'").fetchone() == (1,)  # French one left out
    assert con.execute("SELECT series FROM editions WHERE ol_id = 'OL340M'").fetchone() == (["Red Rising Saga ; 5"],)
    assert con.execute("SELECT alternate_names FROM authors WHERE ol_id = 'OL2A'").fetchone() == (["Liu Cixin", "刘慈欣"],)


def test_extract_work_rules():
    authors = {"OL2A": AuthorRow("Cixin Liu", (), None)}
    record = {"title": "The Three-Body Problem (Deluxe Edition)", "authors": [{"key": "/authors/OL9A"}],
              "subjects": ["series:Remembrance of Earth's Past", "Fiction"], "covers": [-1, 42]}
    work = extract_work("OL20W", record, authors, resolve_author={"OL9A": "OL2A"}.get, edition_years=[2014, 2008])
    assert work["title"] == "The Three-Body Problem"
    assert work["raw_title"] == "The Three-Body Problem (Deluxe Edition)"
    assert work["author_ids"] == ["OL2A"]
    assert work["first_publish_year"] == 2008
    assert work["subjects"] == "series:Remembrance of Earth's Past\nFiction"
    assert work["cover_id"] == 42
    assert work["canonical_key"] == "the three body problem\x1fcixin liu"


def test_extract_work_without_known_authors():
    work = extract_work("OL1W", {"title": "Box Set: Books 1-3"}, {})
    assert work["author"] == "Unknown"
    assert work["kind"] == "collection"
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd pipeline && .venv/bin/python -m pytest tests/test_stage_select_extract.py -v`
Expected: FAIL — modules not found.

- [ ] **Step 3: Implement**

`pipeline/stages/select.py`:

```python
"""select (spec §4.2): keep read works that have an English edition and are not junk."""

from __future__ import annotations

import json

import pyarrow as pa

from pipeline.config import BuildContext
from pipeline.db import iter_rows, swap_in, write_table
from pipeline.select_rules import JunkRules, WorkForSelect
from pipeline.sources.ol_records import author_ids, strings, text


def run(ctx: BuildContext) -> None:
    con = ctx.con
    rules = JunkRules.load(ctx.rules_dir / "junk.yaml")
    english = {
        work: (pages, tuple(p for p in publishers if p))
        for work, pages, publishers in con.execute("""
            SELECT work_ol_id, max(number_of_pages), flatten(list(publishers))
            FROM raw_editions WHERE is_english AND work_ol_id IS NOT NULL GROUP BY work_ol_id
        """).fetchall()
    }
    kept: list[str] = []
    dropped: list[tuple[str, str]] = []
    for ol_id, blob in iter_rows(con, "SELECT ol_id, json FROM raw_works ORDER BY ol_id"):
        if ol_id not in english:
            dropped.append((ol_id, "not_english"))
            continue
        record = json.loads(blob)
        pages, publishers = english[ol_id]
        reason = rules.reason(WorkForSelect(
            ol_id=ol_id, title=text(record.get("title")) or "", subjects=tuple(strings(record.get("subjects"))),
            author_ids=tuple(author_ids(record)), max_pages=pages, publishers=publishers))
        if reason is None:
            kept.append(ol_id)
        else:
            dropped.append((ol_id, reason))
    write_table(con, "selected", pa.table({"ol_id": pa.array(kept, pa.string())}))
    write_table(con, "select_drops", pa.table({
        "ol_id": pa.array([d[0] for d in dropped], pa.string()),
        "rule": pa.array([d[1] for d in dropped], pa.string())}))
    swap_in(con, ["selected", "select_drops"])
```

`pipeline/stages/extract.py`:

```python
"""extract (spec §4.3): normalise selected works, their English editions and authors."""

from __future__ import annotations

import json
from typing import Callable, Iterable, Mapping, NamedTuple

import pyarrow as pa

from pipeline._backend import canonical_key, classify_kind, display_title, join_subjects, normalize_isbn
from pipeline.config import BuildContext
from pipeline.db import iter_rows, swap_in, write_table
from pipeline.sources.load_raw import resolver
from pipeline.sources.ol_records import author_ids, strings, text, year_of

WORKS_SCHEMA = pa.schema([
    ("ol_id", pa.string()), ("raw_title", pa.string()), ("title", pa.string()), ("subtitle", pa.string()),
    ("author", pa.string()), ("author_ids", pa.list_(pa.string())), ("first_publish_year", pa.int32()),
    ("subjects", pa.string()), ("cover_id", pa.int64()), ("ratings_count", pa.int32()),
    ("readinglog_count", pa.int32()), ("edition_count", pa.int32()), ("canonical_key", pa.string()),
    ("kind", pa.string()),
])
EDITIONS_SCHEMA = pa.schema([
    ("ol_id", pa.string()), ("work_ol_id", pa.string()), ("title", pa.string()), ("subtitle", pa.string()),
    ("publisher", pa.string()), ("publish_year", pa.int32()), ("isbn_13", pa.string()),
    ("page_count", pa.int32()), ("cover_id", pa.int64()), ("series", pa.list_(pa.string())),
])
AUTHORS_SCHEMA = pa.schema([
    ("ol_id", pa.string()), ("name", pa.string()), ("alternate_names", pa.list_(pa.string())),
    ("wikidata", pa.string()),
])


class AuthorRow(NamedTuple):
    name: str
    alternate_names: tuple[str, ...]
    wikidata: str | None


def author_row(record: dict) -> AuthorRow:
    remote = record.get("remote_ids") if isinstance(record.get("remote_ids"), dict) else {}
    return AuthorRow(text(record.get("name")) or "", tuple(strings(record.get("alternate_names"))),
                     text(remote.get("wikidata")))


def extract_work(ol_id: str, record: dict, authors: Mapping[str, AuthorRow],
                 resolve_author: Callable[[str], str] = lambda a: a,
                 popularity: tuple[int, int] = (0, 0), edition_count: int = 0,
                 edition_years: Iterable[int] = ()) -> dict:
    raw_title = text(record.get("title")) or ""
    subtitle = text(record.get("subtitle"))
    ids: list[str] = []
    for a in author_ids(record):
        resolved = resolve_author(a)
        if resolved not in ids:
            ids.append(resolved)
    names = [authors[a].name for a in ids if a in authors and authors[a].name]
    title = display_title(raw_title) or raw_title or "Untitled"
    covers = [c for c in record.get("covers") or [] if isinstance(c, int) and c > 0]
    return {
        "ol_id": ol_id,
        "raw_title": raw_title,
        "title": title,
        "subtitle": subtitle,
        "author": ", ".join(names) or "Unknown",
        "author_ids": ids,
        "first_publish_year": year_of(record.get("first_publish_date")) or min(edition_years, default=None),
        "subjects": join_subjects(strings(record.get("subjects"))),
        "cover_id": covers[0] if covers else None,
        "ratings_count": popularity[0],
        "readinglog_count": popularity[1],
        "edition_count": edition_count,
        "canonical_key": canonical_key(title, names[0] if names else None),
        "kind": classify_kind(raw_title, subtitle),
    }


def extract_edition(row: dict) -> dict:
    isbn = next((n for n in map(normalize_isbn, [*row["isbn_13"], *row["isbn_10"]]) if n), None)
    return {
        "ol_id": row["ol_id"], "work_ol_id": row["work_ol_id"], "title": row["title"] or "",
        "subtitle": row["subtitle"], "publisher": row["publishers"][0] if row["publishers"] else None,
        "publish_year": year_of(row["publish_date"]), "isbn_13": isbn, "page_count": row["number_of_pages"],
        "cover_id": row["covers"][0] if row["covers"] else None, "series": row["series"],
    }


def run(ctx: BuildContext) -> None:
    con = ctx.con
    resolve_author = resolver(dict(con.execute("SELECT from_ol, to_ol FROM raw_author_redirects").fetchall()))
    raw_authors = {ol: author_row(json.loads(blob)) for ol, blob in iter_rows(con, "SELECT ol_id, json FROM raw_authors")}
    popularity = {ol: (r, l) for ol, r, l in con.execute(
        "SELECT ol_id, ratings_count, readinglog_count FROM raw_popularity").fetchall()}
    counts = dict(con.execute("SELECT ol_id, edition_count FROM raw_edition_counts").fetchall())

    cursor = con.execute("""
        SELECT e.* FROM raw_editions e JOIN selected s ON e.work_ol_id = s.ol_id
        WHERE e.is_english ORDER BY e.ol_id""")
    columns = [d[0] for d in cursor.description]
    editions = [extract_edition(dict(zip(columns, r))) for r in cursor.fetchall()]
    years: dict[str, list[int]] = {}
    for e in editions:
        if e["publish_year"]:
            years.setdefault(e["work_ol_id"], []).append(e["publish_year"])

    works = [
        extract_work(ol, json.loads(blob), raw_authors, resolve_author, popularity.get(ol, (0, 0)),
                     counts.get(ol, 0), years.get(ol, ()))
        for ol, blob in iter_rows(con, "SELECT w.ol_id, w.json FROM raw_works w JOIN selected s USING (ol_id) ORDER BY w.ol_id")
    ]
    used = sorted({a for w in works for a in w["author_ids"] if a in raw_authors})
    authors = [{"ol_id": a, **raw_authors[a]._asdict()} for a in used]
    for a in authors:
        a["alternate_names"] = list(a["alternate_names"])

    write_table(con, "works", pa.Table.from_pylist(works, schema=WORKS_SCHEMA))
    write_table(con, "editions", pa.Table.from_pylist(editions, schema=EDITIONS_SCHEMA))
    write_table(con, "authors", pa.Table.from_pylist(authors, schema=AUTHORS_SCHEMA))
    swap_in(con, ["works", "editions", "authors"])
```

- [ ] **Step 4: Run the test**

Run: `cd pipeline && .venv/bin/python -m pytest tests/test_stage_select_extract.py -v`
Expected: PASS (4 tests). Drops are exactly calendar, not_english and short.

- [ ] **Step 5: Commit**

```bash
git add pipeline/stages/select.py pipeline/stages/extract.py pipeline/tests/test_stage_select_extract.py
git commit -m "feat(pipeline): select and extract stages"
```

---

### Task 11: Author clusters

**Files:**
- Create: `pipeline/group/authors.py`
- Test: `pipeline/tests/test_authors.py`

**Interfaces:**
- Consumes: `_backend.normalize`.
- Produces: `MAX_NAME_SHARERS = 3`; `AuthorRec(ol_id, name, alternate_names=(), wikidata=None)`; `cluster_authors(authors, wd_author_ids=(), wd_names=()) -> dict[ol_author_id, cluster_id]` — the cluster id is the smallest OL id in the cluster.

Unions, strongest first: one Wikidata item (from OL `remote_ids` or Wikidata P648); then a shared *distinctive* name (≥2 words, or non-Latin like 刘慈欣) carried by 2–3 records. A name on more records is a common name and unions nobody (Review Focus 4).

- [ ] **Step 1: Write the failing test**

`pipeline/tests/test_authors.py`:

```python
from pipeline.group.authors import AuthorRec, cluster_authors


def test_alternate_name_joins_a_translated_record():
    clusters = cluster_authors([
        AuthorRec("OL2A", "Cixin Liu", ("Liu Cixin", "刘慈欣")),
        AuthorRec("OL3A", "刘慈欣"),
    ])
    assert clusters["OL2A"] == clusters["OL3A"] == "OL2A"


def test_one_wikidata_item_joins_its_ol_records():
    clusters = cluster_authors(
        [AuthorRec("OL7A", "J.R.R. Tolkien"), AuthorRec("OL8A", "Tolkien")],
        wd_author_ids=[("Q892", "OL7A"), ("Q892", "OL8A")],
    )
    assert clusters["OL7A"] == clusters["OL8A"]


def test_ol_remote_ids_join_records():
    clusters = cluster_authors([AuthorRec("OL7A", "A", wikidata="Q1"), AuthorRec("OL9A", "B", wikidata="Q1")])
    assert clusters["OL7A"] == clusters["OL9A"]


def test_wikidata_aliases_join_by_name():
    clusters = cluster_authors(
        [AuthorRec("OL2A", "Cixin Liu"), AuthorRec("OL3A", "刘慈欣")],
        wd_author_ids=[("Q5", "OL2A")],
        wd_names=[("Q5", "刘慈欣")],
    )
    assert clusters["OL2A"] == clusters["OL3A"]


def test_a_common_name_joins_nobody():
    records = [AuthorRec(f"OL{i}A", "John Smith") for i in range(1, 6)]
    clusters = cluster_authors(records)
    assert len(set(clusters.values())) == 5


def test_a_single_latin_word_is_not_distinctive():
    clusters = cluster_authors([AuthorRec("OL1A", "Homer"), AuthorRec("OL2A", "Homer")])
    assert clusters["OL1A"] != clusters["OL2A"]


def test_unrelated_authors_stay_apart():
    clusters = cluster_authors([AuthorRec("OL1A", "Pierce Brown"), AuthorRec("OL2A", "George R. R. Martin")])
    assert clusters == {"OL1A": "OL1A", "OL2A": "OL2A"}
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd pipeline && .venv/bin/python -m pytest tests/test_authors.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement**

`pipeline/group/authors.py`:

```python
"""Author clusters (spec §5.1): 刘慈欣 = Cixin Liu = Liu Cixin.

Every later author comparison is between clusters, never strings. A cluster's
id is its smallest OL author id, so it is stable across runs.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from typing import Iterable

from pipeline._backend import normalize

# A name carried by more records than this is a common name ("John Smith"),
# not one person catalogued several times, and never unions anyone.
MAX_NAME_SHARERS = 3
_NON_LATIN = re.compile(r"[^\x00-ɏ]")


@dataclass(frozen=True)
class AuthorRec:
    ol_id: str
    name: str
    alternate_names: tuple[str, ...] = ()
    wikidata: str | None = None  # from the OL record's remote_ids


class _UnionFind:
    def __init__(self, items: Iterable[str]) -> None:
        self.parent = {i: i for i in items}

    def find(self, x: str) -> str:
        root = x
        while self.parent[root] != root:
            root = self.parent[root]
        while self.parent[x] != root:
            self.parent[x], x = root, self.parent[x]
        return root

    def union(self, a: str, b: str) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            # The smaller id is the root, which makes it the cluster id.
            lo, hi = sorted((ra, rb))
            self.parent[hi] = lo


def _distinctive(name: str) -> bool:
    """Two or more words, or a non-Latin name: specific enough to match on."""
    return len(name.split()) >= 2 or (len(name) >= 2 and bool(_NON_LATIN.search(name)))


def cluster_authors(
    authors: Iterable[AuthorRec],
    wd_author_ids: Iterable[tuple[str, str]] = (),
    wd_names: Iterable[tuple[str, str]] = (),
) -> dict[str, str]:
    """Map every OL author id to its cluster id.

    ``wd_author_ids`` is ``(qid, ol_author_id)`` from Wikidata P648;
    ``wd_names`` is ``(qid, name)`` — labels and aliases of those items.
    """
    records = {a.ol_id: a for a in authors}
    uf = _UnionFind(records)

    # 1. One Wikidata item, many OL records: the strongest evidence there is.
    by_qid: dict[str, set[str]] = defaultdict(set)
    for a in records.values():
        if a.wikidata:
            by_qid[a.wikidata].add(a.ol_id)
    for qid, ol_id in wd_author_ids:
        if ol_id in records:
            by_qid[qid].add(ol_id)
    for members in by_qid.values():
        first, *rest = sorted(members)
        for other in rest:
            uf.union(first, other)

    # 2. Shared distinctive names, from OL alternate_names and Wikidata aliases.
    qids_of: dict[str, set[str]] = defaultdict(set)
    for qid, members in by_qid.items():
        for ol_id in members:
            qids_of[ol_id].add(qid)
    wd_name_map: dict[str, set[str]] = defaultdict(set)
    for qid, name in wd_names:
        wd_name_map[qid].add(name)

    carriers: dict[str, set[str]] = defaultdict(set)
    for a in records.values():
        names = {a.name, *a.alternate_names}
        for qid in qids_of[a.ol_id]:
            names |= wd_name_map[qid]
        for name in names:
            key = normalize(name)
            if key and _distinctive(key):
                carriers[key].add(a.ol_id)
    for members in carriers.values():
        if 2 <= len(members) <= MAX_NAME_SHARERS:
            first, *rest = sorted(members)
            for other in rest:
                uf.union(first, other)

    return {ol_id: uf.find(ol_id) for ol_id in records}
```

- [ ] **Step 4: Run the test**

Run: `cd pipeline && .venv/bin/python -m pytest tests/test_authors.py -v`
Expected: PASS (7 tests).

- [ ] **Step 5: Commit**

```bash
git add pipeline/group/authors.py pipeline/tests/test_authors.py
git commit -m "feat(pipeline): author clusters across OL records and Wikidata aliases"
```

---

### Task 12: Duplicate works

**Files:**
- Create: `pipeline/group/duplicates.py`
- Test: `pipeline/tests/test_duplicates.py`

**Interfaces:**
- Produces: `DupWork(ol_id, primary_author, title_key, kind, wd_items: frozenset, edition_titles: frozenset, popularity: int)`; `find_duplicates(works) -> dict[loser_ol_id, survivor_ol_id]`.

Same primary-author cluster and same cleaned title merge unless each is linked to a different Wikidata item, or their English editions share no cleaned title (Review Focus 2). Survivor: Wikidata-linked, then more popular, then lower OL number. Collections never merge.

- [ ] **Step 1: Write the failing test**

`pipeline/tests/test_duplicates.py`:

```python
from pipeline.group.duplicates import DupWork, find_duplicates


def dup(ol_id, title="red rising", author="OL4A", wd=(), editions=("red rising",), pop=10, kind="single"):
    return DupWork(ol_id, author, title, kind, frozenset(wd), frozenset(editions), pop)


def test_same_author_cluster_and_title_merge_into_the_more_popular():
    assert find_duplicates([dup("OL30W", pop=900), dup("OL36W", pop=3)]) == {"OL36W": "OL30W"}


def test_a_wikidata_linked_work_survives_over_a_more_popular_one():
    assert find_duplicates([dup("OL30W", pop=900), dup("OL36W", wd=["Q1"], pop=3)]) == {"OL30W": "OL36W"}


def test_lower_ol_number_breaks_a_tie():
    assert find_duplicates([dup("OL100W"), dup("OL99W")]) == {"OL100W": "OL99W"}


def test_distinct_wikidata_items_are_different_books():
    assert find_duplicates([dup("OL1W", wd=["Q1"]), dup("OL2W", wd=["Q2"])]) == {}


def test_editions_with_no_shared_title_are_different_books():
    # Open Library titles three Brian Herbert books plain "Dune".
    works = [
        dup("OL1W", "dune", "OL9A", editions=["house atreides"]),
        dup("OL2W", "dune", "OL9A", editions=["house harkonnen"]),
        dup("OL3W", "dune", "OL9A", editions=["house corrino"]),
    ]
    assert find_duplicates(works) == {}


def test_a_work_without_editions_can_merge():
    assert find_duplicates([dup("OL1W", pop=5), dup("OL2W", editions=(), pop=1)]) == {"OL2W": "OL1W"}


def test_collections_never_merge():
    assert find_duplicates([dup("OL1W", kind="collection"), dup("OL2W", kind="collection")]) == {}


def test_different_author_clusters_never_merge():
    assert find_duplicates([dup("OL1W", author="OL4A"), dup("OL2W", author="OL5A")]) == {}
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd pipeline && .venv/bin/python -m pytest tests/test_duplicates.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement**

`pipeline/group/duplicates.py`:

```python
"""Duplicate works (spec §5.2): two OL records of one book.

Same primary-author cluster and same cleaned title merge, unless the
evidence says they are different books: each linked to a different Wikidata
item, or editions that share no title at all (Open Library titles three
different Brian Herbert books plain "Dune"; their editions say *House
Atreides*, *House Harkonnen*, *House Corrino*).
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from typing import Sequence

_OL_NUMBER = re.compile(r"\d+")


@dataclass(frozen=True)
class DupWork:
    ol_id: str
    primary_author: str | None
    title_key: str  # clean_title of the work title
    kind: str
    wd_items: frozenset[str]
    edition_titles: frozenset[str]  # clean_title of each English edition's title
    popularity: int  # readinglog_count + edition_count


def _ol_number(ol_id: str) -> int:
    match = _OL_NUMBER.search(ol_id)
    return int(match.group()) if match else 0


def _rank(work: DupWork) -> tuple[int, int, int]:
    """Survivor order: Wikidata-linked, then more popular, then lower OL id."""
    return (0 if work.wd_items else 1, -work.popularity, _ol_number(work.ol_id))


def _compatible(a: DupWork, b: DupWork) -> bool:
    if a.wd_items and b.wd_items and a.wd_items.isdisjoint(b.wd_items):
        return False
    if a.edition_titles and b.edition_titles and a.edition_titles.isdisjoint(b.edition_titles):
        return False
    return True


def find_duplicates(works: Sequence[DupWork]) -> dict[str, str]:
    """``{loser_ol_id: survivor_ol_id}``. Collections never merge."""
    groups: dict[tuple[str, str], list[DupWork]] = defaultdict(list)
    for work in works:
        if work.primary_author is None or work.kind == "collection" or not work.title_key:
            continue
        groups[(work.primary_author, work.title_key)].append(work)

    losers: dict[str, str] = {}
    for group in groups.values():
        if len(group) < 2:
            continue
        clusters: list[list[DupWork]] = []
        for work in sorted(group, key=_rank):
            home = next((c for c in clusters if all(_compatible(work, m) for m in c)), None)
            if home is None:
                clusters.append([work])
            else:
                home.append(work)
        for survivor, *rest in clusters:
            for loser in rest:
                losers[loser.ol_id] = survivor.ol_id
    return losers
```

- [ ] **Step 4: Run the test**

Run: `cd pipeline && .venv/bin/python -m pytest tests/test_duplicates.py -v`
Expected: PASS (8 tests).

- [ ] **Step 5: Commit**

```bash
git add pipeline/group/duplicates.py pipeline/tests/test_duplicates.py
git commit -m "feat(pipeline): merge duplicate works, keeping distinct books apart"
```

---

### Task 13: The ladder's evidence (rungs 1–4)

**Files:**
- Create: `pipeline/group/ladder.py`
- Test: `pipeline/tests/test_ladder.py`

**Interfaces:**
- Consumes: `group.types`, `parse.series_strings`, `_backend.choose_container/parse_tags/series_key/tag_name`.
- Produces: `parse_ordinal(raw) -> float | None`; `ol_key(name) -> "ol:<series_key>" | None`; `wd_label(wd_series, qid) -> str`; `rung1(work, by_item, wd_series) -> list[Candidate]`; `count_tags(works) -> Counter[str]`; `rung2(work, tag_counts)`, `rung3(work)`, `rung4(work) -> Candidate | None`; `candidates(work, by_item, wd_series, tag_counts) -> list[Candidate]`.

Rungs 3 and 4 are majority votes: one vote per edition (or per title) per series, positions voted within the winner. `count_tags` counts over the **whole** catalog, which is what `choose_container` needs to pick the broadest `series:` tag.

- [ ] **Step 1: Write the failing test**

`pipeline/tests/test_ladder.py`:

```python
from pipeline.group.ladder import count_tags, parse_ordinal, rung1, rung2, rung3, rung4
from pipeline.group.types import Candidate, GWork, WdMembership, WdSeries


def gw(ol_id="OL1W", titles=("A Book",), subjects=None, editions=(), wd=()):
    return GWork(ol_id, tuple(titles), "OL1A", "single", subjects, tuple(tuple(e) for e in editions), frozenset(wd))


def test_ordinals():
    assert parse_ordinal("3") == 3.0
    assert parse_ordinal("2.5") == 2.5
    assert parse_ordinal("1a") is None
    assert parse_ordinal(None) is None


def test_rung1_reads_every_wikidata_series_with_its_ordinal():
    by_item = {"Q1": [WdMembership("Q1", "Q45875", "3"), WdMembership("Q1", "Q99", None)]}
    series = {"Q45875": WdSeries("Q45875", "A Song of Ice and Fire")}
    assert rung1(gw(wd=["Q1"]), by_item, series) == [
        Candidate("wd:Q45875", "A Song of Ice and Fire", 3.0, 1),
        Candidate("wd:Q99", "Q99", None, 1),
    ]


def test_rung2_prefers_the_franchise_then_the_broadest_series_tag():
    works = [gw("OL1W", subjects="series:Red Rising Trilogy\nseries:Red Rising Saga"),
             gw("OL2W", subjects="series:Red Rising Saga")]
    counts = count_tags(works)
    assert rung2(works[0], counts) == Candidate("ol:red rising saga", "Red Rising Saga", None, 2)
    assert rung2(gw(subjects="franchise:Red Rising\nseries:X"), counts).key == "ol:red rising"
    assert rung2(gw(subjects="fiction"), counts) is None


def test_rung3_is_a_majority_vote_across_editions():
    work = gw(editions=[["Red Rising Saga ; 5"], ["Red Rising Saga, #5"], ["Red Rising ; 4"], []])
    assert rung3(work) == Candidate("ol:red rising saga", "Red Rising Saga", 5.0, 3)


def test_rung3_counts_one_vote_per_edition():
    work = gw(editions=[["X ; 1", "X (1)"], ["Y ; 2"]])
    assert rung3(work).key == "ol:x"


def test_rung4_reads_titles():
    work = gw(titles=["The Dark Forest", "The Dark Forest (Remembrance of Earth's Past Series Book 2)"])
    assert rung4(work) == Candidate("ol:remembrance of earth s past", "Remembrance of Earth's Past", 2.0, 4)
    assert rung4(gw(titles=["The Hobbit"])) is None
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd pipeline && .venv/bin/python -m pytest tests/test_ladder.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement**

`pipeline/group/ladder.py`:

```python
"""The series decision ladder's evidence (spec §5.3, rungs 1-4).

Each function turns one kind of evidence into candidates. Choosing between
them — and the guards — live in ``guards.py`` and ``decide.py``.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from typing import Iterable, Mapping, Sequence

from pipeline._backend import choose_container, parse_tags, series_key, tag_name
from pipeline.group.types import Candidate, GWork, WdMembership, WdSeries
from pipeline.parse.series_strings import SeriesRef, parse_series_string, parse_title_series

_ORDINAL = re.compile(r"^\d{1,4}(?:\.\d+)?$")


def parse_ordinal(raw: str | None) -> float | None:
    """Wikidata P1545 as a number; "1a" or "I" is no position at all."""
    text = (raw or "").strip()
    return float(text) if _ORDINAL.match(text) else None


def ol_key(name: str) -> str | None:
    key = series_key(name)
    return f"ol:{key}" if key else None


def wd_label(wd_series: Mapping[str, WdSeries], qid: str) -> str:
    series = wd_series.get(qid)
    if series is None:
        return qid
    return series.label or (min(series.aliases) if series.aliases else qid)


def rung1(work: GWork, by_item: Mapping[str, Sequence[WdMembership]],
          wd_series: Mapping[str, WdSeries]) -> list[Candidate]:
    found: dict[str, Candidate] = {}
    for item in sorted(work.wd_items):
        for m in by_item.get(item, ()):
            key = f"wd:{m.series}"
            position = parse_ordinal(m.ordinal)
            prior = found.get(key)
            if prior is None or (prior.position is None and position is not None):
                found[key] = Candidate(key, wd_label(wd_series, m.series), position, 1)
    return [found[k] for k in sorted(found)]


def count_tags(works: Iterable[GWork]) -> Counter[str]:
    """How many catalog works carry each series tag — counted over the whole catalog."""
    counts: Counter[str] = Counter()
    for work in works:
        tags = parse_tags(work.subjects)
        counts.update(set(tags.series))
    return counts


def rung2(work: GWork, tag_counts: Mapping[str, int]) -> Candidate | None:
    tag = choose_container(parse_tags(work.subjects), tag_counts)
    if tag is None:
        return None
    name = tag_name(tag)
    key = ol_key(name)
    return Candidate(key, name, None, 2) if key else None


def _vote(refs_per_voter: Iterable[Iterable[SeriesRef]], rung: int) -> Candidate | None:
    """Majority vote: one vote per voter per series, positions voted within the winner."""
    votes: Counter[str] = Counter()
    names: dict[str, Counter[str]] = defaultdict(Counter)
    positions: dict[str, Counter[float]] = defaultdict(Counter)
    for refs in refs_per_voter:
        seen: set[str] = set()
        for ref in refs:
            key = ol_key(ref.name)
            if key is None or key in seen:
                continue
            seen.add(key)
            votes[key] += 1
            names[key][ref.name] += 1
            if ref.position is not None:
                positions[key][ref.position] += 1
    if not votes:
        return None
    key = min(votes, key=lambda k: (-votes[k], k))
    name = min(names[key], key=lambda n: (-names[key][n], n))
    pos_votes = positions[key]
    position = min(pos_votes, key=lambda p: (-pos_votes[p], p)) if pos_votes else None
    return Candidate(key, name, position, rung)


def rung3(work: GWork) -> Candidate | None:
    return _vote(
        ([r for r in (parse_series_string(raw) for raw in edition) if r] for edition in work.edition_series),
        rung=3,
    )


def rung4(work: GWork) -> Candidate | None:
    return _vote(([r] if (r := parse_title_series(t)) else [] for t in work.titles), rung=4)


def candidates(work: GWork, by_item: Mapping[str, Sequence[WdMembership]],
               wd_series: Mapping[str, WdSeries], tag_counts: Mapping[str, int]) -> list[Candidate]:
    found = rung1(work, by_item, wd_series)
    found += [c for c in (rung2(work, tag_counts), rung3(work), rung4(work)) if c is not None]
    return found
```

- [ ] **Step 4: Run the test**

Run: `cd pipeline && .venv/bin/python -m pytest tests/test_ladder.py -v`
Expected: PASS (6 tests).

- [ ] **Step 5: Commit**

```bash
git add pipeline/group/ladder.py pipeline/tests/test_ladder.py
git commit -m "feat(pipeline): series ladder evidence from Wikidata, tags, editions and titles"
```

---

### Task 14: Ladder guards: imprints, folding, adaptations

**Files:**
- Create: `pipeline/group/guards.py`, `pipeline/rules/imprints.yaml`
- Test: `pipeline/tests/test_guards.py`

**Interfaces:**
- Produces: `MAX_AUTHOR_CLUSTERS = 3`; `imprint_rejections(cands, primary, blocked=()) -> dict[key, author_clusters]`; `fold_map(cands, wd_series, rejected=()) -> dict[ol_key, surviving_key]`; `drop_adaptations(memberships, primary) -> None` (mutates).
  `cands` is `Mapping[work_ol_id, Sequence[Candidate]]`; `primary` is `Mapping[work_ol_id, cluster_id | None]`; `memberships` is `dict[work_ol_id, dict[key, Membership]]`.

Wikidata series are never imprints and override the adaptation filter. Blocklisted names count only when some work actually carries them.

- [ ] **Step 1: Write the failing test**

`pipeline/tests/test_guards.py`:

```python
from pipeline.group.guards import drop_adaptations, fold_map, imprint_rejections
from pipeline.group.types import Candidate, Membership, WdSeries


def c(key, rung, name="x", pos=None):
    return Candidate(key, name, pos, rung)


def test_a_series_spanning_four_author_clusters_is_an_imprint():
    cands = {f"OL{i}W": [c("ol:penguin classics", 2)] for i in range(4)}
    primary = {f"OL{i}W": f"OL{i}A" for i in range(4)}
    assert imprint_rejections(cands, primary) == {"ol:penguin classics": 4}


def test_three_author_clusters_is_still_a_series():
    cands = {f"OL{i}W": [c("ol:dune", 2)] for i in range(3)}
    assert imprint_rejections(cands, {f"OL{i}W": f"OL{i}A" for i in range(3)}) == {}


def test_blocklisted_names_are_rejected_regardless():
    assert imprint_rejections({"OL1W": [c("ol:a del rey book", 2)]}, {"OL1W": "OL1A"},
                              blocked=["ol:a del rey book"]) == {"ol:a del rey book": 1}


def test_wikidata_series_are_never_imprints():
    cands = {f"OL{i}W": [c("wd:Q1", 1)] for i in range(5)}
    assert imprint_rejections(cands, {f"OL{i}W": f"OL{i}A" for i in range(5)}) == {}


def test_folds_into_wikidata_by_name():
    cands = {"OL13W": [c("ol:a song of ice and fire", 3)]}
    wd = {"Q45875": WdSeries("Q45875", "A Song of Ice and Fire")}
    assert fold_map(cands, wd) == {"ol:a song of ice and fire": "wd:Q45875"}


def test_folds_into_wikidata_when_half_its_works_are_members():
    cands = {
        "OL1W": [c("wd:Q7", 1), c("ol:earthsea cycle", 2)],
        "OL2W": [c("ol:earthsea cycle", 2)],
    }
    assert fold_map(cands, {"Q7": WdSeries("Q7", "Earthsea")}) == {"ol:earthsea cycle": "wd:Q7"}


def test_does_not_fold_below_half():
    cands = {
        "OL1W": [c("wd:Q7", 1), c("ol:x", 2)],
        "OL2W": [c("ol:x", 2)],
        "OL3W": [c("ol:x", 2)],
    }
    assert fold_map(cands, {"Q7": WdSeries("Q7", "Other")}) == {}


def test_edition_series_folds_into_the_tag_its_siblings_carry():
    cands = {
        "OL30W": [c("ol:red rising", 2), c("ol:red rising saga", 3, pos=1.0)],
        "OL34W": [c("ol:red rising", 2), c("ol:red rising saga", 3, pos=5.0)],
    }
    assert fold_map(cands, {}) == {"ol:red rising saga": "ol:red rising"}


def test_rejected_series_never_fold():
    cands = {"OL1W": [c("ol:penguin classics", 2)]}
    wd = {"Q9": WdSeries("Q9", "Penguin Classics")}
    assert fold_map(cands, wd, rejected={"ol:penguin classics"}) == {}


def test_adaptations_by_another_author_are_dropped():
    memberships = {
        "OL30W": {"ol:red rising": Membership("ol:red rising", 1.0, 2)},
        "OL31W": {"ol:red rising": Membership("ol:red rising", 2.0, 2)},
        "OL35W": {"ol:red rising": Membership("ol:red rising", None, 2)},
    }
    drop_adaptations(memberships, {"OL30W": "OL4A", "OL31W": "OL4A", "OL35W": "OL6A"})
    assert memberships["OL35W"] == {}
    assert "ol:red rising" in memberships["OL30W"]


def test_wikidata_overrules_the_adaptation_filter():
    memberships = {
        "OL1W": {"wd:Q1": Membership("wd:Q1", 1.0, 1)},
        "OL2W": {"wd:Q1": Membership("wd:Q1", 2.0, 1)},
        "OL3W": {"wd:Q1": Membership("wd:Q1", 3.0, 1)},
    }
    drop_adaptations(memberships, {"OL1W": "OL1A", "OL2W": "OL1A", "OL3W": "OL9A"})
    assert "wd:Q1" in memberships["OL3W"]


def test_blocklisted_names_nobody_carries_are_not_reported():
    assert imprint_rejections({"OL1W": [c("ol:dune", 2)]}, {"OL1W": "OL1A"}, blocked=["ol:penguin classics"]) == {}
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd pipeline && .venv/bin/python -m pytest tests/test_guards.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement**

`pipeline/group/guards.py`:

```python
"""Guards on the ladder (spec §5.3): imprints, folding, adaptations."""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Iterable, Mapping, Sequence

from pipeline._backend import series_key
from pipeline.group.types import Candidate, Membership, WdSeries

# A rung 2-4 series spanning more author clusters than this is a publisher
# imprint (Penguin Classics, "A Del Rey book"), not a series.
MAX_AUTHOR_CLUSTERS = 3


def imprint_rejections(cands: Mapping[str, Sequence[Candidate]],
                       primary: Mapping[str, str | None],
                       blocked: Iterable[str] = ()) -> dict[str, int]:
    """``{series key: author clusters}`` for every rejected rung 2-4 series."""
    clusters: dict[str, set[str]] = defaultdict(set)
    for work, cs in cands.items():
        author = primary.get(work)
        for c in cs:
            if c.rung > 1 and author is not None:
                clusters[c.key].add(author)
    rejected = {k: len(v) for k, v in clusters.items() if len(v) > MAX_AUTHOR_CLUSTERS}
    for key in blocked:
        if key in clusters:
            rejected.setdefault(key, len(clusters[key]))
    return rejected


def _follow(mapping: Mapping[str, str], key: str) -> str:
    seen = {key}
    while key in mapping and mapping[key] not in seen:
        key = mapping[key]
        seen.add(key)
    return key


def fold_map(cands: Mapping[str, Sequence[Candidate]], wd_series: Mapping[str, WdSeries],
             rejected: Iterable[str] = ()) -> dict[str, str]:
    """Where each rung 2-4 series folds, as ``{ol key: surviving key}``.

    Folds into a Wikidata series whose label or alias has the same
    ``series_key``; otherwise into whichever stronger series (Wikidata, or an
    OL series from a higher rung) at least half of its works already carry.
    The second rule is what joins "Red Rising Saga ; 5" on an edition to the
    ``franchise:Red Rising`` tag its siblings carry.
    """
    rejected = set(rejected)
    wd_by_name: dict[str, set[str]] = defaultdict(set)
    for qid, s in wd_series.items():
        for name in (s.label, *s.aliases):
            if name:
                wd_by_name[series_key(name)].add(f"wd:{qid}")
    rung1_members = Counter(c.key for cs in cands.values() for c in cs if c.rung == 1)
    ol_keys = sorted({c.key for cs in cands.values() for c in cs if c.rung > 1} - rejected)

    mapping: dict[str, str] = {}
    for key in ol_keys:
        targets = wd_by_name.get(key[len("ol:"):])
        if targets:
            mapping[key] = min(targets, key=lambda t: (-rung1_members[t], t))

    carriers: dict[str, list[tuple[str, int]]] = defaultdict(list)
    for work, cs in cands.items():
        for c in cs:
            if c.rung > 1 and c.key in ol_keys:
                carriers[c.key].append((work, c.rung))
    for key in ol_keys:
        if key in mapping:
            continue
        votes: Counter[str] = Counter()
        for work, rung in carriers[key]:
            stronger = {mapping.get(c.key, c.key) for c in cands[work]
                        if c.rung < rung and c.key not in rejected} - {key}
            votes.update(stronger)
        if votes:
            target, n = min(votes.items(), key=lambda kv: (-kv[1], kv[0]))
            if 2 * n >= len(carriers[key]):
                mapping[key] = target
    return {k: _follow(mapping, k) for k in mapping}


def drop_adaptations(memberships: dict[str, dict[str, Membership]],
                     primary: Mapping[str, str | None]) -> None:
    """Remove rung 2-4 members not by the series' dominant author cluster.

    Graphic-novel adaptations, companions and game books by other authors
    stay out. Wikidata (rung 1) is trusted over this rule.
    """
    holders: dict[str, list[tuple[str, int]]] = defaultdict(list)
    for work, ms in memberships.items():
        for key, m in ms.items():
            holders[key].append((work, m.rung))
    for key, members in holders.items():
        authors = Counter(primary[w] for w, _ in members if primary.get(w) is not None)
        if not authors:
            continue
        dominant = min(authors, key=lambda a: (-authors[a], a))
        for work, rung in members:
            if rung != 1 and primary.get(work) != dominant:
                del memberships[work][key]
```

`pipeline/rules/imprints.yaml`:

```yaml
# Publisher imprints and lines that are never a series (spec §5.3, imprint
# filter backstop). The >3-author-cluster rule catches most imprints; list
# here the ones too small to trip it. Matched on series_key(name), so casing
# and punctuation do not matter.
- Penguin Classics
- Oxford World's Classics
- Everyman's Library
- Vintage International
- Modern Library
- A Del Rey Book
- Signet Classics
- Bantam Classics
- Tor Essentials
- Harper Perennial Modern Classics
```

- [ ] **Step 4: Run the test**

Run: `cd pipeline && .venv/bin/python -m pytest tests/test_guards.py -v`
Expected: PASS (12 tests).

- [ ] **Step 5: Commit**

```bash
git add pipeline/group/guards.py pipeline/rules/imprints.yaml pipeline/tests/test_guards.py
git commit -m "feat(pipeline): imprint, folding and adaptation guards"
```

---

### Task 15: Membership decisions and rooms

**Files:**
- Create: `pipeline/group/decide.py`, `pipeline/group/nesting.py`
- Test: `pipeline/tests/test_decide.py`, `pipeline/tests/test_nesting.py`

**Interfaces:**
- Consumes: Tasks 13–14.
- Produces (`decide`): `Decision(memberships: dict[work, dict[key, Membership]], names: dict[key, str], rejected: dict[key, int], decided_by: dict[work, int | None], known_series: set[str])`; `decide(works, wd_memberships, wd_series, blocklist=(), rejects=()) -> Decision` — `blocklist` holds imprint *names*, `rejects` series *keys*.
- Produces (`nesting`): `rooms(memberships: Mapping[work, Iterable[key]], parents: Mapping[key, parent_key]) -> tuple[dict[work, room_key], dict[key, parent_key | None]]` — the second result lists every series the release needs.

A work with any rung-1 evidence takes all its Wikidata memberships; otherwise the highest surviving rung wins. Its position comes from the highest rung that supplies one *for the same (folded) series*. A universe with one child series in the catalog does not become that child's room.

- [ ] **Step 1: Write the failing tests**

`pipeline/tests/test_decide.py`:

```python
from pipeline.group.decide import decide
from pipeline.group.types import GWork, Membership, WdMembership, WdSeries


def gw(ol_id, author="OL1A", titles=None, subjects=None, editions=(), wd=(), kind="single"):
    return GWork(ol_id, tuple(titles or [ol_id]), author, kind, subjects,
                 tuple(tuple(e) for e in editions), frozenset(wd))


ASOIAF = {"Q45875": WdSeries("Q45875", "A Song of Ice and Fire")}
ASOIAF_MEMBERS = [WdMembership("Q1", "Q45875", "1"), WdMembership("Q2", "Q45875", "2")]


def test_wikidata_wins_and_edition_strings_fill_in_missing_members():
    works = [gw("OL10W", wd=["Q1"]), gw("OL11W", wd=["Q2"]),
             gw("OL13W", editions=[["A Song of Ice and Fire ; 4"]])]
    d = decide(works, ASOIAF_MEMBERS, ASOIAF)
    assert d.memberships["OL10W"] == {"wd:Q45875": Membership("wd:Q45875", 1.0, 1)}
    assert d.memberships["OL13W"] == {"wd:Q45875": Membership("wd:Q45875", 4.0, 3)}
    assert d.decided_by == {"OL10W": 1, "OL11W": 1, "OL13W": 3}
    assert d.names["wd:Q45875"] == "A Song of Ice and Fire"


def test_position_comes_from_the_highest_rung_that_has_one():
    works = [gw("OL1W", wd=["Q3"], editions=[["A Song of Ice and Fire ; 3"]])]
    d = decide(works, [WdMembership("Q3", "Q45875", None)], ASOIAF)
    assert d.memberships["OL1W"]["wd:Q45875"].position == 3.0


def test_imprint_members_become_singletons():
    works = [gw(f"OL5{i}W", author=f"OL{i}A", subjects="series:Penguin Classics") for i in range(4)]
    d = decide(works, [], {})
    assert all(ms == {} for ms in d.memberships.values())
    assert d.rejected == {"ol:penguin classics": 4}


def test_override_rejects_act_like_imprints():
    d = decide([gw("OL1W", subjects="series:Dune")], [], {}, rejects={"ol:dune"})
    assert d.memberships["OL1W"] == {}


def test_collections_join_without_a_position():
    works = [gw("OL1W", editions=[["Mistborn ; 1"]]), gw("OL2W", editions=[["Mistborn ; 2"]]),
             gw("OL9W", kind="collection", editions=[["Mistborn ; 1-3"], ["Mistborn ; 1"]])]
    d = decide(works, [], {})
    assert d.memberships["OL9W"] == {"ol:mistborn": Membership("ol:mistborn", None, 3)}


def test_a_lone_title_pattern_is_not_a_series():
    d = decide([gw("OL1W", titles=["Red Rising #1"])], [], {})
    assert d.memberships["OL1W"] == {}
    assert d.decided_by["OL1W"] is None


def test_red_rising_positions_fix_publication_order():
    works = [
        gw("OL30W", subjects="franchise:Red Rising", editions=[["Red Rising Saga ; 1"]]),
        gw("OL34W", subjects="franchise:Red Rising", editions=[["Red Rising Saga ; 5"]]),
        gw("OL35W", author="OL6A", subjects="franchise:Red Rising"),
    ]
    d = decide(works, [], {})
    assert d.memberships["OL34W"] == {"ol:red rising": Membership("ol:red rising", 5.0, 2)}
    assert d.memberships["OL35W"] == {}
```

`pipeline/tests/test_nesting.py`:

```python
from pipeline.group.nesting import rooms


def test_a_parent_with_two_child_series_is_the_room():
    memberships = {"OL1W": ["wd:MISTBORN"], "OL2W": ["wd:MISTBORN"], "OL3W": ["wd:STORMLIGHT"]}
    parents = {"wd:MISTBORN": "wd:COSMERE", "wd:STORMLIGHT": "wd:COSMERE"}
    room, parent_of = rooms(memberships, parents)
    assert room == {"OL1W": "wd:COSMERE", "OL2W": "wd:COSMERE", "OL3W": "wd:COSMERE"}
    assert parent_of == {"wd:COSMERE": None, "wd:MISTBORN": "wd:COSMERE", "wd:STORMLIGHT": "wd:COSMERE"}


def test_a_universe_with_one_child_does_not_swallow_it():
    memberships = {"OL60W": ["wd:LOTR"], "OL61W": ["wd:LOTR"], "OL62W": ["wd:LOTR"]}
    room, parent_of = rooms(memberships, {"wd:LOTR": "wd:MIDDLE_EARTH"})
    assert set(room.values()) == {"wd:LOTR"}
    assert parent_of == {"wd:LOTR": None}


def test_a_parent_with_two_direct_works_is_a_room():
    memberships = {"OL1W": ["wd:DISCWORLD"], "OL2W": ["wd:DISCWORLD"], "OL3W": ["wd:RINCEWIND"]}
    room, _ = rooms(memberships, {"wd:RINCEWIND": "wd:DISCWORLD"})
    assert room["OL3W"] == "wd:DISCWORLD"


def test_a_work_in_two_trees_takes_the_bigger_room():
    memberships = {"OL1W": ["wd:A", "wd:B"], "OL2W": ["wd:A"], "OL3W": ["wd:A"]}
    room, _ = rooms(memberships, {})
    assert room["OL1W"] == "wd:A"


def test_parent_cycles_terminate():
    memberships = {"OL1W": ["wd:A"], "OL2W": ["wd:A"], "OL3W": ["wd:B"], "OL4W": ["wd:B"]}
    room, _ = rooms(memberships, {"wd:A": "wd:B", "wd:B": "wd:A"})
    assert set(room) == {"OL1W", "OL2W", "OL3W", "OL4W"}


def test_works_without_series_have_no_room():
    room, parent_of = rooms({"OL1W": []}, {})
    assert room == {} and parent_of == {}
```

- [ ] **Step 2: Run them to verify they fail**

Run: `cd pipeline && .venv/bin/python -m pytest tests/test_decide.py tests/test_nesting.py -v`
Expected: FAIL — modules not found.

- [ ] **Step 3: Implement**

`pipeline/group/decide.py`:

```python
"""Membership decisions: the ladder, its guards, one result (spec §5.3)."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Iterable, Mapping, Sequence

from pipeline._backend import series_key
from pipeline.group.guards import drop_adaptations, fold_map, imprint_rejections
from pipeline.group.ladder import candidates, count_tags, wd_label
from pipeline.group.types import Candidate, GWork, Membership, WdMembership, WdSeries


@dataclass
class Decision:
    memberships: dict[str, dict[str, Membership]]  # work -> series key -> membership
    names: dict[str, str]  # series key -> display name
    rejected: dict[str, int]  # imprint key -> author clusters
    decided_by: dict[str, int | None]  # work -> winning rung (None = singleton)
    known_series: set[str] = field(default_factory=set)  # every key the build has evidence for


def _names(cands: Mapping[str, Sequence[Candidate]], wd_series: Mapping[str, WdSeries]) -> dict[str, str]:
    raw: dict[str, Counter[str]] = defaultdict(Counter)
    for cs in cands.values():
        for c in cs:
            if c.rung > 1:
                raw[c.key][c.name] += 1
    names = {k: min(v, key=lambda n: (-v[n], n)) for k, v in raw.items()}
    names.update({f"wd:{qid}": wd_label(wd_series, qid) for qid in wd_series})
    return names


def decide(works: Sequence[GWork], wd_memberships: Iterable[WdMembership],
           wd_series: Mapping[str, WdSeries], blocklist: Iterable[str] = (),
           rejects: Iterable[str] = ()) -> Decision:
    """``blocklist`` holds imprint names; ``rejects`` holds series keys from overrides."""
    by_item: dict[str, list[WdMembership]] = defaultdict(list)
    for m in wd_memberships:
        by_item[m.item].append(m)
    tag_counts = count_tags(works)
    cands = {w.ol_id: candidates(w, by_item, wd_series, tag_counts) for w in works}
    primary = {w.ol_id: w.primary_author for w in works}

    blocked = {f"ol:{series_key(n)}" for n in blocklist} | set(rejects)
    rejected = imprint_rejections(cands, primary, blocked)
    fold = fold_map(cands, wd_series, rejected)

    memberships: dict[str, dict[str, Membership]] = {}
    for work in works:
        mapped = sorted(
            (Candidate(fold.get(c.key, c.key), c.name,
                       None if work.kind == "collection" else c.position, c.rung)
             for c in cands[work.ol_id] if c.key not in rejected),
            key=lambda c: c.rung,
        )
        top = [c for c in mapped if c.rung == 1] or mapped[:1]
        chosen: dict[str, Membership] = {}
        for c in top:
            if c.key in chosen:
                continue
            position = next((o.position for o in mapped if o.key == c.key and o.position is not None), None)
            chosen[c.key] = Membership(c.key, position, c.rung)
        memberships[work.ol_id] = chosen

    drop_adaptations(memberships, primary)

    # A title pattern alone, seen on one book, is too weak to stand up a series.
    holders: dict[str, list[Membership]] = defaultdict(list)
    for ms in memberships.values():
        for m in ms.values():
            holders[m.key].append(m)
    lonely = {k for k, ms in holders.items() if len(ms) == 1 and ms[0].rung == 4}
    for ms in memberships.values():
        for key in lonely & ms.keys():
            del ms[key]

    decided_by = {w: (min(m.rung for m in ms.values()) if ms else None) for w, ms in memberships.items()}
    known = {c.key for cs in cands.values() for c in cs} | set(fold.values()) | {f"wd:{q}" for q in wd_series}
    return Decision(memberships, _names(cands, wd_series), rejected, decided_by, known)
```

`pipeline/group/nesting.py`:

```python
"""Series nesting and rooms (spec §5.3, "Nesting").

A work's room is the top of its membership's parent chain, but a parent only
becomes a room when it has at least two direct works or two child series — a
sprawling "universe" item cannot swallow unrelated books.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Iterable, Mapping


def rooms(memberships: Mapping[str, Iterable[str]],
          parents: Mapping[str, str]) -> tuple[dict[str, str], dict[str, str | None]]:
    """Return ``(room of each work, parent of each output series)``.

    ``memberships`` maps a work to its series keys; works with none are left
    out (they become singletons). ``parents`` maps a series key to its
    parent's key. The second result holds every series the release needs —
    members' series plus the chain above them up to each room.
    """
    member_keys = {w: set(keys) for w, keys in memberships.items() if keys}
    direct: Counter[str] = Counter(k for keys in member_keys.values() for k in keys)

    relevant = set(direct)
    frontier = list(relevant)
    while frontier:
        parent = parents.get(frontier.pop())
        if parent and parent not in relevant:
            relevant.add(parent)
            frontier.append(parent)
    children: dict[str, set[str]] = defaultdict(set)
    for key in relevant:
        if parents.get(key):
            children[parents[key]].add(key)

    def qualifies(key: str) -> bool:
        return direct[key] >= 2 or len(children[key]) >= 2

    def chain(key: str) -> list[str]:
        path = [key]
        while (parent := parents.get(path[-1])) and parent not in path and qualifies(parent):
            path.append(parent)
        return path

    chains = {k: chain(k) for k in direct}
    tops = {w: sorted({chains[k][-1] for k in keys}) for w, keys in member_keys.items()}
    size = Counter(t for ts in tops.values() for t in ts)
    room = {w: min(ts, key=lambda t: (-size[t], t)) for w, ts in tops.items()}

    output = {k for path in chains.values() for k in path}
    parent_of = {k: (parents[k] if parents.get(k) in output else None) for k in sorted(output)}
    return room, parent_of
```

- [ ] **Step 4: Run the tests**

Run: `cd pipeline && .venv/bin/python -m pytest tests/test_decide.py tests/test_nesting.py -v`
Expected: PASS (13 tests).

- [ ] **Step 5: Commit**

```bash
git add pipeline/group/decide.py pipeline/group/nesting.py pipeline/tests/test_decide.py pipeline/tests/test_nesting.py
git commit -m "feat(pipeline): membership decisions, positions and room nesting"
```

---

### Task 16: Overrides

**Files:**
- Create: `pipeline/overrides.py`, `pipeline/overrides/README.md`
- Test: `pipeline/tests/test_overrides.py`

**Interfaces:**
- Consumes: `group.decide.Decision`, `group.types.Membership`, `OVERRIDE_RUNG`.
- Produces: `OverrideError`; dataclasses `MergeWorks(survivor, losers)`, `SplitWork(work, editions)` (property `new_work`), `SetSeries(work, series, position=None, name=None)`, `RemoveFromSeries(work, series)`, `RejectSeries(series)`, `RenameSeries(series, name)`; `normalize_series_key(raw)`; `load_overrides(directory) -> list[Override]`;
  `IdentityPlan(aliases, splits, edition_work)`; `apply_identity(overrides, works: set, edition_work: Mapping, aliases: Mapping) -> IdentityPlan`; `series_rejects(overrides) -> set[str]`; `apply_series(overrides, decision, works: set, resolve=lambda w: w) -> None`.

The `overrides/README.md` doubles as the directory's placeholder, so `load_overrides` always finds the directory. The librarian tools (TODO.md) will write this same format.

- [ ] **Step 1: Write the failing test**

`pipeline/tests/test_overrides.py`:

```python
import pytest

from pipeline.group.decide import Decision
from pipeline.group.types import Membership
from pipeline.overrides import (
    MergeWorks, OverrideError, RejectSeries, RenameSeries, SetSeries, SplitWork,
    apply_identity, apply_series, load_overrides, series_rejects,
)


def write(tmp_path, text, name="a.yaml"):
    (tmp_path / name).write_text(text, encoding="utf-8")
    return tmp_path


def test_loads_every_override_kind(tmp_path):
    ops = load_overrides(write(tmp_path, """
- merge_works: [OL123W, OL456W]
- split_work: {work: OL789W, editions: [OL1M, OL2M]}
- set_series: {work: OL27448W, series: "wd:Q45875", position: 3}
- remove_from_series: {work: OL27448W, series: "ol:dune"}
- reject_series: "ol:Penguin Classics"
- rename_series: {series: "wd:Q45875", name: "A Song of Ice and Fire"}
"""))
    assert ops[0] == MergeWorks("OL123W", ("OL456W",))
    assert ops[2] == SetSeries("OL27448W", "wd:Q45875", 3.0, None)
    assert ops[4] == RejectSeries("ol:penguin classics")
    assert ops[5] == RenameSeries("wd:Q45875", "A Song of Ice and Fire")


@pytest.mark.parametrize("text,message", [
    ("- frobnicate: OL1W", "unknown override"),
    ("- merge_works: [OL1W]", "at least two"),
    ("- set_series: {work: OL1W}", "malformed"),
    ("- reject_series: penguin", "series must be"),
    ("merge_works: [OL1W, OL2W]", "expected a list"),
])
def test_malformed_entries_fail_with_their_location(tmp_path, text, message):
    with pytest.raises(OverrideError, match=message):
        load_overrides(write(tmp_path, text))


def test_merge_and_split_apply_to_identity():
    plan = apply_identity(
        [MergeWorks("OL1W", ("OL2W",)), SplitWork("OL3W", ("OL9M",))],
        works={"OL1W", "OL2W", "OL3W"},
        edition_work={"OL8M": "OL2W", "OL9M": "OL3W", "OL7M": "OL3W"},
        aliases={},
    )
    assert plan.aliases == {"OL2W": "OL1W"}
    assert plan.edition_work == {"OL8M": "OL1W", "OL9M": "OL3W~OL9M", "OL7M": "OL3W"}


def test_merge_follows_existing_duplicate_aliases():
    plan = apply_identity([MergeWorks("OL5W", ("OL1W",))], {"OL1W", "OL2W", "OL5W"}, {}, aliases={"OL2W": "OL1W"})
    assert plan.aliases == {"OL1W": "OL5W", "OL2W": "OL5W"}


def test_identity_overrides_reject_unknown_ids():
    with pytest.raises(OverrideError, match="unknown work OL404W"):
        apply_identity([MergeWorks("OL1W", ("OL404W",))], {"OL1W"}, {}, {})
    with pytest.raises(OverrideError, match="not an edition of"):
        apply_identity([SplitWork("OL1W", ("OL9M",))], {"OL1W"}, {"OL9M": "OL2W"}, {})


def decision():
    return Decision(memberships={"OL1W": {"ol:dune": Membership("ol:dune", 1.0, 2)}, "OL2W": {}},
                    names={"ol:dune": "Dune"}, rejected={}, decided_by={"OL1W": 2, "OL2W": None},
                    known_series={"ol:dune", "wd:Q45875"})


def test_set_series_wins_over_the_ladder():
    d = decision()
    apply_series([SetSeries("OL2W", "wd:Q45875", 3.0)], d, {"OL1W", "OL2W"})
    assert d.memberships["OL2W"] == {"wd:Q45875": Membership("wd:Q45875", 3.0, 0)}
    assert d.decided_by["OL2W"] == 0


def test_set_series_can_create_a_named_ol_series():
    d = decision()
    apply_series([SetSeries("OL2W", "ol:lord of the rings", 1.0, "The Lord of the Rings")], d, {"OL1W", "OL2W"})
    assert d.names["ol:lord of the rings"] == "The Lord of the Rings"


def test_series_overrides_reject_unknown_series():
    with pytest.raises(OverrideError, match="no series ol:nope"):
        apply_series([SetSeries("OL2W", "ol:nope")], decision(), {"OL1W", "OL2W"})
    with pytest.raises(OverrideError, match="no series"):
        apply_series([RejectSeries("ol:nope")], decision(), {"OL1W"})


def test_rename_and_rejects():
    d = decision()
    apply_series([RenameSeries("ol:dune", "Dune Chronicles")], d, {"OL1W"})
    assert d.names["ol:dune"] == "Dune Chronicles"
    assert series_rejects([RejectSeries("ol:x"), RenameSeries("ol:dune", "y")]) == {"ol:x"}
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd pipeline && .venv/bin/python -m pytest tests/test_overrides.py -v`
Expected: FAIL — `No module named 'pipeline.overrides'`.

- [ ] **Step 3: Implement**

`pipeline/overrides.py`:

```python
"""Manual corrections (spec §5.4): ``pipeline/overrides/*.yaml``, always win.

Identity overrides (``merge_works``, ``split_work``) apply after duplicate
detection; series overrides apply after the ladder. An entry that references
something the build does not hold fails the run — a stale override is a bug
to fix, not something to skip.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping, Union

import yaml

from pipeline._backend import series_key
from pipeline.group.decide import Decision
from pipeline.group.types import OVERRIDE_RUNG, Membership


class OverrideError(ValueError):
    pass


@dataclass(frozen=True)
class MergeWorks:
    survivor: str
    losers: tuple[str, ...]


@dataclass(frozen=True)
class SplitWork:
    work: str
    editions: tuple[str, ...]

    @property
    def new_work(self) -> str:
        """The split-off work's id: not a real OL id, but stable and unique."""
        return f"{self.work}~{min(self.editions)}"


@dataclass(frozen=True)
class SetSeries:
    work: str
    series: str
    position: float | None = None
    name: str | None = None


@dataclass(frozen=True)
class RemoveFromSeries:
    work: str
    series: str


@dataclass(frozen=True)
class RejectSeries:
    series: str


@dataclass(frozen=True)
class RenameSeries:
    series: str
    name: str


Override = Union[MergeWorks, SplitWork, SetSeries, RemoveFromSeries, RejectSeries, RenameSeries]


def normalize_series_key(raw: str) -> str:
    prefix, sep, rest = str(raw).partition(":")
    rest = rest.strip()
    if not sep or prefix not in ("wd", "ol") or not rest:
        raise OverrideError(f"series must be 'wd:Q…' or 'ol:<name>', got {raw!r}")
    return f"wd:{rest}" if prefix == "wd" else f"ol:{series_key(rest)}"


def _position(raw) -> float | None:
    return None if raw is None else float(raw)


def _merge_works(body) -> MergeWorks:
    if not isinstance(body, list) or len(body) < 2:
        raise OverrideError("needs a list of at least two work ids")
    return MergeWorks(body[0], tuple(body[1:]))


def _split_work(body) -> SplitWork:
    if not body.get("editions"):
        raise OverrideError("needs at least one edition")
    return SplitWork(body["work"], tuple(body["editions"]))


_PARSERS: dict[str, Callable[[object], Override]] = {
    "merge_works": _merge_works,
    "split_work": _split_work,
    "set_series": lambda b: SetSeries(b["work"], normalize_series_key(b["series"]),
                                      _position(b.get("position")), b.get("name")),
    "remove_from_series": lambda b: RemoveFromSeries(b["work"], normalize_series_key(b["series"])),
    "reject_series": lambda b: RejectSeries(normalize_series_key(b)),
    "rename_series": lambda b: RenameSeries(normalize_series_key(b["series"]), str(b["name"])),
}


def load_overrides(directory: Path) -> list[Override]:
    found: list[Override] = []
    for path in sorted(directory.glob("*.yaml")):
        entries = yaml.safe_load(path.read_text(encoding="utf-8")) or []
        if not isinstance(entries, list):
            raise OverrideError(f"{path.name}: expected a list of entries")
        for index, entry in enumerate(entries):
            where = f"{path.name}[{index}]"
            if not isinstance(entry, dict) or len(entry) != 1:
                raise OverrideError(f"{where}: each entry is a single-key mapping")
            ((kind, body),) = entry.items()
            if kind not in _PARSERS:
                raise OverrideError(f"{where}: unknown override {kind!r}")
            try:
                found.append(_PARSERS[kind](body))
            except OverrideError as exc:
                raise OverrideError(f"{where}: {kind}: {exc}") from None
            except (KeyError, TypeError, ValueError, AttributeError) as exc:
                raise OverrideError(f"{where}: {kind}: malformed ({exc!r})") from None
    return found


def _follow(aliases: Mapping[str, str], ol_id: str) -> str:
    seen = {ol_id}
    while ol_id in aliases and aliases[ol_id] not in seen:
        ol_id = aliases[ol_id]
        seen.add(ol_id)
    return ol_id


@dataclass
class IdentityPlan:
    aliases: dict[str, str]  # loser -> final survivor
    splits: list[SplitWork]
    edition_work: dict[str, str]  # edition -> final work


def apply_identity(overrides: list[Override], works: set[str], edition_work: Mapping[str, str],
                   aliases: Mapping[str, str]) -> IdentityPlan:
    """Fold ``merge_works`` and ``split_work`` into the duplicate-detection result."""
    merged = dict(aliases)
    splits: list[SplitWork] = []
    for op in overrides:
        if isinstance(op, MergeWorks):
            for ol_id in (op.survivor, *op.losers):
                if ol_id not in works:
                    raise OverrideError(f"merge_works: unknown work {ol_id}")
            survivor = _follow(merged, op.survivor)
            for loser in op.losers:
                loser = _follow(merged, loser)
                if loser != survivor:
                    merged[loser] = survivor
        elif isinstance(op, SplitWork):
            if op.work not in works:
                raise OverrideError(f"split_work: unknown work {op.work}")
            splits.append(op)
    final = {loser: _follow(merged, loser) for loser in merged}
    moved = {e: final.get(w, w) for e, w in edition_work.items()}
    for op in splits:
        owner = final.get(op.work, op.work)
        for edition in op.editions:
            if moved.get(edition) != owner:
                raise OverrideError(f"split_work: edition {edition} is not an edition of {op.work}")
            moved[edition] = op.new_work
    return IdentityPlan(final, splits, moved)


def series_rejects(overrides: list[Override]) -> set[str]:
    return {op.series for op in overrides if isinstance(op, RejectSeries)}


def apply_series(overrides: list[Override], decision: Decision, works: set[str],
                 resolve: Callable[[str], str] = lambda w: w) -> None:
    """Apply set/remove/rename (rejects were fed to ``decide``), validating each."""
    for op in overrides:
        if isinstance(op, RejectSeries):
            if op.series not in decision.known_series:
                raise OverrideError(f"reject_series: no series {op.series} in this build")
        elif isinstance(op, SetSeries):
            work = resolve(op.work)
            if work not in works:
                raise OverrideError(f"set_series: unknown work {op.work}")
            if op.series not in decision.known_series:
                if not (op.series.startswith("ol:") and op.name):
                    raise OverrideError(f"set_series: no series {op.series}; give a name to create an ol: series")
                decision.known_series.add(op.series)
                decision.names[op.series] = op.name
            decision.memberships.setdefault(work, {})[op.series] = Membership(op.series, op.position, OVERRIDE_RUNG)
            decision.decided_by[work] = OVERRIDE_RUNG
        elif isinstance(op, RemoveFromSeries):
            work = resolve(op.work)
            if work not in works:
                raise OverrideError(f"remove_from_series: unknown work {op.work}")
            if op.series not in decision.known_series:
                raise OverrideError(f"remove_from_series: no series {op.series} in this build")
            ms = decision.memberships.get(work, {})
            ms.pop(op.series, None)
            if not ms:
                decision.decided_by[work] = None
        elif isinstance(op, RenameSeries):
            if op.series not in decision.known_series:
                raise OverrideError(f"rename_series: no series {op.series} in this build")
            decision.names[op.series] = op.name
```

`pipeline/overrides/README.md`:

````markdown
# Overrides

Manual corrections, applied on every build and always winning (spec §5.4).
Each `*.yaml` file here is a list; files are read in name order. Series keys
are `wd:Q…` or `ol:<name>` (the name is normalized, so casing and punctuation
do not matter).

```yaml
- merge_works: [OL123W, OL456W]              # the rest merge into the first
- split_work: {work: OL789W, editions: [OL1M, OL2M]}   # new work id: OL789W~OL1M
- set_series: {work: OL27448W, series: "wd:Q45875", position: 3}
- set_series: {work: OL1W, series: "ol:lord of the rings", position: 1, name: "The Lord of the Rings"}
- remove_from_series: {work: OL27448W, series: "ol:dune"}
- reject_series: "ol:penguin classics"
- rename_series: {series: "wd:Q45875", name: "A Song of Ice and Fire"}
```

An entry that names a work or series the build does not hold fails the run:
a stale override is a bug to fix, not something to skip. Say why in a comment
above each entry — the next reader cannot see the report you were looking at.
````

- [ ] **Step 4: Run the test**

Run: `cd pipeline && .venv/bin/python -m pytest tests/test_overrides.py -v`
Expected: PASS (13 tests).

- [ ] **Step 5: Commit**

```bash
git add pipeline/overrides.py pipeline/overrides/README.md pipeline/tests/test_overrides.py
git commit -m "feat(pipeline): validated manual overrides"
```

---

### Task 17: The group stage

**Files:**
- Create: `pipeline/stages/group.py`
- Test: `pipeline/tests/test_stage_group.py`

**Interfaces:**
- Consumes: every `pipeline/group/` module, `overrides`, extract's tables and schemas, fetch's `wd_*`, `raw_editions`, `raw_work_redirects`, `raw_work_aliases`.
- Produces: `representative(editions, work_cover) -> ol_edition_id | None`; `G_WORKS_SCHEMA`; tables `g_works` (extract's columns + `primary_author, room, representative_edition`), `g_editions` (EDITIONS_SCHEMA, `work_ol_id` final), `g_series(key, name, source, provenance, kind, parent_key)`, `g_members(series_key, work_ol_id, position, provenance, confidence)`, `g_aliases(ol_id, work_ol_id)`, `g_decisions(work_ol_id, rung)`, `g_imprints(key, author_clusters)`, `g_author_clusters(ol_author_id, cluster_id)`.
  `source` is `wikidata | openlibrary | heuristic`; `provenance` is the app's `series_provenance_enum` vocabulary.

Merged losers' popularity is summed into the survivor. Every work without a membership gets `single:<ol_id>` as its room. `test_an_override_moves_a_book_and_survives_the_rerun` proves corrections survive re-runs.

- [ ] **Step 1: Write the failing test**

`pipeline/tests/test_stage_group.py`:

```python
import pytest

from pipeline.stages import extract, fetch, group, select
from pipeline.stages.group import representative


@pytest.fixture
def grouped(world_ctx):
    for stage in (fetch, select, extract, group):
        stage.run(world_ctx)
    return world_ctx


def members(con, key):
    return con.execute("SELECT work_ol_id, position FROM g_members WHERE series_key = ? ORDER BY position, work_ol_id",
                       [key]).fetchall()


def room(con, ol):
    return con.execute("SELECT room FROM g_works WHERE ol_id = ?", [ol]).fetchone()[0]


def test_wikidata_series_gains_its_edition_string_member(grouped):
    assert members(grouped.con, "wd:Q45875") == [("OL10W", 1.0), ("OL11W", 2.0), ("OL12W", 3.0), ("OL13W", 4.0)]


def test_one_series_across_two_author_spellings(grouped):
    key = "ol:remembrance of earth s past"
    assert members(grouped.con, key) == [("OL20W", 1.0), ("OL21W", 2.0), ("OL22W", 3.0)]


def test_red_rising_is_ordered_merged_and_keeps_adaptations_out(grouped):
    con = grouped.con
    assert members(con, "ol:red rising") == [("OL30W", 1.0), ("OL31W", 2.0), ("OL32W", 3.0), ("OL33W", 4.0), ("OL34W", 5.0)]
    assert room(con, "OL35W") == "single:OL35W"
    aliases = dict(con.execute("SELECT ol_id, work_ol_id FROM g_aliases").fetchall())
    assert aliases == {"OL36W": "OL30W", "OL99W": "OL30W"}
    assert con.execute("SELECT count(*) FROM g_works WHERE ol_id = 'OL36W'").fetchone() == (0,)
    assert con.execute("SELECT readinglog_count FROM g_works WHERE ol_id = 'OL30W'").fetchone() == (6,)


def test_imprints_are_rejected(grouped):
    con = grouped.con
    assert con.execute("SELECT key, author_clusters FROM g_imprints").fetchall() == [("ol:penguin classics", 4)]
    assert room(con, "OL50W") == "single:OL50W"


def test_a_thin_universe_is_not_a_room(grouped):
    con = grouped.con
    assert {room(con, w) for w in ("OL60W", "OL61W", "OL62W")} == {"wd:Q15228"}
    assert con.execute("SELECT parent_key FROM g_series WHERE key = 'wd:Q15228'").fetchone() == (None,)
    assert con.execute("SELECT count(*) FROM g_series WHERE key = 'wd:Q81'").fetchone() == (0,)


def test_every_work_has_a_room_and_every_room_a_series(grouped):
    con = grouped.con
    orphans = con.execute("SELECT count(*) FROM g_works w LEFT JOIN g_series s ON s.key = w.room "
                          "WHERE s.key IS NULL").fetchone()
    assert orphans == (0,)


def test_an_override_moves_a_book_and_survives_the_rerun(grouped):
    (grouped.overrides_dir / "fixes.yaml").write_text(
        '- set_series: {work: OL63W, series: "wd:Q15228", position: 0}\n', encoding="utf-8")
    group.run(grouped)
    assert room(grouped.con, "OL63W") == "wd:Q15228"
    assert members(grouped.con, "wd:Q15228")[0] == ("OL63W", 0.0)


def test_representative_prefers_the_curated_cover():
    editions = [
        {"ol_id": "OL1M", "cover_id": 5, "isbn_13": "x", "page_count": 1},
        {"ol_id": "OL2M", "cover_id": 9, "isbn_13": None, "page_count": None},
        {"ol_id": "OL3M", "cover_id": None, "isbn_13": "x", "page_count": 1},
    ]
    assert representative(editions, work_cover=9) == "OL2M"
    assert representative(editions, work_cover=None) == "OL1M"
    assert representative([], None) is None
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd pipeline && .venv/bin/python -m pytest tests/test_stage_group.py -v`
Expected: FAIL — `No module named 'pipeline.stages.group'`.

- [ ] **Step 3: Implement**

`pipeline/stages/group.py`:

```python
"""group (spec §5): author clusters, duplicates, the ladder, overrides, rooms."""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Mapping, Sequence

import pyarrow as pa
import yaml

from pipeline._backend import clean_title
from pipeline.config import BuildContext
from pipeline.db import swap_in, write_table
from pipeline.group.authors import AuthorRec, cluster_authors
from pipeline.group.decide import decide
from pipeline.group.duplicates import DupWork, find_duplicates
from pipeline.group.nesting import rooms
from pipeline.group.types import CONFIDENCE, PROVENANCE, GWork, WdMembership, WdSeries
from pipeline.overrides import apply_identity, apply_series, load_overrides, series_rejects
from pipeline.sources.load_raw import resolver
from pipeline.stages.extract import EDITIONS_SCHEMA, WORKS_SCHEMA

_OL_NUMBER = re.compile(r"\d+")
_SUMMED = ("ratings_count", "readinglog_count", "edition_count")
G_WORKS_SCHEMA = WORKS_SCHEMA.append(pa.field("primary_author", pa.string())).append(
    pa.field("room", pa.string())).append(pa.field("representative_edition", pa.string()))


def _number(ol_id: str) -> int:
    match = _OL_NUMBER.search(ol_id)
    return int(match.group()) if match else 0


def representative(editions: Sequence[Mapping], work_cover: int | None) -> str | None:
    """The edition that speaks for the work: its curated cover, then any cover, ISBN, pages."""
    if not editions:
        return None
    return min(editions, key=lambda e: (
        e["cover_id"] is None or e["cover_id"] != work_cover, e["cover_id"] is None,
        e["isbn_13"] is None, e["page_count"] is None, _number(e["ol_id"])))["ol_id"]


def _table(con, sql: str) -> list[dict]:
    cursor = con.execute(sql)
    columns = [d[0] for d in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def run(ctx: BuildContext) -> None:
    con = ctx.con
    overrides = load_overrides(ctx.overrides_dir)
    blocklist = yaml.safe_load((ctx.rules_dir / "imprints.yaml").read_text(encoding="utf-8")) or []

    works = {w["ol_id"]: w for w in _table(con, "SELECT * FROM works ORDER BY ol_id")}
    editions = _table(con, "SELECT * FROM editions ORDER BY ol_id")
    clusters = cluster_authors(
        [AuthorRec(a["ol_id"], a["name"], tuple(a["alternate_names"]), a["wikidata"])
         for a in _table(con, "SELECT * FROM authors ORDER BY ol_id")],
        con.execute("SELECT qid, ol_author_id FROM wd_author_ids").fetchall(),
        con.execute("SELECT qid, name FROM wd_author_names").fetchall(),
    )

    resolve_work = resolver(dict(con.execute("SELECT from_ol, to_ol FROM raw_work_redirects").fetchall()))
    edition_owner = dict(con.execute("SELECT ol_id, work_ol_id FROM raw_editions").fetchall())
    memberships: list[WdMembership] = []
    wd_items: dict[str, set[str]] = defaultdict(set)
    wd_by_edition: dict[str, set[str]] = defaultdict(set)
    for item, series, ordinal, ol_id in con.execute("SELECT item, series, ordinal, ol_id FROM wd_memberships").fetchall():
        memberships.append(WdMembership(item, series, ordinal))
        if ol_id.endswith("M"):
            wd_by_edition[ol_id].add(item)
        work = resolve_work(ol_id) if ol_id.endswith("W") else edition_owner.get(ol_id)
        if work:
            wd_items[work].add(item)
    wd_series = {r["qid"]: WdSeries(r["qid"], r["label"], tuple(r["aliases"]), tuple(r["parents"]))
                 for r in _table(con, "SELECT * FROM wd_series")}

    def primary(work: Mapping) -> str | None:
        return clusters.get(work["author_ids"][0]) if work["author_ids"] else None

    by_work: dict[str, list[dict]] = defaultdict(list)
    for e in editions:
        by_work[e["work_ol_id"]].append(e)

    # 5.2 — duplicates, then identity overrides.
    dups = find_duplicates([
        DupWork(ol, primary(w), clean_title(w["title"]), w["kind"], frozenset(wd_items[ol]),
                frozenset(clean_title(e["title"]) for e in by_work[ol]), w["readinglog_count"] + w["edition_count"])
        for ol, w in works.items()
    ])
    plan = apply_identity(overrides, set(works), {e["ol_id"]: e["work_ol_id"] for e in editions}, dups)
    final: dict[str, dict] = {ol: dict(w) for ol, w in works.items() if ol not in plan.aliases}
    for loser, survivor in sorted(plan.aliases.items()):
        for field in _SUMMED:
            final[survivor][field] += works[loser][field]
        wd_items[survivor] |= wd_items[loser]
    for split in plan.splits:
        first = next(e for e in editions if e["ol_id"] == min(split.editions))
        source = final[plan.aliases.get(split.work, split.work)]
        final[split.new_work] = {**source, "ol_id": split.new_work, "raw_title": first["title"],
                                 "title": first["title"], "subtitle": first["subtitle"], "subjects": None,
                                 "cover_id": first["cover_id"], "ratings_count": 0, "readinglog_count": 0,
                                 "edition_count": len(split.editions)}
        wd_items[split.new_work] = set().union(*(wd_by_edition[e] for e in split.editions))
    for e in editions:
        e["work_ol_id"] = plan.edition_work[e["ol_id"]]
    by_work = defaultdict(list)
    for e in editions:
        by_work[e["work_ol_id"]].append(e)

    # 5.3 — the ladder, its guards, series overrides, rooms.
    gworks = [
        GWork(ol, (w["raw_title"], *(e["title"] for e in by_work[ol])), primary(w), w["kind"], w["subjects"],
              tuple(tuple(e["series"]) for e in by_work[ol]), frozenset(wd_items[ol]), w["first_publish_year"])
        for ol, w in sorted(final.items())
    ]
    decision = decide(gworks, memberships, wd_series, blocklist, series_rejects(overrides))
    apply_series(overrides, decision, set(final), resolve=lambda ol: plan.aliases.get(ol, ol))
    parents = {f"wd:{q}": f"wd:{min(s.parents)}" for q, s in wd_series.items() if s.parents}
    room, parent_of = rooms({w: ms.keys() for w, ms in decision.memberships.items()}, parents)

    series_rows, member_rows = [], []
    rungs: dict[str, list[int]] = defaultdict(list)
    for work, ms in sorted(decision.memberships.items()):
        for key, m in sorted(ms.items()):
            rungs[key].append(m.rung)
            member_rows.append({"series_key": key, "work_ol_id": work, "position": m.position,
                                "provenance": PROVENANCE[m.rung], "confidence": CONFIDENCE[m.rung]})
    for key, parent in sorted(parent_of.items()):
        if key.startswith("wd:"):
            source, provenance = "wikidata", "wikidata"
        else:
            real = [r for r in rungs[key] if r > 0]
            source, provenance = "openlibrary", PROVENANCE[min(real)] if real else "override"
        series_rows.append({"key": key, "name": decision.names.get(key, key), "source": source,
                            "provenance": provenance, "kind": "series", "parent_key": parent})
    for ol, w in sorted(final.items()):
        if ol not in room:
            room[ol] = f"single:{ol}"
            series_rows.append({"key": room[ol], "name": w["title"], "source": "heuristic",
                                "provenance": "single", "kind": "singleton", "parent_key": None})

    redirect_aliases = con.execute("SELECT from_ol, to_ol FROM raw_work_aliases").fetchall()
    aliases = dict(plan.aliases)
    for old, target in redirect_aliases:
        survivor = plan.aliases.get(target, target)
        if survivor in final and old not in final:
            aliases[old] = survivor

    g_works = [{**w, "primary_author": primary(w), "room": room[ol],
                "representative_edition": representative(by_work[ol], w["cover_id"])}
               for ol, w in sorted(final.items())]
    write_table(con, "g_works", pa.Table.from_pylist(g_works, schema=G_WORKS_SCHEMA))
    write_table(con, "g_editions", pa.Table.from_pylist(editions, schema=EDITIONS_SCHEMA))
    write_table(con, "g_series", pa.Table.from_pylist(series_rows, schema=pa.schema([
        ("key", pa.string()), ("name", pa.string()), ("source", pa.string()), ("provenance", pa.string()),
        ("kind", pa.string()), ("parent_key", pa.string())])))
    write_table(con, "g_members", pa.Table.from_pylist(member_rows, schema=pa.schema([
        ("series_key", pa.string()), ("work_ol_id", pa.string()), ("position", pa.float64()),
        ("provenance", pa.string()), ("confidence", pa.string())])))
    write_table(con, "g_aliases", pa.table({"ol_id": pa.array(sorted(aliases), pa.string()),
                                            "work_ol_id": pa.array([aliases[k] for k in sorted(aliases)], pa.string())}))
    write_table(con, "g_decisions", pa.table({
        "work_ol_id": pa.array(sorted(decision.decided_by), pa.string()),
        "rung": pa.array([decision.decided_by[k] for k in sorted(decision.decided_by)], pa.int8())}))
    write_table(con, "g_imprints", pa.table({
        "key": pa.array(sorted(decision.rejected), pa.string()),
        "author_clusters": pa.array([decision.rejected[k] for k in sorted(decision.rejected)], pa.int32())}))
    write_table(con, "g_author_clusters", pa.table({
        "ol_author_id": pa.array(sorted(clusters), pa.string()),
        "cluster_id": pa.array([clusters[k] for k in sorted(clusters)], pa.string())}))
    swap_in(con, ["g_works", "g_editions", "g_series", "g_members", "g_aliases",
                  "g_decisions", "g_imprints", "g_author_clusters"])
```

- [ ] **Step 4: Run the test**

Run: `cd pipeline && .venv/bin/python -m pytest tests/test_stage_group.py -v`
Expected: PASS (8 tests): ASOIAF gains *A Feast for Crows* at #4; *Remembrance of Earth's Past* spans both spellings of Liu Cixin; Red Rising is 1–5 with *Dark Age* last despite its 2015 year; *Sons of Ares* is a singleton; Penguin Classics is rejected.

- [ ] **Step 5: Commit**

```bash
git add pipeline/stages/group.py pipeline/tests/test_stage_group.py
git commit -m "feat(pipeline): group stage — clusters, duplicates, ladder, overrides, rooms"
```

---

### Task 18: The golden set gate

**Files:**
- Create: `pipeline/golden.py`, `pipeline/golden/series.yaml`, `pipeline/golden/README.md`
- Test: `pipeline/tests/test_golden.py`

**Interfaces:**
- Produces: `THRESHOLD = 0.95`; `GoldenGateError`; `GoldenSeries(name, members)`; `MemberRow(work, position, first_publish_year, title)`; `GoldenResult(total, membership_ok, order_ok, failures)` with `membership_rate`/`order_rate`; `load_golden(path)`; `reading_order(rows) -> list[work]`; `evaluate(golden, members: Mapping[key, Sequence[MemberRow]], resolve=…) -> GoldenResult`; `gate(result, threshold=THRESHOLD)`; `draft_from_wikidata(con, qid) -> str`.
- The `golden-draft` subcommand in `pipeline/__main__.py` (Task 2) now works.

`reading_order` is the series page's order (position, first publication, title), so the gate tests what readers will see. An empty golden set fails the gate — `series.yaml` ships empty and must be curated before the first real release (Task 21).

- [ ] **Step 1: Write the failing test**

`pipeline/tests/test_golden.py`:

```python
import pytest

from pipeline.golden import GoldenGateError, GoldenResult, GoldenSeries, MemberRow, evaluate, gate, reading_order


def row(work, position=None, year=None, title="t"):
    return MemberRow(work, position, year, title)


MEMBERS = {
    "ol:red rising": [row("OL34W", 5.0, 2015), row("OL30W", 1.0, 2014), row("OL31W", 2.0, 2015)],
    "wd:Q1": [row("OL60W", None, 1954, "The Fellowship of the Ring"), row("OL62W", None, 1955, "The Return")],
}


def test_reading_order_is_position_then_year_then_title():
    assert reading_order(MEMBERS["ol:red rising"]) == ["OL30W", "OL31W", "OL34W"]
    assert reading_order([row("B", None, 2000, "b"), row("A", None, 2000, "a"), row("C", 1.0, 2020)]) == ["C", "A", "B"]


def test_exact_membership_and_order_pass():
    result = evaluate([GoldenSeries("Red Rising", ("OL30W", "OL31W", "OL34W"))], MEMBERS)
    assert (result.membership_ok, result.order_ok, result.failures) == (1, 1, [])


def test_missing_members_and_wrong_order_are_reported():
    result = evaluate([GoldenSeries("RR", ("OL30W", "OL31W", "OL33W", "OL34W")),
                       GoldenSeries("LOTR", ("OL62W", "OL60W"))], MEMBERS)
    assert result.membership_ok == 1 and result.order_ok == 0
    assert "missing ['OL33W']" in result.failures[0]
    assert "order" in result.failures[1]


def test_merged_ids_resolve_through_aliases():
    aliases = {"OL36W": "OL30W"}
    result = evaluate([GoldenSeries("RR", ("OL36W", "OL31W", "OL34W"))], MEMBERS,
                      resolve=lambda w: aliases.get(w, w))
    assert (result.membership_ok, result.order_ok) == (1, 1)


def test_a_series_nobody_landed_in_fails():
    result = evaluate([GoldenSeries("Dune", ("OL1W",))], MEMBERS)
    assert result.failures == ["Dune: none of its works is in any series"]


def test_gate_thresholds():
    gate(GoldenResult(total=20, membership_ok=19, order_ok=19))
    with pytest.raises(GoldenGateError, match="membership 90.0%"):
        gate(GoldenResult(total=10, membership_ok=9, order_ok=10))
    with pytest.raises(GoldenGateError, match="empty"):
        gate(GoldenResult())


def test_draft_lists_wikidata_members_in_ordinal_order(world_ctx):
    from pipeline.golden import draft_from_wikidata
    from pipeline.stages import extract, fetch, select

    for stage in (fetch, select, extract):
        stage.run(world_ctx)
    draft = draft_from_wikidata(world_ctx.con, "Q45875")
    assert draft.splitlines()[0] == "- name: 'A Song of Ice and Fire'"
    members = [line.split("#")[0].strip(" -") for line in draft.splitlines() if line.startswith("    - ")]
    assert members == ["OL10W", "OL11W", "OL12W"]
    assert "verified_by: ''" in draft
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd pipeline && .venv/bin/python -m pytest tests/test_golden.py -v`
Expected: FAIL — `No module named 'pipeline.golden'`.

- [ ] **Step 3: Implement**

`pipeline/golden.py`:

```python
"""The golden set (spec §7.1): widely read series with known members and order.

``publish`` refuses to write a release unless at least 95% of golden series
have exactly the expected membership and 95% exactly the expected order.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Mapping, Sequence

import yaml

THRESHOLD = 0.95


class GoldenGateError(RuntimeError):
    pass


@dataclass(frozen=True)
class GoldenSeries:
    name: str
    members: tuple[str, ...]  # OL work ids, in reading order


@dataclass(frozen=True)
class MemberRow:
    work: str
    position: float | None
    first_publish_year: int | None
    title: str


@dataclass
class GoldenResult:
    total: int = 0
    membership_ok: int = 0
    order_ok: int = 0
    failures: list[str] = field(default_factory=list)

    @property
    def membership_rate(self) -> float:
        return self.membership_ok / self.total if self.total else 0.0

    @property
    def order_rate(self) -> float:
        return self.order_ok / self.total if self.total else 0.0


def load_golden(path: Path) -> list[GoldenSeries]:
    entries = yaml.safe_load(path.read_text(encoding="utf-8")) if path.exists() else None
    return [GoldenSeries(e["name"], tuple(e["members"])) for e in entries or []]


def reading_order(rows: Sequence[MemberRow]) -> list[str]:
    """The series page's order: position, then first publication, then title."""
    return [r.work for r in sorted(rows, key=lambda r: (
        r.position is None, r.position or 0.0,
        r.first_publish_year is None, r.first_publish_year or 0, r.title, r.work))]


def evaluate(golden: Sequence[GoldenSeries], members: Mapping[str, Sequence[MemberRow]],
             resolve: Callable[[str], str] = lambda w: w) -> GoldenResult:
    """Compare each golden series with the release series most of its works landed in."""
    series_of: dict[str, set[str]] = defaultdict(set)
    for key, rows in members.items():
        for row in rows:
            series_of[row.work].add(key)
    result = GoldenResult(total=len(golden))
    for g in golden:
        expected = [resolve(w) for w in g.members]
        votes = Counter(k for w in expected for k in series_of[w])
        if not votes:
            result.failures.append(f"{g.name}: none of its works is in any series")
            continue
        key = min(votes, key=lambda k: (-votes[k], k))
        actual = reading_order(members[key])
        if set(actual) == set(expected):
            result.membership_ok += 1
        else:
            missing = sorted(set(expected) - set(actual))
            extra = sorted(set(actual) - set(expected))
            result.failures.append(f"{g.name} ({key}): missing {missing}, unexpected {extra}")
        if actual == expected:
            result.order_ok += 1
        elif set(actual) == set(expected):
            result.failures.append(f"{g.name} ({key}): order {actual}, expected {expected}")
    return result


def gate(result: GoldenResult, threshold: float = THRESHOLD) -> None:
    if result.total == 0:
        raise GoldenGateError("the golden set is empty; see pipeline/golden/README.md")
    if result.membership_rate < threshold or result.order_rate < threshold:
        detail = "\n  ".join(result.failures)
        raise GoldenGateError(
            f"golden set: membership {result.membership_rate:.1%}, order {result.order_rate:.1%} "
            f"(need {threshold:.0%})\n  {detail}")


def draft_from_wikidata(con, qid: str) -> str:
    """A golden entry drafted from Wikidata's own ordinals, for a human to verify.

    Drafted from the fetched Wikidata rows, never from the pipeline's grouping
    output: a golden set built from the output would only test itself.
    """
    from pipeline.group.ladder import parse_ordinal
    from pipeline.sources.load_raw import resolver

    resolve = resolver(dict(con.execute("SELECT from_ol, to_ol FROM raw_work_redirects").fetchall()))
    owner = dict(con.execute("SELECT ol_id, work_ol_id FROM raw_editions").fetchall())
    titles = dict(con.execute("SELECT ol_id, title FROM works").fetchall())
    label = con.execute("SELECT label FROM wd_series WHERE qid = ?", [qid]).fetchone()
    found: dict[str, float | None] = {}
    for ol_id, ordinal in con.execute("SELECT ol_id, ordinal FROM wd_memberships WHERE series = ?", [qid]).fetchall():
        work = resolve(ol_id) if ol_id.endswith("W") else owner.get(ol_id)
        if work:
            position = parse_ordinal(ordinal)
            found[work] = position if found.get(work) is None else found[work]
    ordered = sorted(found, key=lambda w: (found[w] is None, found[w] or 0.0, w))
    lines = [f"- name: {(label[0] if label else qid)!r}", f"  # drafted from wd:{qid}; verify against the author's or publisher's list",
             "  verified_by: ''", "  members:"]
    lines += [f"    - {w}  # {found[w] if found[w] is not None else '?'}: {titles.get(w, 'NOT IN CATALOG')}" for w in ordered]
    return "\n".join(lines) + "\n"
```

`pipeline/golden/series.yaml`:

```yaml
# The golden set (spec §7.1): publish fails below 95% exact membership or
# 95% exact order. See README.md for how to add an entry. Empty until curated —
# which means publish refuses to run until it is.
[]
```

`pipeline/golden/README.md`:

````markdown
# Golden set

`series.yaml` lists widely read series with their expected members (OL work
ids) in reading order. `publish` refuses to write a release unless at least
95% of entries have exactly the expected membership and 95% exactly the
expected order.

## Adding an entry

1. Run a build to at least `extract` (`python -m pipeline run --to extract`).
2. For a series Wikidata knows, draft it: `python -m pipeline golden-draft Q45875`.
   The draft comes from Wikidata's own ordinals, never from the pipeline's
   grouping — a golden set drawn from the output would only test itself.
3. Verify every member and the order against an outside source (the author's
   or publisher's series list, or the Wikipedia series article). Fix ids from
   <https://openlibrary.org/search?q=…>. Record the source in `verified_by`.
4. For a series Wikidata does not know, write the entry by hand the same way.

```yaml
- name: A Song of Ice and Fire
  verified_by: "https://georgerrmartin.com/… (checked 2026-10-02)"
  members: [OL257943W, OL257945W, OL257944W, OL2617213W, OL8479867W]
```

Order is what the series page shows: `position`, then first publication year,
then title. A member missing from the catalog, an extra member, or a wrong
order each fail the entry; the report lists every failure.

## Target coverage (~150 series)

Fantasy: A Song of Ice and Fire · The Lord of the Rings · Harry Potter · The
Wheel of Time · Mistborn · The Stormlight Archive · The Kingkiller Chronicle ·
Discworld · The Chronicles of Narnia · Earthsea · The Witcher · The First Law ·
The Broken Earth · The Dark Tower · Malazan Book of the Fallen · The Farseer
Trilogy · The Liveship Traders · Shadow and Bone · Six of Crows · A Court of
Thorns and Roses · Throne of Glass · Gentleman Bastard · The Poppy War · His
Dark Materials · The Inheritance Cycle · The Sword of Truth · The Belgariad ·
The Dresden Files · Shannara · Dragonlance Chronicles · The Black Company ·
Wayward Children · The Locked Tomb · The Green Bone Saga · Kushiel's Legacy ·
Codex Alera · The Riyria Revelations · The Night Angel Trilogy

Science fiction: Dune · Foundation · The Expanse · Remembrance of Earth's Past
· Red Rising · Hyperion Cantos · Ender's Saga · The Hitchhiker's Guide to the
Galaxy · The Murderbot Diaries · Imperial Radch · Culture · Revelation Space ·
Old Man's War · Wayfarers · Children of Time · Robot series · Rendezvous with
Rama · Vorkosigan Saga · Honor Harrington · The Interdependency · Bobiverse ·
Silo · The Space Trilogy · Xenogenesis · Commonwealth Saga

Young adult and children's: The Hunger Games · Divergent · The Maze Runner ·
Percy Jackson and the Olympians · The Heroes of Olympus · The Kane Chronicles ·
Twilight · The Mortal Instruments · A Series of Unfortunate Events · Diary of
a Wimpy Kid · The Chronicles of Prydain · Artemis Fowl · Alex Rider · The
Selection · Red Queen · Shatter Me · Miss Peregrine's Peculiar Children ·
Keeper of the Lost Cities · Wings of Fire · Warriors · The Giver Quartet ·
Anne of Green Gables · Little House · Redwall · The Raven Cycle · Lockwood &
Co. · Arc of a Scythe · Uglies · Legend · The 5th Wave · The Illuminae Files ·
Leviathan · The Lunar Chronicles · Graceling Realm

Romance: Bridgerton · Outlander · Fifty Shades · The Kiss Quotient · Off-Campus
· Ice Planet Barbarians · Virgin River · Chicago Stars · Rosemary Beach ·
Crossfire · The Hathaways · Wallflowers · Psy-Changeling · Black Dagger
Brotherhood · Twisted · Beautiful Disaster · After · The Brown Sisters ·
Bromance Book Club · Scoundrels (Loretta Chase)

Mystery and thriller: Jack Reacher · Millennium · Harry Bosch · Alex Cross ·
Hercule Poirot · Miss Marple · Sherlock Holmes · Cormoran Strike · Chief
Inspector Gamache · Harry Hole · Dublin Murder Squad · Robert Langdon · Jason
Bourne · Stephanie Plum · Kinsey Millhone · Lincoln Rhyme · Jack Ryan · Mitch
Rapp · Thursday Murder Club · Dirk Pitt · Kay Scarpetta · Rizzoli & Isles ·
Temperance Brennan · Lord Peter Wimsey · Maigret · Inspector Rebus · Department
Q

Classics and literary: In Search of Lost Time · The Forsyte Saga · The
Alexandria Quartet · Neapolitan Novels · Wolf Hall trilogy · Chronicles of
Barsetshire · Palliser novels · Leatherstocking Tales · Rabbit Angstrom · The
Border Trilogy · Gormenghast · The Raj Quartet · Aubrey–Maturin · Horatio
Hornblower · Poldark · The Cairo Trilogy · A Dance to the Music of Time ·
Earth's Children · The Cazalet Chronicles · Lonesome Dove · The Saxon Stories ·
Sharpe · Kingsbridge · The Century Trilogy
````

- [ ] **Step 4: Run the test**

Run: `cd pipeline && .venv/bin/python -m pytest tests/test_golden.py -v`
Expected: PASS (7 tests).

- [ ] **Step 5: Commit**

```bash
git add pipeline/golden.py pipeline/golden pipeline/tests/test_golden.py
git commit -m "feat(pipeline): golden set evaluation, release gate and Wikidata drafts"
```

---

### Task 19: Publish: release tables, report, manifest, upload

**Files:**
- Create: `pipeline/release.py`, `pipeline/report.py`, `pipeline/stages/publish.py`
- Test: `pipeline/tests/test_end_to_end.py`

**Interfaces:**
- Consumes: `contract.SCHEMAS`, `ids.*`, the `g_*` tables, `golden.*`.
- Produces (`release`): `cover_url(cover_id)`; `build_release(con) -> dict[name, pa.Table]` in contract schemas, sorted by identity; text columns clipped to 500 characters (the app's `String(500)`).
- Produces (`report`): `TOP_WORKS = 5000`, `MAX_MEMBERS = 40`; `position_problems(positions) -> list[str]`; `render(con, version, golden, slugs, previous) -> str`.
- Produces (`publish`): `PublishError`; `version_key(v) -> (y, m, n)`; `previous_release(releases_dir, version) -> Path | None`; `git_commit()`; `golden_result(ctx)`; `upload(release, version, run=subprocess.run)` — tars to `releases/catalog-<v>.tar.gz` (top folder `catalog-<v>/`) and runs `gh release create catalog-<v> <tarball> --title … --notes-file …`; `run(ctx)`.
- **Release layout** (consumed by plan 2's loader): `releases/catalog-<version>/{works,editions,series,series_members,work_aliases}.parquet`, `report.md`, `manifest.json` with keys `version, schema_version, pipeline_commit, sources, row_counts, files` (`files` maps every other file to its SHA-256).

The golden gate runs before anything is written; files are written to `.catalog-<v>.partial/` and renamed into place, so a crash never leaves a half release. The manifest carries no timestamps of its own, so a re-run reproduces it.

- [ ] **Step 1: Write the failing end-to-end test**

`pipeline/tests/test_end_to_end.py`:

```python
"""The whole pipeline over the fixture world, twice: byte-identical releases."""

import json

import pyarrow.parquet as pq
import pytest
import respx

from pipeline import runner
from pipeline.golden import GoldenGateError
from pipeline.stages import publish
from pipeline.stages.publish import PublishError, previous_release
from pipeline.tests.conftest import make_ctx
from pipeline.tests.fixtures import world

PARQUET = ["editions", "series", "series_members", "work_aliases", "works"]


def build(tmp_path, name, version="2026.10.1", releases=None):
    base = tmp_path / name
    base.mkdir()
    with respx.mock(assert_all_called=False) as router:
        world.serve(router)
        ctx = make_ctx(base, version=version, releases=releases)
        runner.run(ctx)
    return ctx, ctx.releases_dir / f"catalog-{version}"


def test_two_runs_produce_byte_identical_parquet(tmp_path):
    _, first = build(tmp_path, "a")
    _, second = build(tmp_path, "b")
    for name in PARQUET:
        assert (first / f"{name}.parquet").read_bytes() == (second / f"{name}.parquet").read_bytes(), name


def test_the_release_folder_holds_the_contract(tmp_path):
    _, release = build(tmp_path, "a")
    assert sorted(p.name for p in release.iterdir()) == sorted(
        [f"{n}.parquet" for n in PARQUET] + ["manifest.json", "report.md"])
    manifest = json.loads((release / "manifest.json").read_text())
    assert manifest["version"] == "2026.10.1" and manifest["schema_version"] == 1
    assert {s["name"] for s in manifest["sources"]} == {"ratings", "reading_log", "works", "authors", "editions", "wikidata"}
    assert set(manifest["files"]) == {f"{n}.parquet" for n in PARQUET} | {"report.md"}
    series = {s["key"]: s for s in pq.read_table(release / "series.parquet").to_pylist()}
    assert series["wd:Q45875"]["slug"] == "a-song-of-ice-and-fire"
    assert series["single:OL63W"]["kind"] == "singleton"
    works = {w["ol_work_id"]: w for w in pq.read_table(release / "works.parquet").to_pylist()}
    assert works["OL30W"]["series_id"] == series["ol:red rising"]["id"]
    assert "OL36W" not in works
    report = (release / "report.md").read_text()
    for heading in ("## Golden set", "## Select drops", "## Imprint rejections", "## Suspicious series"):
        assert heading in report


def test_a_release_is_never_overwritten(tmp_path):
    ctx, _ = build(tmp_path, "a")
    with pytest.raises(PublishError, match="immutable"):
        publish.run(ctx)


def test_a_golden_regression_blocks_the_release(tmp_path):
    base = tmp_path / "a"
    base.mkdir()
    with respx.mock(assert_all_called=False) as router:
        world.serve(router)
        ctx = make_ctx(base)
        ctx.golden_path.write_text("- name: Red Rising\n  members: [OL31W, OL30W]\n")
        with pytest.raises(GoldenGateError):
            runner.run(ctx)
    assert not ctx.releases_dir.exists() or not any(ctx.releases_dir.iterdir())


def test_a_second_release_reports_its_diff(tmp_path):
    releases = tmp_path / "releases"
    build(tmp_path, "a", "2026.10.1", releases)
    _, second = build(tmp_path, "b", "2026.11.1", releases)
    assert previous_release(releases, "2026.11.1").name == "catalog-2026.10.1"
    assert "Compared with `catalog-2026.10.1`." in (second / "report.md").read_text()


def test_upload_attaches_a_tarball_to_a_tagged_release(tmp_path):
    _, release = build(tmp_path, "a")
    calls = []
    publish.upload(release, "2026.10.1", run=lambda args, check: calls.append(args))
    assert calls[0][:4] == ["gh", "release", "create", "catalog-2026.10.1"]
    assert (release.parent / "catalog-2026.10.1.tar.gz").exists()
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd pipeline && .venv/bin/python -m pytest tests/test_end_to_end.py -v`
Expected: FAIL — `No module named 'pipeline.stages.publish'`.

- [ ] **Step 3: Implement**

`pipeline/release.py`:

```python
"""Build the release tables from the group stage's output (spec §4.5)."""

from __future__ import annotations

from typing import Callable

import duckdb
import pyarrow as pa

from pipeline.contract import SCHEMAS

from pipeline.ids import assign_slugs, edition_identity, row_id, series_identity, work_identity
from pipeline._backend import series_key

# The app's column widths (String(500) and friends); longer values would fail the load.
_TEXT_LIMIT = 500


def _clip(value: str | None, limit: int = _TEXT_LIMIT) -> str | None:
    return value[:limit] if value is not None else None


def cover_url(cover_id: int | None) -> str | None:
    return f"https://covers.openlibrary.org/b/id/{cover_id}-L.jpg" if cover_id else None


def _rows(con: duckdb.DuckDBPyConnection, sql: str) -> list[dict]:
    cursor = con.execute(sql)
    columns = [d[0] for d in cursor.description]
    return [dict(zip(columns, r)) for r in cursor.fetchall()]


def build_release(con: duckdb.DuckDBPyConnection) -> dict[str, pa.Table]:
    """The five release tables, from the group stage's output, in identity order."""
    work_id: Callable[[str], str] = lambda ol: row_id(work_identity(ol))  # noqa: E731
    sid: Callable[[str], str] = lambda key: row_id(series_identity(key))  # noqa: E731

    series = _rows(con, "SELECT * FROM g_series ORDER BY key")
    slugs = assign_slugs({series_identity(s["key"]): s["name"] for s in series})
    works = _rows(con, "SELECT * FROM g_works ORDER BY ol_id")
    authors = {w["ol_id"]: w["author"] for w in works}
    editions = _rows(con, "SELECT * FROM g_editions ORDER BY ol_id")
    members = _rows(con, "SELECT * FROM g_members ORDER BY series_key, work_ol_id")
    aliases = _rows(con, "SELECT * FROM g_aliases ORDER BY ol_id")

    tables = {
        "works": [{
            "id": work_id(w["ol_id"]), "ol_work_id": w["ol_id"], "canonical_key": w["canonical_key"],
            "title": _clip(w["title"]), "subtitle": _clip(w["subtitle"]), "author": _clip(w["author"]),
            "first_publish_year": w["first_publish_year"], "kind": w["kind"], "series_id": sid(w["room"]),
            "ol_cover_id": w["cover_id"], "ol_edition_count": w["edition_count"],
            "readinglog_count": w["readinglog_count"], "ratings_count": w["ratings_count"],
            "subjects": w["subjects"],
            "representative_edition_id": row_id(edition_identity(w["representative_edition"]))
            if w["representative_edition"] else None,
        } for w in works],
        "editions": [{
            "id": row_id(edition_identity(e["ol_id"])), "ol_edition_id": e["ol_id"],
            "work_id": work_id(e["work_ol_id"]), "title": _clip(e["title"]) or "Untitled",
            "subtitle": _clip(e["subtitle"]), "author": _clip(authors[e["work_ol_id"]]),
            "publisher": _clip(e["publisher"]), "published_year": e["publish_year"], "isbn_13": e["isbn_13"],
            "page_count": e["page_count"], "cover_url": cover_url(e["cover_id"]), "language": "en",
        } for e in editions],
        "series": [{
            "id": sid(s["key"]), "key": s["key"], "source": s["source"], "provenance": s["provenance"],
            "name": _clip(s["name"]), "slug": slugs[series_identity(s["key"])],
            "canonical_key": series_key(s["name"]), "kind": s["kind"],
            "parent_series_id": sid(s["parent_key"]) if s["parent_key"] else None,
        } for s in series],
        "series_members": [{
            "series_id": sid(m["series_key"]), "work_id": work_id(m["work_ol_id"]), "position": m["position"],
            "provenance": m["provenance"], "confidence": m["confidence"],
        } for m in members],
        "work_aliases": [{"ol_work_id": a["ol_id"], "work_id": work_id(a["work_ol_id"])} for a in aliases],
    }
    return {name: pa.Table.from_pylist(rows, schema=SCHEMAS[name]) for name, rows in tables.items()}
```

`pipeline/report.py`:

```python
"""``report.md`` (spec §7.2): what a reviewer reads before loading a release."""

from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path

import duckdb
import pyarrow.parquet as pq

from pipeline.golden import GoldenResult
from pipeline.group.types import PROVENANCE

TOP_WORKS = 5000
MAX_MEMBERS = 40
_LIST_LIMIT = 50


def _table(header: tuple[str, ...], rows) -> list[str]:
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    lines += ["| " + " | ".join(str(c) for c in row) + " |" for row in rows]
    return lines


def _clipped(items: list[str]) -> list[str]:
    extra = len(items) - _LIST_LIMIT
    return items[:_LIST_LIMIT] + ([f"- … and {extra} more"] if extra > 0 else [])


def position_problems(positions: list[float | None]) -> list[str]:
    known = [p for p in positions if p is not None]
    problems = []
    dupes = sorted(p for p, n in Counter(known).items() if n > 1)
    if dupes:
        problems.append("duplicate positions " + ", ".join(f"{p:g}" for p in dupes))
    whole = {int(p) for p in known if p == int(p)}
    if whole:
        gaps = sorted(set(range(min(whole), max(whole) + 1)) - whole)
        if gaps:
            problems.append("gaps at " + ", ".join(str(g) for g in gaps))
    return problems


def _previous_rooms(previous: Path) -> tuple[dict[str, str], dict[str, str], dict[str, str]]:
    """(ol work id -> series key, ol alias -> work id, series key -> slug) from an older release."""
    series = pq.read_table(previous / "series.parquet").to_pylist()
    key_of = {s["id"]: s["key"] for s in series}
    works = pq.read_table(previous / "works.parquet").to_pylist()
    aliases = pq.read_table(previous / "work_aliases.parquet").to_pylist()
    return ({w["ol_work_id"]: key_of[w["series_id"]] for w in works},
            {a["ol_work_id"]: a["work_id"] for a in aliases},
            {s["key"]: s["slug"] for s in series})


def render(con: duckdb.DuckDBPyConnection, version: str, golden: GoldenResult,
           slugs: dict[str, str], previous: Path | None) -> str:
    out = [f"# Catalog release {version}", ""]

    out += ["## Golden set", "",
            f"- membership: {golden.membership_ok}/{golden.total} ({golden.membership_rate:.1%})",
            f"- order: {golden.order_ok}/{golden.total} ({golden.order_rate:.1%})"]
    out += [f"- {f}" for f in golden.failures] + [""]

    counts = [(t, con.execute(f"SELECT count(*) FROM {t}").fetchone()[0]) for t in (
        "raw_works", "selected", "works", "editions", "g_works", "g_series", "g_members", "g_aliases")]
    out += ["## Row counts", ""] + _table(("table", "rows"), counts) + [""]
    drops = con.execute("SELECT rule, count(*) FROM select_drops GROUP BY rule ORDER BY rule").fetchall()
    out += ["## Select drops", ""] + _table(("rule", "works"), drops) + [""]

    rungs = con.execute(f"""
        SELECT d.rung FROM g_decisions d JOIN g_works w ON w.ol_id = d.work_ol_id
        ORDER BY w.readinglog_count DESC, w.ol_id LIMIT {TOP_WORKS}""").fetchall()
    tally = Counter("singleton" if r is None else PROVENANCE[r] for (r,) in rungs)
    total = sum(tally.values()) or 1
    out += [f"## Deciding rung ({TOP_WORKS:,} most-read works)", ""]
    out += _table(("rung", "works", "share"), [(k, n, f"{n / total:.1%}") for k, n in sorted(tally.items())]) + [""]

    imprints = con.execute("SELECT key, author_clusters FROM g_imprints ORDER BY key").fetchall()
    out += ["## Imprint rejections", ""] + _table(("series", "author clusters"), imprints) + [""]

    members: dict[str, list[tuple[float | None, str | None]]] = defaultdict(list)
    for key, position, author in con.execute("""
            SELECT m.series_key, m.position, w.primary_author FROM g_members m
            JOIN g_works w ON w.ol_id = m.work_ol_id ORDER BY m.series_key, m.work_ol_id""").fetchall():
        members[key].append((position, author))
    suspicious = []
    for key, rows in sorted(members.items()):
        problems = []
        if len(rows) > MAX_MEMBERS:
            problems.append(f"{len(rows)} members")
        authors = {a for _, a in rows if a}
        if len(authors) > 1:
            problems.append(f"{len(authors)} author clusters")
        problems += position_problems([p for p, _ in rows])
        if problems:
            suspicious.append(f"- `{key}`: " + "; ".join(problems))
    out += ["## Suspicious series", ""] + (_clipped(suspicious) or ["None."]) + [""]

    out += ["## Changes since the previous release", ""]
    if previous is None:
        out += ["First release.", ""]
        return "\n".join(out)
    old_rooms, old_aliases, old_slugs = _previous_rooms(previous)
    rooms = dict(con.execute("SELECT ol_id, room FROM g_works").fetchall())
    aliases = dict(con.execute("SELECT ol_id, work_ol_id FROM g_aliases").fetchall())
    moved = [f"- {ol}: `{old}` → `{rooms[ol]}`" for ol, old in sorted(old_rooms.items())
             if ol in rooms and rooms[ol] != old]
    merged = [f"- {ol} → {aliases[ol]}" for ol in sorted(aliases) if ol not in old_aliases]
    gone = [f"- {ol}" for ol in sorted(old_rooms) if ol not in rooms and ol not in aliases]
    reslugged = [f"- `{k}`: {s} → {slugs[k]}" for k, s in sorted(old_slugs.items()) if k in slugs and slugs[k] != s]
    out += [f"Compared with `{previous.name}`.", ""]
    for title, items in (("Changed series", moved), ("Newly merged", merged),
                         ("Disappeared", gone), ("Slug changes", reslugged)):
        out += [f"### {title} ({len(items)})", ""] + (_clipped(items) or ["None."]) + [""]
    return "\n".join(out)
```

`pipeline/stages/publish.py`:

```python
"""publish (spec §4.5): gate on the golden set, write an immutable release folder."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import tarfile
from collections import defaultdict
from pathlib import Path
from typing import Callable

import pyarrow.parquet as pq

from pipeline import report
from pipeline.config import REPO, SCHEMA_VERSION, BuildContext
from pipeline.golden import MemberRow, evaluate, gate, load_golden
from pipeline.release import build_release

VERSION = re.compile(r"^(\d{4})\.(\d{2})\.(\d+)$")


class PublishError(RuntimeError):
    pass


def version_key(version: str) -> tuple[int, int, int]:
    match = VERSION.match(version)
    if not match:
        raise PublishError(f"release version must be YYYY.MM.N, got {version!r}")
    return tuple(int(g) for g in match.groups())  # type: ignore[return-value]


def previous_release(releases_dir: Path, version: str) -> Path | None:
    older = []
    for path in releases_dir.glob("catalog-*"):
        candidate = path.name.removeprefix("catalog-")
        if path.is_dir() and VERSION.match(candidate) and version_key(candidate) < version_key(version):
            older.append((version_key(candidate), path))
    return max(older)[1] if older else None


def git_commit() -> str:
    try:
        head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO, capture_output=True, text=True, check=True).stdout.strip()
        dirty = subprocess.run(["git", "status", "--porcelain"], cwd=REPO, capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"
    return f"{head}-dirty" if dirty else head


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def golden_result(ctx: BuildContext):
    con = ctx.con
    members: dict[str, list[MemberRow]] = defaultdict(list)
    for key, work, position, year, title in con.execute("""
            SELECT m.series_key, m.work_ol_id, m.position, w.first_publish_year, w.title
            FROM g_members m JOIN g_works w ON w.ol_id = m.work_ol_id""").fetchall():
        members[key].append(MemberRow(work, position, year, title))
    aliases = dict(con.execute("SELECT ol_id, work_ol_id FROM g_aliases").fetchall())
    return evaluate(load_golden(ctx.golden_path), members, resolve=lambda w: aliases.get(w, w))


def upload(release: Path, version: str, run: Callable = subprocess.run) -> None:
    """Attach ``catalog-<version>.tar.gz`` to a GitHub Release tagged ``catalog-<version>``."""
    tag = f"catalog-{version}"
    tarball = release.parent / f"{tag}.tar.gz"
    with tarfile.open(tarball, "w:gz") as tar:
        tar.add(release, arcname=tag)
    manifest = json.loads((release / "manifest.json").read_text())
    notes = release.parent / f"{tag}.notes.md"
    notes.write_text("\n".join(
        [f"Catalog release {version} (schema {manifest['schema_version']}, pipeline {manifest['pipeline_commit']}).", ""]
        + [f"- {name}: {n:,} rows" for name, n in sorted(manifest["row_counts"].items())]
        + ["", "Sources:"] + [f"- {s['name']}: {s['url']} ({s['retrieved']})" for s in manifest["sources"]]) + "\n")
    run(["gh", "release", "create", tag, str(tarball), "--title", tag, "--notes-file", str(notes)], check=True)


def run(ctx: BuildContext) -> None:
    if not ctx.version:
        raise PublishError("publish needs a release version")
    version_key(ctx.version)
    final = ctx.releases_dir / f"catalog-{ctx.version}"
    if final.exists():
        raise PublishError(f"{final} already exists; a release folder is immutable, publish a new version")

    result = golden_result(ctx)
    gate(result)  # before anything is written

    tables = build_release(ctx.con)
    partial = ctx.releases_dir / f".catalog-{ctx.version}.partial"
    shutil.rmtree(partial, ignore_errors=True)
    partial.mkdir(parents=True)
    for name, table in tables.items():
        pq.write_table(table, partial / f"{name}.parquet", compression="zstd")
    slugs = dict(zip(tables["series"].column("key").to_pylist(), tables["series"].column("slug").to_pylist()))
    (partial / "report.md").write_text(
        report.render(ctx.con, ctx.version, result, slugs, previous_release(ctx.releases_dir, ctx.version)),
        encoding="utf-8")

    cursor = ctx.con.execute("SELECT * FROM sources ORDER BY name")
    columns = [d[0] for d in cursor.description]
    manifest = {
        "version": ctx.version,
        "schema_version": SCHEMA_VERSION,
        "pipeline_commit": git_commit(),
        "sources": [dict(zip(columns, r)) for r in cursor.fetchall()],
        "row_counts": {name: table.num_rows for name, table in sorted(tables.items())},
        "files": {p.name: _sha256(p) for p in sorted(partial.iterdir())},
    }
    (partial / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    partial.rename(final)
    if ctx.upload:
        upload(final, ctx.version)
```

- [ ] **Step 4: Run the test**

Run: `cd pipeline && .venv/bin/python -m pytest tests/test_end_to_end.py -v`
Expected: PASS (6 tests), including `test_two_runs_produce_byte_identical_parquet`.

- [ ] **Step 5: Run the whole pipeline suite**

Run: `cd pipeline && .venv/bin/python -m pytest -q`
Expected: 153 passed.

- [ ] **Step 6: Commit**

```bash
git add pipeline/release.py pipeline/report.py pipeline/stages/publish.py pipeline/tests/test_end_to_end.py
git commit -m "feat(pipeline): publish gated, reproducible releases with a quality report"
```

---

### Task 20: CI job and documentation

**Files:**
- Modify: `.github/workflows/ci.yml` (new `pipeline-tests` job)
- Modify: `CLAUDE.md` (commands and architecture for `pipeline/`)

**Interfaces:**
- Consumes: everything above. Produces no code.

- [ ] **Step 1: Add the CI job**

Apply with `git apply` (save the block to a file first), or make the same edits by hand.

```diff
--- a/.github/workflows/ci.yml
+++ b/.github/workflows/ci.yml
@@ -48,6 +48,29 @@
         env:
           DATABASE_URL: postgresql+asyncpg://margin:margin@localhost:5432/margin_test
           SECRET_KEY: ci-test-secret
+        run: python -m pytest -v
+
+  pipeline-tests:
+    runs-on: ubuntu-latest
+    if: github.event_name == 'push' || github.event_name == 'pull_request'
+    defaults:
+      run:
+        working-directory: pipeline
+
+    steps:
+      - uses: actions/checkout@v4
+
+      - uses: actions/setup-python@v5
+        with:
+          python-version: "3.12"
+          cache: pip
+          cache-dependency-path: pipeline/requirements.txt
+
+      - name: Install dependencies
+        run: pip install -r requirements.txt
+
+      # Fixture dumps and Wikidata responses only: no test touches the network.
+      - name: Run pytest
         run: python -m pytest -v
 
   frontend-tests:
```

- [ ] **Step 2: Document the pipeline**

Apply with `git apply`, or make the same edits by hand.

````diff
--- a/CLAUDE.md
+++ b/CLAUDE.md
@@ -58,6 +58,24 @@
 npx playwright install         # one-time
 npm run test:e2e               # auth flow is network-free; thread/reply use live Google Books search
 ```
+
+### Catalog pipeline
+
+`pipeline/` builds the catalog offline from Open Library dumps and Wikidata and
+publishes a versioned release; production only loads releases. It has its own
+dependencies and never connects to the app database. From `pipeline/`:
+
+```bash
+python -m venv .venv && .venv/bin/pip install -r requirements.txt   # one-time
+.venv/bin/python -m pytest                                          # fixture dumps only, no network
+cd .. && pipeline/.venv/bin/python -m pipeline run --version 2026.10.1          # full build (~20 GB free disk)
+pipeline/.venv/bin/python -m pipeline run --from group --version 2026.10.1      # resume from a stage
+pipeline/.venv/bin/python -m pipeline golden-draft Q45875                       # draft a golden entry
+```
+
+Working state is `build/catalog.duckdb`; releases land in `releases/catalog-<version>/`
+(both git-ignored). `--upload` attaches the release to a GitHub Release via `gh`
+(NordVPN breaks `gh` — disconnect first).
 
 ### Subagents & roadmap
 
@@ -232,6 +250,31 @@
 - **No star ratings or user reviews.** This is a product decision, not an
   oversight — see `docs/visual-identity.md` §1 and `margin_spec.md`.
 
+### Catalog pipeline (`pipeline/`)
+
+Five stages, `fetch → select → extract → group → publish`, each reading only
+the previous stage's DuckDB tables and writing `tmp_*` tables it swaps in on
+success (`db.swap_in`), so a crash leaves no partial stage. The pipeline
+imports only the backend's **pure** rule modules (`work_identity`,
+`series_identity`, `text`) through `pipeline/_backend.py` — keep those free of
+settings, HTTP and ORM imports (`tests/test_pure_imports.py` enforces it).
+
+- **Grouping** lives in `pipeline/group/` as pure functions: author clusters,
+  duplicate works, the four-rung series ladder (Wikidata → OL tags → edition
+  `series` strings → title patterns), its guards (imprints, folding,
+  adaptations) and nesting. Stage modules are thin DuckDB wrappers around them.
+- **Rules and corrections are data**: `pipeline/rules/junk.yaml`,
+  `pipeline/rules/imprints.yaml`, and `pipeline/overrides/*.yaml`. An override
+  referencing anything the build does not hold fails the run.
+- **Ids are deterministic** (`ids.py`, `uuid5` over `MARGIN_NS`): never change
+  the namespace. Output is sorted by identity, and two runs over the same
+  inputs produce byte-identical Parquet (asserted in `test_end_to_end.py`).
+- **The release contract** is `pipeline/contract.py`; the loader's `COLUMNS`
+  must match it (`backend/tests/test_catalog_contract.py`). Change both and
+  bump `SCHEMA_VERSION` together.
+- **`publish` is gated** on `pipeline/golden/series.yaml`: it refuses to write
+  a release below 95% exact membership or 95% exact order.
+
 ## Conventions & gotchas
 
 - **API prefix**: all routers are mounted under `/api` in `main.py` (each router keeps its own resource prefix, e.g. `/api/auth/login`, `/api/genres/`). This matches the frontend's axios `baseURL: '/api'` and the vite dev proxy. New routers must be `include_router(..., prefix="/api")` and registered in `main.py`. The only non-`/api` route is `GET /` (returns the app name).
````

- [ ] **Step 3: Check the workflow parses**

Run: `python3 -c "import yaml,sys; yaml.safe_load(open('.github/workflows/ci.yml'))"`
Expected: no output.

- [ ] **Step 4: Commit**

```bash
git add .github/workflows/ci.yml CLAUDE.md
git commit -m "ci: run the pipeline suite; docs: document the catalog pipeline"
```

---

### Task 21: Curate the golden set and cut the first release (manual)

**Files:**
- Modify: `pipeline/golden/series.yaml` (≥150 verified entries)
- Create: `pipeline/overrides/*.yaml` (as the report requires)

**Interfaces:**
- Consumes: the whole pipeline. This task runs against the live sources and needs a human for verification.

This is data work, not code. It cannot be delegated to the pipeline itself: a golden set drafted from the pipeline's own output would only test itself.

- [ ] **Step 1: Run the first live build up to extract**

From the repository root, on a machine with ≥20 GB free and a stable connection (the dumps are several GB; the editions stream alone runs for hours):

```bash
pipeline/.venv/bin/python -m pipeline run --to extract
```

Expected: `build/catalog.duckdb` with the raw, `selected`, `works`, `editions` and `authors` tables. If Wikidata pages time out repeatedly, rerun with `WIKIDATA_SPARQL_URL=https://qlever.cs.uni-freiburg.de/api/wikidata` (same SPARQL, no 60-second limit).

- [ ] **Step 2: Draft and verify ~150 golden entries**

Work through the target list in `pipeline/golden/README.md`. For each series Wikidata knows:

```bash
pipeline/.venv/bin/python -m pipeline golden-draft Q45875 >> /tmp/golden-draft.yaml
```

Verify every member and the order against an outside source (the author's or publisher's list, or the Wikipedia series article), fix OL ids from `https://openlibrary.org/search?q=…`, fill `verified_by`, and move the entry into `pipeline/golden/series.yaml`. Write entries for series Wikidata does not know by hand the same way. Never copy membership from the pipeline's output.

- [ ] **Step 3: Group and read the report**

```bash
pipeline/.venv/bin/python -m pipeline run --from group --version 2026.10.1
```

If the golden gate fails, the error lists each failing series. Read `releases/catalog-2026.10.1/report.md` when it passes. For every flagged item — an imprint that is a real series, a suspicious series, a gap — either add an override with a comment explaining why, or file the rule change it points to.

- [ ] **Step 4: Re-run after overrides until the gate passes**

```bash
rm -rf releases/catalog-2026.10.1
pipeline/.venv/bin/python -m pipeline run --from group --version 2026.10.1
```

Expected: `publish` completes; the report shows ≥95% golden membership and order.

- [ ] **Step 5: Upload the release**

Disconnect NordVPN first (it reroutes `api.github.com` and `gh` hangs), then:

```bash
pipeline/.venv/bin/python -m pipeline run --from publish --version 2026.10.1 --upload
```

(`publish` refuses an existing folder, so delete `releases/catalog-2026.10.1` first, or upload the existing folder with `python -c "from pathlib import Path; from pipeline.stages.publish import upload; upload(Path('releases/catalog-2026.10.1'), '2026.10.1')"`.) Expected: a GitHub Release `catalog-2026.10.1` with the tarball attached.

- [ ] **Step 6: Commit**

```bash
git add pipeline/golden/series.yaml pipeline/overrides
git commit -m "data(pipeline): golden set and overrides for catalog 2026.10.1"
```
