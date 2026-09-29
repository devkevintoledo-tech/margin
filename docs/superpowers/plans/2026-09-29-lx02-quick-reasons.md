# LX02 · Quick Reasons Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

- [ ] **Roadmap item:** 02 — tick in docs/librarian-ux-roadmap.md when merged

**Goal:** Every librarian fix still needs a reason, but the common ones are one click away: preset chips per action kind sit above the reason field, a chip fills the field, and the librarian can still type.

**Architecture:** Presets are data in `components/librarian/reasons.js` (`REASONS` keyed by action kind, plus the pure helpers `reasonsFor`, `presetIn`, `applyPreset`). `components/librarian/ReasonField.jsx` renders the `Reason` label, a `Quick reasons` group of `aria-pressed` toggle buttons, and the textarea, as one controlled component. `LibrarianPanel` swaps its hand-written reason textarea for `ReasonField`; its `ready()` check (non-empty after trim) is untouched, so the field stays required and the server still validates. Frontend only; no API change.

**Tech Stack:** React 18, Tailwind tokens, Vitest 1.6 + React Testing Library + user-event 14, Playwright.

**Spec:** docs/librarian-ux-roadmap.md §02 · Quick reasons (and "Shared names" → Frontend: `components/librarian/ReasonField.jsx`). v1 reason rules: docs/superpowers/specs/2026-09-28-librarian-tools-design.md §5–6 (required `reason`, non-empty after strip).

**Base:** `main` with `fix/librarian-minors` merged — the `LibrarianPanel.jsx` code quoted below (`set()` resetting a refusal, the focus trap) is from that branch. If `git log origin/main --oneline | grep -i "librarian review fixes"` prints nothing, merge that branch first.

## Global Constraints

- `components/librarian/ReasonField.jsx` — reason textarea + preset chips; every panel/float that asks for a reason uses it. (roadmap, Shared names)
- Presets live in `components/librarian/reasons.js`, per action kind: merge "duplicate record", "same book, different edition"; move "wrong series", "belongs to this series"; cover "wrong language", "low quality" — verbatim from the roadmap, plus the others below. (roadmap §02)
- A chip fills the field; the librarian can still type. The field stays required. Frontend only. (roadmap §02)
- `LibrarianPanel.jsx` stays where it is (`components/`); new librarian components go in `components/librarian/`.
- The server sees only the text: no preset id, no new request field. `reason` is still stripped and required by `clean_reason` on the backend.
- Design tokens only; no new radii, shadows, font sizes or durations; chips reuse the page's existing toggle pattern (`aria-pressed` + `text-accent underline underline-offset-4`), since nothing means anything by color alone; mono (not serif) for chip text; §36 test.
- Branch `feat/librarian-lx02-quick-reasons` from `main`; one commit per task; PR to `main`.

## Review Focus

