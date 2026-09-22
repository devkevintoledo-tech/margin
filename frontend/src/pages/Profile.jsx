import { useParams } from 'react-router-dom'
import { useProfile } from '../api/users'
import BookCard from '../components/BookCard'

const SHELF_STATUS_LABELS = {
  want_to_read: 'Want to Read',
  reading: 'Currently Reading',
  read: 'Read',
}

const SHELF_STATUS_ORDER = ['reading', 'want_to_read', 'read']

function ShelfSection({ status, books }) {
  if (!books || books.length === 0) return null
  return (
    <section className="flex flex-col gap-5">
      <div className="flex items-baseline gap-4 border-b border-line pb-3">
        <span className="rule" />
        <h2 className="text-sm font-semibold uppercase tracking-eyebrow text-ink">
          {SHELF_STATUS_LABELS[status]}
        </h2>
        <span className="text-ink-muted text-xs tabular-nums ml-auto">{books.length}</span>
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

  if (isLoading) {
    return (
      <main className="max-w-5xl mx-auto px-6 py-10">
        <div className="animate-pulse flex flex-col gap-6">
          <div className="h-12 bg-surface w-48" />
          <div className="h-4 bg-surface w-32" />
        </div>
      </main>
    )
  }

  if (isError || !profile) {
    return (
      <main className="max-w-5xl mx-auto px-6 py-10">
        <p className="text-danger">User not found.</p>
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
    <main className="max-w-5xl mx-auto px-6 py-10 flex flex-col gap-12">
      {/* Header — reader identity, not a stat dashboard (§21). */}
      <div className="border-b border-line pb-6 flex flex-col gap-4">
        <p className="eyebrow">Reader</p>
        <h1 className="text-display-sm md:text-display font-bold uppercase text-ink break-words">
          {profile.username}
        </h1>
        {profile.bio && <p className="text-ink-dim max-w-xl leading-relaxed">{profile.bio}</p>}

        {/* Counts come straight from the shelves above — nothing is inferred. */}
        <dl className="flex flex-wrap gap-x-10 gap-y-3 mt-2">
          {SHELF_STATUS_ORDER.map((status) => (
            <div key={status} className="flex flex-col gap-0.5">
              <dt className="text-ink-muted text-xs uppercase tracking-wider">
                {SHELF_STATUS_LABELS[status]}
              </dt>
              <dd className="text-ink text-2xl font-semibold tabular-nums">
                {shelves[status]?.length ?? 0}
              </dd>
            </div>
          ))}
        </dl>
      </div>

      {/* Shelves */}
      {SHELF_STATUS_ORDER.map((status) => (
        <ShelfSection key={status} status={status} books={shelves[status]} />
      ))}

      {totalBooks === 0 && <p className="text-ink-dim">No books on shelf yet.</p>}
    </main>
  )
}

export default Profile
