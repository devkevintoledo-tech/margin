# "Recently Fixed" Marker Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** In edit mode, a book fixed in the last 14 days shows who fixed it and when (a `warning` marker plus text), so two librarians don't redo each other's work.

**Architecture:** A new `recent_fixes(db, work_ids)` in `services/librarian/log.py` (created by item 11) finds the newest unreverted correction per work within 14 days. It uses one `DISTINCT ON (work_id)` query for the whole page. `GET /api/series/{slug}` calls it only for librarians and sets `SeriesWorkOut.last_fix`. For everyone else it leaves the field unset, and the route's `response_model_exclude_unset=True` drops the key from the JSON. The series page renders a `RecentFix` line in edit mode.

**Tech Stack:** FastAPI 0.111 (`response_model_exclude_unset`), async SQLAlchemy 2.0 (Postgres `DISTINCT ON`), Pydantic v2, React 18, Tailwind tokens, pytest, Vitest + RTL, Playwright.

**Spec:** docs/librarian-ux-roadmap.md §12

- [ ] **Roadmap item:** 12 — tick in docs/librarian-ux-roadmap.md when merged

## Global Constraints

- Depends on item **11** being merged: `backend/app/services/librarian/log.py`, `tests/query_count.count_statements`, and `tests/librarian_factories.make_fix_row` must exist. Check with `ls backend/app/services/librarian/log.py backend/tests/query_count.py && grep -n "def make_fix_row" backend/tests/librarian_factories.py`.
- Shared name (binding, from the roadmap): for librarians, `SeriesWorkOut` gains `last_fix: {op, user, created_at} | null`. This is the newest **unreverted** correction on that work within **14 days**.
- **Readers and anonymous callers never receive the field.** The key is absent from their JSON, not `null`. Librarians always get the key: an object, or `null` when nothing is recent.
- **One query for the whole page**, never one per row. Task 2 asserts that a librarian's page costs exactly one statement more than a reader's.
- Marker: the `warning` token on an `aria-hidden` `■`, followed by readable text in `ink-dim` (who in `user`). Colour never carries the meaning alone. The marker shows in edit mode only.
- Repo rules in `CLAUDE.md` apply verbatim: `api/` thin, async everywhere, schemas built explicitly, tokens only, no new radii/shadows/sizes/durations, `aria-hidden` on every glyph, §36 test. This item adds no write, no route and no migration.
- Branch `feat/librarian-lx12-recently-fixed-marker` from `main`, one commit per task, PR to `main`.
- **`PYTEST`** (from the repo root): `docker compose run --rm --no-deps -v "$PWD/pipeline:/pipeline:ro" -e DATABASE_URL=postgresql+asyncpg://margin:margin@db:5432/margin_test backend pytest <args>`. Frontend unit tests run from `frontend/`: `npx vitest run <path>`.

## Review Focus

1. **The newest fix was undone.** The marker must fall back to the newest *unreverted* fix still in the window, or show nothing. It must not show the undone fix, and it must not vanish while an older live fix remains. Task 1 `test_recent_fixes_is_the_newest_unreverted_fix_within_14_days`.
2. **The window edge.** A fix 14 days minus a minute ago shows. One 14 days plus a minute ago does not. Task 1 (same test, `edge` and `stale` rows).
3. **A field added to `SeriesWorkOut` later with a default, and not passed explicitly.** `exclude_unset` would silently drop it for everyone. The key-set test in `test_series_api.py` (anonymous shape) and Task 2's librarian key-set assertion catch this. `CLAUDE.md` records the rule (Task 5).
4. **The librarian's own fix.** It reads "by you", so a librarian can tell their own work from a colleague's. Task 3 `says "you" for the librarian's own fix`.
5. **A fix made seconds ago.** `relativeTime` returns `now`. The text must read "fixed just now", not "fixed now ago". Task 3 `RecentFix` test.

---

## File Structure

**Backend — modify**
- `backend/app/schemas/series.py`: `LastFix`, and `SeriesWorkOut.last_fix`.
- `backend/app/services/librarian/log.py`: `RECENT_FIX_WINDOW`, `recent_fixes`.
- `backend/app/api/series.py`: `get_series` sets `last_fix` for librarians and adds `response_model_exclude_unset=True`.

