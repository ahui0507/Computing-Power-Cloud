<template>
  <PageHeader
    title="资源池管理"
    eyebrow="ADMINISTRATION"
    description="按 GPU 型号与节点组织可出租的算力。"
    ><el-button @click="refresh">刷新</el-button
    ><el-button type="primary" @click="open = true"
      ><el-icon><Plus /></el-icon>创建资源池</el-button
    ></PageHeader
  >
  <section class="panel">
    <AsyncState
      :loading="resources.poolsLoading"
      :error="resources.poolsError || nodes.error.value"
      :empty="!resources.pools.length"
      empty-text="暂无资源池，可以选择节点创建"
      @retry="refresh"
      ><el-table :data="resources.pools"
        ><el-table-column
          prop="name"
          label="资源池名称"
          min-width="220"
        /><el-table-column
          prop="gpu_type"
          label="GPU 型号"
          min-width="130"
        /><el-table-column
          prop="total_gpus"
          label="总 GPU"
          width="120"
        /><el-table-column
          prop="free_gpus"
          label="可申请"
          width="120"
        /><el-table-column label="操作" width="120"
          ><template #default="{ row }"
            ><el-button link type="danger" @click="remove(row)"
              >删除资源池</el-button
            ></template
          ></el-table-column
        ></el-table
      ></AsyncState
    >
  </section>
  <el-dialog v-model="open" title="创建资源池" width="520px"
    ><el-form ref="formRef" :model="form" :rules="rules" label-position="top"
      ><el-form-item label="资源池名称" prop="name"
        ><el-input v-model="form.name" maxlength="100" /></el-form-item
      ><el-form-item label="GPU 型号" prop="gpu_type"
        ><el-select
          v-model="form.gpu_type"
          style="width: 100%"
          placeholder="选择型号"
          ><el-option
            v-for="item in types.data.value"
            :key="item.code"
            :value="item.code"
            :label="`${item.name} · ${item.code}`" /></el-select></el-form-item
      ><el-form-item label="包含节点" prop="node_ids"
        ><el-select
          v-model="form.node_ids"
          multiple
          style="width: 100%"
          placeholder="选择节点"
          ><el-option
            v-for="item in nodes.data.value"
            :key="item.node_id"
            :value="item.node_id"
            :label="`${item.name} (${item.ip})`" /></el-select></el-form-item></el-form
    ><template #footer
      ><el-button @click="open = false">取消</el-button
      ><el-button type="primary" :loading="saving" @click="save"
        >创建资源池</el-button
      ></template
    ></el-dialog
  >
  <div class="hint-box section-gap">
    删除资源池不会删除节点或
    GPU。存在未结束实例的资源池不能删除；历史订单会继续保留。
  </div>
</template>
<script setup lang="ts">
import { ref, reactive, onMounted } from 'vue'
import { ElMessage, ElMessageBox, type FormInstance } from 'element-plus'
import { adminApi, clusterApi } from '@/api'
import { consoleApi } from '@/api/console'
import { useResourceStore } from '@/stores/resource'
import { useRemoteData } from '@/composables/useRemoteData'
import { reportError } from '@/utils/feedback'
import type { Node, ResourcePool } from '@/types'
import PageHeader from '@/components/PageHeader.vue'
import AsyncState from '@/components/AsyncState.vue'
const resources = useResourceStore(),
  open = ref(false),
  saving = ref(false),
  formRef = ref<FormInstance>()
const nodes = useRemoteData<Node[]>(
  async () => (await clusterApi.getNodes()).data || [],
  [],
)
const types = useRemoteData<
  { code: string; name: string; memory_mb: number }[]
>(async () => (await adminApi.getGpuTypes()).data || [], [])
const form = reactive({ name: '', gpu_type: '', node_ids: [] as number[] })
const rules = {
  name: [
    {
      required: true,
      whitespace: true,
      message: '请输入资源池名称',
      trigger: 'blur',
    },
  ],
  gpu_type: [{ required: true, message: '请选择GPU型号', trigger: 'change' }],
  node_ids: [
    {
      type: 'array' as const,
      min: 1,
      required: true,
      message: '至少选择一个节点',
      trigger: 'change',
    },
  ],
}
async function refresh() {
  await Promise.allSettled([
    resources.fetchPools(),
    nodes.refresh(),
    types.refresh(),
  ])
}
onMounted(() => {
  void refresh()
})
async function save() {
  if (saving.value || !formRef.value) return
  saving.value = true
  try {
    if (!(await formRef.value.validate().catch(() => false))) return
    await adminApi.createPool(form)
    open.value = false
    ElMessage.success('资源池已创建')
    formRef.value.resetFields()
    await refresh()
  } catch (error) {
    reportError(error)
  } finally {
    saving.value = false
  }
}
async function remove(row: ResourcePool) {
  try {
    await ElMessageBox.confirm(
      `删除资源池“${row.name}”？节点和GPU会保留。`,
      '删除资源池',
      {
        confirmButtonText: '删除资源池',
        cancelButtonText: '取消',
        type: 'warning',
      },
    )
    await consoleApi.deletePool(row.pool_id)
    await resources.fetchPools()
    ElMessage.success('资源池已删除')
  } catch (error) {
    reportError(error)
  }
}
</script>
