# LX01 · Sticky Edit Mode Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

- [ ] **Roadmap item:** 01 — tick in docs/librarian-ux-roadmap.md when merged

**Goal:** A librarian turns edit mode on once and it follows them from book to book (and across reloads) until they press `[done]`; `?edit=1` deep links still turn it on; readers never see any of it.

**Architecture:** A new persisted Zustand store, `store/librarian.js` (`persist` key `margin-librarian`, `{ editMode, setEditMode }`), replaces the `?edit=1` query parameter as the source of truth. The series page reads `editing = user.is_librarian && editMode`; a `?edit=1` in the URL, for a librarian only, sets the store and is then stripped from the address. `[edit]`/`[done]` becomes a toggle button, the status bar names the `EDIT` mode, and the navbar carries `[done editing]` so a librarian can leave edit mode from any page. Signing out leaves edit mode. Frontend only; no API change.

**Tech Stack:** React 18, React Router 6.30, Zustand 4.5 (`persist`), Tailwind tokens, Vitest 1.6 + React Testing Library + user-event 14, Playwright.

**Spec:** docs/librarian-ux-roadmap.md §01 · Sticky edit mode (and its "Shared names" → Frontend). v1 behavior it changes: docs/superpowers/specs/2026-09-28-librarian-tools-design.md §6 ("state in the URL (`?edit=1`)").

**Base:** `main` with `fix/librarian-minors` merged — the `Series.jsx` / `LibrarianPanel.jsx` code quoted below (the `ResultLine` `role="group"`, `result.pages`) is from that branch. If `git log origin/main --oneline | grep -i "librarian review fixes"` prints nothing, merge that branch first.

## Global Constraints

- Store: `frontend/src/store/librarian.js`, Zustand store, `persist` key `margin-librarian`, state `{ editMode: boolean, setEditMode(v) }`. Later items may add fields; never rename these. (roadmap, Shared names)
- `?edit=1` still turns edit mode on (deep links keep working). Leaving edit mode is `[done]` anywhere. Readers never see it. Frontend only. (roadmap §01)
- Every surface gates on `user.is_librarian` as well as `editMode`; a stored `editMode: true` alone must never show a librarian control.
- Design tokens only; no raw colors; no new radii, shadows, font sizes or durations (`duration-fast` only); serif only for book titles and series names; every glyph `aria-hidden`; nothing means anything by color alone; §36 test.
- Tests: Vitest + RTL next to the component; one Playwright scenario for the changed flow; network always mocked in unit tests.
- Branch `feat/librarian-lx01-sticky-edit-mode` from `main`; one commit per task; PR to `main`.

## Review Focus

1. **A shared computer**: a librarian leaves `editMode: true` in localStorage, a reader signs in on the same browser. The reader must see no `[edit]`, `[done]`, `[done editing]` or row action — Task 2 `never shows edit mode to a reader, even with it stored`, Task 3 `never shows [done editing] to a reader`.
2. **A reader follows a `?edit=1` link** (someone pasted a librarian URL). Nothing changes for them and nothing is stored — Task 2 `a reader's ?edit=1 does not turn it on`.
3. **`?edit=1` next to other parameters** (`?book=b2&edit=1`, the fix-log and queue links). Only `edit` is stripped; `book` and its highlight survive — Task 2 `?edit=1 turns it on and leaves the rest of the address alone`.
4. **The "go to its page" link after a fix** carries the correction in `location.state` *and* `?edit=1`. Stripping the parameter must not drop that state, or the result line and its undo vanish on arrival — Task 2 `keeps a fix report carried in by a ?edit=1 link`.
5. **Signing out** in edit mode, then a different librarian (or the same one later) signing in: they start out of edit mode — Task 3 `leaves edit mode on sign-out`.

---

## File Structure

**Create**
- `frontend/src/store/librarian.js` — the persisted librarian UI store (`useLibrarianStore`, default export).
- `frontend/src/store/librarian.test.js` — persistence and coercion.

