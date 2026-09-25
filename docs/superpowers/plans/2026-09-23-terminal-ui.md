# Terminal UI Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild MARGIN's frontend as a terminal-styled interface — Tokyo Night palette, JetBrains Mono throughout with Playfair retained for book titles only, and four terminal structures (path header, glyph-elbow reply tree, `ls -l` listings, pinned status bar) plus an nvim-style diagnostic float.

**Architecture:** Foundation first (design tokens, fonts, component vocabulary, five new primitives), then the Thread page as a pilot with a human review gate, then the remaining ten pages fan out against the proven vocabulary. All colour flows through CSS variables mapped to semantic Tailwind utilities; `surface`/`raised`/`accent-ink`/`success` survive as aliases so unconverted pages keep rendering mid-migration, and are deleted in the final task.

**Tech Stack:** React 18, Vite 5, React Router 6, TanStack Query 5, Zustand 4, Tailwind 3.4, Vitest 1.6 + React Testing Library, Playwright 1.44.

**Spec:** [`docs/superpowers/specs/2026-09-23-terminal-ui-design.md`](../specs/2026-09-23-terminal-ui-design.md)

## Global Constraints

These apply to **every** task. They are design requirements, not style preferences — most are load-bearing for accessibility or for existing tests.

- **No raw colours.** Never write a `zinc-*`, hex, or arbitrary colour in a component. Add a token to `index.css` + `tailwind.config.js` instead.
- **Contrast tiers are fixed.** `ink` (10.59:1) body · `ink-dim` (8.10:1) secondary, metadata, timestamps · `ink-muted` (4.10:1) **control borders and decoration only, never informational text** · `ink-faint` (2.76:1) **`aria-hidden` glyphs only**.
- **Fills invert.** A filled control is `bg-accent text-bg`. White on `#7AA2F7` is 2.52:1 and fails. `accent-ink` is deleted — use `accent` for accent text.
- **Serif is for book titles only.** Everything else, including thread titles, is mono.
- **Scores render ASCII `-2`**, never `−2` (U+2212). Required by `VoteControl.test.jsx:34`.
- **Brackets on buttons live in `::before`/`::after`**, never in the text node — the accessible name must stay `Start a Thread`. Required by `e2e/thread.spec.js:13,18` and `e2e/reply.spec.js:21`.
- **Navbar search keeps `type="search"`** so its role stays `searchbox`, out of `getByRole('textbox')`. Required by `e2e/auth.spec.js:16` and `e2e/helpers.js:17`.
- **Table rows are real `<a href>`**, never `onClick` handlers. Required by `e2e/helpers.js:31`.
- **These exact strings must not change:** `Out` (logout), `Sign in`, `Create account`, `Start a Thread`, `Create Thread`, `Post`, `Page not found` (may be visually hidden), `Go home` (may be an `aria-label`).
- **Register keeps exactly one `input[type="text"]`.** Required by `e2e/helpers.js:18`.
- **Box-drawing frames and tree rails are CSS borders**, not characters. Only tree elbows (`├─`, `└─`), sort carets (`▾`/`▴`) and the float marker (`■`) are literal glyphs, and all are `aria-hidden`.
- **No new border radii, shadows, or durations.** Corners are square; motion is `duration-fast` (120ms) or `duration-base` (180ms).
- **Nothing means anything by colour alone.** Scores keep their `+`/`-` sign, vote state keeps `aria-pressed`, floats keep a severity word in `sr-only` text.
- Run tests from `frontend/`. `npm test` runs Vitest; `npm run build` must stay clean.

---

## File Structure

**Created**

| File | Responsibility |
| --- | --- |
| `frontend/src/design/tokens.test.js` | Parses `index.css` and asserts every contrast tier. Locks the palette against future drift. |
| `frontend/src/lib/slug.js` | `slug(text, maxLength)` — path-safe segment labels. Pure. |
| `frontend/src/lib/slug.test.js` | Unit tests for the above. |
| `frontend/src/store/status.js` | Zustand store + `useStatusBar()` hook feeding the status bar. |
| `frontend/src/components/PathHeader.jsx` | Filesystem-path breadcrumb. |
| `frontend/src/components/StatusBar.jsx` | Pinned bottom bar. |
| `frontend/src/components/DiagnosticFloat.jsx` | nvim-style hover/focus popover. |
| `frontend/src/components/DataTable.jsx` | `ls -l` listing with sortable headers. |
| `frontend/src/components/ThreadModal.jsx` | Shared thread-creation modal (was duplicated in `Book` and `Genre`). |
| `*.test.jsx` for each new component | Behaviour and a11y wiring. |

**Deleted**

| File | Replaced by |
| --- | --- |
| `frontend/src/components/ThreadCard.jsx` | `DataTable` rows |
| `frontend/src/components/GenreCard.jsx` | `ls`-style listing on `Home` |

**Modified:** `frontend/index.html`, `frontend/tailwind.config.js`, `frontend/src/index.css`, `frontend/src/App.jsx`, all 11 pages, `Navbar`, `Post`, `PostComposer`, `VoteControl`, `ShelfButton`, `BookCard`, `AuthLayout`, plus `CLAUDE.md` and `docs/visual-identity.md`.

---

## Task 1: Design tokens, fonts and component vocabulary

Foundation. Nothing renders differently in structure — only colour and typeface change. The token test is the durable deliverable: it makes the contrast tiers executable rather than aspirational.

**Files:**
- Modify: `frontend/src/index.css` (full rewrite)
- Modify: `frontend/tailwind.config.js` (full rewrite)
- Modify: `frontend/index.html:9` (the Google Fonts `<link>`)
- Test: `frontend/src/design/tokens.test.js` (create)

**Interfaces:**
- Consumes: nothing
- Produces: Tailwind utilities `bg-bg`, `bg-panel`, `bg-highlight`, `border-line`, `border-line-strong`, `text-ink`, `text-ink-dim`, `text-ink-muted`, `text-ink-faint`, `text-accent`, `text-accent-hover`, `text-path`, `text-user`, `text-ok`, `text-danger`, `text-warning` (each also available as `bg-*` and `border-*`); aliases `surface`, `raised`, `accent-ink`, `success`; component classes `.btn`, `.btn-primary`, `.btn-primary-lg`, `.btn-secondary`, `.btn-ghost`, `.input`, `.label`, `.panel`, `.panel-title`, `.float`, `.prompt`, `.caret`, `.eyebrow`, `.rule`, `.alert-danger`, `.alert-muted`; CSS variables `--shell-nav-h`, `--shell-status-h`; max-widths `max-w-prose`, `max-w-table`, `max-w-shell`.

- [ ] **Step 1: Write the failing token test**

Create `frontend/src/design/tokens.test.js`:

```js
import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

// The palette is only as good as its worst pair, so the contrast tiers from the
// spec are asserted here rather than trusted to review. Parsing index.css keeps
// this honest: the test reads what actually ships.
const cssPath = fileURLToPath(new URL('../index.css', import.meta.url))
const css = readFileSync(cssPath, 'utf8')

function tokens() {
  const out = {}
  for (const m of css.matchAll(/--color-([a-z-]+):\s*(\d+)\s+(\d+)\s+(\d+)\s*;/g)) {
    out[m[1]] = [Number(m[2]), Number(m[3]), Number(m[4])]
  }
  return out
}

function luminance([r, g, b]) {
  const chan = (c) => {
    const s = c / 255
    return s <= 0.04045 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4
  }
  return 0.2126 * chan(r) + 0.7152 * chan(g) + 0.0722 * chan(b)
}

function contrast(a, b) {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x)
  return (hi + 0.05) / (lo + 0.05)
}

describe('design tokens', () => {
  const t = tokens()

  it('defines every token the design system names', () => {
    for (const name of [
      'bg', 'panel', 'highlight', 'line', 'line-strong',
      'ink', 'ink-dim', 'ink-muted', 'ink-faint',
      'accent', 'accent-hover', 'path', 'user', 'ok', 'danger', 'warning',
    ]) {
      expect(t[name], `--color-${name} is missing`).toBeDefined()
    }
  })

  it('keeps informational text at or above 8:1 on the page background', () => {
    expect(contrast(t.ink, t.bg)).toBeGreaterThanOrEqual(10)
    expect(contrast(t['ink-dim'], t.bg)).toBeGreaterThanOrEqual(8)
  })

  it('keeps ink-muted above the 3:1 non-text floor for control borders', () => {
    expect(contrast(t['ink-muted'], t.bg)).toBeGreaterThanOrEqual(3)
  })

  it('keeps every semantic colour readable as text', () => {
    for (const name of ['accent', 'accent-hover', 'path', 'user', 'ok', 'danger', 'warning']) {
      expect(contrast(t[name], t.bg), `${name} vs bg`).toBeGreaterThanOrEqual(4.5)
    }
  })

  it('keeps inverted fills readable — bg-coloured text on an accent fill', () => {
    expect(contrast(t.bg, t.accent)).toBeGreaterThanOrEqual(4.5)
    expect(contrast(t.bg, t['accent-hover'])).toBeGreaterThanOrEqual(4.5)
  })

  it('confirms white on accent fails, which is why fills invert', () => {
    expect(contrast([255, 255, 255], t.accent)).toBeLessThan(4.5)
  })

  it('reads every token against the panel surface too, since panels are darker', () => {
    expect(contrast(t.ink, t.panel)).toBeGreaterThanOrEqual(10)
    expect(contrast(t.accent, t.panel)).toBeGreaterThanOrEqual(4.5)
  })
})
```

- [ ] **Step 2: Run the test and verify it fails**

Run: `cd frontend && npx vitest run src/design/tokens.test.js`
Expected: FAIL — `--color-panel is missing` (the current `index.css` has `surface`/`raised`, not `panel`/`highlight`).

- [ ] **Step 3: Rewrite `frontend/src/index.css`**

```css
@tailwind base;
@tailwind components;
@tailwind utilities;

/**
 * MARGIN design tokens — Tokyo Night.
 *
 * Values are raw `R G B` channels so Tailwind opacity modifiers (`bg-panel/50`)
 * keep working. `tailwind.config.js` maps each to a semantic utility. Contrast
 * ratios are measured against `bg` and asserted in `src/design/tokens.test.js`.
 *
 * Text tiers: ink (body) > ink-dim (secondary, metadata, timestamps) >
 * ink-muted (control borders and decoration ONLY — 4.10:1 is below AA for
 * normal text) > ink-faint (aria-hidden glyphs ONLY).
 */
@layer base {
  :root {
    --color-bg: 26 27 38; /* #1A1B26 */
    --color-panel: 22 22 30; /* #16161E — floats, status bar, nav, inputs */
    --color-highlight: 41 46 66; /* #292E42 — hovered/selected row */
    --color-line: 59 66 97; /* #3B4261 — dividers (decorative) */
    --color-line-strong: 65 72 104; /* #414868 — box frames, tree rails */

    --color-ink: 192 202 245; /* #C0CAF5 — 10.59:1 */
    --color-ink-dim: 169 177 214; /* #A9B1D6 — 8.10:1 */
    --color-ink-muted: 115 122 162; /* #737AA2 — 4.10:1, borders/decoration */
    --color-ink-faint: 86 95 137; /* #565F89 — 2.76:1, aria-hidden glyphs */

    --color-accent: 122 162 247; /* #7AA2F7 — 6.79:1, interactive */
    --color-accent-hover: 137 221 255; /* #89DDFF — 11.27:1 */
    --color-path: 125 207 255; /* #7DCFFF — 9.96:1, routes */
    --color-user: 187 154 247; /* #BB9AF7 — 7.39:1, people */
    --color-ok: 158 206 106; /* #9ECE6A — 9.35:1, positive */
    --color-danger: 247 118 142; /* #F7768E — 6.46:1, negative */
    --color-warning: 224 175 104; /* #E0AF68 — 8.55:1, mutated state */

    /* Shell metrics. AuthLayout and the status bar both read these rather than
       hardcoding pixel heights. */
    --shell-nav-h: 49px;
    --shell-status-h: 28px;
  }

  body {
    font-family: 'JetBrains Mono', ui-monospace, SFMono-Regular, Menlo, monospace;
    /* The status bar is position:fixed, so the document reserves its height. */
    padding-bottom: var(--shell-status-h);
    -webkit-font-smoothing: antialiased;
    -moz-osx-font-smoothing: grayscale;
  }

  /* Selection inverts, as a terminal does. */
  ::selection {
    background-color: rgb(var(--color-accent));
    color: rgb(var(--color-bg));
  }

  :focus-visible {
    outline: 2px solid rgb(var(--color-accent));
    outline-offset: 2px;
  }
}

/**
 * Shared component vocabulary. Anything repeated on more than one screen lives
 * here so controls can't drift apart.
 */
@layer components {
  .eyebrow {
    @apply text-xs uppercase tracking-eyebrow text-accent font-medium;
  }

  .rule {
    @apply w-0.5 h-5 bg-accent shrink-0;
  }

  .btn {
    @apply inline-flex items-center justify-center gap-2 px-4 py-2 text-sm font-medium
           transition-colors duration-fast disabled:opacity-50 disabled:cursor-not-allowed;
  }

  /* Fills invert: bg-coloured text on an accent ground. White would be 2.52:1. */
  .btn-primary {
    @apply btn bg-accent text-bg hover:bg-accent-hover;
  }

  .btn-primary-lg {
    @apply btn-primary px-8 py-4 text-xs font-semibold uppercase tracking-widest;
  }

  /* Brackets are pseudo-elements so they stay out of the accessible name —
     `[ Start a Thread ]` must still be found by name "Start a Thread". */
  .btn-secondary {
    @apply btn border border-ink-muted text-accent hover:bg-highlight hover:text-accent-hover;
  }

  .btn-secondary::before {
    content: '[';
    @apply text-ink-faint;
  }

  .btn-secondary::after {
    content: ']';
    @apply text-ink-faint;
  }

  .btn-ghost {
    @apply btn text-ink-dim hover:text-ink;
  }

  /* Control borders need 3:1 (WCAG 1.4.11); line-strong is only 1.91:1. */
  .input {
    @apply w-full bg-panel border border-ink-muted text-ink placeholder-ink-muted px-3 py-2 text-sm
           focus:outline-none focus:border-accent transition-colors duration-fast;
    caret-color: rgb(var(--color-accent));
  }

  .label {
    @apply block text-xs font-medium text-ink-dim lowercase tracking-eyebrow mb-1.5;
  }

  /* A framed block with a title notch sitting on the top border. This renders
     `┌─ TITLE ──┐` responsively; literal characters would break at every width. */
  .panel {
    @apply relative border border-line-strong bg-bg;
  }

  .panel-title {
    @apply absolute -top-2 left-3 bg-bg px-2 text-xs uppercase tracking-eyebrow text-ink-dim;
  }

  /* nvim diagnostic float: square border, panel ground, no shadow. */
  .float {
    @apply border border-line-strong bg-panel px-3 py-2 text-xs;
  }

  .prompt {
    @apply flex items-center gap-2;
  }

  .prompt::before {
    content: '>';
    @apply text-accent select-none;
  }

  .alert-danger {
    @apply border border-danger/50 bg-danger/10 text-danger px-4 py-3 text-sm;
  }

  .alert-muted {
    @apply border border-line bg-panel text-ink-dim px-4 py-3 text-sm;
  }
}

@keyframes caret-blink {
  0%, 49% { opacity: 1; }
  50%, 100% { opacity: 0; }
}

.caret {
  animation: caret-blink 1s step-end infinite;
}

@media (prefers-reduced-motion: reduce) {
  .caret {
    animation: none;
  }
}
```

