import { useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'

import { api, type InspectionListItem, type Page } from '../api/client'
import { useTrace } from '../api/hooks'
import { Sheet } from '../components/Shell'
import { Empty, ErrorState, Loading, Panel, StatusTag } from '../components/ui'
import { dt, fmt, gapBetween, PARAM_UNIT, signed, time } from '../lib/format'

function SerialForm() {
  const nav = useNavigate()
  const [v, setV] = useState('')
  const [err, setErr] = useState<string | null>(null)
  return (
    <form className="sheet-tools" onSubmit={async (e) => {
      e.preventDefault()
      const q = v.trim().toUpperCase()
      if (!q) return
      const serial = /^\d+$/.test(q) ? `SIM-${q.padStart(5, '0')}` : q
      const r = await api.get<Page<InspectionListItem>>('/inspections', { q: serial, page_size: 1 }).catch(() => null)
      if (!r?.items.length) return setErr(`No unit matches ${serial}`)
      setErr(null)
      nav(`/trace/${r.items[0].unit_id}`)
    }}>
      <label className="sr-only" htmlFor="trace-serial">Unit serial</label>
      <input id="trace-serial" className="input" placeholder="Serial, e.g. SIM-00351" value={v} onChange={(e) => setV(e.target.value)} />
      <button className="btn" type="submit">Trace unit</button>
      {err && <span className="small" role="alert" style={{ color: 'var(--fault)' }}>{err}</span>}
    </form>
  )
}

export function Traceability() {
  const { unitId } = useParams()
  const id = unitId ? Number(unitId) : undefined
  const t = useTrace(id)
  const d = t.data
  return (
    <Sheet no={4} title="Traceability"
      lede="The simulated manufacturing history of one unit: each station, the fixture or tool it used, recorded process parameters, and the inspection results it produced."
      tools={<SerialForm />} tb={{ dataset: d?.dataset_key, extra: [['Unit', d?.serial ?? '—']] }}>
      {!id && <div className="panel"><Empty title="Choose a unit to trace">Enter a serial above, press / anywhere to search, or open a unit from an inspection or investigation.</Empty></div>}
      {id && t.isLoading && <Loading height={360} />}
      {t.error && <div className="panel"><ErrorState error={t.error} /></div>}
      {d && (
        <>
          <div className="inv-head">
            <div><span className="fig-k">Unit</span><span className="fig-v">{d.serial}</span></div>
            <div><span className="fig-k">Built (S10 start)</span><span className="fig-v" style={{ fontSize: 'var(--t-lg)' }}>{dt(d.built_at)}</span></div>
            <div><span className="fig-k">Line and material batch</span><span className="fig-v" style={{ fontSize: 'var(--t-lg)' }}>{d.line}, {d.batch}</span></div>
            <div><span className="fig-k">History</span><span className="fig-v" style={{ fontSize: 'var(--t-lg)', color: 'var(--amber-ink)' }}>Simulated</span></div>
          </div>

          <Panel title="Process route" aside="stations in sequence; time between steps on the connector">
            {d.route.length ? (
              <div className="route">
                {d.route.map((st, i) => {
                  const next = d.route[i + 1]
                  const isInsp = st.equipment_kind === 'camera'
                  return (
                    <div key={st.station} className={`route-step ${isInsp ? 'inspection' : ''}`}>
                      <span className="route-node" />
                      {next && <span className="route-gap">+{gapBetween(st.ended_at, next.started_at)}</span>}
                      <div className="route-card">
                        <div className="small muted">{st.station}, {st.station_name}</div>
                        <span className="route-eq">{st.equipment}</span>
                        <div className="small muted">{st.equipment_name}</div>
                        <dl className="kv">
                          <dt>Start</dt><dd>{time(st.started_at)} UTC</dd>
                          <dt>Cycle</dt><dd>{gapBetween(st.started_at, st.ended_at)}</dd>
                          {st.parameters.filter((p: any) => p.name !== 'cycle_time_s').map((p: any) => (
                            <FragmentKV key={p.name} k={p.name.replace(/_(bar|ka|c|nm)$/, '').replace(/_/g, ' ')} v={`${fmt(p.value, 2)} ${PARAM_UNIT[p.name] ?? p.unit}`} />
                          ))}
                        </dl>
                        {isInsp && d.inspections.map((ins) => (
                          <Link key={ins.image_id} to={`/inspect/${ins.image_id}`} className="trace-insp">
                            <span className="cond">{ins.location}</span>
                            <b className="cond">{fmt(ins.gap_mm, 3)} mm</b>
                            <StatusTag status={ins.run_status === 'failed' ? 'failed' : ins.tolerance_status} />
                          </Link>
                        ))}
                      </div>
                    </div>
                  )
                })}
              </div>
            ) : <Empty title="No production events">This unit's events were rejected during import; see the pipeline monitor.</Empty>}
            {d.route.length > 0 && d.route.length < 4 && (
              <div className="callout warn small" style={{ marginTop: 10 }}>The route is incomplete: some production events for this unit were rejected by import validation.</div>
            )}
          </Panel>

          <div className="grid cols-2">
            <Panel title="Inspection results">
              <table className="table">
                <thead><tr><th>Location</th><th className="r">Gap (mm)</th><th className="r">Deviation</th><th>Result</th><th /></tr></thead>
                <tbody>
                  {d.inspections.map((ins) => (
                    <tr key={ins.image_id}>
                      <td className="id">{ins.location}</td><td className="r">{fmt(ins.gap_mm, 3)}</td><td className="r">{signed(ins.deviation_mm)}</td>
                      <td><StatusTag status={ins.run_status === 'failed' ? 'failed' : ins.tolerance_status} /></td>
                      <td className="r"><Link to={`/inspect/${ins.image_id}`}>Open image</Link></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </Panel>
            <Panel title="Equipment events before this unit" aside="last 48 h, on the resources it used"
              note="Routine events are recorded for every resource; an event here is context, not evidence of a cause.">
              {d.equipment_events.length ? (
                <table className="table">
                  <thead><tr><th>Equipment</th><th>Event</th><th className="r">Before build</th></tr></thead>
                  <tbody>
                    {d.equipment_events.map((e: any, i: number) => (
                      <tr key={i}><td className="id">{e.equipment}</td><td>{e.kind}: {e.description}</td><td className="r">{Number(e.hours_before).toFixed(1)} h</td></tr>
                    ))}
                  </tbody>
                </table>
              ) : <Empty title="No equipment events in the window" />}
            </Panel>
          </div>
        </>
      )}
    </Sheet>
  )
}

function FragmentKV({ k, v }: { k: string; v: string }) {
  return (<><dt>{k}</dt><dd>{v}</dd></>)
}
