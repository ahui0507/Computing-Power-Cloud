<template>
  <el-dialog
    :model-value="modelValue"
    title="增加用户余额"
    width="720px"
    :close-on-click-modal="false"
    :close-on-press-escape="!saving"
    :show-close="!saving"
    :before-close="close"
    @update:model-value="$emit('update:modelValue', $event)"
  >
    <div class="hint-box">
      <strong>{{ user?.email }}</strong>
      <p class="caption">
        用户 #{{ user?.user_id }} · 当前余额 ¥{{ user?.balance.toFixed(4) }}
      </p>
    </div>
    <el-alert
      v-if="pending"
      class="section-gap"
      title="上次提交结果尚未确认，重试会核对同一笔操作，不会重复入账。"
      type="warning"
      :closable="false"
    />
    <el-form label-position="top" class="section-gap" @submit.prevent="save">
      <el-form-item label="增加金额（元）">
        <el-input-number
          v-model="amount"
          :min="0.0001"
          :max="1000000"
          :precision="4"
          :disabled="saving || !!pending"
          controls-position="right"
          style="width: 100%"
        />
      </el-form-item>
      <el-form-item label="操作说明">
        <el-input
          v-model="reason"
          type="textarea"
          :rows="2"
          maxlength="200"
          show-word-limit
          placeholder="例如：项目经费到账、测试额度发放"
          :disabled="saving || !!pending"
        />
      </el-form-item>
    </el-form>
    <p class="caption">
      确认后为上述用户增加 ¥{{
        (amount || 0).toFixed(4)
      }}。操作人、金额及说明会保存到记录中。
    </p>
    <h3 class="panel-title section-gap">最近到账记录</h3>
    <BalanceCreditHistory
      :history="history.data.value"
      :loading="history.loading.value"
      :error="history.error.value"
      :page="page"
      @refresh="history.refresh"
      @page="changePage"
    />
    <template #footer>
      <el-button :disabled="saving" @click="$emit('update:modelValue', false)"
        >关闭</el-button
      >
      <el-button
        type="primary"
        :loading="saving"
        :disabled="!valid"
        @click="save"
      >
        {{ pending ? '核对并重试本笔操作' : '确认增加余额' }}
      </el-button>
    </template>
  </el-dialog>
</template>
<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { adminApi } from '@/api/admin'
import type { CreditHistory, CreditRequest } from '@/api/balanceCredits'
import { useAuthStore } from '@/stores/auth'
import { useRemoteData } from '@/composables/useRemoteData'
import { ApiError } from '@/utils/request'
import { reportError } from '@/utils/feedback'
import type { User } from '@/types'
import BalanceCreditHistory from './BalanceCreditHistory.vue'
const props = defineProps<{ modelValue: boolean; user?: User }>()
const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  updated: []
}>()
const auth = useAuthStore()
const saving = ref(false),
  amount = ref<number | undefined>(100),
  reason = ref(''),
  page = ref(1)
const pending = ref<CreditRequest>()
const storageKey = computed(
  () => `balance-credit:${auth.userInfo?.user_id}:${props.user?.user_id}`,
)
const valid = computed(
  () =>
    !!pending.value ||
    (Number.isFinite(amount.value) &&
      amount.value! > 0 &&
      amount.value! <= 1000000 &&
      !!reason.value.trim()),
)
const history = useRemoteData<CreditHistory>(
  async () =>
    (await adminApi.balanceCredits(props.user!.user_id, page.value)).data || {
      items: [],
      total: 0,
    },
  { items: [], total: 0 },
)
watch(
  () => [props.modelValue, props.user?.user_id],
  () => {
    if (!props.modelValue || !props.user) return
    page.value = 1
    pending.value = undefined
    // 在同一个浏览器标签中刷新或关闭后重开，仍核对未确认的操作。
    const saved = sessionStorage.getItem(storageKey.value)
    if (saved) {
      try {
        pending.value = JSON.parse(saved) as CreditRequest
      } catch {
        sessionStorage.removeItem(storageKey.value)
      }
    }
    amount.value = pending.value ? Number(pending.value.amount) : 100
    reason.value = pending.value?.reason || ''
    void history.refresh()
  },
)
function close(done: () => void) {
  if (!saving.value) done()
}
function changePage(value: number) {
  page.value = value
  void history.refresh()
}
async function save() {
  if (saving.value || !props.user || !valid.value) return
  saving.value = true
  try {
    if (!pending.value) {
      // getRandomValues 也支持当前 HTTP 内网页面。
      const id = Array.from(
        crypto.getRandomValues(new Uint8Array(16)),
        (value) => value.toString(16).padStart(2, '0'),
      ).join('')
      pending.value = {
        request_id: id,
        amount: amount.value!.toFixed(4),
        reason: reason.value.trim(),
      }
      sessionStorage.setItem(storageKey.value, JSON.stringify(pending.value))
    }
    const response = await adminApi.addBalance(
      props.user.user_id,
      pending.value,
    )
    sessionStorage.removeItem(storageKey.value)
    pending.value = undefined
    ElMessage.success(`余额已增加 ¥${response.data!.amount.toFixed(4)}`)
    emit('updated')
    emit('update:modelValue', false)
  } catch (error) {
    if (
      error instanceof ApiError &&
      [400, 401, 403, 404, 409, 422].includes(error.code)
    ) {
      sessionStorage.removeItem(storageKey.value)
      pending.value = undefined
    }
    reportError(error)
  } finally {
    saving.value = false
  }
}
</script>
