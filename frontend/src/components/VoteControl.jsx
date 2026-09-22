/**
 * The single vote affordance for both posts and threads.
 *
 * §24: voting must not visually dominate — the arrow stays muted until hover,
 * and only the count carries accent color. Two layouts, one behaviour:
 *   `rail`   a full-height column on the left of a thread row
 *   `inline` a compact stack beside a post body
 *
 * Downvotes are deliberately absent: the API only exposes an increment-only
 * upvote today (see ROADMAP Phase 1, "vote toggling / downvotes").
 */
function VoteControl({ count = 0, onVote, disabled, pending, variant = 'inline' }) {
  const isRail = variant === 'rail'

  return (
    <button
      onClick={onVote}
      disabled={disabled || pending}
      title={disabled ? 'Sign in to upvote' : 'Upvote'}
      className={
        isRail
          ? 'flex flex-col items-center justify-center gap-1 shrink-0 w-14 border-r border-line py-4 group/up hover:bg-raised transition-colors duration-fast disabled:cursor-default disabled:hover:bg-transparent'
          : 'flex flex-col items-center gap-0.5 shrink-0 w-8 pt-0.5 group/up disabled:cursor-default'
      }
    >
      <span className="text-ink-muted group-hover/up:text-accent-ink transition-colors duration-fast text-xs leading-none">
        ↑
      </span>
      <span className={`text-accent-ink font-semibold leading-none tabular-nums ${isRail ? 'text-sm' : 'text-xs'}`}>
        {count}
      </span>
    </button>
  )
}

export default VoteControl
