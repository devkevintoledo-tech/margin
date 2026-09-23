import { Link } from 'react-router-dom'

function BookCard({ book }) {
  const { id, title, author, cover_url } = book

  return (
    <Link to={`/books/${id}`} className="group flex flex-col">
      {/* Covers carry most of the color in the UI (§13), so they stay large and
          unobstructed — the frame reacts on hover, the art never dims. */}
      <div className="aspect-[2/3] bg-panel border border-line group-hover:border-accent transition-colors duration-base overflow-hidden">
        {cover_url ? (
          <img
            src={cover_url}
            alt={title}
            loading="lazy"
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
      </div>
    </Link>
  )
}

export default BookCard