- [ ] **Step 4: Rewrite `frontend/tailwind.config.js`**

```js
/**
 * MARGIN design system — Tokyo Night, terminal-styled.
 *
 * Every colour is a semantic token backed by a CSS variable in `src/index.css`
 * (raw `R G B` channels so `/opacity` modifiers work, e.g. `border-line/60`).
 * Never write a raw `zinc-*`, hex, or arbitrary colour in a component.
 *
 * Usage rules (asserted in `src/design/tokens.test.js`):
 *   accent       interactive: links, buttons, focus, prompt caret.
 *                As a FILL it takes `text-bg` — white on accent is 2.52:1.
 *   path         routes and references (path header, book/genre links)
 *   user         people (usernames, bylines)
 *   ok/danger/warning   positive / negative / mutated state
 *   ink-muted    control borders and decoration ONLY — 4.10:1 is below AA
 *   ink-faint    aria-hidden glyphs ONLY — 2.76:1
 */
const token = (name) => `rgb(var(--color-${name}) / <alpha-value>)`

export default {
  content: ['./index.html', './src/**/*.{js,jsx}'],
  theme: {
    extend: {
      colors: {
        bg: token('bg'),
        panel: token('panel'),
        highlight: token('highlight'),
        line: token('line'),
        'line-strong': token('line-strong'),

        ink: token('ink'),
        'ink-dim': token('ink-dim'),
        'ink-muted': token('ink-muted'),
        'ink-faint': token('ink-faint'),

        accent: token('accent'),
        'accent-hover': token('accent-hover'),
        path: token('path'),
        user: token('user'),
        ok: token('ok'),
        danger: token('danger'),
        warning: token('warning'),

        // Migration aliases. Unconverted pages still reference these; the final
        // task deletes them along with their last consumer.
        surface: token('panel'),
        raised: token('highlight'),
        'accent-ink': token('accent'),
        success: token('ok'),
      },
      fontFamily: {
        // Mono carries the whole UI. Serif is reserved for BOOK titles only —
        // not thread titles, which are structure.
        mono: ['"JetBrains Mono"', 'ui-monospace', 'SFMono-Regular', 'Menlo', 'monospace'],
        sans: ['"JetBrains Mono"', 'ui-monospace', 'monospace'],
        serif: ['"Playfair Display"', 'Georgia', 'serif'],
      },
      fontSize: {
        // Mono runs ~15% wider per character, so the display scale is smaller
        // than the proportional one it replaces, at zero tracking.
        'display-sm': ['1.75rem', { lineHeight: '1.15', letterSpacing: '0' }],
        display: ['2.25rem', { lineHeight: '1.1', letterSpacing: '0' }],
        'display-lg': ['3rem', { lineHeight: '1.05', letterSpacing: '0' }],
      },
      letterSpacing: {
        // 0.25em reads as broken on mono; 0.15em reads as wide.
        eyebrow: '0.15em',
      },
      maxWidth: {
        // In a monospaced layout `ch` is a real column count, so this IS the grid.
        prose: '72ch',
        table: '96ch',
        shell: '120ch',
      },
      transitionDuration: {
        fast: '120ms',
        base: '180ms',
      },
    },
  },
  plugins: [],
}
```

- [ ] **Step 5: Swap the font link in `frontend/index.html`**

Replace the `<link href="https://fonts.googleapis.com/css2?family=Space+Grotesk...">` line with:

```html
    <link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:ital,wght@0,400;0,500;0,700;1,400&family=Playfair+Display:ital,wght@0,400;0,600;0,700;1,400;1,600&display=swap" rel="stylesheet">
```

- [ ] **Step 6: Run the token test and verify it passes**

Run: `cd frontend && npx vitest run src/design/tokens.test.js`
Expected: PASS, 7 tests.

- [ ] **Step 7: Verify nothing else broke**

Run: `cd frontend && npm test && npm run build`
Expected: all existing suites PASS (they assert roles and names, not colours); build clean.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/index.css frontend/tailwind.config.js frontend/index.html frontend/src/design/tokens.test.js
git commit -m "feat(web): Tokyo Night tokens, JetBrains Mono, inverted fills

Replaces the cobalt/Space Grotesk system. Fills invert (bg text on accent)
because white on #7AA2F7 is 2.52:1. The muted tier splits three ways so no
informational text sits below 8.10:1. tokens.test.js asserts every tier."
```

---

## Task 2: `slug()` helper

Path segments need stable, path-safe labels. Pure function, so it is tested exhaustively and never again.

**Files:**
- Create: `frontend/src/lib/slug.js`
- Test: `frontend/src/lib/slug.test.js`

**Interfaces:**
- Consumes: nothing
- Produces: `slug(text: string, maxLength = 28): string` — lowercase, accent-stripped, non-alphanumerics collapsed to `-`, trimmed of leading/trailing/trailing-after-truncation dashes.

- [ ] **Step 1: Write the failing test**

Create `frontend/src/lib/slug.test.js`:

```js
import { describe, it, expect } from 'vitest'
import { slug } from './slug'

describe('slug', () => {
  it('lowercases and hyphenates words', () => {
    expect(slug('The Dispossessed')).toBe('the-dispossessed')
  })

  it('strips accents', () => {
    expect(slug('Les Misérables')).toBe('les-miserables')
  })

  it('collapses punctuation and repeated separators', () => {
    expect(slug("Gravity's Rainbow -- Part  II")).toBe('gravity-s-rainbow-part-ii')
  })

  it('truncates without leaving a trailing dash', () => {
    expect(slug('A Very Long Book Title That Runs On', 20)).toBe('a-very-long-book')
  })

  it('returns an empty string for empty or nullish input', () => {
    expect(slug('')).toBe('')
    expect(slug(null)).toBe('')
    expect(slug(undefined)).toBe('')
  })

  it('leaves an already-clean slug untouched', () => {
    expect(slug('science-fiction')).toBe('science-fiction')
  })
})
```

- [ ] **Step 2: Run the test and verify it fails**

Run: `cd frontend && npx vitest run src/lib/slug.test.js`
Expected: FAIL — `Failed to resolve import "./slug"`.

- [ ] **Step 3: Write the implementation**

Create `frontend/src/lib/slug.js`:

```js
/**
 * Path-safe label for a `PathHeader` segment.
 *
 * Segments render as filesystem path components, so they must look like ones:
 * lowercase, no spaces, no punctuation. Truncation is capped at `maxLength` and
 * never leaves a dangling separator.
 */
export function slug(text, maxLength = 28) {
  const cleaned = String(text ?? '')
    .toLowerCase()
    .normalize('NFD')
    .replace(/[̀-ͯ]/g, '')
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')

  if (cleaned.length <= maxLength) return cleaned
  return cleaned.slice(0, maxLength).replace(/-+$/, '')
}

export default slug
```

- [ ] **Step 4: Run the test and verify it passes**

Run: `cd frontend && npx vitest run src/lib/slug.test.js`
Expected: PASS, 6 tests.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/slug.js frontend/src/lib/slug.test.js
git commit -m "feat(web): add slug() for path header segments"
```

---

## Task 3: `PathHeader`

**Files:**
- Create: `frontend/src/components/PathHeader.jsx`
- Test: `frontend/src/components/PathHeader.test.jsx`

**Interfaces:**
- Consumes: `slug()` from `../lib/slug`
- Produces: `<PathHeader segments={[{ label: string, to?: string }]} />`. A segment with no `to` renders as plain text (the current location). Renders nothing when `segments` is empty.

- [ ] **Step 1: Write the failing test**

Create `frontend/src/components/PathHeader.test.jsx`:

```js
import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import PathHeader from './PathHeader'

function renderPath(segments) {
  return render(
    <MemoryRouter>
      <PathHeader segments={segments} />
    </MemoryRouter>,
  )
}

describe('PathHeader', () => {
  it('renders a home root link', () => {
    renderPath([{ label: 'Books', to: '/books' }])
    expect(screen.getByRole('link', { name: '~' })).toHaveAttribute('href', '/')
  })

  it('slugifies segment labels', () => {
    renderPath([{ label: 'The Dispossessed', to: '/books/1' }])
    expect(screen.getByRole('link', { name: 'the-dispossessed' })).toHaveAttribute(
      'href',
      '/books/1',
    )
  })

  it('renders the final segment as text when it has no destination', () => {
    renderPath([
      { label: 'Books', to: '/books' },
      { label: 'Thread 42' },
    ])
    expect(screen.queryByRole('link', { name: 'thread-42' })).not.toBeInTheDocument()
    expect(screen.getByText('thread-42')).toBeInTheDocument()
  })

  it('labels itself as a breadcrumb for assistive tech', () => {
    renderPath([{ label: 'Books', to: '/books' }])
    expect(screen.getByRole('navigation', { name: /breadcrumb/i })).toBeInTheDocument()
  })

  it('renders nothing when there are no segments', () => {
    const { container } = renderPath([])
    expect(container).toBeEmptyDOMElement()
  })
})
```

- [ ] **Step 2: Run the test and verify it fails**

Run: `cd frontend && npx vitest run src/components/PathHeader.test.jsx`
Expected: FAIL — `Failed to resolve import "./PathHeader"`.

- [ ] **Step 3: Write the component**

Create `frontend/src/components/PathHeader.jsx`:

```jsx
import { Link } from 'react-router-dom'
import { slug } from '../lib/slug'

/**
 * The page's location rendered as a filesystem path — `~/books/the-dispossessed`.
 * Replaces breadcrumbs and makes the app's shape legible.
 *
 * Segments are explicit rather than derived from the URL: routes carry ids, but
 * a path wants titles, and only the page knows those.
 *
 * On narrow viewports the middle segments hide (CSS, not JS) and an ellipsis
 * stands in, so the leaf — the part that says where you are — always survives.
 */
function PathHeader({ segments = [] }) {
  if (segments.length === 0) return null

  const middles = segments.slice(0, -1)
  const leaf = segments[segments.length - 1]

  const separator = (
    <span aria-hidden="true" className="text-ink-faint px-0.5">
      /
    </span>
  )

  const segmentClass =
    'text-path hover:text-accent-hover transition-colors duration-fast'

  return (
    <nav aria-label="Breadcrumb" className="text-sm overflow-hidden">
      <ol className="flex items-center">
        <li className="flex items-center">
          <Link to="/" className={segmentClass}>
            ~
          </Link>
        </li>

        {middles.map((seg, i) => (
          <li key={`${seg.label}-${i}`} className="hidden sm:flex items-center min-w-0">
            {separator}
            {seg.to ? (
              <Link to={seg.to} className={`${segmentClass} truncate`}>
                {slug(seg.label)}
              </Link>
            ) : (
              <span className="text-ink-dim truncate">{slug(seg.label)}</span>
            )}
          </li>
        ))}

        {middles.length > 0 && (
          <li className="flex sm:hidden items-center" aria-hidden="true">
            {separator}
            <span className="text-ink-faint">…</span>
          </li>
        )}

        <li className="flex items-center min-w-0">
          {separator}
          {leaf.to ? (
            <Link to={leaf.to} className={`${segmentClass} truncate`}>
              {slug(leaf.label)}
            </Link>
          ) : (
            <span className="text-ink-dim truncate">{slug(leaf.label)}</span>
          )}
        </li>
      </ol>
    </nav>
  )
}

export default PathHeader
```

- [ ] **Step 4: Run the test and verify it passes**

