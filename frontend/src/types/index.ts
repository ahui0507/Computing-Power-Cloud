// 用户相关类型
export interface User {
  user_id: number
  email: string
  role: 'user' | 'admin' | 'auditor'
  balance: number
  username?: string
  phone?: string
  quota?: import('@/api/monitoring').UsageSummary
}

// 认证相关
export interface LoginRequest {
  email: string
  password: string
}

export interface AuthResponse {
  user_id: number
  token: string
  role?: string
}

// 镜像相关
export interface Image {
  display_name?: string | null
  supports_ssh?: boolean
  snapshot_status?: 'saving' | 'ready' | 'failed' | 'deleting' | 'retired'
  snapshot_error?: string | null
  is_snapshot?: boolean
  image_id: number
  name: string
  tag: string
  desc: string
  size?: number
  is_public?: boolean
  created_at?: string
}

// 节点相关
export interface Node {
  node_id: number
  name: string
  ip: string
  gpus_total: number
  gpus_free: number
  cpu_usage: number | null
  mem_usage: number | null
  status: string
  gpu_list?: GPU[]
}

export interface GPU {
  gpu_id: number
  type: string
  status:
    | 'free'
    | 'allocated'
    | 'occupied'
    | 'reserved'
    | 'maintenance'
    | 'external'
    | 'unknown'
}

// 资源池相关
export interface ResourcePool {
  pool_id: number
  name: string
  gpu_type: string
  total_gpus: number
  free_gpus: number
  physical_free_gpus?: number
  max_gpus_per_instance?: number
  queue_max_gpus_per_instance?: number
  cpu_cores_per_gpu?: number
  node_gpu_count?: number | null
  system_cpu_percent?: number
  system_ram_percent?: number
  ram_mb_per_gpu?: number
  available_cpu_cores?: number
  available_ram_mb?: number
  ephemeral_storage_gib_per_gpu?: number | null
  memory_mb?: number | null
  compute_capability?: string | null
  architecture?: string | null
  driver_versions?: string[]
  driver_cuda_versions?: string[]
  cuda_arch_max?: string | null
  recommended_environment?: string | null
  hourly_price?: number
  daily_price?: number
  weekly_price?: number
}

export interface ResourceSummary {
  total_gpus: number
  free_gpus: number
  used_gpus: number
  unavailable_gpus: number
}

// 容器/实例相关
export type ContainerStatus =
  'pending' | 'running' | 'stopped' | 'failed' | 'releasing' | 'released'

export interface Container {
  workspace_path?: string
  persistent_path?: string
  storage_layout?: 'legacy' | 'separate-v1'
  ssh_enabled?: boolean
  container_id: string
  instance_name?: string
  user_email?: string | null
  node_id: number
  node_ip?: string
  gpus: number
  cpu_cores?: number | null
  node_gpu_count?: number | null
  ram_mb?: number | null
  ephemeral_storage_gib?: number | null
  image: string
  status: ContainerStatus
  start_time: string | null
  created_at?: string | null
  end_time?: string | null
  hourly_price?: number | null
  billing_mode?: string
  package_amount?: number | null
  package_expires_at?: string | null
  scheduled_release_at?: string | null
  release_after_hours?: number | null
  package_refunded?: boolean
  settled_amount?: number | null
  pool_id?: number | null
  image_id?: number | null
  status_message?: string | null
  ssh_port?: number | null
  vnc_port?: number | null
  jupyter_port?: number | null
  jupyter_url?: string | null
}

export interface ApplyResourceResponse {
  persistent_path?: string
  storage_scope?: 'user'
  personal_storage_limit_gib?: number | null
  container_id: string
  node_id: number
  status: ContainerStatus
  ssh_port: number | null
  vnc_port: number | null
  jupyter_port: number | null
  jupyter_url: string | null
  message: string
}

export interface ApplyResourceRequest {
  pool_id: number
  gpu_count: number
  image_id: number
  duration?: number
  billing_mode?: 'on_demand' | 'prepaid' | 'day' | 'week'
}

export interface ReleaseResourceResponse {
  container_id: string
  status: 'releasing' | 'released'
}

// 存储相关
export interface FileItem {
  name: string
  size: number
  type: 'file' | 'folder'
  path?: string
}

// 计费相关
export interface BillingPrice {
  [gpuType: string]: number
  v100: number
  a100: number
  rtx4090: number
  k80: number
}

export interface BillingRecord {
  id: number
  container_id: string
  instance_name?: string | null
  billing_mode?: string
  charged_at?: string | null
  amount: number
  start_time: string
  end_time: string
}

// 集群监控
export interface ClusterMetrics {
  cluster_load: number | null
  gpu_usage: number
  network_in: number | null
  network_out: number | null
}

// API响应基础类型
export interface ApiResponse<T = unknown> {
  success?: boolean
  message: string
  data?: T
  code: number
}

// 作业相关
export interface Job {
  job_id: string
  container_id: string
  instance_name?: string
  name: string
  status: 'pending' | 'running' | 'completed' | 'failed' | 'cancelled'
  created_at: string
  started_at?: string
  finished_at?: string
  command?: string
  logs?: string
}

// 通知相关
export interface Notification {
  id: string
  type: 'success' | 'warning' | 'error' | 'info'
  title: string
  message: string
  timestamp: string
  read: boolean
}

// WebSocket消息类型
export interface WSMessage {
  type: 'task_update' | 'container_status' | 'notification' | 'metrics'
  data: any
}

// 审批相关（管理员）
export interface ApprovalRequest {
  id: number
  user_id: number
  user_email: string
  pool_id: number
  gpu_count: number
  image_id: number
  status: 'pending' | 'approved' | 'rejected'
  created_at: string
  reviewed_at?: string
  reviewer_id?: number
  remark?: string
}
