import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter, Routes, Route } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

vi.mock('../api/client', () => ({ default: { get: vi.fn(), put: vi.fn(), post: vi.fn() } }))

import client from '../api/client'
import useAuthStore from '../store/auth'
import Genre from './Genre'

const GENRE = { slug: 'fantasy', name: 'Fantasy', description: 'Magic, myth, and invented worlds.' }
const THREAD = {
  id: 't1',
  title: 'Is Kvothe reliable?',
  author: 'reader',
  score: 3,
  my_vote: 0,
  post_count: 2,
  created_at: new Date().toISOString(),
}

function mockApi({ genre = GENRE, threads = [THREAD], works = [] } = {}) {
  client.get.mockImplementation((url) => {
    if (url === '/genres/fantasy') {
      return genre ? Promise.resolve({ data: genre }) : Promise.reject({ response: { status: 404 } })
    }
    if (url === '/genres/fantasy/works') return Promise.resolve({ data: works })
    if (url === '/genres/fantasy/threads') return Promise.resolve({ data: threads })
    return Promise.reject(new Error(`unexpected GET ${url}`))
  })
}

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={['/genres/fantasy']}>
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
})
