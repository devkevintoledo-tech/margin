import { useParams, Link } from 'react-router-dom'
import { useThread } from '../api/threads'
import Post from '../components/Post'
import PostComposer from '../components/PostComposer'

function Thread() {
  const { id, threadId } = useParams()
  const resolvedId = threadId || id
  const { data: thread, isLoading, isError } = useThread(resolvedId)

  if (isLoading) {
    return (
      <main className="max-w-3xl mx-auto px-6 py-10">
        <div className="animate-pulse flex flex-col gap-4">
          <div className="h-10 bg-surface w-2/3" />
          <div className="h-4 bg-surface w-1/4" />
          {[1, 2, 3].map((i) => (
            <div key={i} className="h-24 border border-line bg-surface" />
          ))}
        </div>
      </main>
    )
  }

  if (isError || !thread) {
    return (
      <main className="max-w-3xl mx-auto px-6 py-10">
        <p className="text-danger">Failed to load thread.</p>
      </main>
    )
  }

  const posts = thread.posts || []
  const topLevelPosts = posts.filter((p) => !p.parent_id)

  return (
    <main className="max-w-3xl mx-auto px-6 py-10 flex flex-col gap-8">
      {/* Header */}
      <div className="border-b border-line pb-5 flex flex-col gap-3">
        {thread.book && (
          <Link
            to={`/books/${thread.book.id}`}
            className="text-xs text-ink-muted hover:text-accent-ink transition-colors duration-fast uppercase tracking-wider"
          >
            ← {thread.book.title}
          </Link>
        )}
        {thread.genre && (
          <Link
            to={`/genres/${thread.genre.slug}`}
            className="text-xs text-ink-muted hover:text-accent-ink transition-colors duration-fast uppercase tracking-wider"
          >
            ← {thread.genre.name}
          </Link>
        )}
        <h1 className="font-serif text-3xl md:text-4xl text-ink leading-tight">{thread.title}</h1>
        <div className="flex items-center gap-4 text-ink-muted text-xs uppercase tracking-wider">
          {thread.author && <span>by {thread.author}</span>}
          <span className="text-accent-ink">{thread.score ?? 0} points</span>
          <span>{posts.length} posts</span>
        </div>
      </div>

      {/* Posts */}
      <div className="flex flex-col divide-y divide-line">
        {topLevelPosts.length === 0 && (
          <p className="text-ink-dim text-sm py-4">No posts yet. Be the first to reply.</p>
        )}
        {topLevelPosts.map((post) => (
          <Post key={post.id} post={post} threadId={resolvedId} depth={0} />
        ))}
      </div>

      {/* New post */}
      <div className="border-t border-line pt-6 flex flex-col gap-3">
        <h3 className="text-xs font-semibold uppercase tracking-eyebrow text-ink-dim">Add a Reply</h3>
        <PostComposer threadId={resolvedId} placeholder="Join the discussion..." />
      </div>
    </main>
  )
}

export default Thread
