<template>
  <el-dialog
    :model-value="modelValue"
    title="资源配额与余额预警"
    width="600px"
    @update:model-value="$emit('update:modelValue', $event)"
  >
    <p class="caption" style="margin-bottom: 20px">{{ user?.email }}</p>
    <AsyncState
      :loading="remote.loading.value"
      :error="remote.error.value"
      :empty="!remote.data.value"
      @retry="load"
    >
      <template v-if="remote.data.value"
        ><div class="hint-box" style="margin-bottom: 20px">
          当前占用 {{ remote.data.value.used_gpus }} 张 GPU、{{
            remote.data.value.used_instances
          }}
          个实例；可用余额 ¥{{
            remote.data.value.available_balance.toFixed(4)
          }}。
        </div>
        <el-checkbox v-model="form.inherited" :disabled="saving"
          >使用平台默认配额与预警阈值</el-checkbox
        ><el-form label-position="top" class="section-gap"
          ><div class="detail-grid">
            <el-form-item label="最多同时使用 GPU（张）"
              ><el-input-number
                v-model="form.max_gpus"
                :key="`gpus-${form.inherited}`"
                :min="0"
                :max="4096"
                :disabled="form.inherited"
                controls-position="right" /></el-form-item
            ><el-form-item label="最多同时使用实例（个）"
              ><el-input-number
                v-model="form.max_instances"
                :key="`instances-${form.inherited}`"
                :min="0"
                :max="1024"
                :disabled="form.inherited"
                controls-position="right" /></el-form-item
            ><el-form-item :label="remote.data.value.storage_mode === 'fixed' ? '个人持久存储上限（GiB）' : '个人存储份额（用户存储池 %）'">
              <el-input-number
                v-if="remote.data.value.storage_mode === 'fixed'"
                v-model="form.storage_limit_gib"
                :min="1"
                :max="1048576"
                :precision="0"
                :disabled="form.inherited || form.storage_inherited"
                controls-position="right"
              />
              <el-input-number
                v-else
                v-model="form.storage_share_percent"
                :min="0.01"
                :max="100"
                :precision="2"
                :disabled="form.inherited || form.storage_inherited"
                controls-position="right"
              />
              <el-checkbox
                v-model="form.storage_inherited"
                :disabled="form.inherited"
                >使用首次分配的默认额度</el-checkbox
              >
              <p class="caption">
                文件与个人镜像共用额度；调整上限不会删除已有数据。
              </p> </el-form-item
            ><el-form-item label="校内统一余额预警阈值（元）"
              ><el-input-number
                v-model="form.low_balance_amount"
                :key="`balance-${form.inherited}`"
                :min="0"
                :max="1000000"
                :precision="4"
                :disabled="true"
                controls-position="right" /></el-form-item
            ><el-form-item label="提前运行时间预警（关闭）"
              ><el-input-number
                v-model="form.low_balance_minutes"
                :key="`minutes-${form.inherited}`"
                :min="0"
                :max="10080"
                :disabled="true"
                controls-position="right"
            /></el-form-item></div></el-form
        ><el-alert
          title="余额预警统一为 10 元，欠费后保留 6 小时用于保存。降低资源配额不会终止现有实例；上限设为 0 可暂停新申请。"
          type="info"
          :closable="false"
      /></template> </AsyncState
    ><template #footer
      ><el-button @click="$emit('update:modelValue', false)">取消</el-button
      ><el-button
        type="primary"
        :loading="saving"
        :disabled="
          remote.loading.value || !!remote.error.value || !remote.data.value
        "
        @click="save"
        >保存配额与预警</el-button
      ></template
    >
  </el-dialog>
</template>
<script setup lang="ts">
import { reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { monitoringApi, type UsageSummary } from '@/api/monitoring'
import { useRemoteData } from '@/composables/useRemoteData'
import { useBudgetStore } from '@/stores/budget'
import { reportError } from '@/utils/feedback'
import type { User } from '@/types'
import AsyncState from './AsyncState.vue'
const props = defineProps<{ modelValue: boolean; user?: User }>()
const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  updated: []
}>()
const saving = ref(false),
  form = reactive({
    inherited: true,
    storage_inherited: true,
    storage_share_percent: 10,
    storage_limit_gib: 100,
    max_gpus: 4,
    max_instances: 4,
    low_balance_amount: 10,
    low_balance_minutes: 30,
  })
const remote = useRemoteData<UsageSummary | null>(
  async () => (await monitoringApi.quota(props.user!.user_id)).data || null,
  null,
)
async function load() {
  const id = props.user?.user_id
  if (!id) return
  await remote.refresh()
  if (props.modelValue && id === props.user?.user_id && remote.data.value)
    Object.assign(form, {
      inherited: remote.data.value.inherited,
      storage_inherited: remote.data.value.storage_inherited ?? true,
      storage_share_percent: remote.data.value.storage_share_percent ?? 10,
      storage_limit_gib: remote.data.value.storage_limit_gib ?? 100,
      max_gpus: remote.data.value.max_gpus,
      max_instances: remote.data.value.max_instances,
      low_balance_amount: remote.data.value.low_balance_amount,
      low_balance_minutes: remote.data.value.low_balance_minutes,
    })
}
watch(
  () => [props.modelValue, props.user?.user_id],
  () => {
    if (props.modelValue) void load()
  },
)
watch(
  () => form.inherited,
  (value) => {
    if (value && remote.data.value)
      Object.assign(form, remote.data.value.default_limits)
  },
)
async function save() {
  if (saving.value || !props.user) return
  if (
    !form.inherited &&
    !form.storage_inherited &&
    !Number.isFinite(remote.data.value?.storage_mode === 'fixed' ? form.storage_limit_gib : form.storage_share_percent)
  )
    return ElMessage.warning('请填写个人存储额度')
  if (
    [
      form.max_gpus,
      form.max_instances,
      form.low_balance_amount,
      form.low_balance_minutes,
    ].some((value) => !Number.isFinite(value))
  )
    return ElMessage.warning('请填写完整的配额与阈值')
  saving.value = true
  try {
    await monitoringApi.setQuota(props.user.user_id, {
      ...form,
      storage_limit_gib: form.storage_inherited ? null : form.storage_limit_gib,
      storage_share_percent: form.storage_inherited
        ? null
        : form.storage_share_percent,
    })
    ElMessage.success('配额与预警已更新')
    emit('update:modelValue', false)
    emit('updated')
    void useBudgetStore()
      .refresh()
      .catch(() => {})
  } catch (error) {
    reportError(error)
  } finally {
    saving.value = false
  }
}
</script>
