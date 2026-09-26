# Catalog pipeline — design

**Status:** approved design, not yet planned
**Date:** 2026-09-26
**Supersedes (for grouping):** the ingest-time series detection in
`2026-09-24-series-as-discussion-home-design.md`. That spec's *model* — the
series is the room, a work is a book tag inside it, every work has a series —
stays. What changes is where grouping decisions are made.

## 1. Why

Series grouping is built one search at a time, from whatever a single Open
Library response happens to contain. Measured against the dev catalog on
2026-09-26:

- **Missing members.** *A Song of Ice and Fire* has books 1–3; *A Feast for
  Crows* and *A Dance with Dragons* were never ingested, so nothing could
  group them.
- **No series evidence.** Tolkien's *Fellowship*, *Two Towers* and *Return of
  the King* are three singletons; the only Tolkien series detected is *The
  History of Middle-earth*, because that is what OL's `series:` tags said.
  *The Dark Forest* and *Death's End* are singletons whose series lives only
  in their title text, under a different author spelling (刘慈欣) from book 1
  (Cixin Liu).
- **No order.** There is no position column. *Red Rising* has the right
  members in the wrong order, and OL's `first_publish_year` cannot fix it
  (*Dark Age* is stored as 2015; it was published in 2019).
- **Noise.** Calendars, colouring books, study guides, RPG sourcebooks and
  physics monographs share titles with the books readers mean.

These are three separate problems — coverage, series evidence, order — and
only a whole-catalog, offline build addresses all three. The product bar is
Goodreads/Reddit: a wrong series makes the app barely functional.

## 2. Goals and non-goals

**Goals**
- Every English work that someone has read (see §4.2) is in the catalog
  before anyone searches for it.
- Each work belongs to the right series, in the right order, with the
  decision traceable to its evidence.
- The build runs **once, offline**, and ships as a **versioned, tagged
  release** that production loads as seed data. Production never runs the
  pipeline.
- Re-running produces byte-identical output from the same inputs; a new
  release updates rows in place without breaking threads or shelves.
- Manual corrections survive every re-run.

**Non-goals (this spec)**
- The librarian UI (it will write the overrides format defined in §5.4).
- Automated monthly refresh.
- An `authors` table or author pages in the app.
- Typo-tolerant search.
- Languages other than English.
- Any AI classification service. An LLM may later adjudicate ambiguous
  clusters from data we hold; it is not part of this design.

## 3. Sources

| Source | Used for |
|---|---|
| OL ratings dump, reading-log dump | Selecting the "read" set; popularity counts |
| OL works dump | Titles, subjects, cover ids, author keys |
| OL authors dump | Name variants (`alternate_names`, `remote_ids`) |
| OL editions dump (streamed, filtered) | Language (English filter), ISBNs, `series` strings, page counts, edition covers |
| Wikidata (paged SPARQL) | Series membership (P179), ordinal (P1545), series nesting (P361 / P179 on the series), OL work/edition/author ids (P648), author aliases |

Wikidata is the highest-precision series source but covers only notable
books, carries no popularity or language data, and has no covers or
descriptions — so it is the series layer, and Open Library is the catalog.

## 4. Pipeline

A new top-level package `pipeline/`, beside `backend/`, with its own
dependencies (DuckDB, pyarrow, httpx). It imports only the **pure** rule
modules from the backend (`app.services.work_identity`,
`app.services.series_identity`) and never connects to the app database. All
working state lives in `build/catalog.duckdb` (git-ignored).

```
fetch ──► select ──► extract ──► group ──► publish
```

Each stage reads only the previous stage's tables, writes to temporary
tables, and swaps them in on success, so a crash leaves no partial stage.
`python -m pipeline run --from <stage>` resumes from any stage without
re-fetching.

### 4.1 fetch

- Downloads the OL ratings, reading-log, works and authors dumps to
  `build/raw/`, resumably (HTTP Range) with checksum verification and
  backoff.
- Streams the editions dump through a filter while downloading: an edition is
  kept only if its language includes `eng` and its work is in the selected set
  (select runs on the other dumps first, then editions are streamed). The
  unfiltered editions file never lands on disk — the build machine has ~20 GB
  free.
- Pulls Wikidata with paged SPARQL: every item with P179 (part of the
  series), its P1545 ordinal, its P648 OL ids, every series item with its
  label, aliases and parent series, and aliases for authors carrying P648.
  Pages retry with backoff; a failed page aborts the stage.
- Records every source in a `sources` table: name, URL, dump date or
  retrieval timestamp, byte size, SHA-256.

### 4.2 select

The **read set**: works with at least one OL reading-log or rating entry, or
a Wikidata item linked by P648. Of those, keep works with at least one
English edition, then drop junk:

- no author;
- all editions under 40 pages;
- calendars, diaries, colouring books (title and subject patterns);
- theses, dissertations, government documents (subjects, publisher
  patterns);
- study guides and summaries (`Summary of …`, `Analysis of …`,
  `study guides` subject).

Patterns live in `pipeline/rules/junk.yaml` so they are reviewable data, not
code.

