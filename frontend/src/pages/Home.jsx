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
      {/* Hero */}
      <section className="border-b border-zinc-800/60 px-6 py-24 md:py-32">
        <div className="max-w-3xl mx-auto flex flex-col items-center text-center gap-8">
          <p className="text-xs uppercase tracking-[0.25em] text-amber-600 font-medium">
            Books worth arguing about
          </p>
          <h1 className="font-serif text-6xl md:text-7xl text-zinc-100 leading-[1.1] tracking-tight">
            Where <span className="italic">serious</span> readers talk.
          </h1>
          <p className="text-zinc-500 text-lg max-w-lg leading-relaxed">
            Threaded discussion anchored to books and genres. No star ratings. No sanitized reviews. Just honest argument.
          </p>
          <form onSubmit={handleSearch} className="flex w-full max-w-xl mt-2">
            <input
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search for a book or author..."
              className="flex-1 bg-zinc-900 border border-zinc-700 text-zinc-100 placeholder-zinc-600 px-5 py-4 text-base focus:outline-none focus:border-amber-700 transition-colors"
            />
            <button
              type="submit"
              className="bg-amber-700 hover:bg-amber-600 text-zinc-100 px-8 py-4 text-sm font-semibold uppercase tracking-widest transition-colors shrink-0"
            >
              Search
            </button>
          </form>
        </div>
      </section>

      {/* Genres */}
      <section className="max-w-5xl mx-auto px-6 py-16 w-full flex flex-col gap-8">
        <div className="flex items-baseline gap-4">
          <span className="w-0.5 h-5 bg-amber-600 shrink-0" />
          <h2 className="font-serif text-2xl text-zinc-100 tracking-tight">
            Browse by Genre
          </h2>
        </div>
        <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-4 gap-px bg-zinc-800/40">
          {(genres || FALLBACK_GENRES).map((genre) => (
            <GenreCard key={genre.slug} genre={genre} />
          ))}
        </div>
      </section>
    </main>
  )
}

export default Home
