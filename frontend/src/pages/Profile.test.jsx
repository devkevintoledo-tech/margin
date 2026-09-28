import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter, Routes, Route } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

vi.mock('../api/client', () => ({ default: { get: vi.fn() } }))

import client from '../api/client'
import Profile from './Profile'

const PROFILE = {
  id: 'u1',
  username: 'reader',
  shelves: {
    reading: [
      {
        id: 'w1',
        title: 'Red Rising',
        author: 'Pierce Brown',
        cover_url: null,
        edition_count: 26,
        shelf_status: 'reading',
        series: { slug: 'red-rising', name: 'Red Rising', kind: 'series' },
      },
    ],
    want_to_read: [],
    read: [],
  },
}

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={['/profile/reader']}>
        <Routes>
          <Route path="/profile/:username" element={<Profile />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('Profile', () => {
  it('renders shelved works as cards linking to their series', async () => {
    client.get.mockResolvedValue({ data: PROFILE })
    renderPage()

    const link = await screen.findByRole('link', { name: /Red Rising/ })
    expect(link).toHaveAttribute('href', '/series/red-rising?book=w1')
    expect(screen.getByText('Pierce Brown')).toBeInTheDocument()
  })

  it('says so when every shelf is empty', async () => {
    client.get.mockResolvedValue({
      data: { ...PROFILE, shelves: { reading: [], want_to_read: [], read: [] } },
    })
    renderPage()

    expect(await screen.findByText('No books on shelf yet.')).toBeInTheDocument()
  })
})
