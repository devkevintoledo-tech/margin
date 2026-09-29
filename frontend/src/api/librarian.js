import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import client from './client'

/** The counts a merge or split would affect, when the server asked to confirm. */
export function confirmationOf(error) {
  if (error?.response?.status !== 422) return null
  const detail = error.response.data?.detail
  return detail && !Array.isArray(detail) && typeof detail === 'object' ? detail.consequences ?? null : null
}

function useInvalidateCatalog() {
  const queryClient = useQueryClient()
  return () => {
    // A fix can move or merge a book anywhere: series pages, search results,
    // shelves and thread tags may all name its old room. Fixes are rare, so
    // everything is marked stale rather than guessing which keys.
    queryClient.invalidateQueries()
  }
}

export function useLibrarianAction() {
  const invalidate = useInvalidateCatalog()
  return useMutation({
    mutationFn: ({ path, body }) => client.post(`/librarian/${path}`, body).then((r) => r.data),
    onSuccess: invalidate,
  })
}

export function useRevertCorrection() {
  const invalidate = useInvalidateCatalog()
  return useMutation({
    mutationFn: (id) => client.post(`/librarian/corrections/${id}/revert`).then((r) => r.data),
    onSuccess: invalidate,
  })
}

export function useSeriesSearch(q) {
  return useQuery({
    queryKey: ['librarian', 'series-search', q],
    queryFn: () => client.get('/librarian/series-search', { params: { q } }).then((r) => r.data),
    enabled: q.trim().length > 1,
  })
}

export function useWorkEditions(workId) {
  return useQuery({
    queryKey: ['librarian', 'editions', workId],
    queryFn: () => client.get(`/librarian/works/${workId}/editions`).then((r) => r.data),
    enabled: !!workId,
  })
}

export function useCorrections({ runtimeOnly = false } = {}) {
  return useQuery({
    queryKey: ['librarian', 'corrections', runtimeOnly],
    queryFn: () =>
      client.get('/librarian/corrections', { params: runtimeOnly ? { runtime_only: true } : {} }).then((r) => r.data),
  })
}

/** Both books of a prospective merge, and what it would move. */
export function useMergePreview(sourceId, intoId) {
  return useQuery({
    queryKey: ['librarian', 'merge-preview', sourceId, intoId],
    queryFn: () =>
      client.get(`/librarian/works/${sourceId}/merge-preview`, { params: { into: intoId } }).then((r) => r.data),
    enabled: !!sourceId && !!intoId,
    retry: false, // a 409 (merged away) or 422 (same book) is an answer, not a blip
    // A swap asks for a new pair; keeping the old one mounted meanwhile keeps
    // focus on the swap button instead of dropping it out of the dialog.
    placeholderData: keepPreviousData,
  })
}
