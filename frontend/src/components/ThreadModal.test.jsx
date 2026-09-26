import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

vi.mock('../api/client', () => ({ default: { post: vi.fn() } }))

import client from '../api/client'
import ThreadModal from './ThreadModal'

function renderModal(props = {}) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <ThreadModal target={{ work_id: '1' }} onClose={() => {}} onCreated={() => {}} {...props} />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('ThreadModal', () => {
  it('uses the exact heading and submit labels the e2e suite clicks', () => {
    renderModal()
    expect(screen.getByRole('heading', { name: 'Start a Thread' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Create Thread' })).toBeInTheDocument()
  })

  it('disables submit until a title is typed', async () => {
    renderModal()
    const submit = screen.getByRole('button', { name: 'Create Thread' })
    expect(submit).toBeDisabled()
    await userEvent.type(screen.getByPlaceholderText(/thread title/i), 'A title')
    expect(submit).toBeEnabled()
  })

  it('closes when cancel is pressed', async () => {
    const onClose = vi.fn()
    renderModal({ onClose })
    await userEvent.click(screen.getByRole('button', { name: /cancel/i }))
    expect(onClose).toHaveBeenCalled()
  })

  it('is exposed as a modal dialog', () => {
    renderModal()
    expect(screen.getByRole('dialog')).toHaveAttribute('aria-modal', 'true')
  })

  it('offers a book tag inside a series and sends it', async () => {
    client.post.mockResolvedValue({ data: { id: 't1' } })
    const onCreated = vi.fn()
    renderModal({
      seriesSlug: 'red-rising',
      books: [{ id: 'b1', title: 'Red Rising' }, { id: 'b2', title: 'Golden Son' }],
      onCreated,
    })
    await userEvent.type(screen.getByPlaceholderText(/thread title/i), 'Mustang')
    await userEvent.selectOptions(screen.getByLabelText('About which book'), 'b2')
    await userEvent.click(screen.getByRole('button', { name: 'Create Thread' }))
    expect(client.post).toHaveBeenCalledWith('/series/red-rising/threads', {
      title: 'Mustang', content: '', work_id: 'b2',
    })
  })

  it('sends no tag when "all books" stays selected', async () => {
    client.post.mockResolvedValue({ data: { id: 't1' } })
    renderModal({ seriesSlug: 'red-rising', books: [{ id: 'b1', title: 'Red Rising' }] })
    await userEvent.type(screen.getByPlaceholderText(/thread title/i), 'General')
    await userEvent.click(screen.getByRole('button', { name: 'Create Thread' }))
    expect(client.post).toHaveBeenCalledWith('/series/red-rising/threads', { title: 'General', content: '' })
  })

  it('hides the book select without books', () => {
    renderModal({ seriesSlug: 'the-hobbit-a1b2c3', books: [] })
    expect(screen.queryByLabelText('About which book')).not.toBeInTheDocument()
  })
})
