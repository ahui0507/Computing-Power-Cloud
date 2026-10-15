import { defineStore } from 'pinia'
import { computed } from 'vue'
import type { Image, ApiResponse } from '@/types'
import request from '@/utils/request'
import { imageApi } from '@/api'
import { useSessionResource } from '@/composables/useSessionResource'
export const useImageStore = defineStore('image', () => {
  const publicData = useSessionResource<Image[], []>(
    [],
    async () => (await imageApi.getPublicImages()).data || [],
  )
  const privateData = useSessionResource<Image[], []>(
    [],
    async () => (await imageApi.getMyImages()).data || [],
  )
  const available = useSessionResource<Record<number, number[]>, []>(
    {},
    async () =>
      (
        await request.get<ApiResponse<Record<number, number[]>>>(
          '/images/availability',
        )
      ).data || {},
  )
  return {
    publicImages: publicData.data,
    myImages: privateData.data,
    loading: computed(
      () =>
        publicData.loading.value ||
        privateData.loading.value ||
        available.loading.value,
    ),
    error: computed(
      () =>
        publicData.error.value ||
        privateData.error.value ||
        available.error.value,
    ),
    fetchAvailability: available.fetch,
    isAvailable: (id: number, pool?: number) =>
      pool
        ? (available.data.value[pool] || []).includes(id)
        : Object.values(available.data.value).some((ids) => ids.includes(id)),
    fetchPublicImages: publicData.fetch,
    fetchMyImages: privateData.fetch,
    getAllImages: () => [...publicData.data.value, ...privateData.data.value],
  }
})
