<template>
  <el-tag :type="tagType" size="small">
    {{ statusText }}
  </el-tag>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { getStatusColor, getStatusText } from '@/utils/format'

const props = defineProps<{
  status: string
}>()

const tagType = computed(() => getStatusColor(props.status))
const statusText = computed(() => getStatusText(props.status))
</script>

<style scoped>
</style>

