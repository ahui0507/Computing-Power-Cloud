import type { TelemetryState } from '@/api/monitoring'
export const telemetryText = (value: TelemetryState) =>
  ({
    live: '采集正常',
    partial: '部分指标缺失',
    stale: '采集已过期',
    missing: '尚未采集',
  })[value]
export const telemetryType = (
  value: TelemetryState,
): 'success' | 'warning' | 'danger' | 'info' =>
  (
    ({
      live: 'success',
      partial: 'warning',
      stale: 'danger',
      missing: 'info',
    }) as const
  )[value]
export function metricText(
  value: number | null | undefined,
  unit = '',
  decimals = 1,
) {
  return value == null || !Number.isFinite(value)
    ? '—'
    : `${value.toFixed(decimals)}${unit}`
}
export function remainingTime(minutes: number | null | undefined) {
  if (minutes == null) return '暂无计费中的实例'
  if (minutes < 1) return '不足1分钟'
  if (minutes < 60) return `约 ${Math.floor(minutes)} 分钟`
  return `约 ${Math.floor(minutes / 60)} 小时 ${Math.floor(minutes % 60)} 分钟`
}
