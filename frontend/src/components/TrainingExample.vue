<template>
  <el-button @click="openDialog">创建训练示例</el-button>
  <el-dialog v-model="open" :title="dialogTitle" width="min(660px, 92vw)" top="5vh" class="training-example-dialog">
    <template v-if="!example">
      <p>请选择与实例镜像一致的框架。示例会保存到你的个人存储。</p>
      <el-radio-group v-model="framework" aria-label="训练框架">
        <el-radio-button value="pytorch">PyTorch</el-radio-button>
        <el-radio-button value="tensorflow">TensorFlow</el-radio-button>
      </el-radio-group>
      <p class="caption section-gap">
        支持单卡、多卡训练及 checkpoint 恢复。示例使用合成数据，无需下载数据集。
      </p>
    </template>
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
        多卡训练：选择当前实例已申请的 GPU 数量
      </p>
      <el-input-number v-model="gpuCount" :min="2" :max="64" :step="1" step-strictly aria-label="多卡 GPU 数量" />
      <pre class="command">{{ multiCommand }}</pre>
      <el-button link type="primary" @click="copyText(multiCommand)"
        >复制命令</el-button
      >
      <p class="caption section-gap">
        {{ checkpointDescription }}每轮保存模型、优化器及训练进度。epochs 表示目标总轮数，恢复后从已完成轮数继续。
      </p>
      <template v-if="example.resume_command">
        <p class="caption">单卡恢复</p>
        <pre class="command">{{ example.resume_command }}</pre>
        <el-button link type="primary" @click="copyText(example.resume_command)">复制单卡恢复命令</el-button>
      </template>
      <template v-if="multiResumeCommand">
        <p class="caption section-gap">多卡恢复：GPU 数量与上方选择一致</p>
        <pre class="command">{{ multiResumeCommand }}</pre>
        <el-button link type="primary" @click="copyText(multiResumeCommand)">复制多卡恢复命令</el-button>
      </template>
      <p class="caption">示例使用合成数据验证流程，多卡速度取决于模型规模与通信开销。</p>
    </template>
    <template #footer>
      <el-button v-if="!example" @click="open = false">取消</el-button>
      <el-button v-if="!example" type="primary" :loading="saving" @click="create">创建并保存</el-button>
      <el-button v-else type="primary" @click="open = false">知道了</el-button>
    </template>
  </el-dialog>
</template>
<script setup lang="ts">
import { computed, ref } from 'vue'
import { storageApi, type TrainingExampleResult, type TrainingFramework } from '@/api/storage'
import { copyText, reportError } from '@/utils/feedback'
const emit = defineEmits<{ created: [] }>()
const saving = ref(false),
  open = ref(false),
  example = ref<TrainingExampleResult | null>(null)
const framework = ref<TrainingFramework>('pytorch')
const gpuCount = ref(2)
const frameworkName = computed(() =>
  (example.value?.framework || framework.value) === 'tensorflow' ? 'TensorFlow' : 'PyTorch',
)
const dialogTitle = computed(() => example.value ? `${frameworkName.value} 训练示例已保存` : '创建训练示例')
const checkpointDescription = computed(() => example.value?.framework === 'tensorflow'
  ? 'checkpoint 保存到示例目录下的 checkpoint-tensorflow 文件夹。'
  : 'checkpoint 保存到示例目录下的 checkpoint.pt。')
const replaceGpuCount = (command?: string) => (command || '').split('<申请的GPU数量>').join(String(gpuCount.value || 2))
const multiCommand = computed(() => replaceGpuCount(example.value?.multi_command))
const multiResumeCommand = computed(() => replaceGpuCount(example.value?.multi_resume_command))
function openDialog() {
  if (saving.value) return
  example.value = null
  open.value = true
}
async function create() {
  if (saving.value) return
  saving.value = true
  try {
    example.value = (await storageApi.trainingExample(framework.value)).data || null
    emit('created')
  } catch (error) {
    reportError(error)
  } finally {
    saving.value = false
  }
}
</script>
<style scoped>
:global(.training-example-dialog .el-dialog__body) {
  max-height: 70vh;
  overflow-y: auto;
}
.command {
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  background: #f3f6fb;
  padding: 14px;
  border-radius: 8px;
}
</style>
