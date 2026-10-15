import { describe, expect, it } from 'vitest'
import { metricText, remainingTime, telemetryText, telemetryType } from '../src/utils/monitoring'

describe('monitoring and budget presentation', () => {
  it('keeps true zero distinct from a missing or invalid sensor', () => {
    expect(metricText(0, '%')).toBe('0.0%')
    expect(metricText(null, '%')).toBe('—')
    expect(metricText(Number.NaN, '%')).toBe('—')
    expect(metricText(11441, ' MB', 0)).toBe('11441 MB')
  })
  it('distinguishes missing, partial, live and expired reports', () => {
    expect(telemetryText('missing')).toBe('尚未采集')
    expect(telemetryText('stale')).toBe('采集已过期')
    expect(telemetryType('live')).toBe('success')
    expect(telemetryType('partial')).toBe('warning')
  })
  it('does not invent remaining runtime without a running hourly rate', () => {
    expect(remainingTime(null)).toBe('暂无计费中的实例')
    expect(remainingTime(0)).toBe('不足1分钟')
    expect(remainingTime(65)).toBe('约 1 小时 5 分钟')
  })
})
