import { beforeEach, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { resetSessionData } from '../src/utils/session'
import { noticesApi, type NoticeList } from '../src/api/notices'
import { useNoticesStore } from '../src/stores/notices'

vi.mock('../src/api/notices', () => ({ noticesApi: { list: vi.fn() } }))
beforeEach(() => {
  resetSessionData()
  setActivePinia(createPinia())
  vi.clearAllMocks()
})
it('does not show old notifications or a late response after switching accounts', async () => {
  let finish!: (value: unknown) => void
  vi.mocked(noticesApi.list).mockImplementation(
    () =>
      new Promise((resolve) => {
        finish = resolve
      }) as ReturnType<typeof noticesApi.list>,
  )
  const store = useNoticesStore()
  store.list = { unread_count: 3, items: [] }
  const pending = store.refresh()
  resetSessionData()
  expect(store.list.unread_count).toBe(0)
  finish({
    code: 200,
    message: '',
    data: { unread_count: 2, items: [] } satisfies NoticeList,
  })
  await pending
  expect(store.list.unread_count).toBe(0)
  expect(store.loading).toBe(false)
})
