<template>
  <AsyncState
    :loading="loading"
    :error="error"
    :empty="!history.items.length"
    empty-text="暂无管理员增加余额记录"
    @retry="$emit('refresh')"
  >
    <el-table :data="history.items">
      <el-table-column label="到账时间" min-width="180">
        <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
      </el-table-column>
      <el-table-column label="增加金额" width="150">
        <template #default="{ row }"
          ><strong class="mono">+¥{{ row.amount.toFixed(4) }}</strong></template
        >
      </el-table-column>
      <el-table-column label="入账后余额" width="150">
        <template #default="{ row }"
          ><span class="mono"
            >¥{{ row.balance_after.toFixed(4) }}</span
          ></template
        >
      </el-table-column>
      <el-table-column prop="reason" label="说明" min-width="220" show-overflow-tooltip />
    </el-table>
  </AsyncState>
  <el-pagination
    v-if="history.total > 10"
    :current-page="page"
    :total="history.total"
    :page-size="10"
    layout="total,prev,pager,next"
    @current-change="$emit('page', $event)"
  />
</template>
<script setup lang="ts">
import type { CreditHistory } from '@/api/balanceCredits'
import { formatTime } from '@/utils/format'
import AsyncState from './AsyncState.vue'
defineProps<{
  history: CreditHistory
  page: number
  loading: boolean
  error: string
}>()
defineEmits<{ refresh: []; page: [value: number] }>()
</script>