1. **The librarian typed a detail, then clicks a chip.** Their words must survive (`duplicate record: two OL ids for one book`), not be replaced — Task 1 `keeps words the librarian typed`, Task 2 `adds a chip to what was typed`.
2. **A chip inside the panel's `<form>`.** A `<button>` without `type="button"` submits the form; one click would send a fix — Task 2 `never submits the form it sits in`.
3. **Editing a chip's text by hand.** Once the text is no longer the preset, the chip must stop claiming to be pressed — Task 2 `unpresses a chip once its text is edited away`.
4. **A kind with no presets yet** (a later item's new kind before it adds its list). No empty `Quick reasons` group for screen readers to land in; the plain field still works — Task 2 `renders only the field for a kind without presets`.
5. **A chip after a refusal.** The panel clears a stale server error when the reason changes; a chip is a change too — Task 3 `a chip clears a refusal like typing does`.

---

## File Structure

**Create**
- `frontend/src/components/librarian/reasons.js` — `REASONS`, `reasonsFor`, `presetIn`, `applyPreset`.
- `frontend/src/components/librarian/reasons.test.js`
- `frontend/src/components/librarian/ReasonField.jsx` — label + chips + textarea.
- `frontend/src/components/librarian/ReasonField.test.jsx`

**Modify**
- `frontend/src/components/LibrarianPanel.jsx` — use `ReasonField`.
- `frontend/src/components/LibrarianPanel.test.jsx` — chip tests.
- `frontend/e2e/librarian.spec.js` — one-click reason scenario.
- Docs: `docs/librarian-ux-roadmap.md`, `ROADMAP.md`, `CLAUDE.md`.

---

### Task 1: Presets as data

**Files:**
- Create: `frontend/src/components/librarian/reasons.js`
- Test: `frontend/src/components/librarian/reasons.test.js`
- Modify: `docs/librarian-ux-roadmap.md` (tracker row → in progress)

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `REASONS: { [kind: string]: string[] }` — keys `move, position, remove, merge, split, rename, dissolve, cover`. The keys are `LibrarianPanel`'s `action.kind` values (`TITLES` in `LibrarianPanel.jsx`) plus `cover` for item 06. Later items add their kinds here (08's batch kinds reuse `move` / `remove` / `position`).
  - `reasonsFor(kind: string) -> string[]` — `[]` for an unknown kind.
  - `presetIn(value: string, presets: string[]) -> string | null` — the preset the text currently starts from (`value.trim()` equals it, or begins with `"<preset>: "`), else `null`.
  - `applyPreset(value: string, preset: string, presets: string[]) -> string` — the field's text after clicking `preset`.

- [ ] **Step 1: Branch and mark the item in progress**

```bash
git fetch origin
git switch -c feat/librarian-lx02-quick-reasons origin/main
```

In `docs/librarian-ux-roadmap.md`, change the tracker row

```
| 02 | Quick reasons | [plan](superpowers/plans/2026-09-29-lx02-quick-reasons.md) | — | ⬜ | | | |
```

to

```
| 02 | Quick reasons | [plan](superpowers/plans/2026-09-29-lx02-quick-reasons.md) | — | 🟡 | feat/librarian-lx02-quick-reasons | | |
```

- [ ] **Step 2: Write the failing test**

`frontend/src/components/librarian/reasons.test.js`:

```js
import { describe, it, expect } from 'vitest'
import { REASONS, applyPreset, presetIn, reasonsFor } from './reasons'

const MERGE = REASONS.merge

describe('quick reasons', () => {
  it('has presets for every panel action and for covers', () => {
    for (const kind of ['move', 'position', 'remove', 'merge', 'split', 'rename', 'dissolve', 'cover']) {
      expect(reasonsFor(kind).length).toBeGreaterThan(0)
    }
    expect(REASONS.merge).toEqual(expect.arrayContaining(['duplicate record', 'same book, different edition']))
    expect(REASONS.move).toEqual(expect.arrayContaining(['wrong series', 'belongs to this series']))
    expect(REASONS.cover).toEqual(expect.arrayContaining(['wrong language', 'low quality']))
  })

  it('has none for a kind it does not know', () => {
    expect(reasonsFor('unknown')).toEqual([])
    expect(reasonsFor(undefined)).toEqual([])
  })

  it('never offers the same preset twice, nor a blank one', () => {
    for (const presets of Object.values(REASONS)) {
      expect(new Set(presets).size).toBe(presets.length)
      presets.forEach((p) => expect(p.trim()).toBe(p))
      presets.forEach((p) => expect(p).not.toBe(''))
    }
  })

  it('fills an empty field', () => {
    expect(applyPreset('', 'duplicate record', MERGE)).toBe('duplicate record')
    expect(applyPreset('   ', 'duplicate record', MERGE)).toBe('duplicate record')
  })

  it('swaps one preset for another', () => {
    expect(applyPreset('duplicate record', 'same book, different edition', MERGE)).toBe('same book, different edition')
  })

  it('keeps words the librarian typed', () => {
    expect(applyPreset('two OL ids for one book', 'duplicate record', MERGE))
      .toBe('duplicate record: two OL ids for one book')
  })

  it('swaps the preset in front of typed words, keeping the words', () => {
    expect(applyPreset('duplicate record: two OL ids', 'same book, different edition', MERGE))
      .toBe('same book, different edition: two OL ids')
  })

  it('changes nothing when the chip is already the one in use', () => {
    expect(applyPreset('duplicate record', 'duplicate record', MERGE)).toBe('duplicate record')
    expect(applyPreset('duplicate record: two OL ids', 'duplicate record', MERGE)).toBe('duplicate record: two OL ids')
  })

  it('knows which preset the text starts from', () => {
    expect(presetIn('duplicate record', MERGE)).toBe('duplicate record')
    expect(presetIn('  duplicate record  ', MERGE)).toBe('duplicate record')
    expect(presetIn('duplicate record: two OL ids', MERGE)).toBe('duplicate record')
    expect(presetIn('duplicate records everywhere', MERGE)).toBeNull()
    expect(presetIn('', MERGE)).toBeNull()
  })
})
```

