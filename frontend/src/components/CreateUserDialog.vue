<template>
  <el-dialog
    :model-value="modelValue"
    title="创建账号"
    width="500px"
    :close-on-click-modal="false"
    :before-close="close"
    @closed="email = ''"
  >
    <p class="caption">
      创建普通用户账号，初始余额为 0。创建后可增加余额或设置角色。
    </p>
    <el-alert
      title="初始密码请查阅管理员提供的凭据记录"
      description="用户登录后可在「账户设置」修改密码。账号开通无需邮箱验证码。"
      type="info"
      :closable="false"
      class="section-gap"
    />
    <el-form
      ref="formRef"
      :model="form"
      label-position="top"
      class="section-gap"
      @submit.prevent="create"
    >
      <el-form-item label="登录邮箱" prop="email" :rules="rules">
        <el-input
          v-model="email"
          placeholder="输入用户邮箱"
          autocomplete="off"
          :maxlength="128"
          :disabled="saving"
        />
      </el-form-item>
    </el-form>
    <template #footer
      ><el-button :disabled="saving" @click="close">取消</el-button
      ><el-button type="primary" :loading="saving" @click="create"
        >创建账号</el-button
      ></template
    >
  </el-dialog>
</template>
<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { ElMessage, type FormInstance, type FormItemRule } from 'element-plus'
import { adminApi } from '@/api/admin'
import type { User } from '@/types'
import { reportError } from '@/utils/feedback'
const props = defineProps<{ modelValue: boolean }>()
const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  created: [user: User]
}>()
const email = ref(''),
  saving = ref(false),
  formRef = ref<FormInstance>()
const form = computed(() => ({ email: email.value.trim() }))
const rules: FormItemRule[] = [
  {
    required: true,
    type: 'email',
    message: '请输入有效的登录邮箱',
    trigger: 'blur',
  },
]
watch(
  () => props.modelValue,
  (open) => {
    if (open) formRef.value?.clearValidate()
  },
)
function close() {
  if (!saving.value) emit('update:modelValue', false)
}
async function create() {
  if (saving.value || !formRef.value) return
  saving.value = true
  try {
    if (!(await formRef.value.validate().catch(() => false))) return
    const result = await adminApi.createUser(email.value.trim())
    if (result.data) {
      emit('update:modelValue', false)
      emit('created', result.data)
      ElMessage.success('账号已创建，请通过约定方式交付初始凭据')
    }
  } catch (error) {
    reportError(error)
  } finally {
    saving.value = false
  }
}
</script>
