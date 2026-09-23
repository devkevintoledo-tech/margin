# Terminal UI — Visual Redesign

**Date:** 2026-09-23
**Status:** Approved (design)
**Supersedes:** parts of [`docs/visual-identity.md`](../../visual-identity.md) §1 —
specifically the cobalt accent, the Space Grotesk UI sans, and the three-blue
fill/text split. The rest of that record (no star ratings, no reviews, covers
stay undimmed, voting stays de-emphasised) is unchanged and still binding.
**Base branch:** `feat/terminal-ui`, cut from `f60b52c` (PR #6, voting).

## Problem

MARGIN's current identity — dark, editorial, cobalt, Playfair + Space Grotesk —
is coherent but generic. It reads as "well-made dark content site" and carries
no memory of what the product is for. The goal is an interface that looks and
behaves like a terminal: monospaced, character-gridded, colorized by meaning
rather than decoration, and recognisable in one screenshot.

This is a visual and structural redesign of the frontend. **No backend, schema,
or API change is in scope.**

## Decisions

Each of these was chosen deliberately over a named alternative.

| Decision | Chosen | Over | Why |
| --- | --- | --- | --- |
| Literalness | **Terminal look, normal clicking** | full typed-command TUI; hybrid ⌘K command bar | A typed-command UI needs a command grammar, history, help and a mobile story — a new interaction model, not a redesign. The aesthetic delivers the identity at a fraction of the risk, and keeps every route linkable, crawlable and touch-usable. |
| Palette | **Tokyo Night** | Catppuccin Mocha; Gruvbox Dark; Rosé Pine | An established 16-colour scheme gives a coherent semantic set for free. Tokyo Night keeps a blue accent, so the cobalt identity evolves rather than snaps; its cool, desaturated ground stays out of the way of full-colour book covers; and it is explicitly *not cozy*, which Catppuccin's pastel warmth would have fought. Gruvbox's warm beige is Goodreads' home turf. |
| Typography | **Mono everywhere, serif for book titles only** | full mono, no exceptions; mono chrome with proportional prose | The single serif moment is what keeps this from reading as a recoloured hacker toy: the machine is a terminal, the works inside it stay literary. Full mono removes all typographic contrast; proportional prose stops the illusion exactly where the reader is looking. |
| Mono face | **JetBrains Mono** | IBM Plex Mono; Space Mono | Body copy is going mono, so legibility at paragraph length outranks character. Tall x-height and wide apertures are what it was engineered for. Playfair on book titles supplies the warmth JetBrains deliberately lacks. |
| Structures | **Path header, tree replies, `ls -l` listings, status bar, nvim diagnostic floats** | a monospace skin alone | These are what make it a terminal rather than a font choice. Each replaces an existing element rather than adding chrome. |
| Sequencing | **Redesign first, then edit/delete/sorting** | features first; one combined branch | Every surface gets written once, and the approved-but-unbuilt sort control lands in `DataTable`'s sortable headers instead of needing new chrome invented for it. |
| Execution | **Foundation → pilot → fan out** | big-bang rewrite; dual switchable theme | The pilot checkpoint catches the one thing a spec cannot settle — whether a real discussion reads well in monospace — after ~250 lines instead of 1,900. A dual theme is a trap: the path header, tree and tables are structural, not colours, so they cannot live behind a CSS variable. |

### Rejected

- **CRT affectations** — scanlines, phosphor glow, screen curvature. Costume, not
  design; they cost readability on the one surface (long discussion) the product
  exists for.
- **Rounded float corners.** nvim's default `border="single"` is square, which
  matches this project's standing "no new border radii" rule. The rounded
  variant would have introduced a radius token for decoration alone.
- **Literal box-drawing characters for panel frames and tree rails.** Characters
  do not stretch to content height or reflow at viewport width. See §2 for what
  replaces them and where glyphs *are* still correct.

---

## 1. Token and type foundation

Two files (`frontend/src/index.css`, `frontend/tailwind.config.js`) plus one
`<link>` in `frontend/index.html`. No component changes in this step — pages keep
rendering through aliases, in new colours and a new face. It is independently
reviewable, and a wrong palette is caught before any structural work.

### Surfaces

Contrast computed against `bg` `#1A1B26`. **Panels are darker than the page**,
as nvim floats and statuslines are — this inverts the current
`bg → surface → raised` ascent and is the one choice here that reads as a
mistake until seen.

| Token | Tokyo Night | Hex | Role |
| --- | --- | --- | --- |
| `bg` | `bg` | `#1A1B26` | the buffer |
| `panel` | `bg_dark` | `#16161E` | floats, status bar, nav, inputs |
| `highlight` | `bg_highlight` | `#292E42` | hovered / selected row |
| `line` | `fg_gutter` | `#3B4261` | table rules, dividers (decorative) |
| `line-strong` | `terminal_black` | `#414868` | box frames, tree rails (decorative) |

### Text

| Token | Hex | vs `bg` | Use |
| --- | --- | --- | --- |
| `ink` | `#C0CAF5` | 10.59:1 | body and headlines |
| `ink-dim` | `#A9B1D6` | 8.10:1 | secondary copy, descriptions, **metadata and timestamps** |
| `ink-muted` | `#737AA2` | 4.10:1 | **control borders** and non-essential decoration. Below AA's 4.5 for normal text — never text a reader needs. |
| `ink-faint` | `#565F89` | 2.76:1 | **`aria-hidden` glyphs only** — tree elbows, separators, frames. |

**All text a reader must perceive sits at 8.10:1 or better.** Today's design
system routes metadata and timestamps through `ink-muted` at 3.3:1; this
redesign moves them to `ink-dim` and leaves `ink-muted` for borders and
decoration, so no informational text sits below AA. That is stricter than what
the code does now, and it is the reason the muted tier splits in three.

`ink-muted` is Tokyo Night's `dark5`, not its `comment` (`#565F89`). `comment`
measures 2.76:1 — below 3:1 even for incidental text, and worse than the
`#66635F` it replaces. Moving to `dark5` clears the 3:1 non-text floor, and
isolates the sub-3:1 value in `ink-faint`, where every consumer is
`aria-hidden` and structurally redundant.

`ink-muted` doubles as the **control border**: WCAG 1.4.11 requires 3:1 for
input and control boundaries, and `line-strong` is only 1.91:1. Inputs,
sortable headers and focusable controls take `#737AA2` (4.10:1); purely
decorative frames keep `line-strong`.

### Semantic colour

One job each, the way a terminal colourises `ls` and `git log`. Colour never
carries meaning alone — see §4.

| Token | Tokyo Night | Hex | vs `bg` | Means |
| --- | --- | --- | --- | --- |
| `accent` | `blue` | `#7AA2F7` | 6.79:1 | interactive — links, buttons, focus ring, prompt caret |
| `accent-hover` | `blue5` | `#89DDFF` | 11.27:1 | hover, text and fill alike |
| `path` | `cyan` | `#7DCFFF` | 9.96:1 | routes and references — path header, book/genre links |
| `user` | `magenta` | `#BB9AF7` | 7.39:1 | people — usernames, bylines |
| `ok` | `green` | `#9ECE6A` | 9.35:1 | positive — upvote cast, success, Read shelf |
| `danger` | `red` | `#F7768E` | 6.46:1 | negative — downvote cast, errors, delete |
| `warning` | `yellow` | `#E0AF68` | 8.55:1 | mutated state — `edited` flag, pending, Reading shelf |

### Inversion replaces the three-blue split

Today's `accent` / `accent-hover` / `accent-ink` trio exists only because cobalt
cannot be both a legible fill and legible text on near-black. **White on
`#7AA2F7` measures 2.52:1 and fails outright** — so the conventional filled
button is not available at all in this palette.

A primary button is therefore `background: accent; color: bg` — the same 6.79:1,
flipped. That is what a terminal does for selected text, and it collapses three
tokens to one plus a hover.

> **`accent-ink` is deleted.** Any component still using it as text takes
> `accent`; any component using `accent` as a fill must also set `text-bg`.

### Aliases during migration

`surface` and `raised` remain as aliases of `panel` and `highlight` until the
last page is converted, then are deleted in the final commit. This is what
allows the pilot to exist — unconverted pages keep rendering instead of forcing
a big-bang after all.

### Type

- **JetBrains Mono** 400/500/700 + italic replaces Space Grotesk everywhere.
  One line in `index.html`, one in `tailwind.config.js`; `font-mono` becomes the
  `body` default. Latin subset, `display=swap`, three weights — roughly
  request-neutral against the Space Grotesk it removes.
- **Playfair Display** survives on **book titles only**. Thread titles
  (`Thread.jsx:62`, `ThreadCard.jsx`), book subtitles and the `BookCard`
  no-cover fallback convert to mono. A thread is not a work.
- **The display scale shrinks.** Mono runs ~15% wider per character, so today's
  `display-lg: 5rem` is a wall. New: `display-sm` `1.75rem`, `display`
  `2.25rem`, `display-lg` `3rem`, all `letterSpacing: 0` — mono is pre-spaced.
  Playfair keeps the large sizes; the book title stays the biggest thing on its
  page.
- **Measure in `ch`.** Prose caps at `72ch`, tables at `96ch`, shell at `120ch`.
  In a monospaced layout `ch` is a real column count, so this *is* the grid.
- `tracking-eyebrow` drops `0.25em → 0.15em`. At 0.25em, uppercase mono reads as
  broken rather than wide.

---

## 2. Primitives

Five shared components plus a revised `@layer components` vocabulary.
Everything in §3 is composition of these.

> **The ASCII blocks in this spec illustrate the intended *rendering*, not the
> implementation.** Where a frame, rule or rail is drawn with CSS borders rather
> than characters, the primitive says so explicitly. Only the tree elbows
> (`├─`, `└─`), the sort carets (`▾`/`▴`) and the float's severity marker (`■`)
> are literal glyphs in the DOM.

### `PathHeader`

```
~/books/the-dispossessed/threads/42
```

**Props:** `segments: [{ label, to }]`. Explicit, not derived from the URL —
pages know their book and thread titles; the route only has ids.

Segments are `path` cyan and clickable; separators are `ink-faint` and
`aria-hidden`. Renders `<nav aria-label="Breadcrumb"><ol>`. Labels slugify
(`The Dispossessed` → `the-dispossessed`) via a new `lib/slug.js`, truncated at
28 characters. Below `sm`, middle segments collapse to `…` so the leaf stays
visible.

### `StatusBar`

```
█ BOOK █ ~/books/the-dispossessed        2 threads │ kevin
```

Mounted once in `App.jsx` beside `Navbar`. Fixed bottom, `panel` background,
`line-strong` top border.

`mode` is a closed set, one per route group: `HOME`, `BOOK`, `THREAD`, `GENRE`,
`SEARCH`, `PROFILE`, `AUTH`, `404`. It renders as an inverted block
(`bg-accent text-bg`), which is the only place besides a primary button where
inversion is used.

Pages feed it through a `useStatusBar({ mode, path, facts })` hook writing into
a context, cleaning up on unmount — one line per page, no prop drilling through
the router, and no page renders the bar itself. `<body>` takes bottom padding
equal to the bar height; it is `position: fixed`, never a flex sibling, so it
cannot eat viewport on short screens. Below `sm` it reduces to mode + user.

### `DiagnosticFloat`

```
┌────────────────────────────────┐
│ ■ edited 2h ago by author      │
│   thread/42 · revision 2       │
└────────────────────────────────┘
```

**Props:** `severity` (`error|warn|info|hint` → red / yellow / blue / muted
marker), `source` (the dim second line), `align` (`start|end`), trigger as
children.

Square border — nvim's `border="single"` — so no border radius is introduced.
Opens on **hover and `focus-within`** so it is keyboard-reachable; `role="tooltip"`
with `aria-describedby` on the trigger; tap toggles on touch. No new dependency:
absolute positioning with alignment variants and a `max-width` clamp covers
every case here. First two uses are the `edited` flag and the post timestamp.

### Tree threading — a change to `Post.jsx`, not a new component

```
+42 │ Is Anarres actually a utopia?
     │
     ├─ kevin · 2h · +8
     │  Le Guin never lets the reader settle.
     │
     └─ jon · 40m · -2
        Disagree — Anarres is romanticised.
```

The elbows (`├─`, `└─`) are **real glyphs** in a `3ch` gutter — which works only
because the whole UI is monospaced, so they align by construction. The vertical
rail is a **CSS border**, because a border stretches to content height and a
repeated character does not. Glyphs are `aria-hidden`; the reply relationship is
already carried by DOM nesting.

`Post` keeps its existing `depth` prop and recursion. MARGIN is capped at two
levels, so this cannot degenerate into deep spaghetti.

### `DataTable`

```
SCORE  THREAD                      REPL   AGE
─────  ──────────────────────────  ────   ───
  +42  Is Anarres actually a...      18    2d
   +9  The ansible as plot device     3    5d
```

**Props:** `columns: [{ key, label, align, width /* ch */, sortable }]`, `rows`,
`sort`, `onSort`.

Numeric columns right-align; scores colour by sign (`ok` / `danger` /
`ink-dim` at zero); the header underline is a `border-bottom`, not a row of `─`.
**Sortable headers are the sort control** — the active column shows `▾`/`▴` —
which is where the parked new/top sorting feature lands with no new UI invented
for it. Below `sm` the table collapses to stacked rows; a horizontally
scrolling table on a phone is the one place this aesthetic genuinely fails.

**Rows are real `<a href>` links**, never `onClick` row handlers — required for
middle-click, keyboard and screen readers, and asserted by `e2e/helpers.js:31`.

### Revised `@layer components`

- `.btn-primary` — inverted: `bg-accent text-bg`, hover `accent-hover`.
- `.btn-secondary` — bracketed `[ Start a thread ]`, brackets via
  `::before` / `::after` so they stay out of the accessible name.
- `.btn-ghost` — `ink-dim`, hover `ink`.
- `.input` — `bg-panel`, border `ink-muted` (4.10:1), focus border `accent`,
  `caret-color: accent`. A `.prompt` wrapper prefixes `>` for search and the
  composer.
- `.panel` — box-drawn with a title notch: `border border-line-strong` plus an
  absolutely-positioned `.panel-title` with `bg-bg` sitting on the top border.
  This renders `┌─ DISCUSSIONS ──┐` responsively; literal characters would break
  at every viewport width.
- `.float` — the `DiagnosticFloat` base, also reused by `ShelfButton`'s dropdown
  and the thread modal.
- `.eyebrow`, `.rule`, `.label`, `.alert-*` — retained, retokenised.
- Blinking caret on the search prompt, disabled under `prefers-reduced-motion`.
  No new durations; `duration-fast` (120ms) and `duration-base` (180ms) still
  cover everything.

---

## 3. Page-by-page

Build order. The pilot gate sits after Thread.

### Shell — built first, visible everywhere

**`Navbar`** becomes a title bar: `MARGIN//` wordmark, nav items, and the search
box as a real prompt (`> _` with a blinking block caret). The `h-0.5 bg-accent`
strip at `Navbar.jsx:22` is removed — the status bar now carries that weight at
the bottom and two accent rails would fight. The signed-in user renders as an
inverted `user`-magenta initial block plus username. The logout button keeps its
`Out` label.

**`StatusBar`** mounts in `App.jsx`.

**`AuthLayout`** hardcodes the navbar's pixel height as
`min-h-[calc(100vh-51px)]`, which breaks the moment the navbar changes. It
becomes a `--shell-nav-h` CSS variable on `:root`, consumed by both.

### Pilot — `Thread` + `Post` + `PostComposer`, then **stop for review**

Path header `~/books/the-dispossessed/threads/42`. The thread title converts
Playfair → mono. The byline becomes `kevin` in `user` magenta; the score colours
by sign. `Post`'s `formatDate` switches from `Mar 3, 2026` to relative (`2h`,
`5d`), with the **absolute timestamp in a `DiagnosticFloat` on hover** — the
first real use of the primitive. Posts get the glyph-elbow tree.
`PostComposer` becomes a prompt: `>` prefix, bracketed `[ Post ]` submit.

