# The Series Is the Discussion Home

**Date:** 2026-09-24
**Status:** Approved (design)
**Supersedes:** the assumption, carried since `2026-09-23-work-grouping-design.md`,
that a *work* is the unit people talk about. Work grouping remains exactly as
specified — editions collapse into works, and that is still the right catalog
model. What changes is the layer above it: a conversation belongs to a
**series**, not to a book.

## Problem

Two symptoms that turn out to be the same design gap.

### A reader sees the wrong book

The work page for *Red Rising* renders a Spanish cover (*Amanecer Rojo*, RBA)
above a German blurb, under an English title. Live, from the API:

```json
{
  "title": "Red Rising",
  "cover_url": "https://covers.openlibrary.org/b/id/7316188-L.jpg",
  "description": "Der fulminante Auftakt zur New York Times-Bestsellertrilogie …"
}
```

Three independent causes:

1. **The cover is language-blind.** `load_work_presentation` (`works.py:417`)
   prefers `ol_cover_url(work.ol_cover_id)`. Open Library's `cover_i` is one
   arbitrary edition's art — here `cover_edition_key: OL25646224M`, the RBA
   Spanish printing. The same search doc returns `language: ["fre","por","eng"]`
   and nothing reads it.
2. **The representative edition is language-blind.** `completeness_score`
   (`works.py:40`) sums cover (+4), description, isbn_13, page_count,
   ratings_count. The Heyne **German** edition scores top, becomes
   `representative_book_id`, and its blurb wins the description fallback.
   **17 of 215** works with a representative already have a non-English one
   (10 `pt-BR`, 3 `fr`, 2 `de`, 1 `it`, 1 `da`).
3. **Enrichment attaches unrelated books.** `enrich_work`
   (`enrichment.py:45-48`) runs one `intitle:/inauthor:` query against Google
   and assigns `work_id` to *every* returned volume that has none. The
   *Red Rising* work therefore owns *Iron Gold* and five *Sons of Ares* graphic
   novels, and `works.description` is a graphic-novel blurb. Only 4 works are
   enriched today, so the corruption is early — and it spreads on every first
   view of a work page.

### Books in a series do not look or read like a series

Even with the language bug fixed, the saga presents as six unrelated products:

| work | cover source | blurb source | register |
|---|---|---|---|
| Red Rising | OL `7316188` (RBA, Spanish) | Heyne (German) | translation |
| Golden Son | OL `8454351` | Hachette UK | in-book pull-quote — *"I'm still playing games…"* |
| Morning Star | OL `8566174` | Del Rey | award shout — `#1 NEW YORK TIMES BESTSELLER • …` |
| Iron Gold · Dark Age · Light Bringer | OL cover | none | empty |

Every work picks an edition in isolation, so cover art and copy voice change
book to book within one saga.

### And the conversation fragments the same way

`threads.work_id` makes each book its own room. A reader moving through the
saga changes rooms five times, and each room starts empty. The reference point
is r/redrising: one community for the whole franchise, with per-book scoping
inside it. Discussion of a series is, in practice, a bigger thing than
discussion of any one of its books.

## Evidence

Open Library already carries the hierarchy, **in rows we have already stored** —
no new upstream dependency:

```
franchise:Red Rising                     ← the r/redrising equivalent
├── series:Red Rising Trilogy            → Red Rising · Golden Son · Morning Star
└── series:Iron Gold Tetralogy           → Iron Gold · Dark Age · Light Bringer
    series:Red Rising Saga               → spans all six
```

Box sets and omnibuses (`Red Rising 3-Book Bundle`, `6 Books Box Set`) carry no
series tags at all, so the junk self-excludes.

What Open Library does **not** give:

- **Position.** `search.json` has no usable `series` field — verified `None` for
  `red rising`, `golden son`, `mistborn` and `the hobbit`. Some *editions*
  carry `series: ["Red Rising Saga"]`, never a number.
- **Coverage.** Only **8 of 98** OL-sourced works carry a `series:` tag and
  **6** a `franchise:` tag; the 134 heuristic works carry no subjects at all.

The per-work `editions.json` call closes both the coverage gap and the language
gap in one request:

```
GET /works/OL17076473W/editions.json   →  26 entries
  Fúria Vermelha        ['por']  series: None                  pub: Alt
  Red Rising            ['eng']  series: ['Red Rising Saga']   pub: Del Rey
  Red Rising            ['eng']  series: None                  pub: Hodder & Stoughton
  Red Rising            []       series: None                  pub: Heyne Verlag
  Kizil Yükselis        []       series: None                  pub: Pegasus
```

