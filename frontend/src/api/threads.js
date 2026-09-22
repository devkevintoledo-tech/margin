import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import client from './client'

export function useThread(id) {
  return useQuery({
    queryKey: ['threads', id],
    queryFn: () => client.get(`/threads/${id}`).then((r) => r.data),
    enabled: !!id,
  })
}

export function useCreateThread() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (payload) => client.post('/threads/', payload).then((r) => r.data),
    onSuccess: (data) => {
      if (data.book_id) {
        queryClient.invalidateQueries({ queryKey: ['books', String(data.book_id), 'threads'] })
      }
      if (data.genre_slug) {
        queryClient.invalidateQueries({ queryKey: ['genres', data.genre_slug, 'threads'] })
      }
    },
  })
}

export function useVoteThread() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ id, value }) =>
      client.put(`/threads/${id}/vote`, { value }).then((r) => r.data),
    // Voting from a list has to refresh that list, or the score the reader
    // just changed stays stale on screen.
    onSuccess: (_, { id, bookId, genreSlug }) => {
      queryClient.invalidateQueries({ queryKey: ['threads', String(id)] })
      if (bookId) {
        queryClient.invalidateQueries({ queryKey: ['books', String(bookId), 'threads'] })
      }
      if (genreSlug) {
        queryClient.invalidateQueries({ queryKey: ['genres', genreSlug, 'threads'] })
      }
    },
  })
}

export function useCreatePost() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (payload) => client.post('/posts/', payload).then((r) => r.data),
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ['threads', String(data.thread_id)] })
    },
  })
}

export function useVotePost() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ id, value }) =>
      client.put(`/posts/${id}/vote`, { value }).then((r) => r.data),
    onSuccess: (_, { threadId }) => {
      if (threadId) {
        queryClient.invalidateQueries({ queryKey: ['threads', String(threadId)] })
      }
    },
  })
}
