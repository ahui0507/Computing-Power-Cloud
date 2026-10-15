<template>
  <PageHeader
    title="节点与 GPU 监控"
    eyebrow="LIVE TELEMETRY"
    description="查看主机实际采集的指标和心跳，每 15 秒更新。"
    ><el-button :loading="nodes.loading.value" @click="refresh"
      ><el-icon><Refresh /></el-icon>刷新指标</el-button
    ></PageHeader
  >
  <div class="hint-box" style="margin-bottom: 22px">
    指标缺失或超过采集有效期会显示为 —，不会显示成 0。历史数据保留 7
    天；曲线展示所选时段的聚合值，空白代表未采集。
  </div>
  <section class="panel">
    <AsyncState
      :loading="nodes.loading.value"
      :error="nodes.error.value"
      :empty="!nodes.data.value.length"
      empty-text="暂无节点"
      @retry="refresh"
      ><el-table :data="nodes.data.value"
        ><el-table-column label="节点" min-width="170"
          ><template #default="{ row }"
            ><span class="table-primary">{{ row.name }}</span>
            <p class="table-secondary mono">{{ row.ip }}</p></template
          ></el-table-column
        ><el-table-column label="采集状态" width="135"
          ><template #default="{ row }"
            ><el-tag :type="telemetryType(row.telemetry_state)">{{
              telemetryText(row.telemetry_state)
            }}</el-tag></template
          ></el-table-column
        ><el-table-column label="CPU" width="100"
          ><template #default="{ row }">{{
            metricText(row.cpu_usage, '%')
          }}</template></el-table-column
        ><el-table-column label="内存" width="100"
          ><template #default="{ row }">{{
            metricText(row.mem_usage, '%')
          }}</template></el-table-column
        ><el-table-column label="GPU 空闲 / 总数" width="135"
          ><template #default="{ row }"
            >{{ row.gpus_free }} / {{ row.gpus_total }}</template
          ></el-table-column
        ><el-table-column label="最近上报" min-width="170"
          ><template #default="{ row }"
            ><span class="caption">{{
              row.received_at ? formatTime(row.received_at) : '尚未收到数据'
            }}</span></template
          ></el-table-column
        ><el-table-column label="操作" width="110" fixed="right"
          ><template #default="{ row }"
            ><el-button link type="primary" @click="showDetail(row)"
              >指标与历史</el-button
            ></template
          ></el-table-column
        ></el-table
      ></AsyncState
    >
  </section>
  <el-drawer v-model="open" title="节点指标与历史" size="850px"
    ><AsyncState
      :loading="detail.loading.value"
      :error="detail.error.value"
      :empty="!selected"
      @retry="refresh"
      ><template v-if="selected"
        ><div class="panel-heading">
          <h2 class="panel-title">{{ selected.name }}</h2>
          <el-tag :type="telemetryType(selected.telemetry_state)">{{
            telemetryText(selected.telemetry_state)
          }}</el-tag>
        </div>
        <div class="detail-grid">
          <div class="detail-item">
            <label>地址 / 主机记录状态</label>
            <div>
              {{ selected.ip }} · <StatusTag :status="selected.status" />
            </div>
          </div>
          <div class="detail-item">
            <label>最近心跳</label>
            <div>
              {{
                selected.received_at
                  ? formatTime(selected.received_at)
                  : '尚未上报'
              }}
            </div>
          </div>
          <div class="detail-item">
            <label>CPU</label>
            <div>
              {{ metricText(selected.cpu_usage, '%') }} ·
              {{ selected.cpu_cores ?? '—' }} 核
            </div>
          </div>
          <div class="detail-item">
            <label>内存</label>
            <div>
              {{
                metricText(
                  selected.memory_used_mb == null
                    ? null
                    : selected.memory_used_mb / 1024,
                  ' GiB',
                )
              }}
              /
              {{
                metricText(
                  selected.memory_total_mb == null
                    ? null
                    : selected.memory_total_mb / 1024,
                  ' GiB',
                )
              }}
              · {{ metricText(selected.mem_usage, '%') }}
            </div>
          </div>
        </div>
        <el-alert
          v-if="
            selected.telemetry_state === 'stale' ||
            selected.telemetry_state === 'missing'
          "
          title="当前没有有效的新指标，历史曲线仍可查询。"
          type="warning"
          :closable="false"
          class="section-gap"
        /><el-alert
          v-if="selected.gpu_error"
          :title="selected.gpu_error"
          type="warning"
          :closable="false"
          class="section-gap"
        />
        <el-alert
          v-if="selected.ownership_error"
          :title="selected.ownership_error"
          type="warning"
          :closable="false"
          class="section-gap"
        />
        <h3 class="panel-title section-gap">物理 GPU</h3>
        <el-table :data="selected.gpu_list || []"
          ><el-table-column label="GPU" min-width="110"
            ><template #default="{ row }"
              ><span class="table-primary"
                >#{{ row.index }} · {{ row.type }}</span
              >
              <p class="table-secondary">
                <StatusTag
                  :status="row.status"
                /></p></template></el-table-column
          ><el-table-column label="利用率" width="105"
            ><template #default="{ row }">{{
              metricText(row.utilization, '%')
            }}</template></el-table-column
          ><el-table-column label="显存 已用 / 总量" min-width="180"
            ><template #default="{ row }"
              >{{ metricText(row.memory_used_mb, ' MiB', 0) }} /
              {{ metricText(row.memory_total_mb, ' MiB', 0) }}</template
            ></el-table-column
          ><el-table-column label="温度" width="95"
            ><template #default="{ row }">{{
              metricText(row.temperature, ' °C')
            }}</template></el-table-column
          ><el-table-column label="功耗" width="105"
            ><template #default="{ row }">{{
              metricText(row.power_watts, ' W')
            }}</template></el-table-column
          ></el-table
        >
        <div class="toolbar section-gap">
          <el-select v-model="mode" style="width: 200px" aria-label="监控指标"
            ><el-option label="CPU 与内存 (%)" value="host" /><el-option
              label="GPU 利用率 (%)"
              value="utilization" /><el-option
              label="GPU 显存 (MiB)"
              value="memory_used_mb" /><el-option
              label="GPU 温度 (°C)"
              value="temperature" /><el-option
              label="GPU 功耗 (W)"
              value="power_watts" /></el-select
          ><el-radio-group v-model="minutes" size="small" aria-label="历史时段"
            ><el-radio-button :label="60">1 小时</el-radio-button
            ><el-radio-button :label="360">6 小时</el-radio-button
            ><el-radio-button :label="1440"
              >24 小时</el-radio-button
            ></el-radio-group
          >
        </div>
        <p v-if="history.error.value" class="request-error">
          {{ history.error.value
          }}<el-button link @click="history.refresh">重试</el-button>
        </p>
        <ChartCard
          title="历史曲线"
          :option="chart"
          :height="270"
          :loading="history.loading.value"
        />
        <p class="caption">
          CPU、内存、利用率和功耗为区间平均值，GPU
          显存和温度为区间最高值；未采集的区间保留为空白。
        </p></template
      ></AsyncState
    ></el-drawer
  >
