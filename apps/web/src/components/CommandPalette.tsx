/*
 * Command palette (Ctrl+K / ⌘K): jump to a sheet, a unit by serial, a measurement location or an
 * investigation without leaving the keyboard. Unit search goes through the same /inspections
 * endpoint the workbench list uses, so it works against the live API and the static snapshot.
 */
import { useQuery } from '@tanstack/react-query'
import { useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { api, type InspectionListItem, type Page } from '../api/client'
import { useInvestigations, useLocations } from '../api/hooks'
import { fmt, PAINT_SWATCH } from '../lib/format'
import { SHEETS } from './Shell'

type Item = { id: string; group: string; label: string; hint?: string; swatch?: string; to: string }

function useDebounced<T>(v: T, ms: number) {
  const [d, setD] = useState(v)
  useEffect(() => { const t = setTimeout(() => setD(v), ms); return () => clearTimeout(t) }, [v, ms])
  return d
}

export function CommandPalette() {
  const nav = useNavigate()
  const [open, setOpen] = useState(false)
  const [q, setQ] = useState('')
  const [active, setActive] = useState(0)
  const input = useRef<HTMLInputElement>(null)
  const listRef = useRef<HTMLUListElement>(null)
  const returnFocus = useRef<HTMLElement | null>(null)

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement
      const typing = ['INPUT', 'TEXTAREA', 'SELECT'].includes(t.tagName) || t.isContentEditable
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k' || (e.key === '/' && !typing)) {
        e.preventDefault()
        setOpen((o) => {
          if (!o) returnFocus.current = document.activeElement as HTMLElement
          return !o
        })
      }
    }
    const onOpen = () => { returnFocus.current = document.activeElement as HTMLElement; setOpen(true) }
    window.addEventListener('keydown', onKey)
    window.addEventListener('fittrace:palette', onOpen)
    return () => { window.removeEventListener('keydown', onKey); window.removeEventListener('fittrace:palette', onOpen) }
  }, [])

  useEffect(() => {
    if (open) { setQ(''); setActive(0); requestAnimationFrame(() => input.current?.focus()) }
    else returnFocus.current?.focus?.()
  }, [open])

  const locations = useLocations()
  const investigations = useInvestigations()
  const term = useDebounced(q.trim(), 140)
  const serialQ = /^\d+$/.test(term) ? term.padStart(Math.min(5, Math.max(term.length, 1)), '0') : term
  const units = useQuery({
    queryKey: ['palette-units', serialQ],
    queryFn: () => api.get<Page<InspectionListItem>>('/inspections', { q: serialQ, page_size: 6 }),
    enabled: open && serialQ.length >= 1,
    staleTime: 30_000,
  })

  const items = useMemo<Item[]>(() => {
    const t = q.trim().toLowerCase()
    const has = (s: string) => !t || s.toLowerCase().includes(t)
    const out: Item[] = []
    SHEETS.forEach((s, i) => has(s.label) && out.push({ id: `s${s.to}`, group: 'Sheets', label: s.label, hint: `sheet ${i + 1}`, to: s.to }))
    if (has('out of tolerance') || has('oot'))
      out.push({ id: 'a-oot', group: 'Sheets', label: 'Out-of-tolerance inspections', hint: 'workbench filter', to: '/inspect?status=out_of_tolerance' })
    for (const l of locations.data ?? [])
      if (has(l.code) || has(l.name))
        out.push({ id: `l${l.code}`, group: 'Locations', label: `${l.code} ${l.name}`, hint: `${l.nominal_mm.toFixed(2)} mm nominal`, to: `/analytics?location=${l.code}` })
    if (t) for (const u of units.data?.items ?? [])
      out.push({
        id: `u${u.image_id}`, group: 'Units', label: u.serial, swatch: u.paint_code ? PAINT_SWATCH[u.paint_code] : undefined,
        hint: `${u.location}, ${u.run_status === 'failed' ? 'no measurement' : `${fmt(u.gap_mm, 3)} mm`}`, to: `/inspect/${u.image_id}`,
      })
    for (const v of investigations.data?.items ?? [])
      if (t && (has(v.serial) || has(`#${v.id}`) || has(v.top_hypothesis ?? '')))
        out.push({ id: `i${v.id}`, group: 'Investigations', label: `#${v.id} ${v.serial} at ${v.location}`, hint: v.top_hypothesis ?? v.status, to: `/investigations/${v.id}` })
    return out.slice(0, 40)
  }, [q, locations.data, units.data, investigations.data])

  useEffect(() => { setActive(0) }, [q])
  useEffect(() => {
    listRef.current?.querySelector<HTMLElement>(`[data-idx="${active}"]`)?.scrollIntoView({ block: 'nearest' })
  }, [active])

  if (!open) return null
  const go = (it?: Item) => { if (!it) return; setOpen(false); nav(it.to) }
  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Escape') { e.preventDefault(); setOpen(false) }
    else if (e.key === 'ArrowDown') { e.preventDefault(); setActive((a) => Math.min(items.length - 1, a + 1)) }
    else if (e.key === 'ArrowUp') { e.preventDefault(); setActive((a) => Math.max(0, a - 1)) }
    else if (e.key === 'Enter') { e.preventDefault(); go(items[active]) }
    else if (e.key === 'Tab') e.preventDefault()  // focus stays in the dialog
  }
  let lastGroup = ''
  return (
    <div className="palette-scrim" onMouseDown={() => setOpen(false)}>
      <div className="palette" role="dialog" aria-modal="true" aria-label="Go to" onMouseDown={(e) => e.stopPropagation()} onKeyDown={onKeyDown}>
        <div className="palette-input">
          <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden><circle cx="7" cy="7" r="5" fill="none" stroke="currentColor" strokeWidth="1.5" /><path d="M11 11l3.5 3.5" stroke="currentColor" strokeWidth="1.5" /></svg>
          <input ref={input} value={q} onChange={(e) => setQ(e.target.value)} placeholder="Unit serial, location, investigation or sheet"
            role="combobox" aria-expanded="true" aria-controls="palette-list" aria-activedescendant={items[active] ? `pi-${items[active].id}` : undefined}
            aria-autocomplete="list" autoComplete="off" spellCheck={false} />
          <kbd>Esc</kbd>
        </div>
        <ul id="palette-list" ref={listRef} role="listbox" className="palette-list">
          {items.map((it, i) => {
            const head = it.group !== lastGroup ? it.group : null
            lastGroup = it.group
            return (
              <li key={it.id} role="presentation">
                {head && <div className="palette-group" role="presentation">{head}</div>}
                <div id={`pi-${it.id}`} role="option" aria-selected={i === active} data-idx={i}
                  className="palette-item" onMouseMove={() => setActive(i)} onClick={() => go(it)}>
                  {it.swatch !== undefined && <i className="wb-paint" style={{ background: it.swatch }} />}
                  <span className="pl-label">{it.label}</span>
                  {it.hint && <span className="pl-hint">{it.hint}</span>}
                </div>
              </li>
            )
          })}
          {!items.length && <li className="palette-empty">{units.isFetching ? 'Searching' : `Nothing matches “${q}”. Try a serial number such as 351.`}</li>}
        </ul>
        <div className="palette-foot"><span><kbd>↑</kbd><kbd>↓</kbd> move</span><span><kbd>Enter</kbd> open</span><span><kbd>Ctrl</kbd><kbd>K</kbd> toggle</span></div>
      </div>
    </div>
  )
}
