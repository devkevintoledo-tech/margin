import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

vi.mock('../api/client', () => ({ default: { get: vi.fn(), post: vi.fn() } }))

import client from '../api/client'
import { errorMessage } from '../api/errors'
import LibrarianPanel from './LibrarianPanel'

const SERIES = { id: 's1', name: 'Dune', slug: 'dune', kind: 'series' }
const BOOK = { id: 'w1', title: 'Dune', author: 'Brian Herbert', position: null }
const CORRECTION = { id: 'c1', op: 'set_series', exportable: true, undoable: true, room_slug: 'dune' }

function renderPanel(action, onDone = vi.fn()) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={qc}>
      <LibrarianPanel action={{ series: SERIES, ...action }} onClose={vi.fn()} onDone={onDone} />
    </QueryClientProvider>,
  )
  return onDone
}

beforeEach(() => vi.clearAllMocks())

describe('LibrarianPanel', () => {
  it('will not submit without a reason', async () => {
    renderPanel({ kind: 'rename' })
    const submit = screen.getByRole('button', { name: 'Rename' })
    await userEvent.type(screen.getByLabelText('New name'), 'Dune Chronicles')
    expect(submit).toBeDisabled()
    await userEvent.type(screen.getByLabelText('Reason'), '   ')
    expect(submit).toBeDisabled()
    await userEvent.type(screen.getByLabelText('Reason'), 'the usual name')
    expect(submit).toBeEnabled()
  })

  it('confirms a merge with the counts the server returned', async () => {
    client.get.mockResolvedValue({ data: [{ id: 'w2', title: 'Dune', author: 'Frank Herbert' }] })
    client.post
      .mockRejectedValueOnce({ response: { status: 422, data: { detail: {
        message: 'Merging Dune into Dune cannot be undone.', consequences: { threads: 3, shelves: 12, editions: 4 } } } } })
      .mockResolvedValueOnce({ data: CORRECTION })
    const onDone = renderPanel({ kind: 'merge', work: BOOK })

    await userEvent.type(screen.getByLabelText('Find the book to keep'), 'dune')
    await userEvent.click(await screen.findByRole('radio', { name: /Frank Herbert/ }))
    await userEvent.type(screen.getByLabelText('Reason'), 'same book')
    await userEvent.click(screen.getByRole('button', { name: 'Merge' }))

    expect(await screen.findByText(/3 threads and 12 shelf entries move/)).toBeInTheDocument()
    expect(screen.getByText(/This cannot be undone/)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Confirm merge' }))
    await waitFor(() => expect(onDone).toHaveBeenCalledWith(CORRECTION))
    expect(client.post).toHaveBeenLastCalledWith('/librarian/works/w1/merge',
      { reason: 'same book', into_work_id: 'w2', confirm: true })
  })

  it('moves a book into a series it names', async () => {
    client.get.mockResolvedValue({ data: [] })
    client.post.mockResolvedValue({ data: CORRECTION })
    renderPanel({ kind: 'move', work: BOOK })
    await userEvent.type(screen.getByLabelText('Find a series'), 'Legends of Dune')
    await userEvent.click(await screen.findByRole('radio', { name: 'new series: Legends of Dune' }))
    await userEvent.type(screen.getByLabelText('Position (optional)'), '1')
    await userEvent.type(screen.getByLabelText('Reason'), 'prequel trilogy')
    await userEvent.click(screen.getByRole('button', { name: 'Move' }))
    await waitFor(() => expect(client.post).toHaveBeenCalledWith('/librarian/works/w1/move',
      { reason: 'prequel trilogy', new_series_name: 'Legends of Dune', position: 1 }))
  })

  it('splits the checked editions', async () => {
    client.get.mockResolvedValue({ data: [
      { id: 'e1', title: 'Dune', published_year: 1965, language: 'en', source: 'openlibrary' },
      { id: 'e2', title: 'Dune Messiah', published_year: 1969, language: 'en', source: 'openlibrary' },
    ] })
    client.post.mockRejectedValueOnce({ response: { status: 422, data: { detail: {
      message: 'm', consequences: { editions: 1, remaining: 1 } } } } })
    renderPanel({ kind: 'split', work: BOOK })
    await userEvent.click(await screen.findByRole('checkbox', { name: /Dune Messiah/ }))
    await userEvent.type(screen.getByLabelText('Reason'), 'sequel')
    await userEvent.click(screen.getByRole('button', { name: 'Split' }))
    expect(await screen.findByText(/1 edition of/)).toBeInTheDocument()
    expect(client.post).toHaveBeenCalledWith('/librarian/works/w1/split',
      { reason: 'sequel', edition_ids: ['e2'], confirm: false })
  })

  it('reads a message out of an object detail', () => {
    expect(errorMessage({ response: { data: { detail: { message: 'Nope.', consequences: {} } } } })).toBe('Nope.')
  })
})
