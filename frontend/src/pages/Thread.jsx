import { useParams } from 'react-router-dom'
import { useThread } from '../api/threads'
import Post from '../components/Post'
import PostComposer from '../components/PostComposer'
import PathHeader from '../components/PathHeader'
import { useStatusBar } from '../store/status'
import { slug } from '../lib/slug'

function countPosts(posts) {
  return posts.reduce((n, p) => n + 1 + countPosts(p.replies || []), 0)
}

function Thread() {
  const { id, threadId } = useParams()
  const resolvedId = threadId || id
  const { data: thread, isLoading, isError } = useThread(resolvedId)

  const posts = thread?.posts || []
  const anchor = thread?.series?.name || thread?.genre?.name || ''

  // `posts` arrives as a tree — top-level posts carry their own `replies` — so
  // its length is the number of branches, not the number of posts.
  const totalPosts = countPosts(posts)

  useStatusBar({
    mode: 'THREAD',
    path: anchor ? `~/${slug(anchor)}/threads/${resolvedId}` : `~/threads/${resolvedId}`,
    facts: [`${totalPosts} ${totalPosts === 1 ? 'post' : 'posts'}`],
  })

  if (isLoading) {
    return (
      <main className="max-w-prose mx-auto px-4 py-8">
        <div className="animate-pulse flex flex-col gap-4">
          <div className="h-8 bg-panel w-2/3" />
          <div className="h-4 bg-panel w-1/4" />
          {[1, 2, 3].map((i) => (
            <div key={i} className="h-24 border border-line bg-panel" />
          ))}
        </div>
      </main>
    )
  }

  if (isError || !thread) {
    return (
      <main className="max-w-prose mx-auto px-4 py-8">
        <p className="alert-danger">Failed to load thread.</p>
      </main>
    )
  }

  const topLevelPosts = posts.filter((p) => !p.parent_id)

  const segments = []
  if (thread.series) {
    segments.push({ label: 'series', to: '/' })
    segments.push({ label: thread.series.name, to: `/series/${thread.series.slug}` })
  } else if (thread.genre) {
    segments.push({ label: 'genres', to: '/' })
    segments.push({ label: thread.genre.name, to: `/genres/${thread.genre.slug}` })
  }
  // The title, not the id: a path segment should say where you are, and a
  // truncated UUID says nothing.
  segments.push({ label: thread.title })

  return (
    <main className="max-w-shell mx-auto px-4 py-6 flex flex-col gap-6">
      <PathHeader segments={segments} />

      <header className="border-b border-line pb-4 flex flex-col gap-2">
        {/* Serif is reserved for BOOK titles. A thread is structure, so it is mono. */}
        <h1 className="text-xl md:text-2xl text-ink leading-snug font-medium max-w-prose">
          {thread.title}
        </h1>
        <div className="flex items-center gap-3 text-xs">
          {thread.author && <span className="text-user">{thread.author}</span>}
          <span aria-hidden="true" className="text-ink-faint">·</span>
          <span className={thread.score > 0 ? 'text-ok' : thread.score < 0 ? 'text-danger' : 'text-ink-dim'}>
            {thread.score > 0 ? `+${thread.score}` : String(thread.score ?? 0)} points
          </span>
          <span aria-hidden="true" className="text-ink-faint">·</span>
          <span className="text-ink-dim">
            {totalPosts} {totalPosts === 1 ? 'post' : 'posts'}
          </span>
        </div>
      </header>

      <div className="flex flex-col divide-y divide-line">
        {topLevelPosts.length === 0 && (
          <p className="text-ink-dim text-sm py-4">No posts yet. Be the first to reply.</p>
        )}
        {topLevelPosts.map((post) => (
          <Post key={post.id} post={post} threadId={resolvedId} depth={0} />
        ))}
      </div>

      <div className="border-t border-line pt-5 flex flex-col gap-3">
        <h2 className="text-xs uppercase tracking-eyebrow text-ink-dim">Add a reply</h2>
        <PostComposer threadId={resolvedId} placeholder="Join the discussion..." />
      </div>
    </main>
  )
}

export default Thread
