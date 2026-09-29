# LX10 · Keyboard Shortcuts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

- [ ] **Roadmap item:** 10 — tick in docs/librarian-ux-roadmap.md when merged

**Goal:** On the series page a librarian can do the common fixes without the mouse: `j`/`k` move a row cursor, `m` move, `p` position, `r` remove, `g` merge into, `c` cover, `x` select for batch, `a` add a book, `e` toggle edit, `?` shows the list — and no key ever fires while they are typing in a field.

**Architecture:** A shortcut never does anything its visible control could not: each key *presses the control that advertises it* in `aria-keyshortcuts` (row actions, the batch checkbox, `add a book`, the `[edit]`/`[done]` toggle). One window `keydown` listener, `useLibrarianShortcuts`, finds that control — inside the row that holds focus for row keys, anywhere on the page for page keys — and calls `.click()`. The row cursor *is* DOM focus: each book row is `tabIndex={-1}` with `data-work-row`, and `j`/`k` move focus between rows, so screen readers announce the row and the global `:focus-visible` outline shows it. Where a control is absent (a reader, a singleton's `position`, a disabled button, 06 not landed yet) the key does nothing. `?` opens `ShortcutHelp`, a small modal listing `SHORTCUTS`. Frontend only.

**Tech Stack:** React 18, React Router 6.30, Zustand 4.5, Tailwind tokens, Vitest 1.6 + React Testing Library + user-event 14, Playwright.

**Spec:** docs/librarian-ux-roadmap.md §10 · Keyboard shortcuts (and "Shared names" → Frontend).

**Depends on (must be merged first — check the tracker):**
- **01 Sticky edit mode** — `frontend/src/store/librarian.js` (`useLibrarianStore`, default export, `{ editMode, setEditMode }`, persist key `margin-librarian`). In `pages/Series.jsx`: `isLibrarian`, `editing = isLibrarian && editMode`, and the header toggle is a `<button type="button">` named `[edit]` / `[done]` calling `setEditMode(!editing)`.
- **03 Add a book** — `pages/Series.jsx` renders a header button named **`add a book`** (edit mode, real series only) that opens the librarian panel with a work search (`WorkPicker` from `components/librarian/pickers.jsx`, with a `label` prop). This plan only adds `aria-keyshortcuts="a"` to that button; it does not care which `action.kind` 03 chose.
- **08 Batch actions** — in edit mode each `BookRow` renders an `<input type="checkbox">` that selects the row for the batch bar. This plan only adds `aria-keyshortcuts="x"` to it.
- **06 Cover picker is optional.** If it has landed, `BookRow`'s actions include one named **`cover`**, and `c` presses it. If it has not, `c` is still listed and mapped, and simply finds no control until 06 lands (Task 4 Step 1 tells you which case you are in).

**Base:** `main` after 01, 03 and 08 have merged.

## Global Constraints

- Keys, verbatim: `j`/`k` move a row cursor, `m` move, `p` position, `r` remove, `g` merge into, `c` cover, `x` select for batch, `a` add a book, `e` toggle edit, `?` shows the list. Series page, edit mode. Never fires while typing in a field. Frontend only. (roadmap §10)
- `e` and `?` also work out of edit mode (`e` is how a librarian gets *into* it); every other key needs edit mode.
- Readers never get shortcuts: the listener is not installed unless `user.is_librarian`.
- No shortcut with Ctrl, Meta (Cmd) or Alt held — `Cmd+R`, `Ctrl+C`, `Alt+←` stay the browser's. Shift is only accepted for `?`; `J`, `M` … do nothing.
- While any `aria-modal="true"` dialog is open (fix panel, new thread, the shortcut list) the page's shortcuts are off; the dialog owns the keyboard.
- A handled key calls `preventDefault()` so its character never lands in a field the key just opened and focused.
- Shared names used as fixed by the roadmap: `store/librarian.js` `{ editMode, setEditMode }`; new librarian components in `components/librarian/`; `LibrarianPanel.jsx` stays in `components/`.
- Design tokens only; no new radii, shadows, font sizes or durations; every glyph `aria-hidden` (key names are text, not glyphs); mono only; §36 test.
- Branch `feat/librarian-lx10-keyboard-shortcuts` from `main`; one commit per task; PR to `main`.

## Review Focus

1. **Browser and OS chords** — `Cmd+R` (reload) on a focused row must not open *remove*; `Ctrl+C` must not open *cover*; `Cmd+E`/`Ctrl+E` must not leave edit mode — Task 1 `ignores anything with Ctrl, Meta or Alt held`, Task 2 `leaves browser chords alone`.
2. **Typing anywhere** — the navbar search box, a panel's search field, the reason textarea, a number input, a contenteditable — must type the letter, not act on it — Task 1 `knows a field that takes text`, Task 2 `types into a field instead of acting`, Task 4 `a key typed in the panel is only typed`.
3. **The key that opens a panel must not also type into it** — `m` opens Move and focuses *Find a series*; that field must stay empty — Task 4 `m opens Move for the row under the cursor, and types nothing into it`.
4. **`?` inside the open list** closes it and must not reopen it in the same keystroke (React flushes the close before the window listener runs) — Task 3 `closes on ? and says it handled it`, Task 4 `? opens the list and ? closes it for good`.
5. **A reader with `editMode: true` stored** (shared browser) presses `e`, `j`, `m`, `?`: nothing happens and nothing is focused — Task 4 `does nothing for a reader, even with edit mode stored`.

---

## File Structure

**Create**
- `frontend/src/components/librarian/shortcuts.js` — `SHORTCUTS`, `ROW_ACTION_KEYS`, `isTypingTarget`, `shortcutKey`, `scopeOf` (pure).
- `frontend/src/components/librarian/shortcuts.test.js`
- `frontend/src/components/librarian/useLibrarianShortcuts.js` — the window `keydown` listener.
- `frontend/src/components/librarian/useLibrarianShortcuts.test.jsx` — against a small harness page.
- `frontend/src/components/librarian/ShortcutHelp.jsx` — the `?` list.
- `frontend/src/components/librarian/ShortcutHelp.test.jsx`
- `frontend/src/pages/Series.shortcuts.test.jsx` — the real series page, driven from the keyboard.

**Modify**
- `frontend/src/pages/Series.jsx` — refs, `data-work-row` + `tabIndex` on rows, `aria-keyshortcuts` on controls, `shortcuts` button, `ShortcutHelp`.
- `frontend/e2e/librarian.spec.js` — keyboard scenario.
- Docs: `docs/librarian-ux-roadmap.md`, `ROADMAP.md`, `CLAUDE.md`.

---

### Task 1: The shortcut table and the "is this typing?" rules

**Files:**
- Create: `frontend/src/components/librarian/shortcuts.js`
- Test: `frontend/src/components/librarian/shortcuts.test.js`
- Modify: `docs/librarian-ux-roadmap.md` (tracker row → in progress)

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `SHORTCUTS: { key: string, scope: 'nav' | 'row' | 'page', does: string }[]` — in display order; `ShortcutHelp` renders it.
  - `ROW_ACTION_KEYS: { [rowActionName: string]: string }` — `{ move: 'm', position: 'p', remove: 'r', 'merge into…': 'g', cover: 'c' }`; keys are `BookRow`'s visible action names. A later item that adds a row action with a shortcut adds it here.
  - `isTypingTarget(el: EventTarget | null) -> boolean`
  - `shortcutKey(event: KeyboardEvent-like) -> string | null` — the shortcut `event.key` names, or `null` when it must be ignored.
  - `scopeOf(key: string) -> 'nav' | 'row' | 'page' | null`

- [ ] **Step 1: Branch and mark the item in progress**

```bash
git fetch origin
git switch -c feat/librarian-lx10-keyboard-shortcuts origin/main
```

In `docs/librarian-ux-roadmap.md`, change the tracker row

```
| 10 | Keyboard shortcuts | [plan](superpowers/plans/2026-09-29-lx10-keyboard-shortcuts.md) | 01, 03, 08 | ⬜ | | | |
```

to

```
| 10 | Keyboard shortcuts | [plan](superpowers/plans/2026-09-29-lx10-keyboard-shortcuts.md) | 01, 03, 08 | 🟡 | feat/librarian-lx10-keyboard-shortcuts | | |
```

- [ ] **Step 2: Write the failing test**

`frontend/src/components/librarian/shortcuts.test.js`:

```js
import { describe, it, expect, afterEach } from 'vitest'
import { ROW_ACTION_KEYS, SHORTCUTS, isTypingTarget, scopeOf, shortcutKey } from './shortcuts'

const el = (html) => {
  const host = document.createElement('div')
  host.innerHTML = html
  document.body.appendChild(host)
  return host.firstElementChild
}
afterEach(() => { document.body.innerHTML = '' })

describe('shortcut table', () => {
  it('lists exactly the roadmap keys, once each', () => {
    expect(SHORTCUTS.map((s) => s.key)).toEqual(['j', 'k', 'm', 'p', 'r', 'g', 'c', 'x', 'a', 'e', '?'])
    SHORTCUTS.forEach((s) => expect(s.does).toMatch(/\S/))
  })

  it('maps each row action to its key', () => {
    expect(ROW_ACTION_KEYS).toEqual({ move: 'm', position: 'p', remove: 'r', 'merge into…': 'g', cover: 'c' })
    Object.values(ROW_ACTION_KEYS).forEach((key) => expect(scopeOf(key)).toBe('row'))
  })

  it('scopes keys', () => {
    expect(scopeOf('j')).toBe('nav')
    expect(scopeOf('x')).toBe('row')
    expect(scopeOf('a')).toBe('page')
    expect(scopeOf('e')).toBe('page')
    expect(scopeOf('q')).toBeNull()
  })
})

describe('isTypingTarget', () => {
  it('knows a field that takes text', () => {
    expect(isTypingTarget(el('<textarea></textarea>'))).toBe(true)
    expect(isTypingTarget(el('<input>'))).toBe(true)
    expect(isTypingTarget(el('<input type="search">'))).toBe(true)
    expect(isTypingTarget(el('<input type="number">'))).toBe(true)
    expect(isTypingTarget(el('<select><option>a</option></select>'))).toBe(true)
    expect(isTypingTarget(el('<div contenteditable="true"><span>x</span></div>'))).toBe(true)
    expect(isTypingTarget(el('<div contenteditable="true"><span>x</span></div>').firstElementChild)).toBe(true)
  })

  it('does not count controls that take no text', () => {
    expect(isTypingTarget(el('<input type="checkbox">'))).toBe(false)
    expect(isTypingTarget(el('<input type="radio">'))).toBe(false)
    expect(isTypingTarget(el('<button>move</button>'))).toBe(false)
    expect(isTypingTarget(el('<li tabindex="-1">row</li>'))).toBe(false)
    expect(isTypingTarget(document.body)).toBe(false)
    expect(isTypingTarget(document)).toBe(false)
    expect(isTypingTarget(null)).toBe(false)
  })
})

describe('shortcutKey', () => {
  const key = (k, extra = {}) => ({ key: k, target: document.body, ...extra })

  it('names a shortcut pressed on the page', () => {
    expect(shortcutKey(key('j'))).toBe('j')
    expect(shortcutKey(key('?', { shiftKey: true }))).toBe('?')
  })

  it('ignores anything with Ctrl, Meta or Alt held', () => {
    expect(shortcutKey(key('r', { metaKey: true }))).toBeNull()
    expect(shortcutKey(key('c', { ctrlKey: true }))).toBeNull()
    expect(shortcutKey(key('e', { altKey: true }))).toBeNull()
  })

  it('ignores capitals, other keys, IME composition and handled events', () => {
    expect(shortcutKey(key('M', { shiftKey: true }))).toBeNull()
    expect(shortcutKey(key('q'))).toBeNull()
    expect(shortcutKey(key('Enter'))).toBeNull()
    expect(shortcutKey(key('m', { isComposing: true }))).toBeNull()
    expect(shortcutKey(key('m', { defaultPrevented: true }))).toBeNull()
  })

  it('ignores keys typed into a field', () => {
    expect(shortcutKey(key('m', { target: el('<textarea></textarea>') }))).toBeNull()
    expect(shortcutKey(key('x', { target: el('<input type="checkbox">') }))).toBe('x')
  })
})
```

- [ ] **Step 3: Run it to verify it fails**

Run: `cd frontend && npx vitest run src/components/librarian/shortcuts.test.js`
Expected: FAIL — `Failed to resolve import "./shortcuts"`.

- [ ] **Step 4: Implement**

`frontend/src/components/librarian/shortcuts.js`:

```js
/**
 * Librarian keyboard shortcuts on the series page.
 *
 * A shortcut never does anything its visible control could not: each key
 * presses the control that carries it in `aria-keyshortcuts` (a row action,
 * the batch checkbox, `add a book`, the edit toggle). Where that control is
 * absent — a reader, a singleton's missing `position`, a disabled button —
 * the key does nothing. `nav` keys move the row cursor (DOM focus), `row`
 * keys act on the row that holds focus, `page` keys on the page.
 */
export const SHORTCUTS = [
  { key: 'j', scope: 'nav', does: 'next book' },
  { key: 'k', scope: 'nav', does: 'previous book' },
  { key: 'm', scope: 'row', does: 'move' },
  { key: 'p', scope: 'row', does: 'set position' },
  { key: 'r', scope: 'row', does: 'remove from series' },
  { key: 'g', scope: 'row', does: 'merge into…' },
  { key: 'c', scope: 'row', does: 'choose a cover' },
  { key: 'x', scope: 'row', does: 'select for a batch' },
  { key: 'a', scope: 'page', does: 'add a book' },
  { key: 'e', scope: 'page', does: 'enter or leave edit mode' },
  { key: '?', scope: 'page', does: 'show these shortcuts' },
]

/** `BookRow`'s visible action names → the key that presses them. */
export const ROW_ACTION_KEYS = { move: 'm', position: 'p', remove: 'r', 'merge into…': 'g', cover: 'c' }

// Inputs that never take typed characters, so a letter on them is a shortcut.
const NON_TEXT_INPUTS = new Set(['checkbox', 'radio', 'button', 'submit', 'reset', 'range', 'color', 'file', 'image'])

export function isTypingTarget(el) {
  if (!el || typeof el.closest !== 'function') return false
  if (el.closest('[contenteditable=""], [contenteditable="true"]')) return true
  if (el.tagName === 'TEXTAREA' || el.tagName === 'SELECT') return true
  if (el.tagName === 'INPUT') return !NON_TEXT_INPUTS.has((el.getAttribute('type') || 'text').toLowerCase())
  return false
}

export function shortcutKey(event) {
  if (event.defaultPrevented || event.isComposing) return null
  // Chords belong to the browser and the OS: Cmd+R is reload, not "remove".
  if (event.ctrlKey || event.metaKey || event.altKey) return null
  if (isTypingTarget(event.target)) return null
  return SHORTCUTS.some((s) => s.key === event.key) ? event.key : null
}

export function scopeOf(key) {
  return SHORTCUTS.find((s) => s.key === key)?.scope ?? null
}
```

- [ ] **Step 5: Run it to verify it passes**

Run: `cd frontend && npx vitest run src/components/librarian/shortcuts.test.js`
Expected: PASS — `Tests  9 passed (9)`.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/librarian/shortcuts.js frontend/src/components/librarian/shortcuts.test.js docs/librarian-ux-roadmap.md
git commit -m "feat(web): librarian shortcut table and typing guard"
```

---

### Task 2: `useLibrarianShortcuts`

**Files:**
- Create: `frontend/src/components/librarian/useLibrarianShortcuts.js`
- Test: `frontend/src/components/librarian/useLibrarianShortcuts.test.jsx`

**Interfaces:**
- Consumes: `shortcutKey`, `scopeOf` (Task 1).
- Produces: `useLibrarianShortcuts({ enabled: boolean, editing: boolean, pageRef: RefObject<HTMLElement>, listRef: RefObject<HTMLElement>, onHelp: () => void }) -> void` (default export). While `enabled`, one `window` `keydown` listener:
  - does nothing while any `[aria-modal="true"]` is in the document;
  - `?` → `onHelp()`;
  - `page` keys (`a`, `e`) → click the first `[aria-keyshortcuts="<key>"]` inside `pageRef.current`, in or out of edit mode;
  - when `editing`: `j`/`k` focus the next / previous `[data-work-row]` inside `listRef.current` (from no row: `j` → first, `k` → last; clamped at the ends, no wrap); `row` keys click the `[aria-keyshortcuts="<key>"]` inside the row that contains `document.activeElement`, or nothing when focus is in no row;
  - never clicks a `disabled` control; calls `preventDefault()` only when it handled the key.

- [ ] **Step 1: Write the failing test**

`frontend/src/components/librarian/useLibrarianShortcuts.test.jsx`:

```jsx
import { describe, it, expect, vi } from 'vitest'
import { useRef, useState } from 'react'
import { fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import useLibrarianShortcuts from './useLibrarianShortcuts'

// A page shaped like the series page: page controls, then rows that each own
// their actions. Row "c" has no position (like a singleton) and every remove
// is disabled.
function Harness({ enabled = true, editing = true, onHelp = vi.fn(), dialog = false }) {
  const pageRef = useRef(null)
  const listRef = useRef(null)
  const [log, setLog] = useState([])
  const hit = (what) => setLog((l) => [...l, what])
  useLibrarianShortcuts({ enabled, editing, pageRef, listRef, onHelp })
  return (
    <main ref={pageRef}>
      <input type="search" aria-label="Search books" />
      <button type="button" aria-keyshortcuts="e" onClick={() => hit('edit')}>[edit]</button>
      <button type="button" aria-keyshortcuts="a" onClick={() => hit('add')}>add a book</button>
      <ul ref={listRef} aria-label="Books">
        {['a', 'b', 'c'].map((id) => (
          <li key={id} data-work-row tabIndex={-1} aria-label={`row ${id}`}>
            <button type="button" aria-keyshortcuts="m" onClick={() => hit(`move ${id}`)}>move {id}</button>
            {id !== 'c' && (
              <button type="button" aria-keyshortcuts="p" onClick={() => hit(`position ${id}`)}>position {id}</button>
            )}
            <button type="button" disabled aria-keyshortcuts="r" onClick={() => hit(`remove ${id}`)}>remove {id}</button>
            <input type="checkbox" aria-label={`select ${id}`} aria-keyshortcuts="x" />
          </li>
        ))}
      </ul>
      {dialog && <div role="dialog" aria-modal="true" aria-label="A fix"><button type="button">inside</button></div>}
      <p data-testid="log">{log.join(',')}</p>
    </main>
  )
}

const row = (id) => screen.getByRole('listitem', { name: `row ${id}` })
const log = () => screen.getByTestId('log').textContent

describe('useLibrarianShortcuts', () => {
  it('moves the row cursor with j and k, stopping at the ends', async () => {
    render(<Harness />)
    await userEvent.keyboard('j')
    expect(row('a')).toHaveFocus()
    await userEvent.keyboard('jjj')
    expect(row('c')).toHaveFocus()
    await userEvent.keyboard('k')
    expect(row('b')).toHaveFocus()
    await userEvent.keyboard('kkk')
    expect(row('a')).toHaveFocus()
  })

  it('starts k from the last row', async () => {
    render(<Harness />)
    await userEvent.keyboard('k')
    expect(row('c')).toHaveFocus()
  })

  it('acts on the row under the cursor', async () => {
    render(<Harness />)
    await userEvent.keyboard('jjm')
    expect(log()).toBe('move b')
  })

  it('acts on the row whose button has focus, too', async () => {
    render(<Harness />)
    screen.getByRole('button', { name: 'move c' }).focus()
    await userEvent.keyboard('m')
    expect(log()).toBe('move c')
  })

  it('does nothing for a row key with no row under the cursor', async () => {
    render(<Harness />)
    await userEvent.keyboard('m')
    expect(log()).toBe('')
  })

  it('does nothing when the row has no such action, or it is disabled', async () => {
    render(<Harness />)
    await userEvent.keyboard('kp')
    await userEvent.keyboard('r')
    expect(log()).toBe('')
  })

  it('toggles the row checkbox with x', async () => {
    render(<Harness />)
    await userEvent.keyboard('jx')
    expect(screen.getByRole('checkbox', { name: 'select a' })).toBeChecked()
    await userEvent.keyboard('x')
    expect(screen.getByRole('checkbox', { name: 'select a' })).not.toBeChecked()
  })

  it('presses page controls, even out of edit mode', async () => {
    render(<Harness editing={false} />)
    await userEvent.keyboard('ea')
    expect(log()).toBe('edit,add')
  })

  it('needs edit mode for the cursor and row keys', async () => {
    render(<Harness editing={false} />)
    await userEvent.keyboard('jm')
    expect(document.body).toHaveFocus()
    expect(log()).toBe('')
  })

  it('asks for the list on ?', () => {
    const onHelp = vi.fn()
    render(<Harness onHelp={onHelp} />)
    fireEvent.keyDown(document.body, { key: '?', shiftKey: true })
    expect(onHelp).toHaveBeenCalledTimes(1)
  })

  it('types into a field instead of acting', async () => {
    render(<Harness />)
    await userEvent.type(screen.getByRole('searchbox', { name: 'Search books' }), 'jkmea')
    expect(screen.getByRole('searchbox', { name: 'Search books' })).toHaveValue('jkmea')
    expect(log()).toBe('')
    expect(screen.getByRole('searchbox', { name: 'Search books' })).toHaveFocus()
  })

  it('leaves browser chords alone', async () => {
    render(<Harness />)
    await userEvent.keyboard('j')
    for (const mod of [{ metaKey: true }, { ctrlKey: true }, { altKey: true }]) {
      expect(fireEvent.keyDown(row('a'), { key: 'm', ...mod })).toBe(true) // not prevented
      fireEvent.keyDown(row('a'), { key: 'e', ...mod })
    }
    expect(log()).toBe('')
  })

  it('handles only what it handles', async () => {
    render(<Harness />)
    expect(fireEvent.keyDown(document.body, { key: 'j' })).toBe(false) // prevented
    expect(fireEvent.keyDown(document.body, { key: 'q' })).toBe(true)
    expect(fireEvent.keyDown(document.body, { key: 'M', shiftKey: true })).toBe(true)
  })

  it('stays out of the way while a dialog is open', async () => {
    const onHelp = vi.fn()
    render(<Harness dialog onHelp={onHelp} />)
    await userEvent.keyboard('jmea')
    fireEvent.keyDown(document.body, { key: '?', shiftKey: true })
    expect(log()).toBe('')
    expect(onHelp).not.toHaveBeenCalled()
  })

  it('does nothing at all when not enabled', async () => {
    const onHelp = vi.fn()
    render(<Harness enabled={false} onHelp={onHelp} />)
    await userEvent.keyboard('jmea')
    fireEvent.keyDown(document.body, { key: '?', shiftKey: true })
    expect(log()).toBe('')
    expect(onHelp).not.toHaveBeenCalled()
    expect(document.body).toHaveFocus()
  })

  it('stops listening when unmounted', async () => {
    const onHelp = vi.fn()
    const { unmount } = render(<Harness onHelp={onHelp} />)
    unmount()
    fireEvent.keyDown(document.body, { key: '?', shiftKey: true })
    expect(onHelp).not.toHaveBeenCalled()
  })
})
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd frontend && npx vitest run src/components/librarian/useLibrarianShortcuts.test.jsx`
Expected: FAIL — `Failed to resolve import "./useLibrarianShortcuts"`.

- [ ] **Step 3: Implement**

`frontend/src/components/librarian/useLibrarianShortcuts.js`:

```js
import { useEffect, useRef } from 'react'
import { scopeOf, shortcutKey } from './shortcuts'

/**
 * The series page's librarian shortcuts (see `shortcuts.js`). One window
 * listener; the row cursor is DOM focus on a `[data-work-row]`, so assistive
 * tech announces the row and `:focus-visible` draws it.
 *
 * Every handled key is `preventDefault`ed: `m` opens a panel that focuses a
 * text field, and the `m` must not land in it.
 */
export default function useLibrarianShortcuts({ enabled, editing, pageRef, listRef, onHelp }) {
  const help = useRef(onHelp)
  help.current = onHelp

  useEffect(() => {
    if (!enabled) return undefined
    const onKeyDown = (event) => {
      const key = shortcutKey(event)
      if (!key) return
      // An open dialog (a fix panel, a new thread, the shortcut list) owns the keyboard.
      if (document.querySelector('[aria-modal="true"]')) return
      const scope = scopeOf(key)

      if (key === '?') {
        event.preventDefault()
        help.current?.()
        return
      }
      if (scope === 'page') {
        press(event, pageRef.current?.querySelector(`[aria-keyshortcuts="${key}"]`))
        return
      }
      if (!editing) return

      const rows = [...(listRef.current?.querySelectorAll('[data-work-row]') ?? [])]
      const at = rows.findIndex((row) => row.contains(document.activeElement))
      if (scope === 'nav') {
        if (!rows.length) return
        const next = key === 'j'
          ? (at === -1 ? 0 : Math.min(at + 1, rows.length - 1))
          : (at === -1 ? rows.length - 1 : Math.max(at - 1, 0))
        event.preventDefault()
        rows[next].focus()
        return
      }
      if (at !== -1) press(event, rows[at].querySelector(`[aria-keyshortcuts="${key}"]`))
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [enabled, editing, pageRef, listRef])
}

/** Press ``control`` as a click would; nothing when it is absent or disabled. */
function press(event, control) {
  if (!control || control.disabled) return
  event.preventDefault()
  control.click()
}
```

- [ ] **Step 4: Run it to verify it passes**

Run: `cd frontend && npx vitest run src/components/librarian/useLibrarianShortcuts.test.jsx`
Expected: PASS — `Tests  16 passed (16)`.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/librarian/useLibrarianShortcuts.js frontend/src/components/librarian/useLibrarianShortcuts.test.jsx
git commit -m "feat(web): useLibrarianShortcuts presses the control a key names"
```

---

### Task 3: `ShortcutHelp`, the `?` list

**Files:**
- Create: `frontend/src/components/librarian/ShortcutHelp.jsx`
- Test: `frontend/src/components/librarian/ShortcutHelp.test.jsx`

**Interfaces:**
- Consumes: `SHORTCUTS` (Task 1).
- Produces: `ShortcutHelp` (default export) — `<ShortcutHelp onClose={() => void} />`. A modal `role="dialog" aria-modal="true"` named `Keyboard shortcuts` (via `aria-labelledby`), styled like `LibrarianPanel` (`fixed inset-0 bg-bg/90` backdrop, `.float` box). Focus goes to its `Close` button on open and back to the opener on unmount; Tab stays on `Close` (the only control); `Escape` and `?` call `onClose` and `preventDefault()` the key, so the page's `?` listener does not reopen it.

- [ ] **Step 1: Write the failing test**

`frontend/src/components/librarian/ShortcutHelp.test.jsx`:

```jsx
import { describe, it, expect, vi } from 'vitest'
import { fireEvent, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import ShortcutHelp from './ShortcutHelp'
import { SHORTCUTS } from './shortcuts'

describe('ShortcutHelp', () => {
  it('lists every shortcut with what it does', () => {
    render(<ShortcutHelp onClose={vi.fn()} />)
    const dialog = screen.getByRole('dialog', { name: 'Keyboard shortcuts' })
    expect(dialog).toHaveAttribute('aria-modal', 'true')
    const terms = within(dialog).getAllByRole('term').map((t) => t.textContent)
    const defs = within(dialog).getAllByRole('definition').map((d) => d.textContent)
    expect(terms).toEqual(SHORTCUTS.map((s) => s.key))
    expect(defs).toEqual(SHORTCUTS.map((s) => s.does))
  })

  it('starts on Close and keeps Tab there', async () => {
    render(<ShortcutHelp onClose={vi.fn()} />)
    const close = screen.getByRole('button', { name: 'Close' })
    expect(close).toHaveFocus()
    await userEvent.tab()
    expect(close).toHaveFocus()
    await userEvent.tab({ shift: true })
    expect(close).toHaveFocus()
  })

  it('closes on Escape and on Close', async () => {
    const onClose = vi.fn()
    render(<ShortcutHelp onClose={onClose} />)
    await userEvent.keyboard('{Escape}')
    await userEvent.click(screen.getByRole('button', { name: 'Close' }))
    expect(onClose).toHaveBeenCalledTimes(2)
  })

  it('closes on ? and says it handled it', () => {
    const onClose = vi.fn()
    render(<ShortcutHelp onClose={onClose} />)
    const notPrevented = fireEvent.keyDown(screen.getByRole('button', { name: 'Close' }), { key: '?', shiftKey: true })
    expect(onClose).toHaveBeenCalledTimes(1)
    expect(notPrevented).toBe(false)
  })

  it('gives focus back to whatever opened it', () => {
    const opener = document.createElement('button')
    document.body.appendChild(opener)
    opener.focus()
    const { unmount } = render(<ShortcutHelp onClose={vi.fn()} />)
    unmount()
    expect(opener).toHaveFocus()
    opener.remove()
  })
})
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd frontend && npx vitest run src/components/librarian/ShortcutHelp.test.jsx`
Expected: FAIL — `Failed to resolve import "./ShortcutHelp"`.

- [ ] **Step 3: Implement**

`frontend/src/components/librarian/ShortcutHelp.jsx`:

```jsx
import { useEffect, useRef } from 'react'
import { SHORTCUTS } from './shortcuts'

/**
 * The list `?` opens. A modal like the fix panel, so the page's shortcuts
 * stand down while it is open; `?` closes it again, and is marked handled so
 * the page's own `?` listener does not reopen it in the same keystroke.
 */
function ShortcutHelp({ onClose }) {
  const closeRef = useRef(null)
  useEffect(() => {
    const opener = document.activeElement
    closeRef.current?.focus()
    return () => opener?.focus?.() // back to the row (or button) the librarian was on
  }, [])

  const onKeyDown = (e) => {
    if (e.key === 'Escape' || e.key === '?') {
      e.preventDefault()
      onClose()
    } else if (e.key === 'Tab') {
      e.preventDefault() // Close is the only stop; aria-modal promises Tab stays here
    }
  }

  return (
    <div className="fixed inset-0 bg-bg/90 flex items-center justify-center z-50 p-4">
      <div role="dialog" aria-modal="true" aria-labelledby="lib-keys-title" onKeyDown={onKeyDown}
           className="float w-full max-w-prose flex flex-col gap-4 p-5">
        <div className="flex items-center justify-between">
          <h2 id="lib-keys-title" className="text-sm uppercase tracking-eyebrow text-ink">Keyboard shortcuts</h2>
          <button ref={closeRef} type="button" onClick={onClose} aria-label="Close" className="text-ink-dim hover:text-danger">
            <span aria-hidden="true">✕</span>
          </button>
        </div>
        <p className="text-ink-dim">
          On a series page in edit mode; <kbd className="text-ink">e</kbd> and <kbd className="text-ink">?</kbd> work
          outside it. Never while typing in a field.
        </p>
        <dl className="flex flex-col gap-1 text-sm">
          {SHORTCUTS.map(({ key, does }) => (
            <div key={key} className="flex gap-3">
              <dt className="w-6 shrink-0"><kbd className="border border-line-strong px-1 text-ink">{key}</kbd></dt>
              <dd className="text-ink">{does}</dd>
            </div>
          ))}
        </dl>
      </div>
    </div>
  )
}

export default ShortcutHelp
```

- [ ] **Step 4: Run it to verify it passes**

Run: `cd frontend && npx vitest run src/components/librarian/ShortcutHelp.test.jsx`
Expected: PASS — `Tests  5 passed (5)`.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/librarian/ShortcutHelp.jsx frontend/src/components/librarian/ShortcutHelp.test.jsx
git commit -m "feat(web): ShortcutHelp lists the librarian shortcuts"
```

---

### Task 4: Wire the series page

**Files:**
- Modify: `frontend/src/pages/Series.jsx` (`BookRow`, the header toggle, the `add a book` button, the books `<ul>`, `<main>`)
- Test: `frontend/src/pages/Series.shortcuts.test.jsx`

**Interfaces:**
- Consumes: `useLibrarianShortcuts`, `ShortcutHelp`, `ROW_ACTION_KEYS` (Tasks 1–3); from 01 `useLibrarianStore`, `isLibrarian`, `editing`, the `[edit]`/`[done]` button; from 03 the `add a book` button; from 08 the row checkbox; from 06 (if landed) the `cover` row action.
- Produces: on the series page, for librarians — every `BookRow` `<li>` has `data-work-row` and, in edit mode, `tabIndex={-1}`; each row action button carries `aria-keyshortcuts` from `ROW_ACTION_KEYS` (none for `split` or any action not in the map); the 08 row checkbox carries `aria-keyshortcuts="x"`; `add a book` carries `a`; the toggle carries `e`; a `shortcuts` button (edit mode) carries `?` and opens `ShortcutHelp`.

- [ ] **Step 1: Check what landed**

Run:

```bash
cd frontend
grep -n "useLibrarianStore\|setEditMode" src/pages/Series.jsx
grep -n "add a book" src/pages/Series.jsx
grep -n 'type="checkbox"' src/pages/Series.jsx
grep -n "'cover'" src/pages/Series.jsx
```

Expected: the first three print at least one line each (01, 03, 08 are in). If any prints nothing, stop — this plan runs after 01, 03 and 08. The fourth line tells you whether 06 has landed: if it prints nothing, skip the `c` test in Step 2 (delete that `it(…)` block) and note it in the PR; the mapping stays and `c` starts working when 06 adds the `cover` action.

Read `BookRow` and the header in `src/pages/Series.jsx` as they are now; 03, 08 and 09 changed them. The edits below add attributes to elements those items created — keep everything else they put there.

- [ ] **Step 2: Write the failing test**

`frontend/src/pages/Series.shortcuts.test.jsx`:

```jsx
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Routes, Route } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

vi.mock('../api/client', () => ({ default: { get: vi.fn(), post: vi.fn(), put: vi.fn() } }))

import client from '../api/client'
import useAuthStore from '../store/auth'
import useLibrarianStore from '../store/librarian'
import Series from './Series'

const SAGA = {
  id: 's1', slug: 'red-rising', name: 'Red Rising', kind: 'series', description: null,
  works: [
    { id: 'b1', title: 'Red Rising', author: 'Pierce Brown', first_publish_year: 2014, cover_url: null, shelf_status: null, position: 1 },
    { id: 'b2', title: 'Golden Son', author: 'Pierce Brown', first_publish_year: 2015, cover_url: null, shelf_status: null, position: 2 },
  ],
}
const SINGLE = {
  id: 's2', slug: 'the-hobbit-a1b2c3', name: 'The Hobbit', kind: 'singleton', description: null,
  works: [{ id: 'h1', title: 'The Hobbit', author: 'J. R. R. Tolkien', first_publish_year: 1937, cover_url: null, shelf_status: null }],
}
const LIBRARIAN = { id: 'u1', username: 'lib', is_librarian: true }

// Every list-shaped GET answers an empty list, so panels opened by a key
// (work search, series search, covers) render; everything else is the series.
function mockApi(series) {
  client.get.mockImplementation((url) => {
    if (url.endsWith('/threads') || url.startsWith('/works/search') || url.startsWith('/librarian/')) {
      return Promise.resolve({ data: [] })
    }
    return Promise.resolve({ data: series })
  })
}

function renderPage(entry) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[entry]}>
        <input type="search" aria-label="Search books" />
        <Routes>
          <Route path="/series/:slug" element={<Series />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

const rows = async () => {
  const list = await screen.findByRole('list', { name: 'Books in this series' })
  return [...list.querySelectorAll('[data-work-row]')]
}

beforeEach(() => {
  vi.clearAllMocks()
  localStorage.clear()
  useAuthStore.setState({ token: 't', user: LIBRARIAN })
  useLibrarianStore.setState({ editMode: true })
})

describe('Series page keyboard shortcuts', () => {
  it('advertises each key on the control it presses', async () => {
    mockApi(SAGA)
    renderPage('/series/red-rising')
    const [first] = await rows()
    expect(within(first).getByRole('button', { name: 'move Red Rising' })).toHaveAttribute('aria-keyshortcuts', 'm')
    expect(within(first).getByRole('button', { name: 'position Red Rising' })).toHaveAttribute('aria-keyshortcuts', 'p')
    expect(within(first).getByRole('button', { name: 'remove Red Rising' })).toHaveAttribute('aria-keyshortcuts', 'r')
    expect(within(first).getByRole('button', { name: 'merge into… Red Rising' })).toHaveAttribute('aria-keyshortcuts', 'g')
    expect(within(first).getByRole('button', { name: 'split Red Rising' })).not.toHaveAttribute('aria-keyshortcuts')
    expect(within(first).getByRole('checkbox')).toHaveAttribute('aria-keyshortcuts', 'x')
    expect(screen.getByRole('button', { name: 'add a book' })).toHaveAttribute('aria-keyshortcuts', 'a')
    expect(screen.getByRole('button', { name: '[done]' })).toHaveAttribute('aria-keyshortcuts', 'e')
    expect(screen.getByRole('button', { name: 'shortcuts' })).toHaveAttribute('aria-keyshortcuts', '?')
  })

  it('m opens Move for the row under the cursor, and types nothing into it', async () => {
    mockApi(SAGA)
    renderPage('/series/red-rising')
    const [, second] = await rows()
    await userEvent.keyboard('jj')
    expect(second).toHaveFocus()
    await userEvent.keyboard('m')
    const dialog = await screen.findByRole('dialog', { name: 'Move Golden Son' })
    expect(within(dialog).getByLabelText('Find a series')).toHaveValue('')
    await userEvent.keyboard('{Escape}')
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
    expect(second).toHaveFocus() // the cursor is where it was
  })

  it('a key typed in the panel is only typed', async () => {
    mockApi(SAGA)
    renderPage('/series/red-rising')
    await rows()
    await userEvent.keyboard('jm')
    const dialog = await screen.findByRole('dialog', { name: 'Move Red Rising' })
    const field = within(dialog).getByLabelText('Find a series')
    await userEvent.type(field, 'jkmrgeax')
    expect(field).toHaveValue('jkmrgeax')
    expect(screen.getAllByRole('dialog')).toHaveLength(1)
  })

  it('g opens merge, p opens position', async () => {
    mockApi(SAGA)
    renderPage('/series/red-rising')
    await rows()
    await userEvent.keyboard('jg')
    expect(await screen.findByRole('dialog', { name: 'Merge Red Rising' })).toBeInTheDocument()
    await userEvent.keyboard('{Escape}')
    await userEvent.keyboard('p')
    expect(await screen.findByRole('dialog', { name: 'Set position Red Rising' })).toBeInTheDocument()
  })

  it('p does nothing on a singleton, which has no position', async () => {
    mockApi(SINGLE)
    renderPage('/series/the-hobbit-a1b2c3')
    await rows()
    await userEvent.keyboard('jp')
    expect(screen.queryByRole('dialog')).toBeNull()
    await userEvent.keyboard('m')
    expect(await screen.findByRole('dialog', { name: 'Move The Hobbit' })).toBeInTheDocument()
  })

  it('x selects the row for a batch', async () => {
    mockApi(SAGA)
    renderPage('/series/red-rising')
    const [first] = await rows()
    await userEvent.keyboard('jx')
    expect(within(first).getByRole('checkbox')).toBeChecked()
  })

  it('a opens add a book, and types nothing into it', async () => {
    mockApi(SAGA)
    renderPage('/series/red-rising')
    await rows()
    await userEvent.keyboard('a')
    const dialog = await screen.findByRole('dialog')
    within(dialog).queryAllByRole('textbox').forEach((field) => expect(field).toHaveValue(''))
  })

  it('c opens the cover picker for the row under the cursor', async () => {
    // Delete this test if Step 1 showed item 06 has not landed.
    mockApi(SAGA)
    renderPage('/series/red-rising')
    await rows()
    await userEvent.keyboard('jc')
    expect(await screen.findByRole('dialog')).toBeInTheDocument()
  })

  it('e enters and leaves edit mode', async () => {
    useLibrarianStore.setState({ editMode: false })
    mockApi(SAGA)
    renderPage('/series/red-rising')
    await screen.findByRole('button', { name: '[edit]' })
    await userEvent.keyboard('e')
    expect(useLibrarianStore.getState().editMode).toBe(true)
    expect(await screen.findByRole('button', { name: 'move Red Rising' })).toBeInTheDocument()
    await userEvent.keyboard('e')
    expect(useLibrarianStore.getState().editMode).toBe(false)
  })

  it('needs edit mode for the cursor', async () => {
    useLibrarianStore.setState({ editMode: false })
    mockApi(SAGA)
    renderPage('/series/red-rising')
    await screen.findByRole('button', { name: '[edit]' })
    await userEvent.keyboard('jm')
    expect(document.body).toHaveFocus()
    expect(screen.queryByRole('dialog')).toBeNull()
  })

  it('? opens the list and ? closes it for good', async () => {
    mockApi(SAGA)
    renderPage('/series/red-rising')
    await rows()
    await userEvent.keyboard('j')
    fireEvent.keyDown(document.activeElement, { key: '?', shiftKey: true })
    const help = await screen.findByRole('dialog', { name: 'Keyboard shortcuts' })
    fireEvent.keyDown(within(help).getByRole('button', { name: 'Close' }), { key: '?', shiftKey: true })
    await waitFor(() => expect(screen.queryByRole('dialog', { name: 'Keyboard shortcuts' })).toBeNull())
    const [first] = await rows()
    expect(first).toHaveFocus()
  })

  it('the shortcuts button opens the same list', async () => {
    mockApi(SAGA)
    renderPage('/series/red-rising')
    await userEvent.click(await screen.findByRole('button', { name: 'shortcuts' }))
    expect(screen.getByRole('dialog', { name: 'Keyboard shortcuts' })).toBeInTheDocument()
  })

  it('types into the search box instead of acting', async () => {
    mockApi(SAGA)
    renderPage('/series/red-rising')
    await rows()
    await userEvent.type(screen.getByRole('searchbox', { name: 'Search books' }), 'jme')
    expect(screen.getByRole('searchbox', { name: 'Search books' })).toHaveValue('jme')
    expect(screen.queryByRole('dialog')).toBeNull()
    expect(useLibrarianStore.getState().editMode).toBe(true)
  })

  it('does nothing for a reader, even with edit mode stored', async () => {
    useAuthStore.setState({ token: 't', user: { id: 'u2', username: 'reader' } })
    mockApi(SAGA)
    renderPage('/series/red-rising')
    await screen.findByRole('list', { name: 'Books in this series' })
    await userEvent.keyboard('jmea')
    fireEvent.keyDown(document.body, { key: '?', shiftKey: true })
    expect(screen.queryByRole('dialog')).toBeNull()
    expect(document.body).toHaveFocus()
    expect(screen.queryByRole('button', { name: 'shortcuts' })).toBeNull()
    const list = screen.getByRole('list', { name: 'Books in this series' })
    list.querySelectorAll('[data-work-row]').forEach((row) => expect(row).not.toHaveAttribute('tabindex'))
  })
})
```

- [ ] **Step 3: Run it to verify it fails**

Run: `cd frontend && npx vitest run src/pages/Series.shortcuts.test.jsx`
Expected: FAIL — `advertises each key…` (no `aria-keyshortcuts`), every key test (no listener: dialogs never open, rows never focus), `shortcuts` button not found. `needs edit mode for the cursor` and `does nothing for a reader…` may already pass.

- [ ] **Step 4: Implement**

In `frontend/src/pages/Series.jsx`:

1. Imports. Change the React import to include `useCallback`:

```jsx
import { useCallback, useEffect, useRef, useState } from 'react'
```

and add, after `import LibrarianPanel from '../components/LibrarianPanel'`:

```jsx
import ShortcutHelp from '../components/librarian/ShortcutHelp'
import useLibrarianShortcuts from '../components/librarian/useLibrarianShortcuts'
import { ROW_ACTION_KEYS } from '../components/librarian/shortcuts'
```

2. `BookRow`: on its `<li>`, add the row marker and, in edit mode, programmatic focusability — keep every attribute 08/09 added:

```jsx
    <li
      ref={rowRef}
      data-work-row
      // The keyboard cursor is focus: j/k move it, and a row key acts on this row.
      tabIndex={editing ? -1 : undefined}
      aria-current={current ? 'true' : undefined}
```

3. `BookRow` action buttons: in the `.map((name) => (<button …>))` that renders the row actions, add `aria-keyshortcuts`:

```jsx
              <button key={name} type="button" className="btn-ghost text-xs" onClick={() => onAction(name)}
                      aria-keyshortcuts={ROW_ACTION_KEYS[name]}
                      aria-label={`${name} ${work.title}`}>
                {name}
              </button>
```

(`ROW_ACTION_KEYS[name]` is `undefined` for `split` and any action without a key, and React then omits the attribute.)

4. `BookRow` batch checkbox (08): add `aria-keyshortcuts="x"` to the `<input type="checkbox" …>` 08 renders in each row, e.g.

```jsx
          <input type="checkbox" aria-keyshortcuts="x" /* …08's existing props: checked, onChange, aria-label… */ />
```

5. In `Series`, next to the other refs and state (before any early `return`):

```jsx
  const pageRef = useRef(null)
  const listRef = useRef(null)
  const [showKeys, setShowKeys] = useState(false)
  const openKeys = useCallback(() => setShowKeys(true), [])
```

and, directly after the `useStatusBar({ … })` call (still before `if (isLoading)`):

```jsx
  // Librarians only: a reader's page never listens, whatever the store says.
  useLibrarianShortcuts({
    enabled: isLibrarian,
    editing: editing && !series?.dissolved,
    pageRef,
    listRef,
    onHelp: openKeys,
  })
```

6. Put `pageRef` on the page's outer `<main>` (the one with `flex flex-col gap-10`):

```jsx
    <main ref={pageRef} className="max-w-shell mx-auto px-4 py-6 flex flex-col gap-10">
```

and `listRef` on the books list:

```jsx
      <ul ref={listRef} aria-label="Books in this series" className="flex flex-col divide-y divide-line">
```

7. Header toggle (from 01). Replace

```jsx
        {isLibrarian && (
          <button type="button" onClick={() => setEditMode(!editing)}
                  className="text-xs text-accent hover:text-accent-hover transition-colors duration-fast">
            {editing ? '[done]' : '[edit]'}
          </button>
        )}
```

with

```jsx
        {isLibrarian && (
          <div className="flex items-center gap-3">
            {editing && (
              <button type="button" aria-keyshortcuts="?" onClick={openKeys}
                      className="text-xs text-ink-dim hover:text-accent transition-colors duration-fast">
                shortcuts
              </button>
            )}
            <button type="button" aria-keyshortcuts="e" onClick={() => setEditMode(!editing)}
                    className="text-xs text-accent hover:text-accent-hover transition-colors duration-fast">
              {editing ? '[done]' : '[edit]'}
            </button>
          </div>
        )}
```

(If 01's toggle has different classes by now, keep them; only the wrapper, the `shortcuts` button and `aria-keyshortcuts="e"` are new.)

8. The `add a book` button (03): add `aria-keyshortcuts="a"` to it and change nothing else, e.g.

```jsx
            <button type="button" className="btn-ghost text-xs" aria-keyshortcuts="a" /* …03's onClick… */>add a book</button>
```

9. Render the list next to the `LibrarianPanel` block at the end of `<main>`:

```jsx
      {showKeys && <ShortcutHelp onClose={() => setShowKeys(false)} />}
```

- [ ] **Step 5: Run it to verify it passes**

Run: `cd frontend && npx vitest run src/pages/Series.shortcuts.test.jsx`
Expected: PASS — every test in `Series page keyboard shortcuts` (13, or 12 if the `c` test was deleted in Step 1).

- [ ] **Step 6: Run the whole frontend suite**

Run: `cd frontend && npm test`
Expected: PASS — in particular `Series.test.jsx` (rows now carry `data-work-row`; nothing there queries by attribute) and `LibrarianPanel.test.jsx`.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/pages/Series.jsx frontend/src/pages/Series.shortcuts.test.jsx
git commit -m "feat(web): keyboard shortcuts on the series page for librarians"
```

---

### Task 5: End-to-end — a fix from the keyboard

**Files:**
- Modify: `frontend/e2e/librarian.spec.js`

**Interfaces:**
- Consumes: Task 4's page; `registerViaUi`, `grantLibrarian`, `openFirstSearchResult` from `e2e/helpers.js`.
- Produces: nothing.

- [ ] **Step 1: Add the scenario**

Append to `frontend/e2e/librarian.spec.js`:

```js
// Edit mode, the cursor, a panel and the list, all from the keyboard. Changes
// nothing in the catalog. Needs the full stack and live Open Library.
test('a librarian drives the series page from the keyboard', async ({ page }) => {
  const user = await registerViaUi(page)
  grantLibrarian(user)
  await page.reload() // useMe refreshes the stored user, now a librarian

  await openFirstSearchResult(page, 'the tombs of atuan')
  await page.keyboard.press('e')
  await expect(page.getByRole('button', { name: '[done]' })).toBeVisible()

  const firstRow = page.locator('[data-work-row]').first()
  await page.keyboard.press('j')
  await expect(firstRow).toBeFocused()

  await page.keyboard.press('m')
  const panel = page.getByRole('dialog', { name: /^Move / })
  await expect(panel).toBeVisible()
  await expect(panel.getByLabel('Find a series')).toHaveValue('')
  await panel.getByLabel('Find a series').pressSequentially('jk')
  await expect(panel.getByLabel('Find a series')).toHaveValue('jk')
  await page.keyboard.press('Escape')
  await expect(panel).toBeHidden()
  await expect(firstRow).toBeFocused()

  await page.keyboard.press('?')
  const help = page.getByRole('dialog', { name: 'Keyboard shortcuts' })
  await expect(help).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(help).toBeHidden()

  await page.keyboard.press('e')
  await expect(page.getByRole('button', { name: '[edit]' })).toBeVisible()
})
```

- [ ] **Step 2: Run it**

Bring the stack up in another terminal (`docker compose up --build`), then:

Run: `cd frontend && npx playwright test e2e/librarian.spec.js -g "keyboard"`
Expected: `1 passed`. Then `npx playwright test e2e/librarian.spec.js` — every scenario in the file passes.

- [ ] **Step 3: Commit**

```bash
git add frontend/e2e/librarian.spec.js
git commit -m "test(e2e): a librarian drives the series page from the keyboard"
```

---

### Task 6: Docs and tracker

**Files:**
- Modify: `docs/librarian-ux-roadmap.md`, `ROADMAP.md`, `CLAUDE.md`

**Interfaces:**
- Consumes: everything above.
- Produces: nothing.

- [ ] **Step 1: `CLAUDE.md`**

In the Design system section, add to the `components/librarian/` bullet (add the bullet if 02 did not: ``- **Librarian components** live in `components/librarian/` (`LibrarianPanel.jsx` itself stays in `components/`).``):

```markdown
  Keyboard shortcuts (series page, librarians): `shortcuts.js` is the table; `useLibrarianShortcuts` presses whichever control carries the key in `aria-keyshortcuts`, inside the focused `[data-work-row]` for row keys. A new row action that deserves a key gets an entry in `ROW_ACTION_KEYS` and `SHORTCUTS`; a new page control gets `aria-keyshortcuts` and a `SHORTCUTS` entry. Never bind a key to anything without a visible control, and never with Ctrl/Meta/Alt.
```

- [ ] **Step 2: `ROADMAP.md`**

In the Phase 5 **Librarian tools** row, replace

```
fix log at `/librarian`.
```

with

```
fix log at `/librarian`; keyboard shortcuts on the series page (`?` lists them).
```

(If an earlier roadmap item already rewrote that cell, add the same clause to the cell as it stands.)

- [ ] **Step 3: Record the new names for later items**

Under **Notes** in `docs/librarian-ux-roadmap.md`, add:

```markdown
- 2026-MM-DD (10): series-page shortcuts press controls by `aria-keyshortcuts`. Book rows carry `data-work-row` (and `tabIndex={-1}` in edit mode). A later row action with a key adds it to `ROW_ACTION_KEYS` in `components/librarian/shortcuts.js`; keys taken: j k m p r g c x a e ?.
```

(with the real date).

- [ ] **Step 4: Run the full frontend suite once more**

Run: `cd frontend && npm test`
Expected: PASS — all test files.

- [ ] **Step 5: Commit and open the PR**

```bash
git add CLAUDE.md ROADMAP.md docs/librarian-ux-roadmap.md
git commit -m "docs: librarian keyboard shortcuts"
git push -u origin feat/librarian-lx10-keyboard-shortcuts
gh pr create --base main --title "feat(web): librarian keyboard shortcuts (LX10)" \
  --body "Roadmap item 10 (docs/librarian-ux-roadmap.md). j/k row cursor (DOM focus), m p r g c x on the focused row, a add a book, e edit mode, ? the list. Each key presses the control that carries it in aria-keyshortcuts; nothing fires while typing, with Ctrl/Meta/Alt, under an open dialog, or for readers."
```

- [ ] **Step 6: Tick the tracker when it merges**

After the PR merges, change the tracker row in `docs/librarian-ux-roadmap.md` to

```
| 10 | Keyboard shortcuts | [plan](superpowers/plans/2026-09-29-lx10-keyboard-shortcuts.md) | 01, 03, 08 | ✅ | feat/librarian-lx10-keyboard-shortcuts | <merge date, YYYY-MM-DD> | #<PR number from `gh pr view --json number -q .number`> |
```

and tick the `Roadmap item` checkbox at the top of this plan.

```bash
git add docs/librarian-ux-roadmap.md docs/superpowers/plans/2026-09-29-lx10-keyboard-shortcuts.md
git commit -m "docs: LX10 done"
```
