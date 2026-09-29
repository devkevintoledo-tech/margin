# Librarian UX roadmap

**Started:** 2026-09-29
**Follows:** [librarian tools design](superpowers/specs/2026-09-28-librarian-tools-design.md) (v1, shipped)
**Why:** v1 tools work, but only from a series page in edit mode, one book at a
time, with a typed reason every time. Duplicates are found in search yet merged
somewhere else; a series cannot take a book in; covers cannot be chosen; the
system never points a librarian at what needs fixing. This roadmap makes the
common fixes fast and brings the work to the librarian.

This file is both the tracker and the shared design: each item's section fixes
the names every plan relies on, so the plans can be written and executed out of
order without contradicting each other. A plan that needs to change one of
these names changes it **here first**.

## How to use this file

- Work items **in order** unless the *Depends on* column says otherwise.
- When you start one: status `🟡 in progress`, fill *Branch*.
- When it merges: status `✅ done`, fill *Done* (date) and *PR*, tick its
  checkbox in the plan's header, and add a line to `ROADMAP.md`'s Phase table
  if it changes what the product does.
- Found something the plan got wrong? Fix the plan and note it under the item's
  **Notes** below, so the next item doesn't inherit the mistake.

Status: ⬜ not started · 🟡 in progress · ✅ done · ⏸ parked

## Tracker

| # | Item | Plan | Depends on | Status | Branch | Done | PR |
|---|---|---|---|---|---|---|---|
| 01 | Sticky edit mode | [plan](superpowers/plans/2026-09-29-lx01-sticky-edit-mode.md) | — | ✅ | feat/librarian-lx01-sticky-edit-mode | 2026-09-29 | #15 |
| 02 | Quick reasons | [plan](superpowers/plans/2026-09-29-lx02-quick-reasons.md) | — | ✅ | feat/librarian-lx02-quick-reasons | 2026-09-29 | #16 |
| 03 | Add a book from the series page | [plan](superpowers/plans/2026-09-29-lx03-add-book-to-series.md) | — | ✅ | feat/librarian-lx03-add-book | 2026-09-29 | #17 |
| 04 | Side-by-side merge preview | [plan](superpowers/plans/2026-09-29-lx04-merge-preview.md) | — | ⬜ | | | |
| 05 | Merge from search results | [plan](superpowers/plans/2026-09-29-lx05-merge-from-search.md) | 04 | ⬜ | | | |
| 06 | Cover picker | [plan](superpowers/plans/2026-09-29-lx06-cover-picker.md) | — | ⬜ | | | |
| 07 | Keep the best of both on merge | [plan](superpowers/plans/2026-09-29-lx07-merge-keep-best.md) | 04, 06 | ⬜ | | | |
| 08 | Batch actions | [plan](superpowers/plans/2026-09-29-lx08-batch-actions.md) | 02 | ⬜ | | | |
| 09 | Drag to reorder | [plan](superpowers/plans/2026-09-29-lx09-drag-reorder.md) | 08 | ⬜ | | | |
| 10 | Keyboard shortcuts | [plan](superpowers/plans/2026-09-29-lx10-keyboard-shortcuts.md) | 01, 03, 08 | ⬜ | | | |
| 11 | Fix log filters, links and per-book history | [plan](superpowers/plans/2026-09-29-lx11-fix-log-history.md) | 08 | ⬜ | | | |
| 12 | "Recently fixed" marker | [plan](superpowers/plans/2026-09-29-lx12-recently-fixed-marker.md) | 11 | ⬜ | | | |
| 13 | Series health checks + librarian queue | [plan](superpowers/plans/2026-09-29-lx13-series-health-queue.md) | — | ⬜ | | | |
| 14 | Duplicate queue | [plan](superpowers/plans/2026-09-29-lx14-duplicate-queue.md) | 04, 13 | ⬜ | | | |
| 15 | Report a problem (readers) | [plan](superpowers/plans/2026-09-29-lx15-report-a-problem.md) | 13 | ⬜ | | | |
| 16 | Undoable merge | [plan](superpowers/plans/2026-09-29-lx16-undoable-merge.md) | 07, 08 | ⬜ | | | |

Suggested waves: **A** 01–03 (small, frontend-first) · **B** 04–07 (merge &
covers) · **C** 08–10 (bulk) · **D** 11–12 (visibility) · **E** 13–15 (queue) ·
**F** 16.

