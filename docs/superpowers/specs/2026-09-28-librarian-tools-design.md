# Librarian tools — design

**Status:** approved design, not yet planned
**Date:** 2026-09-28
**Follows:** `TODO.md` ("Librarian tools") and §5.4 of
`2026-09-26-catalog-pipeline-design.md`, whose overrides format these tools
write.

## 1. Why

The catalog pipeline gets series and work grouping mostly right, and the
mistakes it makes are fixed today by hand-writing `pipeline/overrides/*.yaml`
from a shell. Runtime works (search ingest between releases, heuristic works)
can only be repaired with `merge_works()` from a Python prompt. A librarian
should be able to fix a book where they see it — on its series page — and have
the fix survive every future release instead of the pipeline re-deriving the
mistake.

## 2. Goals and non-goals

**Goals**
- A trusted user can merge, split, move, reorder, rename, remove and dissolve
  from the series page, and the fix is live immediately.
- Every fix is logged with who, when and why.
- Every fix the overrides format can express is exported to
  `pipeline/overrides/` and kept by every later release.
- Fixes the format cannot express still apply, and are reported as
  runtime-only rather than silently lost.
- Small fixes (everything but merge and split) can be undone.

**Non-goals**
- Librarian promotion, roles, or reputation. v1 is one or two hand-picked
  people with a flag set from a shell; the model must not preclude a role
  enum later.
- A review queue or approval workflow.
- Server-side export (endpoint, automatic PR). Export is a script run by a
  person who commits its output.
- Merging two series wholesale (move members one at a time; dissolve the
  loser).
- Undo for merge and split.
- Editing work metadata (title, author, description, cover).

## 3. Permissions

- `users.is_librarian boolean not null default false`.
- `python -m scripts.grant_librarian <username> [--revoke]` sets it. Idempotent;
  unknown username exits non-zero.
- `require_librarian` dependency (in `services/auth.py`), built on
  `get_current_user`: 403 for a signed-in non-librarian, 401 as today for
  anonymous.
- `UserOut` (and so `/auth/me`) exposes `is_librarian`, which the frontend uses
  only to decide what to render — the API is the enforcement.

## 4. Data

### 4.1 `catalog_corrections`

| column | type | notes |
|---|---|---|
| `id` | uuid pk | |
| `op` | enum `correction_op_enum` | `merge_works`, `split_work`, `set_series`, `set_position`, `remove_from_series`, `reject_series`, `rename_series` |
| `payload` | jsonb not null | app ids the op acted on (work, target, series, editions, position, name) |
| `override` | jsonb null | the exact §5.4 entry; null = runtime-only |
| `runtime_only_reason` | text null | set iff `override` is null, e.g. "heuristic work has no Open Library id" |
| `reason` | text not null | librarian's why; non-empty after strip; exported as the YAML comment |
| `snapshot` | jsonb null | undo state (§6); always null for `merge_works` and `split_work` |
| `work_id` | uuid null, fk works `ON DELETE SET NULL`, indexed | subject work, for filtering and undo lookup |
| `series_id` | uuid null, fk series `ON DELETE SET NULL`, indexed | subject series |
| `user_id` | uuid fk users, not null | |
| `created_at` | timestamptz default now() | |
| `reverted_at` | timestamptz null | |
| `reverted_by_id` | uuid null, fk users | |

`set_position` is a distinct op in the log (reorder is its own action) but
exports as `set_series` with `position`.

The migration adds the enum with an explicit drop in `downgrade()` (CLAUDE.md
gotcha).

### 4.2 Other schema changes (same migration)

- `users.is_librarian`.
- `series.dissolved_at timestamptz null`.
- `work_provenance_enum` gains `override` (for split works).

### 4.3 Provenance

Every `series_members` row a correction writes gets `provenance='override'`
and `confidence='high'`. A correction-created series gets
`provenance='override'`.

### 4.4 Runtime respects corrections

`assign_series` already returns early for release rooms. It also returns early
for a work whose latest unreverted `set_series` / `remove_from_series`
correction exists, so a search re-ingest cannot undo a librarian's placement.
`series_for_subjects` never returns a dissolved series.

## 5. Operations (`services/librarian.py`)

Each operation is one function taking the session, the acting user, its
inputs and `reason`; it applies the change through existing services and
writes its `catalog_corrections` row in the same transaction (the route's
`get_db` session). It raises typed errors the route maps to 409 / 422 (§8).

### 5.1 Export keys

- **Work key**: `external_id` when `source='openlibrary'` (including a split id
  `OL…W~OL…M`); none for heuristic works.
- **Series key**: the series `external_id` when it is already `wd:Q…` or
  `ol:…`; otherwise `ol:<canonical_key>`, emitted with `name:` so the
  pipeline's `set_series` can create it. A singleton has no key (moving *out*
  of one needs none; moving *into* one is not offered).
