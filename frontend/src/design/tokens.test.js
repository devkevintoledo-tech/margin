import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

// The palette is only as good as its worst pair, so the contrast tiers from the
// spec are asserted here rather than trusted to review. Parsing index.css keeps
// this honest: the test reads what actually ships.
//
// The directory is resolved before joining: Vite rewrites a literal
// `new URL('...', import.meta.url)` into an asset URL, which is not a file path.
const cssPath = join(dirname(fileURLToPath(import.meta.url)), '..', 'index.css')
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
