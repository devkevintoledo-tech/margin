import { describe, it, expect, beforeEach, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

vi.mock('../api/client', () => ({
  default: { get: vi.fn(), put: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
}))

import client from '../api/client'
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
  vi.clearAllMocks()
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
    user_id: 'u1',
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

describe('Post ownership', () => {
  const mine = {
    id: 'p1',
    user_id: 'u1',
    content: 'Le Guin never lets the reader settle.',
    score: 2,
    my_vote: 0,
    author: 'kevin',
    created_at: '2026-09-23T10:00:00Z',
    edited_at: null,
    deleted: false,
    replies: [],
  }

  function signIn(id = 'u1') {
    useAuthStore.setState({ user: { id, username: 'kevin' }, token: 't' })
  }

  it('shows edit and delete only to the author', () => {
    signIn('someone-else')
    const { unmount } = renderPost(mine)
    expect(screen.queryByRole('button', { name: 'edit' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'delete' })).not.toBeInTheDocument()
    unmount()

    signIn()
    renderPost(mine)
    expect(screen.getByRole('button', { name: 'edit' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'delete' })).toBeInTheDocument()
  })

  it('edits and saves the trimmed content', async () => {
    signIn()
    client.patch.mockResolvedValue({ data: { ...mine, content: 'Fixed.', thread_id: 't1' } })
    renderPost(mine)

    await userEvent.click(screen.getByRole('button', { name: 'edit' }))
    const box = screen.getByLabelText('Edit post')
    expect(box).toHaveValue(mine.content)
    await userEvent.clear(box)
    await userEvent.type(box, '  Fixed.  ')
    await userEvent.click(screen.getByRole('button', { name: 'save' }))

    expect(client.patch).toHaveBeenCalledWith('/posts/p1', { content: 'Fixed.' })
    await waitFor(() => expect(screen.queryByLabelText('Edit post')).not.toBeInTheDocument())
  })

  it('cancel restores the post without a request', async () => {
    signIn()
    renderPost(mine)
    await userEvent.click(screen.getByRole('button', { name: 'edit' }))
    await userEvent.click(screen.getByRole('button', { name: 'cancel' }))
    expect(screen.getByText(mine.content)).toBeInTheDocument()
    expect(client.patch).not.toHaveBeenCalled()
  })

  it('shows the server error when an edit fails', async () => {
    signIn()
    client.patch.mockRejectedValue({ response: { data: { detail: 'This post was deleted.' } } })
    renderPost(mine)
    await userEvent.click(screen.getByRole('button', { name: 'edit' }))
    await userEvent.click(screen.getByRole('button', { name: 'save' }))
    expect(await screen.findByText('This post was deleted.')).toBeInTheDocument()
  })

  it('blocks saving blank content', async () => {
    signIn()
    renderPost(mine)
    await userEvent.click(screen.getByRole('button', { name: 'edit' }))
    await userEvent.clear(screen.getByLabelText('Edit post'))
    expect(screen.getByRole('button', { name: 'save' })).toBeDisabled()
  })

  it('confirms inline, focusing "no" first', async () => {
    signIn()
    client.delete.mockResolvedValue({})
    renderPost(mine)

    await userEvent.click(screen.getByRole('button', { name: 'delete' }))
    expect(screen.getByText('rm post?')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'no, keep it' })).toHaveFocus()

    await userEvent.click(screen.getByRole('button', { name: 'yes, delete post' }))
    expect(client.delete).toHaveBeenCalledWith('/posts/p1')
  })

  it('Escape cancels the confirm', async () => {
    signIn()
    renderPost(mine)
    await userEvent.click(screen.getByRole('button', { name: 'delete' }))
    await userEvent.keyboard('{Escape}')
    expect(screen.queryByText('rm post?')).not.toBeInTheDocument()
    expect(client.delete).not.toHaveBeenCalled()
  })

  it('renders a tombstone with no author, no actions and a disabled vote', () => {
    signIn()
    renderPost({ ...mine, deleted: true, content: '', author: null, user_id: null })
    expect(screen.getAllByText('[deleted]')).toHaveLength(2)
    expect(screen.queryByText('kevin')).not.toBeInTheDocument()
    for (const name of ['edit', 'delete', 'reply']) {
      expect(screen.queryByRole('button', { name })).not.toBeInTheDocument()
    }
    screen.getAllByRole('button', { name: /vote/i }).forEach((b) => expect(b).toBeDisabled())
  })

  it('keeps the replies under a tombstone', () => {
    renderPost({
      ...mine,
      deleted: true, content: '', author: null, user_id: null,
      replies: [{ ...mine, id: 'p2', author: 'mara', user_id: 'u2', content: 'Still here.' }],
    })
    expect(screen.getByText('Still here.')).toBeInTheDocument()
  })

  it('marks an edited post', () => {
    renderPost({ ...mine, edited_at: '2026-09-23T11:00:00Z' })
    expect(screen.getByText('edited')).toBeInTheDocument()
  })
})
