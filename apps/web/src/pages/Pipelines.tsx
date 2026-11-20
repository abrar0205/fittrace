import { useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'

import { ApiError, type PipelineRun } from '../api/client'
import { useHealth, usePipelineErrors, usePipelineRun, usePipelineRuns, useRetryRun, useDefaultDatasetKey } from '../api/hooks'
import { IconReset } from '../components/icons'
import { Sheet } from '../components/Shell'
import { Empty, ErrorState, Loading, Panel, RunTag } from '../components/ui'
import { dt, duration, int } from '../lib/format'

function FlowBar({ r }: { r: PipelineRun }) {
  const total = r.records_loaded + r.records_duplicate + r.records_rejected + r.records_skipped
  if (!total) return <span className="small muted">no records</span>
  const w = (n: number) => `${(n / total) * 100}%`
  return (
    <span className="flow-bar" role="img" aria-label={`${r.records_loaded} loaded, ${r.records_duplicate} duplicate, ${r.records_rejected} rejected, ${r.records_skipped} skipped`}>
      {r.records_loaded > 0 && <span className="loaded" style={{ width: w(r.records_loaded) }} />}
      {r.records_duplicate > 0 && <span className="dup" style={{ width: w(r.records_duplicate) }} />}
      {r.records_rejected > 0 && <span className="rej" style={{ width: w(r.records_rejected) }} />}
      {r.records_skipped > 0 && <span className="skip" style={{ width: w(r.records_skipped) }} />}
    </span>
  )
}

export function Pipelines() {
  const datasetKey = useDefaultDatasetKey()
  const { runId } = useParams()
  const nav = useNavigate()
  const runs = usePipelineRuns()
  const items = runs.data?.items ?? []
  const selected = runId ? Number(runId) : items.find((r) => r.status === 'failed')?.id ?? items[0]?.id
  return (
    <Sheet no={6} title="Data pipelines"
      lede="Every row below is a recorded execution of the import or measurement pipeline: what came in, what was loaded, what was rejected and why."
      tb={{ dataset: datasetKey, extra: [['Pipelines', 'mes_import, gap_measurement']] }}>
      <Panel title="Executions" aside={
        <span className="legend">
          <span><i style={{ background: 'var(--series-1)' }} />loaded</span><span><i style={{ background: 'var(--series-muted)' }} />duplicate</span>
          <span><i style={{ background: 'var(--fault)' }} />rejected</span><span><i style={{ background: 'var(--line-strong)' }} />skipped, unchanged</span>
        </span>}>
        {runs.isLoading ? <Loading /> : runs.error ? <ErrorState error={runs.error} /> : items.length ? (
          <table className="table">
            <thead><tr><th>Run</th><th>Pipeline</th><th>Source</th><th>Status</th><th>Started</th><th className="r">Duration</th>
              <th className="r">In</th><th className="r">Loaded</th><th className="r">Rejected</th><th className="r">Duplicate</th><th>Record flow</th></tr></thead>
            <tbody>
              {items.map((r) => (
                <tr key={r.id} className={`clickable ${r.id === selected ? 'selected' : ''}`} onClick={() => nav(`/pipelines/${r.id}`)} aria-selected={r.id === selected}>
                  <td className="id">{r.id}{r.retry_of_id ? <span className="small muted"> retry of {r.retry_of_id}</span> : null}</td>
                  <td>{r.pipeline}</td>
                  <td className="small" style={{ maxWidth: 220, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={r.source_uri ?? ''}>{r.source_uri ?? r.dataset_key}</td>
                  <td><RunTag status={r.status} /></td>
                  <td className="small">{dt(r.started_at)}</td>
                  <td className="r">{duration(r.duration_s)}</td>
                  <td className="r">{int(r.records_in || r.records_skipped)}</td>
                  <td className="r">{int(r.records_loaded)}</td>
                  <td className="r" style={{ color: r.records_rejected ? 'var(--fault)' : undefined }}>{int(r.records_rejected)}</td>
                  <td className="r">{int(r.records_duplicate)}</td>
                  <td><FlowBar r={r} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : <Empty title="No pipeline has run yet">Run <code>python -m app.cli seed-demo</code> to import and measure the demo dataset.</Empty>}
      </Panel>
      {selected && <RunDetail id={selected} />}
    </Sheet>
  )
}

function RunDetail({ id }: { id: number }) {
  const q = usePipelineRun(id)
  const [page, setPage] = useState(1)
  const errs = usePipelineErrors(id, page)
  const retry = useRetryRun()
  const health = useHealth()
  const r = q.data
  if (q.isLoading) return <Loading />
  if (q.error) return <div className="panel"><ErrorState error={q.error} /></div>
  if (!r) return null
  const files = (r.metrics.files ?? {}) as Record<string, any>
  return (
    <div className="grid cols-main">
      <Panel title={`Run ${r.id}, ${r.pipeline}`} aside={<RunTag status={r.status} />}>
        {r.error_message && (
          <div className="callout warn" style={{ marginBottom: 12 }} role="alert">
            <b>Why it failed:</b> {r.error_message}
            {r.status === 'failed' && (
              <div style={{ marginTop: 8 }}>
                <button className="btn small" type="button" disabled={retry.isPending || health.data?.demo_readonly} onClick={() => retry.mutate(r.id)}>
                  <IconReset />{retry.isPending ? 'Queueing' : 'Retry this run'}
                </button>
                {health.data?.demo_readonly && <span className="small muted"> Re-processing is disabled in the public demo.</span>}
                {retry.isSuccess && <span className="small"> Retry queued as job {retry.data.id}; it appears above when the worker starts it.</span>}
                {retry.error && <span className="small" style={{ color: 'var(--fault)' }}> {(retry.error as ApiError).message}</span>}
              </div>
            )}
          </div>
        )}
        {Object.keys(files).length > 0 && (
          <table className="table" style={{ marginBottom: 12 }}>
            <thead><tr><th>File</th><th className="r">Rows</th><th className="r">Valid</th><th className="r">Inserted</th><th className="r">Rejected</th><th className="r">Duplicate in file</th><th /></tr></thead>
            <tbody>
              {Object.entries(files).map(([f, m]) => (
                <tr key={f}>
                  <td className="id">{f}</td><td className="r">{int(m.rows_in)}</td><td className="r">{m.skipped ? '—' : int(m.valid)}</td>
                  <td className="r">{m.skipped ? '—' : int(m.inserted ?? 0)}</td><td className="r">{m.skipped ? '—' : int(m.rejected)}</td>
                  <td className="r">{m.skipped ? '—' : int(m.duplicates_in_file)}</td><td className="small muted">{m.skipped ? m.reason : ''}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {r.pipeline === 'gap_measurement' && (
          <dl className="kv" style={{ marginBottom: 12 }}>
            <dt>Measured</dt><dd>{int(r.metrics.measured_ok as number)}</dd>
            <dt>Algorithm failures</dt><dd>{int(r.metrics.measurement_failures as number)} (stored as failed runs, not as data)</dd>
            <dt>Processing errors</dt><dd>{int(r.metrics.processing_errors as number)}</dd>
            <dt>Algorithm</dt><dd>{String(r.params.algorithm ?? '')} {String(r.params.version ?? '')}</dd>
          </dl>
        )}
        <h3 style={{ fontSize: 'var(--t-md)', margin: '4px 0 6px' }}>Rejected rows</h3>
        {errs.data?.items.length ? (
          <>
            <table className="table">
              <thead><tr><th>File</th><th className="r">Row</th><th>Field</th><th>Reason</th></tr></thead>
              <tbody>
                {errs.data.items.map((e) => (
                  <tr key={e.id} title={JSON.stringify(e.raw)}><td className="small">{e.file_name}</td><td className="r">{e.row_number ?? '—'}</td>
                    <td className="id">{e.field ?? '—'}</td><td className="small">{e.reason}</td></tr>
                ))}
              </tbody>
            </table>
            <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginTop: 8 }} className="small">
              <button className="btn small" disabled={page <= 1} onClick={() => setPage(page - 1)}>Previous</button>
              <span>Page {page} of {Math.max(1, Math.ceil(errs.data.total / 25))}, {errs.data.total} rejects</span>
              <button className="btn small" disabled={page * 25 >= errs.data.total} onClick={() => setPage(page + 1)}>Next</button>
            </div>
          </>
        ) : <p className="small muted">No rows were rejected in this run.</p>}
      </Panel>
      <div className="grid" style={{ alignContent: 'start' }}>
        <Panel title="Data-quality checks">
          {(r.data_quality as any[]).length ? (
            <ul className="list-plain">{(r.data_quality as any[]).map((c) => (
              <li key={c.check_name}>
                <span><b className="cond">{c.check_name.replace(/_/g, ' ')}</b><br /><span className="small muted">{Object.entries(c.observed).map(([k, v]) => `${k.replace(/_/g, ' ')} ${v}`).join(', ')}</span></span>
                <span className={`tag ${c.passed ? 'in' : 'oot'}`}>{c.passed ? 'passed' : 'attention'}</span>
              </li>
            ))}</ul>
          ) : <p className="small muted">{r.status === 'succeeded' ? 'This pipeline records no data-quality checks.' : 'Checks run only after a successful load.'}</p>}
        </Panel>
        <Panel title="Rejects by pattern">
          {(r.error_summary as any[]).length ? (
            <ul className="list-plain">{(r.error_summary as any[]).map((s, i) => (
              <li key={i}><span className="small">{s.file_name}: {String(s.reason)}</span><b className="cond">{s.count}</b></li>
            ))}</ul>
          ) : <p className="small muted">No rejects.</p>}
        </Panel>
        <Panel title="Imported files">
          {(r.imports as any[]).length ? (
            <ul className="list-plain">{(r.imports as any[]).map((f) => (
              <li key={f.sha256}><span className="small">{f.file_name}</span><span className="small muted" title={f.sha256}>{f.sha256.slice(0, 10)}, {f.rows} rows</span></li>
            ))}</ul>
          ) : <p className="small muted">No files were recorded as imported. Unchanged files are skipped by checksum.</p>}
        </Panel>
      </div>
    </div>
  )
}
