import request from '@/utils/request'
import type { ApplyResourceRequest, ApplyResourceResponse, ResourcePool, ResourceSummary, Container, ApiResponse, ReleaseResourceResponse } from '@/types'

export const resourceApi = {
  releaseCheck: (id: string): Promise<ApiResponse<ReleaseCheck>> => request.get(`/resource/${encodeURIComponent(id)}/release-check`),
  schedule: (id: string, release_at: string | null) => request.post(`/resource/${encodeURIComponent(id)}/release-schedule`, { release_at }),
  enqueue: (data: ApplyResourceRequest, key: string): Promise<ApiResponse<QueueEntry>> => request.post('/resource/queue', data, { headers: { 'Idempotency-Key': key } }),
  queue: (): Promise<ApiResponse<QueueEntry[]>> => request.get('/resource/queue'),
  cancelQueue: (id: number) => request.post(`/resource/queue/${id}/cancel`),
  getHistory: (): Promise<ApiResponse<Container[]>> => request.get('/resource/history'),
  getSummary: (): Promise<ApiResponse<ResourceSummary>> => {
    return request.get('/resource/summary')
  },

  // 获取资源池
  getPools: (): Promise<ApiResponse<ResourcePool[]>> => {
    return request.get('/resource/pools')
  },

  // 申请资源
  apply: (data: ApplyResourceRequest, key?: string): Promise<ApiResponse<ApplyResourceResponse>> => {
    return request.post('/resource/apply', data, {
      timeout: 120000, headers: key ? { 'Idempotency-Key': key } : undefined,
    })
  },

  // 释放资源
  release: (containerId: string, confirmation?: ReleaseConfirmation): Promise<ApiResponse<ReleaseResourceResponse>> => {
    return request.post('/resource/release', { container_id: containerId, ...confirmation }, { timeout: 90000 })
  },

  // 获取我的资源
  getMyResources: (refresh = false): Promise<ApiResponse<Container[]>> => {
    return request.get('/resource/my', { params: refresh ? { refresh: true } : undefined })
  },
}

export interface ReleaseCheck {
  confirmation_token?: string | null
  checked_at?: string
  checks_complete?: boolean
  processes_checked?: boolean
  processes?: { pid: number; name: string; category: 'program' | 'notebook' | 'terminal'; elapsed_seconds: number }[]
  notebooks_checked?: boolean
  notebooks?: { id: string; name: string; state: string; connections: number }[]
  tmux_checked?: boolean
  tmux_sessions?: { name: string; windows: number; attached: number }[]
  jobs_checked: boolean
  active_jobs: { name: string; job_id: string }[]
  saving_image: boolean
  persistent_path: string
  message: string
}

export interface ReleaseConfirmation {
  confirmation_token?: string
  confirm_unchecked: boolean
}

export interface QueueEntry {
  id: number
  status: 'waiting' | 'dispatching' | 'started' | 'cancelled' | 'failed' | 'expired'
  parameters: ApplyResourceRequest
  created_at: string
  expires_at: string
  container_id: string | null
  message: string
}
