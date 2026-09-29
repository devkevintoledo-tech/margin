import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Routes, Route, useLocation, useNavigate } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

vi.mock('../api/client', () => ({ default: { get: vi.fn(), post: vi.fn(), put: vi.fn() } }))

import client from '../api/client'
import useAuthStore from '../store/auth'
import useLibrarianStore from '../store/librarian'
import useStatusStore from '../store/status'
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

// Every book row asks for its genres; the series page tests don't care what they are.
const isGenreGet = (url) => url === '/genres/' || /^\/works\/[^/]+\/genres$/.test(url)
const genreGet = (url) => Promise.resolve({ data: url === '/genres/' ? [] : { source: 'none', genres: [], my_vote_count: null } })

function mockApi(series, threads = THREADS) {
  client.get.mockImplementation((url, config) => {
    if (isGenreGet(url)) return genreGet(url)
    if (url.endsWith('/threads')) {
      const workId = config?.params?.work_id
      return Promise.resolve({ data: workId ? threads.filter((t) => t.work_id === workId) : threads })
    }
    return Promise.resolve({ data: series })
  })
}

function Where() {
  const loc = useLocation()
  const navigate = useNavigate()
  return (
    <>
      <p data-testid="where">{loc.pathname}</p>
      <p data-testid="search">{loc.search}</p>
      <button type="button" onClick={() => navigate('/series/elsewhere')}>go elsewhere</button>
    </>
  )
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
  localStorage.clear()
  useLibrarianStore.setState({ editMode: false })
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
    expect(screen.queryByRole('button', { name: '[edit]' })).toBeNull()
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
    expect(screen.getByRole('button', { name: '[done]' })).toBeInTheDocument()
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

    const status = await screen.findByRole('group', { name: 'Librarian fix result' })
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
    const status = await screen.findByRole('group', { name: 'Librarian fix result' })
    await userEvent.click(within(status).getByRole('button', { name: 'undo' }))
    expect(await screen.findByText(/A later fix to the same book/)).toBeInTheDocument()
  })

  it('drops a book filter once that book has left the room', async () => {
    useAuthStore.setState({ token: 't', user: { id: 'u1', username: 'lib', is_librarian: true } })
    let payload = { ...SAGA, id: 's1' }
    client.get.mockImplementation((url, config) => {
    if (isGenreGet(url)) return genreGet(url)
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

  it('announces only the outcome, not the controls beside it', async () => {
    useAuthStore.setState({ token: 't', user: { id: 'u1', username: 'lib', is_librarian: true } })
    mockApi({ ...SAGA, id: 's1' })
    client.post.mockResolvedValueOnce({ data: { id: 'c1', op: 'remove_from_series', exportable: true, undoable: true, room_slug: 'red-rising' } })
    renderPage('/series/red-rising?edit=1')
    const list = await screen.findByRole('list', { name: 'Books in this series' })
    await userEvent.click(within(list).getByRole('button', { name: 'remove Golden Son' }))
    await userEvent.type(screen.getByLabelText('Reason'), 'not a sequel')
    await userEvent.click(screen.getByRole('button', { name: 'Remove from series' }))
    const line = await screen.findByRole('group', { name: 'Librarian fix result' })
    const live = within(line).getByRole('status')
    expect(live).toHaveTextContent('exported')
    expect(within(live).queryByRole('button')).toBeNull()
  })

  it('does not carry a fix report onto an unrelated series', async () => {
    useAuthStore.setState({ token: 't', user: { id: 'u1', username: 'lib', is_librarian: true } })
    mockApi({ ...SAGA, id: 's1' })
    client.post.mockResolvedValueOnce({ data: { id: 'c1', op: 'remove_from_series', exportable: true, undoable: true, room_slug: 'red-rising' } })
    renderPage('/series/red-rising?edit=1')
    const list = await screen.findByRole('list', { name: 'Books in this series' })
    await userEvent.click(within(list).getByRole('button', { name: 'remove Golden Son' }))
    await userEvent.type(screen.getByLabelText('Reason'), 'not a sequel')
    await userEvent.click(screen.getByRole('button', { name: 'Remove from series' }))
    await screen.findByRole('group', { name: 'Librarian fix result' })

    mockApi({ ...SAGA, id: 's2', slug: 'elsewhere', name: 'Elsewhere' })
    await userEvent.click(screen.getByRole('button', { name: 'go elsewhere' }))
    await screen.findByRole('heading', { level: 1, name: 'Elsewhere' })
    expect(screen.queryByRole('group', { name: 'Librarian fix result' })).toBeNull()
  })

  it('adds a book from the series header as a move into this series', async () => {
    useAuthStore.setState({ token: 't', user: { id: 'u1', username: 'lib', is_librarian: true } })
    client.get.mockImplementation((url) => {
    if (isGenreGet(url)) return genreGet(url)
      if (url.endsWith('/threads')) return Promise.resolve({ data: [] })
      if (url === '/works/search') {
        return Promise.resolve({ data: [{ id: 'b3', title: 'Morning Star', author: 'Pierce Brown',
          series: { slug: 'morning-star-x1', name: 'Morning Star', kind: 'singleton' } }] })
      }
      return Promise.resolve({ data: { ...SAGA, id: 's1' } })
    })
    client.post.mockResolvedValueOnce({ data: { id: 'c9', op: 'set_series', exportable: true, undoable: true, room_slug: 'red-rising' } })
    renderPage('/series/red-rising?edit=1')

    await userEvent.click(await screen.findByRole('button', { name: 'add a book' }))
    await userEvent.type(screen.getByLabelText('Find the book to add'), 'morning star')
    await userEvent.click(await screen.findByRole('radio', { name: /Morning Star/ }))
    await userEvent.type(screen.getByLabelText('Position (optional)'), '3')
    await userEvent.type(screen.getByLabelText('Reason'), 'book three')
    await userEvent.click(screen.getByRole('button', { name: 'Add book' }))

    await waitFor(() => expect(client.post).toHaveBeenCalledWith('/librarian/works/b3/move',
      { reason: 'book three', series_id: 's1', position: 3 }))
    const status = await screen.findByRole('group', { name: 'Librarian fix result' })
    expect(within(status).getByText('exported')).toBeInTheDocument()
    // The book now lives here, so there is no other page to go to.
    expect(within(status).queryByRole('link', { name: /go to its page/ })).toBeNull()
  })

  it('offers add a book only on a live real series', async () => {
    useAuthStore.setState({ token: 't', user: { id: 'u1', username: 'lib', is_librarian: true } })
    mockApi({ ...SINGLE, id: 's9' }, [])
    const { unmount } = renderPage('/series/the-hobbit-a1b2c3?edit=1')
    await screen.findByRole('heading', { level: 1, name: 'The Hobbit' })
    expect(screen.queryByRole('button', { name: 'add a book' })).toBeNull()
    unmount()

    mockApi({ ...SAGA, id: 's1', dissolved: true, works: [] })
    renderPage('/series/red-rising?edit=1')
    await screen.findByText(/This series was dissolved/)
    expect(screen.queryByRole('button', { name: 'add a book' })).toBeNull()
  })

  it('never shows add a book to a reader, even with ?edit=1', async () => {
    mockApi(SAGA)
    renderPage('/series/red-rising?edit=1')
    await screen.findByRole('list', { name: 'Books in this series' })
    expect(screen.queryByRole('button', { name: 'add a book' })).toBeNull()
  })
})

describe('Sticky edit mode', () => {
  const LIBRARIAN = { id: 'u1', username: 'lib', is_librarian: true }
  const READER = { id: 'u2', username: 'reader' }

  it('stays in edit mode on the next book', async () => {
    useAuthStore.setState({ token: 't', user: LIBRARIAN })
    useLibrarianStore.setState({ editMode: true })
    mockApi({ ...SAGA, id: 's1' })
    renderPage('/series/red-rising')
    expect(await screen.findByRole('button', { name: 'move Red Rising' })).toBeInTheDocument()

    mockApi({ ...SAGA, id: 's2', slug: 'elsewhere', name: 'Elsewhere' })
    await userEvent.click(screen.getByRole('button', { name: 'go elsewhere' }))
    await screen.findByRole('heading', { level: 1, name: 'Elsewhere' })
    expect(screen.getByRole('button', { name: 'move Red Rising' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '[done]' })).toBeInTheDocument()
  })

  it('[edit] turns it on and [done] turns it off, without touching the address', async () => {
    useAuthStore.setState({ token: 't', user: LIBRARIAN })
    mockApi({ ...SAGA, id: 's1' })
    renderPage('/series/red-rising')
    await userEvent.click(await screen.findByRole('button', { name: '[edit]' }))
    expect(useLibrarianStore.getState().editMode).toBe(true)
    expect(screen.getByRole('button', { name: 'move Red Rising' })).toBeInTheDocument()
    expect(screen.getByTestId('search')).toHaveTextContent(/^$/)

    await userEvent.click(screen.getByRole('button', { name: '[done]' }))
    expect(useLibrarianStore.getState().editMode).toBe(false)
    expect(screen.queryByRole('button', { name: 'move Red Rising' })).toBeNull()
    expect(screen.getByRole('button', { name: '[edit]' })).toBeInTheDocument()
  })

  it('?edit=1 turns it on and leaves the rest of the address alone', async () => {
    useAuthStore.setState({ token: 't', user: LIBRARIAN })
    mockApi({ ...SAGA, id: 's1' })
    renderPage('/series/red-rising?book=b2&edit=1')
    expect(await screen.findByRole('button', { name: 'move Golden Son' })).toBeInTheDocument()
    expect(useLibrarianStore.getState().editMode).toBe(true)
    await waitFor(() => expect(screen.getByTestId('search')).toHaveTextContent('?book=b2'))
    const list = screen.getByRole('list', { name: 'Books in this series' })
    expect(within(list).getAllByRole('listitem')[1]).toHaveAttribute('aria-current', 'true')
  })

  it('keeps a fix report carried in by a ?edit=1 link', async () => {
    useAuthStore.setState({ token: 't', user: LIBRARIAN })
    mockApi({ ...SAGA, id: 's1' })
    const correction = { id: 'c9', op: 'set_series', exportable: true, undoable: true, room_slug: 'red-rising' }
    renderPage({ pathname: '/series/red-rising', search: '?edit=1', state: { correction } })
    await waitFor(() => expect(screen.getByTestId('search')).toHaveTextContent(/^$/))
    const line = await screen.findByRole('group', { name: 'Librarian fix result' })
    expect(within(line).getByRole('button', { name: 'undo' })).toBeInTheDocument()
  })

  it('never shows edit mode to a reader, even with it stored', async () => {
    useAuthStore.setState({ token: 't', user: READER })
    useLibrarianStore.setState({ editMode: true })
    mockApi({ ...SAGA, id: 's1' })
    renderPage('/series/red-rising')
    await screen.findByRole('list', { name: 'Books in this series' })
    expect(screen.queryByRole('button', { name: /^move/ })).toBeNull()
    expect(screen.queryByRole('button', { name: '[edit]' })).toBeNull()
    expect(screen.queryByRole('button', { name: '[done]' })).toBeNull()
    expect(screen.queryByRole('button', { name: 'rename series' })).toBeNull()
  })

  it("a reader's ?edit=1 does not turn it on", async () => {
    useAuthStore.setState({ token: 't', user: READER })
    mockApi({ ...SAGA, id: 's1' })
    renderPage('/series/red-rising?edit=1')
    await screen.findByRole('list', { name: 'Books in this series' })
    expect(useLibrarianStore.getState().editMode).toBe(false)
    expect(screen.queryByRole('button', { name: /^move/ })).toBeNull()
  })

  it('names the mode in the status bar', async () => {
    useAuthStore.setState({ token: 't', user: LIBRARIAN })
    useLibrarianStore.setState({ editMode: true })
    mockApi({ ...SAGA, id: 's1' })
    renderPage('/series/red-rising')
    await screen.findByRole('list', { name: 'Books in this series' })
    await waitFor(() => expect(useStatusStore.getState().mode).toBe('EDIT'))
    await userEvent.click(screen.getByRole('button', { name: '[done]' }))
    await waitFor(() => expect(useStatusStore.getState().mode).toBe('SERIES'))
  })
})
