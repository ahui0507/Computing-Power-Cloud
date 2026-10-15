import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { webcrypto } from 'node:crypto'

vi.mock('../src/api', () => ({
  resourceApi: { apply: vi.fn(), getMyResources: vi.fn(), getHistory: vi.fn(), getPools: vi.fn(), release: vi.fn() },
}))

import { resourceApi } from '../src/api'
import { useResourceStore } from '../src/stores/resource'
import type { Container, ContainerStatus } from '../src/types'

class MemoryStorage {
  values = new Map<string, string>()
  get length() { return this.values.size }
  key(index: number) { return Array.from(this.values.keys())[index] ?? null }
  getItem(key: string) { return this.values.get(key) ?? null }
  setItem(key: string, value: string) { this.values.set(key, value) }
  removeItem(key: string) { this.values.delete(key) }
}

const input = { pool_id: 1, gpu_count: 1, image_id: 1 }
const created = { code: 200, message: 'submitted', data: {
  container_id: 'container-1', node_id: 1, status: 'pending' as const,
  ssh_port: null, vnc_port: null, jupyter_port: null, jupyter_url: null, message: 'submitted',
} }

beforeEach(() => {
  vi.clearAllMocks()
  vi.stubGlobal('crypto', webcrypto)
  vi.stubGlobal('sessionStorage', new MemoryStorage())
  const local = new MemoryStorage()
  local.setItem('userInfo', '{"user_id":1}')
  vi.stubGlobal('localStorage', local)
  setActivePinia(createPinia())
  vi.mocked(resourceApi.getMyResources).mockResolvedValue({ code: 200, message: '', data: [] })
  vi.mocked(resourceApi.getPools).mockResolvedValue({ code: 200, message: '', data: [] })
})

describe('resource request recovery', () => {
  it('uses the authorized history response without truncating administrator results', async () => {
    const records = Array.from({ length: 25 }, (_, index) => ({ container_id: `history-${index}`, status: 'released', user_email: `user-${index}@example.com` }) as Container)
    vi.mocked(resourceApi.getHistory).mockResolvedValue({ code: 200, message: '', data: records })
    const store = useResourceStore()
    await store.fetchHistory()
    expect(store.historicalInstances).toHaveLength(25)
    expect(store.myContainers).toHaveLength(0)
  })
  it('keeps the request identity after an ambiguous network failure', async () => {
    const store = useResourceStore()
    vi.mocked(resourceApi.apply).mockRejectedValueOnce({ code: 0, message: 'timeout' })
    await expect(store.applyResource(input)).rejects.toMatchObject({ code: 0 })
    const first = vi.mocked(resourceApi.apply).mock.calls[0][1]
    vi.mocked(resourceApi.apply).mockResolvedValueOnce(created)
    await store.applyResource(input)
    expect(vi.mocked(resourceApi.apply).mock.calls[1][1]).toBe(first)
  })

  it('does not report an acknowledged creation as failed when refreshing the list fails', async () => {
    const store = useResourceStore()
    vi.mocked(resourceApi.apply).mockResolvedValue(created)
    vi.mocked(resourceApi.getMyResources).mockRejectedValue(new Error('list unavailable'))
    await expect(store.applyResource(input)).resolves.toMatchObject({ container_id: 'container-1' })
  })

  it('resetting the application explicitly starts a new request', async () => {
    const store = useResourceStore()
    vi.mocked(resourceApi.apply).mockRejectedValue({ code: 0 })
    await expect(store.applyResource(input)).rejects.toMatchObject({ code: 0 })
    const first = vi.mocked(resourceApi.apply).mock.calls[0][1]
    store.resetApplications()
    await expect(store.applyResource(input)).rejects.toMatchObject({ code: 0 })
    expect(vi.mocked(resourceApi.apply).mock.calls[1][1]).not.toBe(first)
  })

  it('returns a processing state while resource release is being recovered', async () => {
    const store = useResourceStore()
    vi.mocked(resourceApi.release).mockResolvedValue({ code: 200, message: '',
      data: { container_id: 'container-1', status: 'releasing' } })
    await expect(store.releaseResource('container-1')).resolves.toBe('releasing')
  })

  it('separates current instances and historical orders for every supported status', async () => {
    const statuses: ContainerStatus[] = ['pending', 'running', 'releasing', 'released', 'stopped', 'failed']
    const records = statuses.map((status) => ({ container_id: status, status }) as Container)
    vi.mocked(resourceApi.getMyResources).mockResolvedValue({ code: 200, message: '', data: records })
    const store = useResourceStore()
    await store.fetchMyResources()
    expect(store.activeInstances.map((item) => item.status)).toEqual(['pending', 'running', 'releasing'])
    expect(store.historicalInstances.map((item) => item.status)).toEqual(['released', 'stopped', 'failed'])
    expect(store.myContainers).toHaveLength(6)
  })

  it('keeps a releasing instance visible until confirmed released, then moves it to history', async () => {
    const store = useResourceStore()
    const record = { container_id: 'owned-instance', status: 'running' } as Container
    store.myContainers = [record]
    vi.mocked(resourceApi.release).mockResolvedValue({ code: 200, message: '',
      data: { container_id: record.container_id, status: 'releasing' } })
    vi.mocked(resourceApi.getMyResources).mockResolvedValueOnce({ code: 200, message: '',
      data: [{ ...record, status: 'releasing' }] })
    await store.releaseResource(record.container_id)
    expect(store.activeInstances).toHaveLength(1)
    expect(store.historicalInstances).toHaveLength(0)
    vi.mocked(resourceApi.getMyResources).mockResolvedValueOnce({ code: 200, message: '',
      data: [{ ...record, status: 'released' }] })
    await store.fetchMyResources()
    expect(store.activeInstances).toHaveLength(0)
    expect(store.historicalInstances[0].container_id).toBe(record.container_id)
  })
})