This is the checkpoint. Everything below is mechanical once it is approved.

### `Book` and `Genre`

The cover stays large and full colour — still the only saturated thing on the
page, and against a desaturated ground it will read *more* dominant than today.
Playfair title kept. The metadata rail becomes aligned `key: value` pairs.
Categories render as `[science fiction]` brackets. `ShelfButton` becomes a
bracketed selector whose dropdown reuses `.float`.

Discussion lists on both pages swap `ThreadCard` → `DataTable`, so **`ThreadCard`
is deleted**. `VoteControl` gains a third variant, `row` — a compact horizontal
`↑ +42 ↓` in the SCORE column, revealing its arrows on hover/focus so voting
still does not dominate (`visual-identity.md` §24 holds).

Both pages carry a **duplicated `CreateThreadModal`** (`Book.jsx:10` and
`Genre.jsx:118` are near-identical). Since both are rewritten anyway, they
collapse into one `ThreadModal` styled as a centred float. This is the only
refactor folded in — it is code the redesign is already touching.

### `Home`

The hero becomes a boot banner in a box-drawn frame:

```
┌──────────────────────────────────────────────┐
│ MARGIN 1.0                                   │
│ books worth arguing about                    │
│                                              │
│ no star ratings. no sanitized reviews.       │
│ just honest argument.                        │
└──────────────────────────────────────────────┘

> search for a book or author_
```

