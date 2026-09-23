import { useEffect } from 'react'
import { create } from 'zustand'

const EMPTY = { mode: 'HOME', path: '~', facts: [] }

/**
 * What the pinned status bar is currently showing.
 *
 * Pages declare their own status through `useStatusBar()` rather than rendering
 * the bar themselves, so the bar mounts once in App and nothing prop-drills
 * through the router.
 */
const useStatusStore = create((set) => ({
  ...EMPTY,
  setStatus: (status) => set(status),
  resetStatus: () => set({ ...EMPTY, facts: [] }),
}))

/**
 * Declare this page's status. Resets on unmount so a stale path can't outlive
 * the page that set it.
 *
 * `facts` is depended on by value, not identity — pages pass array literals,
 * which are new objects on every render.
 */
export function useStatusBar({ mode, path, facts = [] }) {
  const factsKey = facts.join('\u0000')

  useEffect(() => {
    useStatusStore.getState().setStatus({
      mode,
      path,
      facts: factsKey === '' ? [] : factsKey.split('\u0000'),
    })
    return () => useStatusStore.getState().resetStatus()
  }, [mode, path, factsKey])
}

export default useStatusStore
