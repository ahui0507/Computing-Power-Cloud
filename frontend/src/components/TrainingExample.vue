<template>
  <el-button :loading="saving" @click="create">创建训练示例</el-button>
  <el-dialog v-model="open" title="训练示例已保存" width="620px">
    <template v-if="example">
      <p>
        文件已保存到 /data/{{ example.folder }}。在实例的 SSH 或 Jupyter
        终端执行以下命令。
      </p>
      <p class="caption">单卡训练</p>
      <pre class="command">{{ example.single_command }}</pre>
      <el-button link type="primary" @click="copyText(example.single_command)"
        >复制命令</el-button
      >
      <p class="caption section-gap">
        多卡训练：将数量替换为当前实例申请的 GPU 数量
      </p>
      <pre class="command">{{ example.multi_command }}</pre>
      <el-button link type="primary" @click="copyText(example.multi_command)"
        >复制命令</el-button
      >
      <p class="caption section-gap">
        示例使用合成数据演示 DDP 数据并行，并在该目录保存
        checkpoint.pt。它用于验证流程，多卡速度取决于模型规模与通信开销。
      </p>
    </template>
    <template #footer
      ><el-button type="primary" @click="open = false"
        >知道了</el-button
      ></template
    >
  </el-dialog>
</template>
<script setup lang="ts">
import { ref } from 'vue'
import { storageApi, type TrainingExampleResult } from '@/api/storage'
import { copyText, reportError } from '@/utils/feedback'
const emit = defineEmits<{ created: [] }>()
const saving = ref(false),
  open = ref(false),
  example = ref<TrainingExampleResult | null>(null)
async function create() {
  if (saving.value) return
  saving.value = true
  try {
    example.value = (await storageApi.trainingExample()).data || null
    open.value = true
    emit('created')
  } catch (error) {
    reportError(error)
  } finally {
    saving.value = false
  }
}
</script>
<style scoped>
.command {
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  background: #f3f6fb;
  padding: 14px;
  border-radius: 8px;
}
</style>
