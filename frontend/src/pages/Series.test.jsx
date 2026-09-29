import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Routes, Route, useLocation } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

vi.mock('../api/client', () => ({ default: { get: vi.fn(), post: vi.fn(), put: vi.fn() } }))

import client from '../api/client'
import useAuthStore from '../store/auth'
import Series from './Series'

const SAGA = {
  slug: 'red-rising',
  name: 'Red Rising',
  kind: 'series',
  description: 'A boy from the mines.',
  works: [
    { id: 'b1', title: 'Red Rising', author: 'Pierce Brown', first_publish_year: 2014, cover_url: null, shelf_status: null },
    { id: 'b2', title: 'Golden Son', author: 'Pierce Brown', first_publish_year: 2015, cover_url: null, shelf_status: 'reading' },
  ],
}
const SINGLE = {
  slug: 'the-hobbit-a1b2c3',
  name: 'The Hobbit',
  kind: 'singleton',
  description: 'There and back again.',
  works: [{ id: 'h1', title: 'The Hobbit', author: 'J. R. R. Tolkien', first_publish_year: 1937, cover_url: null, shelf_status: null }],
}
const THREADS = [
  { id: 't1', title: 'Is Mustang right?', score: 3, my_vote: 0, post_count: 2, author: 'reader', created_at: new Date().toISOString(), work_id: 'b2' },
  { id: 't2', title: 'Best book?', score: 1, my_vote: 0, post_count: 0, author: 'reader', created_at: new Date().toISOString(), work_id: null },
]

function mockApi(series, threads = THREADS) {
  client.get.mockImplementation((url, config) => {
    if (url.endsWith('/threads')) {
      const workId = config?.params?.work_id
      return Promise.resolve({ data: workId ? threads.filter((t) => t.work_id === workId) : threads })
    }
    return Promise.resolve({ data: series })
  })
}

function Where() {
  const loc = useLocation()
  return <p data-testid="where">{loc.pathname}</p>
}

function renderPage(entry) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[entry]}>
        <Where />
        <Routes>
          <Route path="/series/:slug" element={<Series />} />
          <Route path="/series/:slug/threads/:threadId" element={<p>thread page</p>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  vi.clearAllMocks()
  // Signed in, so ShelfButton renders its status rather than a login link.
  useAuthStore.setState({ token: 't', user: { id: 'u1', username: 'reader' } })
})

