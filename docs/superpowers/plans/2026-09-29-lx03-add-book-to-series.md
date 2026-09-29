# Add a Book from the Series Page Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A librarian on a real series page in edit mode can pull a book into this series: `add a book` opens the panel with a book search and an optional position, warns when the picked book already lives in another real series, and submits a v1 **move** of that book into this series.

**Architecture:** Frontend only. `WorkPicker` and `SeriesPicker` move out of `LibrarianPanel.jsx` into `components/librarian/pickers.jsx` and take a `label` prop. `LibrarianPanel` gains an `add` kind whose request is `POST /librarian/works/{picked}/move {series_id: <this series>, position?}`, the existing v1 route. The "already in another series" warning uses data the search API already returns: `GET /api/works/search` answers `WorkOut[]`, and every `WorkOut` carries `series: {slug, name, kind} | null` (built by `load_work_presentation`, `backend/app/services/works.py:546`). `kind === 'series'` is a real series; `slug === <this page's slug>` means the book is already here. No endpoint changes.

**Tech Stack:** React 18, React Query 5, Tailwind tokens, Vitest + React Testing Library, Playwright.

**Spec:** docs/librarian-ux-roadmap.md §03 · Add a book from the series page

**Roadmap item:** 03 — tick in docs/librarian-ux-roadmap.md when merged

- [ ] **Merged** (PR: ___)

## Global Constraints

- Repo rules in `CLAUDE.md` apply verbatim: design tokens only, serif only for book titles and series names, no new radii/shadows/font sizes/durations, `aria-hidden` on every glyph, run the §36 test before calling the screen done.
- Frontend only: no backend file changes. The submit is the v1 move route: `POST /api/librarian/works/{id}/move {series_id, position?, reason}`.
- Every write carries a required, non-empty reason (the submit stays disabled while the stripped reason is empty; the server refuses a blank one with 422 anyway).
- `add a book` appears only in edit mode, only on a real series (`kind === 'series'`), never on a dissolved series. Readers never see it.
- Shared names (binding, from the roadmap): `WorkPicker` and `SeriesPicker` are exported from `frontend/src/components/librarian/pickers.jsx`, with a `label` prop. `LibrarianPanel.jsx` stays where it is. New librarian components live in `frontend/src/components/librarian/`.
- Do not change how edit mode is derived in `Series.jsx` (item 01 owns that). Tests open edit mode with `?edit=1`, which works before and after item 01.
- If item 02 has merged, `LibrarianPanel` already renders `ReasonField` instead of the reason textarea. This plan does not touch the reason input. It only adds an `add` preset list (Task 3 Step 5).
- One branch, `feat/librarian-lx03-add-book`, from `main`. Commit per task. PR to `main`.
- Frontend unit tests: `cd frontend && npx vitest run <files>`. Network is always mocked (`vi.mock('../api/client')`).

## Review Focus

Five inputs no happy-path test covers that are most likely to bite a librarian. Each line has a test in the task named.

1. **The picked book is already in this series.** A move would come back 422 "already in". The panel says so and keeps submit disabled (Task 2, `will not add a book that is already here`).
2. **The picked book lives in another real series.** Adding it takes it out of there along with the threads tagged with it. The panel names that series before submit (Task 2, `warns before taking a book out of another real series`).
3. **The picked book is on its own page (a singleton).** That is the normal case and gets no warning (Task 2, `says nothing extra for a book on its own page`).
4. **A dissolved series, or a singleton page.** Neither shows `add a book` (Task 3, `offers add a book only on a live real series`).
5. **Typing in the search.** A cold search reaches Open Library and ingests what it finds, so it runs once typing pauses and not on every keystroke. The move to `pickers.jsx` must keep the debounce (Task 1, `searches once typing pauses`).

---

## File Structure

**Create**
- `frontend/src/components/librarian/pickers.jsx`: `WorkPicker({ label, exclude, value, onChange })`, `SeriesPicker({ label, value, onChange })`, and the private `useDebounced`. Search-and-pick controls shared by every librarian float.
- `frontend/src/components/librarian/pickers.test.jsx`: the pickers on their own.

**Modify**
- `frontend/src/components/LibrarianPanel.jsx`: import the pickers, add the `add` kind (request, readiness, title, warning).
- `frontend/src/components/LibrarianPanel.test.jsx`: `add` kind tests.
- `frontend/src/pages/Series.jsx`: `add a book` header button.
- `frontend/src/pages/Series.test.jsx`: page-level add flow.
- `frontend/src/components/librarian/reasons.js`: only if item 02 has merged. Adds `add` presets.
- `frontend/e2e/helpers.js`, `frontend/e2e/librarian.spec.js`: one Playwright scenario.
- `docs/librarian-ux-roadmap.md`, `ROADMAP.md`, `CLAUDE.md`: tracker and docs.

---

### Task 1: Move the pickers to `components/librarian/pickers.jsx` with a `label` prop

