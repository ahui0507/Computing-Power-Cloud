<template>
  <PageHeader
    title="操作审计"
    eyebrow="ADMINISTRATION"
    description="查询平台真实操作记录，按日期和操作类型筛选。"
    ><el-button @click="exportPage" :disabled="!remote.data.value.items.length"
      ><el-icon><Download /></el-icon>导出当前页</el-button
    ></PageHeader
  >
  <section class="panel">
    <div class="toolbar">
      <div class="toolbar-filters">
        <el-date-picker
          v-model="range"
          type="daterange"
          value-format="YYYY-MM-DD"
          start-placeholder="开始日期"
          end-placeholder="结束日期"
        /><el-input
          v-model="action"
          clearable
          placeholder="筛选操作名称"
          aria-label="筛选操作"
        />
      </div>
      <el-button type="primary" @click="search">查询</el-button>
    </div>
    <AsyncState
      :loading="remote.loading.value"
      :error="remote.error.value"
      :empty="!remote.data.value.items.length"
      empty-text="暂无符合条件的真实操作记录"
      @retry="remote.refresh"
      ><el-table
        :data="remote.data.value.items"
        v-loading="remote.loading.value"
        ><el-table-column prop="id" label="编号" width="85" /><el-table-column
          prop="user_id"
          label="用户"
          width="85"
        /><el-table-column
          prop="action"
          label="操作"
          min-width="130"
        /><el-table-column
          prop="resource"
          label="关联资源"
          min-width="230"
        /><el-table-column label="时间" width="180"
          ><template #default="{ row }">{{
            formatTime(row.timestamp)
          }}</template></el-table-column
        ><el-table-column label="结果" width="100"
          ><template #default="{ row }"
            ><el-tag :type="row.result === 'success' ? 'success' : 'danger'">{{
              row.result === 'success' ? '成功' : '失败'
            }}</el-tag></template
          ></el-table-column
        ></el-table
      ></AsyncState
    ><el-pagination
      v-if="remote.data.value.total"
      v-model:current-page="page"
      :total="remote.data.value.total"
      :page-size="20"
      layout="total,prev,pager,next"
      @current-change="remote.refresh"
    />
  </section>
</template>
<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { consoleApi, type AuditEntry } from '@/api/console'
import { useRemoteData } from '@/composables/useRemoteData'
import { downloadCsv } from '@/utils/export'
import { formatTime } from '@/utils/format'
import PageHeader from '@/components/PageHeader.vue'
import AsyncState from '@/components/AsyncState.vue'
const range = ref<[string, string]>(),
  action = ref(''),
  page = ref(1)
const remote = useRemoteData<{ items: AuditEntry[]; total: number }>(
  async () =>
    (
      await consoleApi.audit({
        page: page.value,
        page_size: 20,
        start: range.value?.[0] || '',
        end: range.value?.[1] || '',
        action: action.value,
      })
    ).data || { items: [], total: 0 },
  { items: [], total: 0 },
)
onMounted(() => {
  void remote.refresh()
})
function search() {
  page.value = 1
  void remote.refresh()
}
function exportPage() {
  downloadCsv(
    '操作审计当前页.csv',
    ['编号', '用户', '操作', '资源', '时间', '结果'],
    remote.data.value.items.map((row) => [
      row.id,
      row.user_id,
      row.action,
      row.resource,
      formatTime(row.timestamp),
      row.result,
    ]),
  )
}
</script>
