import { describe, it, expect, vi, beforeEach } from 'vitest'
import { act, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes, useLocation, useNavigate } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

vi.mock('../api/client', () => ({ default: { get: vi.fn(), post: vi.fn() } }))

import client from '../api/client'
import useAuthStore from '../store/auth'
import Search from './Search'

const BRIAN = { id: 'w1', title: 'Dune', author: 'Brian Herbert', cover_url: null, edition_count: 2,
                series: { slug: 'dune-b1', name: 'Dune', kind: 'singleton' } }
const FRANK = { id: 'w2', title: 'Dune', author: 'Frank Herbert', cover_url: 'https://x/dune.jpg', edition_count: 26,
                series: { slug: 'dune', name: 'Dune Saga', kind: 'series' } }
const MESSIAH = { id: 'w3', title: 'Dune Messiah', author: 'Frank Herbert', cover_url: null, edition_count: 9,
                  series: { slug: 'dune', name: 'Dune Saga', kind: 'series' } }
const RESULTS = { dune: [BRIAN, FRANK, MESSIAH], messiah: [MESSIAH] }
const BY_ID = { w1: BRIAN, w2: FRANK, w3: MESSIAH }
const side = (w) => ({ id: w.id, title: w.title, author: w.author, first_publish_year: null, cover_url: w.cover_url,
                       description: null, edition_count: w.edition_count, thread_count: 0, shelf_count: 0,
                       series_slug: w.series.slug, series_name: w.series.kind === 'series' ? w.series.name : null })
const CORRECTION = { id: 'c1', op: 'merge_works', exportable: true, undoable: false, room_slug: 'dune' }

function mockApi() {
  client.get.mockImplementation((url, config) => {
    if (url === '/works/search') return Promise.resolve({ data: RESULTS[config.params.q] ?? [] })
    if (url === '/genres/') return Promise.resolve({ data: [] })
    const preview = url.match(/^\/librarian\/works\/(\w+)\/merge-preview$/)
    if (preview) {
      const [from, to] = [BY_ID[preview[1]], BY_ID[config.params.into]]
      return Promise.resolve({ data: { source: side(from), target: side(to), threads: 0, shelves: 0, editions: 0 } })
    }
    return Promise.reject(new Error(`unmocked GET ${url}`))
  })
}

function Where() {
  const loc = useLocation()
  const navigate = useNavigate()
  return (
    <>
      <p data-testid="where">{loc.pathname}{loc.state?.correction ? ` fixed ${loc.state.correction.id}` : ''}</p>
      <button type="button" onClick={() => navigate('/search?q=messiah')}>search messiah</button>
    </>
  )
}

function LocationProbe() {
  const location = useLocation()
  return <p data-testid="search">{location.search}</p>
}

