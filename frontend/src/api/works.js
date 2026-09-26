import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import client from './client'

export function useSearchWorks(query) {
  return useQuery({
    queryKey: ['works', 'search', query],
    queryFn: () => client.get('/works/search', { params: { q: query } }).then((r) => r.data),
    enabled: query.length > 1,
  })
}

export function useWork(id) {
  return useQuery({
    queryKey: ['works', id],
    queryFn: () => client.get(`/works/${id}`).then((r) => r.data),
    enabled: !!id,
  })
}

export function useAddToShelf() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ id, status }) => client.post(`/works/${id}/shelf`, { status }).then((r) => r.data),
    onSuccess: (_, { id }) => {
      queryClient.invalidateQueries({ queryKey: ['works', id] })
      queryClient.invalidateQueries({ queryKey: ['me'] })
      queryClient.invalidateQueries({ queryKey: ['series'] })
    },
  })
}

export function useUpdateShelf() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ id, status }) => client.put(`/works/${id}/shelf`, { status }).then((r) => r.data),
    onSuccess: (_, { id }) => {
      queryClient.invalidateQueries({ queryKey: ['works', id] })
      queryClient.invalidateQueries({ queryKey: ['me'] })
      queryClient.invalidateQueries({ queryKey: ['series'] })
    },
  })
}

export function useRemoveFromShelf() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ id }) => client.delete(`/works/${id}/shelf`).then((r) => r.data),
    onSuccess: (_, { id }) => {
      queryClient.invalidateQueries({ queryKey: ['works', id] })
      queryClient.invalidateQueries({ queryKey: ['me'] })
      queryClient.invalidateQueries({ queryKey: ['series'] })
    },
  })
}
