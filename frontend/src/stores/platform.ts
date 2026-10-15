import { defineStore } from 'pinia'
import { ref } from 'vue'
import { consoleApi, type Capabilities } from '@/api/console'
export const usePlatformStore = defineStore('platform', () => {
  const capabilities = ref<Capabilities>()
  let pending: Promise<void> | undefined
  async function fetchCapabilities() {
    if (capabilities.value) return
    if (!pending)
      pending = consoleApi
        .capabilities()
        .then((response) => {
          capabilities.value = response.data
        })
        .finally(() => {
          pending = undefined
        })
    return pending
  }
  return { capabilities, fetchCapabilities }
})