describe('Series page', () => {
  it('lists its books in order with only a shelf control each', async () => {
    mockApi(SAGA)
    renderPage('/series/red-rising')
    const list = await screen.findByRole('list', { name: 'Books in this series' })
    const rows = within(list).getAllByRole('listitem')
    expect(rows.map((r) => within(r).getByRole('heading').textContent)).toEqual(['Red Rising', 'Golden Son'])
    // Rows are not links to a book page; the only control is the shelf button.
    rows.forEach((r) => expect(within(r).queryByRole('link', { name: /red rising|golden son/i })).toBeNull())
    expect(within(rows[1]).getByText('reading')).toBeInTheDocument()
  })

  it('shows one description for the series', async () => {
    mockApi(SAGA)
    renderPage('/series/red-rising')
    expect(await screen.findByText('A boy from the mines.')).toBeInTheDocument()
  })

  it('filters the discussion by book', async () => {
    mockApi(SAGA)
    renderPage('/series/red-rising')
    expect(await screen.findByText('Best book?')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Golden Son' }))
    await waitFor(() => expect(screen.queryByText('Best book?')).not.toBeInTheDocument())
    expect(screen.getByText('Is Mustang right?')).toBeInTheDocument()
    expect(client.get).toHaveBeenCalledWith('/series/red-rising/threads', { params: { work_id: 'b2' } })
  })

  it('marks the active book filter by more than colour', async () => {
    mockApi(SAGA)
    renderPage('/series/red-rising')
    const group = await screen.findByRole('group', { name: 'Filter by book' })
    const all = within(group).getByRole('button', { name: 'all' })
    const gold = within(group).getByRole('button', { name: 'Golden Son' })
    expect(all).toHaveClass('underline')
    expect(gold).not.toHaveClass('underline')
    await userEvent.click(gold)
    expect(gold).toHaveClass('underline')
    expect(all).not.toHaveClass('underline')
  })

  it('highlights the book named by ?book=', async () => {
    mockApi(SAGA)
    renderPage('/series/red-rising?book=b2')
    const list = await screen.findByRole('list', { name: 'Books in this series' })
    const [first, second] = within(list).getAllByRole('listitem')
    expect(second).toHaveAttribute('aria-current', 'true')
    expect(first).not.toHaveAttribute('aria-current')
  })

  it('shows each book\'s place in the series', async () => {
    mockApi({ ...SAGA, works: [{ ...SAGA.works[0], position: 1 }, { ...SAGA.works[1], position: 2.5 }] })
    renderPage('/series/red-rising')
    const list = await screen.findByRole('list', { name: 'Books in this series' })
    const [first, second] = within(list).getAllByRole('listitem')
    expect(within(first).getByText('#1')).toBeInTheDocument()
    expect(within(second).getByText('#2.5')).toBeInTheDocument()
  })

  it('shows no position when the catalog has none', async () => {
    mockApi(SAGA)
    renderPage('/series/red-rising')
    const list = await screen.findByRole('list', { name: 'Books in this series' })
    expect(within(list).queryByText(/^#/)).toBeNull()
  })

  it('groups books under their sub-series heading', async () => {
    const book = (id, title, subseries, position) => ({
      id, title, author: 'Brandon Sanderson', first_publish_year: 2006, cover_url: null,
      shelf_status: null, position, subseries,
    })
    mockApi({
      slug: 'cosmere', name: 'Cosmere', kind: 'series', description: null,
      works: [
        book('e', 'Elantris', null, null),
        book('m1', 'Mistborn', 'Mistborn', 1),
        book('m2', 'The Well of Ascension', 'Mistborn', 2),
        book('s1', 'The Way of Kings', 'The Stormlight Archive', 1),
      ],
    })
    renderPage('/series/cosmere')
    const mistborn = await screen.findByRole('list', { name: 'Mistborn' })
    expect(within(mistborn).getAllByRole('heading', { level: 3 }).map((h) => h.textContent)).toEqual([
      'Mistborn', 'The Well of Ascension'])
    expect(screen.getByRole('heading', { level: 2, name: 'The Stormlight Archive' })).toBeInTheDocument()
    // A book in the room itself has no heading above it.
    expect(screen.queryByRole('heading', { level: 2, name: 'Cosmere' })).toBeNull()
  })

  it('ignores a ?book= that is not a member', async () => {
    mockApi(SAGA)
    renderPage('/series/red-rising?book=zzz')
    const list = await screen.findByRole('list', { name: 'Books in this series' })
    within(list).getAllByRole('listitem').forEach((r) => expect(r).not.toHaveAttribute('aria-current'))
  })

  it('drops series chrome for a singleton', async () => {
    mockApi(SINGLE, [])
    renderPage('/series/the-hobbit-a1b2c3')
    expect(await screen.findByRole('heading', { level: 1, name: 'The Hobbit' })).toBeInTheDocument()
    expect(screen.queryByText(/books? in this series/i)).not.toBeInTheDocument()
    expect(screen.queryByRole('group', { name: 'Filter by book' })).not.toBeInTheDocument()
  })

  it('redirects when the API answers with a different slug', async () => {
    mockApi({ ...SAGA, slug: 'red-rising' })
    renderPage('/series/dark-age-a1b2c3')
    await waitFor(() => expect(screen.getByTestId('where')).toHaveTextContent('/series/red-rising'))
  })

  it('offers edit mode only to librarians', async () => {
    mockApi(SAGA)
    renderPage('/series/red-rising?edit=1')
    await screen.findByRole('list', { name: 'Books in this series' })
    expect(screen.queryByRole('link', { name: '[edit]' })).toBeNull()
    expect(screen.queryByRole('button', { name: /^move/ })).toBeNull()
  })

  it('shows row and header actions in edit mode, and marks librarian-placed books', async () => {
    useAuthStore.setState({ token: 't', user: { id: 'u1', username: 'lib', is_librarian: true } })
    mockApi({ ...SAGA, id: 's1', works: [{ ...SAGA.works[0], provenance: 'override' }, SAGA.works[1]] })
    renderPage('/series/red-rising?edit=1')
    const list = await screen.findByRole('list', { name: 'Books in this series' })
    const [first] = within(list).getAllByRole('listitem')
    for (const name of ['move', 'position', 'remove', 'merge into…', 'split']) {
      expect(within(first).getByRole('button', { name: `${name} Red Rising` })).toBeInTheDocument()
    }
    expect(within(first).getByText('librarian-placed')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'rename series' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: '[done]' })).toBeInTheDocument()
  })

  it('reports a fix and undoes it', async () => {
    useAuthStore.setState({ token: 't', user: { id: 'u1', username: 'lib', is_librarian: true } })
    mockApi({ ...SAGA, id: 's1' })
    client.post
      .mockResolvedValueOnce({ data: { id: 'c1', op: 'remove_from_series', exportable: false,
        runtime_only_reason: 'Red Rising is not in a catalog release', undoable: true, room_slug: 'golden-son-abc' } })
      .mockResolvedValueOnce({ data: { id: 'c1', undoable: false, reverted_at: '2026-09-28T00:00:00Z' } })
    renderPage('/series/red-rising?edit=1')
    const list = await screen.findByRole('list', { name: 'Books in this series' })
    await userEvent.click(within(list).getByRole('button', { name: 'remove Golden Son' }))
    await userEvent.type(screen.getByLabelText('Reason'), 'not a sequel')
    await userEvent.click(screen.getByRole('button', { name: 'Remove from series' }))

    const status = await screen.findByRole('status')
    expect(within(status).getByText(/runtime-only: Red Rising is not in a catalog release/)).toBeInTheDocument()
    expect(within(status).getByRole('link', { name: /go to its page/ })).toHaveAttribute('href', '/series/golden-son-abc?edit=1')
    await userEvent.click(within(status).getByRole('button', { name: 'undo' }))
    expect(client.post).toHaveBeenLastCalledWith('/librarian/corrections/c1/revert')
    expect(await within(status).findByText('undone')).toBeInTheDocument()
  })

  it('shows a dissolved series as a notice with no books and no new threads', async () => {
    mockApi({ ...SAGA, id: 's1', dissolved: true, works: [] })
    renderPage('/series/red-rising')
    expect(await screen.findByText(/This series was dissolved/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Start a Thread' })).toBeNull()
  })

  it('says why an undo was refused', async () => {
    useAuthStore.setState({ token: 't', user: { id: 'u1', username: 'lib', is_librarian: true } })
    mockApi({ ...SAGA, id: 's1' })
    client.post
      .mockResolvedValueOnce({ data: { id: 'c1', op: 'remove_from_series', exportable: true, undoable: true, room_slug: 'red-rising' } })
      .mockRejectedValueOnce({ response: { status: 409, data: { detail: 'A later fix to the same book came after this one; undo that first.' } } })
    renderPage('/series/red-rising?edit=1')
    const list = await screen.findByRole('list', { name: 'Books in this series' })
    await userEvent.click(within(list).getByRole('button', { name: 'remove Golden Son' }))
    await userEvent.type(screen.getByLabelText('Reason'), 'not a sequel')
    await userEvent.click(screen.getByRole('button', { name: 'Remove from series' }))
    const status = await screen.findByRole('status', { name: 'Librarian fix result' })
    await userEvent.click(within(status).getByRole('button', { name: 'undo' }))
    expect(await screen.findByText(/A later fix to the same book/)).toBeInTheDocument()
  })

  it('drops a book filter once that book has left the room', async () => {
    useAuthStore.setState({ token: 't', user: { id: 'u1', username: 'lib', is_librarian: true } })
    let payload = { ...SAGA, id: 's1' }
    client.get.mockImplementation((url, config) => {
      if (url.endsWith('/threads')) return Promise.resolve({ data: [] })
      return Promise.resolve({ data: payload })
    })
    client.post.mockImplementation(() => {
      payload = { ...SAGA, id: 's1', works: [SAGA.works[0]] }
      return Promise.resolve({ data: { id: 'c1', op: 'remove_from_series', exportable: true, undoable: true, room_slug: 'red-rising' } })
    })
    renderPage('/series/red-rising?edit=1')
    await userEvent.click(await screen.findByRole('button', { name: 'Golden Son', pressed: false }))
    const list = screen.getByRole('list', { name: 'Books in this series' })
    await userEvent.click(within(list).getByRole('button', { name: 'remove Golden Son' }))
    await userEvent.type(screen.getByLabelText('Reason'), 'not a sequel')
    await userEvent.click(screen.getByRole('button', { name: 'Remove from series' }))
    await waitFor(() => expect(within(list).getAllByRole('listitem')).toHaveLength(1))
    await waitFor(() => {
      const last = client.get.mock.calls.filter(([url]) => url.endsWith('/threads')).at(-1)
      expect(last[1]?.params?.work_id).toBeUndefined()
    })
  })
})
