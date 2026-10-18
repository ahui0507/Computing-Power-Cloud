<template>
  <PageHeader
    title="存储与运行保障"
    eyebrow="OPERATIONS"
    description="查看数据卷和独立故障监测状态。"
    ><el-button @click="remote.refresh">刷新</el-button></PageHeader
  >
  <AsyncState
    :loading="remote.loading.value"
    :error="remote.error.value"
    :empty="!remote.data.value"
    @retry="remote.refresh"
  >
    <template v-if="remote.data.value">
      <section class="panel">
        <h3 class="panel-title">控制节点数据卷</h3>
        <p>
          状态：{{
            storageText[remote.data.value.storage.enforcement] || '未知'
          }}
        </p>
        <p v-if="remote.data.value.storage.volume" class="caption">数据卷已用空间占比</p>
        <el-progress
          v-if="remote.data.value.storage.volume"
          :percentage="
            Number(remote.data.value.storage.volume.used_percent.toFixed(1))
          "
        />
        <p class="caption">
          百分比表示整个数据卷的磁盘使用率，包含原有数据、个人文件及镜像归档。每用户存储额度单独计算；系统空间单独预留。计算节点提供
          CPU、内存、GPU 和临时运行环境。
        </p>
      </section>
      <section v-if="remote.data.value.backup.alerts_enabled !== false" class="panel section-gap">
        <h3 class="panel-title">定时备份</h3>
        <p>状态：{{ backupText[remote.data.value.backup.state] || '未知' }}</p>
        <p>
          最近成功：{{
            remote.data.value.backup.last_success_at
              ? formatTime(remote.data.value.backup.last_success_at)
              : '—'
          }}
        </p>
        <p>
          最近恢复验证：{{
            remote.data.value.backup.recovery_verified_at
              ? formatTime(remote.data.value.backup.recovery_verified_at)
              : '—'
          }}
        </p>
        <p>有效备份：{{ remote.data.value.backup.retained ?? '—' }} 份</p>
        <el-alert
          v-if="remote.data.value.backup.message"
          :title="remote.data.value.backup.message"
          :closable="false"
          :type="remote.data.value.backup.state === 'failed' ? 'error' : 'info'"
        />
        <p class="caption">
          每天保存数据库、个人文件和镜像归档到计算节点数据卷。备份保存磁盘数据；训练中的模型需主动写入
          /data 才能恢复。
        </p>
      </section>
      <section class="panel section-gap"><h3 class="panel-title">独立故障监测</h3><p>监测结果独立于业务接口保存。管理员收到故障弹窗后可手动关闭，同一次故障不会重复弹出。</p><a href="/ops-alerts/" target="_blank" rel="noopener noreferrer">查看独立监测记录</a></section>
    </template>
  </AsyncState>
</template>
<script setup lang="ts">
import request from '@/utils/request'
import type { ApiResponse } from '@/types'
import { useRemoteData } from '@/composables/useRemoteData'
import { useAutoRefresh } from '@/composables/useAutoRefresh'
import { formatTime } from '@/utils/format'
import PageHeader from '@/components/PageHeader.vue'
import AsyncState from '@/components/AsyncState.vue'
interface Status {
  storage: { enforcement: string; volume?: { used_percent: number } }
  backup: {
    alerts_enabled?: boolean
    state: string
    last_success_at?: string | null
    recovery_verified_at?: string | null
    retained?: number
    message?: string
  }
}
const remote = useRemoteData<Status | null>(
  async () =>
    (await request.get<ApiResponse<Status>>('/admin/maintenance')).data || null,
  null,
)
const storageText: Record<string, string> = {
  filesystem: '数据卷与配额正常',
  disabled: '未启用',
  unavailable: '暂不可查询',
}
const backupText: Record<string, string> = {
  ready: '最近备份成功',
  running: '正在备份',
  failed: '备份失败',
  deferred: '等待镜像任务结束后重试',
  not_configured: '尚未配置',
}
useAutoRefresh(remote.refresh, 60000)
</script>
