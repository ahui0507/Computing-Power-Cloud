<template>
  <el-dialog :model-value="modelValue" title="检查并释放实例" width="min(760px, 95vw)" top="5vh"
    :close-on-click-modal="false" :close-on-press-escape="!submitting" :before-close="close">
    <div v-loading="loading" class="inspection-content">
      <p>释放 {{ instance ? instanceName(instance) : '' }} 会终止实例内的所有程序。</p>
      <el-alert v-if="error" :title="error" type="error" :closable="false" />
      <template v-if="check">
        <el-alert v-if="check.saving_image" title="个人镜像正在保存，完成后才能释放。" type="warning" :closable="false" />
        <el-alert v-if="!check.checks_complete" title="部分检查未完成，可能存在未列出的运行任务。请重试，或明确确认仍要终止所有程序。" type="warning" :closable="false" />
        <p class="caption">平台任务：{{ check.jobs_checked ? '已检查' : '未能确认' }} · 进程：{{ check.processes_checked ? '已检查' : '未能确认' }} · Notebook：{{ check.notebooks_checked ? '已检查' : '未能确认' }} · tmux：{{ check.tmux_checked ? '已检查默认会话' : '未能确认' }}</p>
        <h4>平台登记任务（{{ check.active_jobs.length }}）</h4>
        <p>{{ check.active_jobs.map(job => job.name).join('、') || (check.jobs_checked ? '未发现运行任务' : '状态未知') }}</p>
        <h4>实例内进程（{{ check.processes?.length || 0 }}）</h4>
        <el-table v-if="check.processes?.length" :data="check.processes" max-height="220" size="small">
          <el-table-column prop="pid" label="PID" width="80" />
          <el-table-column prop="name" label="程序" min-width="200" />
          <el-table-column label="类型" width="100"><template #default="{ row }">{{ categories[row.category as keyof typeof categories] }}</template></el-table-column>
          <el-table-column label="已运行" width="100"><template #default="{ row }">{{ Math.floor(row.elapsed_seconds / 60) }} 分钟</template></el-table-column>
        </el-table>
        <p v-else>{{ check.processes_checked ? '未发现需要保留的用户进程' : '进程状态未知' }}</p>
        <h4>Notebook 内核（{{ check.notebooks?.length || 0 }}）</h4>
        <ul v-if="check.notebooks?.length"><li v-for="kernel in check.notebooks" :key="kernel.id">{{ kernel.name }} · {{ kernel.state === 'busy' ? '执行中' : kernel.state === 'idle' ? '空闲，仍可能保留内存变量' : '状态待确认' }}</li></ul>
        <p v-else>{{ check.notebooks_checked ? '未发现 Notebook 内核' : '内核状态未知' }}</p>
        <h4>tmux 会话（{{ check.tmux_sessions?.length || 0 }}）</h4>
        <ul v-if="check.tmux_sessions?.length"><li v-for="session in check.tmux_sessions" :key="session.name">{{ session.name }} · {{ session.windows }} 个窗口</li></ul>
        <p v-else>{{ check.tmux_checked ? '未发现默认 tmux 会话；其他会话以进程列表为准' : '会话状态未知' }}</p>
        <p class="caption">请将成果保存到 {{ check.persistent_path }}，或完成个人镜像保存。{{ instance && isPackage(instance) ? '包时订单提前释放不退费。' : '释放时按实际使用时间结算。' }}定时释放和欠费回收仍按既定规则执行。</p>
        <el-checkbox v-model="acknowledged" class="release-confirmation" :disabled="submitting || loading || check.saving_image">{{ check.checks_complete ? '我已保存需要保留的成果，确认终止上述程序并释放实例' : '我了解部分状态未知，已保存成果，仍确认终止所有程序并释放实例' }}</el-checkbox>
      </template>
    </div>
    <template #footer>
      <el-button :disabled="submitting || loading" @click="refresh">重新检查</el-button>
      <el-button :disabled="submitting" @click="close()">继续使用</el-button>
      <el-button type="danger" :loading="submitting" :disabled="loading || !check || !acknowledged || check.saving_image" @click="submit">终止程序并释放</el-button>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import { ref, watch, onBeforeUnmount } from 'vue'
import { ElMessage } from 'element-plus'
import type { Container } from '@/types'
import { resourceApi, type ReleaseCheck } from '@/api/resource'
import { useResourceStore } from '@/stores/resource'
import { instanceName, isPackage } from '@/utils/instance'
import { sessionRevision, onSessionReset } from '@/utils/session'
import { reportError } from '@/utils/feedback'
const props = defineProps<{ modelValue: boolean; instance?: Container }>()
const emit = defineEmits<{ (event: 'update:modelValue', value: boolean): void; (event: 'released'): void }>()
const store = useResourceStore()
const check = ref<ReleaseCheck>(), loading = ref(false), submitting = ref(false), acknowledged = ref(false), error = ref('')
const categories = { program: '程序', notebook: 'Notebook', terminal: '终端会话' }
let generation = 0
function close(done?: () => void) {
  if (submitting.value) return
  generation++
  emit('update:modelValue', false)
  done?.()
}
async function refresh() {
  if (!props.instance) return
  const id = props.instance.container_id, version = ++generation, scope = sessionRevision()
  loading.value = true
  acknowledged.value = false
  check.value = undefined
  error.value = ''
  try {
    const result = await resourceApi.releaseCheck(id)
    if (version !== generation || scope !== sessionRevision()) return
    if (!result.data) throw new Error('未收到检查结果，请重新检查')
    check.value = result.data
  } catch (reason) {
    if (version === generation && scope === sessionRevision()) error.value = reason instanceof Error ? reason.message : '检查失败，请重试'
  } finally {
    if (version === generation) loading.value = false
  }
}
async function submit() {
  if (!props.instance || !check.value || !acknowledged.value || submitting.value || loading.value) return
  const scope = sessionRevision()
  submitting.value = true
  try {
    const result = await store.releaseResource(props.instance.container_id, {
      ...(check.value.confirmation_token ? { confirmation_token: check.value.confirmation_token } : {}),
      confirm_unchecked: !check.value.checks_complete,
    })
    if (scope !== sessionRevision()) return
    ElMessage.success(result === 'releasing' ? '已提交释放，完成后移入历史订单' : '实例已释放')
    emit('update:modelValue', false)
    emit('released')
  } catch (reason) {
    if (scope !== sessionRevision()) return
    if ((reason as { code?: number }).code === 409) {
      await refresh()
      error.value = '任务状态发生变化或原检查已过期，请重新核对列表后确认。'
    } else reportError(reason)
  } finally { submitting.value = false }
}
watch(() => [props.modelValue, props.instance?.container_id] as const, ([open]) => {
  if (open) void refresh()
  else { generation++; check.value = undefined; acknowledged.value = false; loading.value = false }
}, { immediate: true })
onSessionReset(() => { generation++; check.value = undefined; acknowledged.value = false; emit('update:modelValue', false) })
onBeforeUnmount(() => { generation++ })
</script>

<style scoped>
.inspection-content { max-height: 62vh; overflow-y: auto; padding-right: 8px; }
.release-confirmation { height: auto; margin-top: 12px; }
.release-confirmation :deep(.el-checkbox__label) { white-space: normal; line-height: 1.5; }
</style>
