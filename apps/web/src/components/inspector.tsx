/* Context panels for the inspection workbench: location history and unit card. */
import { useMemo, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'

import type { InspectionDetail } from '../api/client'
import { useSpc, useTrace } from '../api/hooks'
import { fmt, PAINT_SWATCH, time } from '../lib/format'
import { useWidth } from './gauges'

/**
 * "Has this happened before?" The current pipeline measurements at this location
 * around the selected unit (production order), against the specification window.
 */
export function LocationHistory({ d }: { d: InspectionDetail }) {
  const spc = useSpc(d.location.code, 100)
  const nav = useNavigate()
  const [ref, W] = useWidth<HTMLDivElement>(300)
  const [hover, setHover] = useState<number | null>(null)
  const H = 96, padY = 8
  const win = useMemo(() => {
    const s = spc.data
    if (!s) return null
    const at = s.image_ids.indexOf(d.image_id)
    const span = 60
    const lo = Math.max(0, (at < 0 ? s.values.length : at) - span)
    const hi = Math.min(s.values.length, lo + 2 * span)
    const idx = Array.from({ length: hi - lo }, (_, i) => lo + i)
    const oot = (v: number) => v < d.location.lsl_mm || v > d.location.usl_mm
    const before = at < 0 ? [] : s.values.slice(0, at)
    return { s, at, idx, oot, nBefore: before.length, ootBefore: before.filter(oot).length }
  }, [spc.data, d.image_id, d.location])
  if (!win) return <section className="panel"><div className="panel-body"><div className="skeleton" style={{ height: 120 }} /></div></section>
  const { s, at, idx, oot } = win
  const vals = idx.map((i) => s.values[i])
  const ymin = Math.min(d.location.lsl_mm - 0.08, ...vals), ymax = Math.max(d.location.usl_mm + 0.08, ...vals)
  const x = (k: number) => 6 + (k / Math.max(1, idx.length - 1)) * (W - 12)
  const y = (v: number) => padY + (1 - (v - ymin) / (ymax - ymin)) * (H - 2 * padY)
  const path = vals.map((v, k) => `${k ? 'L' : 'M'}${x(k).toFixed(1)} ${y(v).toFixed(1)}`).join('')
  const h = hover !== null ? idx[hover] : null
  return (
    <section className="panel" aria-label="History at this location">
      <div className="panel-head"><h3>History at {d.location.code}</h3>
        <span className="aside">{win.ootBefore} of {win.nBefore} earlier out</span></div>
      <div className="panel-body">
        <div ref={ref} className="measure-w">
          <svg width={W} height={H} className="hist" role="img" aria-label={`Gap at ${d.location.code} for ${idx.length} units around ${d.serial}`}
            onMouseLeave={() => setHover(null)}
            onMouseMove={(e) => {
              const r = (e.currentTarget as SVGSVGElement).getBoundingClientRect()
              setHover(Math.max(0, Math.min(idx.length - 1, Math.round(((e.clientX - r.left - 6) / (W - 12)) * (idx.length - 1)))))
            }}
            onClick={() => h !== null && nav(`/inspect/${s.image_ids[h]}`)}>
            <rect x={0} y={y(d.location.usl_mm)} width={W} height={y(d.location.lsl_mm) - y(d.location.usl_mm)} className="h-band" />
            <line x1={0} x2={W} y1={y(d.location.nominal_mm)} y2={y(d.location.nominal_mm)} className="h-nom" />
            <path d={path} className="h-line" />
            {vals.map((v, k) => oot(v) ? <circle key={k} cx={x(k)} cy={y(v)} r={2.6} className="h-oot" /> : null)}
            {at >= 0 && idx.includes(at) && (
              <g className="h-cur"><line x1={x(idx.indexOf(at))} x2={x(idx.indexOf(at))} y1={0} y2={H} /><circle cx={x(idx.indexOf(at))} cy={y(s.values[at])} r={4.5} /></g>
            )}
            {h !== null && <line x1={x(hover!)} x2={x(hover!)} y1={0} y2={H} className="h-hover" />}
          </svg>
        </div>
        <div className="small muted hist-legend">
          {h !== null ? <span><b className="cond">{s.serials[h]}</b> {fmt(s.values[h], 3)} mm, built {time(s.built_at[h])} UTC. Click to open.</span>
            : <span>Band: specification {d.location.lsl_mm.toFixed(2)} to {d.location.usl_mm.toFixed(2)} mm. Amber: out of tolerance. Vertical line: this unit.</span>}
        </div>
      </div>
    </section>
  )
}

/** The unit behind the image: paint and the resources it passed through. */
export function UnitCard({ d }: { d: InspectionDetail }) {
  const t = useTrace(d.unit_id)
  const paint = d.paint
  return (
    <section className="panel unit-card" aria-label="Unit">
      <div className="panel-head"><h3>Unit {d.serial}</h3><Link className="aside" to={`/trace/${d.unit_id}`}>Full traceability</Link></div>
      <div className="panel-body">
        {paint && (
          <div className="paint-row">
            <span className="paint-chip" style={{ background: PAINT_SWATCH[paint.code] ?? '#999' }} />
            <span><b>{paint.name}</b><br /><span className="small muted">{paint.code}{paint.metallic ? ', metallic' : ''}</span></span>
          </div>
        )}
        <ol className="route-mini" aria-label="Route">
          {(t.data?.route ?? []).map((r) => (
            <li key={r.station} title={`${r.station_name}: ${r.equipment_name}`}>
              <span className="small muted">{r.station}</span>
              <b className="cond">{r.equipment}</b>
            </li>
          ))}
          {!t.data && <li className="skeleton" style={{ height: 34, width: '100%' }} />}
        </ol>
      </div>
    </section>
  )
}
