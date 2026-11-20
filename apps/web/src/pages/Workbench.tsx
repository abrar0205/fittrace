import { useEffect, useMemo, useRef, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'

import { api, ApiError, type InspectionDetail, type InspectionRun } from '../api/client'
import { useCreateInvestigation, useGroundTruth, useInspection, useInspectionList, useLocations, useRerun } from '../api/hooks'
import { MicroGauge, RowProfile, ToleranceGauge } from '../components/gauges'
import { IconArrow, IconInvestigate, IconPlay, IconTrace } from '../components/icons'
import { InspectionViewer, type Layers, rowIntensity, useImagePixels } from '../components/InspectionViewer'
import { Sheet } from '../components/Shell'
import { Empty, ErrorState, Loading, StatusTag } from '../components/ui'
import { dt, fmt, signed } from '../lib/format'

const STATUS_FILTERS = [
  { value: '', label: 'All results' },
  { value: 'out_of_tolerance', label: 'Out of tolerance' },
  { value: 'in_tolerance', label: 'In tolerance' },
  { value: 'failed', label: 'Failed' },
]

function InspectionList({ selected, onSelect }: { selected?: number; onSelect: (id: number) => void }) {
  const locations = useLocations()
  const [location, setLocation] = useState('')
  const [status, setStatus] = useState('')
  const [q, setQ] = useState('')
  const list = useInspectionList({ location: location || undefined, status: status || undefined, q: q || undefined })
  const items = useMemo(() => list.data?.pages.flatMap((p) => p.items) ?? [], [list.data])
  const total = list.data?.pages[0]?.total
  const specs = useMemo(() => Object.fromEntries((locations.data ?? []).map((l) => [l.code, l])), [locations.data])
  const listRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (selected === undefined && items.length) onSelect(items[0].image_id)
  }, [items, selected, onSelect])

  useEffect(() => {
    listRef.current?.querySelector<HTMLElement>(`[data-id="${selected}"]`)?.scrollIntoView({ block: 'nearest' })
  }, [selected])

  const move = (d: number) => {
    const i = items.findIndex((x) => x.image_id === selected)
    const next = items[Math.max(0, Math.min(items.length - 1, i + d))]
    if (next) onSelect(next.image_id)
    if (i + d >= items.length - 3 && list.hasNextPage) void list.fetchNextPage()
  }

  return (
    <section className="panel wb-list" aria-label="Inspection list">
      <div className="wb-filters">
        <select className="select" value={location} onChange={(e) => setLocation(e.target.value)} aria-label="Measurement location">
          <option value="">All locations</option>
          {locations.data?.map((l) => <option key={l.code} value={l.code} title={l.name}>{l.code}</option>)}
        </select>
        <select className="select" value={status} onChange={(e) => setStatus(e.target.value)} aria-label="Result">
          {STATUS_FILTERS.map((s) => <option key={s.value} value={s.value}>{s.label}</option>)}
        </select>
        <input className="input" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Serial contains" aria-label="Filter by serial" />
        <div className="wb-count small muted" aria-live="polite">{total === undefined ? ' ' : `${total.toLocaleString()} inspections, newest first`}</div>
      </div>
      <div
        className="wb-items" ref={listRef} role="listbox" aria-label="Inspections" tabIndex={0}
        aria-activedescendant={selected ? `insp-${selected}` : undefined}
        onKeyDown={(e) => {
          if (e.key === 'ArrowDown' || e.key === 'j') { e.preventDefault(); move(1) }
          if (e.key === 'ArrowUp' || e.key === 'k') { e.preventDefault(); move(-1) }
        }}
        onScroll={(e) => {
          const el = e.currentTarget
          if (el.scrollTop + el.clientHeight > el.scrollHeight - 120 && list.hasNextPage && !list.isFetchingNextPage) void list.fetchNextPage()
        }}
      >
        {list.isLoading && <div style={{ padding: 12 }}><Loading height={320} /></div>}
        {list.error && <ErrorState error={list.error} />}
        {!list.isLoading && !items.length && !list.error && <Empty title="No inspections match">Clear the filters to see every inspection.</Empty>}
        {items.map((it) => {
          const spec = specs[it.location]
          const oot = it.tolerance_status === 'out_high' || it.tolerance_status === 'out_low'
          return (
            <div key={it.image_id} id={`insp-${it.image_id}`} data-id={it.image_id} role="option" aria-selected={it.image_id === selected}
              className={`wb-item ${it.image_id === selected ? 'selected' : ''}`} onClick={() => onSelect(it.image_id)}>
              <span className="wb-serial">{it.serial}</span>
              <span className="wb-loc">{it.location}</span>
              <span className={`wb-gap ${oot ? 'oot' : ''} ${it.run_status === 'failed' ? 'fail' : ''}`}>
                {it.run_status === 'failed' ? 'failed' : fmt(it.gap_mm, 3)}
              </span>
              {spec && <MicroGauge value={it.gap_mm} lsl={spec.lsl_mm} usl={spec.usl_mm} nominal={spec.nominal_mm} />}
            </div>
          )
        })}
        {list.isFetchingNextPage && <div className="small muted" style={{ padding: 10 }}>Loading more</div>}
      </div>
      <div className="panel-note small">Arrow keys or j / k step through results.</div>
    </section>
  )
}

