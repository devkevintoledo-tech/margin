import { describe, it, expect, vi, beforeEach } from 'vitest'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

vi.mock('../api/client', () => ({ default: { get: vi.fn(), post: vi.fn() } }))

import client from '../api/client'
import { errorMessage } from '../api/errors'
import LibrarianPanel from './LibrarianPanel'

const SERIES = { id: 's1', name: 'Dune', slug: 'dune', kind: 'series' }
const BOOK = { id: 'w1', title: 'Dune', author: 'Brian Herbert', position: null }
const CORRECTION = { id: 'c1', op: 'set_series', exportable: true, undoable: true, room_slug: 'dune' }

const OTHER = { id: 'w2', title: 'Dune', author: 'Frank Herbert' }
const THIRD = { id: 'w3', title: 'Dune', author: 'Kevin J. Anderson' }
const side = (book, over = {}) => ({
  id: book.id, title: book.title, author: book.author, first_publish_year: null, cover_url: null,
  description: null, edition_count: 1, thread_count: 0, shelf_count: 0, series_slug: `s-${book.id}`,
  series_name: null, ...over,
})
const BY_ID = { w1: BOOK, w2: OTHER, w3: THIRD }

/** Search answers `works`; a merge preview answers for whichever pair it is asked about. */
function mockGets(works = [OTHER, THIRD], previewError = null) {
  client.get.mockImplementation((url, config) => {
    if (url === '/works/search') return Promise.resolve({ data: works })
    const preview = url.match(/^\/librarian\/works\/(\w+)\/merge-preview$/)
    if (preview) {
      if (previewError) return Promise.reject(previewError)
      const [from, to] = [BY_ID[preview[1]], BY_ID[config.params.into]]
      return Promise.resolve({ data: {
        source: side(from), target: side(to), threads: from.id === 'w1' ? 3 : 1, shelves: 0, editions: 1 } })
    }
    return Promise.resolve({ data: [] })
  })
}