**Backend — create**
- `backend/tests/test_series_last_fix.py`.

**Frontend — create**
- `frontend/src/components/librarian/RecentFix.jsx` (+ `RecentFix.test.jsx`).

**Frontend — modify**
- `frontend/src/pages/Series.jsx` (`BookRow`) and `Series.test.jsx`.
- `frontend/e2e/librarian.spec.js` (one scenario).

**Docs — modify:** `docs/librarian-ux-roadmap.md`, `ROADMAP.md`, `CLAUDE.md`.

---

### Task 1: `recent_fixes`, one query for a page of books

**Files:**
- Modify: `backend/app/schemas/series.py`
- Modify: `backend/app/services/librarian/log.py`
- Create: `backend/tests/test_series_last_fix.py`

**Interfaces:**
- Consumes: `make_fix_row`, `count_statements` (item 11).
- Produces: `LastFix(BaseModel) {op: CorrectionOp, user: str, created_at: datetime}` in `app.schemas.series`, and `SeriesWorkOut.last_fix: LastFix | None = None`. Also `RECENT_FIX_WINDOW = timedelta(days=14)` and `recent_fixes(db: AsyncSession, work_ids: Sequence[UUID], *, now: datetime | None = None) -> dict[UUID, LastFix]`. It issues exactly 1 statement, or 0 for an empty list. Works with nothing recent are absent from the dict.

- [ ] **Step 1: Create the branch and confirm 11 is in**

```bash
git switch main && git pull && git switch -c feat/librarian-lx12-recently-fixed-marker
ls backend/app/services/librarian/log.py backend/tests/query_count.py && grep -n "def make_fix_row" backend/tests/librarian_factories.py
```
Expected: both paths and the `def make_fix_row` line are printed.

- [ ] **Step 2: Write the failing test**

`backend/tests/test_series_last_fix.py`:

```python
"""'Recently fixed': the newest unreverted fix per book within 14 days, for librarians only."""

import uuid
from datetime import datetime, timedelta, timezone

from app.models import CorrectionOp
from app.schemas.series import LastFix
from app.services.librarian.log import RECENT_FIX_WINDOW, recent_fixes
from tests.librarian_factories import headers_for, make_fix_row, make_member, make_series, make_user, make_work
from tests.query_count import count_statements

NOW = datetime(2026, 9, 29, 12, 0, tzinfo=timezone.utc)
DAY, MINUTE = timedelta(days=1), timedelta(minutes=1)


async def test_recent_fixes_is_the_newest_unreverted_fix_within_14_days(db_session):
    ada = await make_user(db_session, librarian=True, username=f"ada{uuid.uuid4().hex[:4]}")
    bo = await make_user(db_session, librarian=True, username=f"bo{uuid.uuid4().hex[:4]}")
    saga = await make_series(db_session, "Saga")
    fresh, stale, edge, undone, quiet = [await make_work(db_session, t, series=saga)
                                         for t in ("Fresh", "Stale", "Edge", "Undone", "Quiet")]
    op = CorrectionOp
    await make_fix_row(db_session, ada, op.set_series, work=fresh, series=saga, created_at=NOW - 3 * DAY)
    await make_fix_row(db_session, bo, op.set_position, work=fresh, series=saga, created_at=NOW - DAY)
    await make_fix_row(db_session, ada, op.set_position, work=stale, series=saga,
                       created_at=NOW - RECENT_FIX_WINDOW - MINUTE)
    await make_fix_row(db_session, ada, op.set_position, work=edge, series=saga,
                       created_at=NOW - RECENT_FIX_WINDOW + MINUTE)
    await make_fix_row(db_session, ada, op.set_series, work=undone, series=saga, created_at=NOW - 2 * DAY)
    await make_fix_row(db_session, bo, op.set_position, work=undone, series=saga, created_at=NOW - DAY,
                       reverted_at=NOW - DAY / 2)

    ids = [fresh.id, stale.id, edge.id, undone.id, quiet.id]
    with count_statements(db_session) as seen:
        fixes = await recent_fixes(db_session, ids, now=NOW)
    assert len(seen) == 1
    assert fixes == {
        fresh.id: LastFix(op=op.set_position, user=bo.username, created_at=NOW - DAY),
        edge.id: LastFix(op=op.set_position, user=ada.username, created_at=NOW - RECENT_FIX_WINDOW + MINUTE),
        undone.id: LastFix(op=op.set_series, user=ada.username, created_at=NOW - 2 * DAY),  # the undo is skipped
    }

    with count_statements(db_session) as none:
        assert await recent_fixes(db_session, [], now=NOW) == {}
    assert none == []
```

