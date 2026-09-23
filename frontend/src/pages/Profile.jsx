import { useParams } from 'react-router-dom'
import { useProfile } from '../api/users'
import BookCard from '../components/BookCard'
import PathHeader from '../components/PathHeader'
import { useStatusBar } from '../store/status'

const SHELF_STATUS_LABELS = {
  want_to_read: 'want_to_read',
  reading: 'reading',
  read: 'read',
}

const SHELF_STATUS_TONE = {
  want_to_read: 'text-ink-dim',
  reading: 'text-warning',
  read: 'text-ok',
}

const SHELF_STATUS_ORDER = ['reading', 'want_to_read', 'read']

function ShelfSection({ status, books }) {
  if (!books || books.length === 0) return null
  return (
    <section className="flex flex-col gap-4">
      <div className="flex items-baseline gap-3 border-b border-line pb-2">
        <h2 className={`text-xs uppercase tracking-eyebrow ${SHELF_STATUS_TONE[status]}`}>
          {SHELF_STATUS_LABELS[status]}
        </h2>
        <span className="text-ink-dim text-xs tabular-nums ml-auto">{books.length}</span>
      </div>
      <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 gap-5">
        {books.map((book) => (
          <BookCard key={book.id} book={book} />
        ))}
      </div>
    </section>
  )
}

function Profile() {
  const { username } = useParams()
  const { data: profile, isLoading, isError } = useProfile(username)

  useStatusBar({
    mode: 'PROFILE',
    path: `~/profile/${username}`,
    facts: [],
  })

  if (isLoading) {
    return (
      <main className="max-w-shell mx-auto px-4 py-8">
        <div className="animate-pulse flex flex-col gap-6">
          <div className="h-12 bg-panel w-48" />
          <div className="h-4 bg-panel w-32" />
        </div>
      </main>
    )
  }

  if (isError || !profile) {
    return (
      <main className="max-w-shell mx-auto px-4 py-8">
        <p className="alert-danger">User not found.</p>
      </main>
    )
  }

  // Expect profile.shelves as { want_to_read: [], reading: [], read: [] }
  // or profile.books as flat list with shelf_status field
  const shelves = profile.shelves || {}
  if (!profile.shelves && profile.books) {
    for (const book of profile.books) {
      const s = book.shelf_status
      if (s) {
        shelves[s] = shelves[s] || []
        shelves[s].push(book)
      }
    }
  }

  const totalBooks = Object.values(shelves).reduce((acc, arr) => acc + (arr?.length || 0), 0)

  return (
    <main className="max-w-shell mx-auto px-4 py-6 flex flex-col gap-10">
      <PathHeader segments={[{ label: 'profile', to: '/' }, { label: username }]} />

      <header className="border-b border-line pb-5 flex flex-col gap-4">
        <h1 className="text-display-sm text-user break-words">{profile.username}</h1>
        {profile.bio && <p className="text-ink-dim text-sm max-w-prose leading-relaxed">{profile.bio}</p>}

        {/* Aligned key/value, as `ls` would print it. */}
        <dl className="grid grid-cols-[auto_1fr] gap-x-6 gap-y-0.5 text-sm max-w-xs">
          {SHELF_STATUS_ORDER.map((status) => (
            <div key={status} className="contents">
              <dt className={SHELF_STATUS_TONE[status]}>{SHELF_STATUS_LABELS[status]}</dt>
              <dd className="text-ink tabular-nums">{shelves[status]?.length ?? 0}</dd>
            </div>
          ))}
        </dl>
      </header>

      {/* Shelves */}
      {SHELF_STATUS_ORDER.map((status) => (
        <ShelfSection key={status} status={status} books={shelves[status]} />
      ))}

      {totalBooks === 0 && <p className="text-ink-dim text-sm">No books on shelf yet.</p>}
    </main>
  )
}

export default Profile
