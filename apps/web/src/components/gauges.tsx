import { useId, useLayoutEffect, useMemo, useRef, useState } from 'react'

import { fmt } from '../lib/format'

/** Width of a container in CSS px, so SVG charts draw text at true size instead of scaling it. */
export function useWidth<T extends HTMLElement>(initial = 600) {
  const ref = useRef<T>(null)
  const [w, setW] = useState(initial)
  useLayoutEffect(() => {
    const el = ref.current
    if (!el) return
    const ro = new ResizeObserver(([e]) => setW(Math.max(120, Math.floor(e.contentRect.width))))
    ro.observe(el)
    return () => ro.disconnect()
  }, [])
  return [ref, w] as const
}

/*
 * Tolerance gauge drawn like a caliper's main scale: 0.05 mm minor ticks,
 * 0.25 mm intermediate, labelled every 0.5 mm. The specification window
 * (LSL to USL) is open; the zones beyond it are hatched and turn amber only
 * when the measured value actually falls there.
 */
export function ToleranceGauge({ value, nominal, lsl, usl, se }: {
  value: number | null; nominal: number; lsl: number; usl: number; se?: number | null
}) {
  const hatch = useId().replace(/:/g, '')
  const [ref, W] = useWidth<HTMLDivElement>(300)
  const H = 104, pad = 18
  const span = Math.max(usl - nominal, nominal - lsl) * 2
  const lo = nominal - span, hi = nominal + span
  const x = (v: number) => pad + ((v - lo) / (hi - lo)) * (W - 2 * pad)
  const oot = value !== null && (value < lsl || value > usl)
  const ticks = useMemo(() => {
    const t: { v: number; kind: 0 | 1 | 2 }[] = []
    for (let i = Math.round(lo / 0.05); i <= Math.round(hi / 0.05); i++) {
      const v = i * 0.05
      const kind = Math.abs(v / 0.5 - Math.round(v / 0.5)) < 1e-6 ? 2 : Math.abs(v / 0.25 - Math.round(v / 0.25)) < 1e-6 ? 1 : 0
      t.push({ v, kind })
    }
    return t
  }, [lo, hi])
  const clamped = value === null ? null : Math.max(lo, Math.min(hi, value))
  const off = value !== null && (value < lo || value > hi)
  const base = 50
  return (
    <div ref={ref} className="measure-w">
    <svg viewBox={`0 0 ${W} ${H}`} width={W} height={H} role="img" className="gauge"
      aria-label={value === null ? 'No measured value' : `Measured ${value.toFixed(3)} mm against specification ${lsl.toFixed(2)} to ${usl.toFixed(2)} mm`}>
      <defs>
        {['n', 'a'].map((k) => (
          <pattern key={k} id={`${hatch}${k}`} width="5" height="5" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
            <line x1="0" y1="0" x2="0" y2="5" className={k === 'a' ? 'hatch oot' : 'hatch'} />
          </pattern>
        ))}
      </defs>
      <rect x={x(lo)} y={base - 18} width={x(lsl) - x(lo)} height={18} fill={`url(#${hatch}${value !== null && value < lsl ? 'a' : 'n'})`} className={value !== null && value < lsl ? 'zone-oot' : ''} />
      <rect x={x(usl)} y={base - 18} width={x(hi) - x(usl)} height={18} fill={`url(#${hatch}${value !== null && value > usl ? 'a' : 'n'})`} className={value !== null && value > usl ? 'zone-oot' : ''} />
      <line x1={x(lo)} x2={x(hi)} y1={base} y2={base} className="g-base" />
      {ticks.map((t) => (
        <g key={t.v.toFixed(2)}>
          <line x1={x(t.v)} x2={x(t.v)} y1={base} y2={base + (t.kind === 2 ? 10 : t.kind === 1 ? 7 : 4)} className="g-tick" />
          {t.kind === 2 && <text x={x(t.v)} y={base + 22} textAnchor="middle" className="g-label">{t.v.toFixed(1)}</text>}
        </g>
      ))}
      {/* go / no-go jaws at the specification limits */}
      {[lsl, usl].map((v, i) => (
        <g key={i}>
          <path d={`M${x(v)} ${base - 24}V${base}`} className="g-jaw" />
          <text x={x(v) + (i ? 4 : -4)} y={base - 16} textAnchor={i ? 'start' : 'end'} className="g-spec">{i ? 'USL' : 'LSL'} {v.toFixed(2)}</text>
        </g>
      ))}
      <line x1={x(nominal)} x2={x(nominal)} y1={base - 12} y2={base} className="g-nominal" />
      {clamped !== null && (
        <g className={`g-needle ${oot ? 'oot' : ''}`} style={{ transform: `translateX(${x(clamped)}px)` }}>
          {se && se > 0 && <line x1={-((2 * se) / (hi - lo)) * (W - 2 * pad)} x2={((2 * se) / (hi - lo)) * (W - 2 * pad)} y1={base - 6} y2={base - 6} className="g-se" />}
          <line x1={0} x2={0} y1={base - 16} y2={base + 3} />
          <path d={`M0 ${base + 3}l-5 8h10z`} />
          <rect x={-27} y={base + 34} width={54} height={17} rx={2} className="g-value-box" />
          <text x={0} y={base + 46.5} textAnchor="middle" className="g-value">{off ? 'off scale' : fmt(value, 3)}</text>
          <line x1={0} x2={0} y1={base + 11} y2={base + 34} className="g-lead" />
        </g>
      )}
    </svg>
    </div>
  )
}

