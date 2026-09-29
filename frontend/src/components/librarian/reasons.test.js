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
