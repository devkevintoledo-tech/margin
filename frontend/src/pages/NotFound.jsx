import { Link } from 'react-router-dom'

function NotFound() {
  return (
    <div className="flex flex-col items-center justify-center min-h-[60vh] gap-5 text-center px-6">
      <span className="text-display-lg font-bold text-accent leading-none tabular-nums">404</span>
      <h1 className="text-2xl font-bold uppercase tracking-tight text-ink">Page not found</h1>
      <p className="text-ink-dim text-sm max-w-xs leading-relaxed">
        The page you're looking for doesn't exist or has been moved.
      </p>
      <Link to="/" className="btn-primary mt-2">
        Go home
      </Link>
    </div>
  )
}

export default NotFound
