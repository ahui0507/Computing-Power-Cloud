import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import type { ResourcePool, Container, ApplyResourceRequest } from '@/types'
import { resourceApi } from '@/api'
import type { ReleaseConfirmation } from '@/api/resource'
import {
  applicationKey,
  finishApplication,
  resetApplications,
} from '@/utils/resource-request'
import { useSessionResource } from '@/composables/useSessionResource'
import { sessionRevision, onSessionReset } from '@/utils/session'
import { isCurrentInstance } from '@/utils/instance'

export const useResourceStore = defineStore('resource', () => {
  const poolData = useSessionResource<ResourcePool[], []>(
    [],
    async () => (await resourceApi.getPools()).data || [],
  )
  const instanceData = useSessionResource<Container[], [refresh?: boolean]>(
    [],
    async (refresh = false) =>
      (await resourceApi.getMyResources(refresh)).data || [],
  )
  const pools = poolData.data
  const historyData = useSessionResource<Container[], []>([], async () => (await resourceApi.getHistory()).data || [])
  const historyFetched = ref(false)
  const myContainers = instanceData.data
  const applying = ref(false)
  const releasingIds = ref<string[]>([])
  const loading = computed(
    () => poolData.loading.value || instanceData.loading.value,
  )
  const activeInstances = computed(() =>
    myContainers.value.filter(isCurrentInstance),
  )
  const historicalInstances = computed(() => historyFetched.value ? historyData.data.value : myContainers.value.filter((item) => !isCurrentInstance(item)).slice(0, 10))
  async function fetchHistory() {
    const scope = sessionRevision()
    await historyData.fetch()
    if (scope === sessionRevision()) historyFetched.value = true
  }
  onSessionReset(() => {
    historyFetched.value = false
    applying.value = false
    releasingIds.value = []
  })
  async function applyResource(data: ApplyResourceRequest) {
    const scope = sessionRevision()
    applying.value = true
    try {
      const response = await resourceApi.apply(data, applicationKey(data))
      if (scope !== sessionRevision()) return
      if (response.data) {
        finishApplication(data)
        void Promise.allSettled([instanceData.fetch(), poolData.fetch(), ...(historyFetched.value ? [historyData.fetch()] : [])])
        return response.data
      }
    } catch (error) {
      const code = (error as { code?: number }).code
      if (
        scope === sessionRevision() &&
        code &&
        [400, 401, 403, 409, 422, 501].includes(code)
      )
        finishApplication(data)
      throw error
    } finally {
      if (scope === sessionRevision()) applying.value = false
    }
  }
  async function releaseResource(containerId: string, confirmation?: ReleaseConfirmation) {
    const scope = sessionRevision()
    if (releasingIds.value.includes(containerId)) return 'releasing'
    releasingIds.value.push(containerId)
    try {
      const response = await resourceApi.release(containerId, confirmation)
      if (scope === sessionRevision())
        await Promise.allSettled([instanceData.fetch(), poolData.fetch(), ...(historyFetched.value ? [historyData.fetch()] : [])])
      return response.data?.status
    } finally {
      if (scope === sessionRevision())
        releasingIds.value = releasingIds.value.filter(
          (id) => id !== containerId,
        )
    }
  }
  return {
    pools,
    myContainers,
    loading,
    activeInstances,
    historicalInstances,
    historyLoading: historyData.loading,
    historyError: historyData.error,
    fetchHistory,
    applying,
    releasingIds,
    poolsLoading: poolData.loading,
    instancesLoading: instanceData.loading,
    poolsError: poolData.error,
    instancesError: instanceData.error,
    fetchPools: poolData.fetch,
    fetchMyResources: instanceData.fetch,
    applyResource,
    releaseResource,
    resetApplications,
  }
})
