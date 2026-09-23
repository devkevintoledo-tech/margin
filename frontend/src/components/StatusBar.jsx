import useStatusStore from '../store/status'
import useAuthStore from '../store/auth'

/**
 * The pinned bottom bar — vim/tmux statusline. Fixed, never a flex sibling, so
 * it can't eat viewport on short screens; `body` reserves its height via
 * `--shell-status-h`.
 *
 * The mode block is one of only two places inversion is used (the other is a
 * primary button).
 */
function StatusBar() {
  const { mode, path, facts } = useStatusStore()
  const user = useAuthStore((s) => s.user)

  return (
    <div
      role="status"
      className="fixed bottom-0 inset-x-0 z-30 h-[var(--shell-status-h)] bg-panel border-t border-line-strong
                 flex items-center gap-3 px-3 text-xs"
    >
      <span className="bg-accent text-bg px-2 font-medium shrink-0">{mode}</span>

      <span className="text-path truncate">{path}</span>

      <span className="ml-auto flex items-center gap-3 shrink-0">
        {facts.map((fact) => (
          <span key={fact} className="text-ink-dim hidden sm:inline">
            {fact}
          </span>
        ))}
        {user && (
          <>
            <span aria-hidden="true" className="text-ink-faint hidden sm:inline">
              │
            </span>
            <span className="text-user">{user.username}</span>
          </>
        )}
      </span>
    </div>
  )
}

export default StatusBar
