# Grouping Books by Work, Not Edition

**Date:** 2026-09-23
**Status:** Approved (design)
**Roadmap item:** Phase 1 — supersedes "Duplicate search results"
(`ROADMAP.md:46`), which solved a display symptom of this problem

## Problem

`books` is a table of *editions*. Each row is one Google Books volume, unique on
`(source, external_id)`, and `threads.book_id` and `shelves.book_id` point
straight at it. So discussion attaches to an edition, not to a book.

A search for "red rising" returns, among 20 results: `Red Rising`, `Red Rising
01`, `Red Rising (Deluxe Slipcase Edition)`, a German edition, `Red Rising
3-Book Bundle`, `Red Rising 1-6 ebook collection`, and `Pierce Brown's Red
Rising: Sons of Ares Omnibus`. Each can host its own threads. A reader who
starts a discussion from the deluxe edition is invisible to a reader who found
the paperback.

The current defence is `_dedup_volumes` (`google_books.py:72`), keyed on
normalized title + first author. It collapses duplicates **within a single
search response and nowhere else**: nothing is persisted, so two different
queries can mint two `books` rows for the same novel, and its key cannot
survive `Red Rising` vs `Red Rising 01` vs `Red Rising (Deluxe Slipcase
Edition)` — which is precisely the screenshot above.

This spec introduces `works` as the entity users see, discuss and shelve, and
demotes `books` to the editions that back it.

## Decisions

- **Identity comes from Open Library, not from string similarity.** OL is a
  work/edition graph maintained by librarians: `/works/OL17076473W` is *Red
  Rising*, 26 editions, languages eng/fre/por, and it correctly keeps `Golden
  Son` and `Morning Star` as separate works. A title-cleaning heuristic is the
  thing most likely to get exactly that distinction wrong. Google Books stays
  the search and cover source — it is better at both.
- **A work merges all editions and all languages.** Hardcover, paperback,
  deluxe, ebook, audiobook and translations are one discussion. This is the OL
  and Goodreads model, and it is only achievable with an authority's graph —
  no title heuristic merges `Roter Aufstand` into `Red Rising`.
- **The heuristic survives as a labelled fallback, never as the system.** When
  OL cannot resolve a volume, the work is still created, with
  `identity_provenance = 'heuristic'` recorded so it can be upgraded later.
  Degradation is visible in the data rather than silently permanent.
- **Collections are hidden from search, not dropped at ingest.** Box sets,
  bundles and omnibuses are classified `kind = 'collection'` and filtered out
  of search responses, but the rows exist and stay reachable by URL. A
  conservative classifier will still be wrong sometimes; filtering at ingest
  would make those mistakes unshelvable and unfixable without a migration.
- **`merge_works()` is a first-class operation, not an admin afterthought.**
  Any automatic grouping is sometimes wrong, and the upgrade path from a
  heuristic work to an OL work *is* a merge. The same primitive serves both.
- **Heuristic → OL merges automatically; OL → OL never does.** Two distinct OL
  work ids are an authority's claim. Overriding one belongs in a deliberate
  admin action, not in the middle of a search request.
- **`_dedup_volumes` is deleted outright.** Work grouping does the same job
  persistently and by identity. Keeping both would leave two grouping systems
  to disagree at the seams. `_completeness_score` survives, moved to
  representative-edition selection — the decision it was always really making.
- **`/api/books` is removed, not aliased.** Following the alias removal in
  `f29b948`. A `book_id` is not a `work_id`, so a redirect from `/books/:id`
  would be a lie; pre-launch, dead old URLs are the honest outcome.
- **Shelving is per work.** You shelve *Red Rising*, not the slipcase. There
  are 0 shelf rows today, and "which copy I own" is a Phase 4 concern if ever.

## Data model

New `backend/app/models/work.py`, exported from `models/__init__.py` so
`Base.metadata` stays complete.

```
works
  id                     UUID  PK, default gen_random_uuid()
  source                 work_source_enum      NOT NULL   -- openlibrary | heuristic
  external_id            TEXT  NOT NULL                   -- 'OL17076473W' | sha1(canonical_key)
  canonical_key          TEXT  NOT NULL, indexed          -- cleaned title \x1f first author
  title                  TEXT  NOT NULL
  subtitle               TEXT  NULL
  author                 TEXT  NOT NULL
  first_publish_year     INT   NULL
  kind                   work_kind_enum        NOT NULL   -- single | collection
  identity_provenance    work_provenance_enum  NOT NULL   -- isbn | title_author | heuristic
  representative_book_id UUID  FK books.id  ON DELETE SET NULL, NULL
  genre_id               UUID  FK genres.id ON DELETE SET NULL, NULL, indexed
  merged_into_id         UUID  FK works.id  ON DELETE SET NULL, NULL, indexed
  created_at             TIMESTAMPTZ NOT NULL  default now()
  updated_at             TIMESTAMPTZ NOT NULL  default now()

  UNIQUE (source, external_id)
```

