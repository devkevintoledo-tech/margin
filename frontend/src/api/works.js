import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import client from './client'

export function useSearchWorks(query, { genres = [], author = '', yearFrom = '', yearTo = '' } = {}) {
  const filtered = genres.length > 0 || !!author || !!yearFrom || !!yearTo
  const params = {
    ...(query ? { q: query } : {}),
    ...(genres.length ? { genre: genres } : {}),
    ...(author ? { author } : {}),
    ...(yearFrom ? { year_from: yearFrom } : {}),
    ...(yearTo ? { year_to: yearTo } : {}),
  }
  return useQuery({
    queryKey: ['works', 'search', params],
    // indexes: null → genre=a&genre=b, the repeated form FastAPI reads as a list.
    queryFn: () => client.get('/works/search', { params, paramsSerializer: { indexes: null } }).then((r) => r.data),
    enabled: query.length > 1 || filtered,
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
