<template>
  <PageHeader
    title="账户设置"
    eyebrow="ACCOUNT"
    description="管理登录密码和账户公钥，让你的工作空间保持有序。"
  />
  <div class="two-columns">
    <section class="panel">
      <h2 class="panel-title">账户信息</h2>
      <div class="detail-grid">
        <div class="detail-item">
          <label>账户邮箱</label>
          <div>{{ auth.userInfo?.email }}</div>
        </div>
        <div class="detail-item">
          <label>用户编号</label>
          <div class="mono">#{{ auth.userInfo?.user_id }}</div>
        </div>
        <div class="detail-item">
          <label>账户角色</label>
          <div>
            <el-tag>{{
              auth.isAdmin ? '管理员' : auth.isAuditor ? '审计员' : '普通用户'
            }}</el-tag>
          </div>
        </div>
        <div class="detail-item">
          <label>当前余额</label>
          <div class="mono">
            ¥{{ auth.userInfo?.balance.toFixed(4) }}
            <el-button link type="primary" @click="router.push('/billing')"
              >费用中心</el-button
            >
          </div>
        </div>
      </div>
      <div class="hint-box section-gap">
        当前实例通过 JupyterLab 和浏览器终端连接，无需配置
        SSH。下方公钥可保存在账户中供支持 SSH 的环境使用。
      </div>
    </section>
    <section class="panel">
      <h2 class="panel-title">修改登录密码</h2>
      <p class="caption">
        初始登录凭据由管理员交付。修改后，下次登录使用新密码。
      </p>
      <el-form
        ref="passwordRef"
        :model="password"
        :rules="rules"
        label-position="top"
        @submit.prevent="changePassword"
        ><el-form-item label="当前密码" prop="old"
          ><el-input
            v-model="password.old"
            type="password"
            show-password
            autocomplete="current-password" /></el-form-item
        ><el-form-item label="新密码" prop="next"
          ><el-input
            v-model="password.next"
            type="password"
            show-password
            autocomplete="new-password"
            placeholder="至少8位，包含字母和数字" /></el-form-item
        ><el-form-item label="确认新密码" prop="confirm"
          ><el-input
            v-model="password.confirm"
            type="password"
            show-password
            autocomplete="new-password" /></el-form-item
        ><el-button type="primary" :loading="changing" native-type="submit"
          >保存新密码</el-button
        ></el-form
      >
    </section>
  </div>
  <section class="panel section-gap">
    <div class="panel-heading">
      <h2 class="panel-title">账户公钥</h2>
      <el-button type="primary" @click="keyOpen = true"
        ><el-icon><Plus /></el-icon>添加公钥</el-button
      >
    </div>
    <AsyncState
      :loading="keys.loading.value"
      :error="keys.error.value"
      :empty="keys.data.value.length === 0"
      empty-text="尚未保存公钥，使用当前浏览器终端无需配置"
      @retry="keys.refresh"
      ><el-table :data="keys.data.value"
        ><el-table-column
          prop="name"
          label="公钥名称"
          min-width="160"
        /><el-table-column label="指纹" min-width="270"
          ><template #default="{ row }"
            ><span class="mono">{{ row.fingerprint }}</span></template
          ></el-table-column
        ><el-table-column label="创建时间" width="170"
          ><template #default="{ row }">{{
            formatTime(row.created_at)
          }}</template></el-table-column
        ><el-table-column label="操作" width="85"
          ><template #default="{ row }"
            ><el-button link type="danger" @click="deleteKey(row)"
              >删除</el-button
            ></template
          ></el-table-column
        ></el-table
      ></AsyncState
    >
  </section>
  <el-dialog v-model="keyOpen" title="添加账户公钥" width="560px"
    ><el-form label-position="top"
      ><el-form-item label="公钥名称"
        ><el-input
          v-model="key.name"
          placeholder="例如 我的笔记本"
          maxlength="128" /></el-form-item
      ><el-form-item label="OpenSSH 公钥"
        ><el-input
          v-model="key.public_key"
          type="textarea"
          :rows="5"
          placeholder="ssh-ed25519 AAAA... 或 ssh-rsa AAAA..."
      /></el-form-item>
      <p class="caption">请粘贴 .pub 公钥文件内容，请勿上传私钥。</p></el-form
    ><template #footer
      ><el-button @click="keyOpen = false">取消</el-button
      ><el-button type="primary" :loading="savingKey" @click="addKey"
        >保存公钥</el-button
      ></template
    ></el-dialog
  >
</template>
<script setup lang="ts">
import { ref, reactive, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import {
  ElMessage,
  ElMessageBox,
  type FormInstance,
  type FormRules,
} from 'element-plus'
import { useAuthStore } from '@/stores/auth'
import { consoleApi, type SSHKey } from '@/api/console'
import { useRemoteData } from '@/composables/useRemoteData'
import { validatePassword } from '@/utils/validation'
import { formatTime } from '@/utils/format'
import { reportError } from '@/utils/feedback'
import PageHeader from '@/components/PageHeader.vue'
import AsyncState from '@/components/AsyncState.vue'
const auth = useAuthStore(),
  router = useRouter(),
  passwordRef = ref<FormInstance>(),
  changing = ref(false),
  keyOpen = ref(false),
  savingKey = ref(false)
const password = reactive({ old: '', next: '', confirm: '' }),
  key = reactive({ name: '', public_key: '' })
const keys = useRemoteData<SSHKey[]>(
  async () => (await consoleApi.keys()).data || [],
  [],
)
const rules: FormRules = {
  old: [{ required: true, message: '请输入当前密码', trigger: 'blur' }],
  next: [
    {
      validator: (_rule, value, done) => {
        const result = validatePassword(value)
        done(result.valid ? undefined : new Error(result.message))
      },
      trigger: 'blur',
    },
  ],
  confirm: [
    {
      validator: (_rule, value, done) =>
        done(
          value && value === password.next
            ? undefined
            : new Error('两次新密码不一致'),
        ),
      trigger: 'blur',
    },
  ],
}
onMounted(() => {
  void keys.refresh()
  void auth.fetchUserInfo().catch(() => {})
})
async function changePassword() {
  if (changing.value || !passwordRef.value) return
  changing.value = true
  try {
    if (!(await passwordRef.value.validate().catch(() => false))) return
    await consoleApi.password(password.old, password.next)
    passwordRef.value.resetFields()
    ElMessage.success('密码已修改，下次登录请使用新密码')
  } catch (error) {
    reportError(error)
  } finally {
    changing.value = false
  }
}
async function addKey() {
  if (savingKey.value) return
  if (!key.name.trim() || !key.public_key.trim())
    return ElMessage.warning('请填写公钥名称和内容')
  savingKey.value = true
  try {
    await consoleApi.addKey(key.name, key.public_key)
    keyOpen.value = false
    key.name = ''
    key.public_key = ''
    await keys.refresh()
    ElMessage.success('公钥已保存')
  } catch (error) {
    reportError(error)
  } finally {
    savingKey.value = false
  }
}
async function deleteKey(row: SSHKey) {
  try {
    await ElMessageBox.confirm(`删除公钥“${row.name}”？`, '删除公钥', {
      confirmButtonText: '删除',
      cancelButtonText: '取消',
    })
    await consoleApi.deleteKey(row.id)
    await keys.refresh()
    ElMessage.success('公钥已删除')
  } catch (error) {
    reportError(error)
  }
}
</script>
