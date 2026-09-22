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
    <nav className="bg-bg border-b border-line sticky top-0 z-40">
      <div className="h-0.5 bg-accent w-full" />
      <div className="max-w-7xl mx-auto px-6 py-3 flex items-center gap-8">
        <Link
          to="/"
          className="shrink-0 font-bold text-lg tracking-tight text-ink hover:text-accent-ink transition-colors duration-fast"
        >
          MARGIN<span className="text-accent-ink">//</span>
        </Link>

        <form onSubmit={handleSearch} className="flex flex-1 max-w-sm">
          <input
            type="search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search books..."
            className="input py-1.5"
          />
          <button
            type="submit"
            className="bg-raised hover:bg-line text-ink-dim hover:text-ink border border-l-0 border-line px-3 py-1.5 text-sm transition-colors duration-fast"
            aria-label="Search"
          >
            ↵
          </button>
        </form>

        <div className="flex items-center gap-5 ml-auto">
          {user ? (
            <>
              <Link to={`/profile/${user.username}`} className="flex items-center gap-2 group">
                <span className="w-7 h-7 bg-accent flex items-center justify-center text-xs font-bold text-white shrink-0">
                  {user.username[0].toUpperCase()}
                </span>
                <span className="text-sm text-ink-dim group-hover:text-ink transition-colors duration-fast hidden sm:block">
                  {user.username}
                </span>
              </Link>
              <button
                onClick={async () => {
                  try { await client.post('/auth/logout') } catch { /* JWT is stateless — clear locally regardless */ }
                  logout()
                }}
                className="text-xs text-ink-muted hover:text-ink-dim transition-colors duration-fast uppercase tracking-widest"
              >
                Out
              </button>
            </>
          ) : (
            <>
              <Link to="/login" className="text-sm text-ink-dim hover:text-ink transition-colors duration-fast">
                Sign in
              </Link>
              <Link to="/register" className="btn-primary text-sm px-3 py-1.5">
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