The frame is a `.panel` with its title notch — CSS borders, not characters, so
it reflows. The wordmark line is the only place `display-lg` is used.

Genres drop `GenreCard`'s hairline grid for an `ls`-style two-column listing —
name in `accent`, description in `ink-dim`, aligned on the character grid.
**`GenreCard` is deleted.**

### `Search`, `Profile`, `NotFound`

**`Search`** headline becomes a command echo — `$ search "dispossessed"` with
`12 results` beneath. The cover grid is untouched; it is the one layout that is
already right.

**`Profile`** headline goes mono. The `<dl>` stat block becomes an aligned
key/value table (`reading 4 / want_to_read 12 / read 37`) in shelf-status
colours — `warning` reading, `ok` read, `ink-dim` want. Shelf sections keep
their cover grids.

**`NotFound`**:

```
margin: cannot access '/nope': No such file or directory

> cd ~
```

The visually-hidden heading stays `Page not found` and the link takes
`aria-label="Go home"`, so the terminal error reads as decoration over a page
that is still legible to a screen reader — and `NotFound.test.jsx` passes
unchanged.

### The four auth screens

`AuthLayout` reframes as a login prompt: wordmark, then a `.panel` with a title
notch. Labels become mono lowercase keys; the accent underline rule is removed.
`Login`, `Register`, `ForgotPassword` and `ResetPassword` are otherwise
restyled only — no logic moves. **Their headings keep their exact current text**
(see §4).

