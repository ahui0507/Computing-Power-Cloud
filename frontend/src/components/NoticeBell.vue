<template>
  <el-badge
    :value="store.list.unread_count"
    :hidden="!store.list.unread_count"
    :max="99"
  >
    <el-button
      text
      circle
      aria-label="站内提醒"
      :title="store.error ? '提醒暂不可查询' : '站内提醒'"
      @click="router.push('/notices')"
    >
      <el-icon :size="20"><Bell /></el-icon>
    </el-button>
  </el-badge>
</template>
<script setup lang="ts">
import { useRouter } from 'vue-router'
import { useNoticesStore } from '@/stores/notices'
import { useAutoRefresh } from '@/composables/useAutoRefresh'
const router = useRouter()
const store = useNoticesStore()
useAutoRefresh(store.refresh, 60000)
</script>