**Modify**
- `frontend/src/pages/Series.jsx` — read edit mode from the store; `?edit=1` deep link; `[edit]`/`[done]` toggle button; status-bar mode `EDIT`.
- `frontend/src/pages/Series.test.jsx` — reset the store per test; `Where` shows `search`; toggle is a button; new sticky-mode tests.
- `frontend/src/components/Navbar.jsx` — `[done editing]` for a librarian in edit mode; sign-out leaves edit mode.
- `frontend/src/components/Navbar.test.jsx` — edit-mode tests.
- `frontend/e2e/librarian.spec.js` — `[edit]` is a button; new sticky-mode scenario.
- Docs: `docs/librarian-ux-roadmap.md` (tracker row), `ROADMAP.md` (librarian row), `CLAUDE.md` (frontend store list).

---

### Task 1: The librarian store

**Files:**
- Create: `frontend/src/store/librarian.js`
- Test: `frontend/src/store/librarian.test.js`
- Modify: `docs/librarian-ux-roadmap.md` (tracker row → in progress)

**Interfaces:**
- Consumes: nothing.
- Produces: `useLibrarianStore` (default export of `store/librarian.js`) — a Zustand hook with state `{ editMode: boolean, setEditMode(v: any): void }`; `setEditMode` coerces with `!!v`. Persisted to localStorage under `margin-librarian` as `{ state: { editMode }, version: 0 }` (only `editMode` is persisted). Tasks 2 and 3, and roadmap items 05, 08–12, read `editMode` through this hook.

- [ ] **Step 1: Branch and mark the item in progress**

```bash
git fetch origin
git switch -c feat/librarian-lx01-sticky-edit-mode origin/main
```

In `docs/librarian-ux-roadmap.md`, change the tracker row

```
| 01 | Sticky edit mode | [plan](superpowers/plans/2026-09-29-lx01-sticky-edit-mode.md) | — | ⬜ | | | |
```

to

```
| 01 | Sticky edit mode | [plan](superpowers/plans/2026-09-29-lx01-sticky-edit-mode.md) | — | 🟡 | feat/librarian-lx01-sticky-edit-mode | | |
```

- [ ] **Step 2: Write the failing test**

`frontend/src/store/librarian.test.js`:

```js
import { describe, it, expect, beforeEach } from 'vitest'
import useLibrarianStore from './librarian'

beforeEach(() => {
  localStorage.clear()
  useLibrarianStore.setState({ editMode: false })
})

describe('librarian store', () => {
  it('starts out of edit mode', () => {
    expect(useLibrarianStore.getState().editMode).toBe(false)
  })

  it('persists edit mode under margin-librarian', () => {
    useLibrarianStore.getState().setEditMode(true)
    const persisted = JSON.parse(localStorage.getItem('margin-librarian'))
    expect(persisted.state).toEqual({ editMode: true })
  })

  it('stores a boolean whatever it is given', () => {
    useLibrarianStore.getState().setEditMode('1')
    expect(useLibrarianStore.getState().editMode).toBe(true)
    useLibrarianStore.getState().setEditMode(undefined)
    expect(useLibrarianStore.getState().editMode).toBe(false)
  })

  it('comes back after a reload', async () => {
    localStorage.setItem('margin-librarian', JSON.stringify({ state: { editMode: true }, version: 0 }))
    await useLibrarianStore.persist.rehydrate()
    expect(useLibrarianStore.getState().editMode).toBe(true)
  })
})
```

- [ ] **Step 3: Run it to verify it fails**

Run: `cd frontend && npx vitest run src/store/librarian.test.js`
Expected: FAIL — `Failed to resolve import "./librarian" from "src/store/librarian.test.js"`.

- [ ] **Step 4: Implement the store**

`frontend/src/store/librarian.js`:

```js
import { create } from 'zustand'
import { persist } from 'zustand/middleware'

/**
 * Librarian UI state that outlives a page. Edit mode is sticky: a librarian
 * turns it on once and it follows them from book to book, and across reloads,
 * until they press `[done]`.
 *
 * Nothing here grants anything. Every surface also checks `user.is_librarian`
 * (a reader on a shared browser may inherit `editMode: true`), and the API
 * checks again.
 */
const useLibrarianStore = create(
  persist(
    (set) => ({
      editMode: false,
      setEditMode: (value) => set({ editMode: !!value }),
    }),
    {
      name: 'margin-librarian',
      partialize: (state) => ({ editMode: state.editMode }),
    },
  ),
)

export default useLibrarianStore
```

- [ ] **Step 5: Run it to verify it passes**