const DEFAULT_LAYERS: Layers = { points: true, fits: true, roi: false, dimension: true, loupe: true }

export function Workbench() {
  const { imageId } = useParams()
  const nav = useNavigate()
  const id = imageId ? Number(imageId) : undefined
  const select = useMemo(() => (i: number) => nav(`/inspect/${i}`, { replace: id === undefined }), [nav, id])
  const detail = useInspection(id)
  const d = detail.data

  return (
    <Sheet no={2} title="Inspection workbench"
      lede="Each image is processed by the scan-line, sub-pixel gap algorithm. Edge points, fitted edges and the dimension are drawn from the stored run, not re-created in the browser."
      tb={{ dataset: d?.dataset_key, extra: [['Algorithm', d?.current_run ? `${d.current_run.algorithm.split('.').pop()} ${d.current_run.algorithm_version}` : '—']] }}>
      <div className="workbench">
        <InspectionList selected={id} onSelect={select} />
        {detail.error && !d ? <div className="panel"><ErrorState error={detail.error} /></div> : d ? <Inspector key={d.image_id} d={d} /> : <div className="panel"><Loading height={520} /></div>}
      </div>
    </Sheet>
  )
}

function Inspector({ d }: { d: InspectionDetail }) {
  const nav = useNavigate()
  const [runId, setRunId] = useState<number | null>(d.current_run?.id ?? null)
  const run: InspectionRun | null = d.runs.find((r) => r.id === runId) ?? d.current_run ?? null
  const [layers, setLayers] = useState(DEFAULT_LAYERS)
  const [replay, setReplay] = useState(0)
  const [hoverRow, setHoverRow] = useState<number | null>(null)
  const [showGt, setShowGt] = useState(false)
  const gt = useGroundTruth(d.image_id, showGt)
  const createInv = useCreateInvestigation()
  const mmPerPx = d.calibration?.mm_per_px ?? null
  const imgUrl = api.imageUrl(d.image_url)
  const { pixels } = useImagePixels(imgUrl)
  const meas = run?.measurement ?? null
  const oot = meas?.status === 'out_high' || meas?.status === 'out_low'

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement
      if (['INPUT', 'TEXTAREA', 'SELECT'].includes(t.tagName)) return
      if (e.key === '[' && d.neighbors.prev) nav(`/inspect/${d.neighbors.prev}`)
      if (e.key === ']' && d.neighbors.next) nav(`/inspect/${d.neighbors.next}`)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [d, nav])

  const profileRow = hoverRow ?? run?.overlay.measurement?.p1[1] ?? d.height / 2
  const nearest = run?.overlay.rows?.length
    ? run.overlay.rows.reduce((a, b) => (Math.abs(b.y - profileRow) < Math.abs(a.y - profileRow) ? b : a))
    : null
  const toggle = (k: keyof Layers) => setLayers((l) => ({ ...l, [k]: !l[k] }))
  const startInvestigation = () => createInv.mutate(d.image_id, { onSuccess: (inv) => nav(`/investigations/${inv.id}`) })

  return (
    <>
      <div className="wb-mid">
      <section className="panel wb-center" aria-label="Image and overlay">
        <div className="wb-toolbar">
          <div className="wb-layer-chips" role="group" aria-label="Overlay layers">
            {([['points', 'Edge points'], ['fits', 'Fitted edges'], ['dimension', 'Dimension'], ['roi', 'Region of interest'], ['loupe', 'Loupe']] as const).map(([k, label]) => (
              <button key={k} type="button" className="chip" aria-pressed={layers[k]} onClick={() => toggle(k)}><span className="swatch" />{label}</button>
            ))}
          </div>
          <div className="wb-nav">
            <button type="button" className="btn small ghost" onClick={() => setReplay((r) => r + 1)} disabled={!run}><IconPlay />Replay scan</button>
            <button type="button" className="btn small" disabled={!d.neighbors.prev} onClick={() => nav(`/inspect/${d.neighbors.prev}`)} aria-label="Previous inspection at this location" title="Previous ( [ )"><IconArrow /></button>
            <button type="button" className="btn small" disabled={!d.neighbors.next} onClick={() => nav(`/inspect/${d.neighbors.next}`)} aria-label="Next inspection at this location" title="Next ( ] )"><IconArrow style={{ transform: 'scaleX(-1)' }} /></button>
          </div>
        </div>
        <InspectionViewer src={imgUrl} run={run} location={d.location} mmPerPx={mmPerPx} layers={layers}
          revealKey={`${run?.id}-${replay}`} hoverRow={hoverRow} onHoverRow={setHoverRow} />
        <div className="wb-profile">
          <div className="wb-profile-head">
            <h3>Row intensity profile, y = {profileRow.toFixed(0)}</h3>
            <span className="small muted">
              Grey values read from the image. Gradient uses a 1-D Gaussian (σ = {Number(run?.algorithm_params.smoothing_sigma_px ?? 1.5).toFixed(1)} px) approximating the algorithm's smoothing.
            </span>
          </div>
          {pixels ? <RowProfile intensity={rowIntensity(pixels.data, profileRow)} row={profileRow} edges={nearest} sigma={Number(run?.algorithm_params.smoothing_sigma_px ?? 1.5)} /> : <Loading height={120} />}
        </div>
      </section>
      <RerunPanel d={d} selected={run?.id ?? null} onSelect={setRunId} />
      </div>

      <aside className="wb-side">
        <section className="panel readout-panel" aria-label="Measurement result">
          <div className="rp-head">
            <div>
              <h2 className="rp-serial">{d.serial}</h2>
              <div className="small muted">{d.location.code}, {d.location.name}</div>
            </div>
            <StatusTag status={run?.status === 'failed' ? 'failed' : meas?.status} />
          </div>
          {run?.status === 'ok' && meas ? (
            <div className="rp-value">
              <span className={`readout big ${oot ? 'oot' : ''}`}>{meas.gap_mm !== null ? fmt(meas.gap_mm, 3) : fmt(meas.gap_px, 2)}</span>
              <span className="rp-unit">{meas.gap_mm !== null ? 'mm' : 'px, uncalibrated'}</span>
              <div className="rp-dev">
                <span className={oot ? 'amber' : ''}>{signed(meas.deviation_mm)} mm</span> from nominal {d.location.nominal_mm.toFixed(2)} mm
              </div>
            </div>
          ) : run?.status === 'failed' ? (
            <div className="callout warn" style={{ margin: '4px 0 8px' }}>
              The algorithm did not return a measurement ({run.failure_code?.replace(/_/g, ' ')}). {run.failure_message}
            </div>
          ) : <Empty title="Not measured yet" />}
          <ToleranceGauge value={meas?.gap_mm ?? null} nominal={d.location.nominal_mm} lsl={d.location.lsl_mm} usl={d.location.usl_mm} se={meas?.std_error_mm} />
          <div className="rp-actions">
            {d.investigation_ids.length > 0 ? (
              <Link className="btn primary" to={`/investigations/${d.investigation_ids[0]}`}><IconInvestigate />Open investigation {d.investigation_ids[0]}</Link>
            ) : (
              <button type="button" className="btn primary" disabled={!oot || createInv.isPending || run?.id !== d.current_run?.id} onClick={startInvestigation}
                title={oot ? 'Analyse upstream process history for this deviation' : 'Investigations start from out-of-tolerance results'}>
                <IconInvestigate />{createInv.isPending ? 'Analysing history' : 'Start investigation'}
              </button>
            )}
            <Link className="btn" to={`/trace/${d.unit_id}`}><IconTrace />Trace unit</Link>
          </div>
          {createInv.error && <div className="callout warn small" role="alert">{(createInv.error as ApiError).message}</div>}
        </section>

        <section className="panel" aria-label="Measurement details">
          <div className="panel-head"><h3>Measurement record</h3><span className="aside">run {run?.id} {run?.is_current ? '(current)' : `(${run?.trigger})`}</span></div>
          <div className="panel-body">
            <dl className="kv">
              <dt>Captured</dt><dd>{dt(d.captured_at)}</dd>
              <dt>Calibration</dt><dd>{d.calibration ? `${d.calibration.reference}, ${d.calibration.mm_per_px} mm/px` : 'none, pixel result only'}</dd>
              <dt>Algorithm</dt><dd>{run ? `${run.algorithm} ${run.algorithm_version}` : '—'}</dd>
              <dt>Processing</dt><dd>{run ? `${run.duration_ms.toFixed(1)} ms` : '—'}</dd>
              <dt>Valid rows</dt><dd>{run ? `${(run.overlay.rows ?? []).filter((r) => r.inlier).length} of ${run.overlay.rows?.length ?? 0} with edges` : '—'}</dd>
              <dt>Edge angle</dt><dd>{meas ? `${fmt(meas.angle_deg, 2)}°` : '—'}</dd>
              <dt>Edge fit RMS</dt><dd>{run?.diagnostics.left_edge ? `${fmt((run.diagnostics.left_edge as any).rms_px, 3)} / ${fmt((run.diagnostics.right_edge as any).rms_px, 3)} px` : '—'}</dd>
              <dt title="Standard error of the mean of row-wise widths. A repeatability lower bound, not a full uncertainty budget.">Row std. error</dt>
              <dd>{meas?.std_error_mm ? `${(meas.std_error_mm * 1000).toFixed(2)} µm` : '—'}</dd>
              <dt>Noise estimate</dt><dd>{run?.diagnostics.noise_estimate_grey !== undefined ? `${run.diagnostics.noise_estimate_grey} grey levels` : '—'}</dd>
              <dt>Flags</dt><dd>{run?.flags.length ? run.flags.join(', ').replace(/_/g, ' ') : 'none'}</dd>
              <dt>Image</dt><dd className="small">{d.width} × {d.height} px, sha256 {d.sha256.slice(0, 12)}</dd>
            </dl>
          </div>
          <div className="panel-note">
            {!showGt ? (
              <button type="button" className="btn small" onClick={() => setShowGt(true)}>Compare with generator ground truth</button>
            ) : gt.data ? (
              <div className="gt">
                <div><span className="muted">True gap</span> <b>{fmt(gt.data.true_gap_mm, 4)} mm</b></div>
                <div><span className="muted">Error</span> <b>{signed(gt.data.error_um, 1)} µm</b></div>
                <p className="small muted">{gt.data.note}</p>
              </div>
            ) : gt.error ? <span className="small">{(gt.error as Error).message}</span> : <span className="small muted">Loading ground truth</span>}
          </div>
        </section>
      </aside>
    </>
  )
}

