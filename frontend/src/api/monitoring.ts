import request from '@/utils/request'
import type { ApiResponse, Node, GPU } from '@/types'

export type TelemetryState = 'live' | 'partial' | 'stale' | 'missing'
export interface GPUMetric extends GPU {
  index: number
  utilization: number | null
  memory_used_mb: number | null
  memory_total_mb: number | null
  temperature: number | null
  power_watts: number | null
}
export interface MonitoredNode extends Node {
  telemetry_state: TelemetryState
  collected_at: string | null
  received_at: string | null
  age_seconds: number | null
  stale_after_seconds: number
  gpu_error: string | null
  ownership_error: string | null
  schedulable: boolean
  cpu_cores: number | null
  memory_total_mb: number | null
  memory_used_mb: number | null
  gpu_list?: GPUMetric[]
}
export interface MetricPoint {
  at: string
  cpu_usage: number | null
  mem_usage: number | null
  samples: number
  gpus: {
    gpu_id: number
    utilization: number | null
    memory_used_mb: number | null
    temperature: number | null
    power_watts: number | null
  }[]
}
export interface MetricHistory {
  minutes: number
  bucket_seconds: number
  points: MetricPoint[]
}
export interface InstanceMetrics {
  runtime?: {
    ephemeral_storage?: {
      state: 'live' | 'stale' | 'missing'
      used_bytes: number | null
      limit_bytes: number | null
      remaining_bytes: number | null
      used_percent: number | null
      sampled_at: string | null
      warning: 'none' | 'warning' | 'critical' | 'unknown'
    }
    state: 'live' | 'missing'
    cpu_percent: number | null
    memory_percent: number | null
    restart_count: number | null
    last_exit_reason: string | null
  }
  telemetry_state: TelemetryState
  received_at: string | null
  gpu_list: GPUMetric[]
}
export interface QuotaLimits {
  storage_limit_gib?: number | null
  storage_mode?: 'fixed' | 'percent'
  storage_share_percent?: number | null
  max_gpus: number
  max_instances: number
  low_balance_amount: number
  low_balance_minutes: number
}
export interface UsageSummary extends QuotaLimits {
  storage_inherited?: boolean
  inherited: boolean
  default_limits: QuotaLimits
  used_gpus: number
  used_instances: number
  remaining_gpus: number
  remaining_instances: number
  balance: number
  unsettled_estimate: number
  available_balance: number
  hourly_cost: number
  estimated_remaining_minutes: number | null
  warning: 'none' | 'low' | 'insufficient'
  minimum_balance_minutes: number
  billing_enabled: boolean
  debt_started_at: string | null
  grace_expires_at: string | null
  grace_hours: number
}
export const monitoringApi = {
  nodes: () =>
    request.get<ApiResponse<MonitoredNode[]>>('/cluster/nodes', {
      silentError: true,
    }),
  node: (id: number) =>
    request.get<ApiResponse<MonitoredNode>>(`/cluster/node/${id}`, {
      silentError: true,
    }),
  history: (id: number, minutes: number) =>
    request.get<ApiResponse<MetricHistory>>(`/cluster/node/${id}/history`, {
      params: { minutes },
      silentError: true,
    }),
  instance: (id: string) =>
    request.get<ApiResponse<InstanceMetrics>>(`/resource/${id}/metrics`, {
      silentError: true,
    }),
  usage: () =>
    request.get<ApiResponse<UsageSummary>>('/resource/usage', {
      silentError: true,
    }),
  quota: (id: number) =>
    request.get<ApiResponse<UsageSummary>>(`/admin/quotas/${id}`),
  setQuota: (id: number, data: QuotaLimits & { inherited: boolean }) =>
    request.post<ApiResponse<UsageSummary>>(`/admin/quotas/${id}`, data),
}
