<template>
  <section class="panel section-gap">
    <div class="panel-heading"><h2 class="panel-title">排队申请</h2><el-button @click="data.refresh">刷新</el-button></div>
    <p class="caption">排队期间不占卡、不计费；资源可用后自动申请，按分配时的价格、余额和配额校验。申请24小时后过期，以列表时间为准。按提交顺序尝试，暂不能满足的大申请可能被后续小申请超过。</p>
    <AsyncState :loading="data.loading.value" :error="data.error.value" :empty="!data.data.value.length" empty-text="暂无排队申请" @retry="data.refresh">
      <el-table :data="data.data.value">
        <el-table-column label="申请" width="110"><template #default="{ row }">{{ row.parameters.gpu_count }} 张 GPU</template></el-table-column>
        <el-table-column label="状态" width="110"><template #default="{ row }">{{ labels[row.status as QueueEntry['status']] }}</template></el-table-column>
        <el-table-column label="说明" prop="message" min-width="240" />
        <el-table-column label="排队截止" width="175"><template #default="{ row }">{{ formatTime(row.expires_at) }}</template></el-table-column>
        <el-table-column label="操作" width="140"><template #default="{ row }">
          <el-button v-if="row.status === 'waiting'" link type="danger" :loading="cancelling === row.id" @click="cancel(row.id)">取消排队</el-button>
          <el-button v-if="row.container_id" link type="primary" @click="router.push({path:'/compute/instances',query:{id:row.container_id}})">查看实例</el-button>
        </template></el-table-column>
      </el-table>
    </AsyncState>
  </section>
</template>
<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessageBox } from 'element-plus'
import { resourceApi, type QueueEntry } from '@/api/resource'
import { useRemoteData } from '@/composables/useRemoteData'
import { useAutoRefresh } from '@/composables/useAutoRefresh'
import { onSessionReset } from '@/utils/session'
import { formatTime } from '@/utils/format'
import { reportError } from '@/utils/feedback'
import AsyncState from './AsyncState.vue'
const router = useRouter(), cancelling = ref<number | null>(null)
const labels: Record<QueueEntry['status'], string> = {waiting:'等待资源',dispatching:'正在分配',started:'已登记实例',cancelled:'已取消',failed:'申请失败',expired:'已到期'}
const data = useRemoteData<QueueEntry[]>(async () => (await resourceApi.queue()).data || [], [])
onSessionReset(() => { data.data.value = [] })
useAutoRefresh(() => data.refresh(), 10000)
async function cancel(id: number) {
  if (cancelling.value !== null) return
  try {
    await ElMessageBox.confirm('取消此排队申请？', '取消排队', {confirmButtonText:'取消排队',cancelButtonText:'继续等待'})
    cancelling.value = id
    await resourceApi.cancelQueue(id)
    await data.refresh()
  } catch(error) {reportError(error)} finally {cancelling.value = null}
}
</script>
