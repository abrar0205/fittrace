export const fmt = (x: number | null | undefined, digits = 3) =>
  x === null || x === undefined || !Number.isFinite(x) ? '—' : x.toFixed(digits)

export const signed = (x: number | null | undefined, digits = 3) =>
  x === null || x === undefined || !Number.isFinite(x) ? '—' : `${x >= 0 ? '+' : '−'}${Math.abs(x).toFixed(digits)}`

export const pct = (x: number | null | undefined, digits = 0) =>
  x === null || x === undefined || !Number.isFinite(x) ? '—' : `${(x * 100).toFixed(digits)}%`

/** "p < 0.0001" or "p = 0.0123" */
export const pEq = (p: number | null | undefined) => {
  const s = pval(p)
  return s.startsWith('<') ? `p ${s}` : `p = ${s}`
}

export const pval = (p: number | null | undefined) => {
  if (p === null || p === undefined || !Number.isFinite(p)) return '—'
  if (p < 0.0001) return '< 0.0001'
  return p < 0.01 ? p.toFixed(4) : p.toFixed(3)
}

const dtf = new Intl.DateTimeFormat('en-GB', {
  year: 'numeric', month: 'short', day: '2-digit', hour: '2-digit', minute: '2-digit', timeZone: 'UTC',
})
const tf = new Intl.DateTimeFormat('en-GB', { hour: '2-digit', minute: '2-digit', second: '2-digit', timeZone: 'UTC' })

export const dt = (s: string | null | undefined) => (s ? `${dtf.format(new Date(s))} UTC` : '—')
export const time = (s: string | null | undefined) => (s ? tf.format(new Date(s)) : '—')

export const duration = (seconds: number | null | undefined) => {
  if (seconds === null || seconds === undefined) return '—'
  if (seconds < 1) return `${Math.round(seconds * 1000)} ms`
  if (seconds < 90) return `${seconds.toFixed(1)} s`
  const m = Math.floor(seconds / 60)
  return `${m} min ${Math.round(seconds - m * 60)} s`
}

export const gapBetween = (a: string, b: string) => {
  const s = (new Date(b).getTime() - new Date(a).getTime()) / 1000
  if (s < 60) return `${Math.round(s)} s`
  const m = Math.floor(s / 60)
  return `${m} min ${Math.round(s - m * 60)} s`
}

export const int = (n: number | null | undefined) => (n === null || n === undefined ? '—' : n.toLocaleString('en-US'))

export const STATUS_LABEL: Record<string, string> = {
  in_tolerance: 'In tolerance',
  out_high: 'Over USL',
  out_low: 'Under LSL',
  not_evaluable: 'Not evaluable',
}

export const FACTOR_LABEL: Record<string, string> = {
  s10_fixture: 'S10 fixture',
  s20_fixture: 'S20 fixture',
  s30_tool: 'S30 nutrunner',
  batch: 'Steel coil batch',
  shift: 'Shift',
  clamp_pressure_bar: 'Clamp pressure',
  weld_current_ka: 'Weld current',
  ambient_temp_c: 'Ambient temperature',
  hinge_torque_nm: 'Hinge torque',
  s40_booth: 'S40 paint booth',
  paint: 'Paint',
  film_build_um: 'Paint film build',
  booth_temp_c: 'Booth temperature',
}

export const PARAM_UNIT: Record<string, string> = {
  clamp_pressure_bar: 'bar', weld_current_ka: 'kA', ambient_temp_c: '°C', hinge_torque_nm: 'N·m', cycle_time_s: 's',
  film_build_um: 'µm', booth_temp_c: '°C',
}

/** Display swatches for the simulated paint codes (approximate sRGB of each paint). */
export const PAINT_SWATCH: Record<string, string> = {
  'P-WH1': '#e8e8e4', 'P-BK1': '#17181b', 'P-GY1': '#5b6168', 'P-BL3M': '#1f3f92',
  'P-RD1': '#b5161d', 'P-SL2M': '#b8bcc1', 'P-GR2M': '#3b3e44',
}
