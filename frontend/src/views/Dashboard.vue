<template>
  <PageHeader
    title="欢迎回来，开始今天的探索"
    eyebrow="OVERVIEW"
    description="这里是你的算力工作空间，准备好开始下一次探索了吗？"
    ><el-button @click="refresh"
      ><el-icon><Refresh /></el-icon>刷新</el-button
    ><el-button type="primary" @click="router.push('/compute/pools')"
      ><el-icon><Plus /></el-icon>创建实例</el-button
    ></PageHeader
  >
  <div class="metrics-grid">
    <div
      class="metric"
      v-for="metric in metrics"
      :key="metric.label"
      :class="{ accent: metric.accent }"
    >
      <p class="metric-label">{{ metric.label }}</p>
      <p class="metric-value">
        {{ metric.value }}<span class="metric-unit">{{ metric.unit }}</span>
      </p>
      <p class="metric-sub">{{ metric.note }}</p>
      <span class="metric-icon"
        ><el-icon><component :is="metric.icon" /></el-icon
      ></span>
    </div>
  </div>
  <div class="two-columns">
    <div class="stack">
      <section class="panel">
        <div class="panel-heading">
          <h2 class="panel-title">我的运行实例</h2>
          <el-button
            link
            type="primary"
            @click="router.push('/compute/instances')"
            >查看全部<el-icon><ArrowRight /></el-icon
          ></el-button>
        </div>
        <AsyncState
          :loading="resources.instancesLoading"
          :error="resources.instancesError"
          :empty="resources.activeInstances.length === 0"
          empty-text="你的下一次探索，从一台实例开始"
          @retry="refresh"
          ><template #empty
            ><el-button type="primary" @click="router.push('/compute/pools')"
              >浏览可用算力</el-button
            ></template
          ><el-table :data="resources.activeInstances.slice(0, 4)"
            ><el-table-column label="实例" min-width="170"
              ><template #default="{ row }"
                ><el-button
                  link
                  type="primary"
                  class="mono"
                  @click="
                    router.push({
                      path: '/compute/instances',
                      query: { id: row.container_id },
                    })
                  "
                  >{{ row.instance_name || row.container_id }}</el-button
                >
                <div class="table-secondary">
                  {{ row.gpus }} 张 GPU
                </div></template
              ></el-table-column
            ><el-table-column label="状态" width="100"
              ><template #default="{ row }"
                ><StatusTag :status="row.status" /></template></el-table-column
            ><el-table-column label="快速连接" width="120"
              ><template #default="{ row }"
                ><el-button
                  link
                  type="primary"
                  :disabled="row.status !== 'running' || !row.jupyter_url"
                  @click="open(row.jupyter_url)"
                  >JupyterLab<el-icon
                    ><TopRight /></el-icon></el-button></template></el-table-column></el-table
        ></AsyncState>
      </section>
      <ChartCard
        title="最近七天已结算费用"
        :option="costOption"
        :height="245"
        :loading="billing.loading"
      />
    </div>
    <div class="stack">
      <section class="panel getting-started">
        <p class="eyebrow">QUICK START</p>
        <h2 class="panel-title">从代码到结果，三步开始</h2>
        <div class="quick-step">
          <span>01</span>
          <div>
            <strong>选择算力与镜像</strong>
            <p>按需配置 GPU，确认价格后创建</p>
          </div>
        </div>
        <div class="quick-step">
          <span>02</span>
          <div>
            <strong>打开你的开发环境</strong>
            <p>使用 JupyterLab、终端或后台任务</p>
          </div>
        </div>
        <div class="quick-step">
          <span>03</span>
          <div>
            <strong>保留文件，按需释放</strong>
            <p>临时工作 /workspace · 持久保存 /data</p>
          </div>
        </div>
        <el-button link type="primary" @click="router.push('/guide')"
          >阅读使用指南<el-icon><ArrowRight /></el-icon
        ></el-button>
      </section>
      <section class="panel">
        <div class="panel-heading">
          <h2 class="panel-title">最近费用</h2>
          <el-button link @click="router.push('/billing')">全部账单</el-button>
        </div>
        <AsyncState
          :error="billing.recordsError"
          :empty="billing.records.length === 0"
          empty-text="暂无结算记录"
          @retry="refresh"
          ><div v-for="record in recent" :key="record.id" class="activity-row">
            <div class="activity-icon">
              <el-icon><Tickets /></el-icon>
            </div>
            <div style="min-width: 0; flex: 1">
              <p class="mono">
                {{ record.instance_name || record.container_id }}
              </p>
              <p class="table-secondary">
                {{
                  formatTime(
                    record.charged_at || record.end_time,
                    'MM-DD HH:mm',
                  )
                }}
              </p>
            </div>
            <strong class="mono">¥{{ record.amount.toFixed(4) }}</strong>
          </div></AsyncState
        >
      </section>
    </div>
  </div>
