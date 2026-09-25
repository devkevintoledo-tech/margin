import { useId, useState } from 'react'

/**
 * An nvim-style diagnostic float — the hover primitive for the whole UI.
 *
 * Square border (nvim's `border="single"`), which also keeps the project's
 * no-new-radii rule. Opens on hover AND focus-within so it is keyboard
 * reachable, and toggles on tap for touch, where hover does not exist.
 *
 * The severity is always stated in text for screen readers; the coloured `■` is
 * decorative, because colour never carries meaning alone here.
 */
const SEVERITY = {
  error: { marker: 'text-danger', label: 'Error' },
  warn: { marker: 'text-warning', label: 'Warning' },
  info: { marker: 'text-accent', label: 'Info' },
  hint: { marker: 'text-ink-muted', label: 'Hint' },
}

function DiagnosticFloat({ severity = 'info', message, source, align = 'start', children }) {
  const id = useId()
  const [pinned, setPinned] = useState(false)
  const tone = SEVERITY[severity] ?? SEVERITY.info

  return (
    <span className="relative inline-flex group">
      <span
        tabIndex={0}
        aria-describedby={id}
        onClick={() => setPinned((v) => !v)}
        className="cursor-help underline decoration-dotted decoration-ink-faint underline-offset-2"
      >
        {children}
      </span>

      <span
        role="tooltip"
        id={id}
        className={`float absolute top-full mt-1 z-30 w-max max-w-xs flex-col gap-0.5
                    ${align === 'end' ? 'right-0' : 'left-0'}
                    ${pinned ? 'flex' : 'hidden'} group-hover:flex group-focus-within:flex`}
      >
        <span>
          <span aria-hidden="true" className={tone.marker}>
            ■
          </span>{' '}
          <span className="sr-only">{tone.label}: </span>
          <span className="text-ink">{message}</span>
        </span>
        {source && <span className="text-ink-dim">{source}</span>}
      </span>
    </span>
  )
}

export default DiagnosticFloat