- [ ] **Step 3: Run it to verify it fails**

Run: `cd frontend && npx vitest run src/components/librarian/reasons.test.js`
Expected: FAIL — `Failed to resolve import "./reasons"`.

- [ ] **Step 4: Implement**

`frontend/src/components/librarian/reasons.js`:

```js
/**
 * One-click reasons, per action kind. A preset is a starting point, not a
 * category: it lands in the reason field as plain text the librarian can still
 * edit, and the server only ever sees that text. Lower case, like every other
 * control label here. Later roadmap items add their kinds to this table.
 */
export const REASONS = {
  move: ['wrong series', 'belongs to this series', 'part of a sub-series'],
  position: ['publication order', 'wrong number', "the author's reading order"],
  remove: ['not part of this series', 'standalone book', 'companion, not numbered'],
  merge: ['duplicate record', 'same book, different edition', 'translation of the same book'],
  split: ['different books grouped together', 'omnibus mixed in', 'sequel filed as an edition'],
  rename: ['official series name', 'fix spelling', 'drop the publisher imprint'],
  dissolve: ['not a real series', 'publisher imprint', 'marketing label'],
  cover: ['wrong language', 'low quality', 'wrong book'],
}

const SEPARATOR = ': '

export function reasonsFor(kind) {
  return REASONS[kind] ?? []
}

/** The preset ``value`` starts from — exactly it, or it followed by ": detail". */
export function presetIn(value, presets) {
  const typed = value.trim()
  return presets.find((p) => typed === p || typed.startsWith(`${p}${SEPARATOR}`)) ?? null
}

/**
 * The reason field's text after clicking ``preset``: it fills an empty field
 * and replaces another preset, but never throws away words the librarian
 * typed — those follow the preset as its detail.
 */
export function applyPreset(value, preset, presets) {
  const typed = value.trim()
  const current = presetIn(typed, presets)
  if (current === preset) return value
  const detail = current ? typed.slice(current.length + SEPARATOR.length) : typed
  return detail ? `${preset}${SEPARATOR}${detail}` : preset
}
```

(`current` exactly equal to the text leaves `typed.slice(...)` empty, so swapping one bare preset for another yields the bare new preset.)

- [ ] **Step 5: Run it to verify it passes**

Run: `cd frontend && npx vitest run src/components/librarian/reasons.test.js`
Expected: PASS — `Tests  9 passed (9)`.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/librarian/reasons.js frontend/src/components/librarian/reasons.test.js docs/librarian-ux-roadmap.md
git commit -m "feat(web): preset librarian reasons per action kind"
```

---

### Task 2: `ReasonField`

**Files:**
- Create: `frontend/src/components/librarian/ReasonField.jsx`
- Test: `frontend/src/components/librarian/ReasonField.test.jsx`

**Interfaces:**
- Consumes: `reasonsFor`, `presetIn`, `applyPreset` (Task 1).
- Produces: `ReasonField` (default export) — `<ReasonField kind={string} value={string} onChange={(text: string) => void} id="lib-reason" />`. Controlled. Renders `<label for={id}>Reason</label>`; when the kind has presets, a `role="group"` named `Quick reasons` of `<button type="button" aria-pressed>` chips (accessible name = the preset text); then `<textarea id={id} rows={2} className="input">`. Chips never submit a form. `id` defaults to `lib-reason`, so `getByLabelText('Reason')` keeps finding the textarea. Items 03, 06, 08, 14, 15 use this component for every reason they ask for.

- [ ] **Step 1: Write the failing test**

`frontend/src/components/librarian/ReasonField.test.jsx`:

```jsx
import { describe, it, expect, vi } from 'vitest'
import { useState } from 'react'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import ReasonField from './ReasonField'

