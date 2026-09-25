import { useSearchParams } from 'react-router-dom'
import { useSearchWorks } from '../api/works'
import WorkCard from '../components/WorkCard'
import { useStatusBar } from '../store/status'

function Search() {
  const [searchParams] = useSearchParams()
  const q = searchParams.get('q') || ''
  const { data: works, isLoading, isError } = useSearchWorks(q)

  useStatusBar({
    mode: 'SEARCH',
    path: q ? `~/search?q=${q}` : '~/search',
    facts: works ? [`${works.length} results`] : [],
  })

  return (
    <main className="max-w-shell mx-auto px-4 py-6 flex flex-col gap-8">
      <div className="border-b border-line pb-4 flex flex-col gap-1">
        <h1 className="text-lg text-ink">
          <span aria-hidden="true" className="text-accent">$ </span>
          search {q && <span className="text-path">&quot;{q}&quot;</span>}
        </h1>
        {works && (
          <p className="text-ink-dim text-xs tabular-nums">
            {works.length} {works.length === 1 ? 'result' : 'results'}
          </p>
        )}
      </div>

      {!q && <p className="text-ink-dim text-sm">Enter a search term to find books.</p>}

      {q.length === 1 && (
        <p className="text-ink-dim text-sm">Type at least 2 characters to search.</p>
      )}

      {isLoading && q.length > 1 && (
        <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 gap-5">
          {Array.from({ length: 10 }).map((_, i) => (
            <div key={i} className="animate-pulse flex flex-col gap-3">
              <div className="aspect-[2/3] bg-panel border border-line" />
              <div className="h-3 bg-panel w-3/4" />
              <div className="h-3 bg-panel w-1/2" />
            </div>
          ))}
        </div>
      )}

      {isError && <p className="alert-danger">Failed to load results. Please try again.</p>}

      {works && works.length === 0 && (
        <p className="text-ink-dim text-sm">No books found for &quot;{q}&quot;.</p>
      )}

      {works && works.length > 0 && (
        <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 gap-5">
          {works.map((work) => (
            <WorkCard key={work.id} work={work} />
          ))}
        </div>
      )}
    </main>
  )
}

export default Search
