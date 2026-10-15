import type { ResourcePool, Container } from '@/types'

export function maximumCards(pool: ResourcePool | undefined, userRemaining: number) {
  if (!pool) return 0
  return Math.max(0, Math.min(pool.free_gpus, pool.max_gpus_per_instance ?? pool.free_gpus, userRemaining))
}

export function shareText(cards: number, total: number | null | undefined) {
  if (!total || cards < 1 || cards > total) return '按实际节点 GPU 占比'
  return `可分配额度的 ${Number((cards / total * 100).toFixed(2))}%`
}

export function instanceShareText(instance: Container) {
  if (instance.node_gpu_count) return shareText(instance.gpus, instance.node_gpu_count)
  return instance.cpu_cores != null || instance.ram_mb != null ? '原订单固定配额' : '旧订单未设置配额'
}
