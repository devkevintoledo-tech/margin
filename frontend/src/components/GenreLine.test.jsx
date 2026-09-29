import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

vi.mock('../api/client', () => ({ default: { get: vi.fn(), put: vi.fn(), delete: vi.fn(), post: vi.fn() } }))

import client from '../api/client'
import useAuthStore from '../store/auth'
import GenreLine from './GenreLine'

const TREE = [{ slug: 'fantasy', name: 'Fantasy', children: [{ slug: 'grimdark', name: 'Grimdark' }] }]

function mock(payload) {
  client.get.mockImplementation((url) => {
    if (url === '/works/w1/genres') return Promise.resolve({ data: payload })
    if (url === '/genres/') return Promise.resolve({ data: TREE })
    return Promise.reject(new Error(`unexpected GET ${url}`))
  })
}

function renderLine() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter><GenreLine workId="w1" title="Dune" /></MemoryRouter>
    </QueryClientProvider>,
  )
}

const READERS = {
  source: 'readers', my_vote_count: 1,
  genres: [
    { slug: 'fantasy', name: 'Fantasy', parent_slug: null, score: 19, direct_votes: 4, my_vote: false },
    { slug: 'grimdark', name: 'Grimdark', parent_slug: 'fantasy', score: 7, direct_votes: 7, my_vote: true },
  ],
}

beforeEach(() => {
  vi.clearAllMocks()
  useAuthStore.setState({ user: { id: 'u1', username: 'r' }, token: 't' })
})

describe('GenreLine', () => {
  it('shows reader genres as links with counts and marks my vote', async () => {
    mock(READERS)
    renderLine()
    const link = await screen.findByRole('link', { name: 'grimdark' })
    expect(link).toHaveAttribute('href', '/genres/grimdark')
    expect(screen.getByText('19')).toBeInTheDocument()
    expect(screen.getByText('you tagged this')).toHaveClass('sr-only')
  })

  it('labels inferred genres and shows no counts', async () => {
    mock({ source: 'inferred', my_vote_count: 0, genres: [
      { slug: 'fantasy', name: 'Fantasy', parent_slug: null, score: 0, direct_votes: 0, my_vote: false }] })
    renderLine()
    expect(await screen.findByText('genres (inferred)')).toBeInTheDocument()
    expect(screen.queryByText('0')).toBeNull()
  })

  it('shows a dash and the tag control when nothing is known', async () => {
    mock({ source: 'none', my_vote_count: 0, genres: [] })
    renderLine()
    expect(await screen.findByText('no genres yet')).toHaveClass('sr-only')
    expect(screen.getByRole('button', { name: 'tag genres of Dune' })).toBeInTheDocument()
  })

  it('hides the tag control from anonymous readers', async () => {
    useAuthStore.setState({ user: null, token: null })
    mock(READERS)
    renderLine()
    await screen.findByRole('link', { name: 'grimdark' })
    expect(screen.queryByRole('button', { name: 'tag genres of Dune' })).toBeNull()
  })

  it('rolls back and shows the server’s sentence when a vote is refused', async () => {
    mock(READERS)
    client.put.mockRejectedValue({ response: { status: 422, data: {
      detail: "You've tagged this book with 5 genres; remove one first." } } })
    renderLine()
    await userEvent.click(await screen.findByRole('button', { name: 'tag genres of Dune' }))
    await userEvent.click(await screen.findByRole('option', { name: /fantasy/ }))
    expect(await screen.findByRole('alert')).toHaveTextContent('5 genres')
    await waitFor(() => expect(screen.getByText('19')).toBeInTheDocument())
  })
})

const WITH_VETO = {
  ...READERS,
  genres: [...READERS.genres,
    { slug: 'horror', name: 'Horror', parent_slug: null, score: 2, direct_votes: 2, my_vote: false,
      vetoed: true, veto_id: 'c1' }],
}

function renderEditing() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter><GenreLine workId="w1" title="Dune" editing /></MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('GenreLine in edit mode', () => {
  beforeEach(() => useAuthStore.setState({ user: { id: 'l', username: 'lib', is_librarian: true }, token: 't' }))

  it('shows vetoed genres struck through with undo, only in edit mode', async () => {
    mock(WITH_VETO)
    renderEditing()
    const vetoed = await screen.findByText('horror')
    expect(vetoed).toHaveClass('line-through', 'text-warning')
    client.post.mockResolvedValue({ data: {} })
    await userEvent.click(screen.getByRole('button', { name: 'undo veto of horror' }))
    expect(client.post).toHaveBeenCalledWith('/librarian/corrections/c1/revert')
  })

  it('vetoes a genre with a reason', async () => {
    mock(READERS)
    client.post.mockResolvedValue({ data: { id: 'c2' } })
    renderEditing()
    await userEvent.click(await screen.findByRole('button', { name: 'veto grimdark' }))
    await userEvent.click(screen.getByRole('button', { name: 'troll tagging' }))
    await userEvent.click(screen.getByRole('button', { name: 'veto' }))
    expect(client.post).toHaveBeenCalledWith('/librarian/works/w1/genres/grimdark/veto', { reason: 'troll tagging' })
  })

  it('never shows vetoed genres outside edit mode', async () => {
    mock(WITH_VETO)
    renderLine()
    await screen.findByRole('link', { name: 'grimdark' })
    expect(screen.queryByText('horror')).toBeNull()
  })
})
