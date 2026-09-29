import { useEffect, useRef, useState } from 'react'
import { confirmationOf, useLibrarianAction, useMergePreview, useWorkEditions } from '../api/librarian'
import { errorMessage } from '../api/errors'
import MergePreview from './librarian/MergePreview'
import ReasonField from './librarian/ReasonField'
import { SeriesPicker, WorkPicker } from './librarian/pickers'

/**
 * One librarian fix, as a float over the series page: the fields the action
 * needs, a required reason, and, for merge and split, a second step stating
 * what the server says will happen. Nothing here decides anything; the API does.
 */
const TITLES = {
  move: 'Move', position: 'Set position', remove: 'Remove from series', merge: 'Merge',
  split: 'Split', rename: 'Rename', dissolve: 'Dissolve', add: 'Add book',
}

/** Where the picked book lives now, relative to this series. */
function placeOf(pick, series) {
  if (!pick?.series) return 'own'
  if (pick.series.slug === series.slug) return 'here'
  return pick.series.kind === 'series' ? 'elsewhere' : 'own'
}
const plural = (n, one, many = `${one}s`) => `${n} ${n === 1 ? one : many}`

/** [merges away, survives]: the row's book into the picked one, unless swapped. */
function mergeSides(work, f) {
  return f.swapped ? [f.into, work] : [work, f.into]
}

function request(action, f, confirm) {
  const { kind, work, series } = action
  const reason = f.reason.trim()
  const position = f.position === '' ? null : Number(f.position)
  switch (kind) {
    case 'move':
      return { path: `works/${work.id}/move`, body: {
        reason, ...(f.target?.id ? { series_id: f.target.id } : { new_series_name: f.target?.name }),
        ...(position === null ? {} : { position }) } }
    case 'add':
      // The v1 move, pointed at this series: the picked book is the subject.
      return { path: `works/${f.pick.id}/move`, body: {
        reason, series_id: series.id, ...(position === null ? {} : { position }) } }
    case 'position':
      return { path: `series/${series.id}/position`, body: { reason, work_id: work.id, position } }
    case 'remove':
      return { path: `series/${series.id}/remove`, body: { reason, work_id: work.id } }
    case 'merge': {
      const [from, to] = mergeSides(work, f)
      return { path: `works/${from.id}/merge`, body: { reason, into_work_id: to?.id, confirm } }
    }
    case 'split':
      return { path: `works/${work.id}/split`, body: { reason, edition_ids: f.editions, confirm } }
    case 'rename':
      return { path: `series/${series.id}/rename`, body: { reason, name: f.name.trim() } }
    default:
      return { path: `series/${series.id}/dissolve`, body: { reason } }
  }
}

function ready(kind, f, editions, series) {
  if (!f.reason.trim()) return false
  if (kind === 'add') return !!f.pick && placeOf(f.pick, series) !== 'here'
  if (kind === 'move') return !!f.target
  if (kind === 'merge') return !!f.into
  if (kind === 'split') return f.editions.length > 0 && f.editions.length < editions.length
  if (kind === 'rename') return !!f.name.trim()
  return true
}

function EditionPicker({ editions, loaded, value, onChange }) {
  const toggle = (id) => onChange(value.includes(id) ? value.filter((v) => v !== id) : [...value, id])
  return (
    <fieldset className="flex flex-col gap-1 text-sm">
      <legend className="label">Editions to split off</legend>
      {loaded && editions.length < 2 && (
        <p className="alert-muted">A split needs at least two editions: one to move and one to stay.</p>
      )}
      {editions.map((e) => (
        <label key={e.id} className="flex items-center gap-2">
          <input type="checkbox" checked={value.includes(e.id)} onChange={() => toggle(e.id)} />
          <span className="font-serif text-ink">{e.title}</span>
          <span className="text-ink-dim tabular-nums">{[e.published_year, e.language, e.source].filter(Boolean).join(' · ')}</span>
        </label>
      ))}
    </fieldset>
  )
}