**Files:**
- Create: `frontend/src/components/librarian/pickers.jsx`
- Create: `frontend/src/components/librarian/pickers.test.jsx`
- Modify: `frontend/src/components/LibrarianPanel.jsx` (remove `useDebounced`, `SeriesPicker`, `WorkPicker`; import them)

**Interfaces:**
- Consumes: `useSearchWorks(query)` from `frontend/src/api/works.js`, and `useSeriesSearch(q)` from `frontend/src/api/librarian.js` (both unchanged).
- Produces: `export function WorkPicker({ label = 'Find a book', exclude, value, onChange })`. `value` and the `onChange` argument are a `WorkOut` (`{id, title, author, series: {slug, name, kind} | null, …}`). Each hit whose `series.kind === 'series'` shows `in <series name>`. The results radiogroup is named `` `${label}: results` ``.
- Produces: `export function SeriesPicker({ label = 'Find a series', value, onChange })`. Its behaviour is unchanged (`value` is a `SeriesHit`, or `{ name }` for a new series). The results radiogroup is named `` `${label}: results` ``.
- Every later task and item (05, 08, 14) imports these from `components/librarian/pickers.jsx`.

- [ ] **Step 1: Branch and mark the item started**

```bash
git checkout main && git pull
git checkout -b feat/librarian-lx03-add-book
```

In `docs/librarian-ux-roadmap.md`, change row 03 of the tracker to status `🟡` and Branch `feat/librarian-lx03-add-book`:

```markdown
| 03 | Add a book from the series page | [plan](superpowers/plans/2026-09-29-lx03-add-book-to-series.md) | — | 🟡 | feat/librarian-lx03-add-book | | |
```

- [ ] **Step 2: Write the failing picker tests**

`frontend/src/components/librarian/pickers.test.jsx`:

```jsx
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

vi.mock('../../api/client', () => ({ default: { get: vi.fn(), post: vi.fn() } }))

import client from '../../api/client'
import { SeriesPicker, WorkPicker } from './pickers'

function wrap(ui) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>)
}

beforeEach(() => vi.clearAllMocks())

describe('WorkPicker', () => {
  it('labels its search with the label it is given', () => {
    wrap(<WorkPicker label="Find the book to add" value={null} onChange={vi.fn()} />)
    expect(screen.getByLabelText('Find the book to add')).toHaveAttribute('type', 'text')
    expect(screen.getByRole('radiogroup', { name: 'Find the book to add: results' })).toBeInTheDocument()
  })

  it('says which real series a found book lives in, and nothing for a book on its own page', async () => {
    client.get.mockResolvedValue({ data: [
      { id: 'w2', title: 'Iron Gold', author: 'Pierce Brown',
        series: { slug: 'red-rising', name: 'Red Rising', kind: 'series' } },
      { id: 'w3', title: 'Dune', author: 'Frank Herbert',
        series: { slug: 'dune-a1b2', name: 'Dune', kind: 'singleton' } },
    ] })
    const onChange = vi.fn()
    wrap(<WorkPicker label="Find a book" value={null} onChange={onChange} />)
    await userEvent.type(screen.getByLabelText('Find a book'), 'iron')
    expect(await screen.findByRole('radio', { name: /Iron Gold.*in Red Rising/ })).toBeInTheDocument()
    expect(screen.getByRole('radio', { name: /Dune/ })).not.toHaveAccessibleName(/ in /)
    await userEvent.click(screen.getByRole('radio', { name: /Iron Gold/ }))
    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ id: 'w2' }))
  })

  it('leaves out the excluded book', async () => {
    client.get.mockResolvedValue({ data: [
      { id: 'w1', title: 'Dune', author: 'Brian Herbert', series: null },
      { id: 'w2', title: 'Dune', author: 'Frank Herbert', series: null },
    ] })
    wrap(<WorkPicker label="Find a book" exclude="w1" value={null} onChange={vi.fn()} />)
    await userEvent.type(screen.getByLabelText('Find a book'), 'dune')
    expect(await screen.findByRole('radio', { name: /Frank Herbert/ })).toBeInTheDocument()
    expect(screen.queryByRole('radio', { name: /Brian Herbert/ })).toBeNull()
  })

  it('searches once typing pauses, not on every keystroke', async () => {
    client.get.mockResolvedValue({ data: [] })
    wrap(<WorkPicker label="Find a book" value={null} onChange={vi.fn()} />)
    await userEvent.type(screen.getByLabelText('Find a book'), 'dune messiah')
    await waitFor(() => expect(client.get).toHaveBeenCalledWith('/works/search', { params: { q: 'dune messiah' } }))
    expect(client.get.mock.calls.filter(([url]) => url === '/works/search')).toHaveLength(1)
  })
})

describe('SeriesPicker', () => {
  it('takes a label and still offers a new series by name', async () => {
    client.get.mockResolvedValue({ data: [] })
    const onChange = vi.fn()
    wrap(<SeriesPicker label="Move them to" value={null} onChange={onChange} />)
    await userEvent.type(screen.getByLabelText('Move them to'), 'Legends of Dune')
    await userEvent.click(await screen.findByRole('radio', { name: 'new series: Legends of Dune' }))
    expect(onChange).toHaveBeenCalledWith({ name: 'Legends of Dune' })
  })

  it('defaults its label to "Find a series"', () => {
    wrap(<SeriesPicker value={null} onChange={vi.fn()} />)
    expect(screen.getByLabelText('Find a series')).toBeInTheDocument()
  })
})
```

