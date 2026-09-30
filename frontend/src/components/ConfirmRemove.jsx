import { useEffect, useRef } from 'react'

/**
 * Inline delete confirmation: `rm post? [y] [n]`. Never window.confirm() — a
 * browser dialog is modal chrome this UI does not have. Focus lands on "no" so
 * a stray Enter keeps the post; Escape backs out.
 */
function ConfirmRemove({ noun, onConfirm, onCancel, pending = false }) {
  const noRef = useRef(null)
  useEffect(() => {
    noRef.current?.focus()
  }, [])

  return (
    <span
      role="group"
      aria-label={`Confirm deleting this ${noun}`}
      className="inline-flex items-center gap-2 text-xs"
      onKeyDown={(e) => {
        if (e.key === 'Escape') onCancel()
      }}
    >
      <span className="text-ink-dim">rm {noun}?</span>
      <button
        type="button"
        onClick={onConfirm}
        disabled={pending}
        aria-label={`yes, delete ${noun}`}
        className="text-danger hover:underline disabled:opacity-50"
      >
        [y]
      </button>
      <button
        type="button"
        ref={noRef}
        onClick={onCancel}
        aria-label="no, keep it"
        className="text-ink-dim hover:text-accent transition-colors duration-fast"
      >
        [n]
      </button>
    </span>
  )
}

export default ConfirmRemove
