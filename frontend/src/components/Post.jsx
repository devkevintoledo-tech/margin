import { useState } from 'react'
import { useUpvotePost } from '../api/threads'
import useAuthStore from '../store/auth'
import PostComposer from './PostComposer'
import VoteControl from './VoteControl'

function formatDate(dateStr) {
  if (!dateStr) return ''
  const d = new Date(dateStr)
  return d.toLocaleDateString('en-US', { year: 'numeric', month: 'short', day: 'numeric' })
}

function Post({ post, threadId, depth = 0 }) {
  const { id, content, upvotes = 0, author, created_at, replies = [] } = post
  const [showReply, setShowReply] = useState(false)
  const user = useAuthStore((s) => s.user)
  const upvoteMutation = useUpvotePost()

  const handleUpvote = () => {
    if (user) upvoteMutation.mutate({ id, threadId })
  }

  return (
    <div className={depth > 0 ? 'border-l border-line pl-5 ml-3' : ''}>
      <div className="py-4">
        <div className="flex items-start gap-3">
          <VoteControl
            count={upvotes}
            onVote={handleUpvote}
            disabled={!user}
            pending={upvoteMutation.isPending}
          />

          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 mb-2">
              <span className="text-accent-ink text-xs font-semibold uppercase tracking-wider">{author}</span>
              <span className="text-ink-muted text-xs">{formatDate(created_at)}</span>
            </div>
            <p className="text-ink text-sm leading-relaxed whitespace-pre-wrap">{content}</p>

            {user && (
              <button
                onClick={() => setShowReply((v) => !v)}
                className="mt-3 text-xs text-ink-muted hover:text-ink-dim transition-colors duration-fast uppercase tracking-widest"
              >
                {showReply ? '↩ Cancel' : '↩ Reply'}
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

        {replies.length > 0 && (
          <div className="mt-3">
            {replies.map((reply) => (
              <Post key={reply.id} post={reply} threadId={threadId} depth={depth + 1} />
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

export default Post