- [ ] **Step 3: Run it to make sure it fails**

Run: `cd frontend && npx vitest run src/components/librarian/pickers.test.jsx`
Expected: FAIL. `Failed to resolve import "./pickers"`.

- [ ] **Step 4: Create `pickers.jsx`**

`frontend/src/components/librarian/pickers.jsx`:

```jsx
import { useEffect, useId, useState } from 'react'
import { useSeriesSearch } from '../../api/librarian'
import { useSearchWorks } from '../../api/works'

/**
 * Search-and-pick controls every librarian float shares. Each is a labelled
 * search box over a radiogroup of hits; picking one hands the hit back. They
 * decide nothing; the panel that uses them does.
 */
const plural = (n, one, many = `${one}s`) => `${n} ${n === 1 ? one : many}`

/** ``value`` once it has stopped changing for ``ms``. */
function useDebounced(value, ms = 300) {
  const [settled, setSettled] = useState(value)
  useEffect(() => {
    const timer = setTimeout(() => setSettled(value), ms)
    return () => clearTimeout(timer)
  }, [value, ms])
  return settled
}

export function SeriesPicker({ label = 'Find a series', value, onChange }) {
  const id = useId()
  const [q, setQ] = useState('')
  const { data: hits = [] } = useSeriesSearch(q)
  const named = q.trim()
  return (
    <div className="flex flex-col gap-2">
      <label className="label" htmlFor={id}>{label}</label>
      <input id={id} type="text" className="input" value={q} onChange={(e) => setQ(e.target.value)} />
      <div role="radiogroup" aria-label={`${label}: results`} className="flex flex-col gap-1 text-sm">
        {hits.map((s) => (
          <label key={s.id} className="flex items-center gap-2">
            <input type="radio" name={id} checked={value?.id === s.id} onChange={() => onChange(s)} />
            <span className="font-serif text-ink">{s.name}</span>
            <span className="text-ink-dim tabular-nums">{plural(s.book_count, 'book')}</span>
          </label>
        ))}
        {named.length > 1 && !hits.some((s) => s.name.toLowerCase() === named.toLowerCase()) && (
          <label className="flex items-center gap-2">
            <input type="radio" name={id} checked={!value?.id && value?.name === named}
                   onChange={() => onChange({ name: named })} />
            <span className="text-warning">new series: {named}</span>
          </label>
        )}
      </div>
    </div>
  )
}

export function WorkPicker({ label = 'Find a book', exclude, value, onChange }) {
  const id = useId()
  const [q, setQ] = useState('')
  // A cold search reaches Open Library and ingests what it finds: never per keystroke.
  const { data: works = [] } = useSearchWorks(useDebounced(q.trim()))
  return (
    <div className="flex flex-col gap-2">
      <label className="label" htmlFor={id}>{label}</label>
      <input id={id} type="text" className="input" value={q} onChange={(e) => setQ(e.target.value)} />
      <div role="radiogroup" aria-label={`${label}: results`} className="flex flex-col gap-1 text-sm">
        {works.filter((w) => w.id !== exclude).map((w) => (
          <label key={w.id} className="flex items-center gap-2">
            <input type="radio" name={id} checked={value?.id === w.id} onChange={() => onChange(w)} />
            <span className="font-serif text-ink">{w.title}</span>
            <span className="text-user text-xs">{w.author}</span>
            {/* Where it lives now, so a librarian sees a move coming before picking. */}
            {w.series?.kind === 'series' && (
              <span className="text-ink-dim text-xs">in <span className="font-serif">{w.series.name}</span></span>
            )}
          </label>
        ))}
      </div>
    </div>
  )
}
```

- [ ] **Step 5: Use them from `LibrarianPanel.jsx`**

In `frontend/src/components/LibrarianPanel.jsx`:

Replace the import block at the top:

```jsx
import { useEffect, useRef, useState } from 'react'
import { confirmationOf, useLibrarianAction, useSeriesSearch, useWorkEditions } from '../api/librarian'
import { useSearchWorks } from '../api/works'
import { errorMessage } from '../api/errors'
```

with:

```jsx
import { useEffect, useRef, useState } from 'react'
import { confirmationOf, useLibrarianAction, useWorkEditions } from '../api/librarian'
import { errorMessage } from '../api/errors'
import { SeriesPicker, WorkPicker } from './librarian/pickers'
```

Delete the whole `useDebounced` function, the whole `SeriesPicker` function and the whole `WorkPicker` function from `LibrarianPanel.jsx`. Keep `plural`, because `Consequences` uses it.

