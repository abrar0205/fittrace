import { afterEach, describe, expect, it, vi } from 'vitest'

import { api, ApiError } from './client'

afterEach(() => vi.restoreAllMocks())

describe('api client', () => {
  it('builds versioned URLs and drops empty params', async () => {
    const spy = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response('{"ok":1}', { status: 200 }))
    await api.get('/inspections', { status: 'out_of_tolerance', q: '', page: 2 })
    expect(spy.mock.calls[0][0]).toBe('/api/v1/inspections?status=out_of_tolerance&page=2')
  })
  it('maps the error envelope to ApiError', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify({ error: { code: 'within_tolerance', message: 'nope', request_id: 'r1' } }), { status: 409 }))
    await expect(api.post('/investigations', { image_id: 1 })).rejects.toMatchObject({ status: 409, code: 'within_tolerance', requestId: 'r1' })
  })
  it('reports network failures distinctly', async () => {
    vi.spyOn(globalThis, 'fetch').mockRejectedValue(new TypeError('failed'))
    const err = (await api.get("/health").catch((e: unknown) => e)) as ApiError
    expect(err).toBeInstanceOf(ApiError)
    expect(err.code).toBe('network_error')
  })
})
