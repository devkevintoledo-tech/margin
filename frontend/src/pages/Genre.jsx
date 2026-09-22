import { useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import client from '../api/client'
import { useCreateThread } from '../api/threads'
import { errorMessage } from '../api/errors'
import BookCard from '../components/BookCard'
import ThreadCard from '../components/ThreadCard'
import useAuthStore from '../store/auth'

function Genre() {
  const { slug } = useParams()
  const navigate = useNavigate()
  const user = useAuthStore((s) => s.user)
  const [showModal, setShowModal] = useState(false)
  const [threadTitle, setThreadTitle] = useState('')
  const [threadBody, setThreadBody] = useState('')
  const createThread = useCreateThread()

  const { data: genre, isLoading, isError } = useQuery({
    queryKey: ['genres', slug],
    queryFn: () => client.get(`/genres/${slug}`).then((r) => r.data),
    enabled: !!slug,
  })

  const { data: books } = useQuery({
    queryKey: ['genres', slug, 'books'],
    queryFn: () => client.get(`/genres/${slug}/books`).then((r) => r.data),
    enabled: !!slug,
  })

  const { data: threads } = useQuery({
    queryKey: ['genres', slug, 'threads'],
    queryFn: () => client.get(`/genres/${slug}/threads`).then((r) => r.data),
    enabled: !!slug,
  })

  const handleCreateThread = (e) => {
    e.preventDefault()
    if (!threadTitle.trim()) return
    createThread.mutate(
      { genre_slug: slug, title: threadTitle.trim(), content: threadBody.trim() },
      {
        onSuccess: (data) => {
          navigate(`/genres/${slug}/threads/${data.id}`)
        },
      }
    )
  }

  if (isLoading) {
    return (
      <main className="max-w-5xl mx-auto px-6 py-10">
        <div className="animate-pulse flex flex-col gap-6">
          <div className="h-12 bg-surface w-1/3" />
          <div className="h-4 bg-surface w-2/3" />
        </div>
      </main>
    )
  }

  if (isError || !genre) {
    return (
      <main className="max-w-5xl mx-auto px-6 py-10">
        <p className="text-danger">Genre not found.</p>
      </main>
    )
  }

  return (
    <main className="max-w-5xl mx-auto px-6 py-10 flex flex-col gap-14">
      {/* Header */}
      <div className="border-b border-line pb-6 flex flex-col gap-3">
        <p className="eyebrow">Genre</p>
        <h1 className="text-display-sm md:text-display font-bold uppercase text-ink">{genre.name}</h1>
        {genre.description && <p className="text-ink-dim max-w-2xl leading-relaxed">{genre.description}</p>}
      </div>

      {/* Books */}
      {books && books.length > 0 && (
        <section className="flex flex-col gap-5">
          <div className="flex items-baseline gap-4 border-b border-line pb-3">
            <span className="rule" />
            <h2 className="text-sm font-semibold uppercase tracking-eyebrow text-ink">Notable Books</h2>
          </div>
          <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 gap-5">
            {books.map((book) => (
              <BookCard key={book.id} book={book} />
            ))}
          </div>
        </section>
      )}

      {/* Threads */}
      <section className="flex flex-col gap-5">
        <div className="flex items-center justify-between border-b border-line pb-3">
          <div className="flex items-baseline gap-4">
            <span className="rule" />
            <h2 className="text-sm font-semibold uppercase tracking-eyebrow text-ink">Discussions</h2>
          </div>
          {user && (
            <button onClick={() => setShowModal(true)} className="btn-primary text-xs uppercase tracking-wider">
              Start a Discussion
            </button>
          )}
        </div>

        {!threads || threads.length === 0 ? (
          <p className="text-ink-dim text-sm py-4">No discussions yet.</p>
        ) : (
          <div className="flex flex-col gap-2">
            {threads.map((thread) => (
              <ThreadCard key={thread.id} thread={{ ...thread, genre_slug: slug }} />
            ))}
          </div>
        )}
      </section>

      {/* Create Thread Modal */}
      {showModal && (
        <div className="fixed inset-0 bg-black/80 flex items-center justify-center z-50 p-4">
          <div className="panel border-line-strong w-full max-w-lg p-6 flex flex-col gap-5">
            <div className="flex items-center justify-between">
              <h2 className="text-sm font-semibold uppercase tracking-eyebrow text-ink">Start a Discussion</h2>
              <button
                onClick={() => setShowModal(false)}
                aria-label="Close"
                className="text-ink-muted hover:text-ink text-lg"
              >
                ✕
              </button>
            </div>
            <form onSubmit={handleCreateThread} className="flex flex-col gap-3">
              <input
                type="text"
                value={threadTitle}
                onChange={(e) => setThreadTitle(e.target.value)}
                placeholder="Discussion title"
                required
                className="input bg-raised"
              />
              <textarea
                value={threadBody}
                onChange={(e) => setThreadBody(e.target.value)}
                placeholder="Opening post (optional)"
                rows={4}
                className="input bg-raised resize-none"
              />
              {createThread.isError && (
                <p className="text-danger text-xs">{errorMessage(createThread.error, 'Failed to create.')}</p>
              )}
              <div className="flex justify-end gap-2">
                <button type="button" onClick={() => setShowModal(false)} className="btn-ghost">
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={createThread.isPending || !threadTitle.trim()}
                  className="btn-primary"
                >
                  {createThread.isPending ? 'Creating...' : 'Create'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </main>
  )
}

export default Genre
