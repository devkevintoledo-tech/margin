import { describe, it, expect, vi } from 'vitest'
import { useState } from 'react'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import ReasonField from './ReasonField'

function Harness({ kind = 'merge', initial = '', onSubmit = vi.fn() }) {
  const [value, setValue] = useState(initial)
  return (
    <form onSubmit={(e) => { e.preventDefault(); onSubmit(value) }}>
      <ReasonField kind={kind} value={value} onChange={setValue} />
    </form>
  )
}

describe('ReasonField', () => {
  it('labels the field Reason and offers the kind\'s presets', () => {
    render(<Harness kind="merge" />)
    expect(screen.getByLabelText('Reason').tagName).toBe('TEXTAREA')
    const chips = within(screen.getByRole('group', { name: 'Quick reasons' })).getAllByRole('button')
    expect(chips.map((c) => c.textContent)).toEqual(
      ['duplicate record', 'same book, different edition', 'translation of the same book'])
  })

  it('fills the field with a chip and marks that chip pressed', async () => {
    render(<Harness kind="merge" />)
    const chip = screen.getByRole('button', { name: 'duplicate record' })
    expect(chip).toHaveAttribute('aria-pressed', 'false')
    await userEvent.click(chip)
    expect(screen.getByLabelText('Reason')).toHaveValue('duplicate record')
    expect(chip).toHaveAttribute('aria-pressed', 'true')
    // Pressed shows in the text decoration as well as the colour.
    expect(chip).toHaveClass('underline')
    expect(screen.getByRole('button', { name: 'same book, different edition' })).toHaveAttribute('aria-pressed', 'false')
  })

  it('adds a chip to what was typed', async () => {
    render(<Harness kind="merge" />)
    await userEvent.type(screen.getByLabelText('Reason'), 'two OL ids for one book')
    await userEvent.click(screen.getByRole('button', { name: 'duplicate record' }))
    expect(screen.getByLabelText('Reason')).toHaveValue('duplicate record: two OL ids for one book')
  })

  it('still takes typing after a chip', async () => {
    render(<Harness kind="merge" />)
    await userEvent.click(screen.getByRole('button', { name: 'duplicate record' }))
    await userEvent.type(screen.getByLabelText('Reason'), ': second OL id')
    expect(screen.getByLabelText('Reason')).toHaveValue('duplicate record: second OL id')
    expect(screen.getByRole('button', { name: 'duplicate record' })).toHaveAttribute('aria-pressed', 'true')
  })

  it('unpresses a chip once its text is edited away', async () => {
    render(<Harness kind="merge" />)
    await userEvent.click(screen.getByRole('button', { name: 'duplicate record' }))
    await userEvent.clear(screen.getByLabelText('Reason'))
    await userEvent.type(screen.getByLabelText('Reason'), 'duplicate records everywhere')
    expect(screen.getByRole('button', { name: 'duplicate record' })).toHaveAttribute('aria-pressed', 'false')
  })

  it('never submits the form it sits in', async () => {
    const onSubmit = vi.fn()
    render(<Harness kind="merge" onSubmit={onSubmit} />)
    for (const chip of within(screen.getByRole('group', { name: 'Quick reasons' })).getAllByRole('button')) {
      expect(chip).toHaveAttribute('type', 'button')
      await userEvent.click(chip)
    }
    expect(onSubmit).not.toHaveBeenCalled()
  })

  it('renders only the field for a kind without presets', () => {
    render(<Harness kind="unknown" />)
    expect(screen.queryByRole('group', { name: 'Quick reasons' })).toBeNull()
    expect(screen.getByLabelText('Reason')).toBeInTheDocument()
  })

  it('takes another id when a page has two reason fields', () => {
    render(<ReasonField kind="move" value="" onChange={vi.fn()} id="batch-reason" />)
    expect(screen.getByLabelText('Reason')).toHaveAttribute('id', 'batch-reason')
  })
})
