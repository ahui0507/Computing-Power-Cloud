<template>
  <div class="panel">
    <div class="toolbar">
      <div class="toolbar-filters">
        <el-input
          v-model="search"
          placeholder="搜索实例名或镜像"
          clearable
          aria-label="搜索实例"
          ><template #prefix
            ><el-icon><Search /></el-icon></template></el-input
        ><el-select
          v-model="status"
          placeholder="全部状态"
          clearable
          aria-label="筛选实例状态"
          ><el-option
            v-for="value in statuses"
            :key="value"
            :value="value"
            :label="getStatusText(value)"
        /></el-select>
      </div>
      <span class="caption"
        >共 {{ filtered.length }} 个{{ historical ? '历史订单' : '实例' }}</span
      >
    </div>
    <AsyncState
      :loading="loading"
      :error="loadError"
      :empty="instances.length === 0 && !search && !status"
      :empty-text="
        historical
          ? '暂无历史订单，已结束的实例会出现在这里'
          : '暂无使用中的实例，创建一台开始工作吧'
      "
      @retry="refresh"
      ><template #empty
        ><el-button
          v-if="!historical"
          type="primary"
          @click="router.push('/compute/pools')"
          >创建实例</el-button
        ></template
      >
      <el-table
        :data="pageRows"
        v-loading="loading"
        empty-text="没有符合条件的实例"
        @row-click="showDetail"
      >
        <el-table-column label="实例 / 镜像" min-width="230"
          ><template #default="{ row }"
            ><el-button
              link
              type="primary"
              class="mono"
              @click.stop="showDetail(row)"
              >{{ instanceName(row) }}</el-button
            >
            <div class="table-secondary" :title="row.image">
              {{ row.image }}
            </div></template
          ></el-table-column
        >
        <el-table-column
          v-if="historical && auth.isAdmin"
          prop="user_email"
          label="所属用户"
          min-width="210"
        />
        <el-table-column label="状态" width="108"
          ><template #default="{ row }"
            ><StatusTag :status="row.status" /></template
        ></el-table-column>
        <el-table-column label="算力配置" min-width="175"
          ><template #default="{ row }"
            ><span class="table-primary">{{ row.gpus }} × GPU</span>
            <div class="table-secondary">
              CPU / 内存：{{ instanceShareText(row) }}
            </div><div v-if="row.ephemeral_storage_gib" class="table-secondary">临时磁盘：{{ row.ephemeral_storage_gib }} GiB</div></template
          ></el-table-column
        >
        <el-table-column
          :label="historical ? '结束时间' : '运行时长'"
          min-width="155"
          ><template #default="{ row }"
            ><span class="caption">{{
              historical
                ? row.end_time
                  ? formatTime(row.end_time)
                  : '—'
                : durationText(row.start_time, row.end_time, now)
            }}</span></template
          ></el-table-column
        >
        <el-table-column
          :label="historical ? '订单费用' : '计费方式'"
          min-width="155"
          ><template #default="{ row }"
            ><span class="mono">{{
              historical ? settled(row) : rate(row)
            }}</span>
            <div
              v-if="!historical && row.package_expires_at"
              class="table-secondary"
            >
              到期 {{ formatTime(row.package_expires_at) }}
            </div><div v-if="!historical && row.scheduled_release_at" class="table-secondary">自动释放 {{ formatTime(row.scheduled_release_at) }}</div></template
          ></el-table-column
        >
        <el-table-column
          label="操作"
          :width="historical ? 170 : 320"
          fixed="right"
          ><template #default="{ row }"
            ><div class="table-actions" @click.stop>
              <template v-if="!historical"
                ><el-button
                  link
                  type="primary"
                  :disabled="row.status !== 'running' || !row.jupyter_url"
                  @click="openJupyter(row)"
                  >JupyterLab</el-button
                ><el-button
                  link
                  type="primary"
                  :disabled="row.status !== 'running'"
                  @click="router.push(`/terminal/${row.container_id}`)"
                  >终端</el-button
                ><el-button
                  link
                  type="primary"
                  :disabled="row.status !== 'running' || !row.ssh_enabled"
                  @click="connectSSH(row)"
                  >SSH</el-button
                ><el-button
                  link
                  type="primary"
                  :disabled="row.status !== 'running'"
                  @click="saveImage(row)"
                  >保存镜像</el-button
                ><el-button link type="primary" :disabled="!['pending','running'].includes(row.status)" @click="schedule(row)">定时释放</el-button
                ><el-button
                  link
                  type="danger"
                  :disabled="
                    row.status === 'releasing' ||
                    store.releasingIds.includes(row.container_id)
                  "
                  @click="release(row)"
                  >{{
                    row.status === 'releasing' ? '释放中' : '释放'
                  }}</el-button
                ></template
              ><template v-else
                ><el-button
                  v-if="
                    !row.user_email || row.user_email === auth.userInfo?.email
                  "
                  link
                  type="primary"
                  @click="reapply(row)"
                  >再次申请</el-button
                ><el-button link @click="showDetail(row)"
                  >详情</el-button
                ></template
              >
            </div></template
          ></el-table-column
        >
      </el-table>
      <el-pagination
        v-if="filtered.length > pageSize"
        v-model:current-page="page"
        :page-size="pageSize"
        :total="filtered.length"
        layout="prev, pager, next"
      />
    </AsyncState>
  </div>
  <el-drawer v-model="drawerOpen" title="实例详情" size="520px">
    <template v-if="selected"
      ><div class="panel-heading">
        <span class="mono">{{ instanceName(selected) }}</span
        ><StatusTag :status="selected.status" />
      </div>
      <div class="detail-grid">
        <div class="detail-item">
          <label>镜像</label>
          <div>{{ selected.image }}</div>
        </div>
        <div class="detail-item">
          <label>GPU 数量</label>
          <div>{{ selected.gpus }} 张</div>
        </div>
        <div class="detail-item">
          <label>CPU 份额</label>
          <div>{{ instanceShareText(selected) }}</div>
        </div>
        <div class="detail-item">
          <label>内存份额</label>
          <div>{{ instanceShareText(selected) }}</div>
        </div>
        <div class="detail-item">
          <label>创建时间</label>
          <div>
            {{ selected.created_at ? formatTime(selected.created_at) : '—' }}
          </div>
        </div>
        <div class="detail-item">
          <label>开始时间</label>
          <div>
            {{
              selected.start_time ? formatTime(selected.start_time) : '尚未启动'
            }}
          </div>
        </div>
        <div class="detail-item">
          <label>运行时长</label>
          <div>
            {{ durationText(selected.start_time, selected.end_time, now) }}
          </div>
        </div>
        <div class="detail-item">
          <label>{{
            historical
              ? '结算费用'
              : isPackage(selected)
                ? '已预付金额'
                : '已运行预估费用'
          }}</label>
          <div class="mono">
            {{ historical ? settled(selected) : estimate(selected) }}
          </div>
        </div>
        <div class="detail-item">
          <label>持久文件目录</label>
          <div>
            {{ selected.persistent_path || '/workspace' }}
            <el-button link type="primary" @click="router.push('/storage')"
              >管理文件</el-button
            >
          </div>
        </div>
        <div class="detail-item">
          <label>计费方式</label>
          <div>
            {{ billingLabel(selected)
            }}<span v-if="selected.package_refunded">
              · 创建失败，已退回余额</span
            >
          </div>
        </div>
        <div v-if="selected.package_expires_at" class="detail-item">
          <label>包时截止时间</label>
          <div>{{ formatTime(selected.package_expires_at) }}</div>
        </div>
        <div v-if="selected.user_email" class="detail-item">
          <label>所属用户</label>
          <div>{{ selected.user_email }}</div>
        </div>
        <div class="detail-item">
          <label>内部标识</label
          ><el-button
            link
            type="primary"
            @click="copyText(selected.container_id)"
            >复制实例 ID</el-button
          >
        </div>
      </div>
      <InstanceStorage :instance="selected" />
      <InstanceTelemetry
        v-if="selected.status === 'running'"
        :key="selected.container_id"
        :container-id="selected.container_id"
      />
      <InstanceDiagnostics
        v-if="selected.status === 'running'"
        :key="`diagnostics-${selected.container_id}`"
        :container-id="selected.container_id"
      />
      <el-alert
        v-if="selected.status_message"
        :title="selected.status_message"
        :type="selected.status === 'failed' ? 'error' : 'info'"
        :closable="false"
        class="section-gap"
      />
      <div class="hint-box section-gap">
        按时实例按实际用量结算；包日、包周已预付，到期自动释放，提前释放不退费。释放前请确认成果已写入个人存储，或完成个人镜像保存。
      </div>
      <div class="table-actions section-gap">
        <el-button
          v-if="selected.status === 'running'"
          type="primary"
          @click="openJupyter(selected)"
          >打开 JupyterLab</el-button
        ><el-button
          @click="
            router.push({
              path: '/billing',
              query: { instance: selected.container_id },
            })
          "
          >查看账单</el-button
        ><el-button
          v-if="
            historical &&
            (!selected.user_email ||
              selected.user_email === auth.userInfo?.email)
          "
          @click="reapply(selected)"
          >再次申请</el-button
        >
      </div></template
    >
  </el-drawer>
  <SSHDialog v-model="sshOpen" :container-id="actionId" />
  <SaveImageDialog v-model="saveOpen" :container-id="actionId" />
  <ReleaseScheduleDialog v-model="scheduleOpen" :instance="scheduleInstance" />
  <ReleaseInstanceDialog v-model="releaseOpen" :instance="releaseInstance" @released="afterRelease" />
