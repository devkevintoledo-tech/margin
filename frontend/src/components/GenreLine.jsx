import { Fragment, useState } from 'react'
import { Link } from 'react-router-dom'
import { useGenreTree, useUnvoteGenre, useVetoGenre, useVoteGenre, useWorkGenres } from '../api/genres'
import { useRevertCorrection } from '../api/librarian'
import { errorMessage } from '../api/errors'
import useAuthStore from '../store/auth'
import GenrePicker from './GenrePicker'
import ReasonField from './librarian/ReasonField'

/** One line of a book's genres: `genres  grimdark 7 · fantasy 19  [tag]`. */
function GenreLine({ workId, title, editing = false }) {
  const user = useAuthStore((s) => s.user)
  const { data } = useWorkGenres(workId)
  const { data: tree = [] } = useGenreTree()
  const vote = useVoteGenre(workId)
  const unvote = useUnvoteGenre(workId)
  const [open, setOpen] = useState(false)
  const [error, setError] = useState(null)
  const [vetoing, setVetoing] = useState(null)
  const [reason, setReason] = useState('')
  const veto = useVetoGenre(workId)
  const revertFix = useRevertCorrection()
  const librarian = !!user?.is_librarian && editing

  if (!data) return null
  const readers = data.source === 'readers'
  const shown = data.genres.filter((g) => !g.vetoed)
  const vetoed = librarian ? data.genres.filter((g) => g.vetoed) : []
  const mine = new Set(shown.filter((g) => g.my_vote).map((g) => g.slug))

  const onToggle = (slug, on, name) => {
    setError(null)
    ;(on ? vote : unvote).mutate({ slug, name }, { onError: (e) => setError(errorMessage(e)) })
  }

  return (
    <div className="relative text-xs flex flex-col gap-1">
      <p className="flex flex-wrap items-baseline gap-x-2">
        <span className="text-ink-dim">{data.source === 'inferred' ? 'genres (inferred)' : 'genres'}</span>
        {shown.length === 0 && (
          <>
            <span aria-hidden="true" className="text-ink-dim">—</span>
            <span className="sr-only">no genres yet</span>
          </>
        )}
        {shown.map((g, i) => (
          <Fragment key={g.slug}>
            {i > 0 && <span aria-hidden="true" className="text-ink-faint">·</span>}
            <span>
              {g.my_vote && (
                <>
                  <span aria-hidden="true" className="text-accent">● </span>
                  <span className="sr-only">you tagged this</span>
                </>
              )}
              <Link to={`/genres/${g.slug}`} className="text-path hover:text-accent transition-colors duration-fast">
                {g.slug}
              </Link>
              {readers && <span className="text-ink-dim tabular-nums"> {g.score}</span>}
              {librarian && (
                <button type="button" className="btn-ghost text-xs" aria-label={`veto ${g.slug}`}
                        onClick={() => { setVetoing(g.slug); setReason('') }}>[veto]</button>
              )}
            </span>
          </Fragment>
        ))}
        {vetoed.map((g) => (
          <span key={g.slug} className="flex items-baseline gap-1">
            <span className="line-through text-warning">{g.slug}</span>
            <span className="sr-only">vetoed</span>
            <button type="button" className="btn-ghost text-xs" aria-label={`undo veto of ${g.slug}`}
                    onClick={() => revertFix.mutate(g.veto_id)}>
              [undo]
            </button>
          </span>
        ))}
        {user && (
          <button type="button" className="btn-ghost text-xs" aria-label={`tag genres of ${title}`}
                  aria-expanded={open} onClick={() => setOpen((v) => !v)}>
            [tag]
          </button>
        )}
      </p>
      {error && <p role="alert" className="text-danger">{error}</p>}
      {vetoing && (
        <form className="float p-3 flex flex-col gap-2 max-w-prose" aria-label={`veto ${vetoing} on ${title}`}
              onSubmit={(e) => {
                e.preventDefault()
                veto.mutate({ slug: vetoing, reason: reason.trim() }, {
                  onSuccess: () => setVetoing(null),
                  onError: (err) => setError(errorMessage(err)),
                })
              }}>
          <ReasonField kind="veto_genre" value={reason} onChange={setReason} id={`veto-${workId}`} />
          <div className="flex gap-3 justify-end">
            <button type="button" className="btn-ghost text-xs" onClick={() => setVetoing(null)}>cancel</button>
            <button type="submit" className="btn-secondary text-xs" disabled={!reason.trim() || veto.isPending}>veto</button>
          </div>
        </form>
      )}
      {open && (
        <div className="absolute z-10 top-full left-0 mt-1">
          <GenrePicker tree={tree} selected={mine} max={5} label={`tag ${title}`}
                       onToggle={onToggle} onClose={() => setOpen(false)} />
        </div>
      )}
    </div>
  )
}

export default GenreLine
