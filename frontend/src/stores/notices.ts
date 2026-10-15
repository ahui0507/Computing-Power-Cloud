import { defineStore } from 'pinia'
import { noticesApi, type NoticeList } from '@/api/notices'
import { useSessionResource } from '@/composables/useSessionResource'

export const useNoticesStore = defineStore('notices', () => {
  const remote = useSessionResource<NoticeList, []>(
    { unread_count: 0, items: [] },
    async () =>
      (await noticesApi.list()).data || { unread_count: 0, items: [] },
  )
  return {
    list: remote.data,
    loading: remote.loading,
    error: remote.error,
    refresh: remote.fetch,
  }
})