Run: `cd frontend && npx vitest run src/store/librarian.test.js`
Expected: PASS — `Test Files  1 passed (1)`, `Tests  4 passed (4)`.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/store/librarian.js frontend/src/store/librarian.test.js docs/librarian-ux-roadmap.md
git commit -m "feat(web): persisted librarian store for sticky edit mode"
```

---

### Task 2: The series page reads edit mode from the store

**Files:**
- Modify: `frontend/src/pages/Series.jsx`
- Test: `frontend/src/pages/Series.test.jsx`

**Interfaces:**
- Consumes: `useLibrarianStore` → `{ editMode, setEditMode }` (Task 1); `useAuthStore` `user.is_librarian` (existing); `useStatusStore` (existing, `store/status.js`).
- Produces:
  - `editing = !!user?.is_librarian && editMode` inside `Series` (items 03, 08, 09, 10 extend what renders under it).
  - The header toggle is now `<button type="button">` named `[edit]` / `[done]` (was a `<Link>`). Item 10 adds `aria-keyshortcuts="e"` to it.
  - A librarian landing on any `/series/:slug?…edit=1…` gets `editMode = true` and the `edit` parameter removed with `replace`, keeping every other parameter and `location.state`.
  - Status bar `mode` is `'EDIT'` while editing, `'SERIES'` otherwise.

- [ ] **Step 1: Update the test harness and existing assertions**

In `frontend/src/pages/Series.test.jsx`:

1. Add imports under `import useAuthStore from '../store/auth'`:

```jsx
import useLibrarianStore from '../store/librarian'
import useStatusStore from '../store/status'
```

2. Replace the `Where` component so tests can see the query string too:

```jsx
function Where() {
  const loc = useLocation()
  const navigate = useNavigate()
  return (
    <>
      <p data-testid="where">{loc.pathname}</p>
      <p data-testid="search">{loc.search}</p>
      <button type="button" onClick={() => navigate('/series/elsewhere')}>go elsewhere</button>
    </>
  )
}
```

3. Replace the `beforeEach` so edit mode never leaks between tests:

```jsx
beforeEach(() => {
  vi.clearAllMocks()
  localStorage.clear()
  useLibrarianStore.setState({ editMode: false })
  // Signed in, so ShelfButton renders its status rather than a login link.
  useAuthStore.setState({ token: 't', user: { id: 'u1', username: 'reader' } })
})
```

4. The toggle is now a button. In `it('offers edit mode only to librarians', …)` replace

```jsx
    expect(screen.queryByRole('link', { name: '[edit]' })).toBeNull()
```

with

```jsx
    expect(screen.queryByRole('button', { name: '[edit]' })).toBeNull()
```

and in `it('shows row and header actions in edit mode, and marks librarian-placed books', …)` replace

```jsx
    expect(screen.getByRole('link', { name: '[done]' })).toBeInTheDocument()
```

with

```jsx
    expect(screen.getByRole('button', { name: '[done]' })).toBeInTheDocument()
