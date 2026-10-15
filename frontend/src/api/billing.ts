import request from '@/utils/request'
import type { BillingPrice, BillingRecord, ApiResponse } from '@/types'
import type { CreditHistory } from './balanceCredits'

export const billingApi = {
  getCredits: (page = 1): Promise<ApiResponse<CreditHistory>> =>
    request.get('/billing/credits', { params: { page } }),
  // 获取GPU单价
  getPrice: (): Promise<ApiResponse<BillingPrice>> => {
    return request.get('/billing/price')
  },

  // 获取消费记录
  getRecords: (): Promise<ApiResponse<BillingRecord[]>> => {
    return request.get('/billing/records')
  },
}
