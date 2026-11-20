import { keepPreviousData, useInfiniteQuery, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import {
  api,
  type Benchmark,
  type GroundTruth,
  type Health,
  type InspectionDetail,
  type InspectionListItem,
  type InspectionRun,
  type Investigation,
  type InvestigationListItem,
  type Location,
  type Overview,
  type Page,
  type PipelineError,
  type PipelineRun,
  type PipelineRunDetail,
  type Spc,
  type StationComparison,
  type Traceability,
  type Verification,
} from './client'

export const useHealth = () =>
  useQuery({ queryKey: ['health'], queryFn: () => api.get<Health>('/health'), refetchInterval: 30_000, retry: 0 })

export const useLocations = () =>
  useQuery({ queryKey: ['locations'], queryFn: () => api.get<Location[]>('/locations'), staleTime: Infinity })

export const useOverview = () => useQuery({ queryKey: ['overview'], queryFn: () => api.get<Overview>('/overview') })

export type InspectionFilter = { location?: string; status?: string; q?: string }

export function useInspectionList(f: InspectionFilter) {
  return useInfiniteQuery({
    queryKey: ['inspections', f],
    initialPageParam: 1,
    queryFn: ({ pageParam }) => api.get<Page<InspectionListItem>>('/inspections', { ...f, page: pageParam, page_size: 60 }),
    getNextPageParam: (last) => (last.page * last.page_size < last.total ? last.page + 1 : undefined),
    placeholderData: keepPreviousData,
  })
}

export const useInspection = (id?: number) =>
  useQuery({
    queryKey: ['inspection', id],
    queryFn: () => api.get<InspectionDetail>(`/inspections/${id}`),
    enabled: id !== undefined,
    placeholderData: keepPreviousData,
  })

export const useGroundTruth = (id: number | undefined, enabled: boolean) =>
  useQuery({ queryKey: ['gt', id], queryFn: () => api.get<GroundTruth>(`/inspections/${id}/ground-truth`), enabled: enabled && !!id })

export function useRerun(id: number) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: Record<string, number>) => api.post<InspectionRun>(`/inspections/${id}/runs`, body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['inspection', id] }),
  })
}

export const useSpc = (location: string, baseline: number) =>
  useQuery({
    queryKey: ['spc', location, baseline],
    queryFn: () => api.get<Spc>('/analytics/spc', { location, baseline_n: baseline }),
    placeholderData: keepPreviousData,
  })

export const useStation = (location: string, station: string) =>
  useQuery({
    queryKey: ['station', location, station],
    queryFn: () => api.get<StationComparison>(`/analytics/stations/${station}`, { location }),
    placeholderData: keepPreviousData,
  })

export const useTrace = (unitId?: number) =>
  useQuery({
    queryKey: ['trace', unitId],
    queryFn: () => api.get<Traceability>(`/units/${unitId}/traceability`),
    enabled: unitId !== undefined,
  })

export const useInvestigations = () =>
  useQuery({ queryKey: ['investigations'], queryFn: () => api.get<Page<InvestigationListItem>>('/investigations', { page_size: 50 }) })

export const useInvestigation = (id?: number) =>
  useQuery({ queryKey: ['investigation', id], queryFn: () => api.get<Investigation>(`/investigations/${id}`), enabled: !!id })

export function useCreateInvestigation() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (image_id: number) => api.post<Investigation>('/investigations', { image_id }),
    onSuccess: (inv) => {
      qc.setQueryData(['investigation', inv.id], inv)
      qc.invalidateQueries({ queryKey: ['investigations'] })
      qc.invalidateQueries({ queryKey: ['inspection', inv.trigger.image_id] })
    },
  })
}

export function useCreateVerification() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (b: { investigation_id: number; target_code: string; kind: string; n_units: number; seed: number }) =>
      api.post<Verification>('/simulations/corrective-actions', b),
    onSuccess: (v) => qc.invalidateQueries({ queryKey: ['investigation', v.investigation_id] }),
  })
}

export const useVerification = (id?: number) =>
  useQuery({
    queryKey: ['verification', id],
    queryFn: () => api.get<Verification>(`/simulations/verifications/${id}`),
    enabled: !!id,
    refetchInterval: (q) => (q.state.data && ['queued', 'running'].includes(q.state.data.status) ? 1000 : false),
  })

export const usePipelineRuns = () =>
  useQuery({
    queryKey: ['pipeline-runs'],
    queryFn: () => api.get<Page<PipelineRun>>('/pipelines/runs', { page_size: 100 }),
    refetchInterval: (q) => (q.state.data?.items.some((r) => r.status === 'running') ? 2000 : false),
  })

export const usePipelineRun = (id?: number) =>
  useQuery({ queryKey: ['pipeline-run', id], queryFn: () => api.get<PipelineRunDetail>(`/pipelines/runs/${id}`), enabled: !!id })

export const usePipelineErrors = (id: number | undefined, page: number) =>
  useQuery({
    queryKey: ['pipeline-errors', id, page],
    queryFn: () => api.get<Page<PipelineError>>(`/pipelines/runs/${id}/errors`, { page, page_size: 25 }),
    enabled: !!id,
    placeholderData: keepPreviousData,
  })

export function useRetryRun() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: number) => api.post<{ id: number }>(`/pipelines/runs/${id}/retry`, {}),
    onSuccess: () => setTimeout(() => qc.invalidateQueries({ queryKey: ['pipeline-runs'] }), 1500),
  })
}

export const useBenchmark = (kind: 'vision' | 'investigation') =>
  useQuery({ queryKey: ['bench', kind], queryFn: () => api.get<Benchmark>(`/evaluation/${kind}`), staleTime: 60_000 })

export const useDatasets = () =>
  useQuery({ queryKey: ['datasets'], queryFn: () => api.get<import('./client').S['DatasetOut'][]>('/datasets'), staleTime: 60_000 })

/** Key of the dataset the API serves by default (first synthetic dataset). */
export const useDefaultDatasetKey = () => {
  const q = useDatasets()
  return q.data?.find((d) => d.kind === 'synthetic')?.key ?? q.data?.[0]?.key
}

/** Snapshot provenance (static GitHub Pages build only). */
export const useSnapshotMeta = () =>
  useQuery({
    queryKey: ['snapshot-meta'],
    queryFn: async () => (await import('./snapshot')).loadMeta(),
    enabled: import.meta.env.VITE_SNAPSHOT === '1',
    staleTime: Infinity,
  })