Per-edition `languages`, `publishers`, covers and series names — every input the
selection rules below need, from a source that cannot attach the wrong book.

## Decisions

| Question | Decision | Why |
|---|---|---|
| Where is consistency enforced? | At the **series** | Per-work rules make consistency a side effect; the series makes it a guarantee. |
| Does the series replace the book as the discussion home? | **Yes** | One room per saga, as r/redrising. A reader mid-series never changes rooms. |
| Does the work page survive? | **No — retired** (amended 2026-09-26) | The series page is the only book destination; search links to it and legacy URLs redirect. |
| What about standalone books? | **Every work gets a series**, of one if need be | One container type, one page template, one feed. A singleton shows no series chrome. |
| Do we track position in a series? | **No** | Membership is enough for v1. Ordering falls back to `first_publish_year`, which is correct for all six Red Rising novels. |
| How do spoilers work? | **Optional per-thread book tag, used as a filter** | One nullable column, no hiding. It is also the exact signal reader-progress gating would later need. |
| What happens to `threads.work_id`? | **Repurposed as that tag** | Same column, new meaning; existing threads migrate without moving page. |
| Where do editions come from? | **`editions.json`**, with Google demoted to blurb supply | OL gives identity, language and publisher; Google's copy is genuinely richer. |

## Architecture

### Schema changes

```
series
  id                uuid pk
  source            enum(openlibrary, heuristic)   not null
  external_id       varchar(255)                   not null   -- tag text, or sha1 for singletons
  name              varchar(500)                   not null
  slug              varchar(255)                   not null unique
  canonical_key     text                           not null   -- normalized name, for later merges
  kind              enum(series, singleton)        not null
  preferred_publisher varchar(255)                            -- the edition family; see below
  merged_into_id    uuid → series.id
  created_at / updated_at
  unique (source, external_id)

works.series_id     uuid → series.id   not null after backfill, indexed
threads.series_id   uuid → series.id   nullable, indexed      -- the discussion home
threads.work_id     uuid → works.id    nullable, indexed      -- REINTERPRETED: the book tag
```

`canonical_key` and `merged_into_id` mirror `works` on purpose. Series grouping
is the work-grouping problem one level up: a singleton that later turns out to
be book four of something is a merge, and reusing the tombstone pattern means
`merge_series` is `merge_works` with different foreign keys. Promotion moves
threads with it, and because a tombstoned slug redirects to its survivor, the reader
watches the room grow rather than their thread disappear.

The thread target constraint becomes:

- exactly one of `series_id`, `genre_id` is non-null;
- `work_id` is non-null only when `series_id` is set, and that work's
  `series_id` must equal the thread's.

Enum columns must drop their types in `downgrade()` (`sa.Enum(name=…).drop(...,
checkfirst=True)`) — the repo's standing gotcha.

### Series detection

A ladder, in the shape of the existing work resolution ladder. No call is made
that the page did not already need.

1. **`franchise:` tag** on `works.subjects` → the container. Free; all six
   Red Rising novels carry `franchise:Red Rising`.
2. **`series:` tag** when there is no franchise. Where a work carries several
   (*Red Rising* has both `Red Rising Trilogy` and `Red Rising Saga`), take the
   tag shared by the most works in the catalog — the broadest grouping wins,
   which is the one-room goal. Deterministic tiebreak on name.
3. **`editions.json`** at enrichment time, for works whose subjects are silent.
   Some English editions name their series. This is the tier that grows
   coverage past today's 8-of-98, and the call is one Section 2 makes anyway.
4. **Singleton** otherwise.

The rules are pure string work over a subject blob, so they live beside
`work_identity.py` in `services/series_identity.py` and are tested as a table.

### Edition selection: a dominance ladder

`completeness_score` is replaced. A flat sum lets "has a cover" (+4) outrank
everything, which is how a German edition speaks for an English book. The
replacement decides each tier before consulting the next:

| rank | tier | rule |
|---|---|---|
| 1 | language | an English edition always beats a translation |
| 2 | family | publisher ∈ the series' `preferred_publisher` |
| 3 | cover | verified, non-placeholder art |
| 4 | blurb | quality score (below) |
| 5 | completeness | isbn_13, page_count, ratings — today's signals, demoted to tiebreakers |