### Net component change

| Deleted | New | Changed |
| --- | --- | --- |
| `ThreadCard`, `GenreCard` | `PathHeader`, `StatusBar`, `DiagnosticFloat`, `DataTable`, `ThreadModal`, `lib/slug.js`, `store/status.js` | all 11 pages, `Navbar`, `Post`, `PostComposer`, `VoteControl` (+`row`), `ShelfButton`, `BookCard`, `AuthLayout` |

---

## 4. Verification, docs, rollout

### Existing tests constrain the design

The suites are role- and name-based with **zero class assertions**, so the
redesign is constrained to keep them green rather than rewriting them. These are
design requirements, not test chores:

| Constraint | Why | Otherwise breaks |
| --- | --- | --- |
| Scores render ASCII `-2`, never `−2` (U+2212) | terminals are ASCII | `VoteControl.test.jsx:34` |
| Brackets live in `::before`/`::after` | accessible name must stay `Start a Thread` | `e2e/thread.spec.js:13,18`, `e2e/reply.spec.js:21` |
| Navbar search keeps `type="search"` | `searchbox` role must stay out of `getByRole('textbox')` | `e2e/auth.spec.js:16`, `e2e/helpers.js:17` |
| `DataTable` rows are real `<a href>` | also the a11y-correct answer | `e2e/helpers.js:31` |
| Auth headings keep exact text (`Sign in`, `Create account`) | asserted by name | `Login.test.jsx:36`, `e2e/helpers.js:22` |
| Logout stays `Out` | asserted in two suites | `Navbar.test.jsx:35,49`, `e2e/auth.spec.js:11` |
| Register keeps exactly one `input[type="text"]` | selector assumes uniqueness | `e2e/helpers.js:18` |

