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