```

- [ ] **Step 2: Write the failing tests**

Append at the end of `frontend/src/pages/Series.test.jsx` (after the closing `})` of `describe('Series page', …)`):

```jsx
describe('Sticky edit mode', () => {
  const LIBRARIAN = { id: 'u1', username: 'lib', is_librarian: true }
  const READER = { id: 'u2', username: 'reader' }

  it('stays in edit mode on the next book', async () => {
    useAuthStore.setState({ token: 't', user: LIBRARIAN })
    useLibrarianStore.setState({ editMode: true })
    mockApi({ ...SAGA, id: 's1' })
    renderPage('/series/red-rising')
    expect(await screen.findByRole('button', { name: 'move Red Rising' })).toBeInTheDocument()

    mockApi({ ...SAGA, id: 's2', slug: 'elsewhere', name: 'Elsewhere' })
    await userEvent.click(screen.getByRole('button', { name: 'go elsewhere' }))
    await screen.findByRole('heading', { level: 1, name: 'Elsewhere' })
    expect(screen.getByRole('button', { name: 'move Red Rising' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '[done]' })).toBeInTheDocument()
  })

  it('[edit] turns it on and [done] turns it off, without touching the address', async () => {
    useAuthStore.setState({ token: 't', user: LIBRARIAN })
    mockApi({ ...SAGA, id: 's1' })
    renderPage('/series/red-rising')
    await userEvent.click(await screen.findByRole('button', { name: '[edit]' }))
    expect(useLibrarianStore.getState().editMode).toBe(true)
    expect(screen.getByRole('button', { name: 'move Red Rising' })).toBeInTheDocument()
    expect(screen.getByTestId('search')).toHaveTextContent(/^$/)

    await userEvent.click(screen.getByRole('button', { name: '[done]' }))
    expect(useLibrarianStore.getState().editMode).toBe(false)
    expect(screen.queryByRole('button', { name: 'move Red Rising' })).toBeNull()
    expect(screen.getByRole('button', { name: '[edit]' })).toBeInTheDocument()
  })

  it('?edit=1 turns it on and leaves the rest of the address alone', async () => {
    useAuthStore.setState({ token: 't', user: LIBRARIAN })
    mockApi({ ...SAGA, id: 's1' })
    renderPage('/series/red-rising?book=b2&edit=1')
    expect(await screen.findByRole('button', { name: 'move Golden Son' })).toBeInTheDocument()
    expect(useLibrarianStore.getState().editMode).toBe(true)
    await waitFor(() => expect(screen.getByTestId('search')).toHaveTextContent('?book=b2'))
    const list = screen.getByRole('list', { name: 'Books in this series' })
    expect(within(list).getAllByRole('listitem')[1]).toHaveAttribute('aria-current', 'true')
  })

  it('keeps a fix report carried in by a ?edit=1 link', async () => {
    useAuthStore.setState({ token: 't', user: LIBRARIAN })
    mockApi({ ...SAGA, id: 's1' })
    const correction = { id: 'c9', op: 'set_series', exportable: true, undoable: true, room_slug: 'red-rising' }
    renderPage({ pathname: '/series/red-rising', search: '?edit=1', state: { correction } })
    await waitFor(() => expect(screen.getByTestId('search')).toHaveTextContent(/^$/))
    const line = await screen.findByRole('group', { name: 'Librarian fix result' })
    expect(within(line).getByRole('button', { name: 'undo' })).toBeInTheDocument()
  })

  it('never shows edit mode to a reader, even with it stored', async () => {
    useAuthStore.setState({ token: 't', user: READER })
    useLibrarianStore.setState({ editMode: true })
    mockApi({ ...SAGA, id: 's1' })
    renderPage('/series/red-rising')
    await screen.findByRole('list', { name: 'Books in this series' })
    expect(screen.queryByRole('button', { name: /^move/ })).toBeNull()
    expect(screen.queryByRole('button', { name: '[edit]' })).toBeNull()
    expect(screen.queryByRole('button', { name: '[done]' })).toBeNull()
    expect(screen.queryByRole('button', { name: 'rename series' })).toBeNull()
  })

  it("a reader's ?edit=1 does not turn it on", async () => {
    useAuthStore.setState({ token: 't', user: READER })
    mockApi({ ...SAGA, id: 's1' })
    renderPage('/series/red-rising?edit=1')
    await screen.findByRole('list', { name: 'Books in this series' })
    expect(useLibrarianStore.getState().editMode).toBe(false)
    expect(screen.queryByRole('button', { name: /^move/ })).toBeNull()
  })

  it('names the mode in the status bar', async () => {
    useAuthStore.setState({ token: 't', user: LIBRARIAN })
    useLibrarianStore.setState({ editMode: true })
    mockApi({ ...SAGA, id: 's1' })
    renderPage('/series/red-rising')
    await screen.findByRole('list', { name: 'Books in this series' })
    await waitFor(() => expect(useStatusStore.getState().mode).toBe('EDIT'))
    await userEvent.click(screen.getByRole('button', { name: '[done]' }))
    await waitFor(() => expect(useStatusStore.getState().mode).toBe('SERIES'))
  })
})
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `cd frontend && npx vitest run src/pages/Series.test.jsx`
Expected: FAIL — the two edited assertions (`button` `[edit]`/`[done]` not found, the toggle is still a link) and the new `Sticky edit mode` tests fail (`Unable to find role="button" and name "move Red Rising"`, `[edit]` link not a button, status mode `SERIES`). The remaining `Series page` tests pass.

- [ ] **Step 4: Implement**