</template>
<script setup lang="ts">
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import dayjs from 'dayjs'
import { useResourceStore } from '@/stores/resource'
import { useAuthStore } from '@/stores/auth'
import { useBillingStore } from '@/stores/billing'
import { resourceApi } from '@/api'
import { useRemoteData } from '@/composables/useRemoteData'
import { useAutoRefresh } from '@/composables/useAutoRefresh'
import { formatTime } from '@/utils/format'
import type { ResourceSummary } from '@/types'
import type { EChartsOption } from 'echarts'
import PageHeader from '@/components/PageHeader.vue'
import StatusTag from '@/components/StatusTag.vue'
import AsyncState from '@/components/AsyncState.vue'
import ChartCard from '@/components/ChartCard.vue'
const router = useRouter(),
  resources = useResourceStore(),
  auth = useAuthStore(),
  billing = useBillingStore()
const summary = useRemoteData<ResourceSummary | null>(
  async () => (await resourceApi.getSummary()).data || null,
  null,
)
const spent = computed(() =>
  billing.records
    .filter((row) => dayjs(row.end_time).isSame(dayjs(), 'day'))
    .reduce((sum, row) => sum + row.amount, 0),
)
const metrics = computed(() => [
  {
    label: '可申请 GPU',
    value: summary.data.value?.free_gpus ?? '—',
    unit: '张',
    note: summary.error.value || '集群当前可用资源',
    icon: 'Cpu',
    accent: false,
  },
  {
    label: '我的运行实例',
    value: resources.activeInstances.filter((row) => row.status === 'running')
      .length,
    unit: '台',
    note: `另有 ${resources.activeInstances.filter((row) => row.status === 'pending').length} 台正在创建`,
    icon: 'Monitor',
    accent: false,
  },
  {
    label: '今日已结算',
    value: `¥${spent.value.toFixed(4)}`,
    unit: '',
    note: billing.recordsError || '按今天的结算记录统计',
    icon: 'Tickets',
    accent: false,
  },
  {
    label: '账户余额',
    value: `¥${auth.userInfo?.balance.toFixed(4) || '0.0000'}`,
    unit: '',
    note: '实例运行时请留意账户余额',
    icon: 'Wallet',
    accent: true,
  },
])
const recent = computed(() =>
  [...billing.records]
    .sort((a, b) => dayjs(b.end_time).valueOf() - dayjs(a.end_time).valueOf())
    .slice(0, 4),
)
const costOption = computed<EChartsOption>(() => {
  const days = Array.from({ length: 7 }, (_, i) =>
    dayjs().subtract(6 - i, 'day'),
  )
  return {
    color: ['#7298ee'],
    tooltip: { trigger: 'axis' },
    grid: { left: 48, right: 20, top: 22, bottom: 28 },
    xAxis: {
      type: 'category',
      data: days.map((day) => day.format('MM-DD')),
      axisLine: { show: false },
      axisTick: { show: false },
      axisLabel: { color: '#99a6b8', fontSize: 10 },
    },
    yAxis: {
      type: 'value',
      splitLine: { lineStyle: { color: '#eff2f7', type: 'dashed' } },
      axisLabel: { color: '#99a6b8', fontSize: 10 },
    },
    series: [
      {
        type: 'bar',
        barWidth: 18,
        itemStyle: { borderRadius: [4, 4, 0, 0] },
        data: days.map((day) =>
          Number(
            billing.records
              .filter((row) => dayjs(row.end_time).isSame(day, 'day'))
              .reduce((sum, row) => sum + row.amount, 0)
              .toFixed(4),
          ),
        ),
      },
    ],
  }
})
const refresh = useAutoRefresh(async () => {
  await Promise.allSettled([
    summary.refresh(),
    resources.fetchMyResources(),
    billing.fetchRecords(),
    auth.fetchUserInfo(),
  ])
})
function open(url?: string | null) {
  if (url) window.open(url, '_blank', 'noopener,noreferrer')
}
</script>
<style scoped>
.quick-step {
  display: flex;
  gap: 14px;
  margin: 22px 0;
}
.quick-step > span {
  height: 30px;
  width: 30px;
  background: #eff4ff;
  color: #6f91d5;
  font-size: 11px;
  border-radius: 8px;
  display: grid;
  place-items: center;
}
.quick-step strong {
  font-size: 12px;
  font-weight: 550;
  color: #4c5f7d;
}
.quick-step p {
  font-size: 10px;
  color: #9aa7ba;
  margin-top: 7px;
}
.getting-started {
  background: linear-gradient(140deg, #fff, #f4f8ff);
}
.activity-row {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 16px 0;
  border-bottom: 1px solid #f0f3f8;
}
.activity-row:last-child {
  border-bottom: 0;
}
.activity-row .mono {
  font-size: 10px;
  overflow: hidden;
  text-overflow: ellipsis;
}
.activity-icon {
  height: 32px;
  width: 32px;
  border-radius: 8px;
  background: #f2f6fd;
  color: #8ca4cb;
  display: grid;
  place-items: center;
  flex-shrink: 0;
}
</style>
