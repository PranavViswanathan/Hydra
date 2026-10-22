import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect } from 'react'

import { api } from '../lib/api'

export function useSession() {
  return useQuery({ queryKey: ['session'], queryFn: () => api.session() })
}

export function useRepos() {
  return useQuery({ queryKey: ['repos'], queryFn: () => api.repos() })
}

export function useRepo(repoId: string) {
  return useQuery({ queryKey: ['repo', repoId], queryFn: () => api.repo(repoId) })
}

export function useVulnerabilities(repoId: string) {
  return useQuery({ queryKey: ['vulns', repoId], queryFn: () => api.vulnerabilities(repoId) })
}

export function useEdges(repoId: string) {
  return useQuery({ queryKey: ['edges', repoId], queryFn: () => api.edges(repoId) })
}

export function useRuns(repoId: string) {
  return useQuery({ queryKey: ['runs', repoId], queryFn: () => api.runs(repoId) })
}

export function useEvents(runId: string | null) {
  return useQuery({
    queryKey: ['events', runId],
    queryFn: () => (runId ? api.events(runId) : Promise.resolve([])),
    enabled: runId !== null,
  })
}

export function useScanNow() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (repoId: string) => api.scanNow(repoId),
    onSuccess: () => queryClient.invalidateQueries(),
  })
}

export function useFixNow() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (repoId: string) => api.fixNow(repoId),
    onSuccess: () => queryClient.invalidateQueries(),
  })
}

/**
 * §14.2: anything the agent changes shows up without a refresh. One
 * subscription for the app; every query is invalidated when something moves.
 */
export function useLiveUpdates(): void {
  const queryClient = useQueryClient()

  useEffect(() => {
    const stop = api.watch(() => {
      void queryClient.invalidateQueries()
    })
    return () => stop()
  }, [queryClient])
}
