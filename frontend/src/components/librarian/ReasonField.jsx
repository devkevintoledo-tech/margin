import { applyPreset, presetIn, reasonsFor } from './reasons'

/**
 * The reason every librarian fix requires: preset chips for the common cases
 * above a free-text field that stays the source of truth. A chip only writes
 * text into the field (keeping anything typed as its detail); the field stays
 * required, and the panel and the server still check it.
 *
 * Chips are toggle buttons, and look like the series page's book filter:
 * pressed is underlined as well as coloured, because colour never carries
 * meaning alone.
 */
function ReasonField({ kind, value, onChange, id = 'lib-reason' }) {
  const presets = reasonsFor(kind)
  const active = presetIn(value, presets)
  return (
    <div>
      <label className="label" htmlFor={id}>Reason</label>
      {presets.length > 0 && (
        <div role="group" aria-label="Quick reasons" className="flex flex-wrap gap-x-3 gap-y-1 mb-2">
          {presets.map((preset) => (
            <button
              key={preset}
              type="button"
              aria-pressed={active === preset}
              onClick={() => onChange(applyPreset(value, preset, presets))}
              className={`text-xs px-1 transition-colors duration-fast ${
                active === preset ? 'text-accent underline underline-offset-4' : 'text-ink-dim hover:text-accent'
              }`}
            >
              {preset}
            </button>
          ))}
        </div>
      )}
      <textarea id={id} rows={2} className="input" value={value} onChange={(e) => onChange(e.target.value)} />
    </div>
  )
}

export default ReasonField
