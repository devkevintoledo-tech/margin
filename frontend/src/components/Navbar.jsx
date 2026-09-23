import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import useAuthStore from '../store/auth'
import client from '../api/client'

function Navbar() {
  const [query, setQuery] = useState('')
  const navigate = useNavigate()
  const user = useAuthStore((s) => s.user)
  const logout = useAuthStore((s) => s.logout)

  const handleSearch = (e) => {
    e.preventDefault()
    if (query.trim()) {
      navigate(`/search?q=${encodeURIComponent(query.trim())}`)
      setQuery('')
    }
  }

  return (
    <nav className="bg-panel border-b border-line-strong sticky top-0 z-40 h-[var(--shell-nav-h)]">
      <div className="max-w-shell mx-auto px-4 h-full flex items-center gap-6">
        <Link
          to="/"
          className="shrink-0 font-bold text-sm text-ink hover:text-accent transition-colors duration-fast"
        >
          MARGIN<span className="text-accent">//</span>
        </Link>

        {/* type="search" is load-bearing: it keeps this out of getByRole('textbox'),
            which the auth e2e specs rely on to find the email field. */}
        <form onSubmit={handleSearch} className="prompt flex-1 max-w-sm hidden sm:flex">
          <input
            type="search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="search books"
            aria-label="Search books"
            className="input border-0 bg-transparent px-0 py-1 focus:border-0"
          />
          <button
            type="submit"
            className="text-ink-dim hover:text-accent text-sm transition-colors duration-fast shrink-0"
            aria-label="Search"
          >
            ↵
          </button>
        </form>

        <div className="flex items-center gap-4 ml-auto">
          {user ? (
            <>
              <Link to={`/profile/${user.username}`} className="flex items-center gap-2 group">
                <span className="w-5 h-5 bg-user text-bg flex items-center justify-center text-xs font-bold shrink-0">
                  {user.username[0].toUpperCase()}
                </span>
                <span className="text-sm text-user group-hover:text-accent-hover transition-colors duration-fast hidden sm:block">
                  {user.username}
                </span>
              </Link>
              <button
                onClick={async () => {
                  try { await client.post('/auth/logout') } catch { /* JWT is stateless — clear locally regardless */ }
                  logout()
                }}
                className="text-xs text-ink-dim hover:text-danger transition-colors duration-fast uppercase tracking-eyebrow"
              >
                Out
              </button>
            </>
          ) : (
            <>
              <Link to="/login" className="text-sm text-ink-dim hover:text-ink transition-colors duration-fast">
                Sign in
              </Link>
              <Link to="/register" className="btn-primary text-xs px-3 py-1">
                Join
              </Link>
            </>
          )}
        </div>
      </div>
    </nav>
  )
}

export default Navbar
