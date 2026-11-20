import type { components } from './schema'

export type S = components['schemas']
export type InspectionListItem = S['InspectionListItem']
export type InspectionDetail = S['InspectionDetail']
export type InspectionRun = S['InspectionRunOut']
export type Location = S['LocationOut']
export type Overview = S['OverviewOut']
export type Spc = S['SpcOut']
export type StationComparison = S['StationComparisonOut']
export type Traceability = S['TraceabilityOut']
export type Investigation = S['InvestigationOut']
export type InvestigationListItem = S['InvestigationListItem']
export type Hypothesis = S['HypothesisOut']
export type Verification = S['VerificationOut']
export type PipelineRun = S['PipelineRunOut']
export type PipelineRunDetail = S['PipelineRunDetail']
export type PipelineError = S['PipelineErrorOut']
export type Benchmark = S['BenchmarkOut']
export type GroundTruth = S['GroundTruthComparison']
export type Health = S['Health']
export type Job = S['JobOut']
export type Page<T> = { items: T[]; total: number; page: number; page_size: number }

export const API_BASE: string = (import.meta.env.VITE_API_BASE as string | undefined)?.replace(/\/$/, '') ?? ''

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
    public details?: unknown,
    public requestId?: string | null,
  ) {
    super(message)
  }
}

type Params = Record<string, string | number | boolean | null | undefined>

function url(path: string, params?: Params): string {
  const qs = new URLSearchParams()
  for (const [k, v] of Object.entries(params ?? {})) if (v !== undefined && v !== null && v !== '') qs.set(k, String(v))
  const q = qs.toString()
  return `${API_BASE}/api/v1${path}${q ? `?${q}` : ''}`
}

async function request<T>(method: 'GET' | 'POST', path: string, params?: Params, body?: unknown): Promise<T> {
  let res: Response
  try {
    res = await fetch(url(path, params), {
      method,
      headers: body ? { 'Content-Type': 'application/json' } : undefined,
      body: body ? JSON.stringify(body) : undefined,
    })
  } catch {
    throw new ApiError(0, 'network_error', 'The API could not be reached. Check that the backend is running.')
  }
  if (!res.ok) {
    let err: { error?: { code: string; message: string; details?: unknown; request_id?: string } } = {}
    try {
      err = await res.json()
    } catch {
      /* non-JSON error */
    }
    throw new ApiError(res.status, err.error?.code ?? 'http_error', err.error?.message ?? res.statusText, err.error?.details, err.error?.request_id)
  }
  return (await res.json()) as T
}

/** Static-snapshot build (GitHub Pages): data comes from files exported by `python -m app.cli export-snapshot`. */
export const SNAPSHOT = import.meta.env.VITE_SNAPSHOT === '1'
export const SNAPSHOT_READONLY_MESSAGE =
  'This public demo is a static snapshot computed in CI, so it cannot run new computations. Run the full stack (see the README) to do this.'

const live = {
  get: <T>(path: string, params?: Params) => request<T>('GET', path, params),
  post: <T>(path: string, body: unknown) => request<T>('POST', path, undefined, body),
  imageUrl: (path: string) => `${API_BASE}${path}`,
  href: (path: string) => url(path),
}

export const api = SNAPSHOT
  ? {
      get: async <T>(path: string, params?: Params) => (await import('./snapshot')).snapshotGet(path, params) as Promise<T>,
      post: async <T>(): Promise<T> => {
        throw new ApiError(405, 'snapshot_readonly', SNAPSHOT_READONLY_MESSAGE)
      },
      imageUrl: (path: string) => snapshotAsset(path),
      href: (path: string) => snapshotAsset(`/api/v1${path}`),
    }
  : live

export type { Params }

/** Maps an API asset path to its exported file in the snapshot. */
export function snapshotAsset(path: string): string {
  const base = `${import.meta.env.BASE_URL}snapshot/`
  const rules: [RegExp, string][] = [
    [/^\/api\/v1\/inspections\/(\d+)\/image$/, 'images/$1.png'],
    [/^\/api\/v1\/evaluation\/vision\/cases\/(\d+)\/image$/, 'evaluation/cases/$1.png'],
    [/^\/api\/v1\/reports\/investigations\/(\d+)\.(md|json)$/, 'reports/$1.$2'],
  ]
  for (const [re, to] of rules) if (re.test(path)) return base + path.replace(re, to)
  return base + path.replace(/^\/api\/v1\//, '')
}
