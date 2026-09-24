# Local-First Search: Open Library Ingests, Google Books Enriches

**Date:** 2026-09-24
**Status:** Approved (design)
**Supersedes:** the claim in `2026-09-23-work-grouping-design.md` that "Google
Books stays the search and cover source — it is better at both." It is better
at neither. That spec's identity model is unchanged and still correct; only the
search and cover sourcing is reversed here.

## Problem

Two symptoms, one cause.

**Covers.** Searching "red rising" renders three tiles reading *image not
available*. Those works have a non-null `cover_url`: Google serves a
placeholder at HTTP 200 — a fixed **9103-byte PNG**, where real covers are
JPEG — for metadata-only catalog records. Verified:

| volume | bytes | type |
|---|---|---|
| `5tDS0AEACAAJ` (*Red Rising: An Explosive Dystopian Sci-Fi Novel*) | 9103 | `image/png` |
| `_tbZ0QEACAAJ` (*Red Rising 5 Books Set*) | 9103 | `image/png` |
| `vSCbAwAAQBAJ` (*Red Rising*, Heyne) | 401823 | `image/jpeg` |

Nothing in the JSON distinguishes them — `imageLinks` is populated either way.
So `completeness_score` (`works.py:43`) awards a placeholder edition the full
+4 for having a cover, and it can win `representative_book_id` over a sibling
that has real art. A further 15 of 211 live works have no cover at all.

**Relevance.** `search_books` queries `intitle:{query}` unquoted, so Google
tokenizes. "red rising" returns, at ranks 3 and 4, *Osceola the Seminole, Or
The Red Fawn of the Flower Land* and *History of the Red River Valley, Past and
Present* — neither contains the word "rising" — while *Golden Son* ranks 5th
only because its full title happens to be *Golden Son: Book II of the Red
Rising Saga*. Works Google never returns cannot be found at all, because
nothing is ingested that a search did not surface.

