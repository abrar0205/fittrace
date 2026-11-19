import type { ReactNode } from 'react'

import { ApiError } from '../api/client'
import { STATUS_LABEL } from '../lib/format'
import { IconCheck, IconWarn, IconX } from './icons'

export function StatusTag({ status }: { status: string | null | undefined }) {
  if (!status) return <span className="tag neutral">Not measured</span>
  if (status === 'in_tolerance') return <span className="tag in"><IconCheck />{STATUS_LABEL[status]}</span>
  if (status === 'out_high' || status === 'out_low') return <span className="tag oot"><IconWarn />{STATUS_LABEL[status]}</span>
  if (status === 'failed') return <span className="tag fail"><IconX />Measurement failed</span>
  return <span className="tag neutral">{STATUS_LABEL[status] ?? status}</span>
}

export function RunTag({ status }: { status: string }) {
  const map: Record<string, [string, string]> = {
    succeeded: ['in', 'Succeeded'], failed: ['fail', 'Failed'], skipped: ['neutral', 'Skipped, unchanged'],
    running: ['running', 'Running'], queued: ['running', 'Queued'],
  }
  const [cls, label] = map[status] ?? ['neutral', status]
  return <span className={`tag ${cls}`}>{cls === 'fail' ? <IconX /> : cls === 'in' ? <IconCheck /> : null}{label}</span>
}

export function Panel({ title, aside, children, note, className, bodyClass, id }: {
  title?: ReactNode; aside?: ReactNode; children: ReactNode; note?: ReactNode; className?: string; bodyClass?: string; id?: string
}) {
  return (
    <section className={`panel ${className ?? ''}`} aria-labelledby={id}>
      {(title || aside) && (
        <div className="panel-head">
          {title && <h2 id={id}>{title}</h2>}
          {aside && <div className="aside">{aside}</div>}
        </div>
      )}
      <div className={`panel-body ${bodyClass ?? ''}`}>{children}</div>
      {note && <div className="panel-note">{note}</div>}
    </section>
  )
}

export function Loading({ label = 'Loading', height = 160 }: { label?: string; height?: number }) {
  return <div className="skeleton" style={{ height }} role="status" aria-label={label} />
}

export function ErrorState({ error, action }: { error: unknown; action?: ReactNode }) {
  const e = error instanceof ApiError ? error : null
  const hint =
    e?.code === 'network_error' ? <>Start it with <code>uvicorn app.main:app</code> in <code>apps/api</code>.</>
      : e?.code === 'no_data' ? <>Seed the demo with <code>python -m app.cli seed-demo</code>.</>
        : null
  return (
    <div className="state error" role="alert">
      <h3>{e ? e.message : 'Something went wrong while loading this view.'}</h3>
      {hint && <p>{hint}</p>}
      {e?.requestId && <p className="small muted">Request {e.requestId}</p>}
      {action}
    </div>
  )
}

export function Empty({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="state">
      <h3>{title}</h3>
      {children && <p>{children}</p>}
    </div>
  )
}

export function Seg<T extends string>({ value, options, onChange, label, small }: {
  value: T; options: { value: T; label: ReactNode }[]; onChange: (v: T) => void; label: string; small?: boolean
}) {
  return (
    <div className={`seg ${small ? 'small' : ''}`} role="group" aria-label={label}>
      {options.map((o) => (
        <button key={o.value} type="button" aria-pressed={o.value === value} onClick={() => onChange(o.value)}>{o.label}</button>
      ))}
    </div>
  )
}