No existing test is rewritten. `NotFound.test.jsx` passes via the
accessible-name treatment in §3.

**New coverage** — one Vitest spec per primitive:

- `PathHeader` — segment links, mobile collapse
- `DataTable` — sort toggle, row links, mobile stacking
- `DiagnosticFloat` — opens on focus, `aria-describedby` wiring
- `StatusBar` — context set and cleanup on unmount
- `VoteControl` — the new `row` variant

### Accessibility acceptance

- Every box-drawing glyph and tree elbow is `aria-hidden`; structure is in the DOM.
- **Nothing means anything by colour alone**: scores keep their `+`/`-` sign,
  vote state keeps `aria-pressed`, floats keep their severity word.
- Blinking caret respects `prefers-reduced-motion`.
- Focus ring is `accent` at 6.79:1.
- Control borders meet WCAG 1.4.11 at 4.10:1.
- **No informational text below 8.10:1.** `ink-muted` (4.10:1) is borders and
  decoration only; `ink-faint` (2.76:1) is `aria-hidden` glyphs only. Enforced
  by an automated token test, not by review.
- Contrast figures in §1 are computed from the hex values and must be
  re-verified with a checker before merge.

### Mobile acceptance

Verified at 360px: no horizontal scroll on any route, tables stacked, path
header middle-collapsed, status bar reduced to mode + user.

