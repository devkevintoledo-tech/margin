import { describe, it, expect, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import useAuthStore from '../store/auth'
import Post, { relativeTime } from './Post'

function renderPost(post) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <Post post={post} threadId="t1" depth={0} />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  const { setAuth, logout } = useAuthStore.getState()
  useAuthStore.setState({ user: null, token: null, setAuth, logout }, true)
})

describe('relativeTime', () => {
  const now = new Date('2026-09-23T12:00:00Z')

  it('renders hours within a day', () => {
    expect(relativeTime('2026-09-23T10:00:00Z', now)).toBe('2h')
  })

  it('renders days within a month', () => {
    expect(relativeTime('2026-09-18T12:00:00Z', now)).toBe('5d')
  })

  it('renders months beyond thirty days', () => {
    expect(relativeTime('2026-06-23T12:00:00Z', now)).toBe('3mo')
  })

  it('renders minutes under an hour', () => {
    expect(relativeTime('2026-09-23T11:20:00Z', now)).toBe('40m')
  })

  it('returns an empty string for missing dates', () => {
    expect(relativeTime(null, now)).toBe('')
  })
})

describe('Post', () => {
  const post = {
    id: 'p1',
    content: 'Le Guin never lets the reader settle.',
    score: 8,
    my_vote: 0,
    author: 'kevin',
    created_at: '2026-09-23T10:00:00Z',
    replies: [],
  }

  it('shows the author and the post body', () => {
    renderPost(post)
    expect(screen.getByText('kevin')).toBeInTheDocument()
    expect(screen.getByText(/never lets the reader settle/)).toBeInTheDocument()
  })

  it('exposes the absolute timestamp through a tooltip', () => {
    renderPost(post)
    expect(screen.getByRole('tooltip')).toBeInTheDocument()
  })

  it('draws a tree elbow for replies and hides it from assistive tech', () => {
    const { container } = renderPost({
      ...post,
      replies: [{ ...post, id: 'p2', author: 'mara', replies: [] }],
    })
    const elbow = container.querySelector('[data-testid="tree-elbow"]')
    expect(elbow).toBeInTheDocument()
    expect(elbow).toHaveAttribute('aria-hidden', 'true')
  })
})