**The edition family** is the modal publisher among the English editions of all
of a series' works, stored on `series.preferred_publisher` and recomputed when
a member is enriched. For the Red Rising saga it is Del Rey, so all six books
show Del Rey art and Del Rey copy instead of RBA/Heyne/Hachette/Dynamite
roulette. Presentation reads the stored value; it never recomputes per request.

Ranking family above cover quality is deliberate: a slightly worse cover from
the right imprint beats a better one that breaks the shelf. If a series has no
English editions at all, tier 1 selects nothing and the ladder falls through —
a non-English work is presented in its own language rather than not at all.

### Blurb normalization

Publisher consistency alone does not fix register: within Del Rey, *Morning
Star* opens `#1 NEW YORK TIMES BESTSELLER • …` while *Golden Son* opens with an
in-book pull-quote. A new pure module, `services/blurb.py`:

- **strip** leading marketing furniture — award shouts (`#1 NEW YORK TIMES
  BESTSELLER •`, `NOW A MAJOR MOTION PICTURE`), leading pull-quotes ending in an
  attribution dash, and trailing series plugs (*"Don't miss the next book…"*).
- **score** what remains — prose about the book, in a length band (roughly
  200–1500 characters), beats a two-line teaser or a 4,000-character dump.

String in, string out, no I/O, exhaustively tested — the same shape and the
same reason as `work_identity.py`.

### Presentation precedence, revised

`load_work_presentation` keeps its job and inverts two orders:

- **cover** — the chosen edition's *verified* cover, then OL's `cover_i`, then
  none. Today OL wins because Google serves a 9103-byte placeholder PNG at HTTP
  200, but `covers.verify` already rejects those by their bytes, so the reason
  has expired — and `cover_i` is exactly the language-blind pick that put a
  Spanish cover on an English book. Works with no editions still fall back to
  `cover_i`, so nothing regresses for the unenriched 228.
