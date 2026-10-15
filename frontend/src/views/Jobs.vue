<template>
  <PageHeader
    title="运行任务"
    eyebrow="BACKGROUND JOBS"
    description="在运行中的实例上执行命令，离开页面后继续运行，日志保存在个人工作目录。"
    ><el-button @click="refresh"
      ><el-icon><Refresh /></el-icon>刷新</el-button
    ><el-button
      type="primary"
      :disabled="!running.length"
      @click="showSubmit = true"
      ><el-icon><VideoPlay /></el-icon>新建任务</el-button
    ></PageHeader
  ><el-alert
    v-if="!running.length"
    title="先创建一个运行中的实例，再提交任务。"
    type="info"
    :closable="false"
    style="margin-bottom: 20px"
    ><el-button link type="primary" @click="router.push('/compute/pools')"
      >前往资源市场</el-button
    ></el-alert
  >
  <section class="panel">
    <div class="toolbar">
      <el-radio-group v-model="tab"
        ><el-radio-button label="active">运行中</el-radio-button
        ><el-radio-button label="history">已结束</el-radio-button
        ><el-radio-button label="all">全部任务</el-radio-button></el-radio-group
      ><el-input
        v-model="search"
        clearable
        placeholder="搜索名称或实例"
        aria-label="搜索任务"
      />
    </div>
    <AsyncState
      :loading="jobs.loading.value"
      :error="jobs.error.value"
      :empty="filtered.length === 0"
      empty-text="暂无符合条件的任务"
      @retry="refresh"
      ><el-table :data="filtered"
        ><el-table-column label="任务" min-width="200"
          ><template #default="{ row }"
            ><span class="table-primary">{{ row.name }}</span>
            <p class="table-secondary mono">
              {{ row.instance_name || row.container_id }}
            </p></template
          ></el-table-column
        ><el-table-column label="状态" width="110"
          ><template #default="{ row }"
            ><StatusTag :status="row.status" /></template></el-table-column
        ><el-table-column label="创建时间" width="175"
          ><template #default="{ row }"
            ><span class="caption">{{
              formatTime(row.created_at)
            }}</span></template
          ></el-table-column
        ><el-table-column label="退出码" width="90"
          ><template #default="{ row }">{{
            row.exit_code ?? '—'
          }}</template></el-table-column
        ><el-table-column label="操作" width="180"
          ><template #default="{ row }"
            ><div class="table-actions">
              <el-button link type="primary" @click="showLogs(row)"
                >日志与详情</el-button
              ><el-button
                v-if="['pending', 'running'].includes(row.status)"
                link
                type="danger"
                @click="cancel(row)"
                >取消</el-button
              >
            </div></template
          ></el-table-column
        ></el-table
      ></AsyncState
    >
  </section>
  <div class="hint-box section-gap">
    任务会使用所选实例已有的 Python
    和依赖环境。释放实例会终止其中的任务；程序输出会保存在
    /data/.cloud-jobs/，可在我的文件中下载。取消任务不会释放实例，实例会继续计费。
  </div>
  <el-dialog v-model="showSubmit" title="新建后台任务" width="600px"
    ><el-form
      ref="formRef"
      :model="form"
      :rules="rules"
      label-position="top"
      :disabled="submitting"
      ><el-form-item label="任务名称" prop="name"
        ><el-input
          v-model="form.name"
          placeholder="例如 Python 训练"
          maxlength="128" /></el-form-item
      ><el-form-item label="运行实例" prop="container_id"
        ><el-select
          v-model="form.container_id"
          placeholder="选择运行中的实例"
          style="width: 100%"
          ><el-option
            v-for="item in running"
            :key="item.container_id"
            :label="`${item.instance_name || item.container_id} · ${item.gpus} GPU`"
            :value="item.container_id" /></el-select></el-form-item
      ><el-form-item label="执行命令" prop="command"
        ><el-input
          v-model="form.command"
          type="textarea"
          :rows="5"
          placeholder="例如 python hello.py"
          maxlength="8192"
      /></el-form-item>
      <p class="caption">
        命令在临时 /workspace 目录执行。个人存储脚本可用 python -u /data/脚本.py
        运行；需要保留的输出请明确写入 /data。长任务建议使用 python -u
        及时输出日志。
      </p></el-form
    ><template #footer
      ><el-button @click="showSubmit = false">取消</el-button
      ><el-button type="primary" :loading="submitting" @click="submit"
        >提交任务</el-button
      ></template
    ></el-dialog
  ><el-drawer v-model="logsOpen" title="任务详情与日志" size="650px"
    ><template v-if="selected"
      ><div class="panel-heading">
        <strong>{{ selected.name }}</strong
        ><StatusTag :status="selected.status" />
      </div>
      <p class="mono muted">
        {{ selected.instance_name || selected.container_id }}
      </p>
      <div class="hint-box section-gap">
        <span class="mono">{{ selected.command }}</span>
      </div>
      <div class="panel-heading section-gap">
        <span class="caption">最近 128 KB 输出 · 每 5 秒刷新</span
        ><el-button link type="primary" @click="copyText(logs.data.value)"
          >复制日志</el-button
        >
      </div>
      <p v-if="logs.error.value" class="request-error">
        {{ logs.error.value }}
      </p>
      <pre class="log-output">{{ logs.data.value || '等待程序输出…' }}</pre>
    </template></el-drawer
  >
