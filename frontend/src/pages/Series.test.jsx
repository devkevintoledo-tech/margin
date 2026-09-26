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

  it('highlights the book named by ?book=', async () => {
    mockApi(SAGA)
    renderPage('/series/red-rising?book=b2')
    const list = await screen.findByRole('list', { name: 'Books in this series' })
    const [first, second] = within(list).getAllByRole('listitem')
    expect(second).toHaveAttribute('aria-current', 'true')
    expect(first).not.toHaveAttribute('aria-current')
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
})
