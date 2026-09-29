/**
 * What a librarian has picked from search results. Picks can come from
 * earlier searches, so they are listed by name: merge… acts on exactly these.
 */
function SelectionBar({ selected, onMerge, onClear }) {
  const canMerge = selected.length === 2
  return (
    <div role="group" aria-label="Selection" className="flex flex-wrap items-center gap-3 text-xs border-b border-line pb-3">
      <span role="status" className="text-ink-dim tabular-nums">{selected.length} selected</span>
      {selected.length > 0 && (
        <ul aria-label="Selected books" className="flex flex-wrap gap-x-4">
          {selected.map((w) => (
            <li key={w.id}>
              <span className="font-serif text-ink">{w.title}</span> <span className="text-user">{w.author}</span>
            </li>
          ))}
        </ul>
      )}
      <button type="button" className="btn-primary text-xs" disabled={!canMerge} onClick={onMerge}
              aria-describedby={canMerge ? undefined : 'merge-selection-hint'}>
        merge…
      </button>
      {!canMerge && <span id="merge-selection-hint" className="text-ink-dim">select exactly two books to merge</span>}
      {selected.length > 0 && (
        <button type="button" className="btn-ghost text-xs" onClick={onClear}>clear</button>
      )}
    </div>
  )
}

export default SelectionBar
