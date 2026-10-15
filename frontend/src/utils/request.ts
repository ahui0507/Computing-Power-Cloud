import axios, {
  type AxiosRequestConfig,
  type InternalAxiosRequestConfig,
} from 'axios'
import { ElMessage } from 'element-plus'
import type { ApiResponse } from '@/types'

export interface RequestConfig extends AxiosRequestConfig {
  skipAuth?: boolean
  silentUnauthorized?: boolean
  silentError?: boolean
}

export class ApiError extends Error {
  constructor(
    public readonly code: number,
    message: string,
  ) {
    super(message)
    this.name = 'ApiError'
  }
}

let unauthorizedHandler: (() => void) | undefined

// 在应用入口连接认证状态与导航，HTTP 层不依赖路由或 Pinia。
export function setUnauthorizedHandler(handler: () => void) {
  unauthorizedHandler = handler
}

function rejectApiError(
  code: number,
  message: string,
  config?: RequestConfig,
): never {
  if (code === 401 && !config?.skipAuth) {
    message = '登录状态已过期，请重新登录'
    const sentToken = String(config?.headers?.Authorization || '').replace(
      /^Bearer /,
      '',
    )
    // 只有当前会话的首个失败请求可以清理会话，旧请求不能清除新登录。
    if (sentToken && sentToken === localStorage.getItem('token')) {
      localStorage.removeItem('token')
      localStorage.removeItem('userInfo')
      if (!config?.silentUnauthorized) {
        unauthorizedHandler?.()
        ElMessage.error(message)
      }
    }
    throw new ApiError(code, message)
  }
  if (!config?.silentError) ElMessage.error(message)
  throw new ApiError(code, message)
}

const service = axios.create({
  baseURL: '/api',
  timeout: 30000,
  headers: { 'Content-Type': 'application/json' },
})

service.interceptors.request.use((config: InternalAxiosRequestConfig) => {
  const token = localStorage.getItem('token')
  if (token && !(config as RequestConfig).skipAuth)
    config.headers.Authorization = `Bearer ${token}`
  return config
})

service.interceptors.response.use(
  (response) => {
    const envelope = response.data as ApiResponse
    // 兼容迁移期间仍返回 HTTP 200 的业务错误。
    if (envelope.code && envelope.code !== 200) {
      return rejectApiError(
        envelope.code,
        envelope.message || '操作失败',
        response.config,
      )
    }
    return response
  },
  (error) => {
    const code = error.response?.status || 0
    const message =
      error.response?.data?.message ||
      (code === 401
        ? '登录状态已过期，请重新登录'
        : code === 403
          ? '没有权限访问该资源'
          : code === 404
            ? '请求的资源不存在'
            : code === 0
              ? '网络错误，请检查网络连接'
              : '请求失败')
    return rejectApiError(code, message, error.config)
  },
)

// HTTP 层验证完整响应，API 客户端只返回响应内容。
const request = {
  get<T = ApiResponse>(url: string, config?: RequestConfig): Promise<T> {
    return service.get<T>(url, config).then((response) => response.data)
  },
  post<T = ApiResponse>(
    url: string,
    data?: unknown,
    config?: RequestConfig,
  ): Promise<T> {
    return service.post<T>(url, data, config).then((response) => response.data)
  },
}

export default request