- [ ] **Step 3: Run it to verify it fails**

Run: `PYTEST tests/test_series_last_fix.py -q`
Expected: FAIL with `ImportError: cannot import name 'LastFix' from 'app.schemas.series'`.

- [ ] **Step 4: Add the schema**

In `backend/app/schemas/series.py`, add `from datetime import datetime` and `from app.models.correction import CorrectionOp` to the imports. Add above `SeriesWorkOut`:

```python
class LastFix(BaseModel):
    """The newest unreverted librarian fix on a book within the recent window."""

    op: CorrectionOp
    user: str  # username
    created_at: datetime
```

Add to `SeriesWorkOut` after `provenance`:

```python
    # Librarians only: the newest unreverted fix within 14 days, or null. Left
    # unset for everyone else, so the route's exclude_unset omits the key.
    last_fix: LastFix | None = None
```

- [ ] **Step 5: Implement `recent_fixes`**

Append to `backend/app/services/librarian/log.py`. Add `from datetime import datetime, timedelta, timezone` and `from app.schemas.series import LastFix` to its imports (`select`, `CatalogCorrection`, `User`, `Sequence` and `UUID` are already imported there):

```python
# How long a fix counts as recent on the series page (roadmap item 12).
RECENT_FIX_WINDOW = timedelta(days=14)


async def recent_fixes(db: AsyncSession, work_ids: Sequence[UUID], *,
                       now: datetime | None = None) -> dict[UUID, LastFix]:
    """The newest unreverted fix per book within ``RECENT_FIX_WINDOW``, in one
    query for the whole page. Books with nothing recent are absent."""
    if not work_ids:
        return {}
    since = (now or datetime.now(timezone.utc)) - RECENT_FIX_WINDOW
    rows = (await db.execute(
        select(CatalogCorrection.work_id, CatalogCorrection.op, CatalogCorrection.created_at, User.username)
        .join(User, User.id == CatalogCorrection.user_id)
        .where(CatalogCorrection.work_id.in_(list(work_ids)), CatalogCorrection.reverted_at.is_(None),
               CatalogCorrection.created_at >= since)
        .order_by(CatalogCorrection.work_id, CatalogCorrection.created_at.desc(), CatalogCorrection.id.desc())
        .distinct(CatalogCorrection.work_id)
    )).all()
    return {r.work_id: LastFix(op=r.op, user=r.username, created_at=r.created_at) for r in rows}
```

`catalog_corrections.work_id` is already indexed, so the query needs no migration.

- [ ] **Step 6: Run it to verify it passes**

Run: `PYTEST tests/test_series_last_fix.py -q`
Expected: `1 passed`.

- [ ] **Step 7: Commit**

```bash
git add backend/app/schemas/series.py backend/app/services/librarian/log.py backend/tests/test_series_last_fix.py
git commit -m "feat(librarian): recent_fixes, the newest live fix per book in one query"
```

---

### Task 2: The series page carries `last_fix` for librarians only

**Files:**
- Modify: `backend/app/api/series.py` (`get_series`)
- Test: `backend/tests/test_series_last_fix.py`

**Interfaces:**
- Consumes: `recent_fixes` and `LastFix` (Task 1).
- Produces: `GET /api/series/{slug}`, whose `works[*].last_fix` is present only when the caller is a librarian (`{op, user, created_at}` or `null`). Every other field keeps today's shape. Readers still get `provenance: null`.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_series_last_fix.py`:

