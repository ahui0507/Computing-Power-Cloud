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
    <section class="scratch-usage">
      <h4>临时磁盘用量</h4>
      <template v-if="scratch?.state === 'live'">
        <p>已用 {{ gib(scratch.used_bytes) }} / {{ gib(scratch.limit_bytes) }} · 剩余 {{ gib(scratch.remaining_bytes) }}</p>
        <el-progress v-if="scratch.used_percent != null" :percentage="Math.min(100, Math.max(0, scratch.used_percent))"
          :status="scratch.warning === 'critical' ? 'exception' : scratch.warning === 'warning' ? 'warning' : undefined"
          :format="() => `${scratch!.used_percent!.toFixed(1)}%`" />
        <el-alert v-if="scratch.warning === 'warning' || scratch.warning === 'critical'"
          :title="scratch.warning === 'critical' ? '临时磁盘已达到 90%：请尽快清理或保存成果，超限可能终止实例。' : '临时磁盘已达到 80%：请清理缓存，将需保留的文件保存到个人存储。'"
          :type="scratch.warning === 'critical' ? 'error' : 'warning'" :closable="false" />
        <p v-if="scratch.limit_bytes == null" class="caption">此实例没有配置临时磁盘限额。</p>
      </template>
      <p v-else class="caption">{{ scratch?.state === 'stale' ? '临时磁盘样本已过期，等待新数据。' : '临时磁盘用量暂不可查询。' }}缺失数据不按 0 显示。</p>
      <p class="caption">系统可写层、临时目录与容器日志合并计量，个人持久存储和内存共享空间另算。80%/90% 提醒也会进入站内提醒；采集有延迟，快速写入时仍可能超限。</p>
      <p v-if="scratch?.sampled_at" class="caption">采样时间：{{ formatTime(scratch.sampled_at) }}</p>
    </section>
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
import { computed } from 'vue'
const props = defineProps<{ containerId: string }>()
const remote = useRemoteData<InstanceMetrics | null>(
  async () => (await monitoringApi.instance(props.containerId)).data || null,
  null,
)
useAutoRefresh(remote.refresh, 15000)
const scratch = computed(() => remote.data.value?.runtime?.ephemeral_storage)
const gib = (bytes: number | null | undefined) => bytes == null ? '—' : `${(bytes / 1024 ** 3).toFixed(2)} GiB`
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
.scratch-usage { padding: 16px 0; border-bottom: 1px solid #edf1f6; }
.scratch-usage h4 { margin: 0 0 12px; }
.scratch-usage .el-alert { margin-top: 12px; }
</style>
