import { useEffect, useState } from 'react'
import { useGenreTree } from '../api/genres'
import GenrePicker from './GenrePicker'

/**
 * `genre [space-opera ×] [+]   author [____]   year [____]–[____]`.
 * Controlled by the URL: the page owns the values and applies each patch.
 * Text fields apply on Enter or blur, so typing doesn't search per keystroke.
 */
function SearchFilters({ genres, author, yearFrom, yearTo, onChange }) {
  const { data: tree = [] } = useGenreTree()
  const [picking, setPicking] = useState(false)
  const [draft, setDraft] = useState({ author, yearFrom, yearTo })
  useEffect(() => setDraft({ author, yearFrom, yearTo }), [author, yearFrom, yearTo])

  const field = (key) => ({
    value: draft[key],
    onChange: (e) => setDraft((d) => ({ ...d, [key]: e.target.value })),
    onBlur: () => { if (draft[key].trim() !== { author, yearFrom, yearTo }[key]) onChange({ [key]: draft[key].trim() }) },
  })

  return (
    <form
      aria-label="Filter results"
      className="flex flex-wrap items-baseline gap-x-6 gap-y-2 text-xs"
      onSubmit={(e) => {
        e.preventDefault()
        onChange({ author: draft.author.trim(), yearFrom: draft.yearFrom.trim(), yearTo: draft.yearTo.trim() })
      }}
    >
      <div className="relative flex flex-wrap items-baseline gap-2">
        <span className="text-ink-dim">genre</span>
        {genres.map((slug) => (
          <span key={slug} className="flex items-baseline gap-1">
            <span className="text-path">{slug}</span>
            <button type="button" className="btn-ghost text-xs" aria-label={`remove genre ${slug}`}
                    onClick={() => onChange({ genres: genres.filter((g) => g !== slug) })}>
              <span aria-hidden="true">×</span>
            </button>
          </span>
        ))}
        <button type="button" className="btn-ghost text-xs" aria-label="add a genre filter" aria-expanded={picking}
                onClick={() => setPicking((v) => !v)}>[+]</button>
        {picking && (
          <div className="absolute z-10 top-full left-0 mt-1">
            <GenrePicker tree={tree} selected={new Set(genres)} label="filter by genre"
                         onToggle={(slug, on) => onChange({ genres: on ? [...genres, slug] : genres.filter((g) => g !== slug) })}
                         onClose={() => setPicking(false)} />
          </div>
        )}
      </div>
      <label className="flex items-baseline gap-2">
        <span className="text-ink-dim">author</span>
        <input type="text" aria-label="author" className="input w-[24ch]" {...field('author')} />
      </label>
      <span className="flex items-baseline gap-2">
        <span className="text-ink-dim">year</span>
        <input type="number" inputMode="numeric" aria-label="from year" className="input w-[8ch]" {...field('yearFrom')} />
        <span aria-hidden="true" className="text-ink-faint">–</span>
        <input type="number" inputMode="numeric" aria-label="to year" className="input w-[8ch]" {...field('yearTo')} />
      </span>
      <button type="submit" className="sr-only">apply filters</button>
    </form>
  )
}

export default SearchFilters
