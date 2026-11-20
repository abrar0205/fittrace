/*
 * Line map: the simulated body-in-white line as a process flow. Each fixture or
 * nutrunner tile shows the gap distribution of the units it built (p05 to p95 bar,
 * median tick, mean dot) on one scale shared by every tile, against the
 * specification window. Colours match the station comparison charts.
 */
import { useNavigate } from 'react-router-dom'

import type { Location, StationComparison } from '../api/client'
import { useStation } from '../api/hooks'
import { fmt, int, pct } from '../lib/format'
import { useWidth } from './gauges'

const SERIES = ['var(--series-1)', 'var(--series-2)', 'var(--series-3)']
const STATIONS = [
  { code: 'S10', name: 'Underbody framing', kind: 'fixtures' },
  { code: 'S20', name: 'Side-aperture framing', kind: 'fixtures' },
  { code: 'S30', name: 'Door hang', kind: 'nutrunners' },
]

function Strip({ g, lo, hi, loc, color }: { g: StationComparison['groups'][number]; lo: number; hi: number; loc: Location; color: string }) {
  const [ref, W] = useWidth<HTMLDivElement>(160)
  const H = 30
  const x = (v: number) => 4 + ((v - lo) / (hi - lo)) * (W - 8)
  return (
    <div ref={ref} className="measure-w">
      <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`} className="lm-strip" aria-hidden>
        <rect x={x(loc.lsl_mm)} y={4} width={x(loc.usl_mm) - x(loc.lsl_mm)} height={H - 12} className="lm-spec" />
        <line x1={x(loc.nominal_mm)} x2={x(loc.nominal_mm)} y1={2} y2={H - 6} className="lm-nom" />
        <line x1={x(g.p05_mm)} x2={x(g.p95_mm)} y1={13} y2={13} style={{ stroke: color }} className="lm-range" />
        <line x1={x(g.median_mm)} x2={x(g.median_mm)} y1={8} y2={18} style={{ stroke: color }} className="lm-med" />
        <circle cx={x(g.mean_mm)} cy={13} r={3.5} style={{ fill: color }} className="lm-mean" />
        <text x={x(loc.lsl_mm)} y={H - 1} textAnchor="middle" className="lm-lbl">{loc.lsl_mm.toFixed(1)}</text>
        <text x={x(loc.usl_mm)} y={H - 1} textAnchor="middle" className="lm-lbl">{loc.usl_mm.toFixed(1)}</text>
      </svg>
    </div>
  )
}

export function LineMap({ location, inspection }: {
  location: Location & { measured?: number; out_of_tolerance?: number; failed?: number }
  inspection: { measured: number; oot: number; failed: number }
}) {
  const nav = useNavigate()
  const s10 = useStation(location.code, 'S10')
  const s20 = useStation(location.code, 'S20')
  const s30 = useStation(location.code, 'S30')
  const data = [s10.data, s20.data, s30.data]
  const groups = data.flatMap((d) => d?.groups ?? [])
  const lo = Math.min(location.lsl_mm, ...groups.map((g) => g.p05_mm)) - 0.08
  const hi = Math.max(location.usl_mm, ...groups.map((g) => g.p95_mm)) + 0.08
  const ready = data.every(Boolean)

  return (
    <div className="linemap" role="group" aria-label={`Line map for ${location.code}`}>
      {STATIONS.map((st, si) => {
        const d = data[si]
        return (
          <section key={st.code} className="lm-station" aria-label={`${st.code} ${st.name}`}>
            <header><b className="cond">{st.code}</b> {st.name}</header>
            <div className="lm-tiles">
              {!ready || !d ? <div className="skeleton" style={{ height: 96 }} /> : d.groups.map((g, i) => (
                <button key={g.equipment} type="button" className="lm-tile"
                  onClick={() => nav(`/analytics?location=${location.code}&station=${st.code}`)}
                  aria-label={`${g.equipment}: ${g.n} units, mean gap ${fmt(g.mean_mm)} mm, ${g.n_oot} out of tolerance. Open station comparison.`}>
                  <span className="lm-eq"><i style={{ background: SERIES[i % 3] }} />{g.equipment}</span>
                  <span className="lm-fig">
                    <span>{fmt(g.mean_mm, 3)} <small>mm mean</small></span>
                    <span className={g.n_oot ? 'amber' : 'muted'}>{g.n_oot ? `${g.n_oot} out (${pct(g.oot_rate, 1)})` : 'none out'}</span>
                  </span>
                  <Strip g={g} lo={lo} hi={hi} loc={location} color={SERIES[i % 3]} />
                  <span className="lm-n small muted">{int(g.n)} units</span>
                </button>
              ))}
            </div>
          </section>
        )
      })}
      <section className="lm-station inspection" aria-label="S50 Gap inspection">
        <header><b className="cond">S50</b> Gap inspection</header>
        <div className="lm-tiles">
          <button type="button" className="lm-tile" onClick={() => nav(`/inspect`)} aria-label="CAM-501: open the inspection workbench">
            <span className="lm-eq"><i style={{ background: 'var(--trace)' }} />CAM-501</span>
            <span className="lm-fig">
              <span>{int(inspection.measured)} <small>measured</small></span>
              <span className={inspection.oot ? 'amber' : 'muted'}>{inspection.oot} out of tolerance</span>
            </span>
            <span className="small muted">{location.code}, spec {location.lsl_mm.toFixed(2)} to {location.usl_mm.toFixed(2)} mm</span>
            <span className="lm-n small muted">{inspection.failed ? `${inspection.failed} measurements failed` : 'no failed measurements'}</span>
          </button>
        </div>
      </section>
    </div>
  )
}