### 4.3 extract

Normalises works, editions and subjects into the build tables `works`,
`editions`, `authors`. Subjects are stored one per line (`join_subjects`), as
in the app. Titles use `work_identity.display_title` for display and
`clean_title`/`canonical_key` for keys.

### 4.4 group

See §5.

### 4.5 publish

Writes `releases/catalog-YYYY.MM.N/` (git-ignored):

```
manifest.json      version, schema_version, pipeline git commit,
                   sources (from the sources table), row counts,
                   SHA-256 of every file
works.parquet
editions.parquet
series.parquet
series_members.parquet
work_aliases.parquet
report.md          quality report (§7.2)
```

A release folder is immutable once written. `--upload` tars it and attaches
it to a GitHub Release tagged `catalog-YYYY.MM.N`, with the manifest summary
as release notes. That tag is the unit production loads.

### 4.6 Deterministic identity

Every row id is `uuid5(MARGIN_NS, <identity string>)`:

| Row | Identity string |
|---|---|
| work | `work:ol:OL27448W` (the surviving OL work id) |
| edition | `edition:ol:OL7353617M` |
| series (Wikidata) | `series:wd:Q45875` |
| series (OL evidence) | `series:ol:<series_key(name)>` |
| singleton | `series:single:OL27448W` |

The same book gets the same UUID in every environment and every release.
Slugs are derived deterministically too (name slug; collisions broken by
sorting on identity string and suffixing `-2`, `-3`).

Output ordering is fixed (sort by identity string) so Parquet files are
byte-identical across runs of the same inputs.

## 5. Grouping

Four steps, in order.

### 5.1 Author clusters

Union OL author records (`alternate_names`, `remote_ids`) with Wikidata
author aliases, joined on OL author ids, into clusters: 刘慈欣 = Cixin Liu =
Liu Cixin. Every author comparison below is between clusters, not strings. A
work's *primary author* is the cluster of its first listed author.

### 5.2 Duplicate works

Two OL works merge when they share a primary-author cluster and a
`canonical_key`, **unless** each is linked to a distinct Wikidata item (then
they are different books). Collections (`classify_kind == 'collection'`)
never merge into single works.

Survivor, in order: the Wikidata-linked work; higher `readinglog_count +
edition_count`; lower OL id. Every loser's OL id is written to
`work_aliases`.

### 5.3 Series decision ladder

Each work takes membership from the highest rung with evidence:

| Rung | Evidence | Confidence |
|---|---|---|
| 1 | Wikidata P179 (+ P1545), matched via the work's P648, or via P648 on one of its editions | high |
| 2 | OL `franchise:` / `series:` subjects; `choose_container` with tag counts over the **whole** catalog | medium |
| 3 | OL edition `series` strings — `Name ; 2`, `Name, #2`, `Name (2)`, `Name, book 2` — majority vote across the work's English editions | medium |
| 4 | Title patterns — `(X Series Book 2)`, `X #2`, `Book 2 of X` | low |
| — | nothing: a singleton | — |

Guards:

- **Imprint filter.** A rung 2–4 candidate series whose works span more than
  three author clusters is a publisher imprint (*Penguin Classics*, *A Del
  Rey book*) and is rejected. `pipeline/rules/imprints.yaml` is a blocklist
  backstop.
- **Adaptation filter.** A work joins a series only if its primary-author
  cluster is the series' dominant author cluster, unless Wikidata (rung 1)
  says otherwise. Graphic-novel adaptations, companions and game books by
  other authors stay out.
- **Folding.** A rung 2–4 series folds into a Wikidata series when their
  `series_key` names match, or when ≥50% of its members are already members
  of that Wikidata series.
- **Nesting.** Wikidata parent relations produce `parent_series_id`. A
  work's **room** (`works.series_id`) is the top of its chain, but a parent
  becomes a room only if it has ≥2 direct works or ≥2 child series — a
  sprawling "universe" item cannot swallow unrelated books.
- **Position** comes from the highest rung that supplies one. Duplicate
  positions and gaps are kept and flagged in the report, never guessed.
  Positions are numeric (novellas at 2.5); unnumbered members are null.
- **Collections** may be members of a series with `position = null`.

### 5.4 Overrides

`pipeline/overrides/*.yaml`, checked into the repo, is applied after the
ladder and always wins:

```yaml
- merge_works: [OL123W, OL456W]              # second merges into first
- split_work: {work: OL789W, editions: [OL1M, OL2M]}
- set_series: {work: OL27448W, series: "wd:Q45875", position: 3}
- remove_from_series: {work: OL27448W, series: "ol:dune"}
- reject_series: "ol:penguin classics"
- rename_series: {series: "wd:Q45875", name: "A Song of Ice and Fire"}
```

Each entry is validated (referenced ids must exist in the build); an invalid
entry fails the run rather than being skipped. The later librarian tools
only need to write this format.

## 6. App schema and loading

### 6.1 Schema changes (one Alembic migration)

- **`catalog_releases`** (new): `version` (PK, e.g. `2026.10.1`),
  `manifest` (JSONB), `loaded_at`.