Run: `cd frontend && npx vitest run src/components/PathHeader.test.jsx`
Expected: PASS, 5 tests.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/PathHeader.jsx frontend/src/components/PathHeader.test.jsx
git commit -m "feat(web): add PathHeader filesystem breadcrumb"
```

---

## Task 4: Status store and `StatusBar`

**Files:**
- Create: `frontend/src/store/status.js`
- Create: `frontend/src/components/StatusBar.jsx`
- Modify: `frontend/src/App.jsx`
- Test: `frontend/src/components/StatusBar.test.jsx`

**Interfaces:**
- Consumes: `useAuthStore` from `../store/auth` (for the signed-in username)
- Produces:
  - `useStatusStore` (default export of `store/status.js`) — Zustand store with `{ mode, path, facts, setStatus, resetStatus }`
  - `useStatusBar({ mode, path, facts })` — named export; sets the status on mount, resets on unmount
  - `<StatusBar />` — reads the store; takes no props
  - `mode` is one of `HOME`, `BOOK`, `THREAD`, `GENRE`, `SEARCH`, `PROFILE`, `AUTH`, `404`

- [ ] **Step 1: Write the failing test**

Create `frontend/src/components/StatusBar.test.jsx`:

```js
import { describe, it, expect, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import useStatusStore, { useStatusBar } from '../store/status'
import useAuthStore from '../store/auth'
import StatusBar from './StatusBar'

function Page({ mode, path, facts }) {
  useStatusBar({ mode, path, facts })
  return null
}

beforeEach(() => {
  useStatusStore.getState().resetStatus()
  const { setAuth, logout } = useAuthStore.getState()
  useAuthStore.setState({ user: null, token: null, setAuth, logout }, true)
})

describe('StatusBar', () => {
  it('shows the mode and path a page declares', () => {
    render(
      <>
        <Page mode="BOOK" path="~/books/the-dispossessed" facts={['2 threads']} />
        <StatusBar />
      </>,
    )
    expect(screen.getByText('BOOK')).toBeInTheDocument()
    expect(screen.getByText('~/books/the-dispossessed')).toBeInTheDocument()
    expect(screen.getByText('2 threads')).toBeInTheDocument()
  })

  it('shows the signed-in username', () => {
    const { setAuth, logout } = useAuthStore.getState()
    useAuthStore.setState({ user: { username: 'ada' }, token: 't', setAuth, logout }, true)
    render(
      <>
        <Page mode="HOME" path="~" facts={[]} />
        <StatusBar />
      </>,
    )
    expect(screen.getByText('ada')).toBeInTheDocument()
  })

  it('resets when the declaring page unmounts', () => {
    const { unmount } = render(<Page mode="THREAD" path="~/threads/1" facts={[]} />)
    expect(useStatusStore.getState().mode).toBe('THREAD')
    unmount()
    expect(useStatusStore.getState().mode).toBe('HOME')
    expect(useStatusStore.getState().path).toBe('~')
  })

  it('is exposed to assistive tech as a status region', () => {
    render(<StatusBar />)
    expect(screen.getByRole('status')).toBeInTheDocument()
  })
})
```

- [ ] **Step 2: Run the test and verify it fails**

Run: `cd frontend && npx vitest run src/components/StatusBar.test.jsx`
Expected: FAIL — `Failed to resolve import "../store/status"`.

- [ ] **Step 3: Write the store**

Create `frontend/src/store/status.js`:

```js
import { useEffect } from 'react'
import { create } from 'zustand'

const EMPTY = { mode: 'HOME', path: '~', facts: [] }

/**
 * What the pinned status bar is currently showing.
 *
 * Pages declare their own status through `useStatusBar()` rather than rendering
 * the bar themselves, so the bar mounts once in App and nothing prop-drills
 * through the router.
 */
const useStatusStore = create((set) => ({
  ...EMPTY,
  setStatus: (status) => set(status),
  resetStatus: () => set({ ...EMPTY, facts: [] }),
}))

/**
 * Declare this page's status. Resets on unmount so a stale path can't outlive
 * the page that set it.
 *
 * `facts` is depended on by value, not identity — pages pass array literals,
 * which are new objects on every render.
 */
export function useStatusBar({ mode, path, facts = [] }) {
  const factsKey = facts.join('\u0000')

  useEffect(() => {
    useStatusStore.getState().setStatus({
      mode,
      path,
      facts: factsKey === '' ? [] : factsKey.split('\u0000'),
    })
    return () => useStatusStore.getState().resetStatus()
  }, [mode, path, factsKey])
}

export default useStatusStore
```

- [ ] **Step 4: Write the component**

Create `frontend/src/components/StatusBar.jsx`:

```jsx
import useStatusStore from '../store/status'
import useAuthStore from '../store/auth'

/**
 * The pinned bottom bar — vim/tmux statusline. Fixed, never a flex sibling, so
 * it can't eat viewport on short screens; `body` reserves its height via
 * `--shell-status-h`.
 *
 * The mode block is one of only two places inversion is used (the other is a
 * primary button).
 */
function StatusBar() {
  const { mode, path, facts } = useStatusStore()
  const user = useAuthStore((s) => s.user)

  return (
    <div
      role="status"
      className="fixed bottom-0 inset-x-0 z-30 h-[var(--shell-status-h)] bg-panel border-t border-line-strong
                 flex items-center gap-3 px-3 text-xs"
    >
      <span className="bg-accent text-bg px-2 font-medium shrink-0">{mode}</span>

      <span className="text-path truncate">{path}</span>

      <span className="ml-auto flex items-center gap-3 shrink-0">
        {facts.map((fact) => (
          <span key={fact} className="text-ink-dim hidden sm:inline">
            {fact}
          </span>
        ))}
        {user && (
          <>
            <span aria-hidden="true" className="text-ink-faint hidden sm:inline">
              │
            </span>
            <span className="text-user">{user.username}</span>
          </>
        )}
      </span>
    </div>
  )
}

export default StatusBar
```

- [ ] **Step 5: Mount it in `App.jsx`**

Add the import and render it after `<Suspense>`:

```jsx
import StatusBar from './components/StatusBar'
```

```jsx
      </Suspense>
      <StatusBar />
    </div>
```

- [ ] **Step 6: Run the tests and verify they pass**

Run: `cd frontend && npx vitest run src/components/StatusBar.test.jsx`
Expected: PASS, 4 tests.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/store/status.js frontend/src/components/StatusBar.jsx frontend/src/components/StatusBar.test.jsx frontend/src/App.jsx
git commit -m "feat(web): add pinned StatusBar and per-page status store"
```

---

## Task 5: `DiagnosticFloat`

**Files:**
- Create: `frontend/src/components/DiagnosticFloat.jsx`
- Test: `frontend/src/components/DiagnosticFloat.test.jsx`

**Interfaces:**
- Consumes: the `.float` class from Task 1
- Produces: `<DiagnosticFloat severity="error|warn|info|hint" message={string} source={string?} align="start|end" >{trigger}</DiagnosticFloat>`

**Note for the implementer:** jsdom does not apply Tailwind, so the tooltip is in the DOM regardless of hover state. These tests assert *wiring* (roles, ids, severity text), not visual visibility — visibility is CSS and is checked by hand at the pilot gate.

- [ ] **Step 1: Write the failing test**

Create `frontend/src/components/DiagnosticFloat.test.jsx`:

```js
import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import DiagnosticFloat from './DiagnosticFloat'

describe('DiagnosticFloat', () => {
  it('renders its trigger', () => {
    render(
      <DiagnosticFloat severity="warn" message="edited 2h ago">
        edited
      </DiagnosticFloat>,
    )
    expect(screen.getByText('edited')).toBeInTheDocument()
  })

  it('wires the trigger to the tooltip with aria-describedby', () => {
    render(
      <DiagnosticFloat severity="info" message="posted 3 March 2026">
        2h
      </DiagnosticFloat>,
    )
    const tooltip = screen.getByRole('tooltip')
    const trigger = screen.getByText('2h')
    expect(trigger).toHaveAttribute('aria-describedby', tooltip.id)
  })

  it('names the severity in text, not colour alone', () => {
    render(
      <DiagnosticFloat severity="error" message="failed to load">
        !
      </DiagnosticFloat>,
    )
    expect(screen.getByText(/error/i)).toBeInTheDocument()
  })

  it('renders the dim source line when given one', () => {
    render(
      <DiagnosticFloat severity="warn" message="edited 2h ago" source="thread/42">
        edited
      </DiagnosticFloat>,
    )
    expect(screen.getByText('thread/42')).toBeInTheDocument()
  })

  it('makes the trigger keyboard-focusable', () => {
    render(
      <DiagnosticFloat severity="hint" message="hint text">
        ?
      </DiagnosticFloat>,
    )
    expect(screen.getByText('?')).toHaveAttribute('tabindex', '0')
  })
})
```

- [ ] **Step 2: Run the test and verify it fails**

Run: `cd frontend && npx vitest run src/components/DiagnosticFloat.test.jsx`
Expected: FAIL — `Failed to resolve import "./DiagnosticFloat"`.

- [ ] **Step 3: Write the component**

Create `frontend/src/components/DiagnosticFloat.jsx`:

```jsx
import { useId, useState } from 'react'

/**
 * An nvim-style diagnostic float — the hover primitive for the whole UI.
 *
 * Square border (nvim's `border="single"`), which also keeps the project's
 * no-new-radii rule. Opens on hover AND focus-within so it is keyboard
 * reachable, and toggles on tap for touch, where hover does not exist.
 *
 * The severity is always stated in text for screen readers; the coloured `■` is
 * decorative, because colour never carries meaning alone here.
 */
const SEVERITY = {
  error: { marker: 'text-danger', label: 'Error' },
  warn: { marker: 'text-warning', label: 'Warning' },
  info: { marker: 'text-accent', label: 'Info' },
  hint: { marker: 'text-ink-muted', label: 'Hint' },
}

function DiagnosticFloat({ severity = 'info', message, source, align = 'start', children }) {
  const id = useId()
  const [pinned, setPinned] = useState(false)
  const tone = SEVERITY[severity] ?? SEVERITY.info

  return (
    <span className="relative inline-flex group">
      <span
        tabIndex={0}
        aria-describedby={id}
        onClick={() => setPinned((v) => !v)}
        className="cursor-help underline decoration-dotted decoration-ink-faint underline-offset-2"
      >
        {children}
      </span>

      <span
        role="tooltip"
        id={id}
        className={`float absolute top-full mt-1 z-30 w-max max-w-xs flex-col gap-0.5
                    ${align === 'end' ? 'right-0' : 'left-0'}
                    ${pinned ? 'flex' : 'hidden'} group-hover:flex group-focus-within:flex`}
      >
        <span>
          <span aria-hidden="true" className={tone.marker}>
            ■
          </span>{' '}
          <span className="sr-only">{tone.label}: </span>
          <span className="text-ink">{message}</span>
        </span>
        {source && <span className="text-ink-dim">{source}</span>}
      </span>
    </span>
  )
}

export default DiagnosticFloat
```

- [ ] **Step 4: Run the tests and verify they pass**

Run: `cd frontend && npx vitest run src/components/DiagnosticFloat.test.jsx`
Expected: PASS, 5 tests.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/DiagnosticFloat.jsx frontend/src/components/DiagnosticFloat.test.jsx
git commit -m "feat(web): add nvim-style DiagnosticFloat hover primitive"
```

---

## Task 6: `DataTable`

**Files:**
- Create: `frontend/src/components/DataTable.jsx`
- Test: `frontend/src/components/DataTable.test.jsx`

**Interfaces:**
- Consumes: nothing
- Produces: `<DataTable columns={[{ key, label, align?, width?, sortable?, render }]} rows={[{ id, ...data }]} sort={string?} sortDirection="asc|desc" onSort={(key) => void} caption={string} emptyMessage={string} />`. `render(row)` returns the cell's node. Every row must include a real `<a href>` in at least one cell.

- [ ] **Step 1: Write the failing test**

Create `frontend/src/components/DataTable.test.jsx`:

```js
import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Link } from 'react-router-dom'
import DataTable from './DataTable'

const columns = [
  { key: 'score', label: 'Score', align: 'right', width: 6, sortable: true, render: (r) => r.score },
  {
    key: 'title',
    label: 'Thread',
    sortable: true,
    render: (r) => <Link to={`/books/1/threads/${r.id}`}>{r.title}</Link>,
  },
]

const rows = [
  { id: '1', score: '+42', title: 'Is Anarres actually a utopia?' },
  { id: '2', score: '-3', title: 'Overrated' },
]

function renderTable(props = {}) {
  return render(
    <MemoryRouter>
      <DataTable columns={columns} rows={rows} caption="Discussions" {...props} />
    </MemoryRouter>,
  )
}

describe('DataTable', () => {
  it('renders a row per record', () => {
    renderTable()
    expect(screen.getAllByRole('row')).toHaveLength(3) // header + 2
  })

  it('renders row links as real anchors', () => {
    renderTable()
    expect(screen.getByRole('link', { name: 'Overrated' })).toHaveAttribute(
      'href',
      '/books/1/threads/2',
    )
  })

  it('calls onSort with the column key when a sortable header is clicked', async () => {
    const onSort = vi.fn()
    renderTable({ onSort })
    await userEvent.click(screen.getByRole('button', { name: /sort by score/i }))
    expect(onSort).toHaveBeenCalledWith('score')
  })

  it('exposes the active sort column to assistive tech', () => {
    renderTable({ onSort: vi.fn(), sort: 'score', sortDirection: 'desc' })
    const header = screen.getByRole('columnheader', { name: /score/i })
    expect(header).toHaveAttribute('aria-sort', 'descending')
  })

  it('renders plain headers when no onSort handler is given', () => {
    renderTable()
    expect(screen.queryByRole('button', { name: /sort by/i })).not.toBeInTheDocument()
  })

  it('shows the empty message instead of a table when there are no rows', () => {
    renderTable({ rows: [], emptyMessage: 'No discussions yet.' })
    expect(screen.getByText('No discussions yet.')).toBeInTheDocument()
    expect(screen.queryByRole('table')).not.toBeInTheDocument()
  })

  it('gives the table an accessible caption', () => {
    renderTable()
    expect(screen.getByRole('table', { name: 'Discussions' })).toBeInTheDocument()
  })
})
```

- [ ] **Step 2: Run the test and verify it fails**

Run: `cd frontend && npx vitest run src/components/DataTable.test.jsx`
Expected: FAIL — `Failed to resolve import "./DataTable"`.

- [ ] **Step 3: Write the component**

Create `frontend/src/components/DataTable.jsx`:

```jsx
/**
 * An `ls -l` listing: aligned columns, an underlined header row, and the header
 * itself as the sort control.
 *
 * Below `sm` the table collapses to stacked blocks. A horizontally scrolling
 * table on a phone is the one place this aesthetic genuinely fails, so it is
 * abandoned deliberately rather than scrolled.
 *
 * Cells render real `<a href>` links — never onClick row handlers — so
 * middle-click, keyboard navigation and screen readers all work.
 */