/* Compact position-in-tolerance bar for list rows. */
export function MicroGauge({ value, lsl, usl, nominal }: { value: number | null; lsl: number; usl: number; nominal: number }) {
  const span = (usl - lsl) * 0.9
  const lo = nominal - span, hi = nominal + span
  const p = (v: number) => ((Math.max(lo, Math.min(hi, v)) - lo) / (hi - lo)) * 100
  const oot = value !== null && (value < lsl || value > usl)
  return (
    <span className="micro" aria-hidden>
      <span className="micro-spec" style={{ left: `${p(lsl)}%`, width: `${p(usl) - p(lsl)}%` }} />
      <span className="micro-nom" style={{ left: `${p(nominal)}%` }} />
      {value !== null && <span className={`micro-val ${oot ? 'oot' : ''}`} style={{ left: `${p(value)}%` }} />}
    </span>
  )
}

/* Intensity and gradient profile of one image row, with the algorithm's edges for the nearest sampled row. */
export function RowProfile({ intensity, row, edges, sigma }: {
  intensity: number[]; row: number; edges: { xl: number; xr: number; y: number; inlier: boolean } | null; sigma: number
}) {
  const [ref, W] = useWidth<HTMLDivElement>(640)
  const Hi = 96, Hg = 52, padL = 34, padR = 8
  const n = intensity.length
  const grad = useMemo(() => {
    const r = Math.max(1, Math.ceil(3 * sigma))
    const k = Array.from({ length: 2 * r + 1 }, (_, i) => Math.exp(-((i - r) ** 2) / (2 * sigma * sigma)))
    const ks = k.reduce((a, b) => a + b, 0)
    const sm = intensity.map((_, i) => k.reduce((acc, w, j) => acc + w * intensity[Math.max(0, Math.min(n - 1, i + j - r))], 0) / ks)
    return sm.map((_, i) => (i === 0 || i === n - 1 ? 0 : (sm[i + 1] - sm[i - 1]) / 2))
  }, [intensity, sigma, n])
  const gmax = Math.max(8, ...grad.map(Math.abs))
  const X = (i: number) => padL + (i / (n - 1)) * (W - padL - padR)
  const Yi = (v: number) => 6 + (1 - v / 255) * (Hi - 12)
  const Yg = (v: number) => Hi + 10 + (Hg / 2) - (v / gmax) * (Hg / 2 - 3)
  const pathI = intensity.map((v, i) => `${i ? 'L' : 'M'}${X(i).toFixed(1)} ${Yi(v).toFixed(1)}`).join('')
  const pathG = grad.map((v, i) => `${i ? 'L' : 'M'}${X(i).toFixed(1)} ${Yg(v).toFixed(1)}`).join('')
  return (
    <div ref={ref} className="measure-w">
    <svg viewBox={`0 0 ${W} ${Hi + Hg + 26}`} width={W} height={Hi + Hg + 26} className="profile" role="img"
      aria-label={`Intensity profile of image row ${row.toFixed(0)}`}>
      <text x={0} y={12} className="p-axis">255</text>
      <text x={0} y={Hi - 4} className="p-axis">0</text>
      <line x1={padL} x2={W - padR} y1={Yi(0)} y2={Yi(0)} className="p-grid" />
      <line x1={padL} x2={W - padR} y1={Yi(255)} y2={Yi(255)} className="p-grid" />
      <path d={pathI} className="p-int" />
      <line x1={padL} x2={W - padR} y1={Yg(0)} y2={Yg(0)} className="p-grid" />
      <path d={pathG} className="p-grad" />
      <text x={0} y={Yg(0) + 4} className="p-axis">d/dx</text>
      {edges && [edges.xl, edges.xr].map((e, i) => (
        <g key={i} className={edges.inlier ? 'p-edge' : 'p-edge rejected'}>
          <line x1={X(e)} x2={X(e)} y1={2} y2={Hi + Hg + 8} />
          <text x={X(e) + (i ? 4 : -4)} y={Hi + Hg + 22} textAnchor={i ? 'start' : 'end'}>
            {i ? 'right' : 'left'} edge {e.toFixed(2)} px{edges.y !== Math.round(row) ? ` (row ${edges.y})` : ''}
          </text>
        </g>
      ))}
    </svg>
    </div>
  )
}

