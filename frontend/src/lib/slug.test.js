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
