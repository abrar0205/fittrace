import { describe, expect, it } from 'vitest'

import { duration, fmt, pct, pEq, pval, signed } from './format'

describe('format', () => {
  it('never prints NaN or undefined', () => {
    expect(fmt(null)).toBe('—')
    expect(fmt(Number.NaN)).toBe('—')
    expect(signed(undefined)).toBe('—')
  })
  it('formats signed deviations with a true minus sign', () => {
    expect(signed(0.5771)).toBe('+0.577')
    expect(signed(-0.0151)).toBe('−0.015')
  })
  it('formats p-values without "p = <" mistakes', () => {
    expect(pval(0.00001)).toBe('< 0.0001')
    expect(pEq(0.00001)).toBe('p < 0.0001')
    expect(pEq(0.0123)).toBe('p = 0.012')
    expect(pEq(0.0042)).toBe('p = 0.0042')
    expect(pEq(0.2)).toBe('p = 0.200')
  })
  it('formats durations and percentages', () => {
    expect(duration(0.0061)).toBe('6 ms')
    expect(duration(19.03)).toBe('19.0 s')
    expect(pct(0.0917, 1)).toBe('9.2%')
  })
})