function Harness({ kind = 'merge', initial = '', onSubmit = vi.fn() }) {
  const [value, setValue] = useState(initial)
  return (
    <form onSubmit={(e) => { e.preventDefault(); onSubmit(value) }}>
      <ReasonField kind={kind} value={value} onChange={setValue} />
    </form>
  )
}

describe('ReasonField', () => {
  it('labels the field Reason and offers the kind\'s presets', () => {
    render(<Harness kind="merge" />)
    expect(screen.getByLabelText('Reason').tagName).toBe('TEXTAREA')
    const chips = within(screen.getByRole('group', { name: 'Quick reasons' })).getAllByRole('button')
    expect(chips.map((c) => c.textContent)).toEqual(
      ['duplicate record', 'same book, different edition', 'translation of the same book'])
  })

  it('fills the field with a chip and marks that chip pressed', async () => {
    render(<Harness kind="merge" />)
    const chip = screen.getByRole('button', { name: 'duplicate record' })
    expect(chip).toHaveAttribute('aria-pressed', 'false')
    await userEvent.click(chip)
    expect(screen.getByLabelText('Reason')).toHaveValue('duplicate record')
    expect(chip).toHaveAttribute('aria-pressed', 'true')
    // Pressed shows in the text decoration as well as the colour.
    expect(chip).toHaveClass('underline')
    expect(screen.getByRole('button', { name: 'same book, different edition' })).toHaveAttribute('aria-pressed', 'false')
  })

  it('adds a chip to what was typed', async () => {
    render(<Harness kind="merge" />)
    await userEvent.type(screen.getByLabelText('Reason'), 'two OL ids for one book')
    await userEvent.click(screen.getByRole('button', { name: 'duplicate record' }))
    expect(screen.getByLabelText('Reason')).toHaveValue('duplicate record: two OL ids for one book')
  })

  it('still takes typing after a chip', async () => {
    render(<Harness kind="merge" />)
    await userEvent.click(screen.getByRole('button', { name: 'duplicate record' }))
    await userEvent.type(screen.getByLabelText('Reason'), ': second OL id')
    expect(screen.getByLabelText('Reason')).toHaveValue('duplicate record: second OL id')
    expect(screen.getByRole('button', { name: 'duplicate record' })).toHaveAttribute('aria-pressed', 'true')
  })

  it('unpresses a chip once its text is edited away', async () => {
    render(<Harness kind="merge" />)
    await userEvent.click(screen.getByRole('button', { name: 'duplicate record' }))
    await userEvent.clear(screen.getByLabelText('Reason'))
    await userEvent.type(screen.getByLabelText('Reason'), 'duplicate records everywhere')
    expect(screen.getByRole('button', { name: 'duplicate record' })).toHaveAttribute('aria-pressed', 'false')
  })

  it('never submits the form it sits in', async () => {
    const onSubmit = vi.fn()
    render(<Harness kind="merge" onSubmit={onSubmit} />)
    for (const chip of within(screen.getByRole('group', { name: 'Quick reasons' })).getAllByRole('button')) {
      expect(chip).toHaveAttribute('type', 'button')
      await userEvent.click(chip)
    }
    expect(onSubmit).not.toHaveBeenCalled()
  })

  it('renders only the field for a kind without presets', () => {
    render(<Harness kind="unknown" />)
    expect(screen.queryByRole('group', { name: 'Quick reasons' })).toBeNull()
    expect(screen.getByLabelText('Reason')).toBeInTheDocument()
  })

  it('takes another id when a page has two reason fields', () => {
    render(<ReasonField kind="move" value="" onChange={vi.fn()} id="batch-reason" />)
    expect(screen.getByLabelText('Reason')).toHaveAttribute('id', 'batch-reason')
  })
})
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd frontend && npx vitest run src/components/librarian/ReasonField.test.jsx`
Expected: FAIL — `Failed to resolve import "./ReasonField"`.

- [ ] **Step 3: Implement**

`frontend/src/components/librarian/ReasonField.jsx`:

```jsx
import { applyPreset, presetIn, reasonsFor } from './reasons'

