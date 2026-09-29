import { useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { useSearchWorks } from '../api/works'
import WorkCard from '../components/WorkCard'
import LibrarianPanel from '../components/LibrarianPanel'
import SelectionBar from '../components/librarian/SelectionBar'
import { useStatusBar } from '../store/status'
import useAuthStore from '../store/auth'

function Search() {
  const [searchParams] = useSearchParams()
  const q = searchParams.get('q') || ''
  const { data: works, isLoading, isError } = useSearchWorks(q)
  const navigate = useNavigate()
  const librarian = useAuthStore((s) => !!s.user?.is_librarian)
  // Librarian select mode. The selection outlives a new search: the two halves
  // of a duplicate often only turn up under different queries.
  const [selecting, setSelecting] = useState(false)
  const [selected, setSelected] = useState([]) // works, in the order picked
  const [merging, setMerging] = useState(false)
  const choosing = librarian && selecting

  const toggle = (work) =>
    setSelected((s) => (s.some((w) => w.id === work.id) ? s.filter((w) => w.id !== work.id) : [...s, work]))
  const toggleSelecting = () => {
    setSelecting((v) => !v)
    setSelected([])
  }

  useStatusBar({
    mode: 'SEARCH',
    path: q ? `~/search?q=${q}` : '~/search',
    facts: works ? [`${works.length} results`] : [],
  })

  return (
    <main className="max-w-shell mx-auto px-4 py-6 flex flex-col gap-8">
      <div className="border-b border-line pb-4 flex flex-wrap items-end justify-between gap-3">
        <div className="flex flex-col gap-1">
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
        {librarian && (
          <button type="button" aria-pressed={choosing} onClick={toggleSelecting}
                  className={choosing ? 'btn-secondary text-xs' : 'btn-ghost text-xs'}>
            select
          </button>
        )}
      </div>

      {choosing && (
        <SelectionBar selected={selected} onClear={() => setSelected([])} onMerge={() => setMerging(true)} />
      )}

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
            <WorkCard
              key={work.id}
              work={work}
              {...(choosing ? { selected: selected.some((w) => w.id === work.id), onSelect: toggle } : {})}
            />
          ))}
        </div>
      )}

      {choosing && merging && selected.length === 2 && (
        <LibrarianPanel
          // The first pick merges into the second; the preview's swap flips them.
          action={{ kind: 'merge', work: selected[0], into: selected[1] }}
          onClose={() => setMerging(false)}
          onDone={(correction) => {
            setMerging(false)
            setSelecting(false)
            setSelected([])
            // The survivor's page shows the result line, the same as a fix made there.
            if (correction.room_slug) navigate(`/series/${correction.room_slug}`, { state: { correction } })
          }}
        />
      )}
    </main>
  )
}

export default Search
