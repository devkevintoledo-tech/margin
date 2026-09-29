import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useCorrections, useRevertCorrection } from '../api/librarian'
import { errorMessage } from '../api/errors'
import DataTable from '../components/DataTable'
import DiagnosticFloat from '../components/DiagnosticFloat'
import PathHeader from '../components/PathHeader'
import { relativeTime } from '../components/Post'
import { useStatusBar } from '../store/status'
import useAuthStore from '../store/auth'
import NotFound from './NotFound'

/** The log of catalog fixes: what, why, who, whether it exports, and undo. */
function Log() {
  const [runtimeOnly, setRuntimeOnly] = useState(false)
  const { data: rows = [], isLoading } = useCorrections({ runtimeOnly })
  const revert = useRevertCorrection()
  useStatusBar({ mode: 'LIBRARIAN', path: '~/librarian', facts: [`${rows.length} fixes`] })

  const columns = [
    { key: 'created_at', label: 'Age', align: 'right', width: 6,
      render: (r) => <span className="text-ink-dim tabular-nums">{relativeTime(r.created_at)}</span> },
    { key: 'op', label: 'Op', width: 18, render: (r) => <span className="text-ink-dim">{r.op}</span> },
    { key: 'subject', label: 'Subject',
      render: (r) => r.room_slug
        ? <Link to={`/series/${r.room_slug}`} className="font-serif text-ink hover:text-accent">{r.subject}</Link>
        : <span className="font-serif text-ink-dim">{r.subject}</span> },
    { key: 'reason', label: 'Why', render: (r) => <span className="text-ink">{r.reason}</span> },
    { key: 'user', label: 'By', width: 12, render: (r) => <span className="text-user">{r.user}</span> },
    { key: 'export', label: 'Export', width: 14,
      render: (r) => r.exportable
        ? <span className="text-ok">exported</span>
        : <DiagnosticFloat severity="warn" message={r.runtime_only_reason}><span className="text-warning">runtime-only</span></DiagnosticFloat> },
    { key: 'undo', label: '', width: 6,
      render: (r) => r.reverted_at ? <span className="text-ink-dim">undone</span> : r.undoable && (
        <button type="button" className="btn-ghost text-xs" aria-label={`undo ${r.subject}`}
                disabled={revert.isPending} onClick={() => revert.mutate(r.id)}>undo</button>
      ) },
  ]

  return (
    <main className="max-w-shell mx-auto px-4 py-6 flex flex-col gap-6">
      <PathHeader segments={[{ label: 'librarian' }]} />
      <div className="flex items-center justify-between">
        <h1 className="text-sm uppercase tracking-eyebrow text-ink">Catalog fixes</h1>
        <button type="button" aria-pressed={runtimeOnly} onClick={() => setRuntimeOnly((v) => !v)}
                className={`text-xs ${runtimeOnly ? 'text-accent underline underline-offset-4' : 'text-ink-dim hover:text-accent'}`}>
          runtime-only only
        </button>
      </div>
      {revert.isError && <p className="alert-danger text-xs">{errorMessage(revert.error)}</p>}
      {isLoading
        ? <div className="h-8 border border-line bg-panel animate-pulse" />
        : <DataTable columns={columns} rows={rows} caption="Catalog fixes" emptyMessage="No fixes yet." />}
    </main>
  )
}

function Librarian() {
  const user = useAuthStore((s) => s.user)
  return user?.is_librarian ? <Log /> : <NotFound />
}

export default Librarian
