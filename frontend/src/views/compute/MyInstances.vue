<template>
  <PageHeader
    class="compute-page-heading"
    title="我的实例"
    eyebrow="WORKSPACE"
    description="集中管理你的算力，连接开发环境，查看运行状态。"
    ><el-button @click="router.push('/compute/history')">历史订单</el-button
    ><el-button type="primary" @click="router.push('/compute/pools')"
      ><el-icon><Plus /></el-icon>创建实例</el-button
    ></PageHeader
  >
  <div class="metrics-grid">
    <div class="metric">
      <p class="metric-label">运行中</p>
      <p class="metric-value">
        {{ running }}<span class="metric-unit">个实例</span>
      </p>
      <span class="metric-icon"
        ><el-icon><VideoPlay /></el-icon
      ></span>
    </div>
    <div class="metric">
      <p class="metric-label">创建中</p>
      <p class="metric-value">
        {{ pending }}<span class="metric-unit">个实例</span>
      </p>
      <span class="metric-icon"
        ><el-icon><Loading /></el-icon
      ></span>
    </div>
    <div class="metric">
      <p class="metric-label">使用的 GPU</p>
      <p class="metric-value">{{ gpus }}<span class="metric-unit">张</span></p>
      <span class="metric-icon"
        ><el-icon><Cpu /></el-icon
      ></span>
    </div>
    <div class="metric">
      <p class="metric-label">按时实例小时费用</p>
      <p class="metric-value">¥{{ rate.toFixed(2) }}</p>
      <p class="metric-sub">包日、包周已预付，不计入此项</p>
    </div>
  </div>
  <InstanceList />
</template>
<script setup lang="ts">
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import { useResourceStore } from '@/stores/resource'
import { useAuthStore } from '@/stores/auth'
import { useBillingStore } from '@/stores/billing'
import { useAutoRefresh } from '@/composables/useAutoRefresh'
import PageHeader from '@/components/PageHeader.vue'
import InstanceList from '@/components/InstanceList.vue'
import { instanceRate } from '@/utils/instance'
const store = useResourceStore(),
  auth = useAuthStore(),
  billing = useBillingStore(),
  router = useRouter()
const running = computed(
  () =>
    store.activeInstances.filter((item) => item.status === 'running').length,
)
const pending = computed(
  () =>
    store.activeInstances.filter((item) => item.status === 'pending').length,
)
const gpus = computed(() =>
  store.activeInstances.reduce((sum, item) => sum + item.gpus, 0),
)
const rate = computed(() =>
  store.activeInstances
    .filter((item) => item.status === 'running')
    .reduce((sum, item) => sum + (instanceRate(item) || 0), 0),
)
useAutoRefresh(async () => {
  await Promise.allSettled([
    store.fetchMyResources(),
    auth.fetchUserInfo(),
    billing.fetchRecords(),
  ])
}, 10000)
</script>