```python
R = "2026.10.1"


async def _saga(db, lib, n=2):
    saga = await make_series(db, "Saga", release=R)
    works = []
    for i in range(n):
        w = await make_work(db, f"Book {i}", series=saga, ol_id=f"OL{i + 1}W")
        await make_member(db, saga, w, float(i + 1))
        works.append(w)
    return saga, works


async def test_librarians_get_last_fix_and_readers_never_get_the_field(client, db_session):
    lib, reader = await make_user(db_session, librarian=True), await make_user(db_session)
    saga, (fixed, old) = await _saga(db_session, lib)
    now = datetime.now(timezone.utc)
    await make_fix_row(db_session, lib, CorrectionOp.set_position, work=fixed, series=saga, created_at=now - DAY)
    await make_fix_row(db_session, lib, CorrectionOp.set_position, work=old, series=saga, created_at=now - 20 * DAY)

    as_lib = (await client.get(f"/api/series/{saga.slug}", headers=headers_for(lib))).json()
    by_title = {w["title"]: w for w in as_lib["works"]}
    assert by_title["Book 0"]["last_fix"]["op"] == "set_position"
    assert by_title["Book 0"]["last_fix"]["user"] == lib.username
    assert by_title["Book 1"]["last_fix"] is None  # the key is there, and says nothing is recent
    assert set(by_title["Book 0"]) == {"id", "title", "author", "first_publish_year", "cover_url", "shelf_status",
                                       "position", "subseries", "provenance", "last_fix"}

    for headers in (headers_for(reader), {}):
        body = (await client.get(f"/api/series/{saga.slug}", headers=headers)).json()
        assert body["works"], body
        assert all("last_fix" not in w for w in body["works"])
        assert all(w["provenance"] is None for w in body["works"])  # unchanged


async def test_last_fix_costs_one_query_for_the_whole_page(client, db_session):
    lib, reader = await make_user(db_session, librarian=True), await make_user(db_session)
    saga, works = await _saga(db_session, lib, n=6)
    now = datetime.now(timezone.utc)
    for w in works:
        await make_fix_row(db_session, lib, CorrectionOp.set_position, work=w, series=saga, created_at=now - DAY)
    path = f"/api/series/{saga.slug}"
    await client.get(path, headers=headers_for(reader))  # warm-up: first view may enrich or settle rows

    db_session.expunge_all()
    with count_statements(db_session) as as_reader:
        await client.get(path, headers=headers_for(reader))
    db_session.expunge_all()
    with count_statements(db_session) as as_lib:
        resp = await client.get(path, headers=headers_for(lib))
    assert all(w["last_fix"] is not None for w in resp.json()["works"])
    assert len(as_lib) == len(as_reader) + 1, as_lib
```

- [ ] **Step 2: Run them to verify they fail**

Run: `PYTEST tests/test_series_last_fix.py -q`
Expected: the first new test fails with `KeyError: 'last_fix'` on the librarian's response. The second fails on `w["last_fix"]`.

- [ ] **Step 3: Implement it in the route**

In `backend/app/api/series.py`:

1. Add `from app.services.librarian.log import recent_fixes` to the imports.
2. Change the decorator to `@router.get("/{slug}", response_model=SeriesOut, response_model_exclude_unset=True)`.
3. After the line `librarian = current_user is not None and current_user.is_librarian`, add:

```python
    fixes = await recent_fixes(db, [w.id for w in works]) if librarian else {}
```

4. In the `SeriesWorkOut(...)` constructor, after `provenance=m.provenance if librarian else None,`, add:

```python
                # Set for librarians only; left unset, exclude_unset drops the key for readers.
                **({"last_fix": fixes.get(w.id)} if librarian else {}),
```