async function pickToKeep(name) {
  await userEvent.type(screen.getByLabelText('Find the book to keep'), 'dune')
  await userEvent.click(await screen.findByRole('radio', { name }))
}

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
    mockGets([OTHER])
    client.post
      .mockRejectedValueOnce({ response: { status: 422, data: { detail: {
        message: 'Merging Dune into Dune cannot be undone.', consequences: { threads: 3, shelves: 12, editions: 4 } } } } })
      .mockResolvedValueOnce({ data: CORRECTION })
    const onDone = renderPanel({ kind: 'merge', work: BOOK })

    await userEvent.type(screen.getByLabelText('Find the book to keep'), 'dune')
    await userEvent.click(await screen.findByRole('radio', { name: /Frank Herbert/ }))
    await screen.findByRole('group', { name: 'Merge preview' })
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

  it('sends a one-click reason as the text it shows', async () => {
    client.post.mockResolvedValue({ data: CORRECTION })
    const onDone = renderPanel({ kind: 'dissolve' })
    const submit = screen.getByRole('button', { name: 'Dissolve' })
    expect(submit).toBeDisabled()
    await userEvent.click(screen.getByRole('button', { name: 'publisher imprint' }))
    expect(submit).toBeEnabled()
    await userEvent.click(submit)
    await waitFor(() => expect(onDone).toHaveBeenCalledWith(CORRECTION))
    expect(client.post).toHaveBeenCalledWith('/librarian/series/s1/dissolve', { reason: 'publisher imprint' })
  })

  it('offers the presets of the action it is doing', () => {
    renderPanel({ kind: 'remove', work: BOOK })
    const group = screen.getByRole('group', { name: 'Quick reasons' })
    expect(within(group).getByRole('button', { name: 'not part of this series' })).toBeInTheDocument()
    expect(within(group).queryByRole('button', { name: 'duplicate record' })).toBeNull()
  })

  it('still starts with focus in a field, not on a chip', () => {
    renderPanel({ kind: 'dissolve' })
    expect(document.activeElement).toBe(screen.getByLabelText('Reason'))
  })

  it('a chip clears a refusal like typing does', async () => {
    client.post.mockRejectedValueOnce({ response: { status: 422, data: { detail: 'It is already called Dune.' } } })
    renderPanel({ kind: 'rename' })
    await userEvent.type(screen.getByLabelText('New name'), 'Dune')
    await userEvent.click(screen.getByRole('button', { name: 'fix spelling' }))
    await userEvent.click(screen.getByRole('button', { name: 'Rename' }))
    expect(await screen.findByText('It is already called Dune.')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'official series name' }))
    expect(screen.queryByText('It is already called Dune.')).toBeNull()
  })

  it('adds the picked book as a move into this series', async () => {
    client.get.mockResolvedValue({ data: [
      { id: 'w9', title: 'Dune Messiah', author: 'Frank Herbert', series: { slug: 'dune-messiah-x', name: 'Dune Messiah', kind: 'singleton' } },
    ] })
    client.post.mockResolvedValue({ data: CORRECTION })
    const onDone = renderPanel({ kind: 'add' })
    expect(screen.getByRole('dialog', { name: 'Add a book to Dune' })).toBeInTheDocument()
    const submit = screen.getByRole('button', { name: 'Add book' })
    expect(submit).toBeDisabled()

    await userEvent.type(screen.getByLabelText('Find the book to add'), 'messiah')
    await userEvent.click(await screen.findByRole('radio', { name: /Dune Messiah/ }))
    await userEvent.type(screen.getByLabelText('Position (optional)'), '2')
    expect(submit).toBeDisabled() // still no reason
    await userEvent.type(screen.getByLabelText('Reason'), 'book two')
    await userEvent.click(submit)

    await waitFor(() => expect(onDone).toHaveBeenCalledWith(CORRECTION))
    expect(client.post).toHaveBeenCalledWith('/librarian/works/w9/move',
      { reason: 'book two', series_id: 's1', position: 2 })
  })

  it('leaves the position out when none is given', async () => {
    client.get.mockResolvedValue({ data: [{ id: 'w9', title: 'Dune Messiah', author: 'Frank Herbert', series: null }] })
    client.post.mockResolvedValue({ data: CORRECTION })
    renderPanel({ kind: 'add' })
    await userEvent.type(screen.getByLabelText('Find the book to add'), 'messiah')
    await userEvent.click(await screen.findByRole('radio', { name: /Dune Messiah/ }))
    await userEvent.type(screen.getByLabelText('Reason'), 'book two')
    await userEvent.click(screen.getByRole('button', { name: 'Add book' }))
    await waitFor(() => expect(client.post).toHaveBeenCalledWith('/librarian/works/w9/move',
      { reason: 'book two', series_id: 's1' }))
  })

  it('warns before taking a book out of another real series', async () => {
    client.get.mockResolvedValue({ data: [
      { id: 'w7', title: 'Hunters of Dune', author: 'Brian Herbert',
        series: { slug: 'dune-chronicles', name: 'Dune Chronicles', kind: 'series' } },
    ] })
    renderPanel({ kind: 'add' })
    await userEvent.type(screen.getByLabelText('Find the book to add'), 'hunters')
    await userEvent.click(await screen.findByRole('radio', { name: /Hunters of Dune/ }))
    const warning = screen.getByText(/Adding it here takes it out of/)
    expect(warning).toHaveTextContent('Hunters of Dune is in Dune Chronicles now.')
    expect(warning).toHaveTextContent('with the threads tagged with it')
    await userEvent.type(screen.getByLabelText('Reason'), 'belongs here')
    expect(screen.getByRole('button', { name: 'Add book' })).toBeEnabled() // a warning, not a refusal
  })

  it('says nothing extra for a book on its own page', async () => {
    client.get.mockResolvedValue({ data: [
      { id: 'w9', title: 'Dune Messiah', author: 'Frank Herbert', series: { slug: 'dune-messiah-x', name: 'Dune Messiah', kind: 'singleton' } },
    ] })
    renderPanel({ kind: 'add' })
    await userEvent.type(screen.getByLabelText('Find the book to add'), 'messiah')
    await userEvent.click(await screen.findByRole('radio', { name: /Dune Messiah/ }))
    expect(screen.queryByText(/takes it out of/)).toBeNull()
    expect(screen.queryByText(/already in/)).toBeNull()
  })

  it('will not add a book that is already here', async () => {
    client.get.mockResolvedValue({ data: [
      { id: 'w1', title: 'Dune', author: 'Frank Herbert', series: { slug: 'dune', name: 'Dune', kind: 'series' } },
    ] })
    renderPanel({ kind: 'add' })
    await userEvent.type(screen.getByLabelText('Find the book to add'), 'dune')
    await userEvent.click(await screen.findByRole('radio', { name: /Frank Herbert/ }))
    await userEvent.type(screen.getByLabelText('Reason'), 'r')
    expect(screen.getByText(/is already in/)).toHaveTextContent('Dune is already in Dune.')
    expect(screen.getByRole('button', { name: 'Add book' })).toBeDisabled()
  })

  it('shows both books side by side once the other book is picked', async () => {
    mockGets()
    renderPanel({ kind: 'merge', work: BOOK })
    expect(screen.queryByRole('group', { name: 'Merge preview' })).toBeNull()
    await pickToKeep(/Frank Herbert/)
    const preview = await screen.findByRole('group', { name: 'Merge preview' })
    expect(within(preview).getByRole('region', { name: 'merges away: Dune' })).toHaveTextContent('Brian Herbert')
    expect(within(preview).getByRole('region', { name: 'survives: Dune' })).toHaveTextContent('Frank Herbert')
    expect(client.get).toHaveBeenCalledWith('/librarian/works/w1/merge-preview', { params: { into: 'w2' } })
  })

  it('swap makes the picked book the one that merges away', async () => {
    mockGets()
    client.post
      .mockRejectedValueOnce({ response: { status: 422, data: { detail: {
        message: 'm', consequences: { threads: 1, shelves: 0, editions: 1 } } } } })
      .mockResolvedValueOnce({ data: CORRECTION })
    const onDone = renderPanel({ kind: 'merge', work: BOOK })
    await pickToKeep(/Frank Herbert/)
    await userEvent.click(await screen.findByRole('button', { name: 'swap which book survives' }))
    const preview = await screen.findByRole('group', { name: 'Merge preview' })
    await waitFor(() => expect(within(preview).getByRole('region', { name: /^merges away/ })).toHaveTextContent('Frank Herbert'))
    expect(client.get).toHaveBeenCalledWith('/librarian/works/w2/merge-preview', { params: { into: 'w1' } })

    await userEvent.type(screen.getByLabelText('Reason'), 'same book')
    await userEvent.click(screen.getByRole('button', { name: 'Merge' }))
    expect(client.post).toHaveBeenCalledWith('/librarian/works/w2/merge',
      { reason: 'same book', into_work_id: 'w1', confirm: false })
    expect(await screen.findByText(/Frank Herbert\) will merge into/)).toHaveTextContent(/\(Brian Herbert\)/)
    await userEvent.click(screen.getByRole('button', { name: 'Confirm merge' }))
    await waitFor(() => expect(onDone).toHaveBeenCalledWith(CORRECTION))
    expect(client.post).toHaveBeenLastCalledWith('/librarian/works/w2/merge',
      { reason: 'same book', into_work_id: 'w1', confirm: true })
  })

  it('swapping after the counts came back asks again', async () => {
    mockGets()
    client.post.mockRejectedValue({ response: { status: 422, data: { detail: {
      message: 'm', consequences: { threads: 3, shelves: 0, editions: 1 } } } } })
    renderPanel({ kind: 'merge', work: BOOK })
    await pickToKeep(/Frank Herbert/)
    await screen.findByRole('group', { name: 'Merge preview' })
    await userEvent.type(screen.getByLabelText('Reason'), 'same book')
    await userEvent.click(screen.getByRole('button', { name: 'Merge' }))
    expect(await screen.findByRole('button', { name: 'Confirm merge' })).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: 'swap which book survives' }))
    expect(screen.queryByRole('button', { name: 'Confirm merge' })).toBeNull()
    await waitFor(() => expect(screen.getByRole('button', { name: 'Merge' })).toBeEnabled())
    await userEvent.click(screen.getByRole('button', { name: 'Merge' }))
    expect(client.post).toHaveBeenLastCalledWith('/librarian/works/w2/merge',
      { reason: 'same book', into_work_id: 'w1', confirm: false })
  })

  it('refuses to go on when the preview says a book is gone', async () => {
    mockGets([OTHER], { response: { status: 409, data: { detail: 'Dune was merged into another book; reload the page.' } } })
    renderPanel({ kind: 'merge', work: BOOK })
    await pickToKeep(/Frank Herbert/)
    expect(await screen.findByText('Dune was merged into another book; reload the page.')).toHaveClass('alert-danger')
    await userEvent.type(screen.getByLabelText('Reason'), 'same book')
    expect(screen.getByRole('button', { name: 'Merge' })).toBeDisabled()
  })

  it('picking another book resets the swap', async () => {
    mockGets()
    renderPanel({ kind: 'merge', work: BOOK })
    await pickToKeep(/Frank Herbert/)
    await userEvent.click(await screen.findByRole('button', { name: 'swap which book survives' }))
    await userEvent.click(screen.getByRole('radio', { name: /Kevin J. Anderson/ }))
    const preview = await screen.findByRole('group', { name: 'Merge preview' })
    await waitFor(() => expect(within(preview).getByRole('region', { name: /^survives/ })).toHaveTextContent('Kevin J. Anderson'))
    expect(client.get).toHaveBeenLastCalledWith('/librarian/works/w1/merge-preview', { params: { into: 'w3' } })
  })

  it('keeps focus on swap while the swapped preview loads, so the dialog keeps its keys', async () => {
    mockGets()
    renderPanel({ kind: 'merge', work: BOOK })
    await pickToKeep(/Frank Herbert/)
    const swapButton = await screen.findByRole('button', { name: 'swap which book survives' })
    await userEvent.click(swapButton)
    expect(document.activeElement).toBe(screen.getByRole('button', { name: 'swap which book survives' }))
    await waitFor(() => expect(screen.getByRole('region', { name: /^merges away/ })).toHaveTextContent('Frank Herbert'))
    expect(document.activeElement).toBe(screen.getByRole('button', { name: 'swap which book survives' }))
  })

  it('will not merge on the previous pair while the swapped preview loads', async () => {
    let answer
    mockGets()
    const answered = client.get.getMockImplementation()
    renderPanel({ kind: 'merge', work: BOOK })
    await pickToKeep(/Frank Herbert/)
    await screen.findByRole('group', { name: 'Merge preview' })
    await userEvent.type(screen.getByLabelText('Reason'), 'same book')
    expect(screen.getByRole('button', { name: 'Merge' })).toBeEnabled()
    client.get.mockImplementation((url, config) =>
      url.endsWith('/merge-preview') ? new Promise((resolve) => { answer = () => resolve(answered(url, config)) }) : answered(url, config))
    await userEvent.click(screen.getByRole('button', { name: 'swap which book survives' }))
    expect(screen.getByRole('button', { name: 'Merge' })).toBeDisabled()
    answer()
    await waitFor(() => expect(screen.getByRole('button', { name: 'Merge' })).toBeEnabled())
  })

  it('keeps focus on swap when swapping from the confirm step', async () => {
    mockGets()
    client.post.mockRejectedValue({ response: { status: 422, data: { detail: {
      message: 'm', consequences: { threads: 3, shelves: 0, editions: 1 } } } } })
    renderPanel({ kind: 'merge', work: BOOK })
    await pickToKeep(/Frank Herbert/)
    await screen.findByRole('group', { name: 'Merge preview' })
    await userEvent.type(screen.getByLabelText('Reason'), 'same book')
    await userEvent.click(screen.getByRole('button', { name: 'Merge' }))
    await userEvent.click(await screen.findByRole('button', { name: 'swap which book survives' }))
    expect(screen.queryByRole('button', { name: 'Confirm merge' })).toBeNull()
    expect(document.activeElement).toBe(screen.getByRole('button', { name: 'swap which book survives' }))
  })

  it('cannot swap while a merge request is in flight', async () => {
    mockGets()
    let refuse
    client.post.mockImplementationOnce(() => new Promise((_, reject) => { refuse = reject }))
    renderPanel({ kind: 'merge', work: BOOK })
    await pickToKeep(/Frank Herbert/)
    await screen.findByRole('group', { name: 'Merge preview' })
    await userEvent.type(screen.getByLabelText('Reason'), 'same book')
    await userEvent.click(screen.getByRole('button', { name: 'Merge' }))
    expect(screen.getByRole('button', { name: 'swap which book survives' })).toBeDisabled()
    refuse({ response: { status: 422, data: { detail: { message: 'm', consequences: { threads: 3, shelves: 0, editions: 1 } } } } })
    expect(await screen.findByRole('button', { name: 'Confirm merge' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'swap which book survives' })).toBeEnabled()
  })

  it('drops counts that answered a pair the form no longer shows', async () => {
    mockGets()
    let refuse
    client.post.mockImplementationOnce(() => new Promise((_, reject) => { refuse = reject }))
    renderPanel({ kind: 'merge', work: BOOK })
    await pickToKeep(/Frank Herbert/)
    await screen.findByRole('group', { name: 'Merge preview' })
    await userEvent.type(screen.getByLabelText('Reason'), 'same book')
    await userEvent.click(screen.getByRole('button', { name: 'Merge' }))
    await userEvent.click(screen.getByRole('radio', { name: /Kevin J. Anderson/ }))
    refuse({ response: { status: 422, data: { detail: { message: 'm', consequences: { threads: 3, shelves: 0, editions: 1 } } } } })
    await waitFor(() => expect(client.post).toHaveBeenCalledTimes(1))
    await new Promise((r) => setTimeout(r, 0))
    expect(screen.queryByRole('button', { name: 'Confirm merge' })).toBeNull()
    expect(screen.getByRole('radio', { name: /Kevin J. Anderson/ })).toBeChecked()
  })
})
