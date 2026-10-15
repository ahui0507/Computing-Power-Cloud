<template>
  <section class="instance-telemetry section-gap">
    <div class="panel-heading">
      <h3 class="panel-title">实例实时指标</h3>
      <el-tag
        v-if="remote.data.value"
        :type="telemetryType(remote.data.value.telemetry_state)"
        >{{ telemetryText(remote.data.value.telemetry_state) }}</el-tag
      >
    </div>
    <p v-if="remote.error.value" class="caption">
      指标暂不可查询，可稍后重试。
    </p>
    <p class="caption">
      {{
        remote.data.value?.received_at
          ? `最近上报：${formatTime(remote.data.value.received_at)}`
          : '等待采集服务上报。缺失指标显示为 —。'
      }}
    </p>
    <div class="gpu-metric-row">
      <strong>CPU / 内存</strong><span>相对本实例的分配额度</span>
      <span
        >CPU
        {{ metricText(remote.data.value?.runtime?.cpu_percent, '%') }}</span
      >
      <span
        >内存
        {{ metricText(remote.data.value?.runtime?.memory_percent, '%') }}</span
      >
    </div>
    <p v-if="remote.data.value?.runtime?.restart_count" class="caption">
      容器重启 {{ remote.data.value.runtime.restart_count }} 次。
    </p>
    <el-alert
      v-if="remote.data.value?.runtime?.last_exit_reason"
      :title="
        remote.data.value.runtime.last_exit_reason.includes('OOMKilled')
          ? '曾因内存达到分配额度而退出，请减小批量或申请更多 GPU 份额。'
          : `最近退出原因：${remote.data.value.runtime.last_exit_reason}`
      "
      type="warning"
      :closable="false"
    />
    <div
      v-for="gpu in remote.data.value?.gpu_list || []"
      :key="gpu.gpu_id"
      class="gpu-metric-row"
    >
      <strong>GPU #{{ gpu.index }}</strong
      ><span>利用率 {{ metricText(gpu.utilization, '%') }}</span
      ><span
        >显存 {{ metricText(gpu.memory_used_mb, ' MiB', 0) }} /
        {{ metricText(gpu.memory_total_mb, ' MiB', 0) }}</span
      ><span
        >{{ metricText(gpu.temperature, ' °C') }} ·
        {{ metricText(gpu.power_watts, ' W') }}</span
      >
    </div>
  </section>
</template>
<script setup lang="ts">
import { monitoringApi, type InstanceMetrics } from '@/api/monitoring'
import { useRemoteData } from '@/composables/useRemoteData'
import { useAutoRefresh } from '@/composables/useAutoRefresh'
import { formatTime } from '@/utils/format'
import { metricText, telemetryText, telemetryType } from '@/utils/monitoring'
const props = defineProps<{ containerId: string }>()
const remote = useRemoteData<InstanceMetrics | null>(
  async () => (await monitoringApi.instance(props.containerId)).data || null,
  null,
)
useAutoRefresh(remote.refresh, 15000)
</script>
<style scoped>
.instance-telemetry {
  padding-top: 22px;
  border-top: 1px solid #edf1f6;
}
.gpu-metric-row {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
  padding: 16px 0;
  border-bottom: 1px solid #edf1f6;
  font-size: 11px;
  color: #7e8ea8;
}
.gpu-metric-row strong {
  color: #3b5170;
}
</style>
