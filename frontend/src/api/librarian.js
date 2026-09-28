import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
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
    // A fix can move a book between rooms, so every series page may be stale.
    queryClient.invalidateQueries({ queryKey: ['series'] })
    queryClient.invalidateQueries({ queryKey: ['librarian'] })
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