## Constraints every plan inherits

- Repo rules in `CLAUDE.md` apply verbatim: strict layering (`api/` thin,
  `services/librarian/` is the only writer of `catalog_corrections`), async
  everywhere, schemas built explicitly (never `model_validate` of an ORM object
  with relationships), design tokens only, serif only for book titles, no new
  radii/shadows/sizes/durations, `aria-hidden` on every glyph, §36 test.
- **Migrations**: autogenerate at execution time with `down_revision` = the
  head *then*. Never hardcode a revision id in a plan — items merge in an order
  the plan author cannot know. New `correction_op_enum` values are added with
  `ALTER TYPE correction_op_enum ADD VALUE IF NOT EXISTS '<v>'` (autogenerate
  does not see enum value additions); downgrade leaves the value in place and
  says so in a comment (Postgres cannot drop an enum value).
- **Every new write is a correction.** It carries a required, non-empty
  `reason`, is logged in `catalog_corrections`, and states whether it exports
  (`override`) or is runtime-only (`runtime_only_reason`), exactly like v1.
- Every librarian route depends on `require_librarian`; every test module that
  adds a route asserts 401 anonymous / 403 reader for it.
- Tests: pytest against `margin_test`, Vitest + RTL, one Playwright scenario per
  item that changes a user-visible flow. Network always mocked.
- One branch per item, `feat/librarian-lx<NN>-<slug>`, from `main`; commit per
  task; PR to `main`.

## Shared names (the contract between plans)

### Frontend
- `frontend/src/store/librarian.js` — Zustand store, `persist` key
  `margin-librarian`: `{ editMode: boolean, setEditMode(v) }` (01). Later items
  may add fields; never rename these.
- `frontend/src/components/librarian/` — new librarian components live here.
  `LibrarianPanel.jsx` stays where it is.
- `WorkPicker` and `SeriesPicker` are exported from
  `components/librarian/pickers.jsx` (moved out of `LibrarianPanel.jsx` by 03),
  with a `label` prop.
- `components/librarian/ReasonField.jsx` — reason textarea + preset chips (02);
  every panel/float that asks for a reason uses it.
- `components/librarian/MergePreview.jsx` — `<MergePreview preview={MergePreviewOut}
  onSwap={() => …} />` (04). Used by 05, 07, 14.
- `/librarian` page becomes tabbed: `fixes` (the existing table) · `queue` (13).
  Tab in the URL: `/librarian?tab=queue`. The queue tab renders sections in
  order: **reports** (15) · **duplicates** (14) · **series health** (13).

### Backend
- **Batch** (08): `catalog_corrections.batch_id uuid null, indexed`.
  `POST /api/librarian/batch {reason, actions: [BatchAction]}` →
  `BatchOut {batch_id, corrections: [CorrectionOut]}`; `BatchAction` is a
  discriminated union on `kind` ∈ `move | position | remove` with the same
  fields as the single routes. All-or-nothing (one transaction).
  `POST /api/librarian/batches/{batch_id}/revert` undoes every member, newest
  first, all-or-nothing. `CorrectionOut` gains `batch_id`.
- **Merge preview** (04): `GET /api/librarian/works/{id}/merge-preview?into={id}`
  → `MergePreviewOut {source: MergeSide, target: MergeSide, threads, shelves,
  editions}`, `MergeSide {id, title, author, first_publish_year, cover_url,
  description, edition_count, thread_count, shelf_count, series_slug,
  series_name}`. Refuses self/merged exactly like merge.
- **Cover** (06): new op `set_cover`.
  `GET /api/librarian/works/{id}/covers` → `[CoverOption {book_id, cover_url,
  title, published_year, language, source, current}]`;
  `POST /api/librarian/works/{id}/cover {book_id, reason}` → `CorrectionOut`.
  Sets `works.representative_book_id`; the representative picker
  (`services/works.py`) and `scripts.repair_presentation` leave a work alone
  while it has an unreverted `set_cover` correction (same rule shape as §4.4).
  Runtime-only unless the pipeline gains a cover override (out of scope):
  `runtime_only_reason = "the overrides format has no cover entry"`. Undoable.
- **Keep the best** (07): merge body gains
  `keep: {title: 'source'|'target', cover: 'source'|'target',
  description: 'source'|'target'}`, each defaulting to `target`. Stored in the
  correction payload. `cover: 'source'` records a follow-up `set_cover` in the
  same transaction; `title`/`description` from source are recorded as a new op
  `set_metadata` (runtime-only).
