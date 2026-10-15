<template>
  <el-dialog
    :model-value="modelValue"
    title="保存个人镜像"
    width="540px"
    :close-on-click-modal="false"
    :show-close="!saving"
    :close-on-press-escape="!saving"
    @update:model-value="$emit('update:modelValue', $event)"
  >
    <el-alert
      title="保存已安装的软件和系统盘文件。保存期间实例会临时暂停，请先保存正在编辑的文件。"
      type="info"
      :closable="false"
    />
    <p class="caption section-gap">来源实例：{{ containerId }}</p>
    <el-form label-position="top" class="section-gap">
      <el-form-item label="镜像名称"
        ><el-input
          v-model="name"
          placeholder="例如 pytorch-project"
          :disabled="saving || !!pending"
          maxlength="64"
      /></el-form-item>
      <el-form-item label="版本标签"
        ><el-input
          v-model="tag"
          placeholder="例如 v1"
          :disabled="saving || !!pending"
          maxlength="64"
      /></el-form-item>
      <el-form-item label="说明"
        ><el-input
          v-model="desc"
          type="textarea"
          maxlength="500"
          :disabled="saving || !!pending"
      /></el-form-item>
    </el-form>
    <p class="caption">
      镜像保存实例系统盘及系统盘内的工作文件；挂载的个人存储独立保留。镜像不保存运行中的进程或内存状态，请等待保存完成后再释放实例。
    </p>
    <template #footer
      ><el-button :disabled="saving" @click="$emit('update:modelValue', false)"
        >关闭</el-button
      ><el-button
        type="primary"
        :loading="saving"
        :disabled="!valid"
        @click="save"
        >{{ pending ? '核对并重试保存任务' : '开始保存' }}</el-button
      ></template
    >
  </el-dialog>
</template>
<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { imageApi } from '@/api/images'
import { reportError } from '@/utils/feedback'
import { ApiError } from '@/utils/request'
const props = defineProps<{ modelValue: boolean; containerId: string }>()
const emit = defineEmits<{ 'update:modelValue': [value: boolean] }>()
const router = useRouter()
const name = ref(''),
  tag = ref('v1'),
  desc = ref(''),
  saving = ref(false)
type Draft = {
  container_id: string
  request_id: string
  name: string
  tag: string
  desc: string
}
const pending = ref<Draft>()
const key = computed(() => `image-save:${props.containerId}`)
const valid = computed(
  () =>
    !!pending.value ||
    (/^[a-z0-9][a-z0-9._-]{0,63}$/.test(name.value) &&
      /^[A-Za-z0-9_][A-Za-z0-9_.-]{0,63}$/.test(tag.value)),
)
watch(
  () => [props.modelValue, props.containerId],
  () => {
    if (!props.modelValue) return
    pending.value = undefined
    try {
      pending.value =
        JSON.parse(sessionStorage.getItem(key.value) || 'null') || undefined
    } catch {
      sessionStorage.removeItem(key.value)
    }
    name.value = pending.value?.name || ''
    tag.value = pending.value?.tag || 'v1'
    desc.value = pending.value?.desc || ''
  },
)
async function save() {
  if (saving.value || !valid.value) return
  saving.value = true
  try {
    if (!pending.value) {
      pending.value = {
        container_id: props.containerId,
        name: name.value,
        tag: tag.value,
        desc: desc.value,
        request_id: Array.from(
          crypto.getRandomValues(new Uint8Array(16)),
          (value) => value.toString(16).padStart(2, '0'),
        ).join(''),
      }
      sessionStorage.setItem(key.value, JSON.stringify(pending.value))
    }
    await imageApi.saveImage(pending.value)
    sessionStorage.removeItem(key.value)
    pending.value = undefined
    ElMessage.success('镜像保存任务已提交，请等待保存完成')
    emit('update:modelValue', false)
    void router.push({ path: '/images', query: { tab: 'my' } })
  } catch (error) {
    if (
      error instanceof ApiError &&
      [400, 401, 403, 404, 409, 422].includes(error.code)
    ) {
      sessionStorage.removeItem(key.value)
      pending.value = undefined
    }
    reportError(error)
  } finally {
    saving.value = false
  }
}
</script>
