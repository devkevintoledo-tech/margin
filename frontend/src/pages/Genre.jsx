import { useState } from 'react'
import { useParams, useNavigate, Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import client from '../api/client'
import { useVoteThread } from '../api/threads'
import BookCard from '../components/BookCard'
import PathHeader from '../components/PathHeader'
import DataTable from '../components/DataTable'
import ThreadModal from '../components/ThreadModal'
import VoteControl from '../components/VoteControl'
import { relativeTime } from '../components/Post'
import { useStatusBar } from '../store/status'
import useAuthStore from '../store/auth'

function Genre() {
  const { slug: genreSlug } = useParams()
  const navigate = useNavigate()
  const user = useAuthStore((s) => s.user)
  const [showModal, setShowModal] = useState(false)
  const voteMutation = useVoteThread()

  const { data: genre, isLoading, isError } = useQuery({
    queryKey: ['genres', genreSlug],
    queryFn: () => client.get(`/genres/${genreSlug}`).then((r) => r.data),
    enabled: !!genreSlug,
  })

  const { data: books } = useQuery({
    queryKey: ['genres', genreSlug, 'books'],
    queryFn: () => client.get(`/genres/${genreSlug}/books`).then((r) => r.data),
    enabled: !!genreSlug,
  })

  const { data: threads } = useQuery({
    queryKey: ['genres', genreSlug, 'threads'],
    queryFn: () => client.get(`/genres/${genreSlug}/threads`).then((r) => r.data),
    enabled: !!genreSlug,
  })

  const threadCount = threads?.length ?? 0

  useStatusBar({
    mode: 'GENRE',
    path: `~/genres/${genreSlug}`,
    facts: [`${threadCount} ${threadCount === 1 ? 'thread' : 'threads'}`],
  })

  if (isLoading) {
    return (
      <main className="max-w-shell mx-auto px-4 py-8">
        <div className="animate-pulse flex flex-col gap-6">
          <div className="h-10 bg-panel w-1/3" />
          <div className="h-4 bg-panel w-2/3" />
        </div>
      </main>
    )
  }

  if (isError || !genre) {
    return (
      <main className="max-w-shell mx-auto px-4 py-8">
        <p className="alert-danger">Genre not found.</p>
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
          onVote={(value) => user && voteMutation.mutate({ id: row.id, value, genreSlug })}
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
          to={`/genres/${genreSlug}/threads/${row.id}`}
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
      <PathHeader segments={[{ label: 'genres', to: '/' }, { label: genre.name }]} />

      <header className="border-b border-line pb-4 flex flex-col gap-2">
        <h1 className="text-display-sm text-ink uppercase">{genre.name}</h1>
        {genre.description && (
          <p className="text-ink-dim text-sm max-w-prose leading-relaxed">{genre.description}</p>
        )}
      </header>

      {books && books.length > 0 && (
        <section className="flex flex-col gap-4">
          <h2 className="text-xs uppercase tracking-eyebrow text-ink-dim border-b border-line pb-2">
            Notable books
          </h2>
          <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 gap-5">
            {books.map((book) => (
              <BookCard key={book.id} book={book} />
            ))}
          </div>
        </section>
      )}

      <section className="panel p-5 pt-6">
        <h2 className="panel-title">Discussions</h2>

        <div className="flex justify-end mb-3">
          {user && (
            <button onClick={() => setShowModal(true)} className="btn-secondary text-xs">
              Start a Discussion
            </button>
          )}
        </div>

        <DataTable
          columns={columns}
          rows={threads || []}
          caption={`Discussions in ${genre.name}`}
          emptyMessage="No discussions yet."
        />
      </section>

      {showModal && (
        <ThreadModal
          target={{ genre_slug: genreSlug }}
          onClose={() => setShowModal(false)}
          onCreated={(thread) => navigate(`/genres/${genreSlug}/threads/${thread.id}`)}
          title="Start a Discussion"
          submitLabel="Create"
        />
      )}
    </main>
  )
}

export default Genre
