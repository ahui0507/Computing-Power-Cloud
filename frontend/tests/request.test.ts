import { beforeEach, describe, expect, it, vi } from 'vitest'
import axios, { AxiosError, type AxiosInstance } from 'axios'

vi.mock('element-plus', () => ({ ElMessage: { error: vi.fn() } }))
vi.mock('axios', async (importOriginal) => {
  const module = await importOriginal<typeof import('axios')>()
  return {
    ...module,
    default: { ...module.default, create: vi.fn(module.default.create.bind(module.default)) },
  }
})

import request, { ApiError, setUnauthorizedHandler } from '../src/utils/request'
import { storageApi } from '../src/api/storage'
import { authApi } from '../src/api/auth'
import { ElMessage } from 'element-plus'

const client = vi.mocked(axios.create).mock.results[0].value as AxiosInstance
const unauthorized = vi.fn()

beforeEach(() => {
  vi.clearAllMocks()
  const storage = new Map([['token', 'test-token'], ['userInfo', '{"user_id":1}']])
  vi.stubGlobal('localStorage', {
    getItem: (key: string) => storage.get(key) ?? null,
    setItem: (key: string, value: string) => storage.set(key, value),
    removeItem: (key: string) => storage.delete(key),
  })
  unauthorized.mockClear()
  setUnauthorizedHandler(unauthorized)
})

describe('API response and authentication handling', () => {
  it('downloads binary files with the current bearer token', async () => {
    const file = new Blob(['downloaded content'])
    client.defaults.adapter = async (config) => {
      expect(config.headers.Authorization).toBe('Bearer test-token')
      expect(config.params.path).toBe('data.csv')
      expect(config.responseType).toBe('blob')
      return { config, status: 200, statusText: 'OK', headers: {}, data: file }
    }
    const downloaded = await storageApi.download('data.csv')
    expect(await downloaded.text()).toBe('downloaded content')
  })
  it('returns the response envelope instead of an Axios wrapper', async () => {
    client.defaults.adapter = async (config) => ({
      config, status: 200, statusText: 'OK', headers: {},
      data: { code: 200, message: 'success', data: { container_id: 'container-1' } },
    })
    const result = await request.get<{ code: number; data: { container_id: string } }>('/resource/my')
    expect(result.data.container_id).toBe('container-1')
    expect(unauthorized).not.toHaveBeenCalled()
  })

  it('clears the session and invokes the application handler for HTTP 401', async () => {
    client.defaults.adapter = async (config) => {
      throw new AxiosError('Unauthorized', 'ERR_BAD_REQUEST', config, undefined, {
        config, status: 401, statusText: 'Unauthorized', headers: {},
        data: { code: 401, message: 'session expired' },
      })
    }
    await expect(request.get('/resource/my')).rejects.toMatchObject({ code: 401 })
    expect(localStorage.getItem('token')).toBeNull()
    expect(localStorage.getItem('userInfo')).toBeNull()
    expect(unauthorized).toHaveBeenCalledOnce()
  })

  it('also handles legacy HTTP 200 authentication errors', async () => {
    client.defaults.adapter = async (config) => ({
      config, status: 200, statusText: 'OK', headers: {},
      data: { code: 401, message: 'session expired' },
    })
    await expect(request.get('/resource/my')).rejects.toBeInstanceOf(ApiError)
    expect(localStorage.getItem('token')).toBeNull()
    expect(unauthorized).toHaveBeenCalledOnce()
  })

  it('keeps the session for authorization errors', async () => {
    client.defaults.adapter = async (config) => ({
      config, status: 200, statusText: 'OK', headers: {},
      data: { code: 403, message: 'forbidden' },
    })
    await expect(request.get('/admin/users')).rejects.toMatchObject({ code: 403 })
    expect(localStorage.getItem('token')).toBe('test-token')
    expect(unauthorized).not.toHaveBeenCalled()
  })

  it('quietly rejects an expired startup session without starting a second navigation', async () => {
    client.defaults.adapter = async (config) => ({
      config, status: 200, statusText: 'OK', headers: {},
      data: { code: 401, message: 'Could not validate credentials' },
    })
    await expect(authApi.getUserInfo({ silentUnauthorized: true })).rejects.toMatchObject({ code: 401 })
    expect(localStorage.getItem('token')).toBeNull()
    expect(unauthorized).not.toHaveBeenCalled()
    expect(ElMessage.error).not.toHaveBeenCalled()
  })

  it('reports concurrent session failures only once with a friendly message', async () => {
    client.defaults.adapter = async (config) => ({
      config, status: 200, statusText: 'OK', headers: {},
      data: { code: 401, message: 'Could not validate credentials' },
    })
    const results = await Promise.allSettled([request.get('/resource/my'), request.get('/resource/summary')])
    expect(results.every((result) => result.status === 'rejected')).toBe(true)
    expect(unauthorized).toHaveBeenCalledOnce()
    expect(ElMessage.error).toHaveBeenCalledOnce()
    expect(ElMessage.error).toHaveBeenCalledWith('登录状态已过期，请重新登录')
  })

  it('does not clear a new login when an old request returns 401', async () => {
    client.defaults.adapter = async (config) => {
      localStorage.setItem('token', 'new-login-token')
      return { config, status: 200, statusText: 'OK', headers: {},
        data: { code: 401, message: 'expired old session' } }
    }
    await expect(request.get('/resource/my')).rejects.toMatchObject({ code: 401 })
    expect(localStorage.getItem('token')).toBe('new-login-token')
    expect(unauthorized).not.toHaveBeenCalled()
    expect(ElMessage.error).not.toHaveBeenCalled()
  })

  it('retains wrong-password feedback and omits stale bearer tokens on login', async () => {
    client.defaults.adapter = async (config) => {
      expect(config.headers.Authorization).toBeUndefined()
      throw new AxiosError('Unauthorized', 'ERR_BAD_REQUEST', config, undefined, {
        config, status: 401, statusText: 'Unauthorized', headers: {},
        data: { code: 401, message: '邮箱或密码错误' },
      })
    }
    await expect(authApi.login({ email: 'test@example.com', password: 'wrong' }))
      .rejects.toMatchObject({ code: 401, message: '邮箱或密码错误' })
    expect(localStorage.getItem('token')).toBe('test-token')
    expect(ElMessage.error).toHaveBeenCalledWith('邮箱或密码错误')
    expect(unauthorized).not.toHaveBeenCalled()
  })

  it('does not hide transport failures during startup verification', async () => {
    client.defaults.adapter = async (config) => { throw new AxiosError('offline', 'ERR_NETWORK', config) }
    await expect(authApi.getUserInfo({ silentUnauthorized: true })).rejects.toMatchObject({ code: 0 })
    expect(localStorage.getItem('token')).toBe('test-token')
    expect(ElMessage.error).toHaveBeenCalledWith('网络错误，请检查网络连接')
  })
})
