import { Link } from 'react-router-dom'

/**
 * Shared shell for the four credential screens (login, register, forgot, reset)
 * so the wordmark, rule and heading rhythm can't drift apart between them.
 */
function AuthLayout({ title, subtitle, children, footer }) {
  return (
    <div className="min-h-[calc(100vh-var(--shell-nav-h))] bg-bg flex items-center justify-center px-4 py-16">
      <div className="w-full max-w-sm">
        <div className="text-center mb-10">
          <Link
            to="/"
            className="font-bold text-lg tracking-tight text-ink hover:text-accent-ink transition-colors duration-fast"
          >
            MARGIN<span className="text-accent-ink">//</span>
          </Link>
          <div className="w-8 h-0.5 bg-accent mx-auto mt-4 mb-6" />
          <h1 className="text-2xl font-bold uppercase tracking-tight text-ink">{title}</h1>
          {subtitle && <p className="text-ink-muted text-sm mt-1.5">{subtitle}</p>}
        </div>

        {children}

        {footer && <div className="text-ink-dim text-sm mt-6 text-center">{footer}</div>}
      </div>
    </div>
  )
}

export default AuthLayout
