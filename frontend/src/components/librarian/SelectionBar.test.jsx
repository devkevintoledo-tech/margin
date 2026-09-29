import { describe, it, expect, vi } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import SelectionBar from './SelectionBar'

const A = { id: 'w1', title: 'Dune', author: 'Brian Herbert' }
const B = { id: 'w2', title: 'Dune', author: 'Frank Herbert' }
const C = { id: 'w3', title: 'Dune Messiah', author: 'Frank Herbert' }

describe('SelectionBar', () => {
  it('enables merge only for exactly two, and says why otherwise', async () => {
    const onMerge = vi.fn()
    const { rerender } = render(<SelectionBar selected={[A]} onMerge={onMerge} onClear={vi.fn()} />)
    const merge = screen.getByRole('button', { name: 'merge…' })
    expect(merge).toBeDisabled()
    expect(merge).toHaveAccessibleDescription('select exactly two books to merge')

    rerender(<SelectionBar selected={[A, B, C]} onMerge={onMerge} onClear={vi.fn()} />)
    expect(screen.getByRole('button', { name: 'merge…' })).toBeDisabled()

    rerender(<SelectionBar selected={[A, B]} onMerge={onMerge} onClear={vi.fn()} />)
    expect(screen.getByRole('button', { name: 'merge…' })).toBeEnabled()
    expect(screen.queryByText('select exactly two books to merge')).toBeNull()
    await userEvent.click(screen.getByRole('button', { name: 'merge…' }))
    expect(onMerge).toHaveBeenCalledTimes(1)
  })

  it('announces the count and lists every pick by title and author', () => {
    render(<SelectionBar selected={[A, C]} onMerge={vi.fn()} onClear={vi.fn()} />)
    expect(screen.getByRole('status')).toHaveTextContent('2 selected')
    const items = within(screen.getByRole('list', { name: 'Selected books' })).getAllByRole('listitem')
    expect(items.map((li) => li.textContent)).toEqual(['Dune Brian Herbert', 'Dune Messiah Frank Herbert'])
  })

  it('clears, and offers nothing to clear when empty', async () => {
    const onClear = vi.fn()
    const { rerender } = render(<SelectionBar selected={[A]} onMerge={vi.fn()} onClear={onClear} />)
    await userEvent.click(screen.getByRole('button', { name: 'clear' }))
    expect(onClear).toHaveBeenCalledTimes(1)
    rerender(<SelectionBar selected={[]} onMerge={vi.fn()} onClear={onClear} />)
    expect(screen.queryByRole('button', { name: 'clear' })).toBeNull()
    expect(screen.getByRole('status')).toHaveTextContent('0 selected')
  })
})
