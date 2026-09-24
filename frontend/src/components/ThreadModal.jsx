import { useState } from 'react'
import { useCreateThread } from '../api/threads'
import { errorMessage } from '../api/errors'

/**
 * Thread creation for both works and genres. `target` is whichever key the API
 * expects — `{ work_id }` or `{ genre_slug }` — and is spread into the payload.
 *
 * The default labels are load-bearing: `e2e/thread.spec.js` clicks
 * "Start a Thread" and "Create Thread" by accessible name.
 */
function ThreadModal({
  target,
  onClose,
  onCreated,
  title = 'Start a Thread',
  submitLabel = 'Create Thread',
}) {
  const [threadTitle, setThreadTitle] = useState('')
  const [body, setBody] = useState('')
  const mutation = useCreateThread()

  const handleSubmit = (e) => {
    e.preventDefault()
    if (!threadTitle.trim()) return
    mutation.mutate(
      { ...target, title: threadTitle.trim(), content: body.trim() },
      { onSuccess: (data) => onCreated(data) },
    )
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