function RerunPanel({ d, selected, onSelect }: { d: InspectionDetail; selected: number | null; onSelect: (id: number) => void }) {
  const base = d.current_run?.algorithm_params ?? {}
  const [p, setP] = useState({
    smoothing_sigma_px: Number(base.smoothing_sigma_px ?? 1.5), row_step: Number(base.row_step ?? 4),
    min_edge_gradient: Number(base.min_edge_gradient ?? 6), outlier_mad_k: Number(base.outlier_mad_k ?? 3.5),
  })
  const rerun = useRerun(d.image_id)
  const fields: [keyof typeof p, string, number, number, number][] = [
    ['smoothing_sigma_px', 'Smoothing σ (px)', 0, 6, 0.1], ['row_step', 'Row step (px)', 1, 32, 1],
    ['min_edge_gradient', 'Min. edge gradient', 0.5, 60, 0.5], ['outlier_mad_k', 'Outlier limit (MAD × k)', 1.5, 10, 0.5],
  ]
  return (
    <section className="panel rerun" aria-label="Algorithm parameters and run history">
      <div className="rerun-params">
      <div className="panel-head"><h3>Re-run with different parameters</h3></div>
      <div className="panel-body">
        <form className="param-grid" onSubmit={(e) => { e.preventDefault(); rerun.mutate(p, { onSuccess: (r) => onSelect(r.id) }) }}>
          {fields.map(([k, label, min, max, step]) => (
            <label key={k} className="field">
              {label}
              <input className="input" type="number" min={min} max={max} step={step} value={p[k]}
                onChange={(e) => setP({ ...p, [k]: Number(e.target.value) })} />
            </label>
          ))}
          <button className="btn" type="submit" disabled={rerun.isPending} style={{ gridColumn: '1 / -1' }}>
            <IconPlay />{rerun.isPending ? 'Measuring' : 'Run measurement'}
          </button>
        </form>
        {rerun.error && <div className="callout warn small" role="alert" style={{ marginTop: 8 }}>{(rerun.error as ApiError).message}</div>}
        <p className="small muted" style={{ marginTop: 8 }}>Interactive runs are stored for audit but never replace the pipeline result used in analytics.</p>
      </div>
      </div>
      <div className="rerun-history">
      <div className="panel-head"><h3>Run history</h3><span className="aside">select a run to show its overlay</span></div>
      <table className="table" aria-label="Run history">
        <thead><tr><th>Run</th><th>Trigger</th><th className="r">Gap (mm)</th><th className="r">Processing</th></tr></thead>
        <tbody>
          {d.runs.map((r) => (
            <tr key={r.id} className={`clickable ${r.id === selected ? 'selected' : ''}`} onClick={() => onSelect(r.id)} aria-selected={r.id === selected}>
              <td className="id">{r.id}{r.is_current ? ' current' : ''}</td>
              <td>{r.trigger}</td>
              <td className="r">{r.status === 'ok' ? fmt(r.measurement?.gap_mm, 4) : r.failure_code}</td>
              <td className="r">{r.duration_ms.toFixed(1)} ms</td>
            </tr>
          ))}
        </tbody>
      </table>
      </div>
    </section>
  )
}
