import { useMemo, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'

import { SNAPSHOT } from '../api/client'
import { useDefaultDatasetKey, useLocations, useSnapshotMeta, useSpc, useStation } from '../api/hooks'
import { Plot } from '../components/Plot'
import { Sheet } from '../components/Shell'
import { ErrorState, Loading, Panel, Seg } from '../components/ui'
import { fmt, int, pct, pEq } from '../lib/format'

const SERIES = ['#3b6fd0', '#b04e9a', '#3e9450']
const INK = '#17212a', INK3 = '#5f6c77', STEEL = '#2d5e8c', AMBER = '#a86a00', BLUE = '#3b6fd0'

export function Analytics() {
  const [params, setParams] = useSearchParams()
  const locations = useLocations()
  const location = params.get('location') ?? 'FD-FF-M'
  const [baseline, setBaseline] = useState(100)
  const [station, setStation] = useState<'S10' | 'S20' | 'S30' | 'S40'>((['S10', 'S20', 'S30', 'S40'].includes(params.get('station') ?? '') ? params.get('station') : 'S20') as 'S10' | 'S20' | 'S30' | 'S40')
  const spc = useSpc(location, baseline)
  const st = useStation(location, station)
  const nav = useNavigate()
  const datasetKey = useDefaultDatasetKey()
  const meta = useSnapshotMeta()
  const s = spc.data

  const charts = useMemo(() => {
    if (!s) return null
    const idx = s.values.map((_, i) => i + 1)
    const oot = s.values.map((v) => v < s.location.lsl_mm || v > s.location.usl_mm)
    const sig = s.signals.map((x) => x.filter((r) => r !== 'MR').length > 0)
    const hover = s.values.map((v, i) => `${s.serials[i]}<br>${new Date(s.built_at[i]).toISOString().slice(0, 16).replace('T', ' ')} UTC<br>gap ${v.toFixed(3)} mm${s.signals[i].length ? `<br>signals: ${s.signals[i].join(', ')}` : ''}`)
    const pick = (mask: boolean[]) => ({ x: idx.filter((_, i) => mask[i]), y: s.values.filter((_, i) => mask[i]), text: hover.filter((_, i) => mask[i]), customdata: s.image_ids.filter((_, i) => mask[i]) })
    const n = s.values.length
    const hline = (y: number, color: string, dash: string, width = 1) => ({ type: 'line', xref: 'x', x0: 0.5, x1: n + 0.5, y0: y, y1: y, line: { color, width, dash } })
    const label = (y: number, text: string, color: string) => ({ xref: 'paper', x: 1, xanchor: 'left', y, yref: 'y', text, showarrow: false, font: { size: 11, color }, xshift: 4 })
    const iData = [
      { type: 'scattergl', mode: 'markers', name: 'In tolerance', ...pick(oot.map((o) => !o)), hovertemplate: '%{text}<extra></extra>', marker: { size: 5, color: BLUE } },
      { type: 'scattergl', mode: 'markers', name: 'Out of tolerance', ...pick(oot), hovertemplate: '%{text}<extra></extra>', marker: { size: 7, color: AMBER, symbol: 'diamond' } },
      { type: 'scattergl', mode: 'markers', name: 'SPC signal (R1, R2, R4)', ...pick(sig), hoverinfo: 'skip', marker: { size: 12, color: 'rgba(0,0,0,0)', line: { color: INK, width: 1.2 } } },
    ]
    const iLayout = {
      showlegend: true, margin: { l: 52, r: 84, t: 26, b: 36 },
      xaxis: { title: { text: 'Production sequence (unit order)' }, range: [0, n + 1] },
      yaxis: { title: { text: 'Gap (mm)' } },
      shapes: [
        { type: 'rect', xref: 'x', yref: 'paper', x0: 0.5, x1: s.baseline_n + 0.5, y0: 0, y1: 1, fillcolor: 'rgba(45,94,140,0.05)', line: { width: 0 } },
        hline(s.location.usl_mm, INK, 'solid', 1.5), hline(s.location.lsl_mm, INK, 'solid', 1.5),
        hline(s.ucl, STEEL, 'dash'), hline(s.lcl, STEEL, 'dash'), hline(s.center, INK3, 'dot'),
      ],
      annotations: [
        label(s.location.usl_mm, `USL ${s.location.usl_mm.toFixed(2)}`, INK), label(s.location.lsl_mm, `LSL ${s.location.lsl_mm.toFixed(2)}`, INK),
        label(s.ucl, `UCL ${s.ucl.toFixed(3)}`, STEEL), label(s.lcl, `LCL ${s.lcl.toFixed(3)}`, STEEL), label(s.center, `CL ${s.center.toFixed(3)}`, INK3),
        { xref: 'x', x: s.baseline_n / 2, yref: 'paper', y: 0, yanchor: 'bottom', yshift: 4, text: `baseline: limits from units 1 to ${s.baseline_n}`, showarrow: false, font: { size: 11, color: STEEL } },
      ],
    }
    const mr = s.moving_range.map((v) => v ?? null)
    const mrData = [{ type: 'scattergl', mode: 'lines', x: idx, y: mr, line: { color: INK3, width: 1 }, hovertemplate: 'MR %{y:.3f} mm<extra></extra>' }]
    const mrLayout = {
      margin: { l: 52, r: 84, t: 6, b: 36 }, xaxis: { range: [0, n + 1], title: { text: 'Production sequence (unit order)' } },
      yaxis: { title: { text: 'Moving range (mm)' }, rangemode: 'tozero' },
      shapes: [hline(s.mr_ucl, STEEL, 'dash'), hline(s.mr_bar, INK3, 'dot')],
      annotations: [label(s.mr_ucl, `UCL ${s.mr_ucl.toFixed(3)}`, STEEL), label(s.mr_bar, `MR̄ ${s.mr_bar.toFixed(3)}`, INK3)],
    }
    return { iData, iLayout, mrData, mrLayout }
  }, [s])

  const stationChart = useMemo(() => {
    const g = st.data?.groups
    if (!g || !s) return null
    return {
      data: g.map((grp, i) => ({
        type: 'box', name: grp.equipment, y: grp.values, boxpoints: 'all', jitter: 0.45, pointpos: 0, marker: { size: 3.5, color: SERIES[i % 3], opacity: 0.55 },
        line: { color: SERIES[i % 3], width: 1.5 }, fillcolor: 'rgba(0,0,0,0)', hovertemplate: `${grp.equipment}<br>%{y:.3f} mm<extra></extra>`,
      })),
      layout: {
        margin: { l: 52, r: 84, t: 10, b: 36 }, yaxis: { title: { text: 'Gap (mm)' } },
        shapes: [s.location.usl_mm, s.location.lsl_mm].map((y) => ({ type: 'line', xref: 'paper', x0: 0, x1: 1, y0: y, y1: y, line: { color: INK, width: 1.5 } })),
        annotations: [['USL', s.location.usl_mm], ['LSL', s.location.lsl_mm]].map(([t, y]) => ({ xref: 'paper', x: 1, xanchor: 'left', xshift: 4, y, text: `${t} ${(y as number).toFixed(2)}`, showarrow: false, font: { size: 11 } })),
      },
    }
  }, [st.data, s])

  return (
    <Sheet no={3} title="Dimensional analytics"
      lede="Individuals and moving-range control chart for one measurement location. Control limits describe the process; specification limits are design requirements. They are drawn differently on purpose."
      tools={
        <>
          {locations.data && (
            <Seg label="Measurement location" value={location} onChange={(v) => setParams({ location: v })}
              options={locations.data.map((l) => ({ value: l.code, label: l.code }))} />
          )}
          <label className="field" style={{ gridAutoFlow: 'column', alignItems: 'center', gap: 6 }}>
            Baseline units
            {SNAPSHOT ? (
              <select className="select" value={baseline} onChange={(e) => setBaseline(Number(e.target.value))}>
                {(meta.data?.spc_baselines ?? [100]).map((b) => <option key={b} value={b}>{b}</option>)}
              </select>
            ) : (
              <input className="input" type="number" min={20} max={400} step={10} value={baseline} style={{ width: 80 }}
                onChange={(e) => setBaseline(Math.max(20, Math.min(400, Number(e.target.value) || 100)))} />
            )}
          </label>
        </>
      }
      tb={{ dataset: datasetKey, extra: [['Method', 'I-MR, Western Electric R1 R2 R4']] }}>
      {spc.error && <div className="panel"><ErrorState error={spc.error} /></div>}
      {!s && !spc.error && <Loading height={420} />}
      {s && charts && (
        <>
          <div className="stat-row panel">
            <div><span className="fig-k">Units charted</span><span className="fig-v">{int(s.n)}</span></div>
            <div><span className="fig-k">Process centre (baseline)</span><span className="fig-v">{fmt(s.center, 3)}<small>mm</small></span></div>
            <div><span className="fig-k">Within sigma, MR̄ / d₂</span><span className="fig-v">{fmt(s.sigma_hat, 4)}<small>mm</small></span></div>
            <div><span className="fig-k">First signal</span><span className="fig-v">{s.first_signal_index !== null ? `unit ${s.first_signal_index + 1}` : 'none'}<small>{s.first_signal_index !== null ? s.serials[s.first_signal_index] : ''}</small></span></div>
            <div><span className="fig-k">Cpk (baseline)</span><span className="fig-v">{s.capability?.cpk ? fmt(s.capability.cpk, 2) : 'n/a'}</span></div>
          </div>
          <Panel title={`Individuals chart, ${s.location.code}`} aside="Select a point to open its inspection"
            note={<>{s.warnings.length ? <>Applicability warnings: {s.warnings.join(' ')} </> : 'Baseline checks passed: at least 20 points, lag-1 autocorrelation below 0.3, no strong non-normality. '}{s.capability_note}</>}>
            <Plot ariaLabel={`Individuals control chart for ${s.location.code}`} height={340} data={charts.iData} layout={charts.iLayout}
              onPointClick={(pt) => pt?.customdata && nav(`/inspect/${pt.customdata}`)} />
            <Plot ariaLabel="Moving range chart" height={170} data={charts.mrData} layout={charts.mrLayout} />
          </Panel>
          <Panel title="Comparison by station resource"
            aside={<Seg small label="Station" value={station} onChange={setStation}
              options={[{ value: 'S10', label: 'S10 underbody' }, { value: 'S20', label: 'S20 side aperture' }, { value: 'S30', label: 'S30 door hang' }, { value: 'S40', label: 'S40 paint booth' }]} />}
            note={st.data?.note}>
            {st.data && stationChart ? (
              <div className="grid cols-main">
                <Plot ariaLabel={`Gap distribution by equipment at ${station}`} height={300} data={stationChart.data} layout={stationChart.layout} />
                <div>
                  <table className="table">
                    <thead><tr><th>Equipment</th><th className="r">n</th><th className="r">Mean</th><th className="r">SD</th><th className="r">Out of tol.</th></tr></thead>
                    <tbody>
                      {st.data.groups.map((g, i) => (
                        <tr key={g.equipment}>
                          <td className="id"><i style={{ display: 'inline-block', width: 9, height: 9, borderRadius: 2, background: SERIES[i % 3], marginRight: 6 }} />{g.equipment}</td>
                          <td className="r">{g.n}</td><td className="r">{fmt(g.mean_mm, 3)}</td><td className="r">{fmt(g.sd_mm, 3)}</td>
                          <td className="r" style={{ color: g.n_oot ? 'var(--amber-ink)' : undefined }}>{g.n_oot} ({pct(g.oot_rate, 1)})</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  <dl className="kv" style={{ marginTop: 12 }}>
                    <dt>One-way ANOVA</dt><dd>{pEq(st.data.anova_p)}</dd>
                    <dt>Kruskal-Wallis</dt><dd>{pEq(st.data.kruskal_p)}</dd>
                  </dl>
                </div>
              </div>
            ) : st.error ? <ErrorState error={st.error} /> : <Loading height={300} />}
          </Panel>
        </>
      )}
    </Sheet>
  )
}