- **Fix log** (11): `GET /api/librarian/corrections` gains `op`, `user`
  (username), `q` (reason/subject text), `batch_id`. `CorrectionOut` gains
  `subject_href` (a frontend path).
- **Recently fixed** (12): for librarians, `SeriesWorkOut` gains
  `last_fix: {op, user, created_at} | null`, the newest unreverted correction on
  that work within 14 days.
- **Queue** (13–15), all under `/api/librarian/queue/`:
  - `GET health` → `[HealthIssue {kind: 'gap' | 'duplicate_position' |
    'missing_cover' | 'single_book_series', series_id, series_slug,
    series_name, work_ids, detail}]` (13).
  - `GET duplicates` → `[DuplicateCandidate {a: MergeSide, b: MergeSide,
    signal, score}]`; `POST duplicates/dismiss {work_ids: [a, b], reason}`;
    table `duplicate_dismissals` (unordered pair unique) (14).
  - `GET reports`, `POST reports/{id}/resolve {note, correction_id?}`,
    `POST reports/{id}/dismiss {note}`; readers post to
    `POST /api/reports {work_id | series_id, kind, note}` (15). Table
    `catalog_reports`.
- **Undoable merge** (16): `merge_works` corrections gain a snapshot; revert is
  allowed under the same "latest and unchanged since" rule as v1. Supersedes
  "Undo for merge and split" as a non-goal for merge only; split stays
  permanent.

## Items

Each plan carries the full design; these are the one-paragraph intents and the
decisions that are already made.

### 01 · Sticky edit mode
Edit mode survives navigation: `[edit]` toggles `editMode` in the store and
`?edit=1` still turns it on (deep links keep working). Leaving edit mode is
`[done]` anywhere. Readers never see it. Frontend only.

### 02 · Quick reasons
Preset chips above the reason field, per action kind (e.g. merge: "duplicate
record", "same book, different edition"; move: "wrong series", "belongs to
this series"; cover: "wrong language", "low quality"). A chip fills the field;
the librarian can still type. The field stays required. Frontend only; presets
in `components/librarian/reasons.js`.

### 03 · Add a book from the series page
`add a book` in the series header (edit mode, real series only). Opens the
panel with a work search and an optional position; submit is a v1 **move** of
the picked work into this series. If the picked work already lives in another
real series the panel says so before submit. Frontend only.

### 04 · Side-by-side merge preview
Before confirming a merge, both books are shown next to each other — covers,
author, year, editions, threads, shelves, room — with a swap control to choose
which survives. Backend: the merge-preview endpoint above. Frontend:
`MergePreview`, used by the merge panel.

### 05 · Merge from search results
Librarians get a `select` toggle on the search page; checking two results
enables `merge…`, which opens the merge panel with both preset and the preview
shown. Frontend only (uses 04).

### 06 · Cover picker
`cover` row action in edit mode: a grid of every edition's cover (plus OL's
curated one when present), current one marked; clicking one and giving a reason
sets it. Backend: covers list + `set_cover` op as above.

### 07 · Keep the best of both on merge
In the merge preview, per field (title, cover, description) the librarian picks
which side survives. Backend: `keep` on the merge body, `set_metadata` op.

### 08 · Batch actions
In edit mode, rows get checkboxes; a bar offers `move selected…`,
`remove selected…` and `number 1…n` (positions in current order). One reason
for the batch. Backend: batch endpoint + group revert as above; frontend
exposes `useRevertBatch(batchId)` in `api/librarian.js`. Grouping a batch into
one row in the fix log is **item 11's** job, not this one.

### 09 · Drag to reorder
In edit mode, drag a row (or use ▲/▼ buttons for keyboard users) to reorder;
`save order` sends one batch of `position` actions. Positions are renumbered
1…n; sub-series groups reorder within themselves only.

### 10 · Keyboard shortcuts
Series page, edit mode: `j`/`k` move a row cursor, `m` move, `p` position,
`r` remove, `g` merge into, `c` cover, `x` select for batch, `a` add a book,
`e` toggle edit, `?` shows the list. Never fires while typing in a field.
Frontend only.

### 11 · Fix log filters, links and per-book history
Filters on `/librarian` (op, who, text, batch); every subject links to its page;
in edit mode each row gets `history`, a float listing that book's fixes with
undo.

