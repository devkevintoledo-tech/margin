# Merge From Search Results Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Duplicates are found in search, so let a librarian merge them there. A librarian-only `select` toggle turns search results into checkable cards. Exactly two checked enables `merge…`, which opens the merge panel with both books preset and the side-by-side preview showing.

**Architecture:** Frontend only; it uses item 04's `GET /api/librarian/works/{id}/merge-preview` and `MergePreview`. `WorkCard` gains an optional selectable mode. With `onSelect` it renders a `<label>` wrapping a checkbox instead of a `<Link>`, so a click anywhere toggles and nothing navigates. `pages/Search.jsx` owns the selection, which is kept across new searches because the two halves of a duplicate often turn up under different queries. A new `components/librarian/SelectionBar.jsx` shows the count, the picked titles, `merge…` and `clear`. `LibrarianPanel` accepts `action.into` to preset the book to keep, and hides the picker when it is given. After a merge the page navigates to the survivor's series page with the correction in `location.state`, where the existing result line (with its undo rules) picks it up.

**Tech Stack:** React 18 + React Router + React Query + Zustand + Tailwind tokens, Vitest + RTL, Playwright.

**Spec:** docs/librarian-ux-roadmap.md §05 (and Shared names → Frontend `MergePreview`, from §04)

**Roadmap item:** 05 — tick in docs/librarian-ux-roadmap.md when merged

- [ ] **Merged** (PR: ____, date: ____)

