import { useEffect, useRef } from 'react'

type PlotlyLib = typeof import('plotly.js-cartesian-dist-min')
let plotlyPromise: Promise<PlotlyLib> | null = null
const loadPlotly = () => (plotlyPromise ??= import('plotly.js-cartesian-dist-min').then((m) => ((m as any).default ?? m) as PlotlyLib))

const css = (name: string) => getComputedStyle(document.documentElement).getPropertyValue(name).trim()

export function baseLayout(): Record<string, any> {
  const ink3 = css('--ink-3') || '#5f6c77'
  const grid = css('--grid') || '#e3e8eb'
  const axis = {
    gridcolor: grid, zeroline: false, linecolor: css('--line-strong'), ticks: 'outside', tickcolor: css('--line-strong'),
    ticklen: 4, tickfont: { size: 11, color: ink3 }, title: { font: { size: 12, color: ink3 }, standoff: 8 }, automargin: true,
  }
  return {
    font: { family: 'IBM Plex Sans, sans-serif', size: 12, color: css('--ink') || '#17212a' },
    paper_bgcolor: 'rgba(0,0,0,0)', plot_bgcolor: 'rgba(0,0,0,0)', margin: { l: 52, r: 16, t: 10, b: 38 },
    xaxis: { ...axis }, yaxis: { ...axis }, showlegend: false, hovermode: 'closest',
    hoverlabel: { bgcolor: '#17212a', bordercolor: '#17212a', font: { family: 'IBM Plex Sans, sans-serif', size: 12, color: '#fff' } },
    legend: { orientation: 'h', x: 0, y: 1.12, font: { size: 12 } },
  }
}

const merge = (a: any, b: any): any => {
  if (!b) return a
  const out = { ...a }
  for (const k of Object.keys(b)) out[k] = b[k] && typeof b[k] === 'object' && !Array.isArray(b[k]) && a?.[k] ? merge(a[k], b[k]) : b[k]
  return out
}

export function Plot({ data, layout, height = 300, onPointClick, ariaLabel }: {
  data: any[]; layout?: Record<string, any>; height?: number; onPointClick?: (pt: any) => void; ariaLabel: string
}) {
  const ref = useRef<HTMLDivElement>(null)
  const clickRef = useRef(onPointClick)
  clickRef.current = onPointClick
  useEffect(() => {
    let alive = true
    const el = ref.current
    loadPlotly().then((Plotly) => {
      if (!alive || !el) return
      Plotly.react(el, data, merge(baseLayout(), { height, ...layout }), {
        displaylogo: false, responsive: true, modeBarButtonsToRemove: ['lasso2d', 'select2d', 'autoScale2d', 'toggleSpikelines'],
      })
      const anyEl = el as any
      anyEl.removeAllListeners?.('plotly_click')
      anyEl.on?.('plotly_click', (ev: any) => clickRef.current?.(ev.points?.[0]))
    })
    return () => { alive = false }
  }, [data, layout, height])
  useEffect(() => () => { const el = ref.current; if (el) loadPlotly().then((P) => P.purge(el)) }, [])
  return <div ref={ref} role="img" aria-label={ariaLabel} style={{ width: '100%', minHeight: height }} />
}
