import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

vi.mock('../api/client', () => ({ default: { get: vi.fn(), post: vi.fn() } }))

import client from '../api/client'
import useAuthStore from '../store/auth'
import Librarian from './Librarian'

const ROWS = [
  { id: 'c2', op: 'set_series', subject: 'Iron Gold', room_slug: 'red-rising', reason: 'book four', user: 'ada',
    created_at: new Date().toISOString(), exportable: true, runtime_only_reason: null, undoable: true, reverted_at: null },
  { id: 'c1', op: 'merge_works', subject: 'Dune', room_slug: 'dune', reason: 'dup', user: 'ada',
    created_at: new Date().toISOString(), exportable: false, runtime_only_reason: 'Dune has no Open Library id',
    undoable: false, reverted_at: null },
]

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}><MemoryRouter><Librarian /></MemoryRouter></QueryClientProvider>,
  )
}

beforeEach(() => {
  vi.clearAllMocks()
  client.get.mockResolvedValue({ data: ROWS })
})

describe('Librarian log', () => {
  it('is a 404 for readers', () => {
    useAuthStore.setState({ token: 't', user: { id: 'u', username: 'reader' } })
    renderPage()
    expect(screen.getByText(/not found/i)).toBeInTheDocument()
    expect(client.get).not.toHaveBeenCalled()
  })

  it('lists fixes with export status, links and undo', async () => {
    useAuthStore.setState({ token: 't', user: { id: 'u', username: 'ada', is_librarian: true } })
    client.post.mockResolvedValue({ data: { ...ROWS[0], undoable: false, reverted_at: new Date().toISOString() } })
    renderPage()
    expect(await screen.findByRole('link', { name: 'Iron Gold' })).toHaveAttribute('href', '/series/red-rising')
    expect(screen.getByText('exported')).toBeInTheDocument()
    expect(screen.getByText('runtime-only')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'undo Iron Gold' }))
    expect(client.post).toHaveBeenCalledWith('/librarian/corrections/c2/revert')
  })

  it('filters to runtime-only fixes', async () => {
    useAuthStore.setState({ token: 't', user: { id: 'u', username: 'ada', is_librarian: true } })
    renderPage()
    await screen.findByRole('link', { name: 'Iron Gold' })
    await userEvent.click(screen.getByRole('button', { name: 'runtime-only only' }))
    expect(client.get).toHaveBeenLastCalledWith('/librarian/corrections', { params: { runtime_only: true } })
  })

  it('says why an undo was refused', async () => {
    useAuthStore.setState({ token: 't', user: { id: 'u', username: 'ada', is_librarian: true } })
    client.post.mockRejectedValue({ response: { status: 409, data: { detail: 'The book or series changed since this fix.' } } })
    renderPage()
    await userEvent.click(await screen.findByRole('button', { name: 'undo Iron Gold' }))
    expect(await screen.findByText(/changed since this fix/)).toBeInTheDocument()
  })
})
