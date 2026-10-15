<template>
  <PageHeader
    title="费用中心"
    eyebrow="BILLING"
    description="查看账户余额、按需价格与每一次实例结算。"
    ><el-button @click="refresh"
      ><el-icon><Refresh /></el-icon>刷新账单</el-button
    ></PageHeader
  >
  <div class="metrics-grid">
    <div class="metric accent">
      <p class="metric-label">账户余额</p>
      <p class="metric-value">¥{{ auth.userInfo?.balance.toFixed(4) }}</p>
      <p class="metric-sub">实例释放后自动完成结算</p>
      <span class="metric-icon"
        ><el-icon><Wallet /></el-icon
      ></span>
    </div>
    <div class="metric">
      <p class="metric-label">累计已结算</p>
      <p class="metric-value">¥{{ total.toFixed(4) }}</p>
      <p class="metric-sub">{{ billing.records.length }} 笔资源账单</p>
    </div>
    <div class="metric">
      <p class="metric-label">本月已结算</p>
      <p class="metric-value">¥{{ monthly.toFixed(4) }}</p>
      <p class="metric-sub">按结算完成时间统计</p>
    </div>
    <div class="metric">
      <p class="metric-label">运行中预估费用</p>
      <p class="metric-value">¥{{ estimated.toFixed(4) }}</p>
      <p class="metric-sub">未结算估值，最终以账单为准</p>
    </div>
  </div>
  <section class="panel" style="margin-bottom: 24px">
    <div class="panel-heading">
      <h2 class="panel-title">资源配额与可用预算</h2>
      <el-tag v-if="budget.summary">{{
        budget.summary.inherited ? '平台默认配额' : '个人配额'
      }}</el-tag>
    </div>
    <p v-if="budget.error" class="request-error">
      {{ budget.error }}<el-button link @click="budget.refresh">重试</el-button>
    </p>
    <div v-else-if="budget.summary" class="detail-grid">
      <div class="detail-item">
        <label>GPU 配额</label>
        <div>
          {{ budget.summary.used_gpus }} /
          {{ budget.summary.max_gpus }} 张，剩余
          {{ budget.summary.remaining_gpus }} 张
        </div>
      </div>
      <div class="detail-item">
        <label>实例配额</label>
        <div>
          {{ budget.summary.used_instances }} /
          {{ budget.summary.max_instances }} 个，剩余
          {{ budget.summary.remaining_instances }} 个
        </div>
      </div>
      <div class="detail-item">
        <label>可用余额（扣除未结算估值）</label>
        <div class="mono">
          ¥{{ budget.summary.available_balance.toFixed(4) }}
        </div>
      </div>
      <div class="detail-item">
        <label>按当前费率预计可继续运行</label>
        <div>
          {{ remainingTime(budget.summary.estimated_remaining_minutes) }}
        </div>
      </div>
    </div>
    <p class="caption section-gap">
      余额由管理员统一增加，请联系管理员补充额度。可用余额不超过 10
      元时预警；欠费后保留 6
      小时用于保存文件和镜像，到期自动释放实例，个人存储继续保留。新申请需要覆盖全部实例未来至少
      {{ budget.summary?.minimum_balance_minutes ?? 1 }}
      分钟的费用。
    </p>
  </section>
  <div class="panel">
    <div class="panel-heading">
      <h2 class="panel-title">费用记录</h2>
      <el-button :disabled="!filtered.length" @click="exportRecords"
        ><el-icon><Download /></el-icon>导出 CSV</el-button
      >
    </div>
    <div class="toolbar">
      <div class="toolbar-filters">
        <el-input
          v-model="search"
          clearable
          placeholder="搜索实例名"
          aria-label="搜索账单"
        /><el-date-picker
          v-model="range"
          type="daterange"
          value-format="YYYY-MM-DD"
          start-placeholder="开始日期"
          end-placeholder="结束日期"
          style="max-width: 270px"
        />
      </div>
      <el-button v-if="search" link @click="search = ''"
        >显示全部账单</el-button
      >
    </div>
    <AsyncState
      :loading="billing.loading"
      :error="billing.recordsError"
      :empty="billing.records.length === 0"
      empty-text="暂无结算记录，释放实例后可在此查看费用"
      @retry="refresh"
      ><el-table :data="pageRows" v-loading="billing.loading"
        ><el-table-column prop="id" label="订单编号" width="110"
          ><template #default="{ row }"
            ><span class="mono">#{{ row.id }}</span></template
          ></el-table-column
        ><el-table-column label="实例" min-width="210"
          ><template #default="{ row }"
            ><el-button
              link
              type="primary"
              class="mono"