Changes to existing tables:

| Table | Change |
| --- | --- |
| `books` | add `work_id UUID FK works.id ON DELETE CASCADE`, indexed, **nullable**; **drop** `genre_id` |
| `threads` | add `work_id UUID FK works.id ON DELETE CASCADE`, nullable, indexed; **drop** `book_id` |
| `shelves` | add `work_id UUID FK works.id ON DELETE CASCADE`, indexed; **drop** `book_id`; **drop** `uq_shelf_user_book`, add `uq_shelf_user_work UNIQUE (user_id, work_id)` |

Threads remain work XOR genre, exactly as they were book XOR genre
(`schemas/thread.py:22`).

### Where the display fields come from

`title`, `subtitle`, `author` and `first_publish_year` come from Open Library
when it resolved the work — OL's names are already edition-noise-free (`Red
Rising`, not `Red Rising (Deluxe Slipcase Edition)`). For a heuristic work they
come from `clean_title()` and the author of the first edition seen. `cover_url`
and `description` are never stored on the work; they are read through
`representative_book_id`.

`genre_id` is set from the representative edition's `genre_slug` mapping — the
same `_category_to_slug` output the upsert loop uses today (`books.py:101`),
applied to the work instead of the edition, and only when the work has no genre
yet.

### Why these columns

- **`canonical_key` is stored on every work, including Open Library ones.** It
  is not identity there — it is the bridge. When a volume with no ISBN lands in
  a heuristic work today and a sibling edition resolves to `OL17076473W`
  tomorrow, a matching key is how the two are recognised as the same book and
  merged. Without it, degraded resolution permanently splits a discussion,
  which is the failure this whole spec exists to prevent.
- **Display metadata is a pointer, not a copy.** `representative_book_id` names
  the richest edition and the work page reads cover and description through it,
  so there is nothing to drift. This makes `works ↔ books` a mutual foreign
  key; both sides are nullable, so writes order themselves: insert the work,
  attach editions, then set the representative.
- **`genre_id` moves up to the work.** `GET /genres/{slug}/books`
  (`genres.py:40`) lists edition rows today, so a genre page shows the same
  five Red Risings for the same reason search does. The work carries the genre;
  `books.genre_id` and the `Genre.books` relationship are removed.
- **`merged_into_id` keeps merged works as tombstones** so their URLs keep
  resolving. Reads follow the pointer one hop; `merge_works()` repoints
  everything, so chains never exceed one.

## Resolution

New `backend/app/services/open_library.py` (HTTP client, shaped like
`google_books.py`) and `backend/app/services/work_identity.py` (pure
functions: title cleaning, canonical key, ISBN conversion, `classify_kind`).

Resolution runs **only for Google volumes not already in `books`**. An edition
carries its `work_id` forever once resolved, so a repeat search costs zero Open
Library calls.

### Tier 1 — ISBN (`identity_provenance = 'isbn'`)

One batched call per search over the new volumes' ISBN-13s:

```
GET /search.json?q=isbn:(A OR B OR ...)
    &fields=key,title,author_name,first_publish_year,edition_count,isbn
```

Verified against the live API: three ISBNs resolved in one ~1.2 s call. Each
returned work is mapped back by intersecting its `isbn` array with ours.

**The returned ISBN list mixes ISBN-10 and ISBN-13** — Red Rising's work
returns 44 identifiers including `0345539788` alongside 13-digit forms — so the
intersection converts OL's 10s to 13s (prefix `978`, recompute the check digit)
before comparing.

### Tier 2 — title + author (`identity_provenance = 'title_author'`)

For volumes Tier 1 left unresolved:
`GET /search.json?title=<cleaned title>&author=<first author>`.

Accept only on exact *normalized* title **and** first-author match. Capped at
**5 calls per search** with a shared timeout budget; anything past the cap goes
to Tier 3.

This tier needs a tiebreak, because **Open Library itself contains duplicate
works**: `title=Red Rising&author=Pierce Brown` returns both `OL17076473W`
(26 editions) and `OL26627585W` (8 editions). Rule: highest `edition_count`
wins.

### Tier 3 — heuristic (`identity_provenance = 'heuristic'`)

`canonical_key = normalize(clean_title(title)) \x1f normalize(first_author)`,
and `external_id = sha1(canonical_key)`. `clean_title` strips:

- parenthetical and bracketed qualifiers — `(Deluxe Slipcase Edition)`
- trailing volume numbers — `Red Rising 01`, `#1`, `Vol. 2`, `Book 3`
- edition words — deluxe, slipcase, illustrated, anniversary, revised,
  reprint, unabridged, annotated, movie tie-in