- **`works`**: add `catalog_release` (FK → `catalog_releases.version`,
  nullable; null = created at runtime).
- **`series`**: add `catalog_release` (nullable), `parent_series_id`
  (self-FK, nullable), and extend `series_source_enum` with `wikidata`;
  add `provenance` (`wikidata`, `ol_tag`, `ol_edition_series`,
  `title_pattern`, `single`, `override`).
- **`series_members`** (new): `series_id`, `work_id`, `position NUMERIC
  NULL`, `provenance`, `confidence` (`high`/`medium`/`low`); unique
  `(series_id, work_id)`.
- **`work_aliases`** (new): `ol_work_id` (PK), `work_id` (FK).
- **`books`**: no columns change. Release editions arrive with
  `source='openlibrary'`, `external_id='OL…M'`.

Per the enum gotcha in CLAUDE.md, `downgrade()` explicitly drops any new
enum types.

### 6.2 Loader — `python -m scripts.load_catalog_release <folder | tag>`

1. Resolve a tag to a downloaded folder; verify every checksum in the
   manifest and the `schema_version`. Refuse a release older than the latest
   loaded one unless `--force`.
2. `COPY` each Parquet file into a temporary staging table.
3. In **one transaction**:
   - upsert `series`, `works`, `series_members`, `books`, `work_aliases` by
     id, stamping `catalog_release`;
   - **adopt runtime rows**: a work with `catalog_release IS NULL` whose OL
     id (directly or through `work_aliases`) matches a release work is
     merged into it with `merge_works` semantics — threads, shelves and
     editions move, the runtime row is tombstoned. Heuristic runtime works
     match on `canonical_key` plus author. This is also the migration path
     for the existing dev database;
   - **rows absent from the new release**: deleted when unreferenced; kept
     when a thread or shelf references them, tombstoned onto the survivor
     when an alias exists;
   - **slugs**: release slugs win; a colliding runtime series is re-slugged
     with a numeric suffix;
   - insert the `catalog_releases` row.
4. `ANALYZE` the touched tables. `search_doc` regenerates by itself.

Loading the same release twice is a no-op.

### 6.3 Runtime behaviour after a load

- **Search** stays local-first and unchanged in code. Most queries land on
  the loaded catalog; a miss still calls Open Library once under the
  existing `search_queries` rule. Works created that way have
  `catalog_release = null` and get today's runtime series assignment; the
  next release absorbs them properly. Runtime code never moves a work out of
  a release series (consistent with the existing "never moved
  automatically" rule).
- **Enrichment** (Google editions and descriptions on first view) is
  unchanged.
- **`GET /api/series/{slug}`** returns members with `position` and grouped
  by child series.
- **Series page** orders by child series, then `position`, then
  `first_publish_year`; shows `#2` / `#2.5`; shows a child-series heading
  only where one exists. No visual redesign — existing row components and
  the design-system rules in CLAUDE.md apply.

## 7. Quality

### 7.1 Golden set (release gate)

`pipeline/golden/series.yaml` holds ~150 widely read series across genres
(fantasy, science fiction, YA, romance, thriller, classics), each with its
expected members (OL work ids) and order. `publish` **fails** if fewer than
95% of golden series have exactly the expected membership, or fewer than
95% have exactly the expected order. The set is built once and grows as
regressions are found.

### 7.2 Report (`report.md`, every release)

- Row counts per stage, and junk drops per rule.
- For the 5,000 most-read works: the share decided by each ladder rung.
- Imprint rejections.
- Suspicious series: >40 members, mixed author clusters, gaps or duplicate
  positions.
- Diff against the previous release: works that changed series, merged, or
  disappeared.

Anything flagged is resolved with an overrides entry.

## 8. Error handling

- **fetch**: resumable downloads, checksum verification, retry with
  backoff; Wikidata pages retry then abort the stage.
- **stages**: temp tables swapped in on success only.
- **overrides**: an invalid entry fails the run.
- **loader**: a single transaction; any failure rolls back completely.

## 9. Testing

- **Unit** (`pipeline/tests`): edition `series`-string parsing, title
  patterns, junk rules, imprint and adaptation filters, the ladder, folding,
  nesting/room choice, deterministic ids and slugs, overrides.
- **End-to-end on fixtures**: tiny hand-built dumps and Wikidata fixtures
  run through every stage in seconds; the test runs twice and asserts
  byte-identical Parquet.
- **Loader** (backend pytest, `margin_test`): load a fixture release;
  reload is a no-op; runtime-work adoption moves a thread; an older release
  is refused; absent rows are deleted or kept per §6.2.
- No test touches the network. CI gains a `pipeline` job.

## 10. Next steps (separate specs)

1. **Librarian tools** — in-app merge, split, move and reorder for trusted
   users, persisted as §5.4 overrides so fixes survive every release.
2. **Refresh** — monthly re-runs against new OL dumps and Wikidata, how
   releases are cut and loaded, and how books published after the last dump
   enter the catalog between releases.
