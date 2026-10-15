import { describe, expect, it } from 'vitest'
import { packageUnitPrice, instanceEstimate, instanceRate, instanceName } from '../src/utils/instance'
import type { Container } from '../src/types'

describe('package prices and display', () => {
  it('quotes fixed daily and weekly discounts', () => {
    expect(packageUnitPrice(5, 'day')).toBe(96)
    expect(packageUnitPrice(5, 'week')).toBe(504)
    expect(packageUnitPrice(0.0011, 'day')).toBe(0.0211)
  })
  it('does not double estimate an already paid package', () => {
    const row = { container_id: 'internal-id', instance_name: 'K80-2610111341', billing_mode: 'day', package_amount: 96,
      hourly_price: 5, gpus: 1, start_time: '2026-10-11T00:00:00Z' } as Container
    expect(instanceRate(row)).toBe(0)
    expect(instanceEstimate(row, Date.parse('2026-10-12T00:00:00Z'))).toBe(0)
    expect(instanceName(row)).toBe('K80-2610111341')
    expect(instanceEstimate({ ...row, package_refunded: true })).toBe(0)
  })
})