5. Check the rest of the constructor. `exclude_unset` omits any field that is not passed, so every `SeriesOut` and `SeriesWorkOut` field must be passed explicitly, including fields other items added. Run: `grep -n ": .* = " backend/app/schemas/series.py`. Compare that output with the keyword arguments in `get_series`. Pass any field that is missing.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `PYTEST tests/test_series_last_fix.py tests/test_series_api.py tests/test_librarian_api.py -q`
Expected: all pass. `test_series_page_lists_books_in_publication_order` still sees exactly its 9 keys for an anonymous caller.

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/series.py backend/tests/test_series_last_fix.py
git commit -m "feat(series): last_fix on each book for librarians; readers never get the field"
```

---

### Task 3: The marker on the series page

**Files:**
- Create: `frontend/src/components/librarian/RecentFix.jsx`
- Create: `frontend/src/components/librarian/RecentFix.test.jsx`
- Modify: `frontend/src/pages/Series.jsx` (`BookRow` and where it is rendered)
- Test: `frontend/src/pages/Series.test.jsx`

**Interfaces:**
- Consumes: `work.last_fix` (Task 2) and `relativeTime` from `components/Post`.
- Produces: `<RecentFix fix={{ op, user, created_at }} me={username} />`, which renders `<p>` with the text `■ fixed <age> ago by <user|you> · <op>`, or "fixed just now" when the age is under a minute. The `■` is `text-warning` and `aria-hidden`. `BookRow` gets a `me` prop and shows the marker when `editing && work.last_fix`.

- [ ] **Step 1: Write the failing tests**

`frontend/src/components/librarian/RecentFix.test.jsx`:

```jsx
import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import RecentFix from './RecentFix'

const ago = (ms) => new Date(Date.now() - ms).toISOString()
const DAY = 86400000

describe('RecentFix', () => {
  it('says who fixed the book, when, and how, with a decorative marker', () => {
    const { container } = render(<RecentFix fix={{ op: 'set_position', user: 'ada', created_at: ago(3 * DAY) }} me="bo" />)
    expect(container.querySelector('p')).toHaveTextContent('fixed 3d ago by ada · set_position')
    const marker = screen.getByText('■')
    expect(marker).toHaveAttribute('aria-hidden', 'true')
    expect(marker).toHaveClass('text-warning')
  })

  it('reads "just now" for a fix made seconds ago, and "you" for your own', () => {
    const { container } = render(<RecentFix fix={{ op: 'set_series', user: 'bo', created_at: ago(5000) }} me="bo" />)
    expect(container.querySelector('p')).toHaveTextContent('fixed just now by you · set_series')
  })
})
```

Append to `frontend/src/pages/Series.test.jsx`, inside the existing `describe`. If item 01 has merged, first add `useLibrarianStore.setState({ editMode: false })` to this file's `beforeEach`, the same way 01's tests reset it (import `useLibrarianStore` from `../store/librarian`). Otherwise edit mode leaks between tests.

```jsx
  it('marks a recently fixed book in edit mode with who and when', async () => {
    useAuthStore.setState({ token: 't', user: { id: 'u1', username: 'lib', is_librarian: true } })
    const fix = { op: 'set_position', user: 'ada', created_at: new Date(Date.now() - 3 * 86400000).toISOString() }
    mockApi({ ...SAGA, id: 's1', works: [{ ...SAGA.works[0], last_fix: fix }, { ...SAGA.works[1], last_fix: null }] })
    renderPage('/series/red-rising?edit=1')
    const list = await screen.findByRole('list', { name: 'Books in this series' })
    const [first, second] = within(list).getAllByRole('listitem')
    expect(within(first).getByText(/^fixed/).closest('p')).toHaveTextContent('fixed 3d ago by ada · set_position')
    expect(within(second).queryByText(/^fixed/)).toBeNull()
  })

  it('says "you" for the librarian\'s own fix, and shows nothing outside edit mode', async () => {
    useAuthStore.setState({ token: 't', user: { id: 'u1', username: 'lib', is_librarian: true } })
    const fix = { op: 'set_series', user: 'lib', created_at: new Date().toISOString() }
    mockApi({ ...SAGA, id: 's1', works: [{ ...SAGA.works[0], last_fix: fix }, SAGA.works[1]] })
    const view = renderPage('/series/red-rising?edit=1')
    const list = await screen.findByRole('list', { name: 'Books in this series' })
    expect(within(list).getByText(/^fixed/).closest('p')).toHaveTextContent('fixed just now by you · set_series')
    view.unmount()

    renderPage('/series/red-rising')
    const plain = await screen.findByRole('list', { name: 'Books in this series' })
    expect(within(plain).queryByText(/^fixed/)).toBeNull()
  })
