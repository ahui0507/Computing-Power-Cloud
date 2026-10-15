import request, { type RequestConfig } from '@/utils/request'
import type { LoginRequest, AuthResponse, User, ApiResponse } from '@/types'

export const authApi = {
  // 登录
  login: (data: LoginRequest): Promise<ApiResponse<AuthResponse>> => {
    return request.post('/auth/login', data, { skipAuth: true })
  },

  // 获取用户信息
  getUserInfo: (config?: RequestConfig): Promise<ApiResponse<User>> => {
    return request.get('/auth/user_info', config)
  },
}
