import request from '@/utils/request'
import type { Image, ApiResponse } from '@/types'

export const imageApi = {
  // 获取公共镜像
  getPublicImages: (): Promise<ApiResponse<Image[]>> => {
    return request.get('/images/public')
  },

  // 获取用户私有镜像
  getMyImages: (): Promise<ApiResponse<Image[]>> => {
    return request.get('/images/my')
  },

  // 保存镜像
  saveImage: (data: {
    container_id: string
    name: string
    tag: string
    request_id: string
    desc: string
  }): Promise<ApiResponse<{ image_id: number; status: string }>> => {
    return request.post('/images/save', data)
  },
}
