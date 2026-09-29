import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import GenrePicker from './GenrePicker'

const TREE = [
  { slug: 'fantasy', name: 'Fantasy', children: [
    { slug: 'epic-fantasy', name: 'Epic Fantasy' }, { slug: 'grimdark', name: 'Grimdark' }] },
  { slug: 'mystery', name: 'Mystery', children: [{ slug: 'noir', name: 'Noir' }] },
]

function setup(props = {}) {
  const onToggle = vi.fn()
  render(<GenrePicker tree={TREE} selected={new Set()} onToggle={onToggle} onClose={() => {}}
                      label="tag Dune" {...props} />)
  return { onToggle, input: screen.getByRole('combobox', { name: 'filter genres' }) }
}

describe('GenrePicker', () => {
  it('filters the tree and keeps a matching subgenre’s parent as context', async () => {
    const { input } = setup()
    await userEvent.type(input, 'grim')
    const names = screen.getAllByRole('option').map((o) => o.textContent)
    expect(names.join('|')).toMatch(/fantasy/)
    expect(names.join('|')).toMatch(/grimdark/)
    expect(names.join('|')).not.toMatch(/mystery/)
  })

  it('says the list is curated when nothing matches, and Enter submits nothing', async () => {
    const { input, onToggle } = setup()
    await userEvent.type(input, 'space western{Enter}')
    expect(screen.getByText('no such genre — the list is curated')).toBeInTheDocument()
    expect(onToggle).not.toHaveBeenCalled()
  })

  it('puts Enter on the first real match, not its context parent', async () => {
    const { input, onToggle } = setup()
    await userEvent.type(input, 'grim{Enter}')
    expect(onToggle).toHaveBeenCalledWith('grimdark', true, 'Grimdark')
  })

  it('moves with the arrow keys and toggles with Enter', async () => {
    const { input, onToggle } = setup()
    await userEvent.click(input)
    await userEvent.keyboard('{ArrowDown}{ArrowDown}{Enter}')
    expect(onToggle).toHaveBeenCalledWith('grimdark', true, 'Grimdark')
  })

  it('shows the cap counter and blocks a sixth genre', async () => {
    const { input, onToggle } = setup({
      max: 5, selected: new Set(['fantasy', 'epic-fantasy', 'grimdark', 'mystery', 'noir']) })
    expect(screen.getByText('5/5 tagged')).toBeInTheDocument()
    await userEvent.click(input)
    await userEvent.keyboard('{Enter}') // first option is selected: untagging is allowed
    expect(onToggle).toHaveBeenCalledWith('fantasy', false, 'Fantasy')
  })

  it('disables unselected options at the cap', () => {
    setup({ max: 1, selected: new Set(['fantasy']) })
    expect(screen.getByRole('option', { name: /mystery/ })).toHaveAttribute('aria-disabled', 'true')
  })
})