</template>
<script setup lang="ts">
import { ref, reactive, computed, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox, type FormInstance } from 'element-plus'
import { consoleApi, type ConsoleJob } from '@/api/console'
import { useResourceStore } from '@/stores/resource'
import { useRemoteData } from '@/composables/useRemoteData'
import { useAutoRefresh } from '@/composables/useAutoRefresh'
import { formatTime } from '@/utils/format'
import { reportError, copyText } from '@/utils/feedback'
import PageHeader from '@/components/PageHeader.vue'
import AsyncState from '@/components/AsyncState.vue'
import StatusTag from '@/components/StatusTag.vue'
const router = useRouter(),
  resources = useResourceStore(),
  jobs = useRemoteData<ConsoleJob[]>(
    async () => (await consoleApi.jobs()).data || [],
    [],
  )
const running = computed(() =>
  resources.activeInstances.filter((item) => item.status === 'running'),
)
const showSubmit = ref(false),
  submitting = ref(false),
  logsOpen = ref(false),
  selectedId = ref(''),
  tab = ref('active'),
  search = ref(''),
  formRef = ref<FormInstance>()
const form = reactive({ name: '', container_id: '', command: '' })
const selected = computed(() =>
  jobs.data.value.find((item) => item.job_id === selectedId.value),
)
const filtered = computed(() =>
  jobs.data.value.filter(
    (item) =>
      (tab.value === 'all' ||
        (['pending', 'running'].includes(item.status)
          ? tab.value === 'active'
          : tab.value === 'history')) &&
      `${item.name} ${item.container_id}`
        .toLowerCase()
        .includes(search.value.toLowerCase()),
  ),
)
const logs = useRemoteData<string>(
  async () => (await consoleApi.jobLogs(selectedId.value)).data?.logs || '',
  '',
)
const rules = {
  name: [
    {
      required: true,
      whitespace: true,
      message: '请输入任务名称',
      trigger: 'blur',
    },
  ],
  container_id: [
    { required: true, message: '请选择运行实例', trigger: 'change' },
  ],
  command: [
    {
      required: true,
      whitespace: true,
      message: '请输入执行命令',
      trigger: 'blur',
    },
  ],
}
let requestId = ''
watch(
  () => [form.name, form.command, form.container_id],
  () => {
    requestId = ''
  },
)
watch(showSubmit, (value) => {
  if (value && !form.container_id)
    form.container_id = running.value[0]?.container_id || ''
})
const refresh = useAutoRefresh(async () => {
  await Promise.allSettled([jobs.refresh(), resources.fetchMyResources()])
  if (logsOpen.value && selectedId.value) await logs.refresh()
}, 5000)
function showLogs(row: ConsoleJob) {
  selectedId.value = row.job_id
  logsOpen.value = true
  void logs.refresh()
}
async function submit() {
  if (submitting.value || !formRef.value) return
  submitting.value = true
  try {
    if (!(await formRef.value.validate().catch(() => false))) return
    if (!requestId)
      requestId = Array.from(
        crypto.getRandomValues(new Uint8Array(16)),
        (value) => value.toString(16).padStart(2, '0'),
      ).join('')
    await consoleApi.submitJob({ ...form, job_id: requestId })
    ElMessage.success('任务已提交')
    tab.value = 'all'
    showSubmit.value = false
    requestId = ''
    await jobs.refresh()
    form.name = ''
    form.command = ''
  } catch (error) {
    reportError(error)
    await jobs.refresh()
  } finally {
    submitting.value = false
  }
}
async function cancel(row: ConsoleJob) {
  try {
    await ElMessageBox.confirm(
      '终止此任务及其子进程？实例仍会继续运行和计费。',
      '取消任务',
      {
        confirmButtonText: '终止任务',
        cancelButtonText: '继续运行',
        type: 'warning',
      },
    )
    await consoleApi.cancelJob(row.job_id)
    await jobs.refresh()
    ElMessage.success('任务已取消')
  } catch (error) {
    reportError(error)
  }
}
</script>
