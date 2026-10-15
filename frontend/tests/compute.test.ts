import { describe, expect, it } from 'vitest'
import { maximumCards, shareText, instanceShareText } from '../src/utils/compute'
import type { ResourcePool, Container } from '../src/types'

const pool: ResourcePool = { pool_id: 1, name: 'K80', gpu_type: 'K80', total_gpus: 4,
  free_gpus: 4, max_gpus_per_instance: 2, node_gpu_count: 4 }

describe('compute allocation display', () => {
  it('limits one instance to a single node and the user quota', () => {
    expect(maximumCards(pool, 4)).toBe(2)
    expect(maximumCards(pool, 1)).toBe(1)
    expect(maximumCards({ ...pool, free_gpus: 0 }, 4)).toBe(0)
    expect(maximumCards(undefined, 4)).toBe(0)
  })
  it('shows proportions and handles nodes with different GPU counts honestly', () => {
    expect(shareText(1, 4)).toBe('可分配额度的 25%')
    expect(shareText(2, 4)).toBe('可分配额度的 50%')
    expect(shareText(4, 4)).toBe('可分配额度的 100%')
    expect(shareText(1, 8)).toBe('可分配额度的 12.5%')
    expect(shareText(1, undefined)).toBe('按实际节点 GPU 占比')
  })
  it('keeps frozen instance shares and does not relabel legacy fixed quotas', () => {
    const instance = { gpus: 2, node_gpu_count: 4 } as Container
    expect(instanceShareText(instance)).toBe('可分配额度的 50%')
    expect(instanceShareText({ ...instance, node_gpu_count: null, cpu_cores: 4 })).toBe('原订单固定配额')
    expect(instanceShareText({ ...instance, node_gpu_count: null })).toBe('旧订单未设置配额')
  })
})