function Consequences({ action, fields, counts }) {
  const { work } = action
  if (action.kind === 'merge') {
    const [from, to] = mergeSides(work, fields)
    return (
      <p className="text-sm text-ink">
        <span className="font-serif italic">{from.title}</span> ({from.author}) will merge into{' '}
        <span className="font-serif italic">{to.title}</span> ({to.author}).{' '}
        {plural(counts.threads, 'thread')} and {plural(counts.shelves, 'shelf entry', 'shelf entries')} move.{' '}
        <span className="text-danger">This cannot be undone.</span>
      </p>
    )
  }
  return (
    <p className="text-sm text-ink">
      {plural(counts.editions, 'edition')} of <span className="font-serif italic">{work.title}</span>{' '}
      {counts.editions === 1 ? 'becomes a book of its own' : 'become a book of their own'};{' '}
      {counts.remaining} {counts.remaining === 1 ? 'stays' : 'stay'}. <span className="text-danger">This cannot be undone.</span>
    </p>
  )
}

function AddNotice({ pick, series }) {
  const place = placeOf(pick, series)
  if (place === 'here') {
    return (
      <p className="alert-muted">
        <span className="font-serif italic">{pick.title}</span> is already in{' '}
        <span className="font-serif">{series.name}</span>.
      </p>
    )
  }
  if (place !== 'elsewhere') return null
  return (
    <p className="text-warning text-sm">
      <span className="font-serif italic">{pick.title}</span> is in{' '}
      <span className="font-serif">{pick.series.name}</span> now. Adding it here takes it out of{' '}
      <span className="font-serif">{pick.series.name}</span>, with the threads tagged with it.
    </p>
  )
}

/** The preview, or why there is none. A refusal here is final for this pair. */
function PreviewSlot({ query, onSwap, swapDisabled }) {
  if (query.isError) return <p className="alert-danger">{errorMessage(query.error)}</p>
  if (!query.data) return <p className="text-ink-dim text-xs">loading preview</p>
  return (
    <div aria-busy={query.isPlaceholderData}>
      <MergePreview preview={query.data} onSwap={onSwap} swapDisabled={swapDisabled} />
    </div>
  )
}