```

`renderPage` in `Series.test.jsx` returns RTL's `render(...)` result. If it does not, change its body to `return render(...)`.

- [ ] **Step 2: Run them to verify they fail**

Run: `npx vitest run src/components/librarian/RecentFix.test.jsx src/pages/Series.test.jsx`
Expected: FAIL. `./RecentFix` cannot be resolved, and the Series tests find no text matching `/^fixed/`.

- [ ] **Step 3: Write `RecentFix.jsx`**

```jsx
import { relativeTime } from '../Post'

/**
 * "Someone fixed this lately": the warning marker says *mutated*, the text says
 * who and when, so colour never carries it alone. Edit mode only.
 */
function RecentFix({ fix, me }) {
  const age = relativeTime(fix.created_at)
  return (
    <p className="text-xs">
      <span aria-hidden="true" className="text-warning">■</span>{' '}
      <span className="text-ink-dim">
        fixed <time dateTime={fix.created_at}>{age === 'now' ? 'just now' : `${age} ago`}</time> by{' '}
        <span className="text-user">{fix.user === me ? 'you' : fix.user}</span> · {fix.op}
      </span>
    </p>
  )
}

export default RecentFix
```

- [ ] **Step 4: Wire it into `BookRow`**

In `frontend/src/pages/Series.jsx`:

1. Add the import: `import RecentFix from '../components/librarian/RecentFix'`.
2. Add `me` to `BookRow`'s destructured props and keep every other prop.
3. Directly after the existing `librarian-placed` block (`{editing && work.provenance === 'override' && (...)}`), add:

```jsx
        {editing && work.last_fix && <RecentFix fix={work.last_fix} me={me} />}
