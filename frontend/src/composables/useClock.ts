import { ref, onMounted, onUnmounted } from 'vue'
export function useClock() {
  const now = ref(Date.now())
  let timer: ReturnType<typeof setInterval>
  onMounted(() => {
    timer = setInterval(() => {
      now.value = Date.now()
    }, 1000)
  })
  onUnmounted(() => clearInterval(timer))
  return now
}