In `frontend/src/pages/Series.jsx`:

1. Add the store import below `import useAuthStore from '../store/auth'`:

```jsx
import useLibrarianStore from '../store/librarian'
```

2. Replace

```jsx
  const [searchParams] = useSearchParams()
```

with

```jsx
  const [searchParams, setSearchParams] = useSearchParams()
```

3. Replace

```jsx
  const editing = !!user?.is_librarian && searchParams.get('edit') === '1'
```

with

```jsx
  // Edit mode is sticky (store/librarian.js) and only ever a librarian's: a
  // reader who inherits `editMode: true` on a shared browser sees nothing.
  const isLibrarian = !!user?.is_librarian
  const editMode = useLibrarianStore((s) => s.editMode)
  const setEditMode = useLibrarianStore((s) => s.setEditMode)
  const editing = isLibrarian && editMode
```

4. Delete the whole `editHref` block:

```jsx
  const editHref = (() => {
    const next = new URLSearchParams(searchParams)
    if (editing) next.delete('edit')
    else next.set('edit', '1')
    const qs = next.toString()
    return `/series/${slug}${qs ? `?${qs}` : ''}`
  })()
```

5. Directly after the "A promoted singleton's old slug answers with its survivor." `useEffect`, add:

```jsx
  // ?edit=1 is a deep link into edit mode (fix-log and "go to its page" links).
  // The store carries it from here, so the address drops it; otherwise a reload
  // after [done] would turn edit mode back on. The state rides along: the
  // "go to its page" link carries the fix report in it.
  useEffect(() => {
    if (!isLibrarian || searchParams.get('edit') !== '1') return
    setEditMode(true)
    const next = new URLSearchParams(searchParams)
    next.delete('edit')
    setSearchParams(next, { replace: true, state: location.state })
  }, [isLibrarian, searchParams, setSearchParams, setEditMode, location.state])
```

6. In the `useStatusBar({ … })` call, replace

```jsx
    mode: 'SERIES',
```

with

```jsx
    mode: editing ? 'EDIT' : 'SERIES',
```

7. Replace the header toggle

```jsx
        {user?.is_librarian && (
          <Link to={editHref} className="text-xs text-accent hover:text-accent-hover">{editing ? '[done]' : '[edit]'}</Link>
        )}
```

with

```jsx
        {isLibrarian && (
          <button type="button" onClick={() => setEditMode(!editing)}
                  className="text-xs text-accent hover:text-accent-hover transition-colors duration-fast">
            {editing ? '[done]' : '[edit]'}
          </button>
        )}
```

`Link` is still used by `ResultLine` and the thread table; keep its import. The `ResultLine` "go to its page" link keeps its `?edit=1`: that is exactly the deep link step 5 handles.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd frontend && npx vitest run src/pages/Series.test.jsx`
Expected: PASS — every test in `Series page` and `Sticky edit mode`.

- [ ] **Step 6: Run the whole frontend suite**

Run: `cd frontend && npm test`
Expected: PASS — all test files; no test elsewhere relied on the `[edit]` link.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/pages/Series.jsx frontend/src/pages/Series.test.jsx
git commit -m "feat(web): edit mode survives navigation; ?edit=1 deep-links into it"
```

---

### Task 3: `[done editing]` anywhere, and sign-out leaves edit mode

**Files:**
- Modify: `frontend/src/components/Navbar.jsx`
- Test: `frontend/src/components/Navbar.test.jsx`

**Interfaces:**
- Consumes: `useLibrarianStore` `{ editMode, setEditMode }` (Task 1); `useAuthStore` `user.is_librarian`, `logout` (existing).
- Produces: a navbar `<button type="button">` named `[done editing]`, rendered only when `user.is_librarian && editMode`; clicking it calls `setEditMode(false)`. The `Out` button calls `setEditMode(false)` before `logout()`. The name differs from the series header's `[done]` on purpose, so the two never collide in `getByRole` (e2e renders both).

- [ ] **Step 1: Write the failing tests**

In `frontend/src/components/Navbar.test.jsx`, add under `import useAuthStore from '../store/auth'`:

```jsx
import useLibrarianStore from '../store/librarian'
```

and append at the end of the file:

