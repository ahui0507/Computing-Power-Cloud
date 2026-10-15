<template>
  <section class="panel capacity-panel">
    <div class="panel-heading">
      <h3 class="panel-title">个人存储</h3>
      <el-button link @click="remote.refresh">刷新额度</el-button>
    </div>
    <p v-if="remote.error.value" class="caption">
      额度暂不可查询，请稍后重试。
    </p>
    <template v-else-if="remote.data.value">
      <template v-if="remote.data.value.enforcement === 'filesystem'">
        <el-progress
          :percentage="
            Math.min(
              100,
              Number((remote.data.value.used_percent || 0).toFixed(1)),
            )
          "
          :status="
            remote.data.value.warning === 'full'
              ? 'exception'
              : remote.data.value.warning === 'low'
                ? 'warning'
                : undefined
          "
        />
        <p class="caption">
          <template v-if="remote.data.value.quota_mode === 'fixed'">
            已使用 {{ ((remote.data.value.used_bytes || 0) / 1024 ** 3).toFixed(2) }} GiB，
            固定上限 {{ ((remote.data.value.limit_bytes || 0) / 1024 ** 3).toFixed(0) }} GiB。
          </template>
          <template v-else>个人额度为用户存储池的 {{ remote.data.value.share_percent }}%。</template>
          文件和个人镜像共用额度。
        </p>
        <el-alert
          v-if="remote.data.value.warning !== 'none'"
          :title="
            remote.data.value.warning === 'full'
              ? '存储额度已满，请清理文件、镜像或联系管理员调整额度。'
              : '存储额度已接近上限，请及时清理。'
          "
          type="warning"
          :closable="false"
        />
      </template>
      <p v-else class="caption">此环境尚未启用存储配额。</p>
    </template>
  </section>
</template>
<script setup lang="ts">
import { storageApi, type StorageUsage } from '@/api/storage'
import { useRemoteData } from '@/composables/useRemoteData'
import { useAutoRefresh } from '@/composables/useAutoRefresh'
const remote = useRemoteData<StorageUsage | null>(
  async () => (await storageApi.usage()).data || null,
  null,
)
useAutoRefresh(remote.refresh, 30000)
</script>
<style scoped>
.capacity-panel {
  margin-bottom: 22px;
}
</style>