```

4. Where `Series` renders `<BookRow ... />`, add `me={user?.username}`.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `npx vitest run src/components/librarian/RecentFix.test.jsx src/pages/Series.test.jsx`
Expected: all pass.

- [ ] **Step 6: §36 check, then commit**

With the stack up, open a series page in edit mode and make a fix. The row must gain one quiet line under the title block, `■ fixed just now by you · set_position`, with the cover still dominant. There must be no badge, pill or coloured row background. Then:

```bash
git add frontend/src/components/librarian/RecentFix.jsx frontend/src/components/librarian/RecentFix.test.jsx frontend/src/pages/Series.jsx frontend/src/pages/Series.test.jsx
git commit -m "feat(web): recently fixed marker on series rows in edit mode"
```

---

### Task 4: End to end: a fix leaves a marker

**Files:**
- Modify: `frontend/e2e/librarian.spec.js` (append one test)

**Interfaces:**
- Consumes: `registerViaUi`, `grantLibrarian`, `openFirstSearchResult` from `e2e/helpers.js`, plus the whole stack.

- [ ] **Step 1: Write the scenario**

Append to `frontend/e2e/librarian.spec.js`:

```js
// Item 12: a book a librarian just fixed says so, in edit mode only.
test('a freshly fixed book shows who fixed it and when, in edit mode', async ({ page }) => {
  const user = await registerViaUi(page)
  grantLibrarian(user)
  await page.reload()

  await openFirstSearchResult(page, 'a wizard of earthsea')
  const url = new URL(page.url())
  url.searchParams.set('edit', '1')
  await page.goto(url.toString())
  const books = page.getByRole('list', { name: 'Books in this series' })
  const title = await books.getByRole('heading').first().textContent()

  await books.getByRole('button', { name: `move ${title}`, exact: true }).click()
  const saga = `E2E Marker ${Date.now()}`
  await page.getByLabel('Find a series').fill(saga)
  await page.getByRole('radio', { name: `new series: ${saga}` }).check()
  await page.getByLabel('Reason', { exact: true }).fill('e2e: marker')
  await page.getByRole('button', { name: 'Move', exact: true }).click()
  const status = page.getByRole('group', { name: 'Librarian fix result' })
  const follow = status.getByRole('link', { name: /go to its page/ })
  const heading = page.getByRole('heading', { level: 1, name: saga })
  await expect(async () => {
    if (await follow.isVisible()) await follow.click({ timeout: 1000 }).catch(() => {})
    await expect(heading).toBeVisible({ timeout: 1000 })
  }).toPass()

  const marker = books.locator('p', { hasText: /fixed (just now|\d+m ago) by you · set_series/ })
  await expect(marker).toBeVisible()
  const done = page.getByRole('link', { name: '[done]' }).or(page.getByRole('button', { name: '[done]' }))
  await done.click()
  await expect(marker).toBeHidden()
})
```

- [ ] **Step 2: Run it**

With the stack up in another terminal (`docker compose up --build`), run from `frontend/`: `npm run test:e2e -- librarian.spec.js`
Expected: every scenario in the file passes, including this one.

- [ ] **Step 3: Commit**

```bash
git add frontend/e2e/librarian.spec.js
git commit -m "test(e2e): recently fixed marker"
```

---

### Task 5: Docs and tracker

**Files:**
- Modify: `docs/librarian-ux-roadmap.md`, `ROADMAP.md`, `CLAUDE.md`, and this plan's header checkbox

- [ ] **Step 1: Update them**

- `docs/librarian-ux-roadmap.md`, tracker row 12: set Status `✅`, Branch `feat/librarian-lx12-recently-fixed-marker`, Done to the merge date, and PR to the PR number. Under **Notes**, add a dated line: "12 — `last_fix` comes from `services/librarian/log.recent_fixes` (one `DISTINCT ON` query, `RECENT_FIX_WINDOW` = 14 days). `GET /series/{slug}` now uses `response_model_exclude_unset=True`, so readers get no `last_fix` key. Any new `SeriesWorkOut`/`SeriesOut` field must be passed explicitly in `get_series` or it disappears for everyone."
- `ROADMAP.md`, Phase 5 table: add under the item 11 row:
  `| ✅ | **Recently fixed marker** — in edit mode a book fixed in the last 14 days shows who and when (\`■\` warning + text); librarians only, one query per page. | [plan](docs/superpowers/plans/2026-09-29-lx12-recently-fixed-marker.md), \`services/librarian/log.py\`, \`api/series.py\`, \`components/librarian/RecentFix.jsx\` |`
- `CLAUDE.md`, in the **Series** paragraph after "a singleton renders with no series chrome.", add: "For librarians each book on the page carries `last_fix` (the newest unreverted fix within 14 days, `recent_fixes`). The route uses `response_model_exclude_unset`, so readers never receive that key, and every other field must be passed explicitly in `get_series`."
- This plan's header: tick **Roadmap item**.

- [ ] **Step 2: Verify everything, then commit**

Run `PYTEST -q -p no:warnings`, then `cd frontend && npm test && npm run build`.
Expected: all green, and the build succeeds.

```bash
git add docs/librarian-ux-roadmap.md ROADMAP.md CLAUDE.md docs/superpowers/plans/2026-09-29-lx12-recently-fixed-marker.md
git commit -m "docs: recently fixed marker (lx12)"
```

---

## Self-review

- **Spec coverage (§12 and shared names):** `last_fix: {op, user, created_at} | null` is on `SeriesWorkOut` for librarians (Tasks 1–2). It is the newest unreverted fix within 14 days (Task 1 test), fetched in a single query (Task 1 counts 1 statement; Task 2 counts +1 per page). Readers never receive the field (Task 2, absent key for reader and anonymous). The marker uses the `warning` token plus text in edit mode (Task 3). The roadmap and docs are Task 5.
- **Placeholders:** none. The one execution-time check (fields other items added to `SeriesWorkOut`) names the grep and the fix.
- **Type consistency:** `LastFix(op, user, created_at)` is the same in the schema, `recent_fixes`, the JSON the frontend reads (`work.last_fix.user` / `.op` / `.created_at`), and `RecentFix`'s `fix` prop. `RECENT_FIX_WINDOW` is imported by the test rather than re-typed.
- **Review Focus:** each of the five lines names the test that pins it.
