/*
 * Read-only data source for the static GitHub Pages build.
 *
 * Every file was written by `python -m app.cli export-snapshot`, which requests the
 * real API, so the JSON here is exactly what the API returned. The only logic in
 * this module is routing a request to its file and, for the two long lists, the
 * same filtering and pagination the API applies.
 */
import { ApiError, type InspectionListItem, type Params } from './client'

const BASE = `${import.meta.env.BASE_URL}snapshot/`
const cache = new Map<string, Promise<unknown>>()

export type SnapshotMeta = {
  generated_at: string
  commit: string | null
  run_url: string | null
  dataset: string | null
  spc_baselines: number[]
  counts: Record<string, number>
}

function load<T>(file: string): Promise<T> {
  if (!cache.has(file)) {
    const p = fetch(BASE + file).then(async (r) => {
      const type = r.headers.get('content-type') ?? ''
      if (!r.ok || !type.includes('json')) {
        cache.delete(file)
        throw new ApiError(404, 'not_in_snapshot', 'This view is not part of the static snapshot.')
      }
      return r.json()
    }, () => {
      cache.delete(file)
      throw new ApiError(0, 'network_error', 'The snapshot data could not be loaded.')
    })
    cache.set(file, p)
  }
  return cache.get(file) as Promise<T>
}

export const loadMeta = () => load<SnapshotMeta>('meta.json')

function paginate<T>(items: T[], params?: Params) {
  const page = Number(params?.page ?? 1)
  const size = Number(params?.page_size ?? 50)
  return { items: items.slice((page - 1) * size, page * size), total: items.length, page, page_size: size }
}

/** Same semantics as GET /api/v1/inspections (filters, ordering, pagination). */
function filterInspections(all: InspectionListItem[], p?: Params) {
  let xs = all
  if (p?.location) xs = xs.filter((x) => x.location === p.location)
  const st = p?.status as string | undefined
  if (st === 'out_of_tolerance') xs = xs.filter((x) => x.tolerance_status === 'out_low' || x.tolerance_status === 'out_high')
  else if (st === 'failed') xs = xs.filter((x) => x.run_status === 'failed')
  else if (st) xs = xs.filter((x) => x.tolerance_status === st)
  if (p?.q) {
    const q = String(p.q).trim().toLowerCase()
    xs = xs.filter((x) => x.serial.toLowerCase().includes(q))
  }
  const t = (x: InspectionListItem) => new Date(x.captured_at).getTime()
  xs = [...xs].sort((a, b) => (p?.order === 'asc' ? t(a) - t(b) : t(b) - t(a)) || a.image_id - b.image_id)
  return paginate(xs, p)
}

export async function snapshotGet(path: string, params?: Params): Promise<unknown> {
  let m: RegExpMatchArray | null
  if (path === '/health') {
    const h = await load<Record<string, unknown>>('health.json')
    return { ...h, demo_readonly: true }
  }
  if (['/datasets', '/locations', '/overview'].includes(path)) return load(`${path.slice(1)}.json`)
  if (path === '/inspections') return filterInspections(await load<InspectionListItem[]>('inspections/index.json'), params)
  if ((m = path.match(/^\/inspections\/(\d+)$/))) return load(`inspections/${m[1]}.json`)
  if ((m = path.match(/^\/inspections\/(\d+)\/ground-truth$/))) return load(`inspections/${m[1]}.gt.json`)
  if (path === '/analytics/spc') return load(`analytics/spc/${params?.location}/${params?.baseline_n}.json`)
  if ((m = path.match(/^\/analytics\/stations\/(S\d+)$/))) return load(`analytics/stations/${params?.location}/${m[1]}.json`)
  if ((m = path.match(/^\/units\/(\d+)\/traceability$/))) return load(`units/${m[1]}.json`)
  if (path === '/investigations') return paginate(await load<unknown[]>('investigations/index.json'), params)
  if ((m = path.match(/^\/investigations\/(\d+)$/))) return load(`investigations/${m[1]}.json`)
  if ((m = path.match(/^\/simulations\/verifications\/(\d+)$/))) return load(`verifications/${m[1]}.json`)
  if (path === '/pipelines/runs') return paginate(await load<unknown[]>('pipelines/index.json'), params)
  if ((m = path.match(/^\/pipelines\/runs\/(\d+)$/))) return load(`pipelines/${m[1]}.json`)
  if ((m = path.match(/^\/pipelines\/runs\/(\d+)\/errors$/))) return paginate(await load<unknown[]>(`pipelines/${m[1]}.errors.json`), params)
  if ((m = path.match(/^\/evaluation\/(vision|investigation)$/))) return load(`evaluation/${m[1]}.json`)
  throw new ApiError(404, 'not_in_snapshot', 'This view is not part of the static snapshot.')
}