- **description** — the chosen edition's *normalized* blurb, then the work's.
- **edition_count** — unchanged (OL's total, then the local count).

### Enrichment, reversed

`editions.json` becomes the source of record for a work's editions; Google is
demoted to blurb supply, matched to those editions by ISBN. Editions pulled
from `editions.json` belong to the work by definition, which **deletes cause 3
by construction** — there is no identity guess left to get wrong. `books.source`
gains `open_library`. On upstream failure `enriched_at` stays null so the next
view retries, exactly as today.

### Surfaces

*Amended 2026-09-26: the work page is retired. The series page is the only
destination for a book; search links straight to it.*

- **Search** — results stay works (one card per book). A card whose series is
  `kind='series'` carries a `series ⟨name⟩` line under the author — the word in
  `ink-dim`, the name in `path`; text rather than a glyph, because the
  literal-glyph set is closed (it is a reference); singletons carry none. The whole card links to
  `/series/:slug?book=<work_id>`, which scrolls to and highlights that book's
  row. `GET /api/works/search` gains `series: {slug, name, kind}` per result.
- **`/series/:slug`** — the room, and the only book page.
  - *Header*: `PathHeader` `~/series/red-rising`, series name, book count. A
    singleton shows its book's title instead and no count or series chrome.
  - *Description*: one blurb under the header, clamped to ~4 lines with an
    expand toggle — the singleton's own book, otherwise the first member by
    `first_publish_year`. No per-book blurbs.
  - *Books*: a dense list ordered by `first_publish_year`. Each row is large
    cover, serif title, author, year and `ShelfButton` — nothing else, and rows
    are not links. Shelving stays on works through the existing endpoint.
  - *Discussions*: the whole series' feed in `DataTable`, with a filter row
    `all · ⟨book⟩ · ⟨book⟩ …` over the per-thread book tag (hidden for
    singletons). A tagged thread shows its book in its row.
  - *Composer*: `ThreadModal` gains an optional "about which book" select,
    hidden for singletons.
  - Threads live at `/series/:slug/threads/:threadId`.
- **No editions list anywhere.** Editions remain in the database as cover and
  blurb supply only.
- **Legacy URLs**: `/works/:id` and `/works/:id/threads/:threadId` become a
  redirect component that reads the work's `series.slug` from
  `GET /api/works/{id}` and `navigate(…, {replace: true})`s. That endpoint
  survives only for this lookup. Every internal link to `/works/:id` (profile
  shelves, home, thread back-path) is repointed at the series URL.
- **Enrichment trigger moves** from first view of a work page to first view of
  its series page: `GET /api/series/{slug}` enriches any unenriched member. This
  is also what feeds detection tier 3, so series coverage grows with views.

**Coverage caveat.** At backfill time only 8 of 98 OL works carry a `series:`
tag and 6 a `franchise:` tag, and heuristic works carry none — most search
results will initially show no tag and open a singleton page.

### API

- `GET /api/series/{slug}` → `{slug, name, kind, description, works: [{id,
  title, author, cover_url, first_publish_year, shelf_status}]}`, members
  ordered by `first_publish_year`, then title. A tombstoned (`merged_into_id`)
  slug answers with the survivor's slug so the client can redirect.
- `GET /api/series/{slug}/threads?work_id=` — the feed, optionally filtered to
  one book's tag.
- `POST /api/series/{slug}/threads` — body may carry `work_id`, which must be a
  member of that series (422 otherwise).
- Singletons are created at ingest (`upsert_work_from_ol` and the heuristic
  path), so every searchable work has a series and a slug from its first
  appearance.

## Testing

The three new rule sets are pure functions and carry the weight:

- `series_identity` — subject blob → container, as a table: franchise wins;
  broadest `series:` when no franchise; name tiebreak; no tags → singleton.
- the edition ladder — each tier beats every combination of lower tiers.
  Regression case: the Heyne German edition must lose to the Del Rey English one
  despite equal completeness.
- `blurb` — strip and score, case by case, including the two live examples.

Above them: API tests for `GET /api/series/{slug}`, the thread-target
constraint, the book-tag filter and search's `series` field; a migration
round-trip; Vitest for the series page (singleton vs series chrome, the tag
filter, shelf-only book rows), the `WorkCard` series tag and the legacy-URL
redirect; and one Playwright pass that searches, clicks a result, lands on its
series page, posts a thread tagged to book two, and confirms the book-two
filter shows it and the book-three filter does not. Google and Open Library
stay mocked with `respx` throughout — no test touches the network.

## Migration of existing data

In the sequence the repo already uses for works:

1. **Migration A** — create `series`, add nullable `works.series_id` and
   `threads.series_id`, replace the thread target constraint.
2. **`python -m scripts.backfill_series`** — derive containers from stored
   tags, give every remaining work a singleton, then set each thread's
   `series_id` from its work while leaving `work_id` in place as the tag. Needs
   no HTTP, so it is a script, not a migration. The 8 existing work-threads land
   in the right room with no visible change.
3. **Migration B** — `works.series_id` NOT NULL, refusing to run if any work is
   unassigned. The same guard the works migration uses against unresolved
   editions.
4. **`python -m scripts.repair_presentation`** — re-pick every representative
   under the new ladder, detach editions whose identity does not match their
   work (*Iron Gold* leaves *Red Rising*), and re-enrich the 4 enriched works.

Both scripts are idempotent and open their own `AsyncSessionLocal`, per the
`scripts/` contract.

**Known adjacent defect, deliberately untouched:** 10 of 18 threads have
neither `work_id` nor `genre_id` — orphaned by the works migration and
unreachable from any page. The backfill reports them and changes nothing.
Deleting or rehoming them is a product decision, not a backfill's.

## Order of work

| # | Slice | Depends on |
|---|---|---|
| **0** | Language ladder, cover order, enrichment identity gate, `repair_presentation` | nothing — ships alone |
| **1** | Series model, detection, `backfill_series` | 0 |
| **2** | Edition family, `blurb.py`, series-wide presentation | 1 |
| **3** | Series page, work page retirement + legacy redirects, thread targeting and tag | 1 |
| **4** | Series tag on search cards, search → series page linking | 3 |

*Amended 2026-09-26:* slices 1, 3 and 4 ship together as the next unit of work;
slice 2 (edition family, `blurb.py`) is independent of them and follows.

Slice 0 stands alone and fixes a bug that is corrupting rows today; it should
ship before any of the series work begins.

## Out of scope

- **Position within a series** ("book 3 of 6") — membership is enough for v1;
  ordering is by publication year.
- **Reader-progress spoiler gating** — the per-thread book tag is the signal it
  would gate on, so it stays a pure addition (Phase 4 of `ROADMAP.md`).
- **Series-level shelving** — shelves stay on works.
- **An admin merge/split UI for series** — `merge_series` is the repair tool, as
  `merge_works` is for works (Phase 5 of `ROADMAP.md`).
- **The 10 orphaned threads** — reported, not repaired.
