# Genre voting and search filters — design

**Status:** implemented (plan: docs/superpowers/plans/2026-09-29-genre-voting.md)
**Date:** 2026-09-29
**Follows:** `ROADMAP.md` Phase 3 ("Search filters — book search by
genre/author/year") and Phase 5 ("Genre CRUD"), which this partly absorbs.

## 1. Why

A book's genre is decided once, at ingest: `open_library.genre_slug()` takes
the first of eight flat genres whose needle appears anywhere in the subjects,
falling back to "Literary Fiction" for anything tagged plain *fiction*. Readers
cannot correct it, there is no finer grain than *Fantasy*, and search cannot
filter by it.

Readers should decide what a book is, choosing only from a curated two-level
taxonomy (genre → subgenre) — Goodreads' crowd genres without its free-text
shelves. Those votes then drive genre pages and search filters.

## 2. Goals and non-goals

**Goals**
- A curated taxonomy of top-level genres and subgenres, maintained as a
  reviewed data file.
- Any signed-in reader can tag a book with up to 5 genres from that taxonomy;
  a book's genres are ranked by how many readers tagged them.
- Books without votes still carry genres, inferred from their subjects and
  shown as inferred.
- Librarians can veto a wrong genre on a book, with a reason, undoably.
- Genre pages list books by their crowd genres, with subgenres rolling up.
- Book search can be filtered by genre, author and publication year, and
  filters alone (no text query) browse the local catalog.

**Non-goals**
- Free-text tags or reader-created genres. The picker only filters the
  curated list.
- Downvoting genres. A wrong tag sinks under right ones; an abusive one is
  vetoed.
- In-app taxonomy editing (the rest of "Genre CRUD") — the YAML file is the
  editor for now.
- Genre-based recommendations and trending (Phase 3, later; they read the
  same `work_genres` table).
- Pipeline-side genre overrides. Vetoes are runtime-only.
- Star ratings or reviews (rejected — `docs/visual-identity.md` §1).

## 3. Decisions

| # | Decision | Chosen | Why |
|---|---|---|---|
| D1 | What votes drive | Display, genre pages and search filters | Makes votes matter; replaces the one-shot ingest guess |
| D2 | Vote shape | Tag-only (+1 or withdraw) plus librarian veto | No genre fights; abuse goes through existing correction tooling |
| D3 | Unit voted on | The work, not the series | Search returns works; series genres are the sum of their books |
| D4 | Hierarchy | Vote on either level; subgenre votes roll up to the parent, one reader counted once | A book with 40 *Epic Fantasy* votes belongs on the *Fantasy* page |
| D5 | Taxonomy owner | `backend/app/data/genres.yaml`, synced by script; in-app editing later | Rarely changes; PR review for free |
| D6 | Cold start | Inferred genres, stored apart from votes and shown as inferred | Pages aren't empty on day one; readers win the moment they vote |
| D7 | Eligibility | Any signed-in reader, any book, cap of 5 genres per reader per book | Young product — don't starve the signal; the cap bounds sprays |
| D8 | Storage | Raw votes + a maintained `work_genres` summary (approach B) | One place holds the effective-genre rule; filters are an indexed join |
| D9 | Discussion rooms | Parents only | 100 subgenre rooms would fragment discussion |

## 4. Data model

### 4.1 `genres` (extended)

New columns:

| Column | Type | Notes |
|---|---|---|
| `parent_id` | UUID FK → `genres.id`, nullable | null = top-level |
| `position` | int, not null, default 0 | order among siblings |
| `retired_at` | timestamptz, nullable | set by sync when an entry leaves the YAML |

- The hierarchy is exactly two levels: a genre with a parent cannot itself be
  a parent. `sync_genres` enforces this; a `CHECK` cannot, so the service and
  the YAML validation test both assert it.
- The eight existing rows keep their ids and slugs and become parents, so
  `/genres/:slug` URLs, genre rooms and `threads.genre_id` are untouched.
- A retired genre cannot be voted on, inferred, or used as a filter. It stays
  in the table so its votes and threads keep resolving.

### 4.2 `genre_votes` — readers' source of truth

| Column | Type |
|---|---|
| `id` | UUID PK |
| `user_id` | FK → `users.id`, `ON DELETE CASCADE` |
| `work_id` | FK → `works.id`, `ON DELETE CASCADE` |
| `genre_id` | FK → `genres.id` |
| `created_at` | timestamptz |

Unique `(user_id, work_id, genre_id)`; index `(work_id)`. Withdrawing a vote
deletes the row, as `votes` does.

### 4.3 `genre_inferences` — the machine's guesses

| Column | Type |
|---|---|
| `work_id` | FK → `works.id`, `ON DELETE CASCADE` |
| `genre_id` | FK → `genres.id` |
| `source` | text, `CHECK (source IN ('open_library', 'google', 'catalog'))` |

PK `(work_id, genre_id, source)`. Rows hold exactly what the mapping produced
— no roll-up at rest. `source` lets one ingest path replace its own rows
without erasing another's.

### 4.4 Vetoes — `CorrectionOp.veto_genre`

A new value on `correction_op_enum` (migration uses
`ALTER TYPE ... ADD VALUE`; downgrade cannot remove an enum value, which the
migration documents). Payload `{"work_id": …, "genre_id": …}`, `work_id` set
on the row, recorded with
`runtime_only_reason = "the pipeline has no genre overrides"`. Snapshot is
unnecessary — the veto never deletes votes, so revert is only `reverted_at`.

Unreverted `veto_genre` corrections are the source of truth for vetoes.

### 4.5 `work_genres` — derived summary

| Column | Type | Meaning |
|---|---|---|
| `work_id` | FK → `works.id`, `ON DELETE CASCADE` | |
| `genre_id` | FK → `genres.id` | |
| `direct_votes` | int | readers who voted exactly this genre |
| `score` | int | distinct readers who voted this genre **or any of its subgenres** |
| `inferred` | bool | this genre, or a subgenre of it, is inferred |
| `vetoed` | bool | an unreverted veto names this genre on this work |

PK `(work_id, genre_id)`; index `(genre_id, score DESC)`. A row exists when any
of `score > 0`, `inferred`, `vetoed` holds.

`services/genres.py` is the **only writer**. `recompute(db, work_id)` deletes
and rewrites one work's rows from the three sources, in the caller's
transaction. It runs after every vote, unvote, veto, revert, inference change
and merge.

### 4.6 Effective genres — the one rule

A work's **effective genres** are:

- if it has at least one reader vote on a non-vetoed genre: every genre with
  `score > 0 AND NOT vetoed`;
- otherwise: every genre with `inferred AND NOT vetoed`.

Retired genres are never effective. The rule lives in one SQL view,
`effective_work_genres (work_id, genre_id, score, source)` where `source` is
`'readers'` or `'inferred'`. Its `CREATE VIEW` text is one constant in
`models/genre.py`, executed by the migration and by an `after_create` listener
on `Base.metadata` so `create_all` in tests builds it too — one definition,
not two copies to keep in sync. Book display, genre pages, `top_genres` and
the search filter all read through it; nothing else re-derives the rule.

### 4.7 `works.genre_id` is retired

The migration copies each non-null `works.genre_id` into `genre_inferences`
(`source='open_library'`) and populates `work_genres`, then drops the column
and its index. `Genre.works` and `Work.genre` relationships go with it; every
reader of the column (genre page, catalog loader, `works.py` ingest,
`merge_works`) moves to the new tables in the same change.

### 4.8 `works` search columns

- `author_doc`: generated `tsvector` — `to_tsvector('simple', coalesce(author, ''))`
  — with a GIN index. Declared in the model and the migration with identical
  expressions, as `search_doc` is.
- btree index on `first_publish_year`.

## 5. Taxonomy

### 5.1 The file

`backend/app/data/genres.yaml`:

```yaml
- slug: fantasy
  name: Fantasy
  description: Magic, myth, and invented worlds.
  match: ["fantasy"]
  children:
    - slug: epic-fantasy
      name: Epic Fantasy
      match: ["epic fantasy", "high fantasy"]
    - slug: grimdark
      name: Grimdark
      match: ["grimdark", "dark fantasy"]
```

- `slug` is globally unique and permanent; renames change `name` only.
- `match` is the list of subject phrases inference looks for; it may be empty
  for a genre that should only ever be reader-voted.
- Order in the file is `position`.
- Children may not have children.

### 5.2 `python -m scripts.sync_genres`

Upserts every entry by slug (name, description, parent, position), sets
`retired_at` on any live row missing from the file, clears `retired_at` on one
that reappears. Idempotent; prints what changed. Validation (unique slugs,
depth ≤ 2, a child's parent is not retired) fails the run before writing.
Compose runs it after `alembic upgrade head`. Tests call the same sync
function against the real file, so the shipped taxonomy is always loadable.

After a change to `match` lists, run `scripts.rebuild_work_genres --reinfer`.

### 5.3 Draft

Appendix A is the first draft (18 parents, ~100 subgenres), to be pruned in
review before it becomes the YAML.

## 6. Inference

### 6.1 `services/genre_inference.py` (pure)

```python
def infer_genres(subjects: Sequence[str], taxonomy: Taxonomy) -> set[str]
```

No ORM, settings or HTTP imports, so the pipeline can import it later
(`tests/test_pure_imports.py` gains it). `Taxonomy` is a plain structure
loaded from the YAML.

Rules:
1. Explicit `genre:` subjects are matched first; plain subjects only when the
   explicit pass matched nothing.
2. A needle matches on word boundaries, case-insensitively, after the same
   normalization `work_identity` uses — never as a substring (`crime` does not
   match *Crimea*).
3. Every match is kept; a book can infer several genres.
4. There is no generic fallback. Plain *fiction* infers nothing.

Google categories are passed through the same function as subjects.

### 6.2 Where it runs

| Path | Call | `source` |
|---|---|---|
| `upsert_work_from_ol` / search ingest | `genres.set_inferences(db, work, slugs, "open_library")` | `open_library` |
| Google enrichment (categories) | same, only if the work has no `open_library` inference | `google` |
| `catalog_loader` (release `subjects`) | same, per loaded work | `catalog` |

`set_inferences` replaces that source's rows for the work, then `recompute`s.
It replaces the `genre_id` assignment in `works.py` (`_refresh_work`, the
`ol_genre_slug` branch) and in `catalog_loader.py`. `open_library.genre_slug`
and `google_books._CATEGORY_SLUGS` are deleted. **No pipeline or release
contract change.**

### 6.3 Backfill

`python -m scripts.rebuild_work_genres [--reinfer]` — without the flag,
recomputes every work's `work_genres` from the sources; with it, first
recomputes `open_library`/`catalog` inferences from stored `works.subjects`.
Idempotent, batched, runs once after the taxonomy lands.

## 7. Voting, vetoes, merges — `services/genres.py`

### 7.1 Voting

`vote(db, user, work, genre)`:
- A tombstoned work resolves to its survivor (`merged_into_id`), as series
  lookups do. A `kind='collection'` work → 422.
- Retired genre → 422. Genre vetoed on this work → 422 ("a librarian removed
  this genre from this book").
- Already voted → no-op.
- Takes `SELECT … FOR UPDATE` on the work row, counts the user's votes on it,
  and refuses a sixth → 422 ("you've tagged this book with 5 genres").
- Inserts, then `recompute`.

`unvote(db, user, work, genre)` deletes if present, then `recompute`.

Voting a parent and one of its subgenres is allowed and uses two of the five;
the roll-up still counts that reader once in the parent's `score`.

### 7.2 Vetoes

`veto(db, librarian, work, genre, reason)` records the correction through
`librarian/record` and `recompute`s. Votes are kept, so undo restores the
book exactly. A vetoed genre is invisible to readers everywhere. Vetoing a
parent does not veto its subgenres. Vetoing an already-vetoed genre → 409.

Undo goes through the existing `librarian/undo` revert, extended with a
`veto_genre` branch that `recompute`s the work.

### 7.3 Merges and splits

`merge_works` calls `genres.absorb(db, source, target)` alongside
`absorb_series`:
- votes move to the target; where a reader voted the same genre on both, the
  source row is deleted. A reader may end above the cap — the cap applies to
  new votes only;
- inferences move (union; duplicates dropped);
- unreverted `veto_genre` corrections on the source are re-pointed at the
  target (`work_id` and payload), so the veto keeps holding;
- the source's `work_genres` rows are deleted and the target is recomputed.

`merge_consequences` (and so the merge preview) gains a genre-vote count.

`split_work` leaves votes on the original work; the split-off work gets
inferences from its own subjects and starts with no votes.

## 8. API

### 8.1 Taxonomy

- `GET /api/genres/` → tree: parents in `position` order, each with
  `children`; retired genres excluded. (Was a flat list; `Home.jsx` is its
  only consumer.)
- `GET /api/genres/{slug}` → adds `parent` (`{slug, name}` or null),
  `children`, `retired`. A retired slug is 200 with `retired: true`.

### 8.2 Genre pages

- `GET /api/genres/{slug}/works?limit&offset&sort=top|title` — works whose
  effective genres include the slug (a parent includes its subgenres' books
  via the roll-up). Live `kind='single'` works only. `top` (default) orders by
  `score DESC, readinglog_count DESC, title`, so voted books lead and
  inferred-only books follow.
- `GET /api/genres/{slug}/threads` — unchanged for parents; for a subgenre,
  returns the parent's threads, and `GenreOut.room_slug` names the parent.
- Thread creation with a subgenre `genre_slug` → 422.

### 8.3 A book's genres

- `GET /api/works/{id}/genres` →
  ```json
  {"source": "readers" | "inferred" | "none",
   "genres": [{"slug", "name", "parent_slug", "score", "direct_votes", "my_vote"}],
   "my_vote_count": 2}
  ```
  Effective genres only, ordered by `score DESC` then position. `my_vote` and
  `my_vote_count` are null for anonymous callers.
- `PUT /api/works/{id}/genres/{slug}` — vote; auth required; returns the `GET`
  payload.
- `DELETE /api/works/{id}/genres/{slug}` — withdraw; returns the `GET` payload.
- Errors: 401 anonymous, 404 unknown work or slug, 422 cap / veto / retired /
  collection.
- `WorkOut.top_genres: [{slug, name}]` — top 3 effective genres, filled by
  `load_work_presentation` in one batched query, so search results and series
  rows show badges without extra requests.

### 8.4 Librarian

- `POST /api/librarian/works/{id}/genres/{slug}/veto` `{reason}` —
  `require_librarian`; returns the correction id. The librarian's
  `GET /api/works/{id}/genres` additionally returns vetoed genres with
  `vetoed: true` and the correction id, so edit mode can show and undo them.

### 8.5 Search

`GET /api/works/search` gains `genre` (repeatable), `author`, `year_from`,
`year_to` — see §10.

## 9. Frontend

All of it follows the terminal design system: tokens only, mono, genres in
`path` (they are references you navigate to), no shelf-style pills.

### 9.1 On a book

- `components/GenreLine.jsx`: one line —
  `genres  epic-fantasy 12 · grimdark 7 · fantasy 19`. Slugs link to
  `/genres/:slug` in `path`; counts in `ink-dim`. The reader's own votes carry
  a leading `●` (`aria-hidden`) and sr-only "you tagged this". Inferred:
  `genres (inferred)  epic-fantasy · fantasy`, no counts. `source: "none"`:
  `genres  —` and the tag control.
- `[tag]` (signed in) opens `components/GenrePicker.jsx`, a `.float` with a
  filter input over the taxonomy tree (`├─`/`└─` elbows for subgenres,
  `aria-hidden`). Arrow keys move, Enter toggles, a counter reads `3/5
  tagged`. The input only filters; a non-matching query shows "no such genre
  — the list is curated". Toggles are optimistic and roll back with
  `errorMessage()` on refusal.
- Shown per book on the series page (each row) and in a singleton's book
  section.

### 9.2 Librarian edit mode

Each genre on the line gains `[veto]`, opening `ReasonField kind="veto_genre"`
(new presets in `components/librarian/reasons.js`: "wrong genre", "troll
tagging", "too broad for this book"). Vetoed genres are visible only in edit
mode, struck through in `warning`, with `[undo]`.

### 9.3 Genre page (`pages/Genre.jsx`)

- `PathHeader`: `genres / fantasy / epic-fantasy`.
- A parent shows its subgenres as a compact index with book counts.
- Books: the existing cover grid, `top` default with a `title` toggle;
  inferred-only books carry an `inferred` eyebrow.
- Threads panel on parents only; a subgenre page shows "discussion lives in →
  fantasy".

### 9.4 Home

Genre list becomes parents with their first few subgenres beneath.
`FALLBACK_GENRES` stays (parents only).

### 9.5 Search (`pages/Search.jsx`)

A filter bar above results:
`genre [epic-fantasy ×] [+]   author [________]   year [____]–[____]`.
`[+]` reuses `GenrePicker` in select mode. Filter state lives in the URL
(`?q=dune&genre=space-opera&year_from=1960`), so results are shareable and
survive back/forward. Result rows show `top_genres`.

### 9.6 Hooks (`api/genres.js`)

`useGenreTree`, `useGenre(slug)`, `useGenreWorks(slug, sort)`,
`useWorkGenres(workId)`, `useVoteGenre` / `useUnvoteGenre` (optimistic;
invalidate `work-genres` and the containing series query), `useVetoGenre`.

## 10. Search filters — `services/search.py`

- `search(db, query: str | None, filters: SearchFilters, limit)`, where
  `SearchFilters(genres: tuple[str, ...], author: str | None, year_from: int | None, year_to: int | None)`.
- **Filters only narrow the local query.** Gating and Open Library ingest stay
  keyed on `q` alone: a cold `q` ingests once, and every later search for it —
  filtered or not — makes no HTTP call. Open Library is never asked to filter;
  its subjects are not our genres.
- **`q` is optional when a filter is set.** A filter-only search is a local
  browse with no upstream call, ordered by the summed `score` of the requested
  genres (0 when no genre filter), then `readinglog_count`. No `q` and no
  filter → 422.
- `genre`: each slug must be among the work's effective genres — one `EXISTS`
  against `effective_work_genres` per slug (all must match). A parent slug
  matches subgenre-tagged books. Unknown or retired slug → 422 naming it.
- `author`: `author_doc @@ plainto_tsquery('simple', :author)`.
- `year_from` / `year_to`: inclusive on `first_publish_year`; works with no
  year are excluded once either is set. `year_from > year_to` → 422.
- With `q`, ranking is unchanged; filters are `WHERE` clauses on the same
  ranked query.

## 11. Error handling

| Case | Response |
|---|---|
| Vote or veto anonymously | 401 |
| Veto as a reader | 403 |
| Unknown work / genre slug | 404 |
| Sixth genre, vetoed genre, retired genre, collection | 422 with a sentence the UI shows verbatim |
| Veto an already-vetoed genre | 409 |
| Subgenre as a thread room | 422 |
| Bad search filter | 422 naming the parameter |
| Inference or recompute failure during ingest | propagates — it is in the ingest transaction, and a work must never exist with a stale summary |

## 12. Testing

**Pure** (`backend/tests/`)
- `infer_genres`: explicit tags before plain subjects, word-boundary matching
  (*Crimea*), several matches, no generic fallback, retired genres ignored.
- YAML validation: unique slugs, depth ≤ 2, the shipped file loads.

**Service / DB** (pytest, `margin_test`)
- Effective-genre rule: votes beat inference, a veto hides a genre from both
  branches, roll-up counts one reader once, retired genres drop out.
- Cap: five votes pass, the sixth is refused; two concurrent sixth votes
  cannot both land.
- Veto → undo restores the display exactly.
- `merge_works` combines votes with dedupe, carries inferences and vetoes,
  and removes the source's summary rows.
- `sync_genres`: idempotent; retire and unretire.
- Drift guard: after a random sequence of votes, vetoes and inferences,
  `rebuild_work_genres` produces the same `work_genres` as incremental updates.
- Migration: `works.genre_id` values become `open_library` inferences.

**API**
- Vote / unvote / veto status codes; genre page roll-up and both sorts;
  subgenre thread-create refusal; retired slug page.
- Every search filter alone and combined; filter-only browse makes **zero**
  HTTP calls (`respx` asserts it); a cold `q` with filters ingests once and
  then filters locally.

**Catalog**
- The loader writes `catalog` inferences; the contract test is unchanged.

**Frontend (Vitest)**
- `GenreLine`: readers vs inferred vs none, own-vote marker.
- `GenrePicker`: filtering, keyboard toggling, cap counter, rollback on 422,
  no way to submit free text.
- Search: filter state ↔ URL round trip.

**E2E (Playwright)**
- A reader tags a book, sees the count, finds the book on the subgenre page
  and through the search genre filter.

## 13. Rollout order

Each step ships working:

1. Migration (genre columns, new tables, view, enum value, search columns) +
   `sync_genres` + the YAML.
2. Pure inference, ingest/loader switch-over, backfill, drop `works.genre_id`.
3. Voting service and API.
4. `GenreLine` / `GenrePicker` on series pages.
5. Genre pages (tree API, roll-up listing, subgenre rooms rule, Home).
6. Vetoes (API, undo, edit-mode UI).
7. Search filters (service, API, Search page).

## Appendix A — draft taxonomy

To be pruned in review. Parents marked ◆ are the existing eight (ids and
slugs kept).

- **Literary Fiction** ◆ — contemporary-literary, historical-fiction,
  experimental, family-saga, satire, short-stories, coming-of-age
- **Science Fiction** ◆ — space-opera, hard-sf, cyberpunk, dystopian,
  post-apocalyptic, military-sf, time-travel, first-contact, climate-fiction,
  alternate-history
- **Fantasy** ◆ — epic-fantasy, grimdark, urban-fantasy, sword-and-sorcery,
  mythic-fantasy, fairy-tale-retellings, portal-fantasy, cozy-fantasy,
  magical-realism, historical-fantasy
- **Horror** — cosmic-horror, gothic, supernatural-horror, psychological-horror,
  folk-horror, body-horror
- **Mystery** ◆ — detective, cozy-mystery, police-procedural, noir, hardboiled,
  locked-room, amateur-sleuth
- **Thriller** — psychological-thriller, legal-thriller, spy-thriller,
  techno-thriller, political-thriller
- **Romance** — contemporary-romance, historical-romance, fantasy-romance,
  romantic-suspense
- **Adventure** — nautical, survival, western, swashbuckler
- **Classics** — ancient-classics, nineteenth-century, modernist, epic-poetry
- **Poetry** ◆ — lyric-poetry, narrative-poetry, verse-novels, anthologies
- **Drama** — tragedy, comedy, contemporary-drama
- **Graphic Novels** — superhero, manga, graphic-memoir, bande-dessinee
- **History** ◆ — ancient-history, medieval-history, modern-history,
  military-history, social-history, history-of-science
- **Biography** ◆ — memoir, autobiography, letters-and-diaries
- **Philosophy** ◆ — ethics, political-philosophy, metaphysics, epistemology,
  existentialism, eastern-philosophy, philosophy-of-mind
- **Science** — physics, biology, astronomy, mathematics, popular-science,
  nature-writing
- **Society & Politics** — politics, economics, sociology, true-crime,
  journalism, essays
- **Religion & Mythology** — mythology, theology, religious-texts, spirituality

`match` lists are written during implementation from the Open Library subject
vocabulary; a subgenre with no reliable subject stays vote-only (`match: []`).
