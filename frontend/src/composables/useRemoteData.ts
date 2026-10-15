import { ref, shallowRef, onScopeDispose } from 'vue'
import { onSessionReset, sessionRevision } from '@/utils/session'

export function useRemoteData<T>(loader: () => Promise<T>, initial: T) {
  const data = shallowRef<T>(initial)
  const loading = ref(false)
  const error = ref('')
  let generation = 0
  let active = true
  async function refresh() {
    const request = ++generation
    const session = sessionRevision()
    loading.value = true
    error.value = ''
    try {
      const value = await loader()
      if (active && request === generation && session === sessionRevision())
        data.value = value
    } catch (reason) {
      if (active && request === generation && session === sessionRevision()) {
        error.value =
          reason instanceof Error ? reason.message : '加载失败，请重试'
      }
    } finally {
      if (active && request === generation) loading.value = false
    }
  }
  onSessionReset(() => {
    generation++
    data.value = initial
    loading.value = false
    error.value = ''
  })
  onScopeDispose(() => {
    active = false
    generation++
  })
  return { data, loading, error, refresh }
}
