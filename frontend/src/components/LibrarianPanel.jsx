import { useEffect, useRef, useState } from 'react'
import { confirmationOf, useLibrarianAction, useSeriesSearch, useWorkEditions } from '../api/librarian'
import { useSearchWorks } from '../api/works'
import { errorMessage } from '../api/errors'

/**
 * One librarian fix, as a float over the series page: the fields the action
 * needs, a required reason, and, for merge and split, a second step stating
 * what the server says will happen. Nothing here decides anything; the API does.
 */
const TITLES = {
  move: 'Move', position: 'Set position', remove: 'Remove from series', merge: 'Merge',
  split: 'Split', rename: 'Rename', dissolve: 'Dissolve',
}
const plural = (n, one, many = `${one}s`) => `${n} ${n === 1 ? one : many}`

/** ``value`` once it has stopped changing for ``ms``. */
function useDebounced(value, ms = 300) {
  const [settled, setSettled] = useState(value)
  useEffect(() => {
    const timer = setTimeout(() => setSettled(value), ms)
    return () => clearTimeout(timer)
  }, [value, ms])
  return settled
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
    case 'position':
      return { path: `series/${series.id}/position`, body: { reason, work_id: work.id, position } }
    case 'remove':
      return { path: `series/${series.id}/remove`, body: { reason, work_id: work.id } }
    case 'merge':
      return { path: `works/${work.id}/merge`, body: { reason, into_work_id: f.into?.id, confirm } }
    case 'split':
      return { path: `works/${work.id}/split`, body: { reason, edition_ids: f.editions, confirm } }
    case 'rename':
      return { path: `series/${series.id}/rename`, body: { reason, name: f.name.trim() } }
    default:
      return { path: `series/${series.id}/dissolve`, body: { reason } }
  }
}

function ready(kind, f) {
  if (!f.reason.trim()) return false
  if (kind === 'move') return !!f.target
  if (kind === 'merge') return !!f.into
  if (kind === 'split') return f.editions.length > 0
  if (kind === 'rename') return !!f.name.trim()
  return true
}

function SeriesPicker({ value, onChange }) {
  const [q, setQ] = useState('')
  const { data: hits = [] } = useSeriesSearch(q)
  const named = q.trim()
  return (
    <div className="flex flex-col gap-2">
      <label className="label" htmlFor="lib-series">Find a series</label>
      <input id="lib-series" className="input" value={q} onChange={(e) => setQ(e.target.value)} />
      <div role="radiogroup" aria-label="Series" className="flex flex-col gap-1 text-sm">
        {hits.map((s) => (
          <label key={s.id} className="flex items-center gap-2">
            <input type="radio" name="lib-series" checked={value?.id === s.id} onChange={() => onChange(s)} />
            <span className="font-serif text-ink">{s.name}</span>
            <span className="text-ink-dim tabular-nums">{plural(s.book_count, 'book')}</span>
          </label>
        ))}
        {named.length > 1 && !hits.some((s) => s.name.toLowerCase() === named.toLowerCase()) && (
          <label className="flex items-center gap-2">
            <input type="radio" name="lib-series" checked={!value?.id && value?.name === named}
                   onChange={() => onChange({ name: named })} />
            <span className="text-warning">new series: {named}</span>
          </label>
        )}
      </div>
    </div>
  )
}

function WorkPicker({ exclude, value, onChange }) {
  const [q, setQ] = useState('')
  // A cold search reaches Open Library and ingests what it finds: never per keystroke.
  const { data: works = [] } = useSearchWorks(useDebounced(q.trim()))
  return (
    <div className="flex flex-col gap-2">
      <label className="label" htmlFor="lib-work">Find the book to keep</label>
      <input id="lib-work" className="input" value={q} onChange={(e) => setQ(e.target.value)} />
      <div role="radiogroup" aria-label="Book to keep" className="flex flex-col gap-1 text-sm">
        {works.filter((w) => w.id !== exclude).map((w) => (
          <label key={w.id} className="flex items-center gap-2">
            <input type="radio" name="lib-work" checked={value?.id === w.id} onChange={() => onChange(w)} />
            <span className="font-serif text-ink">{w.title}</span>
            <span className="text-user text-xs">{w.author}</span>
          </label>
        ))}
      </div>
    </div>
  )
}

