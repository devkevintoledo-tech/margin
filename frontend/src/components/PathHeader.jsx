import { Link } from 'react-router-dom'
import { slug } from '../lib/slug'

/**
 * The page's location rendered as a filesystem path — `~/works/the-dispossessed`.
 * Replaces breadcrumbs and makes the app's shape legible.
 *
 * Segments are explicit rather than derived from the URL: routes carry ids, but
 * a path wants titles, and only the page knows those.
 *
 * On narrow viewports the middle segments hide (CSS, not JS) and an ellipsis
 * stands in, so the leaf — the part that says where you are — always survives.
 */
function PathHeader({ segments = [] }) {
  if (segments.length === 0) return null

  const middles = segments.slice(0, -1)
  const leaf = segments[segments.length - 1]

  const separator = (
    <span aria-hidden="true" className="text-ink-faint px-0.5">
      /
    </span>
  )

  const segmentClass =
    'text-path hover:text-accent-hover transition-colors duration-fast'

  return (
    <nav aria-label="Breadcrumb" className="text-sm overflow-hidden">
      <ol className="flex items-center">
        <li className="flex items-center">
          <Link to="/" className={segmentClass}>
            ~
          </Link>
        </li>

        {middles.map((seg, i) => (
          <li key={`${seg.label}-${i}`} className="hidden sm:flex items-center min-w-0">
            {separator}
            {seg.to ? (
              <Link to={seg.to} className={`${segmentClass} truncate`}>
                {slug(seg.label)}
              </Link>
            ) : (
              <span className="text-ink-dim truncate">{slug(seg.label)}</span>
            )}
          </li>
        ))}

        {middles.length > 0 && (
          <li className="flex sm:hidden items-center" aria-hidden="true">
            {separator}
            <span className="text-ink-faint">…</span>
          </li>
        )}

        <li className="flex items-center min-w-0">
          {separator}
          {leaf.to ? (
            <Link to={leaf.to} className={`${segmentClass} truncate`}>
              {slug(leaf.label)}
            </Link>
          ) : (
            <span className="text-ink-dim truncate">{slug(leaf.label)}</span>
          )}
        </li>
      </ol>
    </nav>
  )
}

export default PathHeader