/**
 * The reason every librarian fix requires: preset chips for the common cases
 * above a free-text field that stays the source of truth. A chip only writes
 * text into the field (keeping anything typed as its detail); the field stays
 * required, and the panel and the server still check it.
 *
 * Chips are toggle buttons, and look like the series page's book filter:
 * pressed is underlined as well as coloured, because colour never carries
 * meaning alone.
 */
function ReasonField({ kind, value, onChange, id = 'lib-reason' }) {
  const presets = reasonsFor(kind)
  const active = presetIn(value, presets)
  return (
    <div>
      <label className="label" htmlFor={id}>Reason</label>
      {presets.length > 0 && (
        <div role="group" aria-label="Quick reasons" className="flex flex-wrap gap-x-3 gap-y-1 mb-2">
          {presets.map((preset) => (
            <button
              key={preset}
              type="button"
              aria-pressed={active === preset}
              onClick={() => onChange(applyPreset(value, preset, presets))}
              className={`text-xs px-1 transition-colors duration-fast ${
                active === preset ? 'text-accent underline underline-offset-4' : 'text-ink-dim hover:text-accent'
              }`}
            >
              {preset}
            </button>
          ))}
        </div>
      )}
      <textarea id={id} rows={2} className="input" value={value} onChange={(e) => onChange(e.target.value)} />
    </div>
  )
}

export default ReasonField
```

- [ ] **Step 4: Run it to verify it passes**

Run: `cd frontend && npx vitest run src/components/librarian/ReasonField.test.jsx`
Expected: PASS — `Tests  8 passed (8)`.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/librarian/ReasonField.jsx frontend/src/components/librarian/ReasonField.test.jsx
git commit -m "feat(web): ReasonField, the reason textarea with preset chips"
```

---

### Task 3: The fix panel uses `ReasonField`

**Files:**
- Modify: `frontend/src/components/LibrarianPanel.jsx:230-234` (the reason `<div>`)
- Test: `frontend/src/components/LibrarianPanel.test.jsx`

**Interfaces:**
- Consumes: `ReasonField` (Task 2); the panel's existing `fields.reason`, `set('reason')` (which also clears a stale refusal) and `ready()`.
- Produces: every `LibrarianPanel` action (`move, position, remove, merge, split, rename, dissolve`) shows its presets above the reason field. Request bodies are unchanged: `reason` is the field's trimmed text.

- [ ] **Step 1: Write the failing tests**

Append inside `describe('LibrarianPanel', …)` in `frontend/src/components/LibrarianPanel.test.jsx`:

```jsx
  it('sends a one-click reason as the text it shows', async () => {
    client.post.mockResolvedValue({ data: CORRECTION })
    const onDone = renderPanel({ kind: 'dissolve' })
    const submit = screen.getByRole('button', { name: 'Dissolve' })
    expect(submit).toBeDisabled()
    await userEvent.click(screen.getByRole('button', { name: 'publisher imprint' }))
    expect(submit).toBeEnabled()
    await userEvent.click(submit)
    await waitFor(() => expect(onDone).toHaveBeenCalledWith(CORRECTION))
    expect(client.post).toHaveBeenCalledWith('/librarian/series/s1/dissolve', { reason: 'publisher imprint' })
  })

  it('offers the presets of the action it is doing', () => {
    renderPanel({ kind: 'remove', work: BOOK })
    const group = screen.getByRole('group', { name: 'Quick reasons' })
    expect(within(group).getByRole('button', { name: 'not part of this series' })).toBeInTheDocument()
    expect(within(group).queryByRole('button', { name: 'duplicate record' })).toBeNull()
  })

  it('still starts with focus in a field, not on a chip', () => {
    renderPanel({ kind: 'dissolve' })
    expect(document.activeElement).toBe(screen.getByLabelText('Reason'))
  })

  it('a chip clears a refusal like typing does', async () => {
    client.post.mockRejectedValueOnce({ response: { status: 422, data: { detail: 'It is already called Dune.' } } })
    renderPanel({ kind: 'rename' })
    await userEvent.type(screen.getByLabelText('New name'), 'Dune')
    await userEvent.click(screen.getByRole('button', { name: 'fix spelling' }))
    await userEvent.click(screen.getByRole('button', { name: 'Rename' }))
    expect(await screen.findByText('It is already called Dune.')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'official series name' }))
    expect(screen.queryByText('It is already called Dune.')).toBeNull()
  })
```

