import { describe, it, expect, vi } from 'vitest'
import { fireEvent, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import MergePreview from './MergePreview'

const side = (over) => ({
  id: 'w1', title: 'Dune', author: 'Brian Herbert', first_publish_year: 1999, cover_url: null,
  description: null, edition_count: 2, thread_count: 2, shelf_count: 1, series_slug: 'dune-b1',
  series_name: null, ...over,
})
const PREVIEW = {
  source: side({}),
  target: side({ id: 'w2', author: 'Frank Herbert', first_publish_year: 1965, cover_url: 'https://x/dune.jpg',
                 description: 'Set on the desert planet Arrakis.', edition_count: 26, thread_count: 3,
                 shelf_count: 0, series_slug: 'dune', series_name: 'Dune Saga' }),
  threads: 2, shelves: 1, editions: 2,
}

describe('MergePreview', () => {
  it('labels each side by its role, not only by colour', () => {
    render(<MergePreview preview={PREVIEW} onSwap={vi.fn()} />)
    const group = screen.getByRole('group', { name: 'Merge preview' })
    const away = within(group).getByRole('region', { name: 'merges away: Dune' })
    const kept = within(group).getByRole('region', { name: 'survives: Dune' })
    expect(within(away).getByText('merges away')).toBeInTheDocument()
    expect(within(away).getByText('Brian Herbert')).toBeInTheDocument()
    expect(within(away).getByText('1999')).toBeInTheDocument()
    expect(within(kept).getByText('Frank Herbert')).toBeInTheDocument()
    expect(within(kept).getByText('1965')).toBeInTheDocument()
  })

  it('shows what each book carries: editions, threads, shelves, series, blurb', () => {
    render(<MergePreview preview={PREVIEW} onSwap={vi.fn()} />)
    const away = screen.getByRole('region', { name: /^merges away/ })
    const kept = screen.getByRole('region', { name: /^survives/ })
    expect(within(away).getByText('no series')).toBeInTheDocument()
    expect(within(kept).getByText('Dune Saga')).toHaveClass('text-path')
    expect(within(kept).getByText('26')).toBeInTheDocument()
    expect(within(kept).getByText('Set on the desert planet Arrakis.')).toBeInTheDocument()
    expect(within(away).getByText('editions').nextSibling).toHaveTextContent('2')
    expect(within(away).getByText('threads').nextSibling).toHaveTextContent('2')
    expect(within(away).getByText('shelves').nextSibling).toHaveTextContent('1')
  })

  it('states what moves, agreeing in number', () => {
    render(<MergePreview preview={{ ...PREVIEW, threads: 1, shelves: 2, editions: 0 }} />)
    expect(screen.getByText('1 thread, 2 shelf entries and 0 editions move to the survivor.')).toBeInTheDocument()
  })

  it('shows the cover when there is one and the title when there is none or it fails', () => {
    render(<MergePreview preview={PREVIEW} onSwap={vi.fn()} />)
    const kept = screen.getByRole('region', { name: /^survives/ })
    const img = within(kept).getByRole('img', { name: 'Dune' })
    expect(img).toHaveAttribute('src', 'https://x/dune.jpg')
    const away = screen.getByRole('region', { name: /^merges away/ })
    expect(within(away).queryByRole('img')).toBeNull()
    fireEvent.error(img)
    expect(within(kept).queryByRole('img')).toBeNull()
  })

  it('swaps on request, and offers no swap when the caller gives none', async () => {
    const onSwap = vi.fn()
    const { unmount } = render(<MergePreview preview={PREVIEW} onSwap={onSwap} />)
    await userEvent.click(screen.getByRole('button', { name: 'swap which book survives' }))
    expect(onSwap).toHaveBeenCalledTimes(1)
    unmount()
    render(<MergePreview preview={PREVIEW} />)
    expect(screen.queryByRole('button')).toBeNull()
  })
})
