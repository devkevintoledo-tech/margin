import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import VoteControl from './VoteControl'

describe('VoteControl', () => {
  it('sends 1 when upvoting from neutral', async () => {
    const onVote = vi.fn()
    render(<VoteControl score={3} myVote={0} onVote={onVote} />)
    await userEvent.click(screen.getByRole('button', { name: /upvote/i }))
    expect(onVote).toHaveBeenCalledWith(1)
  })

  it('sends 0 when clicking the arrow already cast', async () => {
    const onVote = vi.fn()
    render(<VoteControl score={4} myVote={1} onVote={onVote} />)
    await userEvent.click(screen.getByRole('button', { name: /upvote/i }))
    expect(onVote).toHaveBeenCalledWith(0)
  })

  it('sends -1 when downvoting', async () => {
    const onVote = vi.fn()
    render(<VoteControl score={0} myVote={0} onVote={onVote} />)
    await userEvent.click(screen.getByRole('button', { name: /downvote/i }))
    expect(onVote).toHaveBeenCalledWith(-1)
  })

  it('marks the cast arrow as pressed and shows the score', () => {
    render(<VoteControl score={-2} myVote={-1} onVote={() => {}} />)
    expect(screen.getByRole('button', { name: /downvote/i })).toHaveAttribute(
      'aria-pressed',
      'true',
    )
    expect(screen.getByText('-2')).toBeInTheDocument()
  })

  it('does not call onVote when disabled', async () => {
    const onVote = vi.fn()
    render(<VoteControl score={0} myVote={0} onVote={onVote} disabled />)
    await userEvent.click(screen.getByRole('button', { name: /upvote/i }))
    expect(onVote).not.toHaveBeenCalled()
  })
})