function EditionPicker({ workId, value, onChange }) {
  const { data: editions = [] } = useWorkEditions(workId)
  const toggle = (id) => onChange(value.includes(id) ? value.filter((v) => v !== id) : [...value, id])
  return (
    <fieldset className="flex flex-col gap-1 text-sm">
      <legend className="label">Editions to split off</legend>
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
    return (
      <p className="text-sm text-ink">
        <span className="font-serif italic">{work.title}</span> ({work.author}) will merge into{' '}
        <span className="font-serif italic">{fields.into.title}</span> ({fields.into.author}).{' '}
        {plural(counts.threads, 'thread')} and {plural(counts.shelves, 'shelf entry', 'shelf entries')} move.{' '}
        <span className="text-danger">This cannot be undone.</span>
      </p>
    )
  }
  return (
    <p className="text-sm text-ink">
      {plural(counts.editions, 'edition')} of <span className="font-serif italic">{work.title}</span> become a
      book of their own; {counts.remaining} stay. <span className="text-danger">This cannot be undone.</span>
    </p>
  )
}

function LibrarianPanel({ action, onClose, onDone }) {
  const { kind, work, series } = action
  const [fields, setFields] = useState({
    reason: '', name: '', target: null, into: null, editions: [],
    // Only a reorder starts from the current place; a move names its own.
    position: kind === 'position' && work?.position != null ? String(work.position) : '',
  })
  const [counts, setCounts] = useState(null)
  const mutation = useLibrarianAction()
  const set = (key) => (value) => setFields((f) => ({ ...f, [key]: value }))
  const dialogRef = useRef(null)
  useEffect(() => {
    dialogRef.current?.querySelector('input, textarea')?.focus()
  }, [])
  const title = `${TITLES[kind]}${work ? ` ${work.title}` : ` ${series.name}`}`

  const submit = (confirm) => {
    mutation.mutate(request(action, fields, confirm), {
      onSuccess: (correction) => onDone(correction),
      onError: (error) => setCounts(confirmationOf(error)),
    })
  }

  return (
    <div className="fixed inset-0 bg-bg/90 flex items-center justify-center z-50 p-4">
      <div ref={dialogRef} role="dialog" aria-modal="true" aria-label={title}
           onKeyDown={(e) => { if (e.key === 'Escape') onClose() }} className="float w-full max-w-lg flex flex-col gap-4 p-5">
        <div className="flex items-center justify-between">
          <h2 className="text-sm uppercase tracking-eyebrow text-ink">{title}</h2>
          <button type="button" onClick={onClose} aria-label="Close" className="text-ink-dim hover:text-danger">
            <span aria-hidden="true">✕</span>
          </button>
        </div>

        {counts ? (
          <div className="flex flex-col gap-3">
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
            {kind === 'move' && <SeriesPicker value={fields.target} onChange={set('target')} />}
            {(kind === 'move' || kind === 'position') && (
              <div>
                <label className="label" htmlFor="lib-position">{kind === 'move' ? 'Position (optional)' : 'Position (blank clears)'}</label>
                <input id="lib-position" type="number" step="0.5" className="input" value={fields.position}
                       onChange={(e) => set('position')(e.target.value)} />
              </div>
            )}
            {kind === 'merge' && <WorkPicker exclude={work.id} value={fields.into} onChange={set('into')} />}
            {kind === 'split' && <EditionPicker workId={work.id} value={fields.editions} onChange={set('editions')} />}
            {kind === 'rename' && (
              <div>
                <label className="label" htmlFor="lib-name">New name</label>
                <input id="lib-name" className="input" value={fields.name} onChange={(e) => set('name')(e.target.value)} />
              </div>
            )}
            <div>
              <label className="label" htmlFor="lib-reason">Reason</label>
              <textarea id="lib-reason" rows={2} className="input" value={fields.reason}
                        onChange={(e) => set('reason')(e.target.value)} />
            </div>
            {mutation.isError && !confirmationOf(mutation.error) && (
              <p className="alert-danger">{errorMessage(mutation.error)}</p>
            )}
            <button type="submit" className="btn-primary text-xs self-start"
                    disabled={!ready(kind, fields) || mutation.isPending}>
              {TITLES[kind]}
            </button>
          </form>
        )}
      </div>
    </div>
  )
}

export default LibrarianPanel
