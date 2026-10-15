import request from '@/utils/request'
import type { ApiResponse } from '@/types'

export const containerApi = {
  // 启动容器
  start: (containerId: string): Promise<ApiResponse> => {
    return request.post('/container/start', { container_id: containerId })
  },

  // 停止容器
  stop: (containerId: string): Promise<ApiResponse> => {
    return request.post('/container/stop', { container_id: containerId })
  },

  // 重启容器
  restart: (containerId: string): Promise<ApiResponse> => {
    return request.post('/container/restart', { container_id: containerId })
  },

  // 调整GPU数量
  resize: (containerId: string, newGpuCount: number): Promise<ApiResponse> => {
    return request.post('/container/resize', {
      container_id: containerId,
      new_gpu_count: newGpuCount,
    })
  },
}
