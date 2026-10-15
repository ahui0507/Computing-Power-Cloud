import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import type { ApiResponse, User } from '../src/types'

vi.mock('../src/api', () => ({
  authApi: { getUserInfo: vi.fn(), login: vi.fn() },
}))
vi.mock('../src/router', () => ({ default: { push: vi.fn() } }))

import { authApi } from '../src/api'
import { useAuthStore } from '../src/stores/auth'

const user: User = {
  user_id: 11,
  email: 'ordinary@example.com',
  role: 'user',
  balance: 100,
}
const response: ApiResponse<User> = {
  code: 200,
  message: 'success',
  data: user,
}

beforeEach(() => {
  vi.clearAllMocks()
  const storage = new Map<string, string>()
  vi.stubGlobal('localStorage', {
    getItem: (key: string) => storage.get(key) ?? null,
    setItem: (key: string, value: string) => storage.set(key, value),
    removeItem: (key: string) => storage.delete(key),
  })
  setActivePinia(createPinia())
})

describe('session bootstrap', () => {
  it('opens an anonymous session without sending an authenticated request', async () => {
    localStorage.setItem('userInfo', JSON.stringify({ ...user, role: 'admin' }))
    const store = useAuthStore()
    await store.init()
    expect(store.isAuthenticated).toBe(false)
    expect(localStorage.getItem('userInfo')).toBeNull()
    expect(authApi.getUserInfo).not.toHaveBeenCalled()
  })

  it('awaits one shared validation and ignores cached identity and role', async () => {
    localStorage.setItem('token', 'saved-token')
    localStorage.setItem('userInfo', JSON.stringify({ ...user, role: 'admin' }))
    let finish!: (value: ApiResponse<User>) => void
    vi.mocked(authApi.getUserInfo).mockImplementation(
      () =>
        new Promise((resolve) => {
          finish = resolve
        }),
    )
    const store = useAuthStore()
    const first = store.init()
    const second = store.init()
    expect(store.isAuthenticated).toBe(false)
    expect(store.isAdmin).toBe(false)
    expect(authApi.getUserInfo).toHaveBeenCalledOnce()
    finish(response)
    await Promise.all([first, second])
    expect(store.isAuthenticated).toBe(true)
    expect(store.userInfo).toEqual(user)
    await store.init()
    expect(authApi.getUserInfo).toHaveBeenCalledOnce()
  })

  it('clears invalid saved credentials and lets navigation continue to login', async () => {
    localStorage.setItem('token', 'expired-token')
    localStorage.setItem('userInfo', '{bad cached JSON')
    vi.mocked(authApi.getUserInfo).mockRejectedValue({ code: 401 })
    const store = useAuthStore()
    await expect(store.init()).resolves.toBeUndefined()
    expect(authApi.getUserInfo).toHaveBeenCalledWith({
      silentUnauthorized: true,
    })
    expect(store.isAuthenticated).toBe(false)
    expect(localStorage.getItem('token')).toBeNull()
    expect(localStorage.getItem('userInfo')).toBeNull()
  })

  it('keeps saved credentials and allows retry after a transport failure', async () => {
    localStorage.setItem('token', 'saved-token')
    vi.mocked(authApi.getUserInfo)
      .mockRejectedValueOnce({ code: 0 })
      .mockResolvedValueOnce(response)
    const store = useAuthStore()
    await expect(store.init()).rejects.toMatchObject({ code: 0 })
    expect(localStorage.getItem('token')).toBe('saved-token')
    expect(store.isAuthenticated).toBe(false)
    await store.init()
    expect(store.isAuthenticated).toBe(true)
  })

  it('does not restore a session after logging out during validation', async () => {
    localStorage.setItem('token', 'saved-token')
    let finish!: (value: ApiResponse<User>) => void
    vi.mocked(authApi.getUserInfo).mockImplementation(
      () =>
        new Promise((resolve) => {
          finish = resolve
        }),
    )
    const store = useAuthStore()
    const pending = store.init()
    store.resetSession()
    finish(response)
    await pending
    expect(store.isAuthenticated).toBe(false)
    expect(localStorage.getItem('userInfo')).toBeNull()
  })

  it('validates a new login after discarding an expired session', async () => {
    localStorage.setItem('token', 'expired-token')
    vi.mocked(authApi.getUserInfo)
      .mockRejectedValueOnce({ code: 401 })
      .mockResolvedValueOnce(response)
    vi.mocked(authApi.login).mockResolvedValue({
      code: 200,
      message: '',
      data: { user_id: user.user_id, token: 'new-token' },
    })
    const store = useAuthStore()
    await store.init()
    expect(await store.login(user.email, 'test-password')).toBe(true)
    expect(store.isAuthenticated).toBe(true)
    expect(localStorage.getItem('token')).toBe('new-token')
  })
})
