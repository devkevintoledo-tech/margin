import { useState } from 'react'
import { useCreateThread } from '../api/threads'
import { useCreateSeriesThread } from '../api/series'
import { errorMessage } from '../api/errors'

/**
 * Thread creation for series and genre rooms. In a series, pass `seriesSlug`
 * and the series' `books`: the thread posts to that room, and the optional
 * "about which book" tag is what the page's per-book filter reads, so it is
 * the spoiler control. Elsewhere `target` is the key the API expects — e.g.
 * `{ genre_slug }` — and is spread into the payload.
 *
 * The default labels are load-bearing: `e2e/thread.spec.js` clicks
 * "Start a Thread" and "Create Thread" by accessible name.
 */
function ThreadModal({
  target,
  seriesSlug,
  books = [],
  defaultBookId = '',
  onClose,
  onCreated,
  title = 'Start a Thread',
  submitLabel = 'Create Thread',
}) {
  const [threadTitle, setThreadTitle] = useState('')
  const [body, setBody] = useState('')
  const [bookId, setBookId] = useState(defaultBookId)
  const genericMutation = useCreateThread()
  const seriesMutation = useCreateSeriesThread(seriesSlug)
  const mutation = seriesSlug ? seriesMutation : genericMutation

  const handleSubmit = (e) => {
    e.preventDefault()
    if (!threadTitle.trim()) return
    const payload = seriesSlug
      ? { title: threadTitle.trim(), content: body.trim(), ...(bookId ? { work_id: bookId } : {}) }
      : { ...target, title: threadTitle.trim(), content: body.trim() }
    mutation.mutate(payload, { onSuccess: (data) => onCreated(data) })
  }

  return (
    <div className="fixed inset-0 bg-bg/90 flex items-center justify-center z-50 p-4">
      <div
        role="dialog"
        aria-modal="true"
        aria-label={title}
        className="panel w-full max-w-lg flex flex-col gap-5 p-6"
      >
        <div className="flex items-center justify-between">
          <h2 className="text-sm uppercase tracking-eyebrow text-ink">{title}</h2>
          <button onClick={onClose} aria-label="Close" className="text-ink-dim hover:text-danger">
            ✕
          </button>
        </div>

        <form onSubmit={handleSubmit} className="flex flex-col gap-3">
          <input
            type="text"
            value={threadTitle}
            onChange={(e) => setThreadTitle(e.target.value)}
            placeholder="Thread title"
            required
            className="input"
          />
          {books.length > 0 && (
            <select
              aria-label="About which book"
              value={bookId}
              onChange={(e) => setBookId(e.target.value)}
              className="input"
            >
              <option value="">all books</option>
              {books.map((b) => (
                <option key={b.id} value={b.id}>
                  {b.title}
                </option>
              ))}
            </select>
          )}
          <textarea
            value={body}
            onChange={(e) => setBody(e.target.value)}
            placeholder="Opening post (optional)"
            rows={4}
            className="input resize-none"
          />
          {mutation.isError && (
            <p className="text-danger text-xs">
              {errorMessage(mutation.error, 'Failed to create thread.')}
            </p>
          )}
          <div className="flex justify-end gap-2">
            <button type="button" onClick={onClose} className="btn-ghost">
              Cancel
            </button>
            <button
              type="submit"
              disabled={mutation.isPending || !threadTitle.trim()}
              className="btn-primary"
            >
              {mutation.isPending ? 'Creating...' : submitLabel}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

export default ThreadModal
