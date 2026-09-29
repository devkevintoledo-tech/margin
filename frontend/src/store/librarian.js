import { create } from 'zustand'
import { persist } from 'zustand/middleware'

/**
 * Librarian UI state that outlives a page. Edit mode is sticky: a librarian
 * turns it on once and it follows them from book to book, and across reloads,
 * until they press `[done]`.
 *
 * Nothing here grants anything. Every surface also checks `user.is_librarian`
 * (a reader on a shared browser may inherit `editMode: true`), and the API
 * checks again.
 */
const useLibrarianStore = create(
  persist(
    (set) => ({
      editMode: false,
      setEditMode: (value) => set({ editMode: !!value }),
    }),
    {
      name: 'margin-librarian',
      partialize: (state) => ({ editMode: state.editMode }),
    },
  ),
)

export default useLibrarianStore