It deliberately **does not strip after a colon**. That is what keeps
`Red Rising: Sons of Ares` out of `Red Rising`.

### Failure and upgrade

Any Open Library failure — timeout, 429, outage — falls through to Tier 3. A
search request never fails because OL is unavailable; it degrades, and the
degradation is recorded in `identity_provenance`.

`python -m scripts.resolve_works --upgrade` re-attempts every work whose
provenance is `heuristic` and, on success, merges it into the OL work.

### `merge_works(source, target)`

In `backend/app/services/works.py`:

1. repoint `books.work_id`, `threads.work_id`, `shelves.work_id`
2. on a shelf collision (user already has `target` shelved) keep the oldest row
   and delete the duplicate — `uq_shelf_user_work` permits one
3. recompute `target`'s representative edition and `kind`
4. set `source.merged_into_id = target.id`; the row survives as a tombstone

### Collections

`classify_kind()` matches the work's title and subtitle against a conservative
pattern set: `box set`, `boxed set`, `omnibus`, `bundle`, `collection`,
`complete series`, `books N-M`, `N-book`, `N books`.

It deliberately omits bare `complete` and bare `collected`, so `Collected
Fictions` and `The Complete Stories` stay `single`. All three collections in
the motivating search match.

### Known limits

Open Library's graph is incomplete. `Roter Aufstand` (the German *Red Rising*)
returns 0 search results, and OL lists that work's languages as eng/fre/por —
so a German edition merges only if OL has attached it. The all-languages radius
is as good as OL's data, with `canonical_key` and manual merge as backstops.

## API

`backend/app/api/books.py` becomes `backend/app/api/works.py`; the `/api/books`
prefix is removed.

| Method | Path | Notes |
| --- | --- | --- |
| GET | `/api/works/search?q=` | one entry per work; `kind='collection'` excluded |
| GET | `/api/works/{id}` | `WorkOut` + `shelf_status`; follows `merged_into_id` one hop |
| GET | `/api/works/{id}/threads` | unchanged shape — `limit`, `offset`, `my_vote` |
| POST/PUT/DELETE | `/api/works/{id}/shelf` | as today, keyed on work |
| GET | `/api/genres/{slug}/works` | replaces `/api/genres/{slug}/books` |
| POST | `/api/threads` | body takes `work_id` instead of `book_id` |

`WorkOut` carries the work's own fields (`title`, `subtitle`, `author`,
`first_publish_year`, `kind`, `genre`), cover and description read through the
representative edition, and `edition_count` — the number of editions **we**
hold, not OL's, because that is the number we can stand behind.
`schemas/book.py` gains `WorkOut`; `ThreadSummary`/`ThreadOut`/`ThreadCreate`
swap `book_id` for `work_id` (`schemas/thread.py:15,62,87`). The thread detail
lookup that names the book a thread hangs off (`threads.py:139-141`, added in
`302f72a`) reads the work's title instead.

### Search path

1. `google_books.search_books(q)` — unchanged two-pass `intitle:` + broad
   fallback, minus the `_dedup_volumes` calls at lines 226 and 233
2. upsert each volume as an edition — unchanged enrich loop (`books.py:70-104`)
3. resolve work ids for new volumes — the tier ladder, one batched OL call
4. upsert works, attach editions, select each work's representative by
   `_completeness_score`, classify `kind`, set `genre_id` when unset
5. group volumes into works in first-seen order, drop collections, return

Ordering is preserved the way dedup preserved it: a work takes the position of
its first-seen volume, so Google's relevance ranking still drives the page. The
motivating search goes from 20 cards to roughly 3–5.

## Frontend

Rename-shaped; no new visual vocabulary, and the design system is untouched.