### 12 · "Recently fixed" marker
In edit mode, a row fixed in the last 14 days shows who and when (`warning`
marker + text), so two librarians don't redo each other's work.

### 13 · Series health checks + librarian queue
Computed on request, no table: gaps in positions, two books at one position,
books without a cover, real series with one book. The `/librarian` queue tab
lists them with a link into the series page in edit mode.

### 14 · Duplicate queue
Candidate pairs from: same `canonical_key` or `identity_keys` overlap across
two live works; same normalized title + primary author; title similarity
(`pg_trgm`) ≥ threshold with the same author. Each row shows both sides
(`MergePreview` compact) with `merge…` and `not a duplicate`. Dismissals are
remembered per pair.

### 15 · Report a problem (readers)
Any signed-in reader can report a book or series from its page: kind ∈
`duplicate | wrong_series | wrong_order | bad_cover | other`, optional note.
Reports land in the queue; a librarian resolves (optionally linking the fix)
or dismisses. Rate-limited per user.

### 16 · Undoable merge
A merge records what it moved (editions, threads, shelves, aliases, the
source's room/membership) and can be reverted while nothing has touched those
rows since. Revert restores the source work and un-tombstones it.

## Notes

_(Add dated notes here as items land: surprises, changed names, follow-ups.)_

- **2026-09-29 — prerequisite:** the plans quote code on `fix/librarian-minors`,
  which is not on `main` yet. Merge it before starting item 01.
- **2026-09-29 — plan-time decisions** (from writing the plans; each plan
  repeats its own):
  - 11 owns fix-log batch grouping; 08 only provides `batch_id`, the endpoints
    and `useRevertBatch`.
  - 11 adds `services/librarian/log.py` (`find_corrections`, `corrections_out`)
    and makes `undo.undoable_ids(db, corrections)` the single copy of the undo
    rule; `undoable()` wraps it. 16 extends `undoable_ids` for merges.
  - 11's `work_id` filter also returns fixes on works merged into that work.
  - 12: readers get **no** `last_fix` key (`response_model_exclude_unset` on
    `GET /series/{slug}`), not `null`.
  - 04 adds `merge_consequences` (shared by preview and the 422 confirm) and
    `useMergePreview(sourceId, intoId)`; `MergePreview.onSwap` is optional
    (14's compact rows omit it); `MergeSide.series_name` is null for a singleton.
  - 05: `LibrarianPanel` accepts `action.into` to preset the kept book;
    `WorkCard` takes `selected`/`onSelect`; new `components/librarian/SelectionBar.jsx`.
  - 01: store is the default export `useLibrarianStore`; `?edit=1` is consumed
    and stripped from the URL.
  - 02: `reasons.js` exports `REASONS`, `reasonsFor`, `presetIn`, `applyPreset`;
    `ReasonField` props `kind, value, onChange, id`.
  - 10: keys press the control carrying `aria-keyshortcuts`; row cursor is focus
    on `[data-work-row]`; `c` (cover) only when 06 has landed.
- **2026-09-29 — 01 done (#15):** the `[edit]` toggle is a button now; e2e and
  later plans must use `getByRole('button', { name: '[edit]' })`.
- **2026-09-29 — 02 done (#16):** Playwright's `getByLabel('Reason')` is a
  substring match and now also hits the `Quick reasons` group; every e2e
  step must use `getByLabel('Reason', { exact: true })`. Plans 03, 07, 08, 11,
  12 and 16 are updated to match.
- **2026-09-29 — 02:** `ReasonField` takes `kind`, `value`, `onChange`, `id`
  (default `lib-reason`); a new kind adds its presets to `REASONS` in
  `components/librarian/reasons.js`; a chip with typed text yields
  `<preset>: <text>`, and a bare `<preset>:` still counts as that preset.
- **2026-09-29 — 03 done (#17):** `WorkPicker` shows `in <series>` for hits in a real
  series, and both pickers name their results radiogroup `` `${label}: results` ``
  (label-derived, so two pickers never share a name). That name contains the
  label, so in Playwright every picker lookup must be exact —
  `getByLabel('Find a series', { exact: true })` — as with `Reason`. The "already
  in another series" check reads `WorkOut.series` from `/works/search`; no
  endpoint was added. `LibrarianPanel`'s float now scrolls within the viewport
  (`max-h-full overflow-y-auto`): a long result list had pushed its submit
  button off screen.
