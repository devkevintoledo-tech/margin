import { useState } from 'react'
import { useVotePost } from '../api/threads'
import useAuthStore from '../store/auth'
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

function Post({ post, threadId, depth = 0 }) {
  const { id, content, score = 0, my_vote = 0, author, created_at, replies = [] } = post
  const [showReply, setShowReply] = useState(false)
  const user = useAuthStore((s) => s.user)
  const voteMutation = useVotePost()

  const handleVote = (value) => {
    if (user) voteMutation.mutate({ id, value, threadId })
  }

  return (
    <div className="py-3">
      <div className="flex items-start gap-3">
        <VoteControl
          score={score}
          myVote={my_vote}
          onVote={handleVote}
          disabled={!user}
          pending={voteMutation.isPending}
        />

        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-1.5 text-xs">
            <span className="text-user font-medium">{author}</span>
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
          </div>

          <p className="text-ink text-sm leading-relaxed whitespace-pre-wrap max-w-prose">
            {content}
          </p>

          {user && (
            <button
              onClick={() => setShowReply((v) => !v)}
              className="mt-2 text-xs text-ink-dim hover:text-accent transition-colors duration-fast"
            >
              {showReply ? 'cancel' : 'reply'}
            </button>
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
                <Post post={reply} threadId={threadId} depth={depth + 1} />
              </li>
            )
          })}
        </ul>
      )}
    </div>
  )
}

export default Post