</template>
<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import dayjs from 'dayjs'
import type { EChartsOption } from 'echarts'
import {
  monitoringApi,
  type MonitoredNode,
  type MetricHistory,
} from '@/api/monitoring'
import { useRemoteData } from '@/composables/useRemoteData'
import { useAutoRefresh } from '@/composables/useAutoRefresh'
import { formatTime } from '@/utils/format'
import { metricText, telemetryText, telemetryType } from '@/utils/monitoring'
import PageHeader from '@/components/PageHeader.vue'
import AsyncState from '@/components/AsyncState.vue'
import StatusTag from '@/components/StatusTag.vue'
import ChartCard from '@/components/ChartCard.vue'
const nodes = useRemoteData<MonitoredNode[]>(
  async () => (await monitoringApi.nodes()).data || [],
  [],
)
const open = ref(false),
  selectedId = ref(0),
  minutes = ref(60),
  mode = ref('host')
const detail = useRemoteData<MonitoredNode | null>(
  async () => (await monitoringApi.node(selectedId.value)).data || null,
  null,
)
const history = useRemoteData<MetricHistory | null>(
  async () =>
    (await monitoringApi.history(selectedId.value, minutes.value)).data || null,
  null,
)
const selected = computed(() =>
  detail.data.value?.node_id === selectedId.value ? detail.data.value : null,
)
const refresh = useAutoRefresh(async () => {
  await nodes.refresh()
  if (open.value && selectedId.value)
    await Promise.all([detail.refresh(), history.refresh()])
})
watch(minutes, () => {
  if (open.value) void history.refresh()
})
function showDetail(row: MonitoredNode) {
  selectedId.value = row.node_id
  open.value = true
  void Promise.all([detail.refresh(), history.refresh()])
}
const chart = computed<EChartsOption>(() => {
  const points = history.data.value?.points || []
  const lines =
    mode.value === 'host'
      ? [
          { name: 'CPU', data: points.map((point) => point.cpu_usage) },
          { name: '内存', data: points.map((point) => point.mem_usage) },
        ]
      : (selected.value?.gpu_list || []).map((gpu) => ({
          name: `GPU #${gpu.index}`,
          data: points.map((point) => {
            const sample = point.gpus.find((row) => row.gpu_id === gpu.gpu_id)
            return sample
              ? sample[
                  mode.value as
                    | 'utilization'
                    | 'memory_used_mb'
                    | 'temperature'
                    | 'power_watts'
                ]
              : null
          }),
        }))
  return {
    color: ['#527ee8', '#33a38b', '#e7ab4d', '#9974d5'],
    tooltip: { trigger: 'axis' },
    legend: { bottom: 0, textStyle: { color: '#8392a9', fontSize: 10 } },
    grid: { left: 52, right: 18, top: 20, bottom: 58 },
    xAxis: {
      type: 'category',
      data: points.map((point) =>
        dayjs(point.at).format(minutes.value > 60 ? 'MM-DD HH:mm' : 'HH:mm:ss'),
      ),
      axisLabel: { color: '#8e9cb0', fontSize: 10 },
      axisTick: { show: false },
    },
    yAxis: {
      type: 'value',
      min: 0,
      max: ['host', 'utilization'].includes(mode.value) ? 100 : undefined,
      splitLine: { lineStyle: { color: '#edf1f6' } },
      axisLabel: { color: '#8e9cb0', fontSize: 10 },
    },
    series: lines.map((line) => ({
      name: line.name,
      type: 'line',
      connectNulls: false,
      showSymbol: false,
      data: line.data,
      lineStyle: { width: 2 },
    })),
  }
})
</script>
