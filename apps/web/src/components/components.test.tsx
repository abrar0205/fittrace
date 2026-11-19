import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { ApiError } from '../api/client'
import { ToleranceGauge } from './gauges'
import { ErrorState, StatusTag } from './ui'

class RO { observe() {} disconnect() {} }
;(globalThis as any).ResizeObserver = RO

describe('StatusTag', () => {
  it('labels states in words, not only colour', () => {
    render(<><StatusTag status="out_high" /><StatusTag status="in_tolerance" /><StatusTag status="failed" /></>)
    expect(screen.getByText('Over USL')).toBeInTheDocument()
    expect(screen.getByText('In tolerance')).toBeInTheDocument()
    expect(screen.getByText('Measurement failed')).toBeInTheDocument()
  })
})

describe('ToleranceGauge', () => {
  it('describes the measured value against the specification', () => {
    render(<ToleranceGauge value={4.577} nominal={4} lsl={3.5} usl={4.5} />)
    expect(screen.getByRole('img', { name: /Measured 4.577 mm against specification 3.50 to 4.50 mm/ })).toBeInTheDocument()
    expect(screen.getByText('4.577')).toBeInTheDocument()
  })
  it('shows no needle without a value', () => {
    render(<ToleranceGauge value={null} nominal={4} lsl={3.5} usl={4.5} />)
    expect(screen.getByRole('img', { name: 'No measured value' })).toBeInTheDocument()
  })
})

describe('ErrorState', () => {
  it('explains how to fix a missing backend', () => {
    render(<ErrorState error={new ApiError(0, 'network_error', 'The API could not be reached.')} />)
    expect(screen.getByRole('alert')).toHaveTextContent('uvicorn app.main:app')
  })
  it('shows the request id from a structured API error', () => {
    render(<ErrorState error={new ApiError(409, 'within_tolerance', 'Within tolerance', null, 'abc123')} />)
    expect(screen.getByText('Request abc123')).toBeInTheDocument()
  })
})
