import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import client from './client'

// Until the tree API lands, /genres/ is flat; a flat item is a parent with no children.
const asTree = (items) => items.map((g) => ({ ...g, children: g.children ?? [] }))

export function useGenreTree() {
  return useQuery({
    queryKey: ['genres'],
    queryFn: () => client.get('/genres/').then((r) => asTree(r.data)),
    staleTime: 10 * 60 * 1000, // the taxonomy changes with a deploy, not a click
  })
}

export function useWorkGenres(workId) {
  return useQuery({
    queryKey: ['work-genres', workId],
    queryFn: () => client.get(`/works/${workId}/genres`).then((r) => r.data),
    enabled: !!workId,
  })
}

// Optimistic: flip my_vote and nudge the count, then take the server's payload.
function toggled(payload, slug, name, on) {
  const found = payload.genres.some((g) => g.slug === slug)
  const genres = found
    ? payload.genres.map((g) => (g.slug === slug
      ? { ...g, my_vote: on, score: g.score + (on ? 1 : -1), direct_votes: g.direct_votes + (on ? 1 : -1) }
      : g))
    : on ? [...payload.genres, { slug, name, parent_slug: null, score: 1, direct_votes: 1, my_vote: true }] : payload.genres
  return {
    ...payload,
    source: on ? 'readers' : payload.source,
    genres,
    my_vote_count: (payload.my_vote_count ?? 0) + (on ? 1 : -1),
  }
}

function useGenreToggle(workId, on) {
  const queryClient = useQueryClient()
  const key = ['work-genres', workId]
  return useMutation({
    mutationFn: ({ slug }) => (on ? client.put : client.delete)(`/works/${workId}/genres/${slug}`).then((r) => r.data),
    onMutate: async ({ slug, name }) => {
      await queryClient.cancelQueries({ queryKey: key })
      const previous = queryClient.getQueryData(key)
      if (previous) queryClient.setQueryData(key, toggled(previous, slug, name, on))
      return { previous }
    },
    onError: (_error, _vars, context) => {
      if (context?.previous) queryClient.setQueryData(key, context.previous)
    },
    onSuccess: (data) => queryClient.setQueryData(key, data),
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: ['series'] })
      queryClient.invalidateQueries({ queryKey: ['works'] })
    },
  })
}

export const useVoteGenre = (workId) => useGenreToggle(workId, true)
export const useUnvoteGenre = (workId) => useGenreToggle(workId, false)

export function useGenre(slug) {
  return useQuery({
    queryKey: ['genres', slug],
    queryFn: () => client.get(`/genres/${slug}`).then((r) => r.data),
    enabled: !!slug,
  })
}

export function useGenreWorks(slug, sort = 'top') {
  return useQuery({
    queryKey: ['genres', slug, 'works', sort],
    queryFn: () => client.get(`/genres/${slug}/works`, { params: { sort } }).then((r) => r.data),
    enabled: !!slug,
  })
}

// Keyed like api/threads.js invalidates it: ['genres', roomSlug, 'threads'].
export function useGenreThreads(slug) {
  return useQuery({
    queryKey: ['genres', slug, 'threads'],
    queryFn: () => client.get(`/genres/${slug}/threads`).then((r) => r.data),
    enabled: !!slug,
  })
}

export function useVetoGenre(workId) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ slug, reason }) =>
      client.post(`/librarian/works/${workId}/genres/${slug}/veto`, { reason }).then((r) => r.data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['work-genres', workId] })
      queryClient.invalidateQueries({ queryKey: ['genres'] })
      queryClient.invalidateQueries({ queryKey: ['librarian', 'corrections'] })
    },
  })
}