and add `within` to the testing-library import at the top:

```jsx
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd frontend && npx vitest run src/components/LibrarianPanel.test.jsx`
Expected: FAIL — the three chip tests (`Unable to find role="button" and name "publisher imprint"`, no `Quick reasons` group); `still starts with focus in a field` passes already. The existing tests pass.

- [ ] **Step 3: Implement**

In `frontend/src/components/LibrarianPanel.jsx`:

1. Add the import after `import { errorMessage } from '../api/errors'`:

```jsx
import ReasonField from './librarian/ReasonField'
```

2. Replace

```jsx
            <div>
              <label className="label" htmlFor="lib-reason">Reason</label>
              <textarea id="lib-reason" rows={2} className="input" value={fields.reason}
                        onChange={(e) => set('reason')(e.target.value)} />
            </div>
```

with

```jsx
            <ReasonField kind={kind} value={fields.reason} onChange={set('reason')} />
```

The open-focus effect (`querySelector('input, textarea')`) skips the chips because they are buttons, so a dissolve or remove still opens with the caret in the reason field. The focus trap's selector already includes `button`, so Tab cycles through the chips inside the dialog.

- [ ] **Step 4: Run to verify they pass**

Run: `cd frontend && npx vitest run src/components/LibrarianPanel.test.jsx`
Expected: PASS — all `LibrarianPanel` tests, including `keeps Tab inside the dialog and gives focus back on close`.

- [ ] **Step 5: Run the whole frontend suite**

