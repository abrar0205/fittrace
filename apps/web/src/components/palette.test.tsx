import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'

import { api } from '../api/client'
import { CommandPalette } from './CommandPalette'

function Where() { return <div data-testid="where">{useLocation().pathname}</div> }

describe('CommandPalette', () => {
  it('opens with Ctrl+K, finds a unit by serial and navigates to its inspection', async () => {
    vi.spyOn(api, 'get').mockImplementation(async (path: string) => {
      if (path === '/locations') return [] as never
      if (path === '/investigations') return { items: [], total: 0, page: 1, page_size: 50 } as never
      if (path === '/inspections') return {
        items: [{ image_id: 42, serial: 'SIM-00351', location: 'FD-FF-M', paint_code: 'P-RD1', gap_mm: 4.61, run_status: 'ok' }],
        total: 1, page: 1, page_size: 6,
      } as never
      throw new Error(path)
    })
    render(
      <QueryClientProvider client={new QueryClient()}>
        <MemoryRouter><Routes><Route path="*" element={<><CommandPalette /><Where /></>} /></Routes></MemoryRouter>
      </QueryClientProvider>,
    )
    expect(screen.queryByRole('dialog')).toBeNull()
    act(() => { fireEvent.keyDown(window, { key: 'k', ctrlKey: true }) })
    const box = await screen.findByRole('combobox')
    fireEvent.change(box, { target: { value: '351' } })
    const option = await screen.findByRole('option', { name: /SIM-00351/ })
    expect(option).toHaveTextContent('4.610 mm')
    fireEvent.keyDown(box, { key: 'Enter' })
    expect(screen.getByTestId('where')).toHaveTextContent('/inspect/42')
    expect(screen.queryByRole('dialog')).toBeNull()
  })
})
