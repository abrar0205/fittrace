import { type ReactNode, useEffect, useRef, useState } from 'react'
import { NavLink, Outlet, useNavigate } from 'react-router-dom'

import { api, type InspectionListItem, type Page } from '../api/client'
import { useHealth } from '../api/hooks'
import { IconChart, IconInspect, IconInvestigate, IconMethod, IconOverview, IconPipeline, IconTrace, Logo } from './icons'

export const SHEETS = [
  { to: '/', label: 'Overview', icon: IconOverview, end: true },
  { to: '/inspect', label: 'Inspection', icon: IconInspect },
  { to: '/analytics', label: 'Analytics', icon: IconChart },
  { to: '/trace', label: 'Traceability', icon: IconTrace },
  { to: '/investigations', label: 'Investigations', icon: IconInvestigate },
  { to: '/pipelines', label: 'Pipelines', icon: IconPipeline },
  { to: '/method', label: 'Method', icon: IconMethod },
]

function UnitSearch() {
  const nav = useNavigate()
  const ref = useRef<HTMLInputElement>(null)
  const [value, setValue] = useState('')
  const [error, setError] = useState<string | null>(null)
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement
      if (e.key === '/' && !['INPUT', 'TEXTAREA', 'SELECT'].includes(t.tagName)) {
        e.preventDefault()
        ref.current?.focus()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])
  const go = async () => {
    const q = value.trim().toUpperCase()
    if (!q) return
    const serial = /^\d+$/.test(q) ? `SIM-${q.padStart(5, '0')}` : q
    try {
      const r = await api.get<Page<InspectionListItem>>('/inspections', { q: serial, page_size: 1 })
      if (!r.items.length) return setError(`No unit matches ${serial}`)
      setError(null)
      setValue('')
      nav(`/trace/${r.items[0].unit_id}`)
    } catch {
      setError('Search is unavailable')
    }
  }
  return (
    <form className="rail-search" onSubmit={(e) => { e.preventDefault(); void go() }} role="search">
      <label className="sr-only" htmlFor="unit-search">Find a unit by serial</label>
      <input id="unit-search" ref={ref} value={value} onChange={(e) => { setValue(e.target.value); setError(null) }}
        placeholder="Find unit, e.g. 351" autoComplete="off" aria-describedby={error ? 'unit-search-err' : undefined} />
      <kbd aria-hidden>/</kbd>
      {error && <div id="unit-search-err" role="alert" style={{ fontSize: 11, color: '#f0b3ad', marginTop: 4 }}>{error}</div>}
    </form>
  )
}

export function Shell() {
  const health = useHealth()
  const ok = health.data?.database === 'ok'
  return (
    <div className="shell">
      <aside className="rail" aria-label="Primary">
        <NavLink to="/" className="brand" aria-label="FitTrace home">
          <Logo />
          <span>
            <span className="brand-name">FitTrace</span>
            <span className="brand-sub">Dimensional quality workbench</span>
          </span>
        </NavLink>
        <UnitSearch />
        <nav>
          {SHEETS.map((s, i) => (
            <NavLink key={s.to} to={s.to} end={s.end} className={({ isActive }) => (isActive ? 'active' : undefined)}>
              <s.icon />
              <span>{s.label}</span>
              <span className="sheet-no" aria-label={`sheet ${i + 1}`}>{i + 1}</span>
            </NavLink>
          ))}
        </nav>
        <div className="rail-foot">
          <span className="sim-stamp" title="All production data in this demo is simulated">
            <svg width="10" height="10" viewBox="0 0 10 10" aria-hidden><path d="M5 0l5 10H0z" fill="#d9a441" /></svg>
            Simulated data
          </span>
          <span className="health" aria-live="polite">
            <span className={`dot ${health.isLoading ? '' : ok ? 'ok' : 'bad'}`} />
            {health.isLoading ? 'Connecting to API' : ok ? `API ${health.data?.version} connected` : 'API unavailable'}
          </span>
          <a href="https://github.com/abrar0205/fittrace" style={{ color: 'inherit' }}>Source on GitHub</a>
        </div>
      </aside>
      <Outlet />
    </div>
  )
}

export type TitleFields = { dataset?: string | null; algorithm?: string; extra?: [string, ReactNode][] }

export function Sheet({ no, title, lede, tools, children, tb }: {
  no: number; title: string; lede?: ReactNode; tools?: ReactNode; children: ReactNode; tb?: TitleFields
}) {
  useEffect(() => { document.title = `${title} | FitTrace` }, [title])
  const rendered = new Date().toISOString().slice(0, 16).replace('T', ' ')  // e.g. 2026-11-19 21:18
  const extra = tb?.extra ?? []
  return (
    <main className="sheet" id="main">
      <header className="sheet-head">
        <div>
          <h1>{title}</h1>
          {lede && <p className="lede">{lede}</p>}
        </div>
        {tools && <div className="sheet-tools">{tools}</div>}
      </header>
      {children}
      <footer className="title-block" aria-label="Sheet title block">
        <div className="tb-name"><span className="k">Project</span><span className="v">FitTrace</span></div>
        <div><span className="k">Sheet</span><span className="v">{title}</span></div>
        <div><span className="k">Dataset</span><span className="v">{tb?.dataset ?? '—'}</span></div>
        <div><span className="k">Sheet no.</span><span className="v">{no} of {SHEETS.length}</span></div>
        <div className="sim"><span className="k">Data source</span><span className="v">Simulated, not factory data</span></div>
        <div><span className="k">{extra[0]?.[0] ?? 'Algorithm'}</span><span className="v">{extra[0]?.[1] ?? tb?.algorithm ?? 'scanline-subpixel 1.0.0'}</span></div>
        <div><span className="k">Rendered (UTC)</span><span className="v">{rendered}</span></div>
      </footer>
    </main>
  )
}
