import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
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
})
