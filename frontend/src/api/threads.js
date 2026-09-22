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

export function useUpvoteThread() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ id }) => client.post(`/threads/${id}/upvote`).then((r) => r.data),
    onSuccess: (_, { id }) => {
      queryClient.invalidateQueries({ queryKey: ['threads', String(id)] })
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

export function useUpvotePost() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ id, threadId }) => client.post(`/posts/${id}/upvote`).then((r) => r.data),
    onSuccess: (_, { threadId }) => {
      if (threadId) {
        queryClient.invalidateQueries({ queryKey: ['threads', String(threadId)] })
      }
    },
  })
}
