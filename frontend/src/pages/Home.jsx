import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import client from '../api/client'
import { useStatusBar } from '../store/status'

const FALLBACK_GENRES = [
  { slug: 'literary-fiction', name: 'Literary Fiction', description: 'Character-driven stories with literary merit.' },
  { slug: 'science-fiction', name: 'Science Fiction', description: 'Speculative worlds, technology, and futures.' },
  { slug: 'fantasy', name: 'Fantasy', description: 'Magic, myth, and invented worlds.' },
  { slug: 'history', name: 'History', description: 'Non-fiction explorations of the past.' },
  { slug: 'philosophy', name: 'Philosophy', description: 'Ideas, ethics, and ways of knowing.' },
  { slug: 'biography', name: 'Biography', description: 'Lives examined and recorded.' },
  { slug: 'mystery', name: 'Mystery', description: 'Puzzles, crimes, and revelations.' },
  { slug: 'poetry', name: 'Poetry', description: 'Language compressed into meaning.' },
]

function Home() {
  const [query, setQuery] = useState('')
  const navigate = useNavigate()

  const { data: genres } = useQuery({
    queryKey: ['genres'],
    queryFn: () => client.get('/genres/').then((r) => r.data),
    placeholderData: FALLBACK_GENRES,
  })

  const list = genres || FALLBACK_GENRES

  useStatusBar({ mode: 'HOME', path: '~', facts: [`${list.length} genres`] })

  const handleSearch = (e) => {
    e.preventDefault()
    if (query.trim()) navigate(`/search?q=${encodeURIComponent(query.trim())}`)
  }

  return (
    <main className="max-w-shell mx-auto px-4 py-10 flex flex-col gap-12">
      {/* Boot banner. The frame is a .panel — CSS borders, not characters, so it
          reflows. This is the only use of display-lg. */}
      <section className="panel p-6 pt-8 max-w-prose">
        <h1 className="panel-title">margin 1.0</h1>
        <p className="text-display-lg text-ink leading-none">
          MARGIN<span className="text-accent">//</span>
        </p>
        <p className="text-accent text-sm mt-3">books worth arguing about</p>
        <p className="text-ink-dim text-sm mt-4 leading-relaxed">
          Threaded discussion anchored to books and genres.
          <br />
          No star ratings. No sanitized reviews. Just honest argument.
        </p>
      </section>

      <form onSubmit={handleSearch} className="flex items-center gap-2 max-w-prose">
        <span aria-hidden="true" className="text-accent select-none">&gt;</span>
        <input
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="search for a book or author"
          aria-label="Search for a book or author"
          className="input"
        />
        <button type="submit" className="btn-primary shrink-0">
          Search
        </button>
      </form>

      {/* `ls`-style listing: name in accent, description dim, on the character grid. */}
      <section className="flex flex-col gap-4">
        <h2 className="text-xs uppercase tracking-eyebrow text-ink-dim border-b border-line pb-2">
          Browse by genre
        </h2>
        <ul className="flex flex-col">
          {list.map((genre) => (
            <li key={genre.slug}>
              <Link
                to={`/genres/${genre.slug}`}
                className="group flex flex-col sm:flex-row sm:items-baseline gap-1 sm:gap-4 py-1.5 px-2 -mx-2
                           hover:bg-highlight transition-colors duration-fast"
              >
                <span className="text-accent group-hover:text-accent-hover sm:w-48 shrink-0">
                  {genre.slug}
                </span>
                <span className="text-ink-dim text-sm truncate">{genre.description}</span>
              </Link>
            </li>
          ))}
        </ul>
      </section>
    </main>
  )
}

export default Home
