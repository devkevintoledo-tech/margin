import { useState } from 'react'
import { useParams, useNavigate, Link } from 'react-router-dom'
import { useWork, useWorkThreads } from '../api/works'
import { useVoteThread } from '../api/threads'
import ShelfButton from '../components/ShelfButton'
import PathHeader from '../components/PathHeader'
import DataTable from '../components/DataTable'
import ThreadModal from '../components/ThreadModal'
import VoteControl from '../components/VoteControl'
import { relativeTime } from '../components/Post'
import { useStatusBar } from '../store/status'
import { slug } from '../lib/slug'
import useAuthStore from '../store/auth'

function Work() {
  const { id } = useParams()
  const navigate = useNavigate()
  const [showModal, setShowModal] = useState(false)
  // Same fallback as WorkCard: a dead cover URL shows the placeholder, not a
  // broken-image glyph.
  const [coverFailed, setCoverFailed] = useState(false)
  const user = useAuthStore((s) => s.user)
  const voteMutation = useVoteThread()

  const { data: work, isLoading: workLoading, isError: workError } = useWork(id)
  const { data: threads, isLoading: threadsLoading } = useWorkThreads(id)

  const threadCount = threads?.length ?? 0

  useStatusBar({
    mode: 'WORK',
    path: work ? `~/works/${slug(work.title)}` : '~/works',
    facts: [`${threadCount} ${threadCount === 1 ? 'thread' : 'threads'}`],
  })

  if (workLoading) {
    return (
      <main className="max-w-shell mx-auto px-4 py-8">
        <div className="animate-pulse flex gap-8">
          <div className="w-44 aspect-[2/3] bg-panel shrink-0" />
          <div className="flex flex-col gap-3 flex-1">
            <div className="h-10 bg-panel w-2/3" />
            <div className="h-4 bg-panel w-1/3" />
            <div className="h-20 bg-panel w-full mt-4" />
          </div>
        </div>
      </main>
    )
  }

  if (workError || !work) {
    return (
      <main className="max-w-shell mx-auto px-4 py-8">
        <p className="alert-danger">Failed to load work.</p>
      </main>
    )
  }

  const columns = [
    {
      key: 'score',
      label: 'Score',
      align: 'right',
      width: 8,
      render: (row) => (
        <VoteControl
          variant="row"
          score={row.score ?? 0}
          myVote={row.my_vote ?? 0}
          onVote={(value) => user && voteMutation.mutate({ id: row.id, value, workId: id })}
          disabled={!user}
          pending={voteMutation.isPending}
        />
      ),
    },
    {
      key: 'title',
      label: 'Thread',
      render: (row) => (
        <Link
          to={`/works/${id}/threads/${row.id}`}
          className="text-ink hover:text-accent transition-colors duration-fast"
        >
          {row.title}
        </Link>
      ),
    },
    {
      key: 'author',
      label: 'By',
      width: 16,
      render: (row) => <span className="text-user">{row.author}</span>,
    },
    {
      key: 'post_count',
      label: 'Repl',
      align: 'right',
      width: 6,
      render: (row) => <span className="text-ink-dim tabular-nums">{row.post_count ?? 0}</span>,
    },
    {
      key: 'created_at',
      label: 'Age',
      align: 'right',
      width: 6,
      render: (row) => <span className="text-ink-dim tabular-nums">{relativeTime(row.created_at)}</span>,
    },
  ]

  return (
    <main className="max-w-shell mx-auto px-4 py-6 flex flex-col gap-10">
      <PathHeader
        segments={[{ label: 'works', to: '/' }, { label: work.title }]}
      />

      {/* The cover is the only saturated thing on the page and stays that way —
          large, full colour, never dimmed. */}
      <section className="flex flex-col sm:flex-row gap-8">
        <div className="shrink-0 w-44 sm:w-56">
          {work.cover_url && !coverFailed ? (
            <img
              src={work.cover_url}
              alt={work.title}
              onError={() => setCoverFailed(true)}
              className="w-full border border-line"
            />
          ) : (
            <div className="w-full aspect-[2/3] bg-panel border border-line flex items-center justify-center text-ink-dim text-xs">
              No Cover
            </div>
          )}
        </div>

        <div className="flex flex-col gap-4 flex-1 min-w-0">
          <div className="flex flex-col gap-1">
            {/* Serif is reserved for works — this is the one place it appears. */}
            <h1 className="font-serif text-3xl md:text-4xl text-ink leading-tight">{work.title}</h1>
            {work.subtitle && <p className="text-ink-dim text-sm">{work.subtitle}</p>}
            <p className="text-user text-sm lowercase tracking-eyebrow mt-1">{work.author}</p>
          </div>

          {/* Publisher and page count were edition facts; they left with the
              edition. What a work can honestly state is when it first appeared
              and how many printings it has. */}
          <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-0.5 text-xs max-w-sm">
            {work.first_publish_year && (
              <>
                <dt className="text-ink-dim">first published</dt>
                <dd className="text-ink tabular-nums">{work.first_publish_year}</dd>
              </>
            )}
            {work.edition_count > 1 && (
              <>
                <dt className="text-ink-dim">editions</dt>
                <dd className="text-ink tabular-nums">{work.edition_count}</dd>
              </>
            )}
            <dt className="text-ink-dim">threads</dt>
            <dd className="text-path tabular-nums">{threadCount}</dd>
          </dl>

          {work.description && (
            <p className="text-ink-dim text-sm leading-relaxed max-w-prose">{work.description}</p>
          )}

          <ShelfButton workId={id} currentStatus={work.shelf_status} />
        </div>
      </section>

      <section className="panel p-5 pt-6">
        <h2 className="panel-title">Discussions</h2>

        <div className="flex justify-end mb-3">
          {user && (
            <button onClick={() => setShowModal(true)} className="btn-secondary text-xs">
              Start a Thread
            </button>
          )}
        </div>

        {threadsLoading ? (
          <div className="flex flex-col gap-2">
            {[1, 2, 3].map((i) => (
              <div key={i} className="h-8 border border-line bg-panel animate-pulse" />
            ))}
          </div>
        ) : (
          <DataTable
            columns={columns}
            rows={threads || []}
            caption={`Discussions about ${work.title}`}
            emptyMessage={user ? 'No discussions yet. Start the first one.' : 'No discussions yet.'}
          />
        )}
      </section>

      {showModal && (
        <ThreadModal
          target={{ work_id: id }}
          onClose={() => setShowModal(false)}
          onCreated={(thread) => navigate(`/works/${id}/threads/${thread.id}`)}
        />
      )}
    </main>
  )
}

export default Work
