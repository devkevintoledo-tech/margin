import { useState } from 'react'

const plural = (n, one, many = `${one}s`) => `${n} ${n === 1 ? one : many}`

function Cover({ side }) {
  // Same answer for "no art" as the series page: the title, never a broken image.
  const [failed, setFailed] = useState(false)
  if (side.cover_url && !failed) {
    return <img src={side.cover_url} alt={side.title} onError={() => setFailed(true)} className="w-full border border-line" />
  }
  return (
    <div className="w-full aspect-[2/3] bg-panel border border-line flex items-center justify-center p-2">
      <span className="font-serif italic text-ink-dim text-xs text-center">{side.title}</span>
    </div>
  )
}

function Side({ side, label, tone }) {
  return (
    // Named by role first: the two halves of a duplicate usually share a title.
    <section aria-label={`${label}: ${side.title}`} className="flex flex-col gap-2 min-w-0">
      <p className={`text-xs uppercase tracking-eyebrow ${tone}`}>{label}</p>
      {/* Covers carry the colour; large, full colour, never dimmed. */}
      <div className="w-28"><Cover side={side} /></div>
      <h3 className="font-serif text-lg text-ink leading-tight">{side.title}</h3>
      <p className="text-user text-xs lowercase tracking-eyebrow">{side.author}</p>
      <p className="text-ink-dim text-xs tabular-nums">{side.first_publish_year ?? 'year unknown'}</p>
      <p className="text-xs lowercase">
        {side.series_name ? (
          <><span className="text-ink-dim">series </span><span className="text-path">{side.series_name}</span></>
        ) : (
          <span className="text-ink-dim">no series</span>
        )}
      </p>
      <dl className="flex flex-wrap gap-x-4 text-xs tabular-nums">
        {[['editions', side.edition_count], ['threads', side.thread_count], ['shelves', side.shelf_count]].map(([name, n]) => (
          <div key={name} className="flex gap-1">
            <dt className="text-ink-dim">{name}</dt>
            <dd className="text-ink">{n}</dd>
          </div>
        ))}
      </dl>
      {side.description && (
        <p className="text-ink-dim text-xs leading-relaxed line-clamp-4">{side.description}</p>
      )}
    </section>
  )
}

/**
 * Two books about to become one, side by side. The left merges away; the
 * right survives. ``onSwap`` flips them (the caller owns which id is which);
 * without it the preview is read-only. ``swapDisabled`` holds it while a
 * request about the current pair is in flight.
 */
function MergePreview({ preview, onSwap, swapDisabled = false }) {
  const { source, target, threads, shelves, editions, genre_votes = 0 } = preview
  return (
    <div role="group" aria-label="Merge preview" className="flex flex-col gap-3">
      <div className="grid grid-cols-2 gap-5">
        {/* Keyed by book, so a swap moves each cover's state with its book. */}
        <Side key={source.id} side={source} label="merges away" tone="text-danger" />
        <Side key={target.id} side={target} label="survives" tone="text-ok" />
      </div>
      <div className="flex flex-wrap items-center gap-3">
        <p className="text-sm text-ink">
          {plural(threads, 'thread')}, {plural(shelves, 'shelf entry', 'shelf entries')},{' '}
          {plural(genre_votes, 'genre vote')} and {plural(editions, 'edition')} move to the survivor.
        </p>
        {onSwap && (
          <button type="button" className="btn-ghost text-xs" onClick={onSwap} disabled={swapDisabled}
                  aria-label="swap which book survives">
            swap
          </button>
        )}
      </div>
    </div>
  )
}

export default MergePreview