Change the merge picker line in the form from:

```jsx
            {kind === 'merge' && <WorkPicker exclude={work.id} value={fields.into} onChange={set('into')} />}
```

to:

```jsx
            {kind === 'merge' && (
              <WorkPicker label="Find the book to keep" exclude={work.id} value={fields.into} onChange={set('into')} />
            )}
```

The `SeriesPicker` line (`{kind === 'move' && <SeriesPicker value={fields.target} onChange={set('target')} />}`) stays as it is. Its default label is still `Find a series`.

- [ ] **Step 6: Run the picker and panel tests**

Run: `cd frontend && npx vitest run src/components/librarian/pickers.test.jsx src/components/LibrarianPanel.test.jsx src/pages/Series.test.jsx`
Expected: PASS. The 6 new picker tests pass, and every existing panel and series test still passes. They query `Find the book to keep` and `Find a series` by label and radios by name, and none of that changed.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/components/librarian/pickers.jsx frontend/src/components/librarian/pickers.test.jsx \
  frontend/src/components/LibrarianPanel.jsx docs/librarian-ux-roadmap.md
git commit -m "refactor(web): librarian pickers move to components/librarian with a label prop"
```

---

### Task 2: The `add` kind in `LibrarianPanel`

**Files:**
- Modify: `frontend/src/components/LibrarianPanel.jsx`
- Test: `frontend/src/components/LibrarianPanel.test.jsx`

**Interfaces:**
- Consumes: `WorkPicker` from Task 1.
- Produces: `LibrarianPanel` accepts `action = { kind: 'add', series }` (no `work`). The dialog title is `` `Add a book to ${series.name}` ``. The submit button is `Add book`. The submit sends `POST /librarian/works/{picked.id}/move` with `{ reason, series_id: series.id, position? }` and calls `onDone(correction)` with the `CorrectionOut`. Task 3 opens it with `setAction({ kind: 'add' })`. Item 10's `a` shortcut does the same.

- [ ] **Step 1: Write the failing tests**

Append inside the `describe('LibrarianPanel', …)` block of `frontend/src/components/LibrarianPanel.test.jsx` (the file's `SERIES` is `{ id: 's1', name: 'Dune', slug: 'dune', kind: 'series' }`):

```jsx
  it('adds the picked book as a move into this series', async () => {
    client.get.mockResolvedValue({ data: [
      { id: 'w9', title: 'Dune Messiah', author: 'Frank Herbert', series: { slug: 'dune-messiah-x', name: 'Dune Messiah', kind: 'singleton' } },
    ] })
    client.post.mockResolvedValue({ data: CORRECTION })
    const onDone = renderPanel({ kind: 'add' })
    expect(screen.getByRole('dialog', { name: 'Add a book to Dune' })).toBeInTheDocument()
    const submit = screen.getByRole('button', { name: 'Add book' })
    expect(submit).toBeDisabled()

    await userEvent.type(screen.getByLabelText('Find the book to add'), 'messiah')
    await userEvent.click(await screen.findByRole('radio', { name: /Dune Messiah/ }))
    await userEvent.type(screen.getByLabelText('Position (optional)'), '2')
    expect(submit).toBeDisabled() // still no reason
    await userEvent.type(screen.getByLabelText('Reason'), 'book two')
    await userEvent.click(submit)

    await waitFor(() => expect(onDone).toHaveBeenCalledWith(CORRECTION))
    expect(client.post).toHaveBeenCalledWith('/librarian/works/w9/move',
      { reason: 'book two', series_id: 's1', position: 2 })
  })

  it('leaves the position out when none is given', async () => {
    client.get.mockResolvedValue({ data: [{ id: 'w9', title: 'Dune Messiah', author: 'Frank Herbert', series: null }] })
    client.post.mockResolvedValue({ data: CORRECTION })
    renderPanel({ kind: 'add' })
    await userEvent.type(screen.getByLabelText('Find the book to add'), 'messiah')
    await userEvent.click(await screen.findByRole('radio', { name: /Dune Messiah/ }))
    await userEvent.type(screen.getByLabelText('Reason'), 'book two')
    await userEvent.click(screen.getByRole('button', { name: 'Add book' }))
    await waitFor(() => expect(client.post).toHaveBeenCalledWith('/librarian/works/w9/move',
      { reason: 'book two', series_id: 's1' }))
  })

  it('warns before taking a book out of another real series', async () => {
    client.get.mockResolvedValue({ data: [
      { id: 'w7', title: 'Hunters of Dune', author: 'Brian Herbert',
        series: { slug: 'dune-chronicles', name: 'Dune Chronicles', kind: 'series' } },
    ] })
    renderPanel({ kind: 'add' })
    await userEvent.type(screen.getByLabelText('Find the book to add'), 'hunters')
    await userEvent.click(await screen.findByRole('radio', { name: /Hunters of Dune/ }))
    const warning = screen.getByText(/Adding it here takes it out of/)
    expect(warning).toHaveTextContent('Hunters of Dune is in Dune Chronicles now.')
    expect(warning).toHaveTextContent('with the threads tagged with it')
    await userEvent.type(screen.getByLabelText('Reason'), 'belongs here')
    expect(screen.getByRole('button', { name: 'Add book' })).toBeEnabled() // a warning, not a refusal
  })

  it('says nothing extra for a book on its own page', async () => {
    client.get.mockResolvedValue({ data: [
      { id: 'w9', title: 'Dune Messiah', author: 'Frank Herbert', series: { slug: 'dune-messiah-x', name: 'Dune Messiah', kind: 'singleton' } },
    ] })
    renderPanel({ kind: 'add' })
    await userEvent.type(screen.getByLabelText('Find the book to add'), 'messiah')
    await userEvent.click(await screen.findByRole('radio', { name: /Dune Messiah/ }))
    expect(screen.queryByText(/takes it out of/)).toBeNull()
    expect(screen.queryByText(/already in/)).toBeNull()
  })

  it('will not add a book that is already here', async () => {
    client.get.mockResolvedValue({ data: [
      { id: 'w1', title: 'Dune', author: 'Frank Herbert', series: { slug: 'dune', name: 'Dune', kind: 'series' } },
    ] })
    renderPanel({ kind: 'add' })
    await userEvent.type(screen.getByLabelText('Find the book to add'), 'dune')
    await userEvent.click(await screen.findByRole('radio', { name: /Frank Herbert/ }))
    await userEvent.type(screen.getByLabelText('Reason'), 'r')
    expect(screen.getByText(/is already in/)).toHaveTextContent('Dune is already in Dune.')
    expect(screen.getByRole('button', { name: 'Add book' })).toBeDisabled()
  })