function renderPage(entry = '/search?q=dune') {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[entry]}>
        <Where />
        <LocationProbe />
        <Routes>
          <Route path="/search" element={<Search />} />
          <Route path="/series/:slug" element={<p>series page</p>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

const asLibrarian = () => useAuthStore.setState({ token: 't', user: { id: 'u1', username: 'lib', is_librarian: true } })
const card = (w) => screen.getByRole('checkbox', { name: `select ${w.title} by ${w.author}` })

async function startSelecting() {
  await userEvent.click(await screen.findByRole('button', { name: 'select' }))
}

beforeEach(() => {
  vi.clearAllMocks()
  mockApi()
})

describe('Search page', () => {
  it('readers and visitors get plain links and no toggle', async () => {
    for (const user of [{ id: 'u2', username: 'reader' }, null]) {
      useAuthStore.setState({ token: user ? 't' : null, user })
      const { unmount } = renderPage()
      expect(await screen.findAllByRole('link')).toHaveLength(3)
      expect(screen.queryByRole('button', { name: 'select' })).toBeNull()
      expect(screen.queryByRole('checkbox')).toBeNull()
      unmount()
    }
  })

  it('selecting never navigates', async () => {
    asLibrarian()
    renderPage()
    await startSelecting()
    expect(screen.getByRole('button', { name: 'select' })).toHaveAttribute('aria-pressed', 'true')
    expect(screen.queryAllByRole('link')).toHaveLength(0)
    await userEvent.click(screen.getByRole('img', { name: 'Dune' }))
    expect(card(FRANK)).toBeChecked()
    expect(screen.getByTestId('where')).toHaveTextContent('/search')
    expect(screen.getByRole('status')).toHaveTextContent('1 selected')
  })

  it('keeps the selection across a new search', async () => {
    asLibrarian()
    renderPage()
    await startSelecting()
    await userEvent.click(card(BRIAN))
    await userEvent.click(screen.getByRole('button', { name: 'search messiah' }))
    await userEvent.click(await screen.findByRole('checkbox', { name: 'select Dune Messiah by Frank Herbert' }))
    expect(screen.getByRole('status')).toHaveTextContent('2 selected')
    const picked = within(screen.getByRole('list', { name: 'Selected books' })).getAllByRole('listitem')
    expect(picked.map((li) => li.textContent)).toEqual(['Dune Brian Herbert', 'Dune Messiah Frank Herbert'])
    expect(screen.getByRole('button', { name: 'merge…' })).toBeEnabled()
  })

  it('leaving select mode clears the selection and restores the links', async () => {
    asLibrarian()
    renderPage()
    await startSelecting()
    await userEvent.click(card(BRIAN))
    await userEvent.click(screen.getByRole('button', { name: 'select' }))
    expect(screen.getAllByRole('link')).toHaveLength(3)
    await startSelecting()
    expect(screen.getByRole('status')).toHaveTextContent('0 selected')
  })

  it('a revoked librarian loses select mode', async () => {
    asLibrarian()
    renderPage()
    await startSelecting()
    act(() => useAuthStore.setState({ user: { id: 'u1', username: 'lib', is_librarian: false } }))
    expect(screen.queryByRole('checkbox')).toBeNull()
    expect(screen.getAllByRole('link')).toHaveLength(3)
  })

  it('closing the panel keeps the selection', async () => {
    asLibrarian()
    renderPage()
    await startSelecting()
    await userEvent.click(card(BRIAN))
    await userEvent.click(card(FRANK))
    await userEvent.click(screen.getByRole('button', { name: 'merge…' }))
    await userEvent.keyboard('{Escape}')
    expect(screen.queryByRole('dialog')).toBeNull()
    expect(card(BRIAN)).toBeChecked()
    expect(card(FRANK)).toBeChecked()
    expect(screen.getByRole('button', { name: 'merge…' })).toHaveFocus() // the panel returns focus
  })

  it("merge… opens the panel preset with the preview, and a merge lands on the survivor's page", async () => {
    client.post
      .mockRejectedValueOnce({ response: { status: 422, data: { detail: {
        message: 'm', consequences: { threads: 0, shelves: 0, editions: 2 } } } } })
      .mockResolvedValueOnce({ data: CORRECTION })
    asLibrarian()
    renderPage()
    await startSelecting()
    await userEvent.click(card(BRIAN))
    await userEvent.click(card(FRANK))
    await userEvent.click(screen.getByRole('button', { name: 'merge…' }))

    const dialog = screen.getByRole('dialog')
    expect(within(dialog).queryByLabelText('Find the book to keep')).toBeNull()
    const preview = await within(dialog).findByRole('group', { name: 'Merge preview' })
    expect(within(preview).getByRole('region', { name: /^merges away/ })).toHaveTextContent('Brian Herbert')
    expect(within(preview).getByRole('region', { name: /^survives/ })).toHaveTextContent('Frank Herbert')

    await userEvent.type(within(dialog).getByLabelText('Reason'), 'duplicate record')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Merge' }))
    await userEvent.click(await within(dialog).findByRole('button', { name: 'Confirm merge' }))
    await waitFor(() => expect(screen.getByTestId('where')).toHaveTextContent('/series/dune fixed c1'))
    expect(client.post).toHaveBeenLastCalledWith('/librarian/works/w1/merge',
      { reason: 'duplicate record', into_work_id: 'w2', confirm: true })
  })

  it('reads filters from the URL and writes changes back', async () => {
    renderPage('/search?q=dune&genre=space-opera&year_from=1960')
    await waitFor(() => expect(client.get).toHaveBeenCalledWith('/works/search', expect.objectContaining({
      params: { q: 'dune', genre: ['space-opera'], year_from: '1960' } })))
    await userEvent.click(screen.getByRole('button', { name: 'remove genre space-opera' }))
    expect(screen.getByTestId('search')).toHaveTextContent('?q=dune&year_from=1960')
  })

  it('browses with filters and no query', async () => {
    renderPage('/search?genre=space-opera')
    await waitFor(() => expect(client.get).toHaveBeenCalledWith('/works/search', expect.objectContaining({
      params: { genre: ['space-opera'] } })))
  })
})
