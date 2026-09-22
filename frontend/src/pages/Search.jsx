import { useSearchParams } from 'react-router-dom'
import { useSearchBooks } from '../api/books'
import BookCard from '../components/BookCard'

function Search() {
  const [searchParams] = useSearchParams()
  const q = searchParams.get('q') || ''
  const { data: books, isLoading, isError } = useSearchBooks(q)

  return (
    <main className="max-w-5xl mx-auto px-6 py-10 flex flex-col gap-8">
      <div className="border-b border-line pb-5 flex flex-col gap-2">
        <p className="eyebrow">Search</p>
        <h1 className="text-display-sm font-bold uppercase text-ink">
          {q ? <>&ldquo;{q}&rdquo;</> : 'Find a book'}
        </h1>
        {books && (
          <p className="text-ink-muted text-xs uppercase tracking-wider">
            {books.length} {books.length === 1 ? 'book' : 'books'} found
          </p>
        )}
      </div>

      {!q && <p className="text-ink-dim">Enter a search term to find books.</p>}

      {q.length <= 1 && q.length > 0 && (
        <p className="text-ink-dim">Type at least 2 characters to search.</p>
      )}

      {isLoading && q.length > 1 && (
        <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 gap-5">
          {Array.from({ length: 10 }).map((_, i) => (
            <div key={i} className="animate-pulse flex flex-col gap-3">
              <div className="aspect-[2/3] bg-surface border border-line" />
              <div className="h-3 bg-surface w-3/4" />
              <div className="h-3 bg-surface w-1/2" />
            </div>
          ))}
        </div>
      )}

      {isError && <p className="text-danger text-sm">Failed to load results. Please try again.</p>}

      {books && books.length === 0 && <p className="text-ink-dim">No books found for &ldquo;{q}&rdquo;.</p>}

      {books && books.length > 0 && (
        <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 gap-5">
          {books.map((book) => (
            <BookCard key={book.id} book={book} />
          ))}
        </div>
      )}
    </main>
  )
}

export default Search
