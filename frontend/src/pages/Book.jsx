import { useState } from 'react'
import { useParams, useNavigate, Link } from 'react-router-dom'
import { useBook, useBookThreads } from '../api/books'
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

function Book() {
  const { id } = useParams()
  const navigate = useNavigate()
  const [showModal, setShowModal] = useState(false)
  const user = useAuthStore((s) => s.user)
  const voteMutation = useVoteThread()

  const { data: book, isLoading: bookLoading, isError: bookError } = useBook(id)
  const { data: threads, isLoading: threadsLoading } = useBookThreads(id)

  const threadCount = threads?.length ?? 0

  useStatusBar({
    mode: 'BOOK',
    path: book ? `~/books/${slug(book.title)}` : '~/books',
    facts: [`${threadCount} ${threadCount === 1 ? 'thread' : 'threads'}`],
  })

  if (bookLoading) {
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

  if (bookError || !book) {
    return (
      <main className="max-w-shell mx-auto px-4 py-8">
        <p className="alert-danger">Failed to load book.</p>
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
          onVote={(value) => user && voteMutation.mutate({ id: row.id, value, bookId: id })}
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
          to={`/books/${id}/threads/${row.id}`}
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
        segments={[{ label: 'books', to: '/' }, { label: book.title }]}
      />

      {/* The cover is the only saturated thing on the page and stays that way —
          large, full colour, never dimmed. */}
      <section className="flex flex-col sm:flex-row gap-8">
        <div className="shrink-0 w-44 sm:w-56">
          {book.cover_url ? (
            <img src={book.cover_url} alt={book.title} className="w-full border border-line" />
          ) : (
            <div className="w-full aspect-[2/3] bg-panel border border-line flex items-center justify-center text-ink-dim text-xs">
              No Cover
            </div>
          )}
        </div>

        <div className="flex flex-col gap-4 flex-1 min-w-0">
          <div className="flex flex-col gap-1">
            {/* Serif is reserved for works — this is the one place it appears. */}
            <h1 className="font-serif text-3xl md:text-4xl text-ink leading-tight">{book.title}</h1>
            {book.subtitle && <p className="text-ink-dim text-sm">{book.subtitle}</p>}
            <p className="text-user text-sm lowercase tracking-eyebrow mt-1">{book.author}</p>
          </div>

          <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-0.5 text-xs max-w-sm">
            {book.published_year && (
              <>
                <dt className="text-ink-dim">year</dt>
                <dd className="text-ink tabular-nums">{book.published_year}</dd>
              </>
            )}
            {book.publisher && (
              <>
                <dt className="text-ink-dim">publisher</dt>
                <dd className="text-ink truncate">{book.publisher}</dd>
              </>
            )}
            {book.page_count && (
              <>
                <dt className="text-ink-dim">pages</dt>
                <dd className="text-ink tabular-nums">{book.page_count}</dd>
              </>
            )}
            <dt className="text-ink-dim">threads</dt>
            <dd className="text-path tabular-nums">{threadCount}</dd>
          </dl>

          {book.categories?.length > 0 && (
            <div className="flex flex-wrap gap-x-3 gap-y-1 text-xs">
              {book.categories.map((category) => (
                <span key={category} className="text-ink-dim">
                  <span aria-hidden="true" className="text-ink-faint">[</span>
                  {category.toLowerCase()}
                  <span aria-hidden="true" className="text-ink-faint">]</span>
                </span>
              ))}
            </div>
          )}

          {book.description && (
            <p className="text-ink-dim text-sm leading-relaxed max-w-prose">{book.description}</p>
          )}

          <ShelfButton bookId={id} currentStatus={book.shelf_status} />
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
            caption={`Discussions about ${book.title}`}
            emptyMessage={user ? 'No discussions yet. Start the first one.' : 'No discussions yet.'}
          />
        )}
      </section>

      {showModal && (
        <ThreadModal
          target={{ book_id: id }}
          onClose={() => setShowModal(false)}
          onCreated={(thread) => navigate(`/books/${id}/threads/${thread.id}`)}
        />
      )}
    </main>
  )
}

export default Book
