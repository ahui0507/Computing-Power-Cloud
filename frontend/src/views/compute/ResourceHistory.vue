<template>
  <PageHeader
    title="历史订单"
    eyebrow="ORDER HISTORY"
    :description="auth.isAdmin ? '全部用户的历史订单，可翻页查看完整记录。' : '仅展示你本人最近 10 条已结束的订单。'"
    ><el-button @click="refresh">刷新</el-button
    ><el-button type="primary" @click="router.push('/compute/instances')"
      >我的实例</el-button
    ></PageHeader
  ><InstanceList historical />
</template>
<script setup lang="ts">
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { useResourceStore } from '@/stores/resource'
import { useAutoRefresh } from '@/composables/useAutoRefresh'
import PageHeader from '@/components/PageHeader.vue'
import InstanceList from '@/components/InstanceList.vue'
const router = useRouter(),
  auth = useAuthStore(),
  store = useResourceStore()
const refresh = useAutoRefresh(async () => {
  await store.fetchHistory()
})
</script>
