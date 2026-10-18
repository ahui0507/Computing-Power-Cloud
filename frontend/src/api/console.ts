import request from '@/utils/request'
import type { ApiResponse } from '@/types'
export interface Capabilities {
  email_registration: boolean
  account_creation: 'admin_only'
  image_snapshot: boolean
  ssh_access: boolean
  jobs: boolean
  workspace_path: string
  max_upload_bytes: number
  recharge_mode: string
}
export interface SSHKey {
  id: number
  name: string
  fingerprint: string
  created_at: string
}
export interface ConsoleJob {
  instance_name?: string
  job_id: string
  name: string
  container_id: string
  command: string
  status:
    'pending' | 'running' | 'completed' | 'failed' | 'cancelled' | 'interrupted'
  created_at: string
  started_at?: string
  finished_at?: string
  exit_code?: number
}
export interface AuditEntry {
  id: number
  user_id: number
  action: string
  resource: string
  ip: string
  timestamp: string
  result: string
}
export const consoleApi = {
  revokeSessions: () => request.post('/account/revoke-sessions'),
  capabilities: () =>
    request.get<ApiResponse<Capabilities>>('/platform/capabilities', {
      skipAuth: true,
    }),
  password: (old_password: string, new_password: string) =>
    request.post('/account/password', { old_password, new_password }),
  keys: () => request.get<ApiResponse<SSHKey[]>>('/account/keys'),
  addKey: (name: string, public_key: string) =>
    request.post('/account/keys', { name, public_key }),
  deleteKey: (id: number) => request.post('/account/keys/delete', { id }),
  registerImage: (data: { name: string; tag: string; desc: string }) =>
    request.post('/images/register', data),
  deleteImage: (id: number) => request.post('/images/delete', { id }),
  deletePool: (id: number) => request.post('/admin/delete_pool', { id }),
  jobs: () =>
    request.get<ApiResponse<ConsoleJob[]>>('/jobs', { silentError: true }),
  submitJob: (data: {
    job_id: string
    name: string
    command: string
    container_id: string
  }) => request.post<ApiResponse<ConsoleJob>>('/jobs', data),
  jobLogs: (id: string) =>
    request.get<ApiResponse<{ logs: string }>>(`/jobs/${id}/logs`, {
      silentError: true,
    }),
  cancelJob: (id: string) => request.post(`/jobs/${id}/cancel`),
  audit: (params: Record<string, string | number>) =>
    request.get<ApiResponse<{ items: AuditEntry[]; total: number }>>(
      '/admin/audit',
      { params },
    ),
}