```jsx
describe('Navbar edit mode', () => {
  const librarian = () => useAuthStore.setState({ user: { username: 'ada', id: '1', is_librarian: true }, token: 'tok' })

  beforeEach(() => {
    localStorage.clear()
    useLibrarianStore.setState({ editMode: false })
  })

  it('offers [done editing] to a librarian in edit mode, on any page', async () => {
    librarian()
    useLibrarianStore.setState({ editMode: true })
    renderNavbar()
    await userEvent.click(screen.getByRole('button', { name: '[done editing]' }))
    expect(useLibrarianStore.getState().editMode).toBe(false)
    expect(screen.queryByRole('button', { name: '[done editing]' })).toBeNull()
  })

  it('shows nothing while a librarian is not editing', () => {
    librarian()
    renderNavbar()
    expect(screen.queryByRole('button', { name: '[done editing]' })).toBeNull()
  })

  it('never shows [done editing] to a reader', () => {
    useLibrarianStore.setState({ editMode: true })
    renderNavbar() // the outer beforeEach signs in "ada", a reader
    expect(screen.queryByRole('button', { name: '[done editing]' })).toBeNull()
  })

  it('leaves edit mode on sign-out', async () => {
    librarian()
    useLibrarianStore.setState({ editMode: true })
    renderNavbar()
    await userEvent.click(screen.getByRole('button', { name: /out/i }))
    await waitFor(() => expect(useLibrarianStore.getState().editMode).toBe(false))
    expect(useAuthStore.getState().user).toBeNull()
  })
})
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd frontend && npx vitest run src/components/Navbar.test.jsx`
Expected: FAIL — `offers [done editing]…` (`Unable to find role="button" and name "[done editing]"`) and `leaves edit mode on sign-out` (editMode stays `true`). The other two pass already.

- [ ] **Step 3: Implement**

In `frontend/src/components/Navbar.jsx`:

1. Add under `import useAuthStore from '../store/auth'`:

```jsx
import useLibrarianStore from '../store/librarian'
```

2. After `const logout = useAuthStore((s) => s.logout)` add:

```jsx
  const editMode = useLibrarianStore((s) => s.editMode)
  const setEditMode = useLibrarianStore((s) => s.setEditMode)
```

3. Replace

```jsx
              {user.is_librarian && (
                <Link to="/librarian" className="text-sm text-ink-dim hover:text-ink transition-colors duration-fast">
                  librarian
                </Link>
              )}
```

with

```jsx
              {user.is_librarian && editMode && (
                // Edit mode is sticky, so it can be left from any page, not only a series.
                <button type="button" onClick={() => setEditMode(false)}
                        className="text-xs text-accent hover:text-accent-hover transition-colors duration-fast">
                  [done editing]
                </button>
              )}
              {user.is_librarian && (
                <Link to="/librarian" className="text-sm text-ink-dim hover:text-ink transition-colors duration-fast">
                  librarian
                </Link>
              )}
```

4. In the `Out` button's `onClick`, replace

```jsx
                  logout()
```

with

```jsx
                  setEditMode(false) // the next person on this browser starts out of edit mode
                  logout()
```

- [ ] **Step 4: Run to verify they pass**

Run: `cd frontend && npx vitest run src/components/Navbar.test.jsx`
Expected: PASS — `Navbar logout` (2) and `Navbar edit mode` (4).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/Navbar.jsx frontend/src/components/Navbar.test.jsx
git commit -m "feat(web): leave edit mode from any page; sign-out leaves it"
```

---

### Task 4: End-to-end — edit mode follows the librarian

**Files:**
- Modify: `frontend/e2e/librarian.spec.js`

**Interfaces:**
- Consumes: the `[edit]` / `[done]` button (Task 2), `[done editing]` (Task 3); `registerViaUi`, `grantLibrarian`, `openFirstSearchResult` from `e2e/helpers.js`.
- Produces: nothing for later tasks.

- [ ] **Step 1: The existing scenario clicks a button now**

In `frontend/e2e/librarian.spec.js` replace

```js
  await page.getByRole('link', { name: '[edit]' }).click()
```

with

```js
  await page.getByRole('button', { name: '[edit]' }).click()
