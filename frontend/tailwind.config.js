/**
 * MARGIN design system.
 *
 * Every color is a semantic token backed by a CSS variable in `src/index.css`
 * (stored as raw `R G B` channels so Tailwind's `/opacity` modifiers still
 * work, e.g. `border-line/60`). Never write a raw `zinc-*`, hex, or arbitrary
 * color in a component — add a token here instead.
 *
 * Accent usage rules (WCAG AA against `bg` #0D0D0D):
 *   accent       fills, rules, focus borders. White/ink text on it passes 5.5:1.
 *   accent-hover fill hover only.
 *   accent-ink   accent-colored TEXT on a dark surface (7.2:1). Never a fill.
 *   ink-muted    decorative/non-essential text only (3.3:1) — never body copy.
 */
const token = (name) => `rgb(var(--color-${name}) / <alpha-value>)`

export default {
  content: ['./index.html', './src/**/*.{js,jsx}'],
  theme: {
    extend: {
      colors: {
        bg: token('bg'),
        surface: token('surface'),
        raised: token('raised'),
        line: token('line'),
        'line-strong': token('line-strong'),
        ink: token('ink'),
        'ink-dim': token('ink-dim'),
        'ink-muted': token('ink-muted'),
        accent: token('accent'),
        'accent-hover': token('accent-hover'),
        'accent-ink': token('accent-ink'),
        success: token('success'),
        warning: token('warning'),
        danger: token('danger'),
      },
      fontFamily: {
        sans: ['"Space Grotesk"', 'system-ui', 'sans-serif'],
        serif: ['"Playfair Display"', 'Georgia', 'serif'],
      },
      fontSize: {
        // Editorial display sizes. Headlines are confident and tight-tracked;
        // §6 of the brand doc: "use large typography to establish hierarchy".
        'display-sm': ['2.5rem', { lineHeight: '1.1', letterSpacing: '-0.02em' }],
        display: ['3.5rem', { lineHeight: '1.05', letterSpacing: '-0.025em' }],
        'display-lg': ['5rem', { lineHeight: '1', letterSpacing: '-0.03em' }],
      },
      letterSpacing: {
        eyebrow: '0.25em',
      },
      transitionDuration: {
        // Interaction is subtle and fast (§26). Nothing animates longer than base.
        fast: '120ms',
        base: '180ms',
      },
    },
  },
  plugins: [],
}
