<template>
  <el-alert
    v-if="budget.error"
    title="预算数据暂不可更新，请稍后到费用中心重试。"
    type="info"
    :closable="false"
    class="budget-notice"
  />
  <el-alert
    v-else-if="budget.summary && budget.summary.warning !== 'none'"
    :type="budget.summary.warning === 'insufficient' ? 'error' : 'warning'"
    :closable="false"
    show-icon
    class="budget-notice"
  >
    <template #title
      >{{
        budget.summary.warning === 'insufficient' ? '可用余额不足' : '余额预警'
      }}
      · ¥{{ budget.summary.available_balance.toFixed(4) }}</template
    >
    <div class="budget-notice-body">
      已扣除运行中预估费用 ¥{{
        budget.summary.unsettled_estimate.toFixed(4)
      }}。<span v-if="budget.summary.hourly_cost > 0"
        >按当前费率{{
          remainingTime(budget.summary.estimated_remaining_minutes)
        }}。</span
      >请联系管理员补充余额或释放不再使用的实例。
      <span v-if="budget.summary.grace_expires_at"
        >欠费保存期截止 {{ formatTime(budget.summary.grace_expires_at) }}，剩余
        {{ graceRemaining }}。请保存个人镜像，并将需要保留的临时文件复制到
        /data，到期自动释放实例。</span
      >
      <span v-else-if="budget.summary.warning === 'insufficient'"
        >按时实例欠费后保留
        {{ budget.summary.grace_hours }}
        小时用于保存文件与镜像。已付费包日、包周实例按各自截止时间释放。</span
      >
      <el-button link type="primary" @click="router.push('/billing')"
        >查看费用</el-button
      >
    </div>
  </el-alert>
</template>
<script setup lang="ts">
import { useRouter } from 'vue-router'
import { useBudgetStore } from '@/stores/budget'
import { useAutoRefresh } from '@/composables/useAutoRefresh'
import { remainingTime } from '@/utils/monitoring'
import { computed } from 'vue'
import { useClock } from '@/composables/useClock'
import { formatTime } from '@/utils/format'
const now = useClock()
const graceRemaining = computed(() => {
  const minutes = Math.max(
    0,
    Math.ceil(
      (Date.parse(budget.summary?.grace_expires_at || '') - now.value) / 60000,
    ),
  )
  return Number.isFinite(minutes)
    ? `${Math.floor(minutes / 60)}小时${minutes % 60}分钟`
    : '等待核对'
})
const budget = useBudgetStore(),
  router = useRouter()
useAutoRefresh(async () => {
  await budget.refresh()
}, 15000)
</script>
<style scoped>
.budget-notice {
  margin-bottom: 24px;
}
.budget-notice-body {
  font-size: 12px;
  line-height: 1.9;
}
</style>
