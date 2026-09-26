import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter, Routes, Route, useLocation } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

vi.mock('../api/client', () => ({ default: { get: vi.fn() } }))
import client from '../api/client'
import WorkRedirect from './WorkRedirect'

function Where() {
  const loc = useLocation()
  return <p>at {loc.pathname + loc.search}</p>
}

function renderAt(entry) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[entry]}>
        <Routes>
          <Route path="/works/:id" element={<WorkRedirect />} />
          <Route path="/works/:id/threads/:threadId" element={<WorkRedirect />} />
          <Route path="*" element={<Where />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

beforeEach(() => vi.clearAllMocks())

describe('WorkRedirect', () => {
  it('sends an old work URL to its series, at that book', async () => {
    client.get.mockResolvedValue({ data: { id: 'w1', series: { slug: 'red-rising', name: 'Red Rising', kind: 'series' } } })
    renderAt('/works/w1')
    expect(await screen.findByText('at /series/red-rising?book=w1')).toBeInTheDocument()
  })

  it('sends an old thread URL to the same thread in the series room', async () => {
    client.get.mockResolvedValue({ data: { id: 'w1', series: { slug: 'red-rising', name: 'Red Rising', kind: 'series' } } })
    renderAt('/works/w1/threads/t9')
    expect(await screen.findByText('at /series/red-rising/threads/t9')).toBeInTheDocument()
  })

  it('says so when the work does not exist', async () => {
    client.get.mockRejectedValue({ response: { status: 404, data: { detail: 'Work not found' } } })
    renderAt('/works/nope')
    expect(await screen.findByText(/could not find this book/i)).toBeInTheDocument()
  })
})
