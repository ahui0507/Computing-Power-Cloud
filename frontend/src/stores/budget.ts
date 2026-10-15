import { defineStore } from 'pinia'
import { monitoringApi, type UsageSummary } from '@/api/monitoring'
import { useSessionResource } from '@/composables/useSessionResource'
export const useBudgetStore = defineStore('budget', () => {
  const resource = useSessionResource<UsageSummary | null, []>(
    null,
    async () => (await monitoringApi.usage()).data || null,
  )
  return {
    summary: resource.data,
    loading: resource.loading,
    error: resource.error,
    refresh: resource.fetch,
  }
})