```

- [ ] **Step 2: Run them to make sure they fail**

Run: `cd frontend && npx vitest run src/components/LibrarianPanel.test.jsx`
Expected: FAIL. The 5 new tests fail with `Unable to find an accessible element with the role "dialog" and name "Add a book to Dune"` (the title reads `undefined Dune`). The existing tests still pass.

- [ ] **Step 3: Implement the `add` kind**

In `frontend/src/components/LibrarianPanel.jsx`:

Replace `TITLES`:

```jsx
const TITLES = {
  move: 'Move', position: 'Set position', remove: 'Remove from series', merge: 'Merge',
  split: 'Split', rename: 'Rename', dissolve: 'Dissolve',
}
```

with:

```jsx
const TITLES = {
  move: 'Move', position: 'Set position', remove: 'Remove from series', merge: 'Merge',
  split: 'Split', rename: 'Rename', dissolve: 'Dissolve', add: 'Add book',
}

/** Where the picked book lives now, relative to this series. */
function placeOf(pick, series) {
  if (!pick?.series) return 'own'
  if (pick.series.slug === series.slug) return 'here'
  return pick.series.kind === 'series' ? 'elsewhere' : 'own'
}
```

In `request`, add a case before `case 'position':`:

```jsx
    case 'add':
      // The v1 move, pointed at this series: the picked book is the subject.
      return { path: `works/${f.pick.id}/move`, body: {
        reason, series_id: series.id, ...(position === null ? {} : { position }) } }
