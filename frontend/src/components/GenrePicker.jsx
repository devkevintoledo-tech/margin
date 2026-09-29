import { useEffect, useId, useMemo, useState } from 'react'

/**
 * A curated-list picker: the input only filters the taxonomy, it never
 * submits text. Controlled — the parent owns `selected` and decides what a
 * toggle does (vote, or add a search filter).
 */
function GenrePicker({ tree, selected, onToggle, onClose, max, label }) {
  const [query, setQuery] = useState('')
  const [active, setActive] = useState(0)
  const listId = useId()

  const rows = useMemo(() => {
    const q = query.trim().toLowerCase()
    const hit = (g) => !q || g.slug.includes(q.replace(/\s+/g, '-')) || g.name.toLowerCase().includes(q)
    const out = []
    for (const parent of tree) {
      const kids = parent.children.filter(hit)
      // A parent shown only as context for a matching subgenre is not a hit.
      if (hit(parent) || kids.length) out.push({ ...parent, depth: 0, hit: hit(parent) })
      kids.forEach((kid, i) => out.push({ ...kid, depth: 1, hit: true, last: i === kids.length - 1 }))
    }
    return out
  }, [tree, query])

  // Enter acts on the first real match, never on a context-only parent row.
  useEffect(() => setActive(Math.max(0, rows.findIndex((r) => r.hit))), [rows])

  const full = max != null && selected.size >= max
  const disabled = (row) => full && !selected.has(row.slug)
  const toggle = (row) => {
    if (!row || disabled(row)) return
    onToggle(row.slug, !selected.has(row.slug), row.name)
  }

  const onKeyDown = (e) => {
    if (e.key === 'ArrowDown') { e.preventDefault(); setActive((a) => Math.min(a + 1, rows.length - 1)) }
    else if (e.key === 'ArrowUp') { e.preventDefault(); setActive((a) => Math.max(a - 1, 0)) }
    else if (e.key === 'Enter') { e.preventDefault(); toggle(rows[active]) }
    else if (e.key === 'Escape') { e.preventDefault(); onClose() }
  }

  return (
    <div className="float p-3 flex flex-col gap-2 w-[36ch] max-w-full" role="dialog" aria-label={label}>
      <div className="flex items-baseline justify-between gap-3 text-xs">
        <span className="text-ink-dim">{label}</span>
        {max != null && <span className="text-ink-dim tabular-nums">{selected.size}/{max} tagged</span>}
      </div>
      <input
        autoFocus
        role="combobox"
        aria-label="filter genres"
        aria-expanded="true"
        aria-controls={listId}
        aria-activedescendant={rows[active] ? `${listId}-${rows[active].slug}` : undefined}
        className="input"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        onKeyDown={onKeyDown}
      />
      {rows.length === 0 ? (
        <p className="text-ink-dim text-xs">no such genre — the list is curated</p>
      ) : (
        <ul id={listId} role="listbox" aria-multiselectable="true" className="max-h-72 overflow-y-auto text-sm">
          {rows.map((row, i) => (
            <li
              key={row.slug}
              id={`${listId}-${row.slug}`}
              role="option"
              aria-selected={selected.has(row.slug)}
              aria-disabled={disabled(row) ? 'true' : undefined}
              onMouseDown={(e) => e.preventDefault()}
              onClick={() => toggle(row)}
              className={`flex gap-2 px-1 cursor-pointer ${i === active ? 'bg-highlight' : ''} ${
                disabled(row) ? 'text-ink-dim cursor-not-allowed' : ''}`}
            >
              {row.depth === 1 && <span aria-hidden="true" className="text-ink-faint">{row.last ? '└─' : '├─'}</span>}
              <span className={selected.has(row.slug) ? 'text-accent underline underline-offset-4' : 'text-path'}>
                {row.slug}
              </span>
            </li>
          ))}
        </ul>
      )}
      {full && <p className="text-ink-dim text-xs">remove one to add another</p>}
      <div className="flex justify-end">
        <button type="button" className="btn-ghost text-xs" onClick={onClose}>[done]</button>
      </div>
    </div>
  )
}

export default GenrePicker
