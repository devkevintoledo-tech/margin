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
    <nav className="bg-zinc-950 border-b border-zinc-800/60">
      <div className="h-0.5 bg-amber-600 w-full" />
      <div className="max-w-7xl mx-auto px-6 py-3 flex items-center gap-8">
        <Link to="/" className="font-serif text-xl text-zinc-100 tracking-tight shrink-0 hover:text-amber-500 transition-colors">
          <span className="italic">M</span>arginalia
        </Link>

        <form onSubmit={handleSearch} className="flex flex-1 max-w-sm">
          <input
            type="search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search books..."
            className="flex-1 bg-zinc-900 text-zinc-100 placeholder-zinc-600 border border-zinc-800 px-3 py-1.5 text-sm focus:outline-none focus:border-amber-700 transition-colors"
          />
          <button
            type="submit"
            className="bg-zinc-800 hover:bg-zinc-700 text-zinc-400 hover:text-zinc-200 border border-l-0 border-zinc-800 px-3 py-1.5 text-sm transition-colors"
          >
            ↵
          </button>
        </form>

        <div className="flex items-center gap-5 ml-auto">
          {user ? (
            <>
              <Link
                to={`/profile/${user.username}`}
                className="flex items-center gap-2 group"
              >
                <span className="w-7 h-7 rounded-full bg-amber-700 flex items-center justify-center text-xs font-semibold text-zinc-100 shrink-0">
                  {user.username[0].toUpperCase()}
                </span>
                <span className="text-sm text-zinc-400 group-hover:text-zinc-100 transition-colors hidden sm:block">
                  {user.username}
                </span>
              </Link>
              <button
                onClick={async () => {
                  try { await client.post('/auth/logout') } catch { /* JWT is stateless — clear locally regardless */ }
                  logout()
                }}
                className="text-xs text-zinc-600 hover:text-zinc-400 transition-colors uppercase tracking-widest"
              >
                Out
              </button>
            </>
          ) : (
            <>
              <Link
                to="/login"
                className="text-sm text-zinc-400 hover:text-zinc-100 transition-colors"
              >
                Sign in
              </Link>
              <Link
                to="/register"
                className="text-sm bg-amber-700 text-zinc-100 px-3 py-1.5 font-medium hover:bg-amber-600 transition-colors"
              >
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