function LibrarianPanel({ action, onClose, onDone }) {
  const { kind, work, series } = action
  const [fields, setFields] = useState({
    reason: '', name: '', target: null, into: action.into ?? null, editions: [], pick: null, swapped: false,
    // Only a reorder starts from the current place; a move names its own.
    position: kind === 'position' && work?.position != null ? String(work.position) : '',
  })
  // The server's counts, stamped with the merge pair they answered.
  const [answer, setAnswer] = useState(null)
  const mutation = useLibrarianAction()
  const editionsQuery = useWorkEditions(kind === 'split' ? work.id : null)
  const editions = editionsQuery.data ?? []
  const patch = (changes) => {
    if (mutation.isError) mutation.reset() // a refusal answered the old values, not these
    setFields((f) => ({ ...f, ...changes }))
  }
  const set = (key) => (value) => patch({ [key]: value })
  const [from, to] = kind === 'merge' && fields.into ? mergeSides(work, fields) : [null, null]
  const preview = useMergePreview(from?.id, to?.id)
  const pair = from && `${from.id}>${to.id}`
  // Counts for any other pair (the pick changed while the request was out) are not these.
  const counts = answer && answer.pair === pair ? answer.counts : null
  const setCounts = (c) => setAnswer(c && { counts: c, pair })
  // Counts from the server described the other direction; ask again.
  const refocusSwap = useRef(false)
  const swap = () => {
    patch({ swapped: !fields.swapped })
    if (counts) { refocusSwap.current = true; setCounts(null) }
  }
  const dialogRef = useRef(null)
  useEffect(() => {
    // Leaving the confirm step remounts the preview; keep focus on its swap.
    if (!refocusSwap.current || counts) return
    refocusSwap.current = false
    dialogRef.current?.querySelector('[aria-label="swap which book survives"]')?.focus()
  }, [counts])
  useEffect(() => {
    const opener = document.activeElement
    dialogRef.current?.querySelector('input, textarea')?.focus()
    return () => opener?.focus?.() // back to the row button that opened it
  }, [])
  // aria-modal promises the page behind is out of reach; Tab must not leave.
  const trapTab = (e) => {
    if (e.key === 'Escape') return onClose()
    if (e.key !== 'Tab') return
    const focusable = [...dialogRef.current.querySelectorAll('button, input, textarea, select, a[href]')]
      .filter((el) => !el.disabled)
    if (!focusable.length) return
    const first = focusable[0]
    const last = focusable[focusable.length - 1]
    if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus() }
    else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus() }
  }
  const subject = from ?? work // a swapped merge is about the picked book
  const title = kind === 'add'
    ? `Add a book to ${series.name}`
    : `${TITLES[kind]}${subject ? ` ${subject.title}` : ` ${series.name}`}`

  const submit = (confirm) => {
    mutation.mutate(request(action, fields, confirm), {
      onSuccess: (correction) => onDone(correction),
      onError: (error) => setCounts(confirmationOf(error)), // stamped with the pair submitted
    })
  }

  return (
    <div className="fixed inset-0 bg-bg/90 flex items-center justify-center z-50 p-4">
      <div ref={dialogRef} role="dialog" aria-modal="true" aria-label={title}
           onKeyDown={trapTab} className="float w-full max-w-prose max-h-full overflow-y-auto flex flex-col gap-4 p-5">
        <div className="flex items-center justify-between">
          <h2 className="text-sm uppercase tracking-eyebrow text-ink">{title}</h2>
          <button type="button" onClick={onClose} aria-label="Close" className="text-ink-dim hover:text-danger">
            <span aria-hidden="true">✕</span>
          </button>
        </div>

        {counts ? (
          <div className="flex flex-col gap-3">
            {kind === 'merge' && <PreviewSlot query={preview} onSwap={swap} swapDisabled={mutation.isPending} />}
            <Consequences action={action} fields={fields} counts={counts} />
            <div className="flex gap-3">
              <button type="button" className="btn-primary text-xs" onClick={() => submit(true)} disabled={mutation.isPending}>
                {`Confirm ${kind}`}
              </button>
              <button type="button" className="btn-ghost text-xs" onClick={() => setCounts(null)}>back</button>
            </div>
          </div>
        ) : (
          <form className="flex flex-col gap-3" onSubmit={(e) => { e.preventDefault(); submit(false) }}>
            {kind === 'add' && (
              <>
                <WorkPicker label="Find the book to add" value={fields.pick} onChange={set('pick')} />
                {fields.pick && <AddNotice pick={fields.pick} series={series} />}
              </>
            )}
            {kind === 'move' && <SeriesPicker value={fields.target} onChange={set('target')} />}
            {(kind === 'move' || kind === 'position' || kind === 'add') && (
              <div>
                <label className="label" htmlFor="lib-position">{kind === 'position' ? 'Position (blank clears)' : 'Position (optional)'}</label>
                <input id="lib-position" type="number" step="any" className="input" value={fields.position}
                       onChange={(e) => set('position')(e.target.value)} />
              </div>
            )}
            {/* From search both books arrive preset; only the series page asks for one. */}
            {kind === 'merge' && !action.into && (
              <WorkPicker label="Find the book to keep" exclude={work.id} value={fields.into}
                          onChange={(w) => patch({ into: w, swapped: false })} />
            )}
            {kind === 'merge' && fields.into && <PreviewSlot query={preview} onSwap={swap} swapDisabled={mutation.isPending} />}
            {kind === 'split' && <EditionPicker editions={editions} loaded={editionsQuery.isSuccess} value={fields.editions} onChange={set('editions')} />}
            {kind === 'rename' && (
              <div>
                <label className="label" htmlFor="lib-name">New name</label>
                <input id="lib-name" className="input" value={fields.name} onChange={(e) => set('name')(e.target.value)} />
              </div>
            )}
            <ReasonField kind={kind} value={fields.reason} onChange={set('reason')} />
            {mutation.isError && !confirmationOf(mutation.error) && (
              <p className="alert-danger">{errorMessage(mutation.error)}</p>
            )}
            <button type="submit" className="btn-primary text-xs self-start"
                    disabled={!ready(kind, fields, editions, series) || mutation.isPending
                              || (kind === 'merge' && (!preview.isSuccess || preview.isPlaceholderData))}>
              {TITLES[kind]}
            </button>
          </form>
        )}
      </div>
    </div>
  )
}

export default LibrarianPanel
