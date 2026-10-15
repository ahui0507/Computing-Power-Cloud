import request from '@/utils/request'
import type { User, ApiResponse } from '@/types'
import type {
  BalanceCredit,
  CreditHistory,
  CreditRequest,
} from './balanceCredits'

export const adminApi = {
  createUser: (email: string): Promise<ApiResponse<User>> =>
    request.post('/admin/users', { email }),
  addBalance: (
    userId: number,
    data: CreditRequest,
  ): Promise<ApiResponse<BalanceCredit>> =>
    request.post(`/admin/users/${userId}/balance-credits`, data),

  balanceCredits: (
    userId: number,
    page = 1,
  ): Promise<ApiResponse<CreditHistory>> =>
    request.get(`/admin/users/${userId}/balance-credits`, { params: { page } }),
  // 获取所有用户
  getUsers: (): Promise<ApiResponse<User[]>> => {
    return request.get('/admin/users')
  },

  // 设置用户角色
  setRole: (userId: number, role: 'user' | 'admin'): Promise<ApiResponse> => {
    return request.post('/admin/set_role', { user_id: userId, role })
  },

  // 获取GPU类型列表
  getGpuTypes: (): Promise<
    ApiResponse<Array<{ code: string; name: string; memory_mb: number }>>
  > => {
    return request.get('/admin/gpu_types')
  },

  // 创建资源池
  createPool: (data: {
    name: string
    gpu_type: string
    node_ids: number[]
  }): Promise<ApiResponse<{ pool_id: number }>> => {
    return request.post('/admin/create_pool', data)
  },
}