- **Edition key**: `external_id` when `books.source='openlibrary'`; none for
  Google volumes.

An op is exportable iff every key it needs exists; otherwise `override` is
null and `runtime_only_reason` names the first missing key.

### 5.2 The seven operations

| op | app effect | override | snapshot |
|---|---|---|---|
| **merge_works** (source → target) | `merge_works(source, target)` unchanged. Refuses source = target, or either already merged (`merged_into_id`). | `merge_works: [target, source]` | — |
| **split_work** (work, editions) | New work: its title is the representative edition's `display_title`, author the original's, `kind` the original's, room the original's `series_id`, a `series_members` row there with no position. The selected editions' `work_id` moves to it; both works re-pick representatives. Threads and shelves stay on the original. Exportable split: `source='openlibrary'`, `external_id=f"{work}~{min(editions)}"` (the pipeline's `SplitWork.new_work`), a new `work_provenance_enum` value `override` as `identity_provenance` (same migration). Runtime-only: heuristic identity from the new title. Refuses an empty selection or all editions. | `split_work: {work, editions}` | — |
| **set_series** (work → existing series, or new by name; optional position) | Room changes to the target (new series: `kind='series'`, `source='heuristic'`, slug from `unique_slug`). Membership in the old room is removed and a target membership written. Threads tagged with the work get the new `series_id`. An old room left with no members is retired into the target with `retire_series` (tombstone; slug keeps resolving). Refuses a dissolved target or a target that is the current room. | `set_series: {work, series, position?, name?}` | old room id, old membership row, moved thread ids, retired room id |
| **set_position** (series, work, position \| null) | `series_members.position` for that pair; provenance override. Refuses a non-member. | `set_series: {work, series, position}` | old position and provenance |
| **rename_series** (series, name) | `series.name` only; **slug unchanged**. Refuses a singleton or empty name. | `rename_series: {series, name}` | old name |
| **remove_from_series** (series, work) | Work gets a fresh singleton room (`singleton_series_for`); its membership in the series is deleted; its tagged threads move to the singleton. Refuses a singleton series and a non-member. | `remove_from_series: {work, series}` | membership row, thread ids, new singleton id |
| **reject_series** (dissolve) | Every member is removed as above. The series row keeps its slug, gets `dissolved_at`, keeps its untagged threads; its page renders a dissolved notice, those threads, and no books. New threads cannot be created in it. | `reject_series: series` | per-member membership rows, thread ids, singleton ids |

`merge_works` and `split_work` require `confirm: true` in the request body;
without it the route answers 422 with the consequence counts (threads,
shelves, editions affected) so the UI can render the confirmation from real
numbers.

## 6. Undo

`POST /corrections/{id}/revert` undoes a correction when:

1. its op is not `merge_works` / `split_work`, and it is not already reverted;
2. it is the latest unreverted correction on its subject work (or subject
   series for rename/dissolve);
3. current state still equals what it left: for `set_series`, the work's room
   is still the target and the moved threads are still there; for
   `set_position`, the position is unchanged; for `rename_series`, the name;
   for `remove_from_series` / `reject_series`, each singleton still holds only
   its work and the listed threads.

It restores the snapshot: a room the correction retired is revived by
clearing its `merged_into_id`; a singleton the correction created is emptied
back into the restored room and tombstoned into it (`merged_into_id`), so a
link to it that was shared in the meantime still resolves. It then sets
`reverted_at` / `reverted_by_id`, and writes no new correction. A failed
condition is 409 with the reason. Reverted corrections are excluded from
export and from §4.4's "latest correction" rule.

## 7. API (`api/librarian.py`, prefix `/librarian`, mounted under `/api`)

All routes depend on `require_librarian`. Every write body carries `reason`.

```
POST /api/librarian/works/{id}/merge      {into_work_id, reason, confirm}
POST /api/librarian/works/{id}/split      {edition_ids[], reason, confirm}
POST /api/librarian/works/{id}/move       {series_id | new_series_name, position?, reason}
POST /api/librarian/series/{id}/position  {work_id, position | null, reason}
POST /api/librarian/series/{id}/remove    {work_id, reason}
POST /api/librarian/series/{id}/rename    {name, reason}
POST /api/librarian/series/{id}/dissolve  {reason}
GET  /api/librarian/corrections           ?runtime_only=&work_id=&series_id=&limit=&offset=
POST /api/librarian/corrections/{id}/revert
GET  /api/librarian/series-search?q=      series by name, excluding singletons and dissolved
```

Writes return `CorrectionOut`: `id, op, reason, created_at, user (username),
exportable, runtime_only_reason, undoable, reverted_at, room_slug` — the slug
of the room the subject work now lives in, so the page can follow a moved
book. Schemas are built explicitly, never `model_validate` of an ORM object
with relationships (MissingGreenlet).

