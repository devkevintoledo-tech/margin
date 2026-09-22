/**
 * The single vote affordance for both posts and threads.
 *
 * §24: voting must not visually dominate — both arrows stay muted until hover,
 * and only the arrow the reader actually cast lights up. Two layouts, one
 * behaviour:
 *   `rail`   a full-height column on the left of a thread row
 *   `inline` a compact stack beside a post body
 *
 * `onVote` receives the value to SET, not a delta: clicking the arrow already
 * cast sends 0, which clears the vote.
 */
function VoteControl({ score = 0, myVote = 0, onVote, disabled, pending, variant = 'inline' }) {
  const isRail = variant === 'rail'

  const cast = (value) => (e) => {
    // Thread rows wrap a <Link>; don't navigate on a vote.
    e.preventDefault()
    e.stopPropagation()
    if (!disabled && !pending) onVote(myVote === value ? 0 : value)
  }

  const arrow = (active) =>
    `leading-none text-xs transition-colors duration-fast disabled:cursor-default ${
      active ? 'text-accent-ink' : 'text-ink-muted hover:text-accent-ink'
    }`

  return (
    <div
      className={
        isRail
          ? 'flex flex-col items-center justify-center gap-1 shrink-0 w-14 border-r border-line py-4 hover:bg-raised transition-colors duration-fast'
          : 'flex flex-col items-center gap-0.5 shrink-0 w-8 pt-0.5'
      }
    >
      <button
        onClick={cast(1)}
        disabled={disabled || pending}
        aria-label="Upvote"
        aria-pressed={myVote === 1}
        title={disabled ? 'Sign in to vote' : 'Upvote'}
        className={arrow(myVote === 1)}
      >
        ↑
      </button>
      <span
        className={`text-accent-ink font-semibold leading-none tabular-nums ${
          isRail ? 'text-sm' : 'text-xs'
        }`}
      >
        {score}
      </span>
      <button
        onClick={cast(-1)}
        disabled={disabled || pending}
        aria-label="Downvote"
        aria-pressed={myVote === -1}
        title={disabled ? 'Sign in to vote' : 'Downvote'}
        className={arrow(myVote === -1)}
      >
        ↓
      </button>
    </div>
  )
}

export default VoteControl
