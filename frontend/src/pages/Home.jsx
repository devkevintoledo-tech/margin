import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import client from '../api/client'
import GenreCard from '../components/GenreCard'

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

  const handleSearch = (e) => {
    e.preventDefault()
    if (query.trim()) {
      navigate(`/search?q=${encodeURIComponent(query.trim())}`)
    }
  }

  return (
    <main className="flex flex-col">
      {/* Hero — full-width editorial masthead, not a card (§7). */}
      <section className="border-b border-line px-6 py-20 md:py-28">
        <div className="max-w-5xl mx-auto flex flex-col gap-10">
          <p className="eyebrow">Books worth arguing about</p>

          <h1 className="text-display-sm md:text-display lg:text-display-lg font-bold uppercase text-ink max-w-4xl">
            Books worth
            <br />
            <span className="text-accent-ink">fighting</span> about.
          </h1>

          <p className="text-ink-dim text-lg max-w-xl leading-relaxed">
            Threaded discussion anchored to books and genres. No star ratings. No sanitized
            reviews. Just honest argument.
          </p>

          <form onSubmit={handleSearch} className="flex w-full max-w-2xl">
            <input
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search for a book or author..."
              className="input px-5 py-4 text-base"
            />
            <button type="submit" className="btn-primary-lg shrink-0">
              Search
            </button>
          </form>
        </div>
      </section>

      {/* Genres */}
      <section className="max-w-5xl mx-auto px-6 py-16 w-full flex flex-col gap-8">
        <div className="flex items-baseline gap-4">
          <span className="rule" />
          <h2 className="text-sm font-semibold uppercase tracking-eyebrow text-ink">Browse by genre</h2>
        </div>
        {/* Hairline grid: one shared border between tiles, no floating cards. */}
        <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-4 gap-px bg-line">
          {(genres || FALLBACK_GENRES).map((genre) => (
            <GenreCard key={genre.slug} genre={genre} />
          ))}
        </div>
      </section>
    </main>
  )
}

export default Home
