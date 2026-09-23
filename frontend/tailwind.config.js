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
