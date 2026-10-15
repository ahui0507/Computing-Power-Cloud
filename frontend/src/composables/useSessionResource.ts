import { computed, ref } from 'vue'
import type { Ref } from 'vue'
import { onSessionReset, sessionRevision } from '@/utils/session'

export function useSessionResource<T, A extends unknown[]>(
  initial: T,
  loader: (...args: A) => Promise<T>,
) {
  const data = ref(initial) as Ref<T>
  const error = ref('')
  const pending = ref(0)
  let generation = 0
  onSessionReset(() => {
    generation++
    data.value = initial
    error.value = ''
    pending.value = 0
  })
  async function fetch(...args: A) {
    const request = ++generation
    const session = sessionRevision()
    pending.value++
    error.value = ''
    try {
      const value = await loader(...args)
      if (request === generation && session === sessionRevision())
        data.value = value
      return value
    } catch (reason) {
      if (request === generation && session === sessionRevision()) {
        error.value =
          reason instanceof Error ? reason.message : '加载失败，请重试'
      }
      throw reason
    } finally {
      if (session === sessionRevision())
        pending.value = Math.max(0, pending.value - 1)
    }
  }
  return { data, error, loading: computed(() => pending.value > 0), fetch }
}
