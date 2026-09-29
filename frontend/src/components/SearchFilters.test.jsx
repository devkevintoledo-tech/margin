import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

vi.mock('../api/client', () => ({ default: { get: vi.fn(() => Promise.resolve({ data: [
  { slug: 'science-fiction', name: 'Science Fiction', children: [{ slug: 'space-opera', name: 'Space Opera' }] }] })) } }))

import SearchFilters from './SearchFilters'

function renderBar(props) {
  const onChange = vi.fn()
  render(
    <QueryClientProvider client={new QueryClient()}>
      <SearchFilters genres={[]} author="" yearFrom="" yearTo="" onChange={onChange} {...props} />
    </QueryClientProvider>,
  )
  return onChange
}

describe('SearchFilters', () => {
  it('removes a genre chip', async () => {
    const onChange = renderBar({ genres: ['space-opera'] })
    await userEvent.click(screen.getByRole('button', { name: 'remove genre space-opera' }))
    expect(onChange).toHaveBeenCalledWith({ genres: [] })
  })

  it('adds a genre through the curated picker', async () => {
    const onChange = renderBar()
    await userEvent.click(screen.getByRole('button', { name: 'add a genre filter' }))
    await userEvent.click(await screen.findByRole('option', { name: /space-opera/ }))
    expect(onChange).toHaveBeenCalledWith({ genres: ['space-opera'] })
  })

  it('applies author and years on Enter', async () => {
    const onChange = renderBar()
    await userEvent.type(screen.getByRole('textbox', { name: 'author' }), 'herbert')
    await userEvent.type(screen.getByRole('spinbutton', { name: 'from year' }), '1960{Enter}')
    expect(onChange).toHaveBeenLastCalledWith({ author: 'herbert', yearFrom: '1960', yearTo: '' })
  })
})