- `api/books.js` → `api/works.js`: `useSearchWorks`, `useWork`,
  `useWorkThreads`, shelf mutations
- `pages/Book.jsx` → `pages/Work.jsx`; `components/BookCard.jsx` →
  `components/WorkCard.jsx`
- routes `/works/:id` and `/works/:id/threads/:threadId` (`App.jsx:30-31`)
- `PathHeader` paths become `~/works/red-rising`
- `pages/Genre.jsx` switches to `/genres/{slug}/works`
- the work card shows `edition_count`, so collapsing 20 results into 4 reads as
  information rather than as search having gotten worse

Covers stay large and undimmed; serif stays reserved for book titles.

## Migration

Two migrations with a script between them, because the backfill needs network
and Alembic must not make HTTP calls.

**Migration 1** (`down_revision = 'c3a7e1b8d904'`) — create `works`; add
nullable `work_id` to `books`, `threads`, `shelves`. Three new enums
(`work_source_enum`, `work_kind_enum`, `work_provenance_enum`), each with an
explicit `sa.Enum(name=...).drop(op.get_bind(), checkfirst=True)` in
`downgrade()` per the documented re-upgrade trap in `CLAUDE.md`.

**`python -m scripts.resolve_works`** — idempotent, following the
`backfill_cover_urls` pattern, batching 20 editions per OL call: resolve every
edition without a `work_id`, create and attach works, set representatives,
classify kind, then fill `threads.work_id` and `shelves.work_id` through their
edition. `--upgrade` re-attempts heuristic works and merges the results.

**Gate** — this must return 0 before proceeding:

```sql
SELECT count(*) FROM threads WHERE book_id IS NOT NULL AND work_id IS NULL;
```

**Migration 2** — drop `threads.book_id`, `shelves.book_id`, `books.genre_id`
and `uq_shelf_user_book`; add `uq_shelf_user_work`; set `shelves.work_id NOT
NULL`.

`books.work_id` stays **nullable**, which is a correction to an earlier draft of
this spec. An edition is inserted and flushed before it is resolved — the
resolution batch needs the generated ids — so a NOT NULL column would make the
upsert order illegal, and Postgres cannot defer NOT NULL. Every edition still
ends its transaction attached to a work; that invariant is enforced by the
resolver and asserted in tests, not by the column. `shelves.work_id` has no such
problem: a shelf row always knows its work at insert time.

Migration 2 is the destructive step and the gate is what makes it safe. Current
scale: 223 editions, 8 threads, 0 shelves.

## Testing

Backend (pytest; Google Books and Open Library both mocked with `respx` —
never the network):

- **Identity units** — `clean_title`/`canonical_key` table-driven on the real
  cases (`Red Rising 01`, `(Deluxe Slipcase Edition)`, and `Red Rising: Sons of
  Ares` staying *out*); ISBN-10 → ISBN-13 conversion and the intersection
  mapping; Tier-2 `edition_count` tiebreak on OL's duplicate Red Rising works;
  representative selection by `_completeness_score`
- **`classify_kind`** — the three motivating collections match; `Collected
  Fictions` and `The Complete Stories` do not
- **OL client** — timeout and 429 fall through to the heuristic tier and the
  search still succeeds
- **API** — a fixture of the 20-volume Red Rising response collapses to one
  card; collections absent from search yet reachable by id; threads and shelves
  on works; `uq_shelf_user_work` enforced; `/genres/{slug}/works`
- **Merge** — a heuristic work absorbed into an OL work moves threads and
  shelves, a shelf collision keeps the oldest row, and the merged id still
  resolves one hop
- **Script** — a second run is a no-op; `--upgrade` promotes and merges

Frontend: `WorkCard` and `Work` unit tests (Vitest + RTL), the existing
`Book`-named tests renamed. E2E: `thread.spec.js` and `reply.spec.js`
repointed at `/works/:id`.

## Out of scope (YAGNI)

- **An editions list in the UI.** `edition_count` is enough; a per-edition
  picker is a Phase 4 concern.
- **Admin merge/split UI.** `merge_works()` and the script are the interface
  until Phase 5 brings roles and an admin surface.
- **Recording which edition a user owns.** Shelves are per work.
- **Series modelling.** OL exposes series data; grouping *Red Rising* with
  *Golden Son* is a different feature, and one this spec must specifically
  avoid doing by accident.
- **Backfilling OL identity for works we already resolved heuristically, on a
  schedule.** `--upgrade` is run manually until there is a job runner
  (Phase 6).
