<template>
  <section class="section-gap">
    <div class="panel-heading">
      <h3 class="panel-title">环境自检</h3>
      <el-button :loading="busy" @click="run">开始检查</el-button>
    </div>
    <p class="caption">检查 Python、GPU 运算、常用工具及软件源联网情况。</p>
    <el-alert v-if="error" :title="error" type="error" :closable="false" />
    <div v-for="(check, index) in checks" :key="index" class="check-row">
      <div>
        <el-tag :type="check.ok ? 'success' : 'warning'" size="small">{{
          check.ok ? '通过' : '需处理'
        }}</el-tag>
        <strong>{{ check.name }}</strong>
      </div>
      <p>{{ check.detail }}</p>
      <p v-if="check.advice" class="caption">{{ check.advice }}</p>
    </div>
  </section>
</template>
<script setup lang="ts">
import { ref } from 'vue'
import request from '@/utils/request'
import type { ApiResponse } from '@/types'
const props = defineProps<{ containerId: string }>()
interface Check {
  name: string
  ok: boolean
  detail: string
  advice: string
}
const busy = ref(false),
  error = ref(''),
  checks = ref<Check[]>([])
async function run() {
  if (busy.value) return
  busy.value = true
  error.value = ''
  checks.value = []
  try {
    const response = await request.post<ApiResponse<{ checks: Check[] }>>(
      `/resource/${props.containerId}/diagnostics`,
      undefined,
      { timeout: 45000, silentError: true },
    )
    checks.value = response.data?.checks || []
  } catch (reason) {
    error.value =
      reason instanceof Error ? reason.message : '检查未完成，请重试'
  } finally {
    busy.value = false
  }
}
</script>
<style scoped>
.check-row {
  padding: 12px 0;
  border-bottom: 1px solid #edf1f6;
}
.check-row p {
  overflow-wrap: anywhere;
}
</style>