```

- [ ] **Step 2: Add the scenario**

Append to `frontend/e2e/librarian.spec.js`:

```js
// Edit mode is sticky: on for the next book, still on after a reload, and
// left from the navbar. Needs the full stack and live Open Library.
test("a librarian's edit mode follows them to the next book", async ({ page }) => {
  const user = await registerViaUi(page)
  grantLibrarian(user)
  await page.reload() // useMe refreshes the stored user, now a librarian

  const books = page.getByRole('list', { name: 'Books in this series' })
  const rowMove = books.getByRole('button', { name: /^move / }).first()

  await openFirstSearchResult(page, 'the dispossessed')
  await page.getByRole('button', { name: '[edit]' }).click()
  await expect(rowMove).toBeVisible()
  await expect(page.getByRole('status').filter({ hasText: 'EDIT' })).toBeVisible()

  await openFirstSearchResult(page, 'a wizard of earthsea') // a full navigation
  await expect(rowMove).toBeVisible()
  await page.reload()
  await expect(rowMove).toBeVisible()

  await page.getByRole('button', { name: '[done editing]' }).click()
  await expect(books.getByRole('button', { name: /^move / })).toHaveCount(0)
  await expect(page.getByRole('button', { name: '[edit]' })).toBeVisible()
})
```

- [ ] **Step 3: Run it**

Bring the stack up in another terminal (`docker compose up --build`), then:

Run: `cd frontend && npx playwright test e2e/librarian.spec.js`
Expected: `2 passed`.

- [ ] **Step 4: Commit**

```bash
git add frontend/e2e/librarian.spec.js
git commit -m "test(e2e): edit mode follows a librarian across books and reloads"
```

---

### Task 5: Docs and tracker

**Files:**
- Modify: `docs/librarian-ux-roadmap.md`, `ROADMAP.md`, `CLAUDE.md`

**Interfaces:**
- Consumes: everything above.
- Produces: nothing.

- [ ] **Step 1: `CLAUDE.md`**

In the Frontend section, after the bullet that starts ``- **`store/auth.js`** — Zustand client-state store``, add:

```markdown
- **`store/librarian.js`** — persisted (`margin-librarian`) librarian UI state: `editMode` / `setEditMode`. Edit mode is sticky across pages and reloads; `?edit=1` on a series URL turns it on and is stripped from the address; `[done]` (series header) or `[done editing]` (navbar) leaves it, and so does signing out. Every surface still gates on `user.is_librarian` as well.
```

- [ ] **Step 2: `ROADMAP.md`**

In the Phase 5 **Librarian tools** row, replace

```
from the series page (`?edit=1`)
```

with

```
from the series page in edit mode (sticky across pages; `?edit=1` deep-links into it)
```

(If an earlier roadmap item already rewrote that cell, make the same change to the cell as it stands.)

- [ ] **Step 3: Run the full frontend suite once more**

Run: `cd frontend && npm test`
Expected: PASS — all test files.

- [ ] **Step 4: Commit and open the PR**

```bash
git add CLAUDE.md ROADMAP.md
git commit -m "docs: sticky librarian edit mode"
git push -u origin feat/librarian-lx01-sticky-edit-mode
gh pr create --base main --title "feat(web): sticky librarian edit mode (LX01)" \
  --body "Roadmap item 01 (docs/librarian-ux-roadmap.md). Edit mode lives in store/librarian.js and survives navigation and reloads; ?edit=1 still deep-links into it; [done] / [done editing] leave it; readers never see it."
```

- [ ] **Step 5: Tick the tracker when it merges**

After the PR merges, on `main` (or as the last commit on the branch, once the PR number is known), change the tracker row in `docs/librarian-ux-roadmap.md` to

```
| 01 | Sticky edit mode | [plan](superpowers/plans/2026-09-29-lx01-sticky-edit-mode.md) | — | ✅ | feat/librarian-lx01-sticky-edit-mode | <merge date, YYYY-MM-DD> | #<PR number from `gh pr view --json number -q .number`> |
```

tick the `Roadmap item` checkbox at the top of this plan, and add a dated line under **Notes** if anything differed from this plan (for example: "01: the `[edit]` toggle is a button now; e2e and later plans must use `getByRole('button', { name: '[edit]' })`").

```bash
git add docs/librarian-ux-roadmap.md docs/superpowers/plans/2026-09-29-lx01-sticky-edit-mode.md
git commit -m "docs: LX01 done"
```
