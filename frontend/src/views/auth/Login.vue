<template>
  <AuthLayout
    ><p class="eyebrow">WELCOME BACK</p>
    <h1>欢迎回到算力云</h1>
    <p class="auth-subtitle">登录工作空间，继续你的探索。</p>
    <el-form
      ref="formRef"
      :model="form"
      :rules="rules"
      label-position="top"
      @submit.prevent="submit"
      ><el-form-item label="邮箱" prop="email"
        ><el-input
          v-model="form.email"
          placeholder="输入账户邮箱"
          size="large"
          autocomplete="username" /></el-form-item
      ><el-form-item label="密码" prop="password"
        ><el-input
          v-model="form.password"
          type="password"
          show-password
          placeholder="输入密码"
          size="large"
          autocomplete="current-password"
          @keyup.enter="submit" /></el-form-item
      ><el-button type="primary" :loading="busy" native-type="submit"
        >登录工作空间<el-icon><ArrowRight /></el-icon></el-button
    ></el-form>
    <div class="auth-switch">
      <span>账号由管理员统一创建，请联系管理员开通。</span>
    </div>
    <p class="auth-note">
      新账号初始密码为 password，可在「账户设置」修改登录密码。
    </p>
    <p class="auth-note">
      实例、文件与费用统一管理。请将需要保留的文件保存到
      /data，使用结束后及时释放实例。
    </p></AuthLayout
  >
</template>
<script setup lang="ts">
import { reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, type FormInstance, type FormRules } from 'element-plus'
import { useAuthStore } from '@/stores/auth'
import { reportError } from '@/utils/feedback'
import AuthLayout from '@/components/AuthLayout.vue'
const auth = useAuthStore(),
  router = useRouter(),
  route = useRoute()
const form = reactive({ email: '', password: '' }),
  formRef = ref<FormInstance>(),
  busy = ref(false)
const rules: FormRules = {
  email: [
    {
      required: true,
      type: 'email',
      message: '请输入正确的邮箱',
      trigger: 'blur',
    },
  ],
  password: [{ required: true, message: '请输入密码', trigger: 'blur' }],
}
async function submit() {
  if (busy.value || !formRef.value) return
  busy.value = true
  try {
    if (!(await formRef.value.validate().catch(() => false))) return
    if (await auth.login(form.email.trim(), form.password)) {
      ElMessage.success('登录成功')
      const redirect = String(route.query.redirect || '/dashboard')
      void router.replace(
        redirect.startsWith('/') &&
          !redirect.startsWith('//') &&
          !redirect.startsWith('/login')
          ? redirect
          : '/dashboard',
      )
    }
  } catch (error) {
    reportError(error)
  } finally {
    busy.value = false
  }
}
</script>
