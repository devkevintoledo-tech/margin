import { Link } from 'react-router-dom'

/**
 * Shared shell for the four credential screens, framed as a login prompt so the
 * wordmark, frame and heading rhythm can't drift apart between them.
 *
 * `title` is passed through verbatim — Login's "Sign in" and Register's
 * "Create account" are asserted by accessible name in the unit and e2e suites.
 */
function AuthLayout({ title, subtitle, children, footer }) {
  return (
    <div className="min-h-[calc(100vh-var(--shell-nav-h))] bg-bg flex items-center justify-center px-4 py-16">
      <div className="w-full max-w-sm panel p-6 pt-8">
        <p className="panel-title">
          <Link to="/" className="text-ink-dim hover:text-accent transition-colors duration-fast">
            margin//
          </Link>
        </p>

        <div className="mb-6">
          <h1 className="text-lg text-ink">
            <span aria-hidden="true" className="text-accent">$ </span>
            {title}
          </h1>
          {subtitle && <p className="text-ink-dim text-xs mt-1">{subtitle}</p>}
        </div>

        {children}

        {footer && <div className="text-ink-dim text-xs mt-6">{footer}</div>}
      </div>
    </div>
  )
}

export default AuthLayout