**The shared cause** is that Google Books is the entry point. Every query goes
upstream to a service with poor title recall, no popularity signal, no work
model, a thin keyless quota (exhausted during this session's probing), and
cover URLs that lie.

## Evidence

The same query against Open Library, ranked by its default relevance:

```
q=red rising  →  Red Rising (Pierce Brown)     cover ✓  1036 readers
                 Iron Gold, Dark Age, Golden Son, Morning Star, Light Bringer
                 Red Storm Rising (Tom Clancy) cover ✓   367 readers
                 Red Rising (Renee Joiner)     cover ✓     8 readers
```

Every hit is a real book, every one has a cover, and each carries the
popularity counts that make "famous books first" expressible. The same held for
`dune`, `brandon sanderson`, `the hobbit` and `1984` — the canonical edition
ranked first with a cover every time.

One search response carries everything a `Work` row needs, with no second call:

```
/works/OL17076473W | Red Rising | 2014 | 26 editions | cover 7316188 | 44 ISBNs
  subjects: ['franchise:Red Rising', 'series:Red Rising Saga', 'form:novel',
             'genre:science fiction', 'Fantasy', 'Fiction', 'Dystopia']
```

It does **not** carry `description` or `subtitle`. Those are the lazy-enrichment
targets.

The cost is latency. Warm, repeated: `dune` 1.7s, `red rising` 1.9–4.3s,
`the hobbit` 2.0s, with one cold run at 12.5s. Against Google's ~0.4s that
would be an unacceptable trade **on the request path** — which is why the
request path stops going upstream at all.

## Decisions

- **The database is the search index; upstream is how it fills.** A query is
  answered from local `works` rows. Open Library is consulted once per novel
  query, never again. This is what makes Open Library's 2s affordable: it is
  paid once, by one user, and amortized across every later search.
- **A query blocks once, then is instant forever.** The first search for a term
  waits on ingest and renders complete results; repeats are local. Chosen over
  showing partial results and filling in live, because it needs no background
  worker and no refetch loop, and the slow path is hit once per distinct query
  for the lifetime of the deployment.
- **Open Library ingests works; Google Books enriches editions, lazily.** A
  search creates `Work` rows directly from OL docs. Google is called only when
  a work page is opened and only if it has never been enriched, to attach
  editions, descriptions and page counts.
- **A work may have zero editions.** `representative_book_id` is already
  nullable, so this needs no schema change — but it does mean cover,
  description and edition count can no longer be derived solely from a
  representative row.
- **Cover precedence inverts: Open Library first, Google second.** OL's cover
  is a librarian-curated image keyed to the work. Preferring it makes the
  placeholder problem disappear for every OL-resolved work without a single
  extra HTTP call.
- **Placeholder detection survives, but moves off the request path.** Works
  with no OL cover still fall back to Google, so the 9103-byte PNG must still
  be caught. That check runs during lazy enrichment, where latency is already
  hidden, not during search.
- **Identity, merging and the works/editions model are untouched.**
  `uq_works_source_external_id` means an OL search returning `OL17076473W`
  finds the existing row rather than duplicating it, and
  `_absorb_heuristic_twin` already folds a matching heuristic work into an
  Open Library one. The reconciliation path for the 211 existing works is code
  that is already written and tested.
- **`WorkOut` does not change shape.** Only the provenance of `cover_url`,
  `description` and `edition_count` changes, so the frontend contract and every
  existing consumer of `load_work_presentation` keep working.

## Architecture

```
GET /api/works/search?q=…
  │
  ├─ normalize(q) ─→ search_queries lookup
  │                    │
  │                    ├─ hit (fresh)  ─────────────────┐
  │                    │                                │
  │                    └─ miss / stale                  │
  │                         │                           │
  │                         ├─ Open Library search.json │   ~2s, once per query
  │                         ├─ upsert Work rows         │
  │                         └─ record search_queries    │
  │                                                     │
  └─ local ranked query over works ←───────────────────┘   ~40ms
         order by text match × popularity

GET /api/works/{id}
  │
  └─ if enriched_at is null:
       ├─ Google Books by ISBN / title+author
       ├─ upsert Book editions, verify covers   ← placeholder HEAD check lives here
       └─ set enriched_at
```

### Schema changes

New columns on `works`, one migration:

| column | type | purpose |
|---|---|---|
| `ol_cover_id` | `integer, null` | Open Library `cover_i`; renders as `covers.openlibrary.org/b/id/{id}-L.jpg` |
| `readinglog_count` | `integer, not null, default 0` | OL readers-who-shelved-it; the primary fame signal |
| `ratings_count` | `integer, not null, default 0` | OL ratings volume |
| `ol_edition_count` | `integer, not null, default 0` | OL's edition total (26 for *Red Rising*), independent of how many we've ingested |
| `description` | `text, null` | work-level description, filled lazily |
| `enriched_at` | `timestamptz, null` | when Google enrichment last ran; null means never |
| `subjects` | `text, null` | OL subject tags, space-joined; feeds `search_doc` |
| `search_doc` | `tsvector, generated stored` | weighted: title `A`, author `B`, subjects `C`; GIN-indexed |

New table `search_queries`:

| column | type |
|---|---|
| `id` | uuid pk |
| `normalized_query` | text, unique, not null |
| `resolved_at` | timestamptz, not null |
| `result_count` | integer, not null |

`resolved_at` supports a staleness TTL (default 30 days) so the catalog can
refresh without a manual purge.

### Ranking

Local ordering lives in one function in a new `services/search.py`:

```
score = ts_rank_cd(search_doc, query) * ln(1 + readinglog_count)
tiebreak: ol_edition_count desc, first_publish_year asc
```

Popularity is a multiplier, not an addend, so an irrelevant famous book cannot
outrank a relevant one — *Dune* does not surface for "red rising" merely for
being popular. Raw counts are stored rather than a precomputed score, so the
formula can be tuned without a migration.

`kind = 'collection'` stays filtered out of results, as today.

**Why `subjects` is in the index.** Open Library returns *Iron Gold*, *Golden
Son* and *Morning Star* for "red rising" — correctly, because they carry
`franchise:Red Rising` and `series:Red Rising Saga`. A tsvector built from
title and author alone would match none of them, so the local index would
return *fewer* results after ingest than the upstream call that filled it, and
the series would vanish on the second search. Indexing the subject tags at
weight `C` reproduces that association locally, which is the whole point of the
local index standing in for upstream.

### Genre

OL subjects carry explicit `genre:` tags (`genre:science fiction`), which map
onto the seeded slugs directly. This replaces the substring guessing in
`_CATEGORY_SLUGS` (`google_books.py:14`) for OL-ingested works; that table
stays for the Google enrichment path.

### Degradation

Open Library is not a hard dependency. On timeout (5s) or failure, the search
falls back to the existing `google_books.search_books` path and does **not**
record a `search_queries` row, so the query is retried upstream next time. A
cold query during an OL outage degrades to today's behaviour rather than to an
error. `open_library.py`'s existing never-raise contract is preserved.

### Presentation precedence

A work can now have zero editions, so every field `load_work_presentation`
derives needs a stated order. `WorkOut`'s shape is unchanged; only these
sources are:

| field | order |
|---|---|
| `cover_url` | `ol_cover_id` → `representative.cover_url` → `null` (`WorkCard.jsx:18` draws the serif-title fallback) |
| `description` | `representative.description` → `works.description` → `null`. Google's edition blurbs are richer than OL's, so an enriched edition wins; the work-level column carries the pre-enrichment case. |
| `edition_count` | `ol_edition_count` when non-zero → count of local `books` rows. OL knows *Red Rising* has 26 editions while we may have ingested none, and the count is shown to readers as a fact about the book, not about our database. |

The frontend additionally gets an `onError` handler so a dead URL degrades to
the serif fallback rather than a broken image icon.

## Testing

**Backend (pytest + respx, never the network):**
- OL search response → works created with cover, popularity and genre
- ranking: famous work outranks obscure same-title work; irrelevant popular
  work does not surface
- `search_queries` gating: a second identical query makes **zero** upstream
  calls **and returns the same works in the same order** — the regression that
  would otherwise drop the series on the second search
- `edition_count` reports OL's total for a work with no ingested editions
- staleness: a query older than the TTL re-fetches
- OL timeout → falls back to Google path, records no `search_queries` row
- heuristic twin absorbed when an OL search returns its work id
- enrichment: placeholder cover (9103-byte PNG) rejected, real cover kept,
  `enriched_at` set, second open makes no upstream call
- zero-edition work serializes to `WorkOut` without `MissingGreenlet`

**Frontend (Vitest):** `WorkCard` `onError` falls back to the serif title.

**E2E (Playwright):** search "red rising" → first result is *Red Rising* by
Pierce Brown with a cover; no result tile shows a broken image.

## Migration of existing data

One script, `scripts/backfill_covers.py`, idempotent:

1. For every `source='openlibrary'` work, fetch `cover_i` and popularity counts
   from OL and populate the new columns.
2. HEAD every stored `books.cover_url`; null the 9103-byte placeholders.
3. Re-run `_refresh_work` so representatives move to editions with real art.

Heuristic-tier works keep their existing upgrade path
(`scripts/resolve_works --upgrade`); nothing about it changes.

## Out of scope

- Typo tolerance (`pg_trgm` fuzzy matching). Deferred until the exact-match
  index is proven; the extension can be added without touching the ranking
  seam.
- Bulk pre-seeding from an OL data dump. The catalog compounds on its own;
  revisit if cold queries prove common in practice.
- Author and series pages, which the OL `franchise:` and `series:` subject tags
  would now make possible.
- Any change to work identity, merging, or the works/editions split.
