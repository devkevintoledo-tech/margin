import { useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useBook, useBookThreads } from '../api/books'
import { useCreateThread } from '../api/threads'
import { errorMessage } from '../api/errors'
import ShelfButton from '../components/ShelfButton'
import ThreadCard from '../components/ThreadCard'
import useAuthStore from '../store/auth'

function CreateThreadModal({ bookId, onClose }) {
  const [title, setTitle] = useState('')
  const [body, setBody] = useState('')
  const mutation = useCreateThread()
  const navigate = useNavigate()

  const handleSubmit = (e) => {
    e.preventDefault()
    if (!title.trim()) return
    mutation.mutate(
      { book_id: bookId, title: title.trim(), content: body.trim() },
      {
        onSuccess: (data) => {
          navigate(`/books/${bookId}/threads/${data.id}`)
        },
      }
    )
  }

  return (
    <div className="fixed inset-0 bg-black/80 flex items-center justify-center z-50 p-4">
      <div className="panel border-line-strong w-full max-w-lg flex flex-col gap-5 p-6">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-semibold uppercase tracking-eyebrow text-ink">Start a Thread</h2>
          <button onClick={onClose} aria-label="Close" className="text-ink-muted hover:text-ink text-lg">
            ✕
          </button>
        </div>
        <form onSubmit={handleSubmit} className="flex flex-col gap-3">
          <input
            type="text"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="Thread title"
            required
            className="input bg-raised"
          />
          <textarea
            value={body}
            onChange={(e) => setBody(e.target.value)}
            placeholder="Opening post (optional)"
            rows={4}
            className="input bg-raised resize-none"
          />
          {mutation.isError && (
            <p className="text-danger text-xs">{errorMessage(mutation.error, 'Failed to create thread.')}</p>
          )}
          <div className="flex justify-end gap-2">
            <button type="button" onClick={onClose} className="btn-ghost">
              Cancel
            </button>
            <button type="submit" disabled={mutation.isPending || !title.trim()} className="btn-primary">
              {mutation.isPending ? 'Creating...' : 'Create Thread'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

function Book() {
  const { id } = useParams()
  const [showModal, setShowModal] = useState(false)
  const user = useAuthStore((s) => s.user)

  const { data: book, isLoading: bookLoading, isError: bookError } = useBook(id)
  const { data: threads, isLoading: threadsLoading } = useBookThreads(id)

  if (bookLoading) {
    return (
      <main className="max-w-5xl mx-auto px-6 py-10">
        <div className="animate-pulse flex gap-8">
          <div className="w-44 aspect-[2/3] bg-surface shrink-0" />
          <div className="flex flex-col gap-3 flex-1">
            <div className="h-10 bg-surface w-2/3" />
            <div className="h-4 bg-surface w-1/3" />
            <div className="h-20 bg-surface w-full mt-4" />
          </div>
        </div>
      </main>
    )
  }

  if (bookError || !book) {
    return (
      <main className="max-w-5xl mx-auto px-6 py-10">
        <p className="text-danger">Failed to load book.</p>
      </main>
    )
  }

  const threadCount = threads?.length ?? 0

  return (
    <main className="max-w-5xl mx-auto px-6 py-10 flex flex-col gap-12">
      {/* Book hero — the cover is the visual anchor of the page (§13). */}
      <section className="flex flex-col sm:flex-row gap-8">
        <div className="shrink-0 w-44 sm:w-56">
          {book.cover_url ? (
            <img src={book.cover_url} alt={book.title} className="w-full border border-line" />
          ) : (
            <div className="w-full aspect-[2/3] bg-surface border border-line flex items-center justify-center text-ink-muted text-xs">
              No Cover
            </div>
          )}
        </div>

        <div className="flex flex-col gap-5 flex-1 min-w-0">
          <div className="flex flex-col gap-1">
            <h1 className="font-serif text-4xl md:text-5xl text-ink leading-tight">{book.title}</h1>
            {book.subtitle && <p className="font-serif italic text-ink-dim text-lg">{book.subtitle}</p>}
            <p className="text-ink-dim text-base uppercase tracking-widest mt-1">{book.author}</p>
          </div>

          {/* Metadata rail — dense, technical, no star rating (see docs/visual-identity.md). */}
          <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs uppercase tracking-wider text-ink-muted">
            {book.published_year && <span>{book.published_year}</span>}
            {book.publisher && <span>{book.publisher}</span>}
            {book.page_count && <span>{book.page_count} pp</span>}
            <span className="text-accent-ink">
              {threadCount} {threadCount === 1 ? 'discussion' : 'discussions'}
            </span>
          </div>

          {book.categories?.length > 0 && (
            <div className="flex flex-wrap gap-2">
              {book.categories.map((category) => (
                <span
                  key={category}
                  className="border border-line text-ink-dim text-xs px-2 py-1 uppercase tracking-wider"
                >
                  {category}
                </span>
              ))}
            </div>
          )}

          {book.description && (
            <p className="text-ink-dim text-sm leading-relaxed max-w-2xl">{book.description}</p>
          )}

          <ShelfButton bookId={id} currentStatus={book.shelf_status} />
        </div>
      </section>

      {/* Discussions */}
      <section className="flex flex-col gap-5">
        <div className="flex items-center justify-between border-b border-line pb-3">
          <div className="flex items-baseline gap-4">
            <span className="rule" />
            <h2 className="text-sm font-semibold uppercase tracking-eyebrow text-ink">Discussions</h2>
          </div>
          {user && (
            <button onClick={() => setShowModal(true)} className="btn-primary text-xs uppercase tracking-wider">
              Start a Thread
            </button>
          )}
        </div>

        {threadsLoading && (
          <div className="flex flex-col gap-2">
            {[1, 2, 3].map((i) => (
              <div key={i} className="h-16 border border-line bg-surface animate-pulse" />
            ))}
          </div>
        )}

        {!threadsLoading && threadCount === 0 && (
          <p className="text-ink-dim text-sm py-4">
            No discussions yet.{' '}
            {user ? (
              'Start the first one.'
            ) : (
              <a href="/login" className="text-accent-ink hover:underline">
                Log in
              </a>
            )}
          </p>
        )}

        {threadCount > 0 && (
          <div className="flex flex-col gap-2">
            {threads.map((thread) => (
              <ThreadCard key={thread.id} thread={{ ...thread, book_id: id }} />
            ))}
          </div>
        )}
      </section>

      {showModal && <CreateThreadModal bookId={id} onClose={() => setShowModal(false)} />}
    </main>
  )
}

export default Book