**Depends on:** item 04 merged into `main` first (`useMergePreview`, `components/librarian/MergePreview.jsx`, the panel's `swapped` field and its `Merge preview` group).

## Global Constraints

- Frontend only. No backend change and no new route.
- Readers and anonymous visitors see today's search page exactly: no toggle, no checkboxes, and every card a link to `seriesHref(work)`.
- The toggle is a `<button aria-pressed>` labelled `select`. The merge button is labelled `merge…`, with the `…` character as in v1's `merge into…`.
- `merge…` is enabled only when exactly two books are selected. Any other count shows why (`select exactly two books to merge`), tied to the button with `aria-describedby`.
- Selecting never navigates. In select mode a card contains no link.
- Keyboard: every card in select mode is a focusable native checkbox (Tab reaches it, Space toggles it) with the accessible name `select <title> by <author>`. The selection count is a `role="status"` live region.
- The merge panel opened from search is the same `LibrarianPanel` as the series page: same reason field, same 422 → `confirm: true` flow, same preview and swap (item 04). The first book selected merges into the second by default, and `swap` flips them.
- Names used from item 04, verbatim: `MergePreview`, group `Merge preview`, regions `merges away: <title>` / `survives: <title>`, button `swap which book survives`, `useMergePreview(sourceId, intoId)`, fields `into`/`swapped`.
- Tokens only. No new radii, shadows, font sizes or durations. Serif only for book titles. No new glyphs. A selected card is shown by its checked box, the word `selected` and an `accent` frame, never by colour alone.
- Branch `feat/librarian-lx05-merge-from-search` from `main`, one commit per task, PR to `main`.

## Review Focus

1. **Clicking a card's cover or title in select mode.** This is where readers click to open a book. It must toggle the checkbox and stay on `/search`, never follow a link. Test: Task 1 `in select mode a click on the cover selects and does not navigate` (card) and Task 3 `selecting never navigates` (page).
2. **The two duplicates only appear under different queries** ("dune" vs "dune frank herbert"). The selection must survive a new search, and the bar must list off-screen picks by title, so the librarian knows what `merge…` will act on. Test: Task 3 `keeps the selection across a new search`.
3. **Three books selected, or one.** `merge…` stays disabled and says why. It never guesses which two. Test: Task 2 `enables merge only for exactly two, and says why otherwise`.
4. **A reader, or a librarian whose flag was revoked** (the auth store refreshes via `useMe`). No toggle renders. If select mode was on, the cards go back to links. Test: Task 3 `readers and visitors get plain links and no toggle` and `a revoked librarian loses select mode`.
5. **Closing the panel without merging** (Escape or ✕). The selection stays, so the librarian can swap in a different book. After a successful merge the selection clears and the page lands on the survivor's page with the result line. Test: Task 3 `closing the panel keeps the selection` and `merge… opens the panel preset with the preview, and a merge lands on the survivor's page`.

---

## File Structure

**Frontend — create**
- `frontend/src/components/librarian/SelectionBar.jsx` — count, picked titles, `merge…`, `clear`.
- `frontend/src/components/librarian/SelectionBar.test.jsx`.
- `frontend/src/pages/Search.test.jsx` — the page had no tests.

**Frontend — modify**
- `frontend/src/components/WorkCard.jsx` — optional `selected` / `onSelect` props.
- `frontend/src/components/WorkCard.test.jsx` — selectable-mode tests.
- `frontend/src/components/LibrarianPanel.jsx` — `action.into` presets the book to keep and hides the picker.
- `frontend/src/components/LibrarianPanel.test.jsx` — preset test.
- `frontend/src/pages/Search.jsx` — toggle, selection state, bar, panel, post-merge navigation.
- `frontend/e2e/librarian.spec.js` — one scenario.

**Docs — modify:** `docs/librarian-ux-roadmap.md`, `ROADMAP.md`, `CLAUDE.md`.

---

### Task 1: `WorkCard` selectable mode

**Files:**
- Modify: `frontend/src/components/WorkCard.jsx` (whole file)
- Test: `frontend/src/components/WorkCard.test.jsx`

**Interfaces:**
- Consumes: `seriesHref(work)` from `api/series.js` (unchanged).
- Produces: `WorkCard({ work, selected?: boolean, onSelect?: (work) => void })`. Without `onSelect` the card is exactly today's link. With it the root is a `<label>` wrapping a checkbox (`aria-label="select <title> by <author>"`, `checked={!!selected}`, `onChange={() => onSelect(work)}`) and the card has no link.

- [ ] **Step 1: Start the item**

```bash
git checkout main && git pull
git checkout -b feat/librarian-lx05-merge-from-search
```

In `docs/librarian-ux-roadmap.md`, change row 05 of the Tracker to status `🟡` and set Branch to `feat/librarian-lx05-merge-from-search`. It is committed with this task.

- [ ] **Step 2: Write the failing card tests**

In `frontend/src/components/WorkCard.test.jsx`, change the imports and `renderCard` to:

```jsx
import { fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import WorkCard from './WorkCard'

function Where() {
  return <p data-testid="where">{useLocation().pathname}</p>
}

function renderCard(work, props = {}) {
  return render(
    <MemoryRouter initialEntries={['/search']}>
      <Where />
      <Routes>
        <Route path="/search" element={<WorkCard work={work} {...props} />} />
        <Route path="*" element={<p>elsewhere</p>} />
      </Routes>
    </MemoryRouter>,
  )
}
```

Append inside `describe('WorkCard', …)`:

```jsx
  it('in select mode it is a checkbox named by title and author, not a link', () => {
    renderCard(inSeries, { selected: false, onSelect: vi.fn() })
    expect(screen.queryByRole('link')).toBeNull()
    expect(screen.getByRole('checkbox', { name: 'select Red Rising by Pierce Brown' })).not.toBeChecked()
  })

  it('in select mode a click on the cover selects and does not navigate', async () => {
    const onSelect = vi.fn()
    renderCard(inSeries, { selected: false, onSelect })
    await userEvent.click(screen.getByRole('img', { name: 'Red Rising' }))
    expect(onSelect).toHaveBeenCalledWith(inSeries)
    expect(screen.getByTestId('where')).toHaveTextContent('/search')
  })

  it('toggles from the keyboard with Space', async () => {
    const onSelect = vi.fn()
    renderCard(inSeries, { selected: false, onSelect })
    await userEvent.tab()
    expect(screen.getByRole('checkbox')).toHaveFocus()
    await userEvent.keyboard(' ')
    expect(onSelect).toHaveBeenCalledTimes(1)
  })

  it('says a selected card is selected, in words as well as the frame', () => {
    renderCard(inSeries, { selected: true, onSelect: vi.fn() })
    expect(screen.getByRole('checkbox')).toBeChecked()
    expect(screen.getByText('selected')).toBeInTheDocument()
    expect(screen.getByRole('img', { name: 'Red Rising' }).parentElement).toHaveClass('border-accent')
  })
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `cd frontend && npx vitest run src/components/WorkCard.test.jsx`
Expected: the four new tests FAIL (no checkbox role; the card is still a link). The ten existing tests PASS under the new router wrapper.

- [ ] **Step 4: Implement selectable mode**

Replace `frontend/src/components/WorkCard.jsx` with:

```jsx
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { seriesHref } from '../api/series'

/**
 * A search result. A link to the book's page, or, when ``onSelect`` is given
 * (librarian select mode), a checkable card: a label around a checkbox, so a
 * click anywhere toggles it and nothing navigates.
 */
function WorkCard({ work, selected = false, onSelect }) {
  const { title, author, cover_url, edition_count, series } = work
  // A cover URL can 404 or be pulled upstream. Falling back to the same
  // placeholder the no-cover case uses keeps one visual answer for "no art"
  // rather than a broken-image glyph.
  const [coverFailed, setCoverFailed] = useState(false)
  const showCover = cover_url && !coverFailed
  const frame = selected ? 'border-accent' : 'border-line group-hover:border-accent'

  const body = (
    <>
      {/* Covers carry most of the color in the UI (§13), so they stay large and
          unobstructed — the frame reacts on hover, the art never dims. */}
      <div className={`aspect-[2/3] bg-panel border ${frame} transition-colors duration-base overflow-hidden`}>
        {showCover ? (
          <img
            src={cover_url}
            alt={title}
            loading="lazy"
            onError={() => setCoverFailed(true)}
            className="w-full h-full object-cover group-hover:scale-[1.03] transition-transform duration-base"
          />
        ) : (
          <div className="w-full h-full flex items-center justify-center p-4">
            <span className="font-serif italic text-ink-dim text-xs text-center">{title}</span>
          </div>
        )}
      </div>
      <div className="pt-3 flex flex-col gap-1">
        <p className="font-serif text-ink text-sm leading-snug line-clamp-2 group-hover:text-accent transition-colors duration-fast">
          {title}
        </p>
        <p className="text-ink-dim text-xs lowercase tracking-eyebrow line-clamp-1">{author}</p>
        {/* A reference to the book's room, so it takes the path colour. Text,
            not a glyph: the literal-glyph set is closed. */}
        {series?.kind === 'series' && (
          <p className="text-xs lowercase line-clamp-1">
            <span className="text-ink-dim">series </span>
            <span className="text-path">{series.name}</span>
          </p>
        )}
        {/* Search collapses many editions into one card; saying so keeps the
            smaller result count legible rather than mysterious. */}
        {edition_count > 1 && (
          <p className="text-ink-dim text-xs tabular-nums">{edition_count} editions</p>
        )}
      </div>
    </>
  )

  if (!onSelect) {
    return <Link to={seriesHref(work)} className="group flex flex-col">{body}</Link>
  }
  return (
    <label className="group flex flex-col cursor-pointer">
      <span className="flex items-center gap-2 pb-2 text-xs">
        <input type="checkbox" checked={selected} onChange={() => onSelect(work)}
               aria-label={`select ${title} by ${author}`} className="accent-accent" />
        <span className={selected ? 'text-accent' : 'text-ink-dim'}>{selected ? 'selected' : 'select'}</span>
      </span>
      {body}
    </label>
  )
}

export default WorkCard
```

`accent-accent` is Tailwind's `accent-color` utility over the existing `accent` token. It adds no new colour.

- [ ] **Step 5: Run the card and token tests**

Run: `cd frontend && npx vitest run src/components/WorkCard.test.jsx src/design/tokens.test.js`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/WorkCard.jsx frontend/src/components/WorkCard.test.jsx docs/librarian-ux-roadmap.md
git commit -m "feat(web): WorkCard has a selectable mode that never navigates"
```

---

### Task 2: `SelectionBar`, and a merge panel that takes both books preset

**Files:**
- Create: `frontend/src/components/librarian/SelectionBar.jsx`
- Test: `frontend/src/components/librarian/SelectionBar.test.jsx`
- Modify: `frontend/src/components/LibrarianPanel.jsx` (initial `fields.into`; the merge picker line)
- Test: `frontend/src/components/LibrarianPanel.test.jsx`

**Interfaces:**
- Consumes: from item 04, `LibrarianPanel`'s `fields.into` / `fields.swapped`, `PreviewSlot`, and the `Merge preview` group.
- Produces:
  - `SelectionBar({ selected: Work[], onMerge: () => void, onClear: () => void })`. It renders `role="group"` named `Selection`, a `role="status"` count `<n> selected`, a list named `Selected books`, a `merge…` button enabled iff `selected.length === 2`, and `clear` when anything is selected.
  - `LibrarianPanel` accepts `action.into` (a work with `id`, `title`, `author`) for `kind: 'merge'`. When given, `fields.into` starts as it and the `WorkPicker` is not rendered. `action.series` may be absent for a merge.

- [ ] **Step 1: Write the failing tests**

Create `frontend/src/components/librarian/SelectionBar.test.jsx`:

```jsx
import { describe, it, expect, vi } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import SelectionBar from './SelectionBar'

const A = { id: 'w1', title: 'Dune', author: 'Brian Herbert' }
const B = { id: 'w2', title: 'Dune', author: 'Frank Herbert' }
const C = { id: 'w3', title: 'Dune Messiah', author: 'Frank Herbert' }

describe('SelectionBar', () => {
  it('enables merge only for exactly two, and says why otherwise', async () => {
    const onMerge = vi.fn()
    const { rerender } = render(<SelectionBar selected={[A]} onMerge={onMerge} onClear={vi.fn()} />)
    const merge = screen.getByRole('button', { name: 'merge…' })
    expect(merge).toBeDisabled()
    expect(merge).toHaveAccessibleDescription('select exactly two books to merge')

    rerender(<SelectionBar selected={[A, B, C]} onMerge={onMerge} onClear={vi.fn()} />)
    expect(screen.getByRole('button', { name: 'merge…' })).toBeDisabled()

    rerender(<SelectionBar selected={[A, B]} onMerge={onMerge} onClear={vi.fn()} />)
    expect(screen.getByRole('button', { name: 'merge…' })).toBeEnabled()
    expect(screen.queryByText('select exactly two books to merge')).toBeNull()
    await userEvent.click(screen.getByRole('button', { name: 'merge…' }))
    expect(onMerge).toHaveBeenCalledTimes(1)
  })

  it('announces the count and lists every pick by title and author', () => {
    render(<SelectionBar selected={[A, C]} onMerge={vi.fn()} onClear={vi.fn()} />)
    expect(screen.getByRole('status')).toHaveTextContent('2 selected')
    const items = within(screen.getByRole('list', { name: 'Selected books' })).getAllByRole('listitem')
    expect(items.map((li) => li.textContent)).toEqual(['Dune Brian Herbert', 'Dune Messiah Frank Herbert'])
  })

  it('clears, and offers nothing to clear when empty', async () => {
    const onClear = vi.fn()
    const { rerender } = render(<SelectionBar selected={[A]} onMerge={vi.fn()} onClear={onClear} />)
    await userEvent.click(screen.getByRole('button', { name: 'clear' }))
    expect(onClear).toHaveBeenCalledTimes(1)
    rerender(<SelectionBar selected={[]} onMerge={vi.fn()} onClear={onClear} />)
    expect(screen.queryByRole('button', { name: 'clear' })).toBeNull()
    expect(screen.getByRole('status')).toHaveTextContent('0 selected')
  })
})
```

In `frontend/src/components/LibrarianPanel.test.jsx`, append inside `describe('LibrarianPanel', …)`. `mockGets`, `OTHER` and `CORRECTION` come from item 04's version of this file:

```jsx
  it('takes both books preset: no picker, preview at once, and the usual confirm', async () => {
    mockGets()
    client.post
      .mockRejectedValueOnce({ response: { status: 422, data: { detail: {
        message: 'm', consequences: { threads: 3, shelves: 0, editions: 1 } } } } })
      .mockResolvedValueOnce({ data: CORRECTION })
    const onDone = vi.fn()
    render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <LibrarianPanel action={{ kind: 'merge', work: BOOK, into: OTHER }} onClose={vi.fn()} onDone={onDone} />
      </QueryClientProvider>,
    )
    expect(screen.queryByLabelText('Find the book to keep')).toBeNull()
    const preview = await screen.findByRole('group', { name: 'Merge preview' })
    expect(within(preview).getByRole('region', { name: /^survives/ })).toHaveTextContent('Frank Herbert')
    expect(client.get).toHaveBeenCalledWith('/librarian/works/w1/merge-preview', { params: { into: 'w2' } })
    expect(client.get).not.toHaveBeenCalledWith('/works/search', expect.anything())

    await userEvent.type(screen.getByLabelText('Reason'), 'duplicate record')
    await userEvent.click(screen.getByRole('button', { name: 'Merge' }))
    await userEvent.click(await screen.findByRole('button', { name: 'Confirm merge' }))
    await waitFor(() => expect(onDone).toHaveBeenCalledWith(CORRECTION))
    expect(client.post).toHaveBeenLastCalledWith('/librarian/works/w1/merge',
      { reason: 'duplicate record', into_work_id: 'w2', confirm: true })
  })
```

This test renders without `series` on purpose, since search has none.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd frontend && npx vitest run src/components/librarian/SelectionBar.test.jsx src/components/LibrarianPanel.test.jsx`
Expected: `SelectionBar.test.jsx` fails to resolve `./SelectionBar`. The new panel test FAILS because `Find the book to keep` is present and no preview is fetched. The existing panel tests PASS.

- [ ] **Step 3: Write `SelectionBar`**

Create `frontend/src/components/librarian/SelectionBar.jsx`:

```jsx
/**
 * What a librarian has picked from search results. Picks can come from
 * earlier searches, so they are listed by name: merge… acts on exactly these.
 */
function SelectionBar({ selected, onMerge, onClear }) {
  const canMerge = selected.length === 2
  return (
    <div role="group" aria-label="Selection" className="flex flex-wrap items-center gap-3 text-xs border-b border-line pb-3">
      <span role="status" className="text-ink-dim tabular-nums">{selected.length} selected</span>
      {selected.length > 0 && (
        <ul aria-label="Selected books" className="flex flex-wrap gap-x-4">
          {selected.map((w) => (
            <li key={w.id}>
              <span className="font-serif text-ink">{w.title}</span> <span className="text-user">{w.author}</span>
            </li>
          ))}
        </ul>
      )}
      <button type="button" className="btn-primary text-xs" disabled={!canMerge} onClick={onMerge}
              aria-describedby={canMerge ? undefined : 'merge-selection-hint'}>
        merge…
      </button>
      {!canMerge && <span id="merge-selection-hint" className="text-ink-dim">select exactly two books to merge</span>}
      {selected.length > 0 && (
        <button type="button" className="btn-ghost text-xs" onClick={onClear}>clear</button>
      )}
    </div>
  )
}

export default SelectionBar
```

- [ ] **Step 4: Let the panel take `action.into`**

In `frontend/src/components/LibrarianPanel.jsx`, in the initial `fields` object, change `into: null` to:

```jsx
    reason: '', name: '', target: null, into: action.into ?? null, editions: [], swapped: false,
```

Replace the merge picker block from item 04:

```jsx
            {kind === 'merge' && (
              <WorkPicker exclude={work.id} value={fields.into} onChange={(w) => patch({ into: w, swapped: false })} />
            )}
```

with:

```jsx
            {/* From search both books arrive preset; only the series page asks for one. */}
            {kind === 'merge' && !action.into && (
              <WorkPicker exclude={work.id} value={fields.into} onChange={(w) => patch({ into: w, swapped: false })} />
            )}
```

- [ ] **Step 5: Run the tests**

Run: `cd frontend && npx vitest run src/components/librarian/SelectionBar.test.jsx src/components/LibrarianPanel.test.jsx src/design/tokens.test.js`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/librarian/SelectionBar.jsx frontend/src/components/librarian/SelectionBar.test.jsx \
        frontend/src/components/LibrarianPanel.jsx frontend/src/components/LibrarianPanel.test.jsx
git commit -m "feat(web): selection bar for search, merge panel accepts both books preset"
```

---

### Task 3: Search page select mode and merge…

**Files:**
- Modify: `frontend/src/pages/Search.jsx` (whole file)
- Create: `frontend/src/pages/Search.test.jsx`

**Interfaces:**
- Consumes: `WorkCard({ work, selected, onSelect })` (Task 1). `SelectionBar({ selected, onMerge, onClear })` and `LibrarianPanel` with `action = { kind: 'merge', work, into }` (Task 2). `useAuthStore` (`user.is_librarian`). The Series page reads `location.state.correction` on mount (v1, `pages/Series.jsx`).
- Produces: the user-visible flow. Nothing later in this plan consumes it except Task 4's e2e.

- [ ] **Step 1: Write the failing page tests**

Create `frontend/src/pages/Search.test.jsx`:

```jsx
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { act, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes, useLocation, useNavigate } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

vi.mock('../api/client', () => ({ default: { get: vi.fn(), post: vi.fn() } }))

import client from '../api/client'
import useAuthStore from '../store/auth'
import Search from './Search'

const BRIAN = { id: 'w1', title: 'Dune', author: 'Brian Herbert', cover_url: null, edition_count: 2,
                series: { slug: 'dune-b1', name: 'Dune', kind: 'singleton' } }
const FRANK = { id: 'w2', title: 'Dune', author: 'Frank Herbert', cover_url: 'https://x/dune.jpg', edition_count: 26,
                series: { slug: 'dune', name: 'Dune Saga', kind: 'series' } }
const MESSIAH = { id: 'w3', title: 'Dune Messiah', author: 'Frank Herbert', cover_url: null, edition_count: 9,
                  series: { slug: 'dune', name: 'Dune Saga', kind: 'series' } }
const RESULTS = { dune: [BRIAN, FRANK, MESSIAH], messiah: [MESSIAH] }
const BY_ID = { w1: BRIAN, w2: FRANK, w3: MESSIAH }
const side = (w) => ({ id: w.id, title: w.title, author: w.author, first_publish_year: null, cover_url: w.cover_url,
                       description: null, edition_count: w.edition_count, thread_count: 0, shelf_count: 0,
                       series_slug: w.series.slug, series_name: w.series.kind === 'series' ? w.series.name : null })
const CORRECTION = { id: 'c1', op: 'merge_works', exportable: true, undoable: false, room_slug: 'dune' }

function mockApi() {
  client.get.mockImplementation((url, config) => {
    if (url === '/works/search') return Promise.resolve({ data: RESULTS[config.params.q] ?? [] })
    const preview = url.match(/^\/librarian\/works\/(\w+)\/merge-preview$/)
    if (preview) {
      const [from, to] = [BY_ID[preview[1]], BY_ID[config.params.into]]
      return Promise.resolve({ data: { source: side(from), target: side(to), threads: 0, shelves: 0, editions: 0 } })
    }
    return Promise.reject(new Error(`unmocked GET ${url}`))
  })
}

function Where() {
  const loc = useLocation()
  const navigate = useNavigate()
  return (
    <>
      <p data-testid="where">{loc.pathname}{loc.state?.correction ? ` fixed ${loc.state.correction.id}` : ''}</p>
      <button type="button" onClick={() => navigate('/search?q=messiah')}>search messiah</button>
    </>
  )
}

function renderPage(entry = '/search?q=dune') {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[entry]}>
        <Where />
        <Routes>
          <Route path="/search" element={<Search />} />
          <Route path="/series/:slug" element={<p>series page</p>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

const asLibrarian = () => useAuthStore.setState({ token: 't', user: { id: 'u1', username: 'lib', is_librarian: true } })
const card = (w) => screen.getByRole('checkbox', { name: `select ${w.title} by ${w.author}` })

async function startSelecting() {
  await userEvent.click(await screen.findByRole('button', { name: 'select' }))
}

beforeEach(() => {
  vi.clearAllMocks()
  mockApi()
})

describe('Search page', () => {
  it('readers and visitors get plain links and no toggle', async () => {
    for (const user of [{ id: 'u2', username: 'reader' }, null]) {
      useAuthStore.setState({ token: user ? 't' : null, user })
      const { unmount } = renderPage()
      expect(await screen.findAllByRole('link')).toHaveLength(3)
      expect(screen.queryByRole('button', { name: 'select' })).toBeNull()
      expect(screen.queryByRole('checkbox')).toBeNull()
      unmount()
    }
  })

  it('selecting never navigates', async () => {
    asLibrarian()
    renderPage()
    await startSelecting()
    expect(screen.getByRole('button', { name: 'select' })).toHaveAttribute('aria-pressed', 'true')
    expect(screen.queryAllByRole('link')).toHaveLength(0)
    await userEvent.click(screen.getByRole('img', { name: 'Dune' }))
    expect(card(FRANK)).toBeChecked()
    expect(screen.getByTestId('where')).toHaveTextContent('/search')
    expect(screen.getByRole('status')).toHaveTextContent('1 selected')
  })

  it('keeps the selection across a new search', async () => {
    asLibrarian()
    renderPage()
    await startSelecting()
    await userEvent.click(card(BRIAN))
    await userEvent.click(screen.getByRole('button', { name: 'search messiah' }))
    await userEvent.click(await screen.findByRole('checkbox', { name: 'select Dune Messiah by Frank Herbert' }))
    expect(screen.getByRole('status')).toHaveTextContent('2 selected')
    const picked = within(screen.getByRole('list', { name: 'Selected books' })).getAllByRole('listitem')
    expect(picked.map((li) => li.textContent)).toEqual(['Dune Brian Herbert', 'Dune Messiah Frank Herbert'])
    expect(screen.getByRole('button', { name: 'merge…' })).toBeEnabled()
  })

  it('leaving select mode clears the selection and restores the links', async () => {
    asLibrarian()
    renderPage()
    await startSelecting()
    await userEvent.click(card(BRIAN))
    await userEvent.click(screen.getByRole('button', { name: 'select' }))
    expect(screen.getAllByRole('link')).toHaveLength(3)
    await startSelecting()
    expect(screen.getByRole('status')).toHaveTextContent('0 selected')
  })

  it('a revoked librarian loses select mode', async () => {
    asLibrarian()
    renderPage()
    await startSelecting()
    act(() => useAuthStore.setState({ user: { id: 'u1', username: 'lib', is_librarian: false } }))
    expect(screen.queryByRole('checkbox')).toBeNull()
    expect(screen.getAllByRole('link')).toHaveLength(3)
  })

  it('closing the panel keeps the selection', async () => {
    asLibrarian()
    renderPage()
    await startSelecting()
    await userEvent.click(card(BRIAN))
    await userEvent.click(card(FRANK))
    await userEvent.click(screen.getByRole('button', { name: 'merge…' }))
    await userEvent.keyboard('{Escape}')
    expect(screen.queryByRole('dialog')).toBeNull()
    expect(card(BRIAN)).toBeChecked()
    expect(card(FRANK)).toBeChecked()
    expect(screen.getByRole('button', { name: 'merge…' })).toHaveFocus() // the panel returns focus
  })

  it("merge… opens the panel preset with the preview, and a merge lands on the survivor's page", async () => {
    client.post
      .mockRejectedValueOnce({ response: { status: 422, data: { detail: {
        message: 'm', consequences: { threads: 0, shelves: 0, editions: 2 } } } } })
      .mockResolvedValueOnce({ data: CORRECTION })
    asLibrarian()
    renderPage()
    await startSelecting()
    await userEvent.click(card(BRIAN))
    await userEvent.click(card(FRANK))
    await userEvent.click(screen.getByRole('button', { name: 'merge…' }))

    const dialog = screen.getByRole('dialog')
    expect(within(dialog).queryByLabelText('Find the book to keep')).toBeNull()
    const preview = await within(dialog).findByRole('group', { name: 'Merge preview' })
    expect(within(preview).getByRole('region', { name: /^merges away/ })).toHaveTextContent('Brian Herbert')
    expect(within(preview).getByRole('region', { name: /^survives/ })).toHaveTextContent('Frank Herbert')

    await userEvent.type(within(dialog).getByLabelText('Reason'), 'duplicate record')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Merge' }))
    await userEvent.click(await within(dialog).findByRole('button', { name: 'Confirm merge' }))
    await waitFor(() => expect(screen.getByTestId('where')).toHaveTextContent('/series/dune fixed c1'))
    expect(client.post).toHaveBeenLastCalledWith('/librarian/works/w1/merge',
      { reason: 'duplicate record', into_work_id: 'w2', confirm: true })
  })
})
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd frontend && npx vitest run src/pages/Search.test.jsx`
Expected: `readers and visitors…` PASSES, because the page already behaves that way for them. Every librarian test FAILS with `Unable to find role="button" and name "select"`.

- [ ] **Step 3: Implement the page**

Replace `frontend/src/pages/Search.jsx` with:

```jsx
import { useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { useSearchWorks } from '../api/works'
import WorkCard from '../components/WorkCard'
import LibrarianPanel from '../components/LibrarianPanel'
import SelectionBar from '../components/librarian/SelectionBar'
import { useStatusBar } from '../store/status'
import useAuthStore from '../store/auth'

function Search() {
  const [searchParams] = useSearchParams()
  const q = searchParams.get('q') || ''
  const { data: works, isLoading, isError } = useSearchWorks(q)
  const navigate = useNavigate()
  const librarian = useAuthStore((s) => !!s.user?.is_librarian)
  // Librarian select mode. The selection outlives a new search: the two halves
  // of a duplicate often only turn up under different queries.
  const [selecting, setSelecting] = useState(false)
  const [selected, setSelected] = useState([]) // works, in the order picked
  const [merging, setMerging] = useState(false)
  const choosing = librarian && selecting

  const toggle = (work) =>
    setSelected((s) => (s.some((w) => w.id === work.id) ? s.filter((w) => w.id !== work.id) : [...s, work]))
  const toggleSelecting = () => {
    setSelecting((v) => !v)
    setSelected([])
  }

  useStatusBar({
    mode: 'SEARCH',
    path: q ? `~/search?q=${q}` : '~/search',
    facts: works ? [`${works.length} results`] : [],
  })

  return (
    <main className="max-w-shell mx-auto px-4 py-6 flex flex-col gap-8">
      <div className="border-b border-line pb-4 flex flex-wrap items-end justify-between gap-3">
        <div className="flex flex-col gap-1">
          <h1 className="text-lg text-ink">
            <span aria-hidden="true" className="text-accent">$ </span>
            search {q && <span className="text-path">&quot;{q}&quot;</span>}
          </h1>
          {works && (
            <p className="text-ink-dim text-xs tabular-nums">
              {works.length} {works.length === 1 ? 'result' : 'results'}
            </p>
          )}
        </div>
        {librarian && (
          <button type="button" aria-pressed={choosing} onClick={toggleSelecting}
                  className={choosing ? 'btn-secondary text-xs' : 'btn-ghost text-xs'}>
            select
          </button>
        )}
      </div>

      {choosing && (
        <SelectionBar selected={selected} onClear={() => setSelected([])} onMerge={() => setMerging(true)} />
      )}

      {!q && <p className="text-ink-dim text-sm">Enter a search term to find books.</p>}

      {q.length === 1 && (
        <p className="text-ink-dim text-sm">Type at least 2 characters to search.</p>
      )}

      {isLoading && q.length > 1 && (
        <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 gap-5">
          {Array.from({ length: 10 }).map((_, i) => (
            <div key={i} className="animate-pulse flex flex-col gap-3">
              <div className="aspect-[2/3] bg-panel border border-line" />
              <div className="h-3 bg-panel w-3/4" />
              <div className="h-3 bg-panel w-1/2" />
            </div>
          ))}
        </div>
      )}

      {isError && <p className="alert-danger">Failed to load results. Please try again.</p>}

      {works && works.length === 0 && (
        <p className="text-ink-dim text-sm">No books found for &quot;{q}&quot;.</p>
      )}

      {works && works.length > 0 && (
        <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 gap-5">
          {works.map((work) => (
            <WorkCard
              key={work.id}
              work={work}
              {...(choosing ? { selected: selected.some((w) => w.id === work.id), onSelect: toggle } : {})}
            />
          ))}
        </div>
      )}

      {choosing && merging && selected.length === 2 && (
        <LibrarianPanel
          // The first pick merges into the second; the preview's swap flips them.
          action={{ kind: 'merge', work: selected[0], into: selected[1] }}
          onClose={() => setMerging(false)}
          onDone={(correction) => {
            setMerging(false)
            setSelecting(false)
            setSelected([])
            // The survivor's page shows the result line, the same as a fix made there.
            if (correction.room_slug) navigate(`/series/${correction.room_slug}`, { state: { correction } })
          }}
        />
      )}
    </main>
  )
}

export default Search
```

- [ ] **Step 4: Run the page tests and the full unit suite**

Run: `cd frontend && npx vitest run src/pages/Search.test.jsx`
Expected: all PASS.

Run: `cd frontend && npm test`
Expected: all PASS, including `Series.test.jsx`, `LibrarianPanel.test.jsx`, `WorkCard.test.jsx` and `tokens.test.js`.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/Search.jsx frontend/src/pages/Search.test.jsx
git commit -m "feat(web): librarians select two search results and merge them with a preview"
```

---

### Task 4: End-to-end: select two results and preview their merge

**Files:**
- Modify: `frontend/e2e/librarian.spec.js` (append)

**Interfaces:**
- Consumes: `registerViaUi`, `grantLibrarian` from `e2e/helpers.js`; the page from Task 3.
- Produces: nothing.

It never confirms: merge is permanent until item 16, and e2e runs against the dev database. It needs the full stack and live Open Library, like the v1 scenario.

- [ ] **Step 1: Write the scenario**

Append to `frontend/e2e/librarian.spec.js`:

```js
// A librarian checks two search results, opens merge…, sees both side by
// side with the first merging into the second, swaps, and backs out.
test('a librarian selects two search results and previews their merge', async ({ page }) => {
  const user = await registerViaUi(page)
  grantLibrarian(user)
  await page.reload()

  await page.goto('/search?q=dune')
  await page.getByRole('button', { name: 'select', exact: true }).click()
  const boxes = page.getByRole('checkbox', { name: /^select / })
  await expect(boxes.nth(1)).toBeVisible()
  await boxes.nth(0).check()
  await boxes.nth(1).check()
  await expect(page).toHaveURL(/\/search\?q=dune$/) // selecting did not navigate
  await expect(page.getByRole('status').filter({ hasText: 'selected' })).toHaveText('2 selected')

  await page.getByRole('button', { name: 'merge…' }).click()
  const dialog = page.getByRole('dialog')
  const preview = dialog.getByRole('group', { name: 'Merge preview' })
  const away = preview.getByRole('region', { name: /^merges away: / })
  await expect(away).toBeVisible()
  const awayName = await away.getAttribute('aria-label')

  await preview.getByRole('button', { name: 'swap which book survives' }).click()
  await expect(preview.getByRole('region', { name: awayName.replace('merges away', 'survives') })).toBeVisible()

  await page.keyboard.press('Escape')
  await expect(dialog).toBeHidden()
  await expect(boxes.nth(0)).toBeChecked() // backing out keeps the picks
})
```

- [ ] **Step 2: Run it**

Run (stack up in another terminal via `docker compose up --build`, then from `frontend/`): `npm run test:e2e -- librarian.spec.js`
Expected: every scenario in the file passes: v1's move, item 04's preview, and this one.

- [ ] **Step 3: Commit**

```bash
git add frontend/e2e/librarian.spec.js
git commit -m "test(e2e): librarian selects two search results and previews their merge"
```

---

### Task 5: Docs and tracker

**Files:**
- Modify: `docs/librarian-ux-roadmap.md`, `ROADMAP.md`, `CLAUDE.md`

- [ ] **Step 1: Write them**

- `docs/librarian-ux-roadmap.md`:
  - Tracker row 05: status `✅`, *Done* = merge date, *PR* = the PR link (fill both when the PR merges; until then leave `🟡`).
  - Under **Notes**, add:
    `- 2026-09-29 (05): LibrarianPanel accepts action.into to preset the book to keep (the picker is then hidden) and needs no action.series for a merge. WorkCard takes optional selected/onSelect; with onSelect it is a label+checkbox, never a link. components/librarian/SelectionBar.jsx is search-only; item 08's series-page bar is separate. Search keeps the selection across queries and clears it on leaving select mode or after a merge, which navigates to the survivor's page with location.state.correction.`
  - Tick this plan's **Merged** checkbox in its header.
- `ROADMAP.md`, Phase 5 table: add directly under item 04's row:
  `| ✅ | **Librarian: merge from search** — librarians toggle \`select\` on search results; exactly two checked enables \`merge…\`, which opens the merge panel with both preset and the side-by-side preview. Readers see plain links. | [plan](docs/superpowers/plans/2026-09-29-lx05-merge-from-search.md), \`pages/Search.jsx\`, \`components/WorkCard.jsx\`, \`components/librarian/SelectionBar.jsx\`, \`components/LibrarianPanel.jsx\` |`
- `CLAUDE.md`, **Known remaining gaps**, in the librarian bullet, change "Librarian tools cover merge/split/move/reorder/rename/remove/dissolve in-app;" to:
  "Librarian tools cover merge/split/move/reorder/rename/remove/dissolve in-app (from the series page in edit mode; merge also from search results via `select`);"

- [ ] **Step 2: Verify, then commit**

Run: `cd frontend && npm test && npm run build`
Expected: all green. Vite builds with no errors. There are no backend changes, but run `PYTEST -q -p no:warnings` if item 04's docs task was skipped on this branch. (`PYTEST` as defined in item 04's plan: `docker compose run --rm --no-deps -v "$PWD/pipeline:/pipeline:ro" -e DATABASE_URL=postgresql+asyncpg://margin:margin@db:5432/margin_test backend pytest`.)

```bash
git add docs/librarian-ux-roadmap.md ROADMAP.md CLAUDE.md docs/superpowers/plans/2026-09-29-lx05-merge-from-search.md
git commit -m "docs: merge from search results (lx05)"
```

---

## Self-review

- **Spec coverage (§05):** the librarian-only `select` toggle is Task 3 (test: readers/visitors get none). "Checking two results enables `merge…`" is Task 2 `SelectionBar` plus Task 3. "Opens the merge panel with both preset and the preview shown" is Task 2's panel preset plus Task 3's end-to-end unit test. "Frontend only (uses 04)" holds: no backend files are touched, and the preview comes from item 04's `useMergePreview` through `PreviewSlot`. Readers are unaffected: Task 3's first test. Because WorkCard is a link, selection must not navigate: Task 1 and Task 3 tests. Keyboard/aria is covered by the Task 1 Space test, the checkbox names, the `aria-pressed` toggle, the `role="status"` count, `aria-describedby` on the disabled merge button, and focus returning to `merge…`. The e2e scenario is Task 4, and the tracker and docs are Task 5.
- **Placeholders:** none. Every code step carries its code, and every run step its command and expectation.
- **Type consistency:** `WorkCard({ work, selected, onSelect })` is the same in Tasks 1 and 3. `SelectionBar({ selected, onMerge, onClear })` is the same in Tasks 2 and 3. `action = { kind: 'merge', work, into }` is the same in Tasks 2 and 3. Item 04's names (`Merge preview`, `merges away: …`, `survives: …`, `swap which book survives`) are used verbatim.
- **Review Focus:** each of the five lines names its test in the owning task.