`GET /api/series/{slug}` gains `dissolved: bool`, and for librarians each
member carries `provenance`, so edit mode can mark override rows.

## 8. Errors

| status | when |
|---|---|
| 401 / 403 | anonymous / not a librarian |
| 404 | unknown work, series, edition or correction |
| 409 | the subject changed underneath: work already merged away, series already dissolved, stale undo, undo not latest |
| 422 | impossible or incomplete: self-merge, non-member, empty reason, missing `confirm`, split of zero or all editions, empty name |

## 9. Export (`scripts/export_overrides.py`)

```
python -m scripts.export_overrides [--out pipeline/overrides/z-librarian.yaml] [--check]
```

- Rewrites the file from every unreverted correction with an `override`,
  ordered by `created_at, id`. Deterministic: same database, same bytes.
- Each entry is preceded by `# <reason>  (<username>, <YYYY-MM-DD>, correction
  <first 8 of id>)`; multi-line reasons become multiple comment lines.
- Named `z-…` so it loads after hand-written files; the pipeline reads
  overrides in name order, so an in-app fix wins a conflict.
- Prints the runtime-only corrections it skipped and their reasons.
- `--check` writes nothing and exits 1 if the file on disk differs.
- Run from a workstation against the production `DATABASE_URL`; the output is
  reviewed and committed like any other change.

The plan must confirm that `pipeline/overrides.apply_series` applies entries in
order (so the last `set_series` for a work wins). If it does not, export keeps
only the latest `set_series` / `remove_from_series` per (work, series).

A later release that no longer holds a work an exported entry names fails the
build, as every stale override does. The fix is to revert the correction in the
app and re-export, or edit the file.

## 10. Frontend

- **Edit toggle**: `[edit]` in the series page's `PathHeader`, rendered only
  for `me.is_librarian`; state in the URL (`?edit=1`).
- **Row actions** (edit mode): `move · position · remove · merge into… · split`
  as `.btn-ghost`; header actions `rename · dissolve`. A singleton page shows
  `move · merge into… · split`. A dissolved series shows no actions.
- **Action panel** (a `DiagnosticFloat`-style float): series picker
  (`series-search`, with a trailing "new series: <name>" row), position number
  field (blank clears), work picker (`/api/works/search`), edition checkboxes,
  required `reason` textarea. Submit is disabled until reason is non-empty.
- **Confirmation** for merge and split: a second step stating the counts the
  422 returned, e.g. "*Dune* (Brian Herbert) will merge into *Dune*. 3 threads
  and 12 shelf entries move. This cannot be undone."
- **Result line**: `ok` "exported" or `warning` "runtime-only: <reason>", with
  `undo` when `undoable`. If `room_slug` differs from the current page, link to
  it.
- **Override marker**: in edit mode, members with `provenance='override'`
  carry an `aria-hidden` glyph plus a visually hidden "librarian-placed" label.
- **`/librarian`**: a `DataTable` of corrections — time, op, subject (link),
  reason, who, export status, undo — with a runtime-only filter. Non-librarians
  get the app's 404.
- **Hooks** in `api/librarian.js`: React Query mutations that invalidate the
  affected series/work queries; errors through `errorMessage()`.
- Tokens only, no new radii/shadows/sizes; `warning` for mutated state, `ok`
  for exported, `danger` for merge/split confirmation.

## 11. Testing

**Backend (pytest)**
- Per op: resulting rows, the correction row, the rendered `override`, and the
  runtime-only reason for heuristic works / Google editions.
- Undo round-trip per undoable op; 409 for stale state and for not-latest.
- 403 for a non-librarian on every route; 422 for missing reason / confirm.
- `assign_series` leaves a correction-placed work alone; a reverted correction
  no longer protects it.
- Export: deterministic bytes, comments, ordering, skipped runtime-only list,
  `--check`.
- Contract: the exported YAML is parsed by the pipeline's own
  `load_overrides()` (imported the way `test_catalog_contract.py` reaches the
  pipeline).
- Loader round-trip: export a merge, a move and a split; build a fixture
  release that reflects them; load it; assert the runtime rows are adopted
  (split work by its `~` id), not duplicated.

**Frontend (Vitest + RTL)**
- `[edit]` hidden for non-librarians; reason required; merge/split
  confirmation shows the server's counts; export badge; undo button.

**E2E (Playwright)**
- A librarian moves a book into a new series, lands on the new room, sees the
  book, and undoes the move.

## 12. Follow-ups

- Promotion and roles (turn `is_librarian` into a role enum).
- Series-to-series merge.
- An export endpoint if production stops being shell-reachable.
- Undo for merge/split, if a real case appears.