### Docs must change in the same PR

`CLAUDE.md`'s design-system section currently *binds future work* to cobalt,
Space Grotesk and the three-blue split. Left unchanged, the next session reverts
this redesign in good faith. Both files are updated alongside the code:

- **`CLAUDE.md`** — retokenise the design-system section; replace the accent
  rules with the inversion rule; keep §36 and the no-ratings rule verbatim.
- **`docs/visual-identity.md`** — add a dated section superseding §1's accent and
  serif decisions, keeping the original reasoning visible rather than deleting
  it. That file exists so decisions are not re-litigated from the brief alone;
  erasing the cobalt rationale would defeat it.

### Branching

`feat/terminal-ui` is cut from **`f60b52c`** (the local merge of PR #6,
voting) — *not* from `main`. Local `main` is stale at `2acff1c`, and `origin/main`
(`d90bb5d`) does not yet contain the voting work that `VoteControl` and
`my_vote` depend on. `f60b52c` is a strict superset of `origin/main`.

Consequence: until PR #6 lands on `origin/main`, a PR from this branch will
include the voting commits. **PR #6 should be merged first.**

`feat/edit-delete-sorting` stays parked; it holds only the unbuilt spec commit
`22c392e`. When it resumes it rebases onto the new UI, and its spec takes a
short addendum noting the sort control lives in `DataTable` headers rather than
in new chrome.

### Risks

| Risk | Mitigation |
| --- | --- |
| Mono body copy is tiring across long discussions | **This is what the pilot exists to catch.** Fallback is the rejected "mono chrome, proportional prose" variant, which costs one token change |
| `ls` tables cannot work at 360px | stacked-row collapse, specced not improvised |
| JetBrains Mono adds a font request | latin subset, `display=swap`, three weights — roughly neutral against dropping Space Grotesk |
| Covers clash with the desaturated ground | low; this is the palette's strength — covers get more dominant, not less |
| `CLAUDE.md` and the code disagree mid-migration | docs land in the same PR, not a follow-up |

### Done means

- `npm test` green
- `npm run build` clean
- `npx playwright test` green against the full stack
- 360px verified on every route
- contrast table re-verified
- `CLAUDE.md` and `docs/visual-identity.md` updated

## Out of scope

Backend, schema and API changes. Edit/delete/soft-delete and thread sorting
(parked on `feat/edit-delete-sorting`, resuming after this ships). A typed
command interface, a ⌘K palette and keyboard-driven navigation — the status bar
reserves room for keyboard hints, but no binding is implemented here.
