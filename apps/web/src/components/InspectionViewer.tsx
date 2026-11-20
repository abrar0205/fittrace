/*
 * Inspection viewer: the calibrated image with the algorithm's own geometry.
 *
 * Every mark drawn here comes from the stored inspection run (sampled edge
 * points, robust line fits, ROI, measurement segment) or from the image's
 * actual pixels (loupe, crosshair readout, intensity profile). Nothing is
 * synthesised for effect: the scan-line reveal replays the order in which the
 * algorithm sampled its rows.
 */
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'

import type { InspectionRun, Location } from '../api/client'
import { fmt, signed } from '../lib/format'
import { IconReset } from './icons'

export type Layers = { points: boolean; fits: boolean; roi: boolean; dimension: boolean; loupe: boolean }
type Overlay = InspectionRun['overlay']
type View = { k: number; tx: number; ty: number }

const REVEAL_MS = 1150
const prefersReduced = () => typeof window !== 'undefined' && window.matchMedia?.('(prefers-reduced-motion: reduce)').matches

export function useImagePixels(src: string) {
  const [state, setState] = useState<{ canvas: HTMLCanvasElement; data: ImageData; w: number; h: number } | null>(null)
  const [error, setError] = useState(false)
  useEffect(() => {
    let alive = true
    setError(false)
    const img = new Image()
    img.crossOrigin = 'anonymous'
    img.onload = () => {
      if (!alive) return
      const c = document.createElement('canvas')
      c.width = img.naturalWidth
      c.height = img.naturalHeight
      const ctx = c.getContext('2d', { willReadFrequently: true })!
      ctx.drawImage(img, 0, 0)
      setState({ canvas: c, data: ctx.getImageData(0, 0, c.width, c.height), w: c.width, h: c.height })
    }
    img.onerror = () => alive && setError(true)
    img.src = src
    return () => { alive = false }
  }, [src])
  return { pixels: state, error }
}

/** Luma (ITU-R BT.601, as OpenCV's BGR2GRAY) of one image row: what the algorithm sees. */
export function rowIntensity(data: ImageData, y: number): number[] {
  const row = Math.max(0, Math.min(data.height - 1, Math.round(y)))
  const out = new Array<number>(data.width)
  for (let x = 0; x < data.width; x++) out[x] = lumaAt(data, x, row)
  return out
}

export function lumaAt(data: ImageData, x: number, y: number): number {
  const i = (Math.floor(y) * data.width + Math.floor(x)) * 4
  return Math.round(0.299 * data.data[i] + 0.587 * data.data[i + 1] + 0.114 * data.data[i + 2])
}

export type Hud = { serial: string; location: string; paint?: { name: string; swatch: string } | null; camera?: string }

