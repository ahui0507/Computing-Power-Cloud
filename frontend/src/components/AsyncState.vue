<template>
  <div v-if="error" class="request-error" role="alert">
    <el-icon><Warning /></el-icon><span>{{ error }}</span
    ><el-button link type="primary" @click="$emit('retry')">重新加载</el-button>
  </div>
  <el-skeleton
    v-else-if="loading && empty"
    :rows="5"
    animated
    class="panel skeleton-panel"
  />
  <el-empty
    v-else-if="empty"
    :description="emptyText || '暂无记录'"
    :image-size="90"
    ><slot name="empty"
  /></el-empty>
  <slot v-else />
</template>
<script setup lang="ts">
defineProps<{
  loading?: boolean
  error?: string
  empty?: boolean
  emptyText?: string
}>()
defineEmits<{ retry: [] }>()
</script>
