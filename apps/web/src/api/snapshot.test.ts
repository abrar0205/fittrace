import { afterEach, describe, expect, it, vi } from 'vitest'

const rows = [
  { image_id: 1, serial: 'SIM-00001', unit_id: 1, location: 'FD-FF-M', captured_at: '2026-02-09T06:00:00Z', run_status: 'ok', gap_mm: 4.0, deviation_mm: 0, tolerance_status: 'in_tolerance', flags: [] },
  { image_id: 2, serial: 'SIM-00001', unit_id: 1, location: 'FD-RD-M', captured_at: '2026-02-09T06:00:00Z', run_status: 'ok', gap_mm: 4.6, deviation_mm: 0.1, tolerance_status: 'in_tolerance', flags: [] },
  { image_id: 3, serial: 'SIM-00002', unit_id: 2, location: 'FD-FF-M', captured_at: '2026-02-09T06:04:00Z', run_status: 'ok', gap_mm: 4.6, deviation_mm: 0.6, tolerance_status: 'out_high', flags: [] },
  { image_id: 4, serial: 'SIM-00003', unit_id: 3, location: 'FD-FF-M', captured_at: '2026-02-09T06:08:00Z', run_status: 'failed', gap_mm: null, deviation_mm: null, tolerance_status: null, flags: [] },
]

afterEach(() => vi.restoreAllMocks())

describe('snapshot adapter', () => {
  it('applies the API list semantics to the exported inspection index', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify(rows), { headers: { 'content-type': 'application/json' } }))
    const { snapshotGet } = await import('./snapshot')
    const all: any = await snapshotGet('/inspections', { page: 1, page_size: 2 })
    expect(all.total).toBe(4)
    expect(all.items.map((x: any) => x.image_id)).toEqual([4, 3])
    const oot: any = await snapshotGet('/inspections', { status: 'out_of_tolerance' })
    expect(oot.items.map((x: any) => x.image_id)).toEqual([3])
    const failed: any = await snapshotGet('/inspections', { status: 'failed' })
    expect(failed.items.map((x: any) => x.image_id)).toEqual([4])
    const asc: any = await snapshotGet('/inspections', { location: 'FD-FF-M', order: 'asc', q: 'sim-0000' })
    expect(asc.items.map((x: any) => x.image_id)).toEqual([1, 3, 4])
  })

  it('reports views missing from the snapshot instead of failing silently', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response('<html>', { status: 404, headers: { 'content-type': 'text/html' } }))
    const { snapshotGet } = await import('./snapshot')
    await expect(snapshotGet('/units/999999/traceability')).rejects.toMatchObject({ code: 'not_in_snapshot' })
    await expect(snapshotGet('/jobs/1')).rejects.toMatchObject({ code: 'not_in_snapshot' })
  })
})
