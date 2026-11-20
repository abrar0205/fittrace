import { type ReactNode, useEffect } from 'react'
import { NavLink, Outlet } from 'react-router-dom'

import { SNAPSHOT } from '../api/client'
import { useHealth, useSnapshotMeta } from '../api/hooks'
import { CommandPalette } from './CommandPalette'
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

export function Shell() {
  const health = useHealth()
  const meta = useSnapshotMeta()
  const ok = health.data?.database === 'ok'
  return (
    <div className="shell">
      <aside className="rail" aria-label="Primary">
        <NavLink to="/" className="brand" aria-label="FitTrace home">
          <Logo />
          <span className="brand-text">
            <span className="brand-name">FitTrace</span>
            <span className="brand-sub">Dimensional quality workbench</span>
          </span>
        </NavLink>
        <button type="button" className="rail-cmd" onClick={() => window.dispatchEvent(new Event('fittrace:palette'))}
          aria-keyshortcuts="Control+K /" title="Find a unit, location, investigation or sheet">
          <svg width="14" height="14" viewBox="0 0 16 16" aria-hidden><circle cx="7" cy="7" r="5" fill="none" stroke="currentColor" strokeWidth="1.5" /><path d="M11 11l3.5 3.5" stroke="currentColor" strokeWidth="1.5" /></svg>
          <span className="rail-cmd-label">Search</span><kbd>Ctrl K</kbd>
        </button>
        <nav>
          {SHEETS.map((s, i) => (
            <NavLink key={s.to} to={s.to} end={s.end} title={s.label} className={({ isActive }) => (isActive ? 'active' : undefined)}>
              <s.icon />
              <span className="nav-label">{s.label}</span>
              <span className="sheet-no" aria-label={`sheet ${i + 1}`}>{i + 1}</span>
            </NavLink>
          ))}
        </nav>
        <div className="rail-foot">
          <span className="sim-stamp" title="All production data in this demo is simulated">
            <svg width="10" height="10" viewBox="0 0 10 10" aria-hidden><path d="M5 0l5 10H0z" fill="#d9a441" /></svg>
            Simulated data
          </span>
          {SNAPSHOT ? (
            <span className="health" title="Computed by GitHub Actions; read-only">
              <span className="dot ok" />
              {meta.data ? `Snapshot ${meta.data.generated_at.slice(0, 10)}` : 'Static snapshot'}
            </span>
          ) : (
            <span className="health" aria-live="polite">
              <span className={`dot ${health.isLoading ? '' : ok ? 'ok' : 'bad'}`} />
              {health.isLoading ? 'Connecting to API' : ok ? `API ${health.data?.version} connected` : 'API unavailable'}
            </span>
          )}
          <a href="https://github.com/abrar0205/fittrace" style={{ color: 'inherit' }}>Source on GitHub</a>
        </div>
      </aside>
      <Outlet />
      <CommandPalette />
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