</template>
<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useResourceStore } from '@/stores/resource'
import { useBillingStore } from '@/stores/billing'
import { useAuthStore } from '@/stores/auth'
import { useClock } from '@/composables/useClock'
import {
  durationText,
  instanceRate,
  instanceEstimate,
  instanceName,
  isPackage,
  billingLabel,
} from '@/utils/instance'
import { formatTime, getStatusText } from '@/utils/format'
import { instanceShareText } from '@/utils/compute'
import { copyText } from '@/utils/feedback'
import type { Container } from '@/types'
import AsyncState from './AsyncState.vue'
import StatusTag from './StatusTag.vue'
import InstanceTelemetry from './InstanceTelemetry.vue'
import InstanceStorage from './InstanceStorage.vue'
import InstanceDiagnostics from './InstanceDiagnostics.vue'
import SSHDialog from './SSHDialog.vue'
import SaveImageDialog from './SaveImageDialog.vue'
import ReleaseScheduleDialog from './ReleaseScheduleDialog.vue'
import ReleaseInstanceDialog from './ReleaseInstanceDialog.vue'
const releaseOpen = ref(false), releaseInstance = ref<Container>()
const scheduleOpen = ref(false), scheduleInstance = ref<Container>()
function schedule(row: Container) { scheduleInstance.value = row; scheduleOpen.value = true }
const sshOpen = ref(false),
  saveOpen = ref(false),
  actionId = ref('')
