import { useState } from 'react'
import { useDeletePost, useEditPost, useVotePost } from '../api/threads'
import { errorMessage } from '../api/errors'
import useAuthStore from '../store/auth'
import ConfirmRemove from './ConfirmRemove'
import PostComposer from './PostComposer'
import VoteControl from './VoteControl'
import DiagnosticFloat from './DiagnosticFloat'

/**
 * Terminal-style age: `40m`, `2h`, `5d`, `3mo`. The absolute timestamp is not
 * lost — it moves into the diagnostic float on hover/focus.
 */
export function relativeTime(dateStr, now = new Date()) {
  if (!dateStr) return ''
  const then = new Date(dateStr)
  const seconds = Math.max(0, Math.floor((now - then) / 1000))
  if (seconds < 60) return 'now'
  const minutes = Math.floor(seconds / 60)
  if (minutes < 60) return `${minutes}m`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours}h`
  const days = Math.floor(hours / 24)
  if (days < 30) return `${days}d`
  const months = Math.floor(days / 30)
  if (months < 12) return `${months}mo`
  return `${Math.floor(months / 12)}y`
}

function absoluteTime(dateStr) {
  if (!dateStr) return ''
  return new Date(dateStr).toLocaleString('en-GB', {
    day: 'numeric',
    month: 'long',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function Post({ post, threadId, depth = 0, threadDeleted = false }) {
  const {
    id, content, score = 0, my_vote = 0, author, created_at, edited_at, deleted = false,
    replies = [],
  } = post
  const [showReply, setShowReply] = useState(false)
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(content)
  const [confirming, setConfirming] = useState(false)
  const user = useAuthStore((s) => s.user)
  const voteMutation = useVotePost()
  const editMutation = useEditPost()
  const deleteMutation = useDeletePost()
  // Tombstones carry user_id null, so they never match.
  const isOwner = !!user && !deleted && user.id === post.user_id

  const handleVote = (value) => {
    if (user && !deleted) voteMutation.mutate({ id, value, threadId })
  }

  const startEdit = () => {
    setDraft(content)
    editMutation.reset()
    setEditing(true)
  }

  const saveEdit = (e) => {
    e.preventDefault()
    if (!draft.trim()) return
    editMutation.mutate({ id, content: draft.trim() }, { onSuccess: () => setEditing(false) })
  }

  return (
    <div className="py-3">
      <div className="flex items-start gap-3">
        <VoteControl
          score={score}
          myVote={my_vote}
          onVote={handleVote}
          disabled={!user || deleted}
          pending={voteMutation.isPending}
        />

        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-1.5 text-xs">
            {deleted ? (
              <span className="text-ink-dim">[deleted]</span>
            ) : (
              <span className="text-user font-medium">{author}</span>
            )}
            <span aria-hidden="true" className="text-ink-faint">·</span>
            <span className="text-ink-dim">
              <DiagnosticFloat
                severity="hint"
                message={absoluteTime(created_at)}
                source={`post/${id}`}
              >
                {relativeTime(created_at)}
              </DiagnosticFloat>
            </span>
            {edited_at && !deleted && (
              <>
                <span aria-hidden="true" className="text-ink-faint">·</span>
                <span className="text-ink-dim">
                  <DiagnosticFloat
                    severity="hint"
                    message={`edited ${absoluteTime(edited_at)}`}
                    source={`post/${id}`}
                  >
                    edited
                  </DiagnosticFloat>
                </span>
              </>
            )}
          </div>

          {deleted ? (
            <p className="text-ink-dim text-sm">[deleted]</p>
          ) : editing ? (
            <form onSubmit={saveEdit} className="flex flex-col gap-2 max-w-prose">
              <textarea
                aria-label="Edit post"
                className="input min-h-24"
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
              />
              {editMutation.isError && (
                <p className="alert-danger">{errorMessage(editMutation.error)}</p>
              )}
              <div className="flex gap-2">
                <button
                  type="submit"
                  className="btn-primary"
                  disabled={!draft.trim() || editMutation.isPending}
                >
                  save
                </button>
                <button type="button" className="btn-ghost" onClick={() => setEditing(false)}>
                  cancel
                </button>
              </div>
            </form>
          ) : (
            <p className="text-ink text-sm leading-relaxed whitespace-pre-wrap max-w-prose">
              {content}
            </p>
          )}

          {!deleted && !editing && (
            <div className="mt-2 flex items-center gap-3 text-xs">
              {confirming ? (
                <ConfirmRemove
                  noun="post"
                  pending={deleteMutation.isPending}
                  onCancel={() => setConfirming(false)}
                  onConfirm={() =>
                    deleteMutation.mutate(
                      { id, threadId },
                      { onSuccess: () => setConfirming(false) },
                    )
                  }
                />
              ) : (
                <>
                  {/* A deleted thread refuses replies (409), so do not offer one. */}
                  {user && !threadDeleted && (
                    <button
                      onClick={() => setShowReply((v) => !v)}
                      className="text-ink-dim hover:text-accent transition-colors duration-fast"
                    >
                      {showReply ? 'cancel' : 'reply'}
                    </button>
                  )}
                  {isOwner && (
                    <>
                      <button
                        onClick={startEdit}
                        className="text-ink-dim hover:text-accent transition-colors duration-fast"
                      >
                        edit
                      </button>
                      <button
                        onClick={() => setConfirming(true)}
                        className="text-ink-dim hover:text-accent transition-colors duration-fast"
                      >
                        delete
                      </button>
                    </>
                  )}
                </>
              )}
            </div>
          )}
          {deleteMutation.isError && (
            <p className="alert-danger mt-2">{errorMessage(deleteMutation.error)}</p>
          )}

          {showReply && (
            <div className="mt-3">
              <PostComposer
                threadId={threadId}
                parentId={id}
                placeholder="Write a reply..."
                onSuccess={() => setShowReply(false)}
              />
            </div>
          )}
        </div>
      </div>

      {/* Replies. The elbow is a real glyph — it aligns because the whole UI is
          monospaced — but the vertical rail is a CSS border, since a border
          stretches to content height and a repeated character does not.
          MARGIN is capped at two levels, so this cannot nest further. */}
      {replies.length > 0 && (
        <ul className="mt-2 ml-8 border-l border-line-strong list-none">
          {replies.map((reply, i) => {
            const isLast = i === replies.length - 1
            return (
              <li
                key={reply.id}
                // The rail is one continuous border on the <ul>, so the last
                // child paints a bg-coloured stripe over its remainder — that is
                // what makes `└─` actually terminate the branch.
                className={`relative pl-6 ${
                  isLast
                    ? 'after:absolute after:left-[-1px] after:top-5 after:bottom-0 after:w-px after:bg-bg after:content-[""]'
                    : ''
                }`}
              >
                <span
                  data-testid="tree-elbow"
                  aria-hidden="true"
                  className="absolute left-0 top-4 text-ink-faint select-none leading-none"
                >
                  {isLast ? '└─' : '├─'}
                </span>
                <Post post={reply} threadId={threadId} depth={depth + 1} threadDeleted={threadDeleted} />
              </li>
            )
          })}
        </ul>
      )}
    </div>
  )
}

export default Post