@click="selectedRecord = row; recordOpen = true"
              >{{ row.instance_name || row.container_id }}</el-button
            ></template
          ></el-table-column
        ><el-table-column label="计费方式" width="120"><template #default="{ row }">{{ row.billing_mode === 'day' ? '包日（预付）' : row.billing_mode === 'week' ? '包周（预付）' : '按时' }}</template></el-table-column><el-table-column label="计费时间" min-width="270"
          ><template #default="{ row }"
            ><span class="caption"
              >{{ formatTime(row.start_time) }} →
              {{ formatTime(row.end_time) }}</span
            ></template
          ></el-table-column
        ><el-table-column label="结算金额" width="150"
          ><template #default="{ row }"
            ><strong class="mono"
              >¥{{ row.amount.toFixed(4) }}</strong
            ></template
          ></el-table-column
        ></el-table
      ><el-pagination
        v-if="filtered.length > 10"
        v-model:current-page="page"
        :page-size="10"
        :total="filtered.length"
        layout="total,prev,pager,next"
    /></AsyncState>
  </div>
  <section class="panel section-gap">
    <h2 class="panel-title">管理员增加余额记录</h2>
    <BalanceCreditHistory
      :history="credits.data.value"
      :loading="credits.loading.value"
      :error="credits.error.value"
      :page="creditPage"
      @refresh="credits.refresh"
      @page="changeCreditPage"
    />
  </section>
  <section class="panel section-gap">
    <h2 class="panel-title">GPU 计费标准</h2>
    <AsyncState
      :error="billing.pricesError"
      :empty="!billing.prices"
      @retry="refresh"
      ><div class="price-tags">
        <span v-for="(price, type) in billing.prices" :key="type"
          ><strong>{{ String(type).toUpperCase() }}</strong
          ><span class="mono">¥{{ price.toFixed(4) }} / 卡·小时 · 包日 ¥{{ (price * 24 * 0.8).toFixed(4) }}（8 折） · 包周 ¥{{ (price * 168 * 0.6).toFixed(4) }}（6 折）</span></span
        >
      </div></AsyncState
    >
    <p class="caption section-gap">
      按时实例按申请时单价结算。包日、包周下单扣费，就绪起算，到期自动释放，提前释放不退费；创建失败退回余额。
    </p>
  </section>
  <el-dialog v-model="recordOpen" title="费用记录" width="560px">
    <div v-if="selectedRecord" class="detail-grid">
      <div class="detail-item"><label>实例</label><div>{{ selectedRecord.instance_name || selectedRecord.container_id }}</div></div>
      <div class="detail-item"><label>计费方式</label><div>{{ selectedRecord.billing_mode === 'day' ? '包日（预付）' : selectedRecord.billing_mode === 'week' ? '包周（预付）' : '按时' }}</div></div>
      <div class="detail-item"><label>金额</label><div>¥{{ selectedRecord.amount.toFixed(4) }}</div></div>
      <div class="detail-item"><label>扣费时间</label><div>{{ formatTime(selectedRecord.charged_at || selectedRecord.end_time) }}</div></div>
      <div class="detail-item"><label>计费开始</label><div>{{ formatTime(selectedRecord.start_time) }}</div></div>
      <div class="detail-item"><label>计费结束</label><div>{{ formatTime(selectedRecord.end_time) }}</div></div>
    </div>
    <template #footer><el-button @click="recordOpen = false">关闭</el-button><el-button type="primary" @click="router.push('/compute/history')">历史订单</el-button></template>
  </el-dialog>
