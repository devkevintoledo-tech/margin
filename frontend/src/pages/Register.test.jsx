import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Routes, Route } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

vi.mock('../api/client', () => ({ default: { post: vi.fn() } }))

import client from '../api/client'
import useAuthStore from '../store/auth'
import Register from './Register'

function renderPage() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={['/register']}>
        <Routes>
          <Route path="/register" element={<Register />} />
          <Route path="/" element={<p>home page</p>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

async function fill(user, container, { password = 'longenough', confirm = password } = {}) {
  await user.type(container.querySelector('input[type="email"]'), 'ada@example.com')
  await user.type(container.querySelector('input[type="text"]'), 'ada')
  const [pw, pw2] = container.querySelectorAll('input[type="password"]')
  await user.type(pw, password)
  await user.type(pw2, confirm)
  await user.click(screen.getByRole('button', { name: 'Create account' }))
}

beforeEach(() => {
  useAuthStore.setState({ user: null, token: null })
  vi.clearAllMocks()
})

describe('Register page', () => {
  it('creates the account, stores the token and goes home', async () => {
    client.post.mockResolvedValue({ data: { token: 'tok-1', user: { id: '1', username: 'ada' } } })
    const user = userEvent.setup()
    const { container } = renderPage()

    await fill(user, container)

    expect(client.post).toHaveBeenCalledWith('/auth/register', {
      email: 'ada@example.com',
      username: 'ada',
      password: 'longenough',
    })
    expect(await screen.findByText('home page')).toBeInTheDocument()
    expect(useAuthStore.getState().token).toBe('tok-1')
  })

  it('refuses mismatched passwords without calling the API', async () => {
    const user = userEvent.setup()
    const { container } = renderPage()

    await fill(user, container, { password: 'longenough', confirm: 'different1' })

    expect(screen.getByText('Passwords do not match.')).toBeInTheDocument()
    expect(client.post).not.toHaveBeenCalled()
  })

  it('refuses a short password without calling the API', async () => {
    const user = userEvent.setup()
    const { container } = renderPage()
    // minLength would stop the browser submitting; jsdom does not enforce it,
    // so this exercises the page's own check.
    await fill(user, container, { password: 'short' })

    expect(screen.getByText('Password must be at least 8 characters.')).toBeInTheDocument()
    expect(client.post).not.toHaveBeenCalled()
  })

  it('shows the backend message when registration fails', async () => {
    client.post.mockRejectedValue({ response: { data: { detail: 'Email already registered' } } })
    const user = userEvent.setup()
    const { container } = renderPage()

    await fill(user, container)

    await waitFor(() => expect(screen.getByText('Email already registered')).toBeInTheDocument())
    expect(useAuthStore.getState().token).toBeNull()
  })
})
