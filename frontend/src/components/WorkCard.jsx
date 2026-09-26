import { useState } from 'react'
import { Link } from 'react-router-dom'
import { seriesHref } from '../api/series'

function WorkCard({ work }) {
  const { title, author, cover_url, edition_count, series } = work
  // A cover URL can 404 or be pulled upstream. Falling back to the same
  // placeholder the no-cover case uses keeps one visual answer for "no art"
  // rather than a broken-image glyph.
  const [coverFailed, setCoverFailed] = useState(false)
  const showCover = cover_url && !coverFailed

  return (
    <Link to={seriesHref(work)} className="group flex flex-col">
      {/* Covers carry most of the color in the UI (§13), so they stay large and
          unobstructed — the frame reacts on hover, the art never dims. */}
      <div className="aspect-[2/3] bg-panel border border-line group-hover:border-accent transition-colors duration-base overflow-hidden">
        {showCover ? (
          <img
            src={cover_url}
            alt={title}
            loading="lazy"
            onError={() => setCoverFailed(true)}
            className="w-full h-full object-cover group-hover:scale-[1.03] transition-transform duration-base"
          />
        ) : (
          <div className="w-full h-full flex items-center justify-center p-4">
            <span className="font-serif italic text-ink-dim text-xs text-center">{title}</span>
          </div>
        )}
      </div>
      <div className="pt-3 flex flex-col gap-1">
        <p className="font-serif text-ink text-sm leading-snug line-clamp-2 group-hover:text-accent transition-colors duration-fast">
          {title}
        </p>
        <p className="text-ink-dim text-xs lowercase tracking-eyebrow line-clamp-1">{author}</p>
        {/* A reference to the book's room, so it takes the path colour. Text,
            not a glyph: the literal-glyph set is closed. */}
        {series?.kind === 'series' && (
          <p className="text-xs lowercase line-clamp-1">
            <span className="text-ink-dim">series </span>
            <span className="text-path">{series.name}</span>
          </p>
        )}
        {/* Search collapses many editions into one card; saying so keeps the
            smaller result count legible rather than mysterious. */}
        {edition_count > 1 && (
          <p className="text-ink-dim text-xs tabular-nums">{edition_count} editions</p>
        )}
      </div>
    </Link>
  )
}

export default WorkCard
