import { onMounted, onUnmounted } from 'vue'

export function useAutoRefresh(
  refresh: () => Promise<unknown>,
  interval = 15000,
) {
  let timer: ReturnType<typeof setInterval> | undefined
  let busy = false
  let disposed = false
  const run = async () => {
    if (busy || disposed || document.hidden) return
    busy = true
    try {
      await refresh()
    } catch {
      /* 页面状态或请求层负责展示错误 */
    } finally {
      busy = false
    }
  }
  const visible = () => {
    if (!document.hidden) void run()
  }
  onMounted(() => {
    void run()
    timer = setInterval(() => {
      void run()
    }, interval)
    document.addEventListener('visibilitychange', visible)
  })
  onUnmounted(() => {
    disposed = true
    clearInterval(timer)
    document.removeEventListener('visibilitychange', visible)
  })
  return run
}
