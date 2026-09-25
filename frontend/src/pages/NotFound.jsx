import { Link, useLocation } from 'react-router-dom'
import { useStatusBar } from '../store/status'

function NotFound() {
  const { pathname } = useLocation()
  useStatusBar({ mode: '404', path: `~${pathname}`, facts: [] })

  return (
    <div className="max-w-shell mx-auto px-4 py-16 flex flex-col gap-6">
      {/* The heading is visually hidden, not removed: the terminal error below is
          decoration, and a screen reader still gets a real page title. */}
      <h1 className="sr-only">Page not found</h1>

      <p className="text-sm">
        <span className="text-danger">margin: </span>
        <span className="text-ink">cannot access </span>
        <span className="text-path">&apos;{pathname}&apos;</span>
        <span className="text-ink">: No such file or directory</span>
      </p>

      <p className="flex items-center gap-2 text-sm">
        <span aria-hidden="true" className="text-accent select-none">&gt;</span>
        <Link
          to="/"
          aria-label="Go home"
          className="text-accent hover:text-accent-hover transition-colors duration-fast"
        >
          cd ~
        </Link>
        <span aria-hidden="true" className="caret text-accent">▌</span>
      </p>
    </div>
  )
}

export default NotFound
