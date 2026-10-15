import { defineStore } from 'pinia'
import { computed } from 'vue'
import type { BillingPrice, BillingRecord } from '@/types'
import { billingApi } from '@/api'
import { useSessionResource } from '@/composables/useSessionResource'
export const useBillingStore = defineStore('billing', () => {
  const priceData = useSessionResource<BillingPrice | null, []>(
    null,
    async () => (await billingApi.getPrice()).data || null,
  )
  const recordData = useSessionResource<BillingRecord[], []>(
    [],
    async () => (await billingApi.getRecords()).data || [],
  )
  function calculateEstimatedCost(type: string, count: number, hours: number) {
    return (priceData.data.value?.[type.toLowerCase()] || 0) * count * hours
  }
  return {
    prices: priceData.data,
    records: recordData.data,
    loading: computed(
      () => priceData.loading.value || recordData.loading.value,
    ),
    pricesError: priceData.error,
    recordsError: recordData.error,
    fetchPrices: priceData.fetch,
    fetchRecords: recordData.fetch,
    calculateEstimatedCost,
  }
})
