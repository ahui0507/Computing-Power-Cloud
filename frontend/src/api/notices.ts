import request from '@/utils/request'
import type { ApiResponse } from '@/types'

export interface Notice {
  id: number
  title: string
  message: string
  link: string
  created_at: string
  read: boolean
  expired: boolean
}
export interface NoticeList {
  unread_count: number
  items: Notice[]
}
export const noticesApi = {
  list: () =>
    request.get<ApiResponse<NoticeList>>('/notices', { silentError: true }),
  read: (id: number) => request.post(`/notices/${id}/read`),
  readAll: () => request.post('/notices/read-all'),
}
