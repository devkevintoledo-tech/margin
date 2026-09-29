import { useEffect, useRef, useState } from 'react'
import { Link, useLocation, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { useSeries, useSeriesThreads } from '../api/series'
import { useVoteThread } from '../api/threads'
import { useRevertCorrection } from '../api/librarian'
import { errorMessage } from '../api/errors'
import ShelfButton from '../components/ShelfButton'
import GenreLine from '../components/GenreLine'
import PathHeader from '../components/PathHeader'
import DataTable from '../components/DataTable'
import ThreadModal from '../components/ThreadModal'
import LibrarianPanel from '../components/LibrarianPanel'
import VoteControl from '../components/VoteControl'
import { relativeTime } from '../components/Post'
import { useStatusBar } from '../store/status'
import useAuthStore from '../store/auth'
import useLibrarianStore from '../store/librarian'

/**
 * A book's only page. A series lists its books — each with nothing but a
 * shelf control — above one description and the whole series' discussion.
 * A singleton is the same page with the series chrome removed.
 */
/** "#2", "#2.5" — a place in the series; nothing when the catalog has none. */
export function formatPosition(position) {
  return position == null ? null : `#${position}`
}

/** Consecutive books sharing a sub-series, in API order: [{ name, works }]. */
function groupBySubseries(works) {
  const groups = []
  for (const work of works) {
    const name = work.subseries ?? null
    if (groups.length === 0 || groups[groups.length - 1].name !== name) groups.push({ name, works: [] })
    groups[groups.length - 1].works.push(work)
  }
  return groups
}

function BookRow({ work, current, rowRef, editing, isSeries, onAction }) {
  const [coverFailed, setCoverFailed] = useState(false)
  return (
    <li
      ref={rowRef}
      aria-current={current ? 'true' : undefined}
      className={`flex gap-5 py-4 px-2 -mx-2 ${current ? 'bg-highlight' : ''}`}
    >
      {/* Covers carry the colour; large, full colour, never dimmed. */}
      <div className="shrink-0 w-28">
        {work.cover_url && !coverFailed ? (
          <img src={work.cover_url} alt={work.title} onError={() => setCoverFailed(true)} className="w-full border border-line" />
        ) : (
          <div className="w-full aspect-[2/3] bg-panel border border-line flex items-center justify-center p-2">
            <span className="font-serif italic text-ink-dim text-xs text-center">{work.title}</span>
          </div>
        )}
      </div>
      <div className="flex flex-col gap-2 min-w-0">
        {work.position != null && (
          <p className="text-ink-dim text-xs tabular-nums">{formatPosition(work.position)}</p>
        )}
        {editing && work.provenance === 'override' && (
          <span className="text-xs">
            <span aria-hidden="true" className="text-warning">■</span>
            <span className="sr-only">librarian-placed</span>
          </span>
        )}
        <h3 className="font-serif text-xl text-ink leading-tight">{work.title}</h3>
        <p className="text-user text-xs lowercase tracking-eyebrow">{work.author}</p>
        {work.first_publish_year && (
          <p className="text-ink-dim text-xs tabular-nums">{work.first_publish_year}</p>
        )}
        <ShelfButton workId={work.id} currentStatus={work.shelf_status} />
        <GenreLine workId={work.id} title={work.title} />
        {editing && (
          <div className="flex flex-wrap gap-x-3 text-xs" aria-label={`Fix ${work.title}`}>
            {(isSeries ? ['move', 'position', 'remove', 'merge into…', 'split'] : ['move', 'merge into…', 'split']).map((name) => (
              <button key={name} type="button" className="btn-ghost text-xs" onClick={() => onAction(name)}
                      aria-label={`${name} ${work.title}`}>
                {name}
              </button>
            ))}
          </div>
        )}
      </div>
    </li>
  )
}

const KIND_OF = { 'merge into…': 'merge' }

function ResultLine({ correction, currentSlug, onUndone }) {
  const revert = useRevertCorrection()
  const [state, setState] = useState(correction)
  return (
    // A group, not one live region: only the outcome is announced, not the controls.
    <div role="group" aria-label="Librarian fix result" className="flex flex-col gap-2 border-b border-line pb-3">
      <p className="text-xs flex flex-wrap items-center gap-3">
        <span role="status">
          {state.exportable
            ? <span className="text-ok">exported</span>
            : <span className="text-warning">runtime-only: {state.runtime_only_reason}</span>}
          {state.reverted_at && <span className="text-ink-dim ml-3">undone</span>}
        </span>
        {!state.reverted_at && state.undoable && (
          <button type="button" className="btn-ghost text-xs" disabled={revert.isPending}
                  onClick={() => revert.mutate(state.id, { onSuccess: (c) => { setState({ ...state, ...c }); onUndone?.() } })}>
            undo
          </button>
        )}
        {state.room_slug && state.room_slug !== currentSlug && !state.reverted_at && (
          <Link to={`/series/${state.room_slug}?edit=1`} state={{ correction: state }} className="text-path hover:text-accent">
            go to its page
          </Link>
        )}
      </p>
      {/* The server re-checks undo: a newer fix or a changed catalog refuses it. */}
      {revert.isError && <p className="alert-danger text-xs">{errorMessage(revert.error)}</p>}
    </div>
  )
}

function Series() {
  const { slug } = useParams()
  const [searchParams, setSearchParams] = useSearchParams()
  const navigate = useNavigate()
  const user = useAuthStore((s) => s.user)
  const voteMutation = useVoteThread()
  const [showModal, setShowModal] = useState(false)
  const [expanded, setExpanded] = useState(false)
  const [filter, setFilter] = useState(null) // a work id, or null for all books
  const currentRef = useRef(null)
  const location = useLocation()
  // Edit mode is sticky (store/librarian.js) and only ever a librarian's: a
  // reader who inherits `editMode: true` on a shared browser sees nothing.
  const isLibrarian = !!user?.is_librarian
  const editMode = useLibrarianStore((s) => s.editMode)
  const setEditMode = useLibrarianStore((s) => s.setEditMode)
  const editing = isLibrarian && editMode
  const [action, setAction] = useState(null) // { kind, work? } while the panel is open
  // The last fix, shown only on the pages it concerns: where it was made, and
  // the room its book now lives in. The page component survives a slug change.
  const [result, setResult] = useState(() => {
    const correction = location.state?.correction
    return correction ? { correction, pages: [slug, correction.room_slug] } : null
  })

  const { data: series, isLoading, isError } = useSeries(slug)
  // A fix can take the filtered book out of the room; the filter goes with it.
  const bookFilter = series?.works.some((w) => w.id === filter) ? filter : null
  const { data: threads, isLoading: threadsLoading } = useSeriesThreads(series?.slug, bookFilter)

  // A promoted singleton's old slug answers with its survivor.
  useEffect(() => {
    if (series && series.slug !== slug) {
      const qs = searchParams.toString()
      navigate(`/series/${series.slug}${qs ? `?${qs}` : ''}`, { replace: true })
    }
  }, [series, slug, navigate, searchParams])

  // ?edit=1 is a deep link into edit mode (fix-log and "go to its page" links).
  // The store carries it from here, so the address drops it; otherwise a reload
  // after [done] would turn edit mode back on. The state rides along: the
  // "go to its page" link carries the fix report in it.
  useEffect(() => {
    if (!isLibrarian || searchParams.get('edit') !== '1') return
    setEditMode(true)
    const next = new URLSearchParams(searchParams)
    next.delete('edit')
    setSearchParams(next, { replace: true, state: location.state })
  }, [isLibrarian, searchParams, setSearchParams, setEditMode, location.state])

  const bookParam = searchParams.get('book')
  const currentId = series?.works.some((w) => w.id === bookParam) ? bookParam : null
  useEffect(() => {
    currentRef.current?.scrollIntoView?.({ block: 'center' })
  }, [currentId])

  const isSeries = series?.kind === 'series'
  const threadCount = threads?.length ?? 0
  useStatusBar({
    mode: editing ? 'EDIT' : 'SERIES',
    path: series ? `~/series/${series.slug}` : '~/series',
    facts: [`${threadCount} ${threadCount === 1 ? 'thread' : 'threads'}`],
  })

  if (isLoading) {
    return (
      <main className="max-w-shell mx-auto px-4 py-8">
        <div className="animate-pulse flex flex-col gap-4">
          <div className="h-10 bg-panel w-1/2" />
          <div className="h-20 bg-panel w-full" />
        </div>
      </main>
    )
  }
  if (isError || !series) {
    return (
      <main className="max-w-shell mx-auto px-4 py-8">
        <p className="alert-danger">Failed to load this book.</p>
      </main>
    )
  }

  const titleOf = Object.fromEntries(series.works.map((w) => [w.id, w.title]))
  const columns = [
    {
      key: 'score', label: 'Score', align: 'right', width: 8,
      render: (row) => (
        <VoteControl
          variant="row"
          score={row.score ?? 0}
          myVote={row.my_vote ?? 0}
          onVote={(value) => user && voteMutation.mutate({ id: row.id, value, seriesSlug: series.slug })}
          disabled={!user}
          pending={voteMutation.isPending}
        />
      ),
    },
    {
      key: 'title', label: 'Thread',
      render: (row) => (
        <Link to={`/series/${series.slug}/threads/${row.id}`} className="text-ink hover:text-accent transition-colors duration-fast">
          {row.title}
        </Link>
      ),
    },
    ...(isSeries
      ? [{
          key: 'book', label: 'Book', width: 20,
          render: (row) =>
            row.work_id ? <span className="font-serif text-ink-dim">{titleOf[row.work_id] ?? ''}</span> : null,
        }]
      : []),
    { key: 'author', label: 'By', width: 16, render: (row) => <span className="text-user">{row.author}</span> },
    { key: 'post_count', label: 'Repl', align: 'right', width: 6, render: (row) => <span className="text-ink-dim tabular-nums">{row.post_count ?? 0}</span> },
    { key: 'created_at', label: 'Age', align: 'right', width: 6, render: (row) => <span className="text-ink-dim tabular-nums">{relativeTime(row.created_at)}</span> },
  ]

  const filterButton = (id, label) => (
    <button
      key={id ?? 'all'}
      type="button"
      aria-pressed={bookFilter === id}
      onClick={() => setFilter(id)}
      className={`text-xs px-1 transition-colors duration-fast ${
        // Underlined as well as coloured: nothing means anything by colour alone.
        bookFilter === id ? 'text-accent underline underline-offset-4' : 'text-ink-dim hover:text-accent'
      }`}
    >
      {label}
    </button>
  )

  return (
    <main className="max-w-shell mx-auto px-4 py-6 flex flex-col gap-10">
      <div className="flex items-center justify-between gap-3">
        <PathHeader segments={[{ label: 'series', to: '/' }, { label: series.name }]} />
        {isLibrarian && (
          <button type="button" onClick={() => setEditMode(!editing)}
                  className="text-xs text-accent hover:text-accent-hover transition-colors duration-fast">
            {editing ? '[done]' : '[edit]'}
          </button>
        )}
      </div>
      {result && result.pages.includes(series.slug) && (
        <ResultLine key={result.correction.id} correction={result.correction} currentSlug={series.slug} />
      )}

      <header className="flex flex-col gap-3 border-b border-line pb-6">
        {/* Serif is reserved for book titles; a series name is one. */}
        <h1 className="font-serif text-3xl md:text-4xl text-ink leading-tight">{series.name}</h1>
        {isSeries && (
          <p className="text-ink-dim text-xs tabular-nums">
            {series.works.length} {series.works.length === 1 ? 'book' : 'books'} in this series
          </p>
        )}
        {editing && isSeries && !series.dissolved && (
          <div className="flex gap-3 text-xs">
            <button type="button" className="btn-ghost text-xs" onClick={() => setAction({ kind: 'add' })}>add a book</button>
            <button type="button" className="btn-ghost text-xs" onClick={() => setAction({ kind: 'rename' })}>rename series</button>
            <button type="button" className="btn-ghost text-xs" onClick={() => setAction({ kind: 'dissolve' })}>dissolve series</button>
          </div>
        )}
        {series.dissolved && (
          <p className="alert-muted">This series was dissolved; its books have their own pages now.</p>
        )}
        {series.description && (
          <div className="flex flex-col gap-1 max-w-prose">
            <p className={`text-ink-dim text-sm leading-relaxed ${expanded ? '' : 'line-clamp-4'}`}>
              {series.description}
            </p>
            <button type="button" onClick={() => setExpanded((v) => !v)} className="btn-ghost self-start text-xs">
              {expanded ? 'less' : 'more'}
            </button>
          </div>
        )}
      </header>

      <ul aria-label="Books in this series" className="flex flex-col divide-y divide-line">
        {groupBySubseries(series.works).map((group) => {
          const rows = group.works.map((work) => (
            <BookRow
              key={work.id}
              work={work}
              current={work.id === currentId}
              rowRef={work.id === currentId ? currentRef : undefined}
              editing={editing && !series.dissolved}
              isSeries={isSeries}
              onAction={(name) => setAction({ kind: KIND_OF[name] ?? name, work })}
            />
          ))
          if (!group.name) return rows
          // A sub-series inside the room (Mistborn in the Cosmere) gets a heading.
          return (
            <li key={`group-${group.name}`} className="flex flex-col pt-6">
              {/* Serif: a series name is a book title here too. Dim, so it reads as a heading over books. */}
              <h2 className="font-serif text-xl text-ink-dim border-b border-line pb-2">{group.name}</h2>
              <ul aria-label={group.name} className="flex flex-col divide-y divide-line">{rows}</ul>
            </li>
          )
        })}
      </ul>

      <section className="panel p-5 pt-6">
        <h2 className="panel-title">Discussions</h2>
        <div className="flex flex-wrap items-center justify-between gap-3 mb-3">
          {isSeries ? (
            <div role="group" aria-label="Filter by book" className="flex flex-wrap items-center gap-2">
              {filterButton(null, 'all')}
              {series.works.map((w) => filterButton(w.id, w.title))}
            </div>
          ) : (
            <span />
          )}
          {user && !series.dissolved && (
            <button onClick={() => setShowModal(true)} className="btn-secondary text-xs">
              Start a Thread
            </button>
          )}
        </div>
        {threadsLoading ? (
          <div className="flex flex-col gap-2">
            {[1, 2, 3].map((i) => <div key={i} className="h-8 border border-line bg-panel animate-pulse" />)}
          </div>
        ) : (
          <DataTable
            columns={columns}
            rows={threads || []}
            caption={`Discussions about ${series.name}`}
            emptyMessage={user ? 'No discussions yet. Start the first one.' : 'No discussions yet.'}
          />
        )}
      </section>

      {showModal && (
        <ThreadModal
          seriesSlug={series.slug}
          books={isSeries ? series.works.map((w) => ({ id: w.id, title: w.title })) : []}
          defaultBookId={bookFilter ?? currentId ?? ''}
          onClose={() => setShowModal(false)}
          onCreated={(thread) => navigate(`/series/${series.slug}/threads/${thread.id}`)}
        />
      )}
      {action && (
        <LibrarianPanel
          action={{ ...action, series }}
          onClose={() => setAction(null)}
          onDone={(correction) => { setAction(null); setResult({ correction, pages: [series.slug, correction.room_slug] }) }}
        />
      )}
    </main>
  )
}

export default Series
