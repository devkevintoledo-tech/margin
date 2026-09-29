import { describe, it, expect, vi, beforeEach } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

vi.mock('../api/client', () => ({ default: { get: vi.fn(), post: vi.fn() } }))

import client from '../api/client'
import { errorMessage } from '../api/errors'
import LibrarianPanel from './LibrarianPanel'

const SERIES = { id: 's1', name: 'Dune', slug: 'dune', kind: 'series' }
const BOOK = { id: 'w1', title: 'Dune', author: 'Brian Herbert', position: null }
const CORRECTION = { id: 'c1', op: 'set_series', exportable: true, undoable: true, room_slug: 'dune' }

function renderPanel(action, onDone = vi.fn(), { qc = new QueryClient({ defaultOptions: { queries: { retry: false } } }), onClose = vi.fn() } = {}) {
  render(
    <QueryClientProvider client={qc}>
      <LibrarianPanel action={{ series: SERIES, ...action }} onClose={onClose} onDone={onDone} />
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

  it('does not carry the old position into a move', async () => {
    client.get.mockResolvedValue({ data: [] })
    renderPanel({ kind: 'move', work: { ...BOOK, position: 3 } })
    expect(screen.getByLabelText('Position (optional)')).toHaveValue(null)
  })

  it('searches for the book to keep once typing pauses, not on every keystroke', async () => {
    client.get.mockResolvedValue({ data: [] })
    renderPanel({ kind: 'merge', work: BOOK })
    await userEvent.type(screen.getByLabelText('Find the book to keep'), 'dune messiah')
    await waitFor(() => expect(client.get).toHaveBeenCalledWith('/works/search', { params: { q: 'dune messiah' } }))
    const searches = client.get.mock.calls.filter(([url]) => url === '/works/search')
    expect(searches).toHaveLength(1)
  })

  it('closes on Escape and starts with focus inside the dialog', async () => {
    const onClose = vi.fn()
    renderPanel({ kind: 'dissolve' }, vi.fn(), { onClose })
    expect(screen.getByRole('dialog').contains(document.activeElement)).toBe(true)
    fireEvent.keyDown(document.activeElement, { key: 'Escape' })
    expect(onClose).toHaveBeenCalled()
  })

  it('marks every cached query stale after a fix, since a fix can move a book anywhere', async () => {
    client.post.mockResolvedValue({ data: CORRECTION })
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    qc.setQueryData(['works', 'search', 'dune'], [])
    qc.setQueryData(['threads', 't1'], {})
    renderPanel({ kind: 'dissolve' }, vi.fn(), { qc })
    await userEvent.type(screen.getByLabelText('Reason'), 'an imprint')
    await userEvent.click(screen.getByRole('button', { name: 'Dissolve' }))
    await waitFor(() => expect(qc.getQueryState(['works', 'search', 'dune']).isInvalidated).toBe(true))
    expect(qc.getQueryState(['threads', 't1']).isInvalidated).toBe(true)
  })

  it('accepts any catalog position, not only halves', () => {
    renderPanel({ kind: 'position', work: { ...BOOK, position: 1.25 } })
    expect(screen.getByLabelText('Position (blank clears)')).toHaveAttribute('step', 'any')
  })

  it('clears a refusal once the librarian edits the form', async () => {
    client.post.mockRejectedValueOnce({ response: { status: 422, data: { detail: 'It is already called Dune.' } } })
    renderPanel({ kind: 'rename' })
    await userEvent.type(screen.getByLabelText('New name'), 'Dune')
    await userEvent.type(screen.getByLabelText('Reason'), 'r')
    await userEvent.click(screen.getByRole('button', { name: 'Rename' }))
    expect(await screen.findByText('It is already called Dune.')).toBeInTheDocument()
    await userEvent.type(screen.getByLabelText('New name'), ' Saga')
    expect(screen.queryByText('It is already called Dune.')).toBeNull()
  })

  it('agrees with the number of editions it names', async () => {
    client.get.mockResolvedValue({ data: [
      { id: 'e1', title: 'Dune', source: 'openlibrary' },
      { id: 'e2', title: 'Dune Messiah', source: 'openlibrary' },
      { id: 'e3', title: 'Children of Dune', source: 'openlibrary' },
    ] })
    client.post.mockRejectedValueOnce({ response: { status: 422, data: { detail: {
      message: 'm', consequences: { editions: 2, remaining: 1 } } } } })
    renderPanel({ kind: 'split', work: BOOK })
    await userEvent.click(await screen.findByRole('checkbox', { name: /Dune Messiah/ }))
    await userEvent.click(screen.getByRole('checkbox', { name: /Children of Dune/ }))
    await userEvent.type(screen.getByLabelText('Reason'), 'sequels')
    await userEvent.click(screen.getByRole('button', { name: 'Split' }))
    expect(await screen.findByText(/2 editions of/)).toHaveTextContent(/become a book of their own; 1 stays/)
  })

  it('explains why a book with one edition cannot be split', async () => {
    client.get.mockResolvedValue({ data: [{ id: 'e1', title: 'Dune', source: 'openlibrary' }] })
    renderPanel({ kind: 'split', work: BOOK })
    expect(await screen.findByText(/needs at least two editions/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Split' })).toBeDisabled()
  })

  it('keeps Tab inside the dialog and gives focus back on close', async () => {
    const opener = document.createElement('button')
    document.body.appendChild(opener)
    opener.focus()
    const qc = new QueryClient()
    const { unmount } = render(
      <QueryClientProvider client={qc}>
        <LibrarianPanel action={{ series: SERIES, kind: 'dissolve' }} onClose={vi.fn()} onDone={vi.fn()} />
      </QueryClientProvider>,
    )
    const dialog = screen.getByRole('dialog')
    for (let i = 0; i < 6; i++) {
      await userEvent.tab()
      expect(dialog.contains(document.activeElement)).toBe(true)
    }
    await userEvent.tab({ shift: true })
    expect(dialog.contains(document.activeElement)).toBe(true)
    unmount()
    expect(document.activeElement).toBe(opener)
    opener.remove()
  })
})
