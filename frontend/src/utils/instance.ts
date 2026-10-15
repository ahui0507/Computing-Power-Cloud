import type { Container } from '@/types'
import dayjs from 'dayjs'

export function durationText(
  start: string | null | undefined,
  end?: string | null,
  now = Date.now(),
) {
  if (!start) return '尚未启动'
  const seconds = Math.max(
    0,
    Math.floor(
      ((end ? dayjs(end).valueOf() : now) - dayjs(start).valueOf()) / 1000,
    ),
  )
  const hours = Math.floor(seconds / 3600)
  return `${hours}小时 ${Math.floor((seconds % 3600) / 60)}分 ${seconds % 60}秒`
}
export function instanceRate(instance: Container) {
  if (isPackage(instance)) return 0
  return instance.hourly_price == null
    ? null
    : instance.hourly_price * instance.gpus
}
export function instanceEstimate(instance: Container, now = Date.now()) {
  if (isPackage(instance)) return 0
  const rate = instanceRate(instance)
  if (rate == null || !instance.start_time) return null
  const stop = instance.end_time ? dayjs(instance.end_time).valueOf() : now
  return (
    (Math.max(0, stop - dayjs(instance.start_time).valueOf()) / 3600000) * rate
  )
}
export const isCurrentInstance = (instance: Container) =>
  ['pending', 'running', 'releasing'].includes(instance.status)

export const instanceName = (instance: Container) => instance.instance_name || instance.container_id
export const isPackage = (instance: Container) => instance.package_amount != null
export const billingLabel = (instance: Container) => isPackage(instance) ? (instance.billing_mode === 'week' ? '包周' : '包日') : '按时计费'
export function packageUnitPrice(hourly: number, mode: 'on_demand' | 'day' | 'week') {
  const value = hourly * (mode === 'day' ? 24 * 0.8 : mode === 'week' ? 168 * 0.6 : 1)
  return Math.round((value + Number.EPSILON) * 10000) / 10000
}