```

Replace `ready`:

```jsx
function ready(kind, f, editions) {
  if (!f.reason.trim()) return false
  if (kind === 'move') return !!f.target
```

with:

```jsx
function ready(kind, f, editions, series) {
  if (!f.reason.trim()) return false
  if (kind === 'add') return !!f.pick && placeOf(f.pick, series) !== 'here'
  if (kind === 'move') return !!f.target
```

Add this component after `Consequences`:

```jsx
function AddNotice({ pick, series }) {
  const place = placeOf(pick, series)
  if (place === 'here') {
    return (
      <p className="alert-muted">
        <span className="font-serif italic">{pick.title}</span> is already in{' '}
        <span className="font-serif">{series.name}</span>.
      </p>
    )
  }
  if (place !== 'elsewhere') return null
  return (
    <p className="text-warning text-sm">
      <span className="font-serif italic">{pick.title}</span> is in{' '}
      <span className="font-serif">{pick.series.name}</span> now. Adding it here takes it out of{' '}
      <span className="font-serif">{pick.series.name}</span>, with the threads tagged with it.
    </p>
  )
}
```

In `LibrarianPanel`, add `pick: null` to the initial `fields` state:

```jsx
  const [fields, setFields] = useState({
    reason: '', name: '', target: null, into: null, editions: [], pick: null,
```

Replace the title line:

```jsx
  const title = `${TITLES[kind]}${work ? ` ${work.title}` : ` ${series.name}`}`
```

with:

```jsx
  const title = kind === 'add'
    ? `Add a book to ${series.name}`
    : `${TITLES[kind]}${work ? ` ${work.title}` : ` ${series.name}`}`
```

In the form, just before `{kind === 'move' && <SeriesPicker …`, add:

```jsx
            {kind === 'add' && (
              <>
                <WorkPicker label="Find the book to add" value={fields.pick} onChange={set('pick')} />
                {fields.pick && <AddNotice pick={fields.pick} series={series} />}
              </>
            )}
```

Replace the position block's condition and label:

```jsx
            {(kind === 'move' || kind === 'position') && (
              <div>
                <label className="label" htmlFor="lib-position">{kind === 'move' ? 'Position (optional)' : 'Position (blank clears)'}</label>
```

with:

```jsx
            {(kind === 'move' || kind === 'position' || kind === 'add') && (
              <div>
                <label className="label" htmlFor="lib-position">{kind === 'position' ? 'Position (blank clears)' : 'Position (optional)'}</label>
```

Change the submit button's `disabled` from `!ready(kind, fields, editions) || mutation.isPending` to:

```jsx
                    disabled={!ready(kind, fields, editions, series) || mutation.isPending}>
```

- [ ] **Step 4: Run the tests**

Run: `cd frontend && npx vitest run src/components/LibrarianPanel.test.jsx src/components/librarian/pickers.test.jsx`
Expected: PASS. All panel tests (the 5 new ones included) and the 6 picker tests.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/LibrarianPanel.jsx frontend/src/components/LibrarianPanel.test.jsx
git commit -m "feat(web): librarian panel adds a found book to this series as a move, warning when it leaves another series"
```

---

### Task 3: `add a book` in the series header

**Files:**
- Modify: `frontend/src/pages/Series.jsx` (header actions, around the `rename series` button)
- Modify (only if item 02 has merged): `frontend/src/components/librarian/reasons.js`
- Test: `frontend/src/pages/Series.test.jsx`

**Interfaces:**
- Consumes: `LibrarianPanel` with `action = { kind: 'add', series }` (Task 2).
- Produces: a header button with accessible name `add a book`. It renders only when `editing && isSeries && !series.dissolved`. Item 10's `a` shortcut clicks it, or calls `setAction({ kind: 'add' })`.

- [ ] **Step 1: Write the failing tests**

Append inside `describe('Series page', …)` in `frontend/src/pages/Series.test.jsx`:

```jsx
  it('adds a book from the series header as a move into this series', async () => {
    useAuthStore.setState({ token: 't', user: { id: 'u1', username: 'lib', is_librarian: true } })
    client.get.mockImplementation((url) => {
      if (url.endsWith('/threads')) return Promise.resolve({ data: [] })
      if (url === '/works/search') {
        return Promise.resolve({ data: [{ id: 'b3', title: 'Morning Star', author: 'Pierce Brown',
          series: { slug: 'morning-star-x1', name: 'Morning Star', kind: 'singleton' } }] })
      }
      return Promise.resolve({ data: { ...SAGA, id: 's1' } })
    })
    client.post.mockResolvedValueOnce({ data: { id: 'c9', op: 'set_series', exportable: true, undoable: true, room_slug: 'red-rising' } })
    renderPage('/series/red-rising?edit=1')

    await userEvent.click(await screen.findByRole('button', { name: 'add a book' }))
    await userEvent.type(screen.getByLabelText('Find the book to add'), 'morning star')
    await userEvent.click(await screen.findByRole('radio', { name: /Morning Star/ }))
    await userEvent.type(screen.getByLabelText('Position (optional)'), '3')
    await userEvent.type(screen.getByLabelText('Reason'), 'book three')
    await userEvent.click(screen.getByRole('button', { name: 'Add book' }))

    await waitFor(() => expect(client.post).toHaveBeenCalledWith('/librarian/works/b3/move',
      { reason: 'book three', series_id: 's1', position: 3 }))
    const status = await screen.findByRole('group', { name: 'Librarian fix result' })
    expect(within(status).getByText('exported')).toBeInTheDocument()
    // The book now lives here, so there is no other page to go to.
    expect(within(status).queryByRole('link', { name: /go to its page/ })).toBeNull()
  })

  it('offers add a book only on a live real series', async () => {
    useAuthStore.setState({ token: 't', user: { id: 'u1', username: 'lib', is_librarian: true } })
    mockApi({ ...SINGLE, id: 's9' }, [])
    const { unmount } = renderPage('/series/the-hobbit-a1b2c3?edit=1')
    await screen.findByRole('heading', { level: 1, name: 'The Hobbit' })
    expect(screen.queryByRole('button', { name: 'add a book' })).toBeNull()
    unmount()

    mockApi({ ...SAGA, id: 's1', dissolved: true, works: [] })
    renderPage('/series/red-rising?edit=1')
    await screen.findByText(/This series was dissolved/)
    expect(screen.queryByRole('button', { name: 'add a book' })).toBeNull()
  })

  it('never shows add a book to a reader, even with ?edit=1', async () => {
    mockApi(SAGA)
    renderPage('/series/red-rising?edit=1')
    await screen.findByRole('list', { name: 'Books in this series' })
    expect(screen.queryByRole('button', { name: 'add a book' })).toBeNull()
  })
```

- [ ] **Step 2: Run them to make sure they fail**

Run: `cd frontend && npx vitest run src/pages/Series.test.jsx`
Expected: FAIL. `adds a book from the series header…` fails with `Unable to find an accessible element with the role "button" and name "add a book"`. The other two pass already, because they assert absence. They stay as regression guards.

- [ ] **Step 3: Add the header button**

In `frontend/src/pages/Series.jsx`, replace the header action block:

```jsx
        {editing && isSeries && !series.dissolved && (
          <div className="flex gap-3 text-xs">
            <button type="button" className="btn-ghost text-xs" onClick={() => setAction({ kind: 'rename' })}>rename series</button>
```

with:

```jsx
        {editing && isSeries && !series.dissolved && (
          <div className="flex gap-3 text-xs">
            <button type="button" className="btn-ghost text-xs" onClick={() => setAction({ kind: 'add' })}>add a book</button>
            <button type="button" className="btn-ghost text-xs" onClick={() => setAction({ kind: 'rename' })}>rename series</button>
```

Nothing else changes. `LibrarianPanel` already receives `action={{ ...action, series }}`, and `onDone` already records the result for `[series.slug, correction.room_slug]`.

- [ ] **Step 4: Run the tests**

Run: `cd frontend && npx vitest run src/pages/Series.test.jsx`
Expected: PASS (all series page tests).

- [ ] **Step 5: Presets for `add`, only if item 02 has merged**

Run: `ls frontend/src/components/librarian/reasons.js`

If the file does not exist, skip this step (item 02 will add the entry when it lands; its plan lists preset kinds). If it exists, open it and add an `add` entry in the same shape as its `move` entry. For example, if it exports `export const PRESETS = { move: [...], ... }`, add:

```js
  add: ['belongs to this series', 'missing from this series'],
```

Then run `cd frontend && npx vitest run src/components/librarian` and expect PASS.

- [ ] **Step 6: Full frontend suite, then commit**

Run: `cd frontend && npm test`
Expected: all tests pass.

```bash
git add frontend/src/pages/Series.jsx frontend/src/pages/Series.test.jsx
git add frontend/src/components/librarian/reasons.js 2>/dev/null || true
git commit -m "feat(web): add a book from the series header in edit mode"
```

---

### Task 4: Playwright scenario

**Files:**
- Modify: `frontend/e2e/helpers.js`
- Modify: `frontend/e2e/librarian.spec.js`

**Interfaces:**
- Produces: `ensureEditMode(page)` and `moveFirstResultInto(page, query, saga, { create })` in `frontend/e2e/helpers.js`. Items 08 and 09 reuse them.

- [ ] **Step 1: Add the helpers (skip any that already exist)**

Run: `grep -n "export async function ensureEditMode\|export async function moveFirstResultInto" frontend/e2e/helpers.js`

Append to `frontend/e2e/helpers.js` whichever of the two is missing:

```js
// Edit mode is sticky after roadmap item 01 and per-URL before it: click
// [edit] only when the page is not already in edit mode.
export async function ensureEditMode(page) {
  const done = page.getByRole('link', { name: '[done]' })
  if (!(await done.isVisible())) await page.getByRole('link', { name: '[edit]' }).click()
  await expect(done).toBeVisible()
}

// Opens the first search result for `query` and moves its first book into
// `saga`. `create` names a new series; otherwise `saga` must already exist.
// Leaves the page on the saga's series page. Returns the moved book's title.
export async function moveFirstResultInto(page, query, saga, { create = false, position } = {}) {
  await openFirstSearchResult(page, query)
  await ensureEditMode(page)
  const books = page.getByRole('list', { name: 'Books in this series' })
  const title = (await books.getByRole('heading', { level: 3 }).first().textContent()).trim()
  await books.getByRole('button', { name: `move ${title}`, exact: true }).click()
  await page.getByLabel('Find a series').fill(saga)
  const radio = create
    ? page.getByRole('radio', { name: `new series: ${saga}` })
    : page.getByRole('radio', { name: new RegExp(`^${saga}`) })
  await radio.check()
  if (position != null) await page.getByLabel('Position (optional)').fill(String(position))
  await page.getByLabel('Reason', { exact: true }).fill('e2e: building a series')
  await page.getByRole('button', { name: 'Move', exact: true }).click()
  const status = page.getByRole('group', { name: 'Librarian fix result' })
  await expect(status).toBeVisible()
  // A singleton the move emptied redirects by itself; a book moved out of a
  // real series needs the link.
  const heading = page.getByRole('heading', { level: 1, name: saga })
  const follow = status.getByRole('link', { name: /go to its page/ })
  await expect(async () => {
    if (await follow.isVisible()) await follow.click({ timeout: 1000 }).catch(() => {})
    await expect(heading).toBeVisible({ timeout: 1000 })
  }).toPass()
  return title
}
```

- [ ] **Step 2: Write the scenario**

Append to `frontend/e2e/librarian.spec.js`, and extend its import line to `import { ensureEditMode, grantLibrarian, moveFirstResultInto, openFirstSearchResult, registerViaUi } from './helpers'`:

```js
// A librarian builds a one-book series, then adds a second book from the
// series header. Needs the full stack and live Open Library.
test('a librarian adds a book from the series page and undoes it', async ({ page }) => {
  const user = await registerViaUi(page)
  grantLibrarian(user)
  await page.reload()

  const saga = `E2E Add ${Date.now()}`
  await moveFirstResultInto(page, 'the left hand of darkness', saga, { create: true })
  await ensureEditMode(page)

  await page.getByRole('button', { name: 'add a book' }).click()
  await page.getByLabel('Find the book to add').fill('the dispossessed')
  const hit = page.getByRole('radio', { name: /Dispossessed/ }).first()
  await hit.check()
  await page.getByLabel('Reason', { exact: true }).fill('e2e: checking add a book')
  await page.getByRole('button', { name: 'Add book' }).click()

  const status = page.getByRole('group', { name: 'Librarian fix result' })
  await expect(status).toBeVisible()
  const books = page.getByRole('list', { name: 'Books in this series' })
  await expect(books.getByRole('heading', { level: 3, name: /Dispossessed/ })).toBeVisible()

  await status.getByRole('button', { name: 'undo' }).click()
  await expect(status.getByText('undone')).toBeVisible()
  await expect(books.getByRole('heading', { level: 3, name: /Dispossessed/ })).toHaveCount(0)
})
```

- [ ] **Step 3: Run it**

Run (stack up in another terminal with `docker compose up --build`): `cd frontend && npx playwright test e2e/librarian.spec.js`
Expected: 2 passed (the v1 move scenario and this one).

- [ ] **Step 4: Commit**

```bash
git add frontend/e2e/helpers.js frontend/e2e/librarian.spec.js
git commit -m "test(e2e): librarian adds a book from the series page and undoes it"
```

---

### Task 5: Docs and tracker

**Files:**
- Modify: `docs/librarian-ux-roadmap.md`, `ROADMAP.md`, `CLAUDE.md`, and this plan's header

- [ ] **Step 1: §36 check**

Open a real series in edit mode (`docker compose up`, then any series at `/series/<slug>?edit=1` as a librarian). Check that `add a book` sits with `rename series` / `dissolve series` as ghost buttons, that the panel is the existing float, and that the warning line is `text-warning` prose with serif titles, not a banner. If it reads as a SaaS modal, simplify it before continuing.

- [ ] **Step 2: Update the docs**

`ROADMAP.md`: in the **Librarian tools** row (Phase table), change `in-app merge, split, move-to-series, reorder, rename, remove and dissolve from the series page (`?edit=1`)` to `in-app merge, split, move-to-series (including "add a book" from the series header), reorder, rename, remove and dissolve from the series page (`?edit=1`)`.

`CLAUDE.md`: in "Known remaining gaps", change the first librarian bullet's opening line from `- Librarian tools cover merge/split/move/reorder/rename/remove/dissolve in-app;` to `- Librarian tools cover merge/split/move/reorder/rename/remove/dissolve in-app (a series page can also add a book, as a move);`.

`docs/librarian-ux-roadmap.md`: set tracker row 03 to `✅`, with *Done* = the merge date and *PR* = the PR link. Under **Notes**, add:

```markdown
- 2026-09-29 (03): `WorkPicker` shows `in <series>` for hits in a real series, and both pickers name their results radiogroup `` `${label}: results` `` (label-derived, so two pickers never share a name). The "already in another series" check reads `WorkOut.series` from `/works/search`; no endpoint was added.
```

In this plan's header, tick `- [x] **Merged** (PR: <link>)`.

- [ ] **Step 3: Commit**

```bash
git add docs/librarian-ux-roadmap.md ROADMAP.md CLAUDE.md docs/superpowers/plans/2026-09-29-lx03-add-book-to-series.md
git commit -m "docs: roadmap item 03 (add a book from the series page) done"
```

---

## Self-review

- **Spec coverage:** header button, edit mode only, real series only (Task 3). Panel with work search and optional position (Task 2). Submit is a v1 move (Task 2 request). "Already in another real series" is stated before submit (Task 2 `AddNotice`). Frontend only: no backend files. Pickers moved with `label` (Task 1). Playwright scenario (Task 4). Tracker and docs (Task 5).
- **Placeholders:** none. Task 3 Step 5 is conditional on item 02, and says exactly what to do in each case.
- **Type consistency:** `WorkPicker({ label, exclude, value, onChange })` and `SeriesPicker({ label, value, onChange })` match between Task 1 and their uses. `placeOf` returns `'own' | 'here' | 'elsewhere'`, and `ready` and `AddNotice` use it. `fields.pick` is a `WorkOut`.
- **Review Focus:** each of the five lines has its named test.
