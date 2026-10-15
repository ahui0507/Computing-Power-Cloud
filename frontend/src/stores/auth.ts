import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import type { User } from '@/types'
import { authApi } from '@/api'
import router from '@/router'
import type { RequestConfig } from '@/utils/request'
import { resetSessionData } from '@/utils/session'

export const useAuthStore = defineStore('auth', () => {
  const token = ref<string>(localStorage.getItem('token') || '')
  const userInfo = ref<User | null>(null)
  let initialized = false
  let initialization: Promise<void> | undefined

  const isAuthenticated = computed(() => !!token.value && !!userInfo.value)
  const isAdmin = computed(() => userInfo.value?.role === 'admin')
  const isAuditor = computed(() => userInfo.value?.role === 'auditor')

  // 登录
  async function login(email: string, password: string) {
    const res = await authApi.login({ email, password })
    if (res.data) {
      resetSessionData()
      userInfo.value = null
      token.value = res.data.token
      localStorage.setItem('token', res.data.token)
      await fetchUserInfo()
      return true
    }
    return false
  }

  // 获取用户信息
  async function fetchUserInfo(config?: RequestConfig) {
    const requestedToken = token.value
    try {
      const res = await authApi.getUserInfo(config)
      if (res.data && token.value === requestedToken) {
        userInfo.value = res.data
        localStorage.setItem('userInfo', JSON.stringify(res.data))
        initialized = true
      }
    } catch (error: any) {
      if (error.code === 401 && token.value === requestedToken) {
        resetSession()
      }
      throw error
    }
  }

  function resetSession() {
    resetSessionData()
    token.value = ''
    userInfo.value = null
    localStorage.removeItem('token')
    localStorage.removeItem('userInfo')
    initialized = true
  }

  // 登出
  function logout() {
    resetSession()
    router.push('/login')
  }

  // 页面进入前验证保存的令牌；并发导航共用一次验证，不信任缓存的用户角色。
  function init(): Promise<void> {
    if (initialized) return Promise.resolve()
    if (initialization) return initialization
    token.value = localStorage.getItem('token') || ''
    if (!token.value) {
      resetSession()
      return Promise.resolve()
    }
    initialization = fetchUserInfo({ silentUnauthorized: true })
      .catch((error) => {
        if (error.code !== 401) throw error
      })
      .finally(() => {
        initialization = undefined
      })
    return initialization
  }

  return {
    token,
    userInfo,
    isAuthenticated,
    isAdmin,
    isAuditor,
    login,
    fetchUserInfo,
    logout,
    resetSession,
    init,
  }
})
