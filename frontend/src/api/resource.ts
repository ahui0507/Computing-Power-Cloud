import request from '@/utils/request'
import type { ApplyResourceRequest, ApplyResourceResponse, ResourcePool, ResourceSummary, Container, ApiResponse, ReleaseResourceResponse } from '@/types'

export const resourceApi = {
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
  release: (containerId: string): Promise<ApiResponse<ReleaseResourceResponse>> => {
    return request.post('/resource/release', { container_id: containerId }, { timeout: 90000 })
  },

  // 获取我的资源
  getMyResources: (refresh = false): Promise<ApiResponse<Container[]>> => {
    return request.get('/resource/my', { params: refresh ? { refresh: true } : undefined })
  },
}
