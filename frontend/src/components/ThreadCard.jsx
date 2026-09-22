import { Link } from 'react-router-dom'
import { useUpvoteThread } from '../api/threads'
import useAuthStore from '../store/auth'
import VoteControl from './VoteControl'

function ThreadCard({ thread }) {
  const { id, title, upvotes = 0, post_count = 0, book_id, genre_slug, author } = thread
  const upvoteMutation = useUpvoteThread()
  const user = useAuthStore((s) => s.user)

  const href = book_id
    ? `/books/${book_id}/threads/${id}`
    : genre_slug
    ? `/genres/${genre_slug}/threads/${id}`
    : `/threads/${id}`

  const handleUpvote = (e) => {
    e.preventDefault()
    if (user) upvoteMutation.mutate({ id })
  }

  return (
    <div className="group flex border border-line hover:border-line-strong bg-bg hover:bg-surface transition-colors duration-fast">
      <VoteControl
        variant="rail"
        count={upvotes}
        onVote={handleUpvote}
        disabled={!user}
        pending={upvoteMutation.isPending}
      />
      <div className="flex flex-col gap-1.5 min-w-0 px-4 py-3.5">
        <Link
          to={href}
          className="font-serif text-ink hover:text-accent-ink transition-colors duration-fast text-base leading-snug"
        >
          {title}
        </Link>
        <div className="flex items-center gap-3 text-ink-muted text-xs">
          {author && <span className="uppercase tracking-wider">{author}</span>}
          {author && <span className="text-line-strong">·</span>}
          <span>
            {post_count} {post_count === 1 ? 'reply' : 'replies'}
          </span>
        </div>
      </div>
    </div>
  )
}

export default ThreadCard
