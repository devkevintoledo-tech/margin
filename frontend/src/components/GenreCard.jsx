import { Link } from 'react-router-dom'

function GenreCard({ genre }) {
  const { slug, name, description } = genre

  return (
    <Link
      to={`/genres/${slug}`}
      className="group bg-bg hover:bg-surface transition-colors duration-fast p-5 flex flex-col gap-2"
    >
      <div className="flex items-center gap-2">
        <span className="w-0.5 h-4 bg-accent group-hover:bg-accent-hover transition-colors duration-fast shrink-0" />
        {/* Serif is reserved for works; a genre is structure, so it stays sans. */}
        <h3 className="text-sm font-semibold uppercase tracking-wider text-ink leading-tight group-hover:text-accent-ink transition-colors duration-fast">
          {name}
        </h3>
      </div>
      {description && (
        <p className="text-ink-dim text-xs leading-relaxed line-clamp-2 pl-2.5">{description}</p>
      )}
    </Link>
  )
}

export default GenreCard
