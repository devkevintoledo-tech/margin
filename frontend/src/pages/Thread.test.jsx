import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Routes, Route } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

vi.mock('../api/client', () => ({
  default: { get: vi.fn(), put: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
}))

import client from '../api/client'
import useAuthStore from '../store/auth'
import Thread from './Thread'

const NOW = new Date().toISOString()

function post(id, content, replies = []) {
  return { id, content, author: 'reader', score: 0, my_vote: 0, parent_id: null, created_at: NOW, replies }
}

const THREAD = {
  id: 't1',
  title: 'Who is the real villain?',
  author: 'darrow',
  user_id: 'u1',
  deleted: false,
  score: 4,
  series: { slug: 'red-rising', name: 'Red Rising' },
  genre: null,
  posts: [
    post('p1', 'The Society, obviously.', [
      { ...post('p2', 'Octavia more than anyone.'), parent_id: 'p1' },
    ]),
  ],
}

function renderPage(path = '/series/red-rising/threads/t1') {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/series/:slug/threads/:threadId" element={<Thread />} />
          <Route path="/genres/:slug/threads/:threadId" element={<Thread />} />
          <Route path="/series/:slug" element={<p>room page</p>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  useAuthStore.setState({ user: null, token: null })
  vi.clearAllMocks()
})

describe('Thread', () => {
  it('renders the thread, its score and every post in the tree', async () => {
    client.get.mockResolvedValue({ data: THREAD })
    renderPage()

    expect(await screen.findByRole('heading', { name: 'Who is the real villain?' })).toBeInTheDocument()
    expect(client.get).toHaveBeenCalledWith('/threads/t1')
    expect(screen.getByText('+4 points')).toBeInTheDocument()
    // Two posts, though only one top-level branch.
    expect(screen.getByText('2 posts')).toBeInTheDocument()
    expect(screen.getByText('The Society, obviously.')).toBeInTheDocument()
    expect(screen.getByText('Octavia more than anyone.')).toBeInTheDocument()
  })

  it('paths back to the series room', async () => {
    client.get.mockResolvedValue({ data: THREAD })
    renderPage()

    expect(await screen.findByRole('link', { name: 'red-rising' })).toHaveAttribute(
      'href',
      '/series/red-rising',
    )
  })

  it('paths back to the genre for a genre thread', async () => {
    client.get.mockResolvedValue({
      data: { ...THREAD, series: null, genre: { slug: 'fantasy', name: 'Fantasy' }, posts: [] },
    })
    renderPage('/genres/fantasy/threads/t1')

    expect(await screen.findByRole('link', { name: 'fantasy' })).toHaveAttribute('href', '/genres/fantasy')
    expect(screen.getByText('No posts yet. Be the first to reply.')).toBeInTheDocument()
  })

  it('reports a thread that fails to load', async () => {
    client.get.mockRejectedValue({ response: { status: 404 } })
    renderPage()

    expect(await screen.findByText('Failed to load thread.')).toBeInTheDocument()
  })
})

describe('Thread deletion', () => {
  it('lets the author delete the thread and returns to its room', async () => {
    useAuthStore.setState({ user: { id: 'u1', username: 'darrow' }, token: 't' })
    client.get.mockResolvedValue({ data: THREAD })
    client.delete.mockResolvedValue({})
    renderPage()

    await userEvent.click(await screen.findByRole('button', { name: 'delete thread' }))
    expect(screen.getByRole('button', { name: 'no, keep it' })).toHaveFocus()
    await userEvent.click(screen.getByRole('button', { name: 'yes, delete thread' }))

    expect(client.delete).toHaveBeenCalledWith('/threads/t1')
    expect(await screen.findByText('room page')).toBeInTheDocument()
  })

  it('offers no delete to other readers', async () => {
    useAuthStore.setState({ user: { id: 'u2', username: 'mustang' }, token: 't' })
    client.get.mockResolvedValue({ data: THREAD })
    renderPage()
    await screen.findByRole('heading', { name: 'Who is the real villain?' })
    expect(screen.queryByRole('button', { name: 'delete thread' })).not.toBeInTheDocument()
  })

  it('renders a deleted thread without author, composer or delete', async () => {
    useAuthStore.setState({ user: { id: 'u1', username: 'darrow' }, token: 't' })
    client.get.mockResolvedValue({
      data: { ...THREAD, deleted: true, title: '', author: null, user_id: null },
    })
    renderPage()

    expect(await screen.findByRole('heading', { name: '[deleted]' })).toBeInTheDocument()
    expect(screen.queryByText('darrow')).not.toBeInTheDocument()
    expect(
      screen.getByText('This thread was deleted and no longer accepts replies.'),
    ).toBeInTheDocument()
    expect(screen.queryByPlaceholderText('Join the discussion...')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'delete thread' })).not.toBeInTheDocument()
    // The remaining discussion stays readable.
    expect(screen.getByText('The Society, obviously.')).toBeInTheDocument()
  })

  it('offers no reply on the surviving posts of a deleted thread', async () => {
    useAuthStore.setState({ user: { id: 'u2', username: 'mustang' }, token: 't' })
    client.get.mockResolvedValue({
      data: { ...THREAD, deleted: true, title: '', author: null, user_id: null },
    })
    renderPage()

    expect(await screen.findByText('The Society, obviously.')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'reply' })).not.toBeInTheDocument()
  })

  it('does not count tombstones as posts', async () => {
    client.get.mockResolvedValue({
      data: {
        ...THREAD,
        posts: [{ ...THREAD.posts[0], deleted: true, content: '', author: null, user_id: null }],
      },
    })
    renderPage()
    expect(await screen.findByText('1 post')).toBeInTheDocument()
  })
})