export function InspectionViewer({ src, run, location, mmPerPx, layers, revealKey, hoverRow, onHoverRow, hud }: {
  src: string
  run: InspectionRun | null
  location: Location
  mmPerPx: number | null
  layers: Layers
  revealKey: string
  hoverRow: number | null
  onHoverRow: (row: number | null) => void
  hud?: Hud
}) {
  const { pixels, error } = useImagePixels(src)
  const wrap = useRef<HTMLDivElement>(null)
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const loupeRef = useRef<HTMLCanvasElement>(null)
  const [box, setBox] = useState({ w: 640, h: 320 })
  const [view, setView] = useState<View>({ k: 1, tx: 0, ty: 0 })
  const [hover, setHover] = useState<{ sx: number; sy: number; ix: number; iy: number } | null>(null)
  const [reveal, setReveal] = useState(1)
  const drag = useRef<{ x: number; y: number; tx: number; ty: number } | null>(null)

  const W = pixels?.w ?? 480
  const H = pixels?.h ?? 240
  const fit = box.w / W
  const s = fit * view.k
  const sx = useCallback((x: number) => x * s + view.tx, [s, view.tx])
  const sy = useCallback((y: number) => y * s + view.ty, [s, view.ty])

  useLayoutEffect(() => {
    const el = wrap.current
    if (!el) return
    const ro = new ResizeObserver(([e]) => setBox({ w: e.contentRect.width, h: e.contentRect.width * (H / W) }))
    ro.observe(el)
    return () => ro.disconnect()
  }, [W, H])

  // Paint the image with nearest-neighbour scaling so individual pixels stay visible when zoomed.
  useEffect(() => {
    const c = canvasRef.current
    if (!c || !pixels) return
    const dpr = window.devicePixelRatio || 1
    c.width = Math.round(box.w * dpr)
    c.height = Math.round(box.h * dpr)
    const ctx = c.getContext('2d')!
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
    ctx.imageSmoothingEnabled = view.k < 2
    ctx.fillStyle = '#20262b'
    ctx.fillRect(0, 0, box.w, box.h)
    ctx.drawImage(pixels.canvas, view.tx, view.ty, W * s, H * s)
  }, [pixels, box, view, s, W, H])

  // Scan-line reveal: replays the algorithm's row order once per new run.
  useEffect(() => {
    if (!run || prefersReduced()) { setReveal(1); return }
    let raf = 0
    const t0 = performance.now()
    setReveal(0)
    const tick = (t: number) => {
      const f = Math.min(1, (t - t0) / REVEAL_MS)
      setReveal(1 - Math.pow(1 - f, 2.2))
      if (f < 1) raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
  }, [revealKey, run])

  const resetView = () => setView({ k: 1, tx: 0, ty: 0 })
  useEffect(resetView, [src])

  const clampView = (v: View): View => {
    const k = Math.max(1, Math.min(12, v.k))
    const minX = box.w - W * fit * k
    const minY = box.h - H * fit * k
    return { k, tx: Math.min(0, Math.max(minX, v.tx)), ty: Math.min(0, Math.max(minY, v.ty)) }
  }

  const onWheel = (e: React.WheelEvent) => {
    if (!e.ctrlKey && !e.metaKey && !e.altKey && view.k === 1 && e.deltaY > 0) return
    e.preventDefault()
    const r = wrap.current!.getBoundingClientRect()
    const px = e.clientX - r.left
    const py = e.clientY - r.top
    const k2 = view.k * Math.exp(-e.deltaY * 0.0018)
    const kc = Math.max(1, Math.min(12, k2))
    const ratio = kc / view.k
    setView(clampView({ k: kc, tx: px - (px - view.tx) * ratio, ty: py - (py - view.ty) * ratio }))
  }

  const toImage = (clientX: number, clientY: number) => {
    const r = wrap.current!.getBoundingClientRect()
    const px = clientX - r.left
    const py = clientY - r.top
    return { sx: px, sy: py, ix: (px - view.tx) / s, iy: (py - view.ty) / s }
  }

  const onMove = (e: React.PointerEvent) => {
    if (drag.current) {
      setView(clampView({ k: view.k, tx: drag.current.tx + e.clientX - drag.current.x, ty: drag.current.ty + e.clientY - drag.current.y }))
    }
    const p = toImage(e.clientX, e.clientY)
    if (p.ix >= 0 && p.ix < W && p.iy >= 0 && p.iy < H) {
      setHover(p)
      onHoverRow(p.iy)
    } else {
      setHover(null)
      onHoverRow(null)
    }
  }

  // Loupe: 6x nearest-neighbour magnification of the real pixels under the cursor.
  useEffect(() => {
    const c = loupeRef.current
    if (!c || !pixels || !hover || !layers.loupe) return
    const size = 148
    const mag = 6
    const dpr = window.devicePixelRatio || 1
    c.width = size * dpr
    c.height = size * dpr
    const ctx = c.getContext('2d')!
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
    ctx.imageSmoothingEnabled = false
    const half = size / mag / 2
    ctx.clearRect(0, 0, size, size)
    ctx.drawImage(pixels.canvas, hover.ix - half, hover.iy - half, half * 2, half * 2, 0, 0, size, size)
    if (run?.overlay?.rows && layers.points) {
      ctx.strokeStyle = '#2fd0d9'
      ctx.lineWidth = 1.5
      for (const r of run.overlay.rows) {
        for (const x of [r.xl, r.xr]) {
          const lx = (x - hover.ix + half) * mag
          const ly = (r.y - hover.iy + half) * mag
          if (lx < -6 || ly < -6 || lx > size + 6 || ly > size + 6) continue
          ctx.beginPath(); ctx.moveTo(lx - 5, ly); ctx.lineTo(lx + 5, ly); ctx.moveTo(lx, ly - 5); ctx.lineTo(lx, ly + 5); ctx.stroke()
        }
      }
    }
    ctx.strokeStyle = 'rgba(255,255,255,0.75)'
    ctx.lineWidth = 1
    ctx.beginPath(); ctx.moveTo(size / 2, 0); ctx.lineTo(size / 2, size); ctx.moveTo(0, size / 2); ctx.lineTo(size, size / 2); ctx.stroke()
  }, [hover, pixels, layers.loupe, layers.points, run])

  const ov: Overlay | undefined = run?.overlay
  const meas = run?.measurement
  const revealY = reveal * H
  const fitsDone = reveal >= 1
  const oot = meas?.status === 'out_high' || meas?.status === 'out_low'

  const dim = useMemo(() => {
    if (!ov?.measurement || !meas) return null
    const [x1, y1] = ov.measurement.p1
    const [x2, y2] = ov.measurement.p2
    const dx = x2 - x1, dy = y2 - y1
    const len = Math.hypot(dx, dy)
    // Edge direction (unit), pointing up the image.
    let ex = -dy / len, ey = dx / len
    if (ey > 0) { ex = -ex; ey = -ey }
    const off = (y1 - H * 0.2)
    return { x1, y1, x2, y2, ex, ey, off }
  }, [ov, meas, H])

  const pixelValue = hover && pixels ? lumaAt(pixels.data, hover.ix, hover.iy) : null
  const pixelRgb = hover && pixels
    ? Array.from(pixels.data.data.slice((Math.floor(hover.iy) * W + Math.floor(hover.ix)) * 4, (Math.floor(hover.iy) * W + Math.floor(hover.ix)) * 4 + 3))
    : null
  // Scale bar: the largest "nice" length that stays under ~22% of the view width.
  const scaleBar = useMemo(() => {
    if (!mmPerPx) return null
    const pxPerMm = s / mmPerPx
    const mm = [0.1, 0.2, 0.5, 1, 2, 5].filter((v) => v * pxPerMm <= box.w * 0.22).pop() ?? 0.1
    return { mm, px: mm * pxPerMm }
  }, [mmPerPx, s, box.w])
  const nearRow = hover && ov?.rows?.length
    ? ov.rows.reduce((a, b) => (Math.abs(b.y - hover.iy) < Math.abs(a.y - hover.iy) ? b : a))
    : null

  // Rulers (screen space). The top ruler is in millimetres when the calibration supports it.
  const ticks = useMemo(() => {
    if (!mmPerPx) return []
    const out: { x: number; major: boolean; label?: string }[] = []
    const stepMm = view.k > 4 ? 0.1 : view.k > 2 ? 0.25 : 0.5
    const x0mm = (-view.tx / s) * mmPerPx
    const x1mm = ((box.w - view.tx) / s) * mmPerPx
    for (let m = Math.ceil(x0mm / stepMm) * stepMm; m <= x1mm; m += stepMm) {
      const major = Math.abs(m / (stepMm * 4) - Math.round(m / (stepMm * 4))) < 1e-6
      out.push({ x: sx(m / mmPerPx), major, label: major ? `${m.toFixed(stepMm < 0.25 ? 1 : 0)}` : undefined })
    }
    return out
  }, [mmPerPx, view, s, box.w, sx])

  return (
    <div className="viewer">
      <div className="ruler-top" aria-hidden>
        <svg width="100%" height="22">
          {ticks.map((t, i) => (
            <g key={i}>
              <line x1={t.x} x2={t.x} y1={t.major ? 9 : 15} y2={22} />
              {t.label && <text x={t.x + 3} y={11}>{t.label}</text>}
            </g>
          ))}
          <text x="100%" dx={-4} y={11} textAnchor="end" className="unit">{mmPerPx ? 'mm' : 'uncalibrated'}</text>
        </svg>
      </div>
      <div
        ref={wrap}
        className={`viewport ${drag.current ? 'dragging' : ''}`}
        style={{ height: box.h }}
        onWheel={onWheel}
        onPointerDown={(e) => {
          if (view.k > 1) { drag.current = { x: e.clientX, y: e.clientY, tx: view.tx, ty: view.ty }; (e.target as Element).setPointerCapture?.(e.pointerId) }
        }}
        onPointerUp={() => { drag.current = null }}
        onPointerMove={onMove}
        onPointerLeave={() => { setHover(null); onHoverRow(null); drag.current = null }}
        onDoubleClick={resetView}
        tabIndex={0}
        aria-label={`Inspection image ${W} by ${H} pixels with measurement overlay. Scroll with Ctrl to zoom, drag to pan, double-click to reset.`}
        onKeyDown={(e) => {
          if (e.key === '+' || e.key === '=') setView((v) => clampView({ ...v, k: v.k * 1.25 }))
          if (e.key === '-') setView((v) => clampView({ ...v, k: v.k / 1.25 }))
          if (e.key === '0') resetView()
        }}
      >
        <canvas ref={canvasRef} style={{ width: box.w, height: box.h }} />
        {error && <div className="viewer-msg">The image file could not be loaded from the API.</div>}
        <svg className="overlay" width={box.w} height={box.h}>
          {ov?.roi && layers.roi && (
            <rect x={sx(ov.roi[0])} y={sy(ov.roi[1])} width={ov.roi[2] * s} height={ov.roi[3] * s} className="ov-roi" />
          )}
          {ov?.rows && layers.points && ov.rows.filter((r) => r.y <= revealY).map((r) => (
            <g key={r.y} className={r.inlier ? 'ov-pt' : 'ov-pt rejected'}>
              {[r.xl, r.xr].map((x, j) => r.inlier
                ? <path key={j} d={`M${sx(x) - 3.5} ${sy(r.y)}h7M${sx(x)} ${sy(r.y) - 3.5}v7`} />
                : <circle key={j} cx={sx(x)} cy={sy(r.y)} r={3.2} />)}
            </g>
          ))}
          {ov?.left_line && ov.right_line && layers.fits && fitsDone && (
            <g className="ov-fit">
              {[ov.left_line, ov.right_line].map((l, j) => (
                <line key={`${revealKey}-${j}`} x1={sx(l[0][0])} y1={sy(l[0][1])} x2={sx(l[1][0])} y2={sy(l[1][1])} pathLength={1} />
              ))}
            </g>
          )}
          {reveal < 1 && (
            <g className="scanline">
              <rect x={0} y={sy(revealY) - 18} width={box.w} height={18} />
              <line x1={0} x2={box.w} y1={sy(revealY)} y2={sy(revealY)} />
            </g>
          )}
          {dim && meas && layers.dimension && fitsDone && (
            <Dimension key={revealKey} d={dim} sx={sx} sy={sy} value={meas.gap_mm} px={meas.gap_px} oot={oot}
              deviation={meas.deviation_mm} location={location} />
          )}
          {hover && (
            <g className="crosshair">
              <line x1={0} x2={box.w} y1={hover.sy} y2={hover.sy} />
              <line x1={hover.sx} x2={hover.sx} y1={0} y2={box.h} />
            </g>
          )}
          {hoverRow !== null && !hover && (
            <line className="crosshair" x1={0} x2={box.w} y1={sy(hoverRow)} y2={sy(hoverRow)} />
          )}
          {run?.status === 'failed' && (
            <g>
              <rect x={12} y={12} width={Math.min(box.w - 24, 420)} height={46} className="ov-fail-box" />
              <text x={24} y={32} className="ov-fail-title">No measurement: {run.failure_code?.replace(/_/g, ' ')}</text>
              <text x={24} y={49} className="ov-fail-msg">{run.failure_message}</text>
            </g>
          )}
        </svg>
        {hover && layers.loupe && pixels && (
          <canvas
            ref={loupeRef}
            className="loupe"
            style={{
              left: hover.sx + (hover.sx > box.w - 190 ? -168 : 20),
              top: Math.max(4, Math.min(box.h - 152, hover.sy - 74)),
            }}
            aria-hidden
          />
        )}
        {hud && (
          <div className="hud" aria-hidden>
            <span className="hud-chip strong">{hud.serial}</span>
            <span className="hud-chip">{hud.location}</span>
            {hud.paint && <span className="hud-chip"><i style={{ background: hud.paint.swatch }} />{hud.paint.name}</span>}
            {hud.camera && <span className="hud-chip">{hud.camera}</span>}
          </div>
        )}
        {scaleBar && (
          <div className="scalebar" aria-hidden>
            <span style={{ width: scaleBar.px }} />
            <b>{scaleBar.mm} mm</b>
          </div>
        )}
        {view.k > 1 && (
          <button type="button" className="btn small zoom-reset" onClick={resetView}><IconReset />{view.k.toFixed(1)}×, reset</button>
        )}
      </div>
      <div className="viewer-status" aria-live="off">
        {hover ? (
          <>
            <span>x <b>{hover.ix.toFixed(1)}</b> px</span>
            <span>y <b>{hover.iy.toFixed(1)}</b> px</span>
            {mmPerPx && <span><b>{(hover.ix * mmPerPx).toFixed(3)}</b> mm from left edge of field</span>}
            <span>luma <b>{pixelValue}</b>{pixelRgb && <span className="rgb"> (R {pixelRgb[0]} G {pixelRgb[1]} B {pixelRgb[2]})</span>}</span>
            {nearRow && Math.abs(nearRow.y - hover.iy) < 3 && (
              <span className="trace-ink">sampled row {nearRow.y}: width {fmt((nearRow.xr - nearRow.xl), 2)} px{nearRow.inlier ? '' : ', rejected as outlier'}</span>
            )}
          </>
        ) : (
          <span className="muted">Hover for pixel values and the loupe. Ctrl + scroll or + / − to zoom, drag to pan.</span>
        )}
      </div>
    </div>
  )
}

function Dimension({ d, sx, sy, value, px, oot, deviation, location }: {
  d: { x1: number; y1: number; x2: number; y2: number; ex: number; ey: number; off: number }
  sx: (x: number) => number; sy: (y: number) => number; value: number | null; px: number; oot: boolean
  deviation: number | null; location: Location
}) {
  const ax = sx(d.x1 + d.ex * d.off), ay = sy(d.y1 + d.ey * d.off)
  const bx = sx(d.x2 + d.ex * d.off), by = sy(d.y2 + d.ey * d.off)
  const p1x = sx(d.x1), p1y = sy(d.y1), p2x = sx(d.x2), p2y = sy(d.y2)
  const ang = Math.atan2(by - ay, bx - ax)
  const head = (x: number, y: number, dir: number) => {
    const a = ang + (dir > 0 ? 0 : Math.PI)
    const l = 9, w = 3.2
    return `M${x} ${y}L${x - l * Math.cos(a) + w * Math.sin(a)} ${y - l * Math.sin(a) - w * Math.cos(a)}L${x - l * Math.cos(a) - w * Math.sin(a)} ${y - l * Math.sin(a) + w * Math.cos(a)}Z`
  }
  const mx = (ax + bx) / 2, my = (ay + by) / 2
  const label = value !== null ? value.toFixed(3) : `${px.toFixed(1)} px`
  const tol = `${location.lsl_mm.toFixed(2)} to ${location.usl_mm.toFixed(2)}`
  const ovsh = 7
  return (
    <g className={`ov-dim ${oot ? 'oot' : ''}`}>
      {/* Extension lines run along the edge direction and overshoot the dimension line slightly (ISO 129). */}
      <line x1={p1x} y1={p1y} x2={ax + d.ex * ovsh} y2={ay + d.ey * ovsh} className="ext" />
      <line x1={p2x} y1={p2y} x2={bx + d.ex * ovsh} y2={by + d.ey * ovsh} className="ext" />
      <line x1={ax} y1={ay} x2={bx} y2={by} className="dimline" />
      <path d={head(ax, ay, -1)} /><path d={head(bx, by, 1)} />
      <line x1={p1x} y1={p1y} x2={p2x} y2={p2y} className="measrow" />
      <g transform={`translate(${mx} ${my}) rotate(${(ang * 180) / Math.PI})`}>
        <rect x={-46} y={-30} width={92} height={24} rx={2} className="dimbox" />
        <text x={0} y={-12.5} textAnchor="middle" className="dimtext">{label}</text>
        {Math.hypot(bx - ax, by - ay) >= 190 && <text x={0} y={14} textAnchor="middle" className="dimsub">
          {oot && deviation !== null ? `${signed(deviation)} mm, spec ${tol}` : `spec ${tol} mm`}
        </text>}
      </g>
      <circle cx={p1x} cy={p1y} r={2.5} /><circle cx={p2x} cy={p2y} r={2.5} />
    </g>
  )
}
