<template>
  <PageHeader
    title="用户管理"
    eyebrow="ADMINISTRATION"
    description="管理平台账户、使用权限与余额。"
    ><el-button @click="remote.refresh">刷新用户</el-button>
    <el-button type="primary" @click="createOpen = true"
      ><el-icon><Plus /></el-icon>创建账号</el-button
    ></PageHeader
  >
  <section class="panel">
    <div class="toolbar">
      <el-input
        v-model="search"
        clearable
        placeholder="搜索邮箱或用户编号"
        aria-label="搜索用户"
      /><span class="caption">{{ filtered.length }} 个账户</span>
    </div>
    <AsyncState
      :loading="remote.loading.value"
      :error="remote.error.value"
      :empty="!filtered.length"
      empty-text="没有匹配的用户"
      @retry="remote.refresh"
      ><el-table :data="filtered"
        ><el-table-column
          prop="user_id"
          label="用户编号"
          width="100"
        /><el-table-column
          prop="email"
          label="邮箱"
          min-width="250"
        /><el-table-column label="角色" width="130"
          ><template #default="{ row }"
            ><el-tag :type="row.role === 'admin' ? 'warning' : 'info'">{{
              roleName(row.role)
            }}</el-tag></template
          ></el-table-column
        ><el-table-column label="余额" width="160"
          ><template #default="{ row }"
            ><span class="mono">¥{{ row.balance.toFixed(4) }}</span></template
          ></el-table-column
        ><el-table-column label="并发配额（已用 / 上限）" width="210"
          ><template #default="{ row }"
            ><span
              >{{ row.quota?.used_gpus ?? '—' }} /
              {{ row.quota?.max_gpus ?? '—' }} 张 GPU</span
            >
            <p class="table-secondary">
              {{ row.quota?.used_instances ?? '—' }} /
              {{ row.quota?.max_instances ?? '—' }} 个实例
            </p></template
          ></el-table-column
        ><el-table-column label="操作" width="310"
          ><template #default="{ row }"
            ><el-button
              v-if="row.role === 'user'"
              link
              type="primary"
              @click="editBalance(row)"
              >增加余额</el-button
            ><el-button link type="primary" @click="editQuota(row)"
              >配额与预警</el-button
            ><el-button link type="primary" @click="edit(row)"
              >设置角色</el-button
            ></template
          ></el-table-column
        ></el-table
      ></AsyncState
    >
  </section>
  <el-dialog v-model="open" title="设置用户角色" width="440px"
    ><p class="caption" style="margin-bottom: 24px">{{ selected?.email }}</p>
    <el-radio-group v-model="role"
      ><el-radio label="user">普通用户</el-radio
      ><el-radio label="admin">管理员</el-radio></el-radio-group
    ><el-alert
      v-if="selected?.user_id === auth.userInfo?.user_id"
      title="正在修改自己的角色，降为普通用户后将退出管理页面。"
      type="warning"
      :closable="false"
      class="section-gap"
    /><template #footer
      ><el-button @click="open = false">取消</el-button
      ><el-button type="primary" :loading="saving" @click="save"
        >保存角色</el-button
      ></template
    ></el-dialog
  >
  <QuotaDialog
    v-model="quotaOpen"
    :user="quotaUser"
    @updated="remote.refresh"
  />
  <CreateUserDialog v-model="createOpen" @created="userCreated" />
  <BalanceCreditDialog
    v-model="creditOpen"
    :user="creditUser"
    @updated="remote.refresh"
  />
</template>
<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { adminApi } from '@/api'
import { useAuthStore } from '@/stores/auth'
import { useRemoteData } from '@/composables/useRemoteData'
import { reportError } from '@/utils/feedback'
import type { User } from '@/types'
import PageHeader from '@/components/PageHeader.vue'
import AsyncState from '@/components/AsyncState.vue'
import QuotaDialog from '@/components/QuotaDialog.vue'
import BalanceCreditDialog from '@/components/BalanceCreditDialog.vue'
import CreateUserDialog from '@/components/CreateUserDialog.vue'
const createOpen = ref(false)
const creditOpen = ref(false),
  creditUser = ref<User>()
const quotaOpen = ref(false),
  quotaUser = ref<User>()
const auth = useAuthStore(),
  router = useRouter(),
  search = ref(''),
  open = ref(false),
  saving = ref(false),
  selected = ref<User>(),
  role = ref<'user' | 'admin'>('user')
const remote = useRemoteData<User[]>(
  async () => (await adminApi.getUsers()).data || [],
  [],
)
const filtered = computed(() =>
  remote.data.value.filter((row) =>
    `${row.email} ${row.user_id}`
      .toLowerCase()
      .includes(search.value.toLowerCase()),
  ),
)
const roleName = (value: string) =>
  ({ admin: '管理员', user: '普通用户', auditor: '审计员' })[value] || value
onMounted(() => {
  void remote.refresh()
})
function edit(row: User) {
  selected.value = row
  role.value = row.role === 'admin' ? 'admin' : 'user'
  open.value = true
}
function userCreated(user: User) {
  search.value = user.email
  void remote.refresh()
}
function editQuota(row: User) {
  quotaUser.value = row
  quotaOpen.value = true
}
function editBalance(row: User) {
  creditUser.value = row
  creditOpen.value = true
}
async function save() {
  if (saving.value || !selected.value) return
  saving.value = true
  try {
    await adminApi.setRole(selected.value.user_id, role.value)
    open.value = false
    ElMessage.success('角色已更新')
    if (selected.value.user_id === auth.userInfo?.user_id) {
      await auth.fetchUserInfo()
      if (!auth.isAdmin) {
        void router.replace('/dashboard')
        return
      }
    }
    await remote.refresh()
  } catch (error) {
    reportError(error)
  } finally {
    saving.value = false
  }
}
</script>
