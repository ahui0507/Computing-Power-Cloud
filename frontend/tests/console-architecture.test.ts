import { beforeEach, describe, expect, it } from 'vitest'
import { effectScope } from 'vue'
import { useSessionResource } from '../src/composables/useSessionResource'
import { resetSessionData } from '../src/utils/session'
import { csvText } from '../src/utils/export'
import { durationText, instanceEstimate, instanceRate } from '../src/utils/instance'
import type { Container } from '../src/types'

beforeEach(() => resetSessionData())

describe('session-scoped resources', () => {
  it('clears private state and ignores an old account response after switching accounts', async () => {
    const scope = effectScope()
    let finish!: (value: string[]) => void
    const resource = scope.run(() => useSessionResource<string[], []>([], () => new Promise((resolve) => { finish = resolve })))!
    resource.data.value = ['previous-account-record']
    const request = resource.fetch()
    resetSessionData()
    expect(resource.data.value).toEqual([])
    finish(['late-private-record'])
    await request
    expect(resource.data.value).toEqual([])
    expect(resource.loading.value).toBe(false)
    scope.stop()
  })

  it('keeps loading until all concurrent requests end and preserves the newest result', async () => {
    const scope = effectScope()
    const finishes: ((value: string[]) => void)[] = []
    const resource = scope.run(() => useSessionResource<string[], []>([], () => new Promise((resolve) => { finishes.push(resolve) })))!
    const first = resource.fetch(), second = resource.fetch()
    finishes[1](['new']); await second
    expect(resource.loading.value).toBe(true)
    finishes[0](['old']); await first
    expect(resource.loading.value).toBe(false)
    expect(resource.data.value).toEqual(['new'])
    scope.stop()
  })
})

describe('usage and export contracts', () => {
  const instance = { start_time: '2026-10-10T08:00:00Z', end_time: '2026-10-10T08:30:00Z', hourly_price: 6, gpus: 2 } as Container
  it('uses the final cutoff for duration and estimates and accounts for multiple GPUs', () => {
    expect(durationText(instance.start_time, instance.end_time, Date.now())).toBe('0小时 30分 0秒')
    expect(instanceRate(instance)).toBe(12)
    expect(instanceEstimate(instance)).toBe(6)
  })
  it('does not invent a price or running duration for an instance that has not started', () => {
    expect(durationText(null)).toBe('尚未启动')
    expect(instanceEstimate({ gpus: 1, start_time: null } as Container)).toBeNull()
  })
  it('exports Chinese CSV and escapes quotes and spreadsheet formulas', () => {
    const text = csvText(['实例'], [['=HYPERLINK("bad")'], ['a,b']])
    expect(text.startsWith('\uFEFF')).toBe(true)
    expect(text).toContain('"\'=HYPERLINK(""bad"")"')
    expect(text).toContain('"a,b"')
  })
})
