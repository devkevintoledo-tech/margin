import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import client from './client'

export function seriesHref(work) {
  // A work without a series predates the backfill; its legacy URL redirects.
  return work.series ? `/series/${work.series.slug}?book=${work.id}` : `/works/${work.id}`
}

export function useSeries(slug) {
  return useQuery({
    queryKey: ['series', slug],
    queryFn: () => client.get(`/series/${slug}`).then((r) => r.data),
    enabled: !!slug,
  })
}

export function useSeriesThreads(slug, workId) {
  return useQuery({
    queryKey: ['series', slug, 'threads', workId ?? 'all'],
    queryFn: () =>
      client
        .get(`/series/${slug}/threads`, { params: workId ? { work_id: workId } : {} })
        .then((r) => r.data),
    enabled: !!slug,
  })
}

export function useCreateSeriesThread(slug) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (payload) => client.post(`/series/${slug}/threads`, payload).then((r) => r.data),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['series', slug, 'threads'] }),
  })
}
