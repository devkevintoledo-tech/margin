import { useEffect, useRef, useState } from 'react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { useSeries, useSeriesThreads } from '../api/series'
import { useVoteThread } from '../api/threads'
import ShelfButton from '../components/ShelfButton'
import PathHeader from '../components/PathHeader'
import DataTable from '../components/DataTable'
import ThreadModal from '../components/ThreadModal'
import VoteControl from '../components/VoteControl'
import { relativeTime } from '../components/Post'
import { useStatusBar } from '../store/status'
import useAuthStore from '../store/auth'

/**
 * A book's only page. A series lists its books — each with nothing but a
 * shelf control — above one description and the whole series' discussion.
 * A singleton is the same page with the series chrome removed.
 */
function BookRow({ work, current, rowRef }) {
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
        <h3 className="font-serif text-xl text-ink leading-tight">{work.title}</h3>
        <p className="text-user text-xs lowercase tracking-eyebrow">{work.author}</p>
        {work.first_publish_year && (
          <p className="text-ink-dim text-xs tabular-nums">{work.first_publish_year}</p>
        )}
        <ShelfButton workId={work.id} currentStatus={work.shelf_status} />
      </div>
    </li>
  )
}

function Series() {
  const { slug } = useParams()
  const [searchParams] = useSearchParams()
  const navigate = useNavigate()
  const user = useAuthStore((s) => s.user)
  const voteMutation = useVoteThread()
  const [showModal, setShowModal] = useState(false)
  const [expanded, setExpanded] = useState(false)
  const [filter, setFilter] = useState(null) // a work id, or null for all books
  const currentRef = useRef(null)

  const { data: series, isLoading, isError } = useSeries(slug)
  const { data: threads, isLoading: threadsLoading } = useSeriesThreads(series?.slug, filter)

  // A promoted singleton's old slug answers with its survivor.
  useEffect(() => {
    if (series && series.slug !== slug) {
      navigate(`/series/${series.slug}?${searchParams}`, { replace: true })
    }
  }, [series, slug, navigate, searchParams])

  const bookParam = searchParams.get('book')
  const currentId = series?.works.some((w) => w.id === bookParam) ? bookParam : null
  useEffect(() => {
    currentRef.current?.scrollIntoView?.({ block: 'center' })
  }, [currentId])

  const isSeries = series?.kind === 'series'
  const threadCount = threads?.length ?? 0
  useStatusBar({
    mode: 'SERIES',
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
      aria-pressed={filter === id}
      onClick={() => setFilter(id)}
      className={`text-xs px-1 transition-colors duration-fast ${
        filter === id ? 'text-accent' : 'text-ink-dim hover:text-accent'
      }`}
    >
      {label}
    </button>
  )

  return (
    <main className="max-w-shell mx-auto px-4 py-6 flex flex-col gap-10">
      <PathHeader segments={[{ label: 'series', to: '/' }, { label: series.name }]} />

      <header className="flex flex-col gap-3 border-b border-line pb-6">
        {/* Serif is reserved for book titles; a series name is one. */}
        <h1 className="font-serif text-3xl md:text-4xl text-ink leading-tight">{series.name}</h1>
        {isSeries && (
          <p className="text-ink-dim text-xs tabular-nums">
            {series.works.length} {series.works.length === 1 ? 'book' : 'books'} in this series
          </p>
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
        {series.works.map((work) => (
          <BookRow
            key={work.id}
            work={work}
            current={work.id === currentId}
            rowRef={work.id === currentId ? currentRef : undefined}
          />
        ))}
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
          {user && (
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
          defaultBookId={filter ?? currentId ?? ''}
          onClose={() => setShowModal(false)}
          onCreated={(thread) => navigate(`/series/${series.slug}/threads/${thread.id}`)}
        />
      )}
    </main>
  )
}

export default Series
