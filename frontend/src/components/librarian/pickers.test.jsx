import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

vi.mock('../../api/client', () => ({ default: { get: vi.fn(), post: vi.fn() } }))

import client from '../../api/client'
import { SeriesPicker, WorkPicker } from './pickers'

function wrap(ui) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>)
}

beforeEach(() => vi.clearAllMocks())

describe('WorkPicker', () => {
  it('labels its search with the label it is given', () => {
    wrap(<WorkPicker label="Find the book to add" value={null} onChange={vi.fn()} />)
    expect(screen.getByLabelText('Find the book to add')).toHaveAttribute('type', 'text')
    expect(screen.getByRole('radiogroup', { name: 'Find the book to add: results' })).toBeInTheDocument()
  })

  it('says which real series a found book lives in, and nothing for a book on its own page', async () => {
    client.get.mockResolvedValue({ data: [
      { id: 'w2', title: 'Iron Gold', author: 'Pierce Brown',
        series: { slug: 'red-rising', name: 'Red Rising', kind: 'series' } },
      { id: 'w3', title: 'Dune', author: 'Frank Herbert',
        series: { slug: 'dune-a1b2', name: 'Dune', kind: 'singleton' } },
    ] })
    const onChange = vi.fn()
    wrap(<WorkPicker label="Find a book" value={null} onChange={onChange} />)
    await userEvent.type(screen.getByLabelText('Find a book'), 'iron')
    expect(await screen.findByRole('radio', { name: /Iron Gold.*in Red Rising/ })).toBeInTheDocument()
    expect(screen.getByRole('radio', { name: /Dune/ })).not.toHaveAccessibleName(/ in /)
    await userEvent.click(screen.getByRole('radio', { name: /Iron Gold/ }))
    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ id: 'w2' }))
  })

  it('leaves out the excluded book', async () => {
    client.get.mockResolvedValue({ data: [
      { id: 'w1', title: 'Dune', author: 'Brian Herbert', series: null },
      { id: 'w2', title: 'Dune', author: 'Frank Herbert', series: null },
    ] })
    wrap(<WorkPicker label="Find a book" exclude="w1" value={null} onChange={vi.fn()} />)
    await userEvent.type(screen.getByLabelText('Find a book'), 'dune')
    expect(await screen.findByRole('radio', { name: /Frank Herbert/ })).toBeInTheDocument()
    expect(screen.queryByRole('radio', { name: /Brian Herbert/ })).toBeNull()
  })

  it('searches once typing pauses, not on every keystroke', async () => {
    client.get.mockResolvedValue({ data: [] })
    wrap(<WorkPicker label="Find a book" value={null} onChange={vi.fn()} />)
    await userEvent.type(screen.getByLabelText('Find a book'), 'dune messiah')
    await waitFor(() => expect(client.get).toHaveBeenCalledWith('/works/search', expect.objectContaining({ params: { q: 'dune messiah' } })))
    expect(client.get.mock.calls.filter(([url]) => url === '/works/search')).toHaveLength(1)
  })
})

describe('SeriesPicker', () => {
  it('takes a label and still offers a new series by name', async () => {
    client.get.mockResolvedValue({ data: [] })
    const onChange = vi.fn()
    wrap(<SeriesPicker label="Move them to" value={null} onChange={onChange} />)
    await userEvent.type(screen.getByLabelText('Move them to'), 'Legends of Dune')
    await userEvent.click(await screen.findByRole('radio', { name: 'new series: Legends of Dune' }))
    expect(onChange).toHaveBeenCalledWith({ name: 'Legends of Dune' })
  })

  it('defaults its label to "Find a series"', () => {
    wrap(<SeriesPicker value={null} onChange={vi.fn()} />)
    expect(screen.getByLabelText('Find a series')).toBeInTheDocument()
  })
})
