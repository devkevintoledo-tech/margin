import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Routes, Route } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

vi.mock('../api/client', () => ({ default: { get: vi.fn(), put: vi.fn(), post: vi.fn() } }))

import client from '../api/client'
import useAuthStore from '../store/auth'
import Genre from './Genre'

const GENRE = {
  slug: 'fantasy', name: 'Fantasy', description: 'Magic, myth, and invented worlds.',
  parent: null, retired: false, room_slug: 'fantasy',
  children: [{ slug: 'grimdark', name: 'Grimdark', book_count: 3 }],
}
const SUB = { slug: 'grimdark', name: 'Grimdark', description: null, parent: { slug: 'fantasy', name: 'Fantasy' },
              retired: false, room_slug: 'fantasy', children: [] }

const THREAD = {
  id: 't1',
  title: 'Is Kvothe reliable?',
  author: 'reader',
  score: 3,
  my_vote: 0,
  post_count: 2,
  created_at: new Date().toISOString(),
}

function mockApi({ genre = GENRE, threads = [THREAD], works = [], slug = 'fantasy' } = {}) {
  client.get.mockImplementation((url) => {
    if (url === `/genres/${slug}`) {
      return genre ? Promise.resolve({ data: genre }) : Promise.reject({ response: { status: 404 } })
    }
    if (url === `/genres/${slug}/works`) return Promise.resolve({ data: works })
    if (url === `/genres/${slug}/threads`) return Promise.resolve({ data: threads })
    return Promise.reject(new Error(`unexpected GET ${url}`))
  })
}

function renderPage(path = '/genres/fantasy') {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/genres/:slug" element={<Genre />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  useAuthStore.setState({ user: null, token: null })
  vi.clearAllMocks()
})

describe('Genre', () => {
  it('renders the genre and links each thread under it', async () => {
    mockApi()
    renderPage()

    expect(await screen.findByRole('heading', { name: 'Fantasy' })).toBeInTheDocument()
    expect(await screen.findByRole('link', { name: 'Is Kvothe reliable?' })).toHaveAttribute(
      'href',
      '/genres/fantasy/threads/t1',
    )
  })

  it('says when there are no discussions yet', async () => {
    mockApi({ threads: [] })
    renderPage()

    expect(await screen.findByText('No discussions yet.')).toBeInTheDocument()
  })

  it('offers to start a discussion only to a signed-in reader', async () => {
    mockApi()
    const { unmount } = renderPage()
    await screen.findByRole('heading', { name: 'Fantasy' })
    expect(screen.queryByRole('button', { name: 'Start a Discussion' })).not.toBeInTheDocument()
    unmount()

    useAuthStore.setState({ user: { id: 'u1', username: 'reader' }, token: 'tok' })
    renderPage()
    expect(await screen.findByRole('button', { name: 'Start a Discussion' })).toBeInTheDocument()
  })

  it('reports an unknown genre', async () => {
    mockApi({ genre: null })
    renderPage()

    expect(await screen.findByText('Genre not found.')).toBeInTheDocument()
  })

  it('indexes a parent’s subgenres with book counts', async () => {
    mockApi()
    renderPage()
    const sub = await screen.findByRole('link', { name: /grimdark/ })
    expect(sub).toHaveAttribute('href', '/genres/grimdark')
    expect(sub).toHaveTextContent('3')
  })

  it('sends a subgenre’s discussion to its parent', async () => {
    mockApi({ genre: SUB, slug: 'grimdark' })
    renderPage('/genres/grimdark')
    const note = await screen.findByText(/discussion lives in/)
    // The path header links the parent too; the note's own link is the one under test.
    expect(within(note).getByRole('link', { name: 'fantasy' })).toHaveAttribute('href', '/genres/fantasy')
    expect(screen.queryByRole('button', { name: 'Start a Discussion' })).toBeNull()
    expect(client.get).not.toHaveBeenCalledWith('/genres/grimdark/threads', expect.anything())
  })

  it('marks inferred books and toggles the sort', async () => {
    mockApi({ works: [{ id: 'w1', title: 'Prince of Thorns', author: 'Mark Lawrence', kind: 'single',
                        edition_count: 1, inferred: true, top_genres: [] }] })
    renderPage()
    expect(await screen.findByText('inferred')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'title' }))
    await waitFor(() => expect(client.get).toHaveBeenCalledWith('/genres/fantasy/works', { params: { sort: 'title' } }))
  })
})
