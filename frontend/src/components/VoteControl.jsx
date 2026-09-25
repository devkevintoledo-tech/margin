/**
 * The single vote affordance for both posts and threads.
 *
 * §24: voting must not visually dominate — both arrows stay muted until hover,
 * and only the arrow the reader actually cast lights up. Three layouts, one
 * behaviour:
 *   `rail`   a full-height column on the left of a thread row
 *   `inline` a compact stack beside a post body
 *   `row`    a horizontal `↑ +42 ↓` for a DataTable score cell
 *
 * `onVote` receives the value to SET, not a delta: clicking the arrow already
 * cast sends 0, which clears the vote.
 */
function VoteControl({ score = 0, myVote = 0, onVote, disabled, pending, variant = 'inline' }) {
  const isRail = variant === 'rail'
  const isRow = variant === 'row'

  const cast = (value) => (e) => {
    // Thread rows wrap a <Link>; don't navigate on a vote.
    e.preventDefault()
    e.stopPropagation()
    if (!disabled && !pending) onVote(myVote === value ? 0 : value)
  }

  // Sign is carried in text, not colour alone. ASCII hyphen, never U+2212.
  const label = score > 0 ? `+${score}` : String(score)

  const scoreTone =
    score > 0 ? 'text-ok' : score < 0 ? 'text-danger' : 'text-ink-dim'

  const arrow = (active, tone) =>
    `leading-none text-xs transition-colors duration-fast disabled:cursor-default ${
      active ? tone : 'text-ink-muted hover:text-ink'
    } ${isRow ? 'opacity-0 group-hover:opacity-100 focus:opacity-100' : ''}`

  const wrapper = isRail
    ? 'flex flex-col items-center justify-center gap-1 shrink-0 w-14 border-r border-line py-4 hover:bg-highlight transition-colors duration-fast'
    : isRow
      ? 'group inline-flex items-center gap-1 justify-end tabular-nums'
      : 'flex flex-col items-center gap-0.5 shrink-0 w-8 pt-0.5'

  return (
    <div className={wrapper}>
      <button
        onClick={cast(1)}
        disabled={disabled || pending}
        aria-label="Upvote"
        aria-pressed={myVote === 1}
        title={disabled ? 'Sign in to vote' : 'Upvote'}
        className={arrow(myVote === 1, 'text-ok')}
      >
        ↑
      </button>
      <span
        className={`font-medium leading-none tabular-nums ${scoreTone} ${
          isRail ? 'text-sm' : 'text-xs'
        }`}
      >
        {label}
      </span>
      <button
        onClick={cast(-1)}
        disabled={disabled || pending}
        aria-label="Downvote"
        aria-pressed={myVote === -1}
        title={disabled ? 'Sign in to vote' : 'Downvote'}
        className={arrow(myVote === -1, 'text-danger')}
      >
        ↓
      </button>
    </div>
  )
}

export default VoteControl
