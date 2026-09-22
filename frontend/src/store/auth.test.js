import { describe, it, expect, beforeEach } from 'vitest'
import useAuthStore from './auth'

beforeEach(() => {
  localStorage.clear()
  useAuthStore.getState().logout()
})

describe('auth store persistence', () => {
  it('writes user and token to localStorage on setAuth', () => {
    useAuthStore.getState().setAuth({ id: '1', username: 'ada' }, 'tok-123')

    const persisted = JSON.parse(localStorage.getItem('margin-auth'))
    expect(persisted.state.token).toBe('tok-123')
    expect(persisted.state.user).toEqual({ id: '1', username: 'ada' })
  })

  it('clears persisted token on logout', () => {
    useAuthStore.getState().setAuth({ id: '1', username: 'ada' }, 'tok-123')
    useAuthStore.getState().logout()

    const persisted = JSON.parse(localStorage.getItem('margin-auth'))
    expect(persisted.state.token).toBeNull()
    expect(persisted.state.user).toBeNull()
  })
})