Run: `cd frontend && npm test`
Expected: PASS — `Series.test.jsx` still finds `getByLabelText('Reason')` and types into it.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/LibrarianPanel.jsx frontend/src/components/LibrarianPanel.test.jsx
git commit -m "feat(web): quick reasons in every librarian fix panel"
```

---

### Task 4: End-to-end — a fix with a one-click reason

**Files:**
- Modify: `frontend/e2e/librarian.spec.js`

**Interfaces:**
- Consumes: the chips (Task 3); `registerViaUi`, `grantLibrarian`, `openFirstSearchResult` from `e2e/helpers.js`; the fix log at `/librarian` (v1).
- Produces: nothing.

- [ ] **Step 1: Add the scenario**

Append to `frontend/e2e/librarian.spec.js`:

```js
// A preset reason is one click, lands in the log as its text, and the fix
// undoes from the log. Needs the full stack and live Open Library.
test('a librarian gives a reason with one click', async ({ page }) => {
  const user = await registerViaUi(page)
  grantLibrarian(user)
  await page.reload() // useMe refreshes the stored user, now a librarian

  await openFirstSearchResult(page, 'the lathe of heaven')
  // By text, not role: [edit] is a link before roadmap item 01 and a button after it.
  await page.getByText('[edit]', { exact: true }).click()
  const books = page.getByRole('list', { name: 'Books in this series' })
  const title = await books.getByRole('heading').first().textContent()

  await books.getByRole('button', { name: `move ${title}`, exact: true }).click()
  const saga = `E2E Reasons ${Date.now()}`
  await page.getByLabel('Find a series').fill(saga)
  await page.getByRole('radio', { name: `new series: ${saga}` }).check()
  const chip = page.getByRole('group', { name: 'Quick reasons' }).getByRole('button', { name: 'belongs to this series' })
  await chip.click()
  await expect(chip).toHaveAttribute('aria-pressed', 'true')
  await expect(page.getByLabel('Reason')).toHaveValue('belongs to this series')
  await page.getByRole('button', { name: 'Move', exact: true }).click()
  await expect(page.getByRole('group', { name: 'Librarian fix result' })).toBeVisible()

  await page.goto('/librarian')
  const table = page.getByRole('table', { name: 'Catalog fixes' })
  await expect(table.getByText('belongs to this series').first()).toBeVisible()
  await table.getByRole('button', { name: `undo ${title}` }).first().click()
  await expect(table.getByText('undone').first()).toBeVisible()
})
```

- [ ] **Step 2: Run it**

Bring the stack up in another terminal (`docker compose up --build`), then:

Run: `cd frontend && npx playwright test e2e/librarian.spec.js`
Expected: every scenario in the file passes (`2 passed` before item 01 lands, `3 passed` after).

`DataTable` renders its `caption` prop as an `sr-only` `<caption>`, which is the table's accessible name, so `getByRole('table', { name: 'Catalog fixes' })` finds the log. `.first()` is there because the e2e database keeps earlier runs' fixes; the log is newest first.

- [ ] **Step 3: Commit**

```bash
git add frontend/e2e/librarian.spec.js
git commit -m "test(e2e): a librarian fix with a one-click reason, undone from the log"
```

---

### Task 5: Docs and tracker

**Files:**
- Modify: `docs/librarian-ux-roadmap.md`, `ROADMAP.md`, `CLAUDE.md`

**Interfaces:**
- Consumes: everything above.
- Produces: nothing.

- [ ] **Step 1: `CLAUDE.md`**

In the Design system section, after the bullet that starts ``- **Reuse the component classes**``, add:

```markdown
- **Librarian components** live in `components/librarian/` (`LibrarianPanel.jsx` itself stays in `components/`). Any librarian surface that asks for a reason uses `ReasonField` (`<ReasonField kind value onChange />`): preset chips from `components/librarian/reasons.js` above a required textarea. A chip only writes text (keeping typed words as its detail); add a new action kind's presets to `REASONS`.
```

(If item 01 or 10 already added a `components/librarian/` bullet, merge this sentence into it instead.)

- [ ] **Step 2: `ROADMAP.md`**

In the Phase 5 **Librarian tools** row, replace

```
logged in `catalog_corrections`
```

with

```
logged in `catalog_corrections` with a required reason (preset chips per action, `components/librarian/reasons.js`)
```

(If an earlier roadmap item already rewrote that cell, make the same change to the cell as it stands.)

- [ ] **Step 3: Run the full frontend suite once more**

Run: `cd frontend && npm test`
Expected: PASS — all test files.

- [ ] **Step 4: Commit and open the PR**

```bash
git add CLAUDE.md ROADMAP.md
git commit -m "docs: quick librarian reasons"
git push -u origin feat/librarian-lx02-quick-reasons
gh pr create --base main --title "feat(web): quick librarian reasons (LX02)" \
  --body "Roadmap item 02 (docs/librarian-ux-roadmap.md). Preset chips per action kind above the reason field (components/librarian/ReasonField.jsx, presets in reasons.js). A chip fills the field and keeps typed words; the field stays required; request bodies are unchanged."
```

- [ ] **Step 5: Tick the tracker when it merges**

After the PR merges, change the tracker row in `docs/librarian-ux-roadmap.md` to

```
| 02 | Quick reasons | [plan](superpowers/plans/2026-09-29-lx02-quick-reasons.md) | — | ✅ | feat/librarian-lx02-quick-reasons | <merge date, YYYY-MM-DD> | #<PR number from `gh pr view --json number -q .number`> |
```

tick the `Roadmap item` checkbox at the top of this plan, and add a dated line under **Notes**: "02: `ReasonField` takes `kind`, `value`, `onChange`, `id` (default `lib-reason`); a new kind adds its presets to `REASONS` in `components/librarian/reasons.js`; a chip with typed text yields `<preset>: <text>`."

```bash
git add docs/librarian-ux-roadmap.md docs/superpowers/plans/2026-09-29-lx02-quick-reasons.md
git commit -m "docs: LX02 done"
```
