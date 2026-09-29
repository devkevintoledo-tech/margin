import { describe, it, expect, beforeEach } from 'vitest'
import useLibrarianStore from './librarian'

beforeEach(() => {
  localStorage.clear()
  useLibrarianStore.setState({ editMode: false })
})

describe('librarian store', () => {
  it('starts out of edit mode', () => {
    expect(useLibrarianStore.getState().editMode).toBe(false)
  })

  it('persists edit mode under margin-librarian', () => {
    useLibrarianStore.getState().setEditMode(true)
    const persisted = JSON.parse(localStorage.getItem('margin-librarian'))
    expect(persisted.state).toEqual({ editMode: true })
  })

  it('stores a boolean whatever it is given', () => {
    useLibrarianStore.getState().setEditMode('1')
    expect(useLibrarianStore.getState().editMode).toBe(true)
    useLibrarianStore.getState().setEditMode(undefined)
    expect(useLibrarianStore.getState().editMode).toBe(false)
  })

  it('comes back after a reload', async () => {
    localStorage.setItem('margin-librarian', JSON.stringify({ state: { editMode: true }, version: 0 }))
    await useLibrarianStore.persist.rehydrate()
    expect(useLibrarianStore.getState().editMode).toBe(true)
  })
})
