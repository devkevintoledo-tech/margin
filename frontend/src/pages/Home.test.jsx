import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Routes, Route, useLocation } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

vi.mock('../api/client', () => ({ default: { get: vi.fn() } }))

import client from '../api/client'
import Home from './Home'

function Location() {
  const location = useLocation()
  return <p data-testid="location">{location.pathname + location.search}</p>
}

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={['/']}>
        <Routes>
          <Route path="/" element={<Home />} />
          <Route path="*" element={<Location />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

beforeEach(() => vi.clearAllMocks())

describe('Home', () => {
  it('lists the genres the API returns, each linking to its page', async () => {
    client.get.mockResolvedValue({
      data: [{ slug: 'horror', name: 'Horror', description: 'Things that go bump.' }],
    })
    renderPage()

    const link = await screen.findByRole('link', { name: /horror/ })
    expect(link).toHaveAttribute('href', '/genres/horror')
    expect(client.get).toHaveBeenCalledWith('/genres/')
  })

  it('shows the fallback genres while the API is unavailable', () => {
    client.get.mockReturnValue(new Promise(() => {}))
    renderPage()

    expect(screen.getByRole('link', { name: /science-fiction/ })).toHaveAttribute(
      'href',
      '/genres/science-fiction',
    )
  })

  it('searches for the trimmed query', async () => {
    client.get.mockReturnValue(new Promise(() => {}))
    const user = userEvent.setup()
    renderPage()

    await user.type(screen.getByLabelText('Search for a book or author'), '  red rising ')
    await user.click(screen.getByRole('button', { name: 'Search' }))

    expect(screen.getByTestId('location')).toHaveTextContent('/search?q=red%20rising')
  })

  it('does not search for a blank query', async () => {
    client.get.mockReturnValue(new Promise(() => {}))
    const user = userEvent.setup()
    renderPage()

    await user.type(screen.getByLabelText('Search for a book or author'), '   ')
    await user.click(screen.getByRole('button', { name: 'Search' }))

    expect(screen.queryByTestId('location')).not.toBeInTheDocument()
  })
})
