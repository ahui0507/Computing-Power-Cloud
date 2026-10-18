<template>
  <el-dialog v-model="open" title="定时释放" width="460px">
    <p>到时将终止实例内的所有程序，个人存储文件保留。包时订单提前释放不退费。</p>
    <p v-if="instance?.scheduled_release_at">当前计划：{{ formatTime(instance.scheduled_release_at) }}</p>
    <p v-else-if="instance?.release_after_hours">实例首次就绪后 {{ instance.release_after_hours }} 小时自动释放。</p>
    <el-date-picker v-model="date" type="datetime" placeholder="选择释放时间（本地时区）" style="width:100%; margin:16px 0" />
    <p class="caption">可设置1分钟后至30天内的时间。到期前60分钟及10分钟提醒；后台恢复后按原截止时间结算。</p>
    <template #footer>
      <el-button :loading="saving" @click="save(null)">取消定时释放</el-button>
      <el-button type="primary" :loading="saving" :disabled="!date" @click="save(date)">保存计划</el-button>
    </template>
  </el-dialog>
</template>
<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import type { Container } from '@/types'
import { resourceApi } from '@/api/resource'
import { useResourceStore } from '@/stores/resource'
import { formatTime } from '@/utils/format'
import { reportError } from '@/utils/feedback'
const props = defineProps<{ modelValue: boolean; instance?: Container }>()
const emit = defineEmits<{ 'update:modelValue': [boolean] }>()
const open = computed({ get: () => props.modelValue, set: v => emit('update:modelValue', v) })
const date = ref<Date | null>(null), saving = ref(false)
watch(() => props.modelValue, value => { if (value) date.value = props.instance?.scheduled_release_at ? new Date(props.instance.scheduled_release_at) : null })
async function save(value: Date | null) {
  if (!props.instance || saving.value) return
  if (value && (value.getTime() < Date.now() + 60000 || value.getTime() > Date.now() + 30 * 86400000)) return ElMessage.warning('请选择1分钟后至30天内的时间')
  saving.value = true
  try {
    await resourceApi.schedule(props.instance.container_id, value?.toISOString() || null)
    ElMessage.success(value ? '定时释放已设置' : '定时释放已取消')
    open.value = false
    await useResourceStore().fetchMyResources()
  } catch (error) { reportError(error) } finally { saving.value = false }
}
</script>
