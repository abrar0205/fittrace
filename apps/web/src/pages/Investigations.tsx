import { useEffect, useMemo, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'

import { api, ApiError, type Hypothesis, type Investigation } from '../api/client'
import { useCreateVerification, useInvestigation, useInvestigations, useVerification } from '../api/hooks'
import { EffectBar, useWidth } from '../components/gauges'
import { IconDownload, IconPlay } from '../components/icons'
import { Plot } from '../components/Plot'
import { Sheet } from '../components/Shell'
import { Empty, ErrorState, Loading, Panel, StatusTag } from '../components/ui'
import { dt, FACTOR_LABEL, fmt, PARAM_UNIT, pct, pval, signed } from '../lib/format'

const BLUE = '#3b6fd0', MUTED = '#a7b2ba', INK = '#17212a', AMBER = '#a86a00'

export function InvestigationList() {
  const q = useInvestigations()
  const nav = useNavigate()
  return (
    <Sheet no={5} title="Investigations"
      lede="Each investigation starts from one out-of-tolerance inspection and uses only the history available up to that unit.">
      <Panel title="Investigation records">
        {q.isLoading ? <Loading /> : q.error ? <ErrorState error={q.error} /> : q.data?.items.length ? (
          <table className="table">
            <thead><tr><th>#</th><th>Trigger unit</th><th>Location</th><th>Conclusion</th><th>Top-ranked contributor</th><th className="r">Created</th></tr></thead>
            <tbody>
              {q.data.items.map((i) => (
                <tr key={i.id} className="clickable" onClick={() => nav(`/investigations/${i.id}`)}>
                  <td className="id"><Link to={`/investigations/${i.id}`}>{i.id}</Link></td><td className="id">{i.serial}</td><td>{i.location}</td>
                  <td>{i.status === 'shift_detected' ? 'Sustained shift detected' : 'No sustained shift'}</td>
                  <td>{i.top_hypothesis ? `${i.top_hypothesis}${i.top_explained_fraction ? `, explains ${pct(i.top_explained_fraction)}` : ', not significant'}` : '—'}</td>
                  <td className="r">{dt(i.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <Empty title="No investigations yet">
            Open an out-of-tolerance result in the <Link to="/inspect">inspection workbench</Link> and choose Start investigation.
          </Empty>
        )}
      </Panel>
    </Sheet>
  )
}

const label = (h: Hypothesis) => FACTOR_LABEL[h.factor] ?? h.factor

export function InvestigationDetail() {
  const { invId } = useParams()
  const q = useInvestigation(Number(invId))
  const inv = q.data
  return (
    <Sheet no={5} title={inv ? `Investigation ${inv.id}` : 'Investigation'}
      lede={inv ? <>Gap at {inv.location.code} on {String(inv.trigger.serial)} was {fmt(inv.trigger.gap_mm as number, 3)} mm ({signed(inv.trigger.deviation_mm as number)} mm). The analysis looks for a sustained shift before this unit and tests which recorded factors are associated with it.</> : undefined}
      tools={inv && (
        <>
          <a className="btn" href={api.href(`/reports/investigations/${inv.id}.md`)}><IconDownload />Report (Markdown)</a>
          <a className="btn" href={api.href(`/reports/investigations/${inv.id}.json`)}><IconDownload />Report (JSON)</a>
        </>
      )}
      tb={{ dataset: inv?.provenance.dataset_key, extra: [['Method', inv ? `${inv.method.split('.').pop()} ${inv.method_version}` : '—']] }}>
      {q.isLoading && <Loading height={480} />}
      {q.error && <div className="panel"><ErrorState error={q.error} /></div>}
      {inv && <InvestigationBody inv={inv} />}
    </Sheet>
  )
}

function InvestigationBody({ inv }: { inv: Investigation }) {
  const trig = inv.trigger as any
  const tested = inv.hypotheses.filter((h) => h.status === 'tested')
  const notEst = inv.hypotheses.filter((h) => h.status !== 'tested')
  const [sel, setSel] = useState<Hypothesis | null>(tested[0] ?? null)
  const nav = useNavigate()
  const cp = inv.change_point as any
  const snap = inv.evidence.series_snapshot as any
  const shift = inv.summary.observed_shift_mm as number | null
  const scale = Math.max(0.1, ...tested.filter((h) => h.factor_type !== 'parameter').map((h) => Math.max(Math.abs(h.ci_low ?? 0), Math.abs(h.ci_high ?? 0))))

  const chart = useMemo(() => {
    if (!snap?.deviation_mm) return null
    const n = snap.deviation_mm.length
    const idx = Array.from({ length: n }, (_, i) => i + 1)
    const col = sel && sel.factor_type !== 'parameter' ? (snap[sel.factor] as string[] | undefined) : undefined
    const isLvl = idx.map((_, i) => !!col && col[i] === sel?.level)
    const text = idx.map((_, i) => `${snap.serial[i]}<br>${String(snap.built_at[i]).slice(0, 16).replace('T', ' ')} UTC<br>deviation ${signed(snap.deviation_mm[i])} mm<br>S20 ${snap.s20_fixture[i]}, S30 ${snap.s30_tool[i]}, S10 ${snap.s10_fixture[i]}`)
    const pick = (m: boolean[]) => ({ x: idx.filter((_, i) => m[i]), y: snap.deviation_mm.filter((_: number, i: number) => m[i]), text: text.filter((_, i) => m[i]), customdata: snap.image_id.filter((_: number, i: number) => m[i]) })
    const tol = inv.location.upper_tol_mm
    const k = cp?.index ?? null
    const data: any[] = [
      { type: 'scattergl', mode: 'markers', name: col ? 'Other units' : 'Units', ...pick(isLvl.map((v) => !v)), hovertemplate: '%{text}<extra></extra>', marker: { size: 5, color: MUTED } },
    ]
    if (col) data.push({ type: 'scattergl', mode: 'markers', name: `${label(sel!)} = ${sel!.level}`, ...pick(isLvl), hovertemplate: '%{text}<extra></extra>', marker: { size: 6, color: BLUE } })
    data.push({ type: 'scatter', mode: 'markers', name: 'Trigger', x: [n], y: [snap.deviation_mm[n - 1]], hoverinfo: 'skip', marker: { size: 14, color: 'rgba(0,0,0,0)', line: { color: AMBER, width: 2 } } })
    const shapes: any[] = [
      { type: 'line', xref: 'paper', x0: 0, x1: 1, y0: tol, y1: tol, line: { color: INK, width: 1.5 } },
      { type: 'line', xref: 'paper', x0: 0, x1: 1, y0: inv.location.lower_tol_mm, y1: inv.location.lower_tol_mm, line: { color: INK, width: 1.5 } },
    ]
    const ann: any[] = [
      { xref: 'paper', x: 1, xanchor: 'left', xshift: 4, y: tol, text: 'USL', showarrow: false, font: { size: 11 } },
      { xref: 'paper', x: 1, xanchor: 'left', xshift: 4, y: inv.location.lower_tol_mm, text: 'LSL', showarrow: false, font: { size: 11 } },
    ]
    if (k !== null) {
      shapes.push({ type: 'line', x0: k + 0.5, x1: k + 0.5, yref: 'paper', y0: 0, y1: 1, line: { color: INK, width: 1, dash: 'dash' } })
      shapes.push({ type: 'line', x0: 0.5, x1: k + 0.5, y0: cp.mean_before, y1: cp.mean_before, line: { color: INK, width: 2 } })
      shapes.push({ type: 'line', x0: k + 0.5, x1: n + 0.5, y0: cp.mean_after, y1: cp.mean_after, line: { color: INK, width: 2 } })
      // Inside the plot, beside the line, so it never collides with the legend on narrow screens.
      ann.push({ x: k + 0.5, xanchor: 'right', xshift: -4, yref: 'paper', y: 0, yanchor: 'bottom', yshift: 16, text: `change point ${cp.serial}`, showarrow: false, font: { size: 11 } })
    }
    return { data, layout: { showlegend: true, margin: { l: 56, r: 40, t: 28, b: 38 }, shapes, annotations: ann,
      xaxis: { title: { text: 'Production sequence up to the trigger' }, range: [0, n + 2] }, yaxis: { title: { text: 'Deviation from nominal (mm)' } } } }
  }, [snap, sel, cp, inv.location])

  const top = tested[0]
  return (
    <>
      <div className="callout sim">
        Production history, equipment events and the fault behind this deviation are simulated. Rankings are statistical associations to check on the line, not confirmed root causes.
      </div>
      <div className="inv-head">
        <div><span className="fig-k">Trigger</span><span className="fig-v"><Link to={`/inspect/${trig.image_id}`}>{trig.serial}</Link></span> <StatusTag status={inv.trigger.status as string} /></div>
        <div><span className="fig-k">Change point</span><span className="fig-v">{cp?.found ? cp.serial : 'none'}</span>
          {cp?.found && <div className="small muted">{signed(cp.delta)} mm, permutation p {pval(cp.p_value)} ({cp.n_perm} permutations)</div>}</div>
        <div><span className="fig-k">Units analysed</span><span className="fig-v">{inv.summary.n_units as number}</span>
          <div className="small muted">{inv.summary.n_pre as number} before, {inv.summary.n_post as number} after the change{(inv.summary.excluded_incomplete as number) ? `, ${inv.summary.excluded_incomplete} excluded` : ''}</div></div>
        <div><span className="fig-k">Highest-ranked contributor</span>
          <span className="fig-v">{top?.significant ? top.level ?? label(top) : 'none significant'}</span>
          {top?.significant && <div className="small muted">{label(top)}, explains {pct(top.explained_fraction)} of the shift</div>}</div>
      </div>

      {inv.status !== 'shift_detected' ? (
        <Panel title="No sustained shift"><p>{inv.limitations[0]}</p></Panel>
      ) : (
        <>
          <Panel title="Deviation history up to the trigger" aside={sel ? `highlighting ${label(sel)}${sel.level ? ` = ${sel.level}` : ''}` : undefined}>
            {chart && <Plot ariaLabel="Deviation series with change point" height={330} data={chart.data} layout={chart.layout}
              onPointClick={(pt) => pt?.customdata && nav(`/inspect/${pt.customdata}`)} />}
          </Panel>

          <div className="evidence-grid">
            <Panel title="Ranked candidate contributors" aside={`${tested.length} tested, Benjamini-Hochberg q < ${inv.params.alpha as number}`}
              note="Effect: how much more this level changed across the change point than everything else (difference-in-differences, HC3 errors). Explains: the effect times the level's share of post-change production, divided by the observed shift. Values above 100% mean other factors moved the other way.">
              <div className="table-scroll"><table className="table hyp-table">
                <thead><tr><th>#</th><th>Factor and level</th><th>Effect, 95% CI (mm)</th><th className="r">q</th><th>Explains</th></tr></thead>
                <tbody>
                  {tested.map((h) => (
                    <tr key={`${h.factor}-${h.level}`} className={`clickable ${sel === h ? 'selected' : ''}`} onClick={() => setSel(h)} aria-selected={sel === h}>
                      <td className="id">{h.rank}</td>
                      <td>{label(h)}{h.level && <> <b className="cond">{h.level}</b></>}</td>
                      <td>
                        {h.factor_type === 'parameter'
                          ? <span className="small">{signed(h.effect_mm, 3)} per {PARAM_UNIT[h.factor] ?? 'unit'}</span>
                          : <span style={{ display: 'inline-flex', alignItems: 'center', gap: 8 }}><EffectBar effect={h.effect_mm} lo={h.ci_low} hi={h.ci_high} scale={scale} significant={h.significant} /><span className="small">{signed(h.effect_mm)}</span></span>}
                      </td>
                      <td className="r">{pval(h.q_value)}</td>
                      <td>
                        <span className="frac"><span className={`frac-bar ${h.significant ? 'sig' : ''}`}><span style={{ width: `${Math.max(0, Math.min(1, h.explained_fraction ?? 0)) * 100}%` }} /></span>
                          <span className="small">{pct(h.explained_fraction)}{h.significant ? '' : ', n.s.'}</span></span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table></div>
              {notEst.length > 0 && (
                <details style={{ marginTop: 10 }}>
                  <summary className="small">{notEst.length} levels could not be estimated</summary>
                  <ul className="small muted">{notEst.map((h) => <li key={`${h.factor}-${h.level}`}>{label(h)} {h.level}: {h.reason}</li>)}</ul>
                </details>
              )}
            </Panel>
            {sel && <EvidencePanel h={sel} shift={shift} cpSerial={cp?.serial} />}
          </div>

          <Panel title="Limitations of this analysis">
            <ul className="limitations">{inv.limitations.map((l) => <li key={l}>{l}</li>)}</ul>
          </Panel>

          <VerificationPanel inv={inv} suggested={tested.find((h) => h.significant && h.factor_type === 'equipment')?.level ?? undefined} />
        </>
      )}
    </>
  )
}

function EvidencePanel({ h, shift, cpSerial }: { h: Hypothesis; shift: number | null; cpSerial?: string }) {
  const [ref, W] = useWidth<HTMLDivElement>(420)
  const e = h.evidence as any
  const events = (e.equipment_events_near_change ?? []) as any[]
  if (h.factor_type === 'parameter') {
    return (
      <Panel title={`Evidence: ${label(h)}`}>
        <dl className="kv">
          <dt>Slope</dt><dd>{signed(e.slope_mm_per_unit, 4)} mm per unit, 95% CI {fmt(h.ci_low, 4)} to {fmt(h.ci_high, 4)}</dd>
          <dt>Mean before / after</dt><dd>{fmt(e.mean_pre_x, 3)} / {fmt(e.mean_post_x, 3)} (change {signed(e.delta_x, 3)})</dd>
          <dt>Spearman ρ</dt><dd>{fmt(e.spearman_rho, 3)}</dd>
          <dt>Attributable shift</dt><dd>{signed(h.attributable_shift_mm, 4)} mm of {signed(shift)} mm</dd>
          <dt>q value</dt><dd>{pval(h.q_value)}</dd>
          <dt>Model</dt><dd className="small">{e.model}</dd>
        </dl>
        <p className="small muted" style={{ marginTop: 10 }}>A parameter can only explain a shift if its own level changed across the change point; a stable reading explains little even when it is correlated with the gap.</p>
      </Panel>
    )
  }
  const pts = [e.mean_pre_level, e.mean_post_level, e.mean_pre_rest, e.mean_post_rest] as number[]
  const lo = Math.min(...pts) - 0.05, hi = Math.max(...pts) + 0.05
  const H = 170, x0 = 64, x1 = W - 120
  const y = (v: number) => 14 + (1 - (v - lo) / (hi - lo)) * (H - 44)
  return (
    <Panel title={`Evidence: ${label(h)} = ${h.level}`} aside={h.significant ? <span className="tag in">significant</span> : <span className="tag neutral">not significant</span>}>
      <p style={{ marginBottom: 10 }}>
        Units built on <b>{h.level}</b> changed by <b>{signed(e.mean_post_level - e.mean_pre_level)} mm</b> across the change point; all other units changed by {signed(e.mean_post_rest - e.mean_pre_rest)} mm.
        The difference, {signed(h.effect_mm)} mm (95% CI {fmt(h.ci_low)} to {fmt(h.ci_high)}), applies to {pct(e.share_post)} of post-change units, accounting for {signed(h.attributable_shift_mm)} mm of the observed {signed(shift)} mm shift.
      </p>
      <div ref={ref} className="measure-w">
      <svg viewBox={`0 0 ${W} ${H}`} width={W} height={H} className="did" role="img" aria-label="Mean deviation before and after the change point for the level and for all other units">
        <line x1={x0} x2={x0} y1={8} y2={H - 28} className="d-axis" /><line x1={x1} x2={x1} y1={8} y2={H - 28} className="d-axis" />
        <text x={x0} y={H - 10} textAnchor="middle" className="d-lbl">before {cpSerial}</text>
        <text x={x1} y={H - 10} textAnchor="middle" className="d-lbl">from {cpSerial}</text>
        <path d={`M${x0} ${y(e.mean_pre_rest)}L${x1} ${y(e.mean_post_rest)}`} className="d-rest" />
        <path d={`M${x0} ${y(e.mean_pre_level)}L${x1} ${y(e.mean_post_level)}`} className="d-level" />
        {[['rest', e.mean_pre_rest, e.mean_post_rest], ['level', e.mean_pre_level, e.mean_post_level]].map(([k, a, b]) => {
          // Pre-change values are often within a few hundredths of each other: separate their labels vertically.
          const close = Math.abs(y(e.mean_pre_rest) - y(e.mean_pre_level)) < 14
          const dy = close ? (k === 'level' ? -7 : 8) : 0
          return (
            <g key={k as string}>
              <circle cx={x0} cy={y(a as number)} r={5} className={k as string} /><circle cx={x1} cy={y(b as number)} r={5} className={k as string} />
              <text x={x0 - 9} y={y(a as number) + 4 + dy} textAnchor="end" className="d-val">{signed(a as number)}</text>
              <text x={x1 + 9} y={y(b as number) + 4} className="d-val">{signed(b as number)} {k === 'level' ? h.level : 'others'}</text>
            </g>
          )
        })}
      </svg>
      </div>
      <h3 style={{ fontSize: 'var(--t-md)', margin: '10px 0 4px' }}>Equipment events near the change point</h3>
      {events.length ? (
        <ul className="list-plain">{events.map((ev, i) => (
          <li key={i}><span>{ev.kind}: {ev.description}</span><span className="small muted">{ev.hours_before_change >= 0 ? `${ev.hours_before_change.toFixed(1)} h before` : `${(-ev.hours_before_change).toFixed(1)} h after`}</span></li>
        ))}</ul>
      ) : <p className="small muted">No events recorded on {h.level} in the 12 h before or 2 h after the change point.</p>}
      <p className="small muted" style={{ marginTop: 6 }}>Events are context only and do not change the ranking.</p>
    </Panel>
  )
}

const EQUIPMENT = ['FX-101', 'FX-102', 'FX-201', 'FX-202', 'FX-203', 'NR-301', 'NR-302']

function VerificationPanel({ inv, suggested }: { inv: Investigation; suggested?: string }) {
  const [target, setTarget] = useState(suggested ?? 'FX-202')
  const [n, setN] = useState(120)
  // Default to the latest verification of the suggested target, else the latest run.
  const [active, setActive] = useState<number | undefined>(
    ((inv.verification_runs as any[]).find((r) => r.target_code === suggested) ?? (inv.verification_runs[0] as any))?.id)
  const create = useCreateVerification()
  const v = useVerification(active)
  useEffect(() => { if (suggested) setTarget(suggested) }, [suggested])
  const run = () => create.mutate(
    { investigation_id: inv.id, target_code: target, kind: target.startsWith('FX') ? 'realign_fixture' : 'recalibrate_tool', n_units: n, seed: inv.verification_runs.length + 1 },
    { onSuccess: (r) => setActive(r.id) },
  )
  const r = v.data?.result as any
  const hist = useMemo(() => {
    if (!r?.units) return null
    const g = (k: string) => r.units[k].map((u: any) => u.gap_mm).filter((x: number | null) => x !== null)
    const bins = { start: inv.location.nominal_mm - 1, end: inv.location.nominal_mm + 1, size: 0.04 }
    return {
      data: [
        { type: 'histogram', name: 'Without action (simulated)', x: g('baseline'), xbins: bins, marker: { color: MUTED }, opacity: 0.75, hovertemplate: '%{x} mm: %{y}<extra>without action</extra>' },
        { type: 'histogram', name: `After ${r.target_code} correction (simulated)`, x: g('adjusted'), xbins: bins, marker: { color: BLUE }, opacity: 0.75, hovertemplate: '%{x} mm: %{y}<extra>with action</extra>' },
      ],
      layout: { barmode: 'overlay', showlegend: true, margin: { l: 48, r: 16, t: 28, b: 38 }, xaxis: { title: { text: 'Measured gap (mm)' } }, yaxis: { title: { text: 'Units' } },
        shapes: [r.spec.lsl, r.spec.usl].map((x: number) => ({ type: 'line', x0: x, x1: x, yref: 'paper', y0: 0, y1: 1, line: { color: INK, width: 1.5 } })) },
    }
  }, [r, inv.location.nominal_mm])

  return (
    <Panel title="Corrective-action verification" aside={<span className="tag sim">simulated experiment</span>}
      note="The plant simulator continues production after the last imported unit twice, with identical random draws: once unchanged and once with the action applied. Both runs are rendered and measured by the vision algorithm, so the comparison is paired. It shows how a verification would be judged; it is not evidence about a real line.">
      <form className="verify-form" onSubmit={(e) => { e.preventDefault(); run() }}>
        <label className="field">Action
          <select className="select" value={target} onChange={(e) => setTarget(e.target.value)}>
            {EQUIPMENT.map((c) => <option key={c} value={c}>{c.startsWith('FX') ? 'Re-align fixture' : 'Re-calibrate nutrunner'} {c}{c === suggested ? ' (top ranked)' : ''}</option>)}
          </select>
        </label>
        <label className="field">Simulated units
          <input className="input" type="number" min={30} max={200} step={10} value={n} onChange={(e) => setN(Number(e.target.value))} />
        </label>
        <button className="btn primary" type="submit" disabled={create.isPending || ['queued', 'running'].includes(v.data?.status ?? '')}><IconPlay />Run simulated verification</button>
      </form>
      {create.error && <div className="callout warn small" role="alert">{(create.error as ApiError).message}</div>}
      {inv.verification_runs.length > 0 && (
        <div className="small" style={{ margin: '10px 0', display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'center' }}>
          <span className="muted">Previous runs:</span>
          {inv.verification_runs.map((vr: any) => (
            <button key={vr.id} type="button" className="chip" aria-pressed={vr.id === active} onClick={() => setActive(vr.id)}>
              {vr.target_code}, {vr.n_units} units{vr.adjusted_oot_rate !== null ? `, OOT ${pct(vr.baseline_oot_rate)} to ${pct(vr.adjusted_oot_rate)}` : ''}
            </button>
          ))}
        </div>
      )}
      {v.data && ['queued', 'running'].includes(v.data.status) && (
        <div style={{ display: 'grid', gap: 6, marginTop: 10 }} aria-live="polite">
          <div className="small">{v.data.status === 'queued' ? 'Queued for the worker' : v.data.job?.message ?? 'Running'}</div>
          <div className="progress"><div style={{ width: `${(v.data.job?.progress ?? 0) * 100}%` }} /></div>
        </div>
      )}
      {v.data?.status === 'failed' && <div className="callout warn">Verification failed: {(r?.error as string) ?? v.data.job?.error}</div>}
      {v.data?.status === 'succeeded' && r && (
        <div style={{ display: 'grid', gap: 12, marginTop: 12 }}>
          <div className="stat-row">
            <div><span className="fig-k">Mean gap, without action</span><span className="fig-v">{fmt(r.baseline.mean_mm, 3)}<small>mm</small></span></div>
            <div><span className="fig-k">Mean gap, with action</span><span className="fig-v">{fmt(r.adjusted.mean_mm, 3)}<small>mm</small></span></div>
            <div><span className="fig-k">Paired change, 95% CI</span><span className="fig-v">{signed(r.paired_mean_change_mm)}<small>{r.paired_ci95_mm ? `${fmt(r.paired_ci95_mm[0])} to ${fmt(r.paired_ci95_mm[1])}` : ''}</small></span></div>
            <div><span className="fig-k">Out of tolerance</span><span className="fig-v">{pct(r.baseline.oot_rate, 1)} to {pct(r.adjusted.oot_rate, 1)}<small>Fisher p {pval(r.fisher_p)}</small></span></div>
            <div><span className="fig-k">Hedges g</span><span className="fig-v">{fmt(r.hedges_g, 2)}</span></div>
          </div>
          {r.on_target_equipment && (
            <p className="small">On units that passed through {r.target_code} ({r.on_target_equipment.n}), the mean gap changed by {signed(r.on_target_equipment.mean_change_mm)} mm. {Math.abs(r.paired_mean_change_mm ?? 0) < 0.005 ? `Acting on ${r.target_code} had no measurable effect: the simulated fault is elsewhere.` : ''}</p>
          )}
          {hist && <Plot ariaLabel="Gap distributions with and without the corrective action" height={260} data={hist.data} layout={hist.layout} />}
        </div>
      )}
    </Panel>
  )
}
