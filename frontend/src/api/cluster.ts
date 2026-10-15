import request from '@/utils/request'
import type { Node, ClusterMetrics, ApiResponse } from '@/types'

export const clusterApi = {
  // 获取所有节点
  getNodes: (): Promise<ApiResponse<Node[]>> => {
    return request.get('/cluster/nodes')
  },

  // 获取节点详情
  getNodeDetail: (nodeId: number): Promise<ApiResponse<Node>> => {
    return request.get(`/cluster/node/${nodeId}`)
  },

  // 获取集群监控数据
  getMetrics: (): Promise<ApiResponse<ClusterMetrics>> => {
    return request.get('/cluster/metrics')
  },
}
