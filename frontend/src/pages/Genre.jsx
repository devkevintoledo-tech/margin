import { useState } from 'react'
import { useParams, useNavigate, Link } from 'react-router-dom'
import { useGenre, useGenreThreads, useGenreWorks } from '../api/genres'
import { useVoteThread } from '../api/threads'
import WorkCard from '../components/WorkCard'
import PathHeader from '../components/PathHeader'
import DataTable from '../components/DataTable'
import ThreadModal from '../components/ThreadModal'
import VoteControl from '../components/VoteControl'
import { relativeTime } from '../components/Post'
import { useStatusBar } from '../store/status'
import useAuthStore from '../store/auth'

function Genre() {
  const { slug: genreSlug } = useParams()
  const navigate = useNavigate()
  const user = useAuthStore((s) => s.user)
  const [showModal, setShowModal] = useState(false)
  const voteMutation = useVoteThread()

  const [sort, setSort] = useState('top')
  const { data: genre, isLoading, isError } = useGenre(genreSlug)
  const { data: works } = useGenreWorks(genreSlug, sort)
  // Subgenres have no room of their own (spec D9): their discussion is the parent's.
  const isRoom = !!genre && !genre.parent
  const { data: threads } = useGenreThreads(isRoom ? genreSlug : null)

  const threadCount = threads?.length ?? 0

  useStatusBar({
    mode: 'GENRE',
    path: `~/genres/${genreSlug}`,
    facts: [`${threadCount} ${threadCount === 1 ? 'thread' : 'threads'}`],
  })

  if (isLoading) {
    return (
      <main className="max-w-shell mx-auto px-4 py-8">
        <div className="animate-pulse flex flex-col gap-6">
          <div className="h-10 bg-panel w-1/3" />
          <div className="h-4 bg-panel w-2/3" />
        </div>
      </main>
    )
  }

  if (isError || !genre) {
    return (
      <main className="max-w-shell mx-auto px-4 py-8">
        <p className="alert-danger">Genre not found.</p>
      </main>
    )
  }

  const columns = [
    {
      key: 'score',
      label: 'Score',
      align: 'right',
      width: 8,
      render: (row) => (
        <VoteControl
          variant="row"
          score={row.score ?? 0}
          myVote={row.my_vote ?? 0}
          onVote={(value) => user && voteMutation.mutate({ id: row.id, value, genreSlug })}
          disabled={!user}
          pending={voteMutation.isPending}
        />
      ),
    },
    {
      key: 'title',
      label: 'Thread',
      render: (row) => (
        <Link
          to={`/genres/${genreSlug}/threads/${row.id}`}
          className="text-ink hover:text-accent transition-colors duration-fast"
        >
          {row.title}
        </Link>
      ),
    },
    {
      key: 'author',
      label: 'By',
      width: 16,
      render: (row) => <span className="text-user">{row.author}</span>,
    },
    {
      key: 'post_count',
      label: 'Repl',
      align: 'right',
      width: 6,
      render: (row) => <span className="text-ink-dim tabular-nums">{row.post_count ?? 0}</span>,
    },
    {
      key: 'created_at',
      label: 'Age',
      align: 'right',
      width: 6,
      render: (row) => <span className="text-ink-dim tabular-nums">{relativeTime(row.created_at)}</span>,
    },
  ]

  const path = [{ label: 'genres', to: '/' }]
  if (genre.parent) path.push({ label: genre.parent.slug, to: `/genres/${genre.parent.slug}` })
  path.push({ label: genre.slug })

  return (
    <main className="max-w-shell mx-auto px-4 py-6 flex flex-col gap-10">
      <PathHeader segments={path} />

      <header className="border-b border-line pb-4 flex flex-col gap-2">
        <h1 className="text-display-sm text-ink uppercase">{genre.name}</h1>
        {genre.description && (
          <p className="text-ink-dim text-sm max-w-prose leading-relaxed">{genre.description}</p>
        )}
      </header>
      {genre.retired && (
        <p className="alert-muted">This genre was retired from the list; its books and threads stay reachable.</p>
      )}

      {genre.children.length > 0 && (
        <section className="flex flex-col gap-3" aria-labelledby="subgenres">
          <h2 id="subgenres" className="text-xs uppercase tracking-eyebrow text-ink-dim border-b border-line pb-2">
            Subgenres
          </h2>
          <ul className="grid sm:grid-cols-2 lg:grid-cols-3 gap-x-8">
            {genre.children.map((child) => (
              <li key={child.slug}>
                <Link to={`/genres/${child.slug}`}
                      className="flex justify-between gap-3 py-1 px-2 -mx-2 hover:bg-highlight transition-colors duration-fast">
                  <span className="text-path">{child.slug}</span>
                  <span className="text-ink-dim tabular-nums">{child.book_count}</span>
                </Link>
              </li>
            ))}
          </ul>
        </section>
      )}

      {works && works.length > 0 && (
        <section className="flex flex-col gap-4">
          <div className="flex items-baseline justify-between border-b border-line pb-2">
            <h2 className="text-xs uppercase tracking-eyebrow text-ink-dim">Books</h2>
            <div role="group" aria-label="Sort books" className="flex gap-3 text-xs">
              {['top', 'title'].map((s) => (
                <button key={s} type="button" aria-pressed={sort === s} onClick={() => setSort(s)}
                        className={sort === s ? 'text-accent underline underline-offset-4' : 'text-ink-dim hover:text-accent'}>
                  {s}
                </button>
              ))}
            </div>
          </div>
          <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 gap-5">
            {works.map((work) => (
              <div key={work.id} className="flex flex-col gap-1">
                {work.inferred && <p className="text-xs uppercase tracking-eyebrow text-ink-dim">inferred</p>}
                <WorkCard work={work} />
              </div>
            ))}
          </div>
        </section>
      )}

      {isRoom ? (
      <section className="panel p-5 pt-6">
        <h2 className="panel-title">Discussions</h2>

        <div className="flex justify-end mb-3">
          {user && (
            <button onClick={() => setShowModal(true)} className="btn-secondary text-xs">
              Start a Discussion
            </button>
          )}
        </div>

        <DataTable
          columns={columns}
          rows={threads || []}
          caption={`Discussions in ${genre.name}`}
          emptyMessage="No discussions yet."
        />
      </section>
      ) : (
        <p className="text-ink-dim text-sm">
          discussion lives in{' '}
          <Link to={`/genres/${genre.room_slug}`} className="text-path hover:text-accent">{genre.room_slug}</Link>
        </p>
      )}

      {showModal && (
        <ThreadModal
          target={{ genre_slug: genreSlug }}
          onClose={() => setShowModal(false)}
          onCreated={(thread) => navigate(`/genres/${genreSlug}/threads/${thread.id}`)}
          title="Start a Discussion"
          submitLabel="Create"
        />
      )}
    </main>
  )
}

export default Genre