</template>
<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import type { BillingRecord } from '@/types'
import dayjs from 'dayjs'
import { useBillingStore } from '@/stores/billing'
import { useAuthStore } from '@/stores/auth'
import { useResourceStore } from '@/stores/resource'
import { useBudgetStore } from '@/stores/budget'
import { remainingTime } from '@/utils/monitoring'
import { useAutoRefresh } from '@/composables/useAutoRefresh'
import { useClock } from '@/composables/useClock'
import { instanceEstimate } from '@/utils/instance'
import { formatTime } from '@/utils/format'
import { downloadCsv } from '@/utils/export'
import PageHeader from '@/components/PageHeader.vue'
import AsyncState from '@/components/AsyncState.vue'
import BalanceCreditHistory from '@/components/BalanceCreditHistory.vue'
import { billingApi } from '@/api/billing'
import type { CreditHistory } from '@/api/balanceCredits'
import { useRemoteData } from '@/composables/useRemoteData'
const recordOpen = ref(false), selectedRecord = ref<BillingRecord | null>(null)
const creditPage = ref(1)
const credits = useRemoteData<CreditHistory>(
  async () =>
    (await billingApi.getCredits(creditPage.value)).data || {
      items: [],
      total: 0,
    },
  { items: [], total: 0 },
)
function changeCreditPage(value: number) {
  creditPage.value = value
  void credits.refresh()
}
const billing = useBillingStore(),
  auth = useAuthStore(),
  resources = useResourceStore(),
  route = useRoute(),
  router = useRouter(),
  now = useClock()
const budget = useBudgetStore()
const search = ref(String(route.query.instance || '')),
  range = ref<[string, string]>(),
  page = ref(1)
const total = computed(() =>
  billing.records.reduce((sum, row) => sum + row.amount, 0),
)
const monthly = computed(() =>
  billing.records
    .filter((row) => dayjs(row.charged_at || row.end_time).isSame(dayjs(), 'month'))
    .reduce((sum, row) => sum + row.amount, 0),
)
const estimated = computed(() =>
  resources.activeInstances.reduce(
    (sum, row) => sum + (instanceEstimate(row, now.value) || 0),
    0,
  ),
)
const filtered = computed(() =>
  [...billing.records]
    .filter(
      (row) =>
        `${row.instance_name || ''} ${row.container_id}`.includes(search.value) &&
        (!range.value ||
          (!dayjs(row.end_time).isBefore(dayjs(range.value[0]), 'day') &&
            !dayjs(row.end_time).isAfter(dayjs(range.value[1]), 'day'))),
    )
    .sort((a, b) => b.id - a.id),
)
const pageRows = computed(() =>
  filtered.value.slice((page.value - 1) * 10, page.value * 10),
)
watch([search, range], () => {
  page.value = 1
})
const refresh = useAutoRefresh(async () => {
  await Promise.allSettled([
    billing.fetchRecords(),
    billing.fetchPrices(),
    auth.fetchUserInfo(),
    resources.fetchMyResources(),
    budget.refresh(),
    credits.refresh(),
  ])
})
function exportRecords() {
  downloadCsv(
    '算力结算记录.csv',
    ['订单编号', '实例名', '内部ID', '金额(元)', '开始时间', '结束时间'],
    filtered.value.map((row) => [
      row.id,
      row.instance_name || row.container_id,
      row.container_id,
      row.amount.toFixed(4),
      formatTime(row.start_time),
      formatTime(row.end_time),
    ]),
  )
}
</script>
<style scoped>
.price-tags {
  display: flex;
  gap: 20px;
  flex-wrap: wrap;
}
.price-tags > span {
  display: flex;
  gap: 12px;
  padding: 16px 20px;
  background: #f7f9fd;
  border-radius: 8px;
  align-items: center;
}
.price-tags strong {
  font-size: 12px;
  color: #4d6487;
}
.price-tags .mono {
  font-size: 11px;
  color: #8798b1;
}
</style>