function connectSSH(row: Container) {
  actionId.value = row.container_id
  sshOpen.value = true
}
function saveImage(row: Container) {
  actionId.value = row.container_id
  saveOpen.value = true
}
import { useBudgetStore } from '@/stores/budget'
const props = defineProps<{ historical?: boolean }>()
const store = useResourceStore(),
  billing = useBillingStore(),
  auth = useAuthStore()
const router = useRouter(),
  route = useRoute(),
  now = useClock()
const search = ref(''),
  status = ref(''),
  page = ref(1),
  pageSize = 10
const drawerOpen = ref(false),
  selectedId = ref('')
const selected = computed(() =>
  (props.historical ? store.historicalInstances : store.myContainers).find(
    (item) => item.container_id === selectedId.value,
  ),
)
const loading = computed(() =>
  props.historical ? store.historyLoading : store.instancesLoading,
)
const loadError = computed(() =>
  props.historical ? store.historyError : store.instancesError,
)
const instances = computed(() =>
  props.historical ? store.historicalInstances : store.activeInstances,
)
const statuses = computed(() =>
  props.historical
    ? ['released', 'stopped', 'failed']
    : ['pending', 'running', 'releasing'],
)
const filtered = computed(() =>
  instances.value.filter(
    (item) =>
      (!status.value || item.status === status.value) &&
      `${instanceName(item)} ${item.container_id} ${item.image} ${item.user_email || ''}`
        .toLowerCase()
        .includes(search.value.toLowerCase()),
  ),
)
const pageRows = computed(() =>
  filtered.value.slice((page.value - 1) * pageSize, page.value * pageSize),
)
watch([search, status], () => {
  page.value = 1
})
watch(filtered, () => {
  page.value = Math.min(
    page.value,
    Math.max(1, Math.ceil(filtered.value.length / pageSize)),
  )
})
watch(
  [() => route.query.id, () => instances.value.length],
  () => {
    if (
      route.query.id &&
      instances.value.some((item) => item.container_id === route.query.id)
    ) {
      selectedId.value = String(route.query.id)
      drawerOpen.value = true
    }
  },
  { immediate: true },
)
const refresh = () =>
  (props.historical ? store.fetchHistory() : store.fetchMyResources()).catch(
    () => {},
  )
function showDetail(row: Container) {
  selectedId.value = row.container_id
  drawerOpen.value = true
}
function rate(row: Container) {
  if (isPackage(row))
    return `${billingLabel(row)} ¥${(row.package_amount || 0).toFixed(4)}`
  const value = instanceRate(row)
  return value == null ? '—' : `¥${value.toFixed(4)}`
}
function estimate(row: Container) {
  if (isPackage(row))
    return `¥${(row.package_refunded ? 0 : row.package_amount || 0).toFixed(4)}`
  const value = instanceEstimate(row, now.value)
  return value == null ? '—' : `约 ¥${value.toFixed(4)}`
}
function settled(row: Container) {
  if (row.settled_amount != null) return `¥${row.settled_amount.toFixed(4)}`
  const record = billing.records.find(
    (item) => item.container_id === row.container_id,
  )
  return record
    ? `¥${record.amount.toFixed(4)}`
    : billing.recordsError
      ? '加载失败'
      : '未结算'
}
function openJupyter(row: Container) {
  if (row.jupyter_url)
    window.open(row.jupyter_url, '_blank', 'noopener,noreferrer')
}
function reapply(row: Container) {
  void router.push({
    path: '/compute/apply',
    query: {
      pool_id: row.pool_id || undefined,
      image_id: row.image_id || undefined,
      gpu_count: row.gpus,
      billing_mode:
        row.billing_mode === 'day' || row.billing_mode === 'week'
          ? row.billing_mode
          : 'on_demand',
    },
  })
}
function release(row: Container) {
  releaseInstance.value = row
  releaseOpen.value = true
}
async function afterRelease() {
  await Promise.allSettled([auth.fetchUserInfo(), billing.fetchRecords(), useBudgetStore().refresh()])
}
</script>
