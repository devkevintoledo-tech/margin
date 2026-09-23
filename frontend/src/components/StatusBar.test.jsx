import { describe, it, expect, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import useStatusStore, { useStatusBar } from '../store/status'
import useAuthStore from '../store/auth'
import StatusBar from './StatusBar'

function Page({ mode, path, facts }) {
  useStatusBar({ mode, path, facts })
  return null
}

beforeEach(() => {
  useStatusStore.getState().resetStatus()
  const { setAuth, logout } = useAuthStore.getState()
  useAuthStore.setState({ user: null, token: null, setAuth, logout }, true)
})

describe('StatusBar', () => {
  it('shows the mode and path a page declares', () => {
    render(
      <>
        <Page mode="BOOK" path="~/books/the-dispossessed" facts={['2 threads']} />
        <StatusBar />
      </>,
    )
    expect(screen.getByText('BOOK')).toBeInTheDocument()
    expect(screen.getByText('~/books/the-dispossessed')).toBeInTheDocument()
    expect(screen.getByText('2 threads')).toBeInTheDocument()
  })

  it('shows the signed-in username', () => {
    const { setAuth, logout } = useAuthStore.getState()
    useAuthStore.setState({ user: { username: 'ada' }, token: 't', setAuth, logout }, true)
    render(
      <>
        <Page mode="HOME" path="~" facts={[]} />
        <StatusBar />
      </>,
    )
    expect(screen.getByText('ada')).toBeInTheDocument()
  })

  it('resets when the declaring page unmounts', () => {
    const { unmount } = render(<Page mode="THREAD" path="~/threads/1" facts={[]} />)
    expect(useStatusStore.getState().mode).toBe('THREAD')
    unmount()
    expect(useStatusStore.getState().mode).toBe('HOME')
    expect(useStatusStore.getState().path).toBe('~')
  })

  it('is exposed to assistive tech as a status region', () => {
    render(<StatusBar />)
    expect(screen.getByRole('status')).toBeInTheDocument()
  })
})
