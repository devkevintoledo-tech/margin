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
    // Combining diacritical marks, left behind by NFD once the base letter is split off.
    .replace(/[̀-ͯ]/g, '')
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')

  if (cleaned.length <= maxLength) return cleaned

  // Truncate on a segment boundary: a path component cut mid-word ("the-dispossess")
  // reads as corruption rather than abbreviation. If the cut lands inside a word,
  // fall back to the last separator before it.
  const window = cleaned.slice(0, maxLength)
  if (cleaned[maxLength] === '-') return window.replace(/-+$/, '')

  const boundary = window.lastIndexOf('-')
  // A single word longer than maxLength has no boundary to retreat to; a hard cut
  // beats returning nothing.
  if (boundary <= 0) return window
  return window.slice(0, boundary).replace(/-+$/, '')
}

export default slug