function DataTable({
  columns,
  rows,
  sort,
  sortDirection = 'desc',
  onSort,
  caption,
  emptyMessage = 'Nothing here yet.',
}) {
  if (!rows || rows.length === 0) {
    return <p className="text-ink-dim text-sm py-4">{emptyMessage}</p>
  }

  const alignClass = (align) => (align === 'right' ? 'text-right' : 'text-left')

  return (
    <table className="w-full max-w-table text-sm border-collapse block sm:table">
      <caption className="sr-only">{caption}</caption>

      <thead className="hidden sm:table-header-group">
        <tr className="border-b border-line">
          {columns.map((col) => {
            const active = sort === col.key
            return (
              <th
                key={col.key}
                scope="col"
                aria-sort={
                  !col.sortable || !onSort
                    ? undefined
                    : active
                      ? sortDirection === 'asc'
                        ? 'ascending'
                        : 'descending'
                      : 'none'
                }
                style={col.width ? { width: `${col.width}ch` } : undefined}
                className={`py-2 px-2 font-medium text-xs uppercase tracking-eyebrow text-ink-dim ${alignClass(col.align)}`}
              >
                {col.sortable && onSort ? (
                  <button
                    type="button"
                    onClick={() => onSort(col.key)}
                    aria-label={`Sort by ${col.label}`}
                    className="inline-flex items-center gap-1 hover:text-ink transition-colors duration-fast"
                  >
                    {col.label}
                    <span aria-hidden="true" className="text-ink-faint">
                      {active ? (sortDirection === 'asc' ? '▴' : '▾') : ''}
                    </span>
                  </button>
                ) : (
                  col.label
                )}
              </th>
            )
          })}
        </tr>
      </thead>

      <tbody className="block sm:table-row-group">
        {rows.map((row) => (
          <tr
            key={row.id}
            className="block sm:table-row border-b border-line/60 hover:bg-highlight transition-colors duration-fast"
          >
            {columns.map((col) => (
              <td
                key={col.key}
                className={`block sm:table-cell py-2 px-2 align-top ${alignClass(col.align)}`}
              >
                {col.render(row)}
              </td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  )
}

export default DataTable
```

- [ ] **Step 4: Run the tests and verify they pass**

Run: `cd frontend && npx vitest run src/components/DataTable.test.jsx`
Expected: PASS, 7 tests.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/DataTable.jsx frontend/src/components/DataTable.test.jsx
git commit -m "feat(web): add DataTable ls -l listing with sortable headers"
```

---

## Task 7: `Navbar` title bar and shell metrics

**Files:**
- Modify: `frontend/src/components/Navbar.jsx`
- Modify: `frontend/src/components/AuthLayout.jsx:9`
- Test: `frontend/src/components/Navbar.test.jsx` (existing — must stay green unchanged)

**Interfaces:**
- Consumes: `--shell-nav-h` from Task 1
- Produces: no new exports. `AuthLayout` now sizes itself from `--shell-nav-h` instead of a hardcoded `51px`.

- [ ] **Step 1: Run the existing Navbar tests to establish the baseline**

Run: `cd frontend && npx vitest run src/components/Navbar.test.jsx`
Expected: PASS, 2 tests. These must still pass after the rewrite — the logout button's accessible name stays `Out`.

- [ ] **Step 2: Rewrite `Navbar.jsx`**

```jsx
import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import useAuthStore from '../store/auth'
import client from '../api/client'

function Navbar() {
  const [query, setQuery] = useState('')
  const navigate = useNavigate()
  const user = useAuthStore((s) => s.user)
  const logout = useAuthStore((s) => s.logout)

  const handleSearch = (e) => {
    e.preventDefault()
    if (query.trim()) {
      navigate(`/search?q=${encodeURIComponent(query.trim())}`)
      setQuery('')
    }
  }

  return (
    <nav className="bg-panel border-b border-line-strong sticky top-0 z-40 h-[var(--shell-nav-h)]">
      <div className="max-w-shell mx-auto px-4 h-full flex items-center gap-6">
        <Link
          to="/"
          className="shrink-0 font-bold text-sm text-ink hover:text-accent transition-colors duration-fast"
        >
          MARGIN<span className="text-accent">//</span>
        </Link>

        {/* type="search" is load-bearing: it keeps this out of getByRole('textbox'),
            which the auth e2e specs rely on to find the email field. */}
        <form onSubmit={handleSearch} className="prompt flex-1 max-w-sm hidden sm:flex">
          <input
            type="search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="search books"
            aria-label="Search books"
            className="input border-0 bg-transparent px-0 py-1 focus:border-0"
          />
          <button
            type="submit"
            className="text-ink-dim hover:text-accent text-sm transition-colors duration-fast shrink-0"
            aria-label="Search"
          >
            ↵
          </button>
        </form>

        <div className="flex items-center gap-4 ml-auto">
          {user ? (
            <>
              <Link to={`/profile/${user.username}`} className="flex items-center gap-2 group">
                <span className="w-5 h-5 bg-user text-bg flex items-center justify-center text-xs font-bold shrink-0">
                  {user.username[0].toUpperCase()}
                </span>
                <span className="text-sm text-user group-hover:text-accent-hover transition-colors duration-fast hidden sm:block">
                  {user.username}
                </span>
              </Link>
              <button
                onClick={async () => {
                  try { await client.post('/auth/logout') } catch { /* JWT is stateless — clear locally regardless */ }
                  logout()
                }}
                className="text-xs text-ink-dim hover:text-danger transition-colors duration-fast uppercase tracking-eyebrow"
              >
                Out
              </button>
            </>
          ) : (
            <>
              <Link to="/login" className="text-sm text-ink-dim hover:text-ink transition-colors duration-fast">
                Sign in
              </Link>
              <Link to="/register" className="btn-primary text-xs px-3 py-1">
                Join
              </Link>
            </>
          )}
        </div>
      </div>
    </nav>
  )
}

export default Navbar
```

- [ ] **Step 3: Fix the hardcoded navbar height in `AuthLayout.jsx`**

Replace line 9's `min-h-[calc(100vh-51px)]` with a variable-driven value:

```jsx
    <div className="min-h-[calc(100vh-var(--shell-nav-h))] bg-bg flex items-center justify-center px-4 py-16">
```

- [ ] **Step 4: Run the full unit suite**

Run: `cd frontend && npm test`
Expected: PASS — `Navbar.test.jsx` unchanged and green, all other suites green.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/Navbar.jsx frontend/src/components/AuthLayout.jsx
git commit -m "feat(web): terminal title bar, prompt search, shell height variable

AuthLayout no longer hardcodes the navbar's 51px; both read --shell-nav-h."
```

---

## Task 8: `VoteControl` `row` variant

**Files:**
- Modify: `frontend/src/components/VoteControl.jsx`
- Test: `frontend/src/components/VoteControl.test.jsx` (existing, extended)

**Interfaces:**
- Consumes: tokens from Task 1
- Produces: `<VoteControl variant="inline|rail|row" />`. `row` is a horizontal `↑ +42 ↓` for `DataTable`'s score column. Score text gains an explicit `+` for positive values; negatives keep an ASCII `-`.

- [ ] **Step 1: Add the failing tests**

Append to `frontend/src/components/VoteControl.test.jsx`, inside the existing `describe`:

```js
  it('renders a row variant for table cells', () => {
    render(<VoteControl variant="row" score={42} myVote={0} onVote={() => {}} />)
    expect(screen.getByText('+42')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /upvote/i })).toBeInTheDocument()
  })

  it('signs positive scores and keeps negatives ASCII', () => {
    const { rerender } = render(<VoteControl score={7} myVote={0} onVote={() => {}} />)
    expect(screen.getByText('+7')).toBeInTheDocument()
    rerender(<VoteControl score={-7} myVote={0} onVote={() => {}} />)
    expect(screen.getByText('-7')).toBeInTheDocument()
  })

  it('renders zero without a sign', () => {
    render(<VoteControl score={0} myVote={0} onVote={() => {}} />)
    expect(screen.getByText('0')).toBeInTheDocument()
  })
```

**Important:** the existing test `expect(screen.getByText('-2'))` must keep passing — the minus stays ASCII `-` (U+002D), never `−` (U+2212).

- [ ] **Step 2: Run the tests and verify the new ones fail**

Run: `cd frontend && npx vitest run src/components/VoteControl.test.jsx`
Expected: FAIL on the three new tests (`+42`, `+7` not found); the five existing tests still PASS.

- [ ] **Step 3: Update `VoteControl.jsx`**

Replace the component body (keep the existing file header comment, adding the `row` variant to its list):

```jsx
function VoteControl({ score = 0, myVote = 0, onVote, disabled, pending, variant = 'inline' }) {
  const isRail = variant === 'rail'
  const isRow = variant === 'row'

  const cast = (value) => (e) => {
    // Thread rows wrap a <Link>; don't navigate on a vote.
    e.preventDefault()
    e.stopPropagation()
    if (!disabled && !pending) onVote(myVote === value ? 0 : value)
  }

  // Sign is carried in text, not colour alone. ASCII hyphen, never U+2212.
  const label = score > 0 ? `+${score}` : String(score)

  const scoreTone =
    score > 0 ? 'text-ok' : score < 0 ? 'text-danger' : 'text-ink-dim'

  const arrow = (active, tone) =>
    `leading-none text-xs transition-colors duration-fast disabled:cursor-default ${
      active ? tone : 'text-ink-muted hover:text-ink'
    } ${isRow ? 'opacity-0 group-hover:opacity-100 focus:opacity-100' : ''}`

  const wrapper = isRail
    ? 'flex flex-col items-center justify-center gap-1 shrink-0 w-14 border-r border-line py-4 hover:bg-highlight transition-colors duration-fast'
    : isRow
      ? 'group inline-flex items-center gap-1 justify-end tabular-nums'
      : 'flex flex-col items-center gap-0.5 shrink-0 w-8 pt-0.5'

  return (
    <div className={wrapper}>
      <button
        onClick={cast(1)}
        disabled={disabled || pending}
        aria-label="Upvote"
        aria-pressed={myVote === 1}
        title={disabled ? 'Sign in to vote' : 'Upvote'}
        className={arrow(myVote === 1, 'text-ok')}
      >
        ↑
      </button>
      <span
        className={`font-medium leading-none tabular-nums ${scoreTone} ${
          isRail ? 'text-sm' : 'text-xs'
        }`}
      >
        {label}
      </span>
      <button
        onClick={cast(-1)}
        disabled={disabled || pending}
        aria-label="Downvote"
        aria-pressed={myVote === -1}
        title={disabled ? 'Sign in to vote' : 'Downvote'}
        className={arrow(myVote === -1, 'text-danger')}
      >
        ↓
      </button>
    </div>
  )
}
```

For the `row` variant the arrows render before and after the score in DOM order, which is the horizontal `↑ +42 ↓` reading order.

- [ ] **Step 4: Run the tests and verify they pass**

Run: `cd frontend && npx vitest run src/components/VoteControl.test.jsx`
Expected: PASS, 8 tests.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/VoteControl.jsx frontend/src/components/VoteControl.test.jsx
git commit -m "feat(web): add VoteControl row variant and signed scores

Scores carry their sign in text so vote direction never depends on colour."
```

---

## Task 9: `Post` — reply tree, relative time, diagnostic float

**Files:**
- Modify: `frontend/src/components/Post.jsx`
- Test: `frontend/src/components/Post.test.jsx` (create)

**Interfaces:**
- Consumes: `DiagnosticFloat` (Task 5), `VoteControl` (Task 8)
- Produces: `Post` keeps its `{ post, threadId, depth }` props. New named export `relativeTime(dateStr, now = new Date())` returning `2h`, `5d`, `3mo`, or `now`.

- [ ] **Step 1: Write the failing test**

Create `frontend/src/components/Post.test.jsx`:

```js
import { describe, it, expect, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import useAuthStore from '../store/auth'
import Post, { relativeTime } from './Post'

function renderPost(post) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <Post post={post} threadId="t1" depth={0} />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  const { setAuth, logout } = useAuthStore.getState()
  useAuthStore.setState({ user: null, token: null, setAuth, logout }, true)
})

describe('relativeTime', () => {
  const now = new Date('2026-09-23T12:00:00Z')

  it('renders hours within a day', () => {
    expect(relativeTime('2026-09-23T10:00:00Z', now)).toBe('2h')
  })

  it('renders days within a month', () => {
    expect(relativeTime('2026-09-18T12:00:00Z', now)).toBe('5d')
  })

  it('renders months beyond thirty days', () => {
    expect(relativeTime('2026-06-23T12:00:00Z', now)).toBe('3mo')
  })

  it('renders minutes under an hour', () => {
    expect(relativeTime('2026-09-23T11:20:00Z', now)).toBe('40m')
  })

  it('returns an empty string for missing dates', () => {
    expect(relativeTime(null, now)).toBe('')
  })
})

describe('Post', () => {
  const post = {
    id: 'p1',
    content: 'Le Guin never lets the reader settle.',
    score: 8,
    my_vote: 0,
    author: 'kevin',
    created_at: '2026-09-23T10:00:00Z',
    replies: [],
  }

  it('shows the author and the post body', () => {
    renderPost(post)
    expect(screen.getByText('kevin')).toBeInTheDocument()
    expect(screen.getByText(/never lets the reader settle/)).toBeInTheDocument()
  })

  it('exposes the absolute timestamp through a tooltip', () => {
    renderPost(post)
    expect(screen.getByRole('tooltip')).toBeInTheDocument()
  })

  it('draws a tree elbow for replies and hides it from assistive tech', () => {
    const { container } = renderPost({
      ...post,
      replies: [{ ...post, id: 'p2', author: 'mara', replies: [] }],
    })
    const elbow = container.querySelector('[data-testid="tree-elbow"]')
    expect(elbow).toBeInTheDocument()
    expect(elbow).toHaveAttribute('aria-hidden', 'true')
  })
})
```

- [ ] **Step 2: Run the test and verify it fails**

Run: `cd frontend && npx vitest run src/components/Post.test.jsx`
Expected: FAIL — `relativeTime` is not exported.

- [ ] **Step 3: Rewrite `Post.jsx`**

```jsx
import { useState } from 'react'
import { useVotePost } from '../api/threads'
import useAuthStore from '../store/auth'
import PostComposer from './PostComposer'
import VoteControl from './VoteControl'
import DiagnosticFloat from './DiagnosticFloat'

/**
 * Terminal-style age: `40m`, `2h`, `5d`, `3mo`. The absolute timestamp is not
 * lost — it moves into the diagnostic float on hover/focus.
 */
export function relativeTime(dateStr, now = new Date()) {
  if (!dateStr) return ''
  const then = new Date(dateStr)
  const seconds = Math.max(0, Math.floor((now - then) / 1000))
  if (seconds < 60) return 'now'
  const minutes = Math.floor(seconds / 60)
  if (minutes < 60) return `${minutes}m`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours}h`
  const days = Math.floor(hours / 24)
  if (days < 30) return `${days}d`
  const months = Math.floor(days / 30)
  if (months < 12) return `${months}mo`
  return `${Math.floor(months / 12)}y`
}

function absoluteTime(dateStr) {
  if (!dateStr) return ''
  return new Date(dateStr).toLocaleString('en-GB', {
    day: 'numeric',
    month: 'long',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function Post({ post, threadId, depth = 0 }) {
  const { id, content, score = 0, my_vote = 0, author, created_at, replies = [] } = post
  const [showReply, setShowReply] = useState(false)
  const user = useAuthStore((s) => s.user)
  const voteMutation = useVotePost()

  const handleVote = (value) => {
    if (user) voteMutation.mutate({ id, value, threadId })
  }

  return (
    <div className="py-3">
      <div className="flex items-start gap-3">
        <VoteControl
          score={score}
          myVote={my_vote}
          onVote={handleVote}
          disabled={!user}
          pending={voteMutation.isPending}
        />

        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-1.5 text-xs">
            <span className="text-user font-medium">{author}</span>
            <span aria-hidden="true" className="text-ink-faint">·</span>
            <span className="text-ink-dim">
              <DiagnosticFloat
                severity="hint"
                message={absoluteTime(created_at)}
                source={`post/${id}`}
              >
                {relativeTime(created_at)}
              </DiagnosticFloat>
            </span>
          </div>

          <p className="text-ink text-sm leading-relaxed whitespace-pre-wrap max-w-prose">
            {content}
          </p>

          {user && (
            <button
              onClick={() => setShowReply((v) => !v)}
              className="mt-2 text-xs text-ink-dim hover:text-accent transition-colors duration-fast"
            >
              {showReply ? 'cancel' : 'reply'}
            </button>
          )}

          {showReply && (
            <div className="mt-3">
              <PostComposer
                threadId={threadId}
                parentId={id}
                placeholder="Write a reply..."
                onSuccess={() => setShowReply(false)}
              />
            </div>
          )}
        </div>
      </div>

      {/* Replies. The elbow is a real glyph — it aligns because the whole UI is
          monospaced — but the vertical rail is a CSS border, since a border
          stretches to content height and a repeated character does not.
          MARGIN is capped at two levels, so this cannot nest further. */}
      {replies.length > 0 && (
        <ul className="mt-2 ml-8 border-l border-line-strong list-none">
          {replies.map((reply, i) => {
            const isLast = i === replies.length - 1
            return (
              <li
                key={reply.id}
                // The rail is one continuous border on the <ul>, so the last
                // child paints a bg-coloured stripe over its remainder — that is
                // what makes `└─` actually terminate the branch.
                className={`relative pl-6 ${
                  isLast
                    ? 'after:absolute after:left-[-1px] after:top-5 after:bottom-0 after:w-px after:bg-bg after:content-[""]'
                    : ''
                }`}
              >
                <span
                  data-testid="tree-elbow"
                  aria-hidden="true"
                  className="absolute left-0 top-4 text-ink-faint select-none leading-none"
                >
                  {isLast ? '└─' : '├─'}
                </span>
                <Post post={reply} threadId={threadId} depth={depth + 1} />
              </li>
            )
          })}
        </ul>
      )}
    </div>
  )
}

export default Post
```

- [ ] **Step 4: Run the tests and verify they pass**

Run: `cd frontend && npx vitest run src/components/Post.test.jsx`
Expected: PASS, 8 tests.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/Post.jsx frontend/src/components/Post.test.jsx
git commit -m "feat(web): glyph-elbow reply tree, relative post ages

Absolute timestamps move into a DiagnosticFloat rather than being dropped."
```

---

## Task 10: `PostComposer` prompt

**Files:**
- Modify: `frontend/src/components/PostComposer.jsx`

**Interfaces:**
- Consumes: `.prompt`, `.input`, `.btn-primary` from Task 1
- Produces: unchanged props and behaviour. The submit button's accessible name stays `Post`.

- [ ] **Step 1: Update the composer's presentation**

Replace the returned JSX (logic above it is unchanged):

```jsx
  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-2">
      <div className="flex gap-2 items-start">
        <span aria-hidden="true" className="text-accent pt-2 select-none">
          &gt;
        </span>
        <textarea
          value={content}
          onChange={(e) => setContent(e.target.value)}
          placeholder={placeholder}
          rows={3}
          className="input resize-none max-w-prose"
        />
      </div>
      <div className="flex justify-end">
        <button type="submit" disabled={mutation.isPending || !content.trim()} className="btn-primary">
          {mutation.isPending ? 'Posting...' : 'Post'}
        </button>
      </div>
      {mutation.isError && (
        <p className="text-danger text-xs">{errorMessage(mutation.error, 'Failed to post.')}</p>
      )}
    </form>
  )
```

Also update the signed-out branch to use `text-accent` instead of `text-accent-ink`:

```jsx
    return (
      <p className="text-ink-dim text-sm py-2">
        <Link to="/login" className="text-accent hover:underline">Log in</Link> to post.
      </p>
    )
```

- [ ] **Step 2: Verify the reply e2e contract still holds**

Run: `cd frontend && npm test`
Expected: PASS. The submit button's accessible name is still `Post`, which `e2e/reply.spec.js:21` requires.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/PostComposer.jsx
git commit -m "feat(web): prompt-style post composer"
```

---

## Task 11: `Thread` page — PILOT

**Files:**
- Modify: `frontend/src/pages/Thread.jsx`

**Interfaces:**
- Consumes: `PathHeader` (Task 3), `useStatusBar` (Task 4), `Post` (Task 9), `PostComposer` (Task 10)
- Produces: nothing new

- [ ] **Step 1: Rewrite `Thread.jsx`**

```jsx
import { useParams, Link } from 'react-router-dom'
import { useThread } from '../api/threads'
import Post from '../components/Post'
import PostComposer from '../components/PostComposer'
import PathHeader from '../components/PathHeader'
import { useStatusBar } from '../store/status'
import { slug } from '../lib/slug'

function Thread() {
  const { id, threadId } = useParams()
  const resolvedId = threadId || id
  const { data: thread, isLoading, isError } = useThread(resolvedId)

  const posts = thread?.posts || []
  const anchor = thread?.book?.title || thread?.genre?.name || ''

  useStatusBar({
    mode: 'THREAD',
    path: anchor ? `~/${slug(anchor)}/threads/${resolvedId}` : `~/threads/${resolvedId}`,
    facts: [`${posts.length} posts`],
  })

  if (isLoading) {
    return (
      <main className="max-w-prose mx-auto px-4 py-8">
        <div className="animate-pulse flex flex-col gap-4">
          <div className="h-8 bg-panel w-2/3" />
          <div className="h-4 bg-panel w-1/4" />
          {[1, 2, 3].map((i) => (
            <div key={i} className="h-24 border border-line bg-panel" />
          ))}
        </div>
      </main>
    )
  }

  if (isError || !thread) {
    return (
      <main className="max-w-prose mx-auto px-4 py-8">
        <p className="alert-danger">Failed to load thread.</p>
      </main>
    )
  }

  const topLevelPosts = posts.filter((p) => !p.parent_id)

  const segments = []
  if (thread.book) {
    segments.push({ label: 'books', to: '/' })
    segments.push({ label: thread.book.title, to: `/books/${thread.book.id}` })
  } else if (thread.genre) {
    segments.push({ label: 'genres', to: '/' })
    segments.push({ label: thread.genre.name, to: `/genres/${thread.genre.slug}` })
  }
  segments.push({ label: `thread ${resolvedId}` })

  return (
    <main className="max-w-shell mx-auto px-4 py-6 flex flex-col gap-6">
      <PathHeader segments={segments} />

      <header className="border-b border-line pb-4 flex flex-col gap-2">
        {/* Serif is reserved for BOOK titles. A thread is structure, so it is mono. */}
        <h1 className="text-xl md:text-2xl text-ink leading-snug font-medium max-w-prose">
          {thread.title}
        </h1>
        <div className="flex items-center gap-3 text-xs">
          {thread.author && <span className="text-user">{thread.author}</span>}
          <span aria-hidden="true" className="text-ink-faint">·</span>
          <span className={thread.score > 0 ? 'text-ok' : thread.score < 0 ? 'text-danger' : 'text-ink-dim'}>
            {thread.score > 0 ? `+${thread.score}` : String(thread.score ?? 0)} points
          </span>
          <span aria-hidden="true" className="text-ink-faint">·</span>
          <span className="text-ink-dim">{posts.length} posts</span>
        </div>
      </header>

      <div className="flex flex-col divide-y divide-line">
        {topLevelPosts.length === 0 && (
          <p className="text-ink-dim text-sm py-4">No posts yet. Be the first to reply.</p>
        )}
        {topLevelPosts.map((post) => (
          <Post key={post.id} post={post} threadId={resolvedId} depth={0} />
        ))}
      </div>

      <div className="border-t border-line pt-5 flex flex-col gap-3">
        <h2 className="text-xs uppercase tracking-eyebrow text-ink-dim">Add a reply</h2>
        <PostComposer threadId={resolvedId} placeholder="Join the discussion..." />
      </div>
    </main>
  )
}

export default Thread
```

- [ ] **Step 2: Run the full unit suite and build**

Run: `cd frontend && npm test && npm run build`
Expected: both clean.

- [ ] **Step 3: Run the app and look at a real thread**

```bash
docker compose up --build
```

Open a book, open a thread with at least three posts and one reply. Check:
- A full paragraph of prose is comfortable to read in JetBrains Mono at 72ch
- The tree elbows align with the rail and the last reply's rail is clipped
- Hovering a timestamp opens the float; tabbing to it opens the float too
- The status bar reads `THREAD ~/…/threads/…  N posts │ username`
- At 360px there is no horizontal scroll

- [ ] **Step 4: Commit**

```bash
git add frontend/src/pages/Thread.jsx
git commit -m "feat(web): terminal Thread page (pilot)"
```

- [ ] **Step 5: STOP — pilot review gate**

**Do not continue to Task 12 without human sign-off.** Report back with what the thread page looks like and any friction found. The one question this gate exists to answer: **does reading a real discussion in monospace feel good?**

If it does not, the fallback is the spec's rejected "mono chrome, proportional prose" variant — add a `sans` family to `tailwind.config.js` and apply it to `Post`'s body paragraph and `Book`'s description. That is a one-token change precisely because it was anticipated.

---

## Task 12: Extract `ThreadModal`

`Book.jsx:10` and `Genre.jsx:118` carry near-identical thread-creation modals. Both pages are about to be rewritten, so they collapse into one component now — before either rewrite, so neither inherits the duplicate.

**Files:**
- Create: `frontend/src/components/ThreadModal.jsx`
- Test: `frontend/src/components/ThreadModal.test.jsx`

**Interfaces:**
- Consumes: `useCreateThread` from `../api/threads`, `errorMessage` from `../api/errors`
- Produces: `<ThreadModal target={{ book_id }} | {{ genre_slug }} onClose={fn} onCreated={(thread) => void} title="Start a Thread" submitLabel="Create Thread" />`. The default `title` and `submitLabel` are the exact strings `e2e/thread.spec.js` clicks.

- [ ] **Step 1: Write the failing test**

Create `frontend/src/components/ThreadModal.test.jsx`:

```js
import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import ThreadModal from './ThreadModal'

function renderModal(props = {}) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <ThreadModal target={{ book_id: '1' }} onClose={() => {}} onCreated={() => {}} {...props} />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('ThreadModal', () => {
  it('uses the exact heading and submit labels the e2e suite clicks', () => {
    renderModal()
    expect(screen.getByRole('heading', { name: 'Start a Thread' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Create Thread' })).toBeInTheDocument()
  })

  it('disables submit until a title is typed', async () => {
    renderModal()
    const submit = screen.getByRole('button', { name: 'Create Thread' })
    expect(submit).toBeDisabled()
    await userEvent.type(screen.getByPlaceholderText(/thread title/i), 'A title')
    expect(submit).toBeEnabled()
  })

  it('closes when cancel is pressed', async () => {
    const onClose = vi.fn()
    renderModal({ onClose })
    await userEvent.click(screen.getByRole('button', { name: /cancel/i }))
    expect(onClose).toHaveBeenCalled()
  })

  it('is exposed as a modal dialog', () => {
    renderModal()
    expect(screen.getByRole('dialog')).toHaveAttribute('aria-modal', 'true')
  })
})
```

- [ ] **Step 2: Run the test and verify it fails**

Run: `cd frontend && npx vitest run src/components/ThreadModal.test.jsx`
Expected: FAIL — `Failed to resolve import "./ThreadModal"`.

- [ ] **Step 3: Write the component**

Create `frontend/src/components/ThreadModal.jsx`:

```jsx
import { useState } from 'react'
import { useCreateThread } from '../api/threads'
import { errorMessage } from '../api/errors'

/**
 * Thread creation for both books and genres. `target` is whichever key the API
 * expects — `{ book_id }` or `{ genre_slug }` — and is spread into the payload.
 *
 * The default labels are load-bearing: `e2e/thread.spec.js` clicks
 * "Start a Thread" and "Create Thread" by accessible name.
 */
function ThreadModal({
  target,
  onClose,
  onCreated,
  title = 'Start a Thread',
  submitLabel = 'Create Thread',
}) {
  const [threadTitle, setThreadTitle] = useState('')
  const [body, setBody] = useState('')
  const mutation = useCreateThread()

  const handleSubmit = (e) => {
    e.preventDefault()
    if (!threadTitle.trim()) return
    mutation.mutate(
      { ...target, title: threadTitle.trim(), content: body.trim() },
      { onSuccess: (data) => onCreated(data) },
    )
  }

  return (
    <div className="fixed inset-0 bg-bg/90 flex items-center justify-center z-50 p-4">
      <div
        role="dialog"
        aria-modal="true"
        aria-label={title}
        className="panel w-full max-w-lg flex flex-col gap-5 p-6"
      >
        <div className="flex items-center justify-between">
          <h2 className="text-sm uppercase tracking-eyebrow text-ink">{title}</h2>
          <button onClick={onClose} aria-label="Close" className="text-ink-dim hover:text-danger">
            ✕
          </button>
        </div>

        <form onSubmit={handleSubmit} className="flex flex-col gap-3">
          <input
            type="text"
            value={threadTitle}
            onChange={(e) => setThreadTitle(e.target.value)}
            placeholder="Thread title"
            required
            className="input"
          />
          <textarea
            value={body}
            onChange={(e) => setBody(e.target.value)}
            placeholder="Opening post (optional)"
            rows={4}
            className="input resize-none"
          />
          {mutation.isError && (
            <p className="text-danger text-xs">
              {errorMessage(mutation.error, 'Failed to create thread.')}
            </p>
          )}
          <div className="flex justify-end gap-2">
            <button type="button" onClick={onClose} className="btn-ghost">
              Cancel
            </button>
            <button
              type="submit"
              disabled={mutation.isPending || !threadTitle.trim()}
              className="btn-primary"
            >
              {mutation.isPending ? 'Creating...' : submitLabel}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

export default ThreadModal
```

- [ ] **Step 4: Run the tests and verify they pass**

Run: `cd frontend && npx vitest run src/components/ThreadModal.test.jsx`
Expected: PASS, 4 tests.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/ThreadModal.jsx frontend/src/components/ThreadModal.test.jsx
git commit -m "refactor(web): extract shared ThreadModal from Book and Genre"
```

---

## Task 13: `BookCard` and `ShelfButton`

**Files:**
- Modify: `frontend/src/components/BookCard.jsx`
- Modify: `frontend/src/components/ShelfButton.jsx`

**Interfaces:**
- Consumes: `.float`, `.btn-secondary`, tokens
- Produces: unchanged props for both

- [ ] **Step 1: Retokenise `BookCard.jsx`**

Covers stay large and full colour — the art is never dimmed and the frame does the reacting. Change only the classes:

- Cover wrapper: `bg-surface border border-line group-hover:border-accent` → `bg-panel border border-line group-hover:border-accent`
- No-cover fallback text: `font-serif italic text-ink-muted text-xs` → `font-serif italic text-ink-dim text-xs`
- Title: keep `font-serif` (it is a book title), change `group-hover:text-accent-ink` → `group-hover:text-accent`
- Author: `text-ink-muted text-xs uppercase tracking-widest` → `text-ink-dim text-xs lowercase tracking-eyebrow`

- [ ] **Step 2: Restyle `ShelfButton.jsx`**

Replace the labels map and the two rendered branches:

```jsx
const SHELF_LABELS = {
  want_to_read: 'want to read',
  reading: 'reading',
  read: 'read',
}

const SHELF_TONE = {
  want_to_read: 'text-ink-dim',
  reading: 'text-warning',
  read: 'text-ok',
}
```

Signed-out branch:

```jsx
    return (
      <Link to="/login" className="btn-secondary self-start">
        Log in to add to shelf
      </Link>
    )
```

Trigger button and dropdown:

```jsx
      <button
        onClick={() => setOpen((v) => !v)}
        disabled={isPending}
        aria-expanded={open}
        className="btn-secondary text-xs"
      >
        {isPending ? 'Saving...' : label}
        <span aria-hidden="true" className="text-ink-faint">{open ? '▴' : '▾'}</span>
      </button>

      {open && (
        <div className="float absolute top-full left-0 mt-1 z-20 min-w-full p-0">
          {Object.entries(SHELF_LABELS).map(([status, lbl]) => (
            <button
              key={status}
              onClick={() => handleSelect(status)}
              className={`block w-full text-left px-3 py-1.5 text-xs hover:bg-highlight transition-colors duration-fast ${
                currentStatus === status ? SHELF_TONE[status] : 'text-ink-dim'
              }`}
            >
              {lbl}
            </button>
          ))}
          {currentStatus && (
            <button
              onClick={() => handleSelect(null)}
              className="block w-full text-left px-3 py-1.5 text-xs text-danger hover:bg-highlight transition-colors duration-fast border-t border-line"
            >
              remove
            </button>
          )}
        </div>
      )}
```

The `label` line changes to lowercase too:

```jsx
  const label = currentStatus ? SHELF_LABELS[currentStatus] : 'add to library'
```

- [ ] **Step 3: Run the suite**

Run: `cd frontend && npm test && npm run build`
Expected: both clean.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/BookCard.jsx frontend/src/components/ShelfButton.jsx
git commit -m "feat(web): terminal BookCard frame and bracketed ShelfButton"
```

---

## Task 14: `Book` page

**Files:**
- Modify: `frontend/src/pages/Book.jsx`

**Interfaces:**
- Consumes: `PathHeader`, `useStatusBar`, `DataTable`, `ThreadModal`, `VoteControl` (`row`), `ShelfButton`
- Produces: nothing new. Deletes the local `CreateThreadModal`.

- [ ] **Step 1: Rewrite `Book.jsx`**

```jsx
import { useState } from 'react'
import { useParams, useNavigate, Link } from 'react-router-dom'
import { useBook, useBookThreads } from '../api/books'
import { useVoteThread } from '../api/threads'
import ShelfButton from '../components/ShelfButton'
import PathHeader from '../components/PathHeader'
import DataTable from '../components/DataTable'
import ThreadModal from '../components/ThreadModal'
import VoteControl from '../components/VoteControl'
import { relativeTime } from '../components/Post'
import { useStatusBar } from '../store/status'
import { slug } from '../lib/slug'
import useAuthStore from '../store/auth'

function Book() {
  const { id } = useParams()
  const navigate = useNavigate()
  const [showModal, setShowModal] = useState(false)
  const user = useAuthStore((s) => s.user)
  const voteMutation = useVoteThread()

  const { data: book, isLoading: bookLoading, isError: bookError } = useBook(id)
  const { data: threads, isLoading: threadsLoading } = useBookThreads(id)

  const threadCount = threads?.length ?? 0

  useStatusBar({
    mode: 'BOOK',
    path: book ? `~/books/${slug(book.title)}` : '~/books',
    facts: [`${threadCount} threads`],
  })

  if (bookLoading) {
    return (
      <main className="max-w-shell mx-auto px-4 py-8">
        <div className="animate-pulse flex gap-8">
          <div className="w-44 aspect-[2/3] bg-panel shrink-0" />
          <div className="flex flex-col gap-3 flex-1">
            <div className="h-10 bg-panel w-2/3" />
            <div className="h-4 bg-panel w-1/3" />
            <div className="h-20 bg-panel w-full mt-4" />
          </div>
        </div>
      </main>
    )
  }

  if (bookError || !book) {
    return (
      <main className="max-w-shell mx-auto px-4 py-8">
        <p className="alert-danger">Failed to load book.</p>
      </main>
    )
  }

  const columns = [
    {
      key: 'score',
      label: 'Score',
      align: 'right',
      width: 8,
      render: (row) => (
        <VoteControl
          variant="row"
          score={row.score ?? 0}
          myVote={row.my_vote ?? 0}
          onVote={(value) => user && voteMutation.mutate({ id: row.id, value, bookId: id })}
          disabled={!user}
          pending={voteMutation.isPending}
        />
      ),
    },
    {
      key: 'title',
      label: 'Thread',
      render: (row) => (
        <Link
          to={`/books/${id}/threads/${row.id}`}
          className="text-ink hover:text-accent transition-colors duration-fast"
        >
          {row.title}
        </Link>
      ),
    },
    {
      key: 'author',
      label: 'By',
      width: 16,
      render: (row) => <span className="text-user">{row.author}</span>,
    },
    {
      key: 'post_count',
      label: 'Repl',
      align: 'right',
      width: 6,
      render: (row) => <span className="text-ink-dim tabular-nums">{row.post_count ?? 0}</span>,
    },
    {
      key: 'created_at',
      label: 'Age',
      align: 'right',
      width: 6,
      render: (row) => <span className="text-ink-dim tabular-nums">{relativeTime(row.created_at)}</span>,
    },
  ]

  return (
    <main className="max-w-shell mx-auto px-4 py-6 flex flex-col gap-10">
      <PathHeader
        segments={[{ label: 'books', to: '/' }, { label: book.title }]}
      />

      {/* The cover is the only saturated thing on the page and stays that way —
          large, full colour, never dimmed. */}
      <section className="flex flex-col sm:flex-row gap-8">
        <div className="shrink-0 w-44 sm:w-56">
          {book.cover_url ? (
            <img src={book.cover_url} alt={book.title} className="w-full border border-line" />
          ) : (
            <div className="w-full aspect-[2/3] bg-panel border border-line flex items-center justify-center text-ink-dim text-xs">
              No Cover
            </div>
          )}
        </div>

        <div className="flex flex-col gap-4 flex-1 min-w-0">
          <div className="flex flex-col gap-1">
            {/* Serif is reserved for works — this is the one place it appears. */}
            <h1 className="font-serif text-3xl md:text-4xl text-ink leading-tight">{book.title}</h1>
            {book.subtitle && <p className="text-ink-dim text-sm">{book.subtitle}</p>}
            <p className="text-user text-sm lowercase tracking-eyebrow mt-1">{book.author}</p>
          </div>

          <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-0.5 text-xs max-w-sm">
            {book.published_year && (
              <>
                <dt className="text-ink-dim">year</dt>
                <dd className="text-ink tabular-nums">{book.published_year}</dd>
              </>
            )}
            {book.publisher && (
              <>
                <dt className="text-ink-dim">publisher</dt>
                <dd className="text-ink truncate">{book.publisher}</dd>
              </>
            )}
            {book.page_count && (
              <>
                <dt className="text-ink-dim">pages</dt>
                <dd className="text-ink tabular-nums">{book.page_count}</dd>
              </>
            )}
            <dt className="text-ink-dim">threads</dt>
            <dd className="text-path tabular-nums">{threadCount}</dd>
          </dl>

          {book.categories?.length > 0 && (
            <div className="flex flex-wrap gap-x-3 gap-y-1 text-xs">
              {book.categories.map((category) => (
                <span key={category} className="text-ink-dim">
                  <span aria-hidden="true" className="text-ink-faint">[</span>
                  {category.toLowerCase()}
                  <span aria-hidden="true" className="text-ink-faint">]</span>
                </span>
              ))}
            </div>
          )}

          {book.description && (
            <p className="text-ink-dim text-sm leading-relaxed max-w-prose">{book.description}</p>
          )}

          <ShelfButton bookId={id} currentStatus={book.shelf_status} />
        </div>
      </section>

      <section className="panel p-5 pt-6">
        <h2 className="panel-title">Discussions</h2>

        <div className="flex justify-end mb-3">
          {user && (
            <button onClick={() => setShowModal(true)} className="btn-secondary text-xs">
              Start a Thread
            </button>
          )}
        </div>

        {threadsLoading ? (
          <div className="flex flex-col gap-2">
            {[1, 2, 3].map((i) => (
              <div key={i} className="h-8 border border-line bg-panel animate-pulse" />
            ))}
          </div>
        ) : (
          <DataTable
            columns={columns}
            rows={threads || []}
            caption={`Discussions about ${book.title}`}
            emptyMessage={user ? 'No discussions yet. Start the first one.' : 'No discussions yet.'}
          />
        )}
      </section>

      {showModal && (
        <ThreadModal
          target={{ book_id: id }}
          onClose={() => setShowModal(false)}
          onCreated={(thread) => navigate(`/books/${id}/threads/${thread.id}`)}
        />
      )}
    </main>
  )
}

export default Book
```

- [ ] **Step 2: Verify the thread-creation e2e contract**

Run: `cd frontend && npm test && npm run build`
Expected: clean. Confirm by reading the file that the button text is exactly `Start a Thread` and `ThreadModal`'s default submit label is `Create Thread` — `e2e/thread.spec.js:13,18` clicks both by name.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/pages/Book.jsx
git commit -m "feat(web): terminal Book page with ls -l discussion table"
```

---

## Task 15: `Genre` page and deleting `ThreadCard`

**Files:**
- Modify: `frontend/src/pages/Genre.jsx`
- Delete: `frontend/src/components/ThreadCard.jsx`

**Interfaces:**
- Consumes: the same set as Task 14
- Produces: nothing. `ThreadCard` has no remaining consumers after this task.

- [ ] **Step 1: Confirm `ThreadCard` has exactly two consumers before deleting**

Run: `cd frontend && grep -rn "ThreadCard" src/`
Expected: only `src/pages/Book.jsx` (already converted in Task 14 — should show no hits) and `src/pages/Genre.jsx`. If anything else appears, convert it in this task too.

- [ ] **Step 2: Rewrite `Genre.jsx`**

Apply the same structure as `Book`:

```jsx
import { useState } from 'react'
import { useParams, useNavigate, Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import client from '../api/client'
import { useVoteThread } from '../api/threads'
import BookCard from '../components/BookCard'
import PathHeader from '../components/PathHeader'
import DataTable from '../components/DataTable'
import ThreadModal from '../components/ThreadModal'
import VoteControl from '../components/VoteControl'
import { relativeTime } from '../components/Post'
import { useStatusBar } from '../store/status'
import useAuthStore from '../store/auth'

function Genre() {
  const { slug: genreSlug } = useParams()
  const navigate = useNavigate()
  const user = useAuthStore((s) => s.user)
  const [showModal, setShowModal] = useState(false)
  const voteMutation = useVoteThread()

  const { data: genre, isLoading, isError } = useQuery({
    queryKey: ['genres', genreSlug],
    queryFn: () => client.get(`/genres/${genreSlug}`).then((r) => r.data),
    enabled: !!genreSlug,
  })

  const { data: books } = useQuery({
    queryKey: ['genres', genreSlug, 'books'],
    queryFn: () => client.get(`/genres/${genreSlug}/books`).then((r) => r.data),
    enabled: !!genreSlug,
  })

  const { data: threads } = useQuery({
    queryKey: ['genres', genreSlug, 'threads'],
    queryFn: () => client.get(`/genres/${genreSlug}/threads`).then((r) => r.data),
    enabled: !!genreSlug,
  })

  useStatusBar({
    mode: 'GENRE',
    path: `~/genres/${genreSlug}`,
    facts: [`${threads?.length ?? 0} threads`],
  })

  if (isLoading) {
    return (
      <main className="max-w-shell mx-auto px-4 py-8">
        <div className="animate-pulse flex flex-col gap-6">
          <div className="h-10 bg-panel w-1/3" />
          <div className="h-4 bg-panel w-2/3" />
        </div>
      </main>
    )
  }

  if (isError || !genre) {
    return (
      <main className="max-w-shell mx-auto px-4 py-8">
        <p className="alert-danger">Genre not found.</p>
      </main>
    )
  }

  const columns = [
    {
      key: 'score',
      label: 'Score',
      align: 'right',
      width: 8,
      render: (row) => (
        <VoteControl
          variant="row"
          score={row.score ?? 0}
          myVote={row.my_vote ?? 0}
          onVote={(value) => user && voteMutation.mutate({ id: row.id, value, genreSlug })}
          disabled={!user}
          pending={voteMutation.isPending}
        />
      ),
    },
    {
      key: 'title',
      label: 'Thread',
      render: (row) => (
        <Link
          to={`/genres/${genreSlug}/threads/${row.id}`}
          className="text-ink hover:text-accent transition-colors duration-fast"
        >
          {row.title}
        </Link>
      ),
    },
    {
      key: 'author',
      label: 'By',
      width: 16,
      render: (row) => <span className="text-user">{row.author}</span>,
    },
    {
      key: 'post_count',
      label: 'Repl',
      align: 'right',
      width: 6,
      render: (row) => <span className="text-ink-dim tabular-nums">{row.post_count ?? 0}</span>,
    },
    {
      key: 'created_at',
      label: 'Age',
      align: 'right',
      width: 6,
      render: (row) => <span className="text-ink-dim tabular-nums">{relativeTime(row.created_at)}</span>,
    },
  ]

  return (
    <main className="max-w-shell mx-auto px-4 py-6 flex flex-col gap-10">
      <PathHeader segments={[{ label: 'genres', to: '/' }, { label: genre.name }]} />

      <header className="border-b border-line pb-4 flex flex-col gap-2">
        <h1 className="text-display-sm text-ink uppercase">{genre.name}</h1>
        {genre.description && (
          <p className="text-ink-dim text-sm max-w-prose leading-relaxed">{genre.description}</p>
        )}
      </header>

      {books && books.length > 0 && (
        <section className="flex flex-col gap-4">
          <h2 className="text-xs uppercase tracking-eyebrow text-ink-dim border-b border-line pb-2">
            Notable books
          </h2>
          <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 gap-5">
            {books.map((book) => (
              <BookCard key={book.id} book={book} />
            ))}
          </div>
        </section>
      )}

      <section className="panel p-5 pt-6">
        <h2 className="panel-title">Discussions</h2>

        <div className="flex justify-end mb-3">
          {user && (
            <button onClick={() => setShowModal(true)} className="btn-secondary text-xs">
              Start a Discussion
            </button>
          )}
        </div>

        <DataTable
          columns={columns}
          rows={threads || []}
          caption={`Discussions in ${genre.name}`}
          emptyMessage="No discussions yet."
        />
      </section>

      {showModal && (
        <ThreadModal
          target={{ genre_slug: genreSlug }}
          onClose={() => setShowModal(false)}
          onCreated={(thread) => navigate(`/genres/${genreSlug}/threads/${thread.id}`)}
          title="Start a Discussion"
          submitLabel="Create"
        />
      )}
    </main>
  )
}

export default Genre
```

- [ ] **Step 3: Delete `ThreadCard`**

```bash
cd frontend && rm src/components/ThreadCard.jsx && grep -rn "ThreadCard" src/ || echo "no remaining references"
```
Expected: `no remaining references`.

- [ ] **Step 4: Run the suite and build**

Run: `cd frontend && npm test && npm run build`
Expected: both clean.

- [ ] **Step 5: Commit**

```bash
git add -A frontend/src/pages/Genre.jsx frontend/src/components/ThreadCard.jsx
git commit -m "feat(web): terminal Genre page; delete ThreadCard

Both thread lists are now DataTable, so the card component has no consumers."
```

---

## Task 16: `Home` and deleting `GenreCard`

**Files:**
- Modify: `frontend/src/pages/Home.jsx`
- Delete: `frontend/src/components/GenreCard.jsx`

**Interfaces:**
- Consumes: `useStatusBar`, `.panel`/`.panel-title`, `.caret`
- Produces: nothing

- [ ] **Step 1: Rewrite `Home.jsx`**

```jsx
import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import client from '../api/client'
import { useStatusBar } from '../store/status'

const FALLBACK_GENRES = [
  { slug: 'literary-fiction', name: 'Literary Fiction', description: 'Character-driven stories with literary merit.' },
  { slug: 'science-fiction', name: 'Science Fiction', description: 'Speculative worlds, technology, and futures.' },
  { slug: 'fantasy', name: 'Fantasy', description: 'Magic, myth, and invented worlds.' },
  { slug: 'history', name: 'History', description: 'Non-fiction explorations of the past.' },
  { slug: 'philosophy', name: 'Philosophy', description: 'Ideas, ethics, and ways of knowing.' },
  { slug: 'biography', name: 'Biography', description: 'Lives examined and recorded.' },
  { slug: 'mystery', name: 'Mystery', description: 'Puzzles, crimes, and revelations.' },
  { slug: 'poetry', name: 'Poetry', description: 'Language compressed into meaning.' },
]

function Home() {
  const [query, setQuery] = useState('')
  const navigate = useNavigate()

  const { data: genres } = useQuery({
    queryKey: ['genres'],
    queryFn: () => client.get('/genres/').then((r) => r.data),
    placeholderData: FALLBACK_GENRES,
  })

  const list = genres || FALLBACK_GENRES

  useStatusBar({ mode: 'HOME', path: '~', facts: [`${list.length} genres`] })

  const handleSearch = (e) => {
    e.preventDefault()
    if (query.trim()) navigate(`/search?q=${encodeURIComponent(query.trim())}`)
  }

  return (
    <main className="max-w-shell mx-auto px-4 py-10 flex flex-col gap-12">
      {/* Boot banner. The frame is a .panel — CSS borders, not characters, so it
          reflows. This is the only use of display-lg. */}
      <section className="panel p-6 pt-8 max-w-prose">
        <h1 className="panel-title">margin 1.0</h1>
        <p className="text-display-lg text-ink leading-none">
          MARGIN<span className="text-accent">//</span>
        </p>
        <p className="text-accent text-sm mt-3">books worth arguing about</p>
        <p className="text-ink-dim text-sm mt-4 leading-relaxed">
          Threaded discussion anchored to books and genres.
          <br />
          No star ratings. No sanitized reviews. Just honest argument.
        </p>
      </section>

      <form onSubmit={handleSearch} className="flex items-center gap-2 max-w-prose">
        <span aria-hidden="true" className="text-accent select-none">&gt;</span>
        <input
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="search for a book or author"
          aria-label="Search for a book or author"
          className="input"
        />
        <button type="submit" className="btn-primary shrink-0">
          Search
        </button>
      </form>

      {/* `ls`-style listing: name in accent, description dim, on the character grid. */}
      <section className="flex flex-col gap-4">
        <h2 className="text-xs uppercase tracking-eyebrow text-ink-dim border-b border-line pb-2">
          Browse by genre
        </h2>
        <ul className="flex flex-col">
          {list.map((genre) => (
            <li key={genre.slug}>
              <Link
                to={`/genres/${genre.slug}`}
                className="group flex flex-col sm:flex-row sm:items-baseline gap-1 sm:gap-4 py-1.5 px-2 -mx-2
                           hover:bg-highlight transition-colors duration-fast"
              >
                <span className="text-accent group-hover:text-accent-hover sm:w-48 shrink-0">
                  {genre.slug}
                </span>
                <span className="text-ink-dim text-sm truncate">{genre.description}</span>
              </Link>
            </li>
          ))}
        </ul>
      </section>
    </main>
  )
}

export default Home
```

- [ ] **Step 2: Delete `GenreCard`**

```bash
cd frontend && rm src/components/GenreCard.jsx && grep -rn "GenreCard" src/ || echo "no remaining references"
```
Expected: `no remaining references`.

- [ ] **Step 3: Run the suite and build**

Run: `cd frontend && npm test && npm run build`
Expected: both clean.

- [ ] **Step 4: Commit**

```bash
git add -A frontend/src/pages/Home.jsx frontend/src/components/GenreCard.jsx
git commit -m "feat(web): boot-banner Home with ls-style genre listing"
```

---

## Task 17: `Search` page

**Files:**
- Modify: `frontend/src/pages/Search.jsx`

- [ ] **Step 1: Restyle the header and states**

Replace the header block and the loading/empty states; the cover grid at the bottom is unchanged (it is already right).

```jsx
import { useSearchParams } from 'react-router-dom'
import { useSearchBooks } from '../api/books'
import BookCard from '../components/BookCard'
import { useStatusBar } from '../store/status'

function Search() {
  const [searchParams] = useSearchParams()
  const q = searchParams.get('q') || ''
  const { data: books, isLoading, isError } = useSearchBooks(q)

  useStatusBar({
    mode: 'SEARCH',
    path: q ? `~/search?q=${q}` : '~/search',
    facts: books ? [`${books.length} results`] : [],
  })

  return (
    <main className="max-w-shell mx-auto px-4 py-6 flex flex-col gap-8">
      <div className="border-b border-line pb-4 flex flex-col gap-1">
        <h1 className="text-lg text-ink">
          <span aria-hidden="true" className="text-accent">$ </span>
          search {q && <span className="text-path">&quot;{q}&quot;</span>}
        </h1>
        {books && (
          <p className="text-ink-dim text-xs tabular-nums">
            {books.length} {books.length === 1 ? 'result' : 'results'}
          </p>
        )}
      </div>

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

      {books && books.length === 0 && (
        <p className="text-ink-dim text-sm">No books found for &quot;{q}&quot;.</p>
      )}

      {books && books.length > 0 && (
        <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 gap-5">
          {books.map((book) => (
            <BookCard key={book.id} book={book} />
          ))}
        </div>
      )}
    </main>
  )
}

export default Search
```

- [ ] **Step 2: Run the suite and build**

Run: `cd frontend && npm test && npm run build`
Expected: both clean. `e2e/helpers.js:31` finds `a[href^="/books/"]` — `BookCard` still renders one per result.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/pages/Search.jsx
git commit -m "feat(web): command-echo Search header"
```

---

## Task 18: `Profile` page

**Files:**
- Modify: `frontend/src/pages/Profile.jsx`

- [ ] **Step 1: Restyle the header, stat block and shelf sections**

Replace the labels/order constants, `ShelfSection`, and the header block:

```jsx
import { useParams } from 'react-router-dom'
import { useProfile } from '../api/users'
import BookCard from '../components/BookCard'
import PathHeader from '../components/PathHeader'
import { useStatusBar } from '../store/status'

const SHELF_STATUS_LABELS = {
  want_to_read: 'want_to_read',
  reading: 'reading',
  read: 'read',
}

const SHELF_STATUS_TONE = {
  want_to_read: 'text-ink-dim',
  reading: 'text-warning',
  read: 'text-ok',
}

const SHELF_STATUS_ORDER = ['reading', 'want_to_read', 'read']

function ShelfSection({ status, books }) {
  if (!books || books.length === 0) return null
  return (
    <section className="flex flex-col gap-4">
      <div className="flex items-baseline gap-3 border-b border-line pb-2">
        <h2 className={`text-xs uppercase tracking-eyebrow ${SHELF_STATUS_TONE[status]}`}>
          {SHELF_STATUS_LABELS[status]}
        </h2>
        <span className="text-ink-dim text-xs tabular-nums ml-auto">{books.length}</span>
      </div>
      <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 gap-5">
        {books.map((book) => (
          <BookCard key={book.id} book={book} />
        ))}
      </div>
    </section>
  )
}
```

Inside `Profile`, add the status bar and path header, and replace the `<dl>`:

```jsx
  useStatusBar({
    mode: 'PROFILE',
    path: `~/profile/${username}`,
    facts: [],
  })
```

```jsx
    <main className="max-w-shell mx-auto px-4 py-6 flex flex-col gap-10">
      <PathHeader segments={[{ label: 'profile', to: '/' }, { label: username }]} />

      <header className="border-b border-line pb-5 flex flex-col gap-4">
        <h1 className="text-display-sm text-user break-words">{profile.username}</h1>
        {profile.bio && <p className="text-ink-dim text-sm max-w-prose leading-relaxed">{profile.bio}</p>}

        {/* Aligned key/value, as `ls` would print it. */}
        <dl className="grid grid-cols-[auto_1fr] gap-x-6 gap-y-0.5 text-sm max-w-xs">
          {SHELF_STATUS_ORDER.map((status) => (
            <div key={status} className="contents">
              <dt className={SHELF_STATUS_TONE[status]}>{SHELF_STATUS_LABELS[status]}</dt>
              <dd className="text-ink tabular-nums">{shelves[status]?.length ?? 0}</dd>
            </div>
          ))}
        </dl>
      </header>
```

Also swap the loading skeleton's `bg-surface` → `bg-panel`, the error `<p className="text-danger">` → `<p className="alert-danger">`, and the empty state's `text-ink-dim` copy stays as-is.

- [ ] **Step 2: Run the suite and build**

Run: `cd frontend && npm test && npm run build`
Expected: both clean.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/pages/Profile.jsx
git commit -m "feat(web): terminal Profile with ls-style shelf counts"
```

---

## Task 19: `NotFound`

The joke must not cost accessibility. The existing test stays green because the heading text and the link's accessible name are preserved.

**Files:**
- Modify: `frontend/src/pages/NotFound.jsx`
- Test: `frontend/src/pages/NotFound.test.jsx` (existing — must stay green **unchanged**)

- [ ] **Step 1: Read the existing test and confirm what must survive**

Run: `cd frontend && cat src/pages/NotFound.test.jsx`
Expected: it asserts `getByRole('heading', { name: /page not found/i })` and `getByRole('link', { name: /go home/i })`. Both must still resolve.

- [ ] **Step 2: Rewrite `NotFound.jsx`**

```jsx
import { Link } from 'react-router-dom'
import { useLocation } from 'react-router-dom'
import { useStatusBar } from '../store/status'

function NotFound() {
  const { pathname } = useLocation()
  useStatusBar({ mode: '404', path: `~${pathname}`, facts: [] })

  return (
    <div className="max-w-shell mx-auto px-4 py-16 flex flex-col gap-6">
      {/* The heading is visually hidden, not removed: the terminal error below is
          decoration, and a screen reader still gets a real page title. */}
      <h1 className="sr-only">Page not found</h1>

      <p className="text-sm">
        <span className="text-danger">margin: </span>
        <span className="text-ink">cannot access </span>
        <span className="text-path">&apos;{pathname}&apos;</span>
        <span className="text-ink">: No such file or directory</span>
      </p>

      <p className="flex items-center gap-2 text-sm">
        <span aria-hidden="true" className="text-accent select-none">&gt;</span>
        <Link
          to="/"
          aria-label="Go home"
          className="text-accent hover:text-accent-hover transition-colors duration-fast"
        >
          cd ~
        </Link>
        <span aria-hidden="true" className="caret text-accent">▌</span>
      </p>
    </div>
  )
}

export default NotFound
```

- [ ] **Step 3: Run the existing test unchanged and verify it passes**

Run: `cd frontend && npx vitest run src/pages/NotFound.test.jsx`
Expected: PASS, both tests, with **no edits to the test file**. If either fails, fix the component — not the test.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/pages/NotFound.jsx
git commit -m "feat(web): terminal 404 with preserved accessible name"
```

---

## Task 20: The four auth screens

**Files:**
- Modify: `frontend/src/components/AuthLayout.jsx`
- Modify: `frontend/src/pages/Login.jsx`, `Register.jsx`, `ForgotPassword.jsx`, `ResetPassword.jsx`
- Test: the four existing specs must stay green **unchanged**

- [ ] **Step 1: Establish the baseline**

Run: `cd frontend && npx vitest run src/pages/Login.test.jsx src/pages/ForgotPassword.test.jsx src/pages/ResetPassword.test.jsx`
Expected: PASS. Note that `Login.test.jsx:36` asserts a heading named exactly `Sign in` — that string cannot change.

- [ ] **Step 2: Rewrite `AuthLayout.jsx`**

```jsx
import { Link } from 'react-router-dom'

/**
 * Shared shell for the four credential screens, framed as a login prompt so the
 * wordmark, frame and heading rhythm can't drift apart between them.
 *
 * `title` is passed through verbatim — Login's "Sign in" and Register's
 * "Create account" are asserted by accessible name in the unit and e2e suites.
 */
function AuthLayout({ title, subtitle, children, footer }) {
  return (
    <div className="min-h-[calc(100vh-var(--shell-nav-h))] bg-bg flex items-center justify-center px-4 py-16">
      <div className="w-full max-w-sm panel p-6 pt-8">
        <p className="panel-title">
          <Link to="/" className="text-ink-dim hover:text-accent transition-colors duration-fast">
            margin//
          </Link>
        </p>

        <div className="mb-6">
          <h1 className="text-lg text-ink">
            <span aria-hidden="true" className="text-accent">$ </span>
            {title}
          </h1>
          {subtitle && <p className="text-ink-dim text-xs mt-1">{subtitle}</p>}
        </div>

        {children}

        {footer && <div className="text-ink-dim text-xs mt-6">{footer}</div>}
      </div>
    </div>
  )
}

export default AuthLayout
```

- [ ] **Step 3: Retokenise the four pages**

In each of `Login.jsx`, `Register.jsx`, `ForgotPassword.jsx`, `ResetPassword.jsx`, apply only these substitutions — **do not change any heading text, button text, or input types**:

- `text-accent-ink` → `text-accent`
- `bg-surface` → `bg-panel`
- `bg-raised` → `bg-highlight`
- `border-line-strong` → `border-ink-muted` on anything focusable
- `uppercase tracking-widest` on `.label` elements → rely on `.label` (now lowercase `tracking-eyebrow`); remove the redundant utilities
- any `text-danger` error paragraph that is a block → `alert-danger`

**`Register.jsx` must keep exactly one `input[type="text"]`** (the username) — `e2e/helpers.js:18` depends on it.

- [ ] **Step 4: Run the four suites unchanged**

Run: `cd frontend && npm test`
Expected: PASS across all suites, with no edits to any test file.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/AuthLayout.jsx frontend/src/pages/Login.jsx frontend/src/pages/Register.jsx frontend/src/pages/ForgotPassword.jsx frontend/src/pages/ResetPassword.jsx
git commit -m "feat(web): login-prompt auth screens"
```

---

## Task 21: Drop aliases, update docs, full verification

The migration is only finished when nothing references the old system and the binding docs describe the new one. `CLAUDE.md` in particular *instructs future sessions* — leaving it stale means the next agent reverts this work in good faith.

**Files:**
- Modify: `frontend/tailwind.config.js` (remove aliases)
- Modify: `CLAUDE.md`
- Modify: `docs/visual-identity.md`

- [ ] **Step 1: Confirm no consumer of the aliases remains**

```bash
cd frontend && grep -rnE "surface|raised|accent-ink|text-success|bg-success" src/ | grep -v "tailwind.config" || echo "no alias references remain"
```
Expected: `no alias references remain`. Fix any hits before continuing.

- [ ] **Step 2: Delete the aliases from `tailwind.config.js`**

Remove this block:

```js
        // Migration aliases. Unconverted pages still reference these; the final
        // task deletes them along with their last consumer.
        surface: token('panel'),
        raised: token('highlight'),
        'accent-ink': token('accent'),
        success: token('ok'),
```

- [ ] **Step 3: Verify the build still passes without them**

Run: `cd frontend && npm test && npm run build`
Expected: both clean. A failure here means Step 1's grep missed a consumer.

- [ ] **Step 4: Update `CLAUDE.md`'s design-system section**

Replace the bullet list under "### Design system" with:

```markdown
- **Tokens are the only source of color.** Values live as raw `R G B` channels on
  `:root` in `index.css` and map to semantic Tailwind utilities in
  `tailwind.config.js` (so `/opacity` modifiers still work). **Never write a raw
  `zinc-*`, hex, or arbitrary color in a component** — add a token instead.
  Surfaces: `bg` → `panel` → `highlight`; borders: `line`, `line-strong`; text:
  `ink`, `ink-dim`, `ink-muted`, `ink-faint`.
- **Text tiers are a contrast contract, asserted in `src/design/tokens.test.js`.**
  `ink` (10.59:1) body · `ink-dim` (8.10:1) secondary, metadata, timestamps ·
  `ink-muted` (4.10:1) **control borders and decoration only — never
  informational text** · `ink-faint` (2.76:1) **`aria-hidden` glyphs only**.
- **Fills invert.** A filled control is `bg-accent text-bg`. White on the accent
  is 2.52:1 and fails AA, so the conventional filled button does not exist here.
- **Color means one thing each.** `accent` interactive · `path` routes and
  references · `user` people · `ok` positive · `danger` negative · `warning`
  mutated state. Nothing means anything by color alone.
- **Serif is reserved for book titles.** Everything else — including thread
  titles — is JetBrains Mono.
- **Reuse the component classes** in the `@layer components` block (`.btn-primary`,
  `.btn-secondary`, `.btn-ghost`, `.input`, `.label`, `.panel`, `.panel-title`,
  `.float`, `.prompt`, `.caret`, `.eyebrow`, `.rule`, `.alert-danger`,
  `.alert-muted`) rather than re-deriving them. Shared shells live in
  `components/` (`AuthLayout`, `VoteControl`, `PathHeader`, `StatusBar`,
  `DiagnosticFloat`, `DataTable`, `ThreadModal`).
- **Box-drawing frames and rails are CSS borders, not characters.** Only tree
  elbows (`├─`, `└─`), sort carets (`▾`/`▴`) and the float marker (`■`) are
  literal glyphs, and every one is `aria-hidden`.
- **Measure in `ch`**: `max-w-prose` (72ch), `max-w-table` (96ch),
  `max-w-shell` (120ch). In a monospaced layout that is the grid.
- **No new border radii, shadows, font sizes, or durations.** Corners are square
  by design; motion is `duration-fast` (120ms) or `duration-base` (180ms).
- **Layout**: dense but organized — grids, rules and dividers over floating
  cards. Book covers carry the color, so keep them large and never dim the art.
- **Before calling a screen done**, run the §36 test: if it looks like Goodreads,
  a generic SaaS dashboard, or recolored Reddit, redesign it. Book content stays
  visually dominant; voting never does.
- **No star ratings or user reviews.** This is a product decision, not an
  oversight — see `docs/visual-identity.md` §1 and `margin_spec.md`.
```

Also update the design-system paragraph above it to point at the new record:

```markdown
MARGIN's visual identity is a terminal: dark, monospaced, character-gridded, and
colorized by meaning. The decisions are recorded in
[`docs/visual-identity.md`](docs/visual-identity.md) and specified in
[`docs/superpowers/specs/2026-09-23-terminal-ui-design.md`](docs/superpowers/specs/2026-09-23-terminal-ui-design.md).
Read those before changing anything visual.
```

- [ ] **Step 5: Add a superseding section to `docs/visual-identity.md`**

Append — do **not** delete the cobalt rationale; the file exists so decisions are not re-litigated from the brief alone, and the old reasoning is what makes the new decision legible:

```markdown
---

## 6. Superseded by the terminal redesign (2026-09-23)

Spec: [`docs/superpowers/specs/2026-09-23-terminal-ui-design.md`](superpowers/specs/2026-09-23-terminal-ui-design.md)

§1's accent, UI sans and three-blue split are **superseded**. What replaced them,
and why the original reasoning no longer applies:

| §1 decision | Superseded by | Why |
| --- | --- | --- |
| Cobalt `#2B5FE3` accent | Tokyo Night blue `#7AA2F7` | The blue lineage is kept deliberately — the identity evolves rather than snaps — but the palette is now an established terminal scheme, which supplies a coherent semantic set (path/user/ok/danger/warning) that a single hand-picked accent could not. |
| Space Grotesk UI sans | JetBrains Mono | The whole UI is monospaced. Space Grotesk has no role left. |
| Three-blue fill/text split (`accent`/`accent-hover`/`accent-ink`) | One `accent` plus inversion | White on `#7AA2F7` is 2.52:1, so filled buttons take `text-bg` instead. Inversion is what a terminal does for selected text, and it collapses three tokens to one. |
| Playfair for book **and** thread titles | Playfair for book titles only | A thread is structure, not a work. The single serif moment is what keeps the UI from reading as a recolored hacker toy. |
| `ink-muted` at 3.3:1 for metadata | `ink-dim` at 8.10:1 for metadata | The muted tier splits three ways so no informational text sits below AA. Stricter than what this record originally allowed. |

**Unchanged and still binding:** no star ratings or reviews (§1), covers stay
large and undimmed (§2 §13), voting stays de-emphasised (§24), square corners,
and the §36 "does it look like Goodreads" test.
```

- [ ] **Step 6: Full verification**

```bash
cd frontend && npm test && npm run build
```
Expected: all suites PASS, build clean.

```bash
docker compose up --build   # in another terminal
cd frontend && npx playwright test
```
Expected: all e2e specs PASS. If `thread.spec.js` or `reply.spec.js` fail on a selector, the fix is in the component (restore the accessible name), not the spec.

Then walk every route at 360px width in a browser — `/`, `/search?q=dune`, a book, a thread, a genre, a profile, `/login`, `/register`, `/nope` — and confirm no horizontal scroll, tables stacked, path header collapsed, status bar showing mode and user.

- [ ] **Step 7: Commit**

```bash
git add frontend/tailwind.config.js CLAUDE.md docs/visual-identity.md
git commit -m "feat(web): drop migration aliases; rewrite binding design docs

CLAUDE.md instructs future sessions, so leaving it describing cobalt and
Space Grotesk would have had the next agent revert this in good faith.
visual-identity.md gains a superseding section rather than losing the
original rationale."
```

---

## Verification Summary

| Gate | Command | When |
| --- | --- | --- |
| Token contrast | `npx vitest run src/design/tokens.test.js` | Task 1, then every task |
| Unit suite | `npm test` | Every task |
| Build | `npm run build` | Every page task |
| **Pilot review** | human, in a browser | **After Task 11 — blocking** |
| E2E | `npx playwright test` (stack up) | Task 21 |
| 360px sweep | manual, every route | Task 21 |

## Deferred

Edit/delete/soft-delete and thread sorting remain parked on
`feat/edit-delete-sorting`. When resumed, the sort control attaches to
`DataTable`'s `sortable` columns via its existing `sort`/`sortDirection`/`onSort`
props — already built and tested here — and the `edited` flag uses
`DiagnosticFloat severity="warn"`. No new chrome should be invented for either.
