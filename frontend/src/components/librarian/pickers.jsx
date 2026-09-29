import { useEffect, useId, useState } from 'react'
import { useSeriesSearch } from '../../api/librarian'
import { useSearchWorks } from '../../api/works'

/**
 * Search-and-pick controls every librarian float shares. Each is a labelled
 * search box over a radiogroup of hits; picking one hands the hit back. They
 * decide nothing; the panel that uses them does.
 */
const plural = (n, one, many = `${one}s`) => `${n} ${n === 1 ? one : many}`

/** ``value`` once it has stopped changing for ``ms``. */
function useDebounced(value, ms = 300) {
  const [settled, setSettled] = useState(value)
  useEffect(() => {
    const timer = setTimeout(() => setSettled(value), ms)
    return () => clearTimeout(timer)
  }, [value, ms])
  return settled
}

export function SeriesPicker({ label = 'Find a series', value, onChange }) {
  const id = useId()
  const [q, setQ] = useState('')
  const { data: hits = [] } = useSeriesSearch(q)
  const named = q.trim()
  return (
    <div className="flex flex-col gap-2">
      <label className="label" htmlFor={id}>{label}</label>
      <input id={id} type="text" className="input" value={q} onChange={(e) => setQ(e.target.value)} />
      <div role="radiogroup" aria-label={`${label}: results`} className="flex flex-col gap-1 text-sm">
        {hits.map((s) => (
          <label key={s.id} className="flex items-center gap-2">
            <input type="radio" name={id} checked={value?.id === s.id} onChange={() => onChange(s)} />
            <span className="font-serif text-ink">{s.name}</span>
            <span className="text-ink-dim tabular-nums">{plural(s.book_count, 'book')}</span>
          </label>
        ))}
        {named.length > 1 && !hits.some((s) => s.name.toLowerCase() === named.toLowerCase()) && (
          <label className="flex items-center gap-2">
            <input type="radio" name={id} checked={!value?.id && value?.name === named}
                   onChange={() => onChange({ name: named })} />
            <span className="text-warning">new series: {named}</span>
          </label>
        )}
      </div>
    </div>
  )
}

export function WorkPicker({ label = 'Find a book', exclude, value, onChange }) {
  const id = useId()
  const [q, setQ] = useState('')
  // A cold search reaches Open Library and ingests what it finds: never per keystroke.
  const { data: works = [] } = useSearchWorks(useDebounced(q.trim()))
  return (
    <div className="flex flex-col gap-2">
      <label className="label" htmlFor={id}>{label}</label>
      <input id={id} type="text" className="input" value={q} onChange={(e) => setQ(e.target.value)} />
      <div role="radiogroup" aria-label={`${label}: results`} className="flex flex-col gap-1 text-sm">
        {works.filter((w) => w.id !== exclude).map((w) => (
          <label key={w.id} className="flex items-center gap-2">
            <input type="radio" name={id} checked={value?.id === w.id} onChange={() => onChange(w)} />
            <span className="font-serif text-ink">{w.title}</span>
            <span className="text-user text-xs">{w.author}</span>
            {/* Where it lives now, so a librarian sees a move coming before picking. */}
            {w.series?.kind === 'series' && (
              <span className="text-ink-dim text-xs">in <span className="font-serif">{w.series.name}</span></span>
            )}
          </label>
        ))}
      </div>
    </div>
  )
}