/* Histogram with the specification window, for overview strips. */
export function SpecHistogram({ counts, edges, lsl, usl, nominal, height = 86 }: {
  counts: number[]; edges: number[]; lsl: number; usl: number; nominal: number; height?: number
}) {
  const [ref, W] = useWidth<HTMLDivElement>(360)
  const pad = 4, base = height - 16
  const lo = edges[0], hi = edges[edges.length - 1]
  const x = (v: number) => pad + ((v - lo) / (hi - lo)) * (W - 2 * pad)
  const cmax = Math.max(1, ...counts)
  return (
    <div ref={ref} className="measure-w">
    <svg viewBox={`0 0 ${W} ${height}`} width={W} height={height} className="spec-hist" role="img"
      aria-label={`Distribution of measured gaps from ${lo.toFixed(2)} to ${hi.toFixed(2)} mm`}>
      <rect x={x(lsl)} y={0} width={x(usl) - x(lsl)} height={base} className="h-spec" />
      {counts.map((c, i) => {
        const mid = (edges[i] + edges[i + 1]) / 2
        const out = mid < lsl || mid > usl
        const h = (c / cmax) * (base - 6)
        return c > 0 ? (
          <rect key={i} x={x(edges[i]) + 1} y={base - h} width={Math.max(1, x(edges[i + 1]) - x(edges[i]) - 2)} height={h} rx={1}
            className={out ? 'h-bar oot' : 'h-bar'}><title>{`${edges[i].toFixed(3)} to ${edges[i + 1].toFixed(3)} mm: ${c}`}</title></rect>
        ) : null
      })}
      <line x1={x(nominal)} x2={x(nominal)} y1={0} y2={base} className="h-nom" />
      <line x1={pad} x2={W - pad} y1={base} y2={base} className="h-base" />
      <text x={x(lsl)} y={height - 3} textAnchor="middle" className="h-lbl">{lsl.toFixed(2)}</text>
      <text x={x(nominal)} y={height - 3} textAnchor="middle" className="h-lbl">{nominal.toFixed(2)}</text>
      <text x={x(usl)} y={height - 3} textAnchor="middle" className="h-lbl">{usl.toFixed(2)}</text>
    </svg>
    </div>
  )
}

/* Effect estimate with 95% CI around zero (forest-plot row). */
export function EffectBar({ effect, lo, hi, scale, significant }: {
  effect: number | null; lo: number | null; hi: number | null; scale: number; significant: boolean
}) {
  const W = 116, H = 18
  const x = (v: number) => W / 2 + (Math.max(-scale, Math.min(scale, v)) / scale) * (W / 2 - 4)
  return (
    <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`} className={`effect ${significant ? 'sig' : ''}`} aria-hidden>
      <line x1={W / 2} x2={W / 2} y1={1} y2={H - 1} className="e-zero" />
      {effect !== null && lo !== null && hi !== null && (
        <>
          <line x1={x(lo)} x2={x(hi)} y1={H / 2} y2={H / 2} className="e-ci" />
          <rect x={x(effect) - 3.5} y={H / 2 - 3.5} width={7} height={7} className="e-pt" />
        </>
      )}
    </svg>
  )
}
