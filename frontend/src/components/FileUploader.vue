<template>
  <el-upload
    ref="upload"
    :http-request="requestUpload"
    :before-upload="beforeUpload"
    :on-progress="onProgress"
    :on-success="onSuccess"
    :on-error="onError"
    :on-exceed="onExceed"
    :limit="1"
    :show-file-list="true"
    :disabled="busy"
    drag
    ><el-icon style="font-size: 36px; color: #7d9bd0"><UploadFilled /></el-icon>
    <p style="font-size: 13px; color: #5d7293; margin: 12px 0">
      拖放文件至此，或<em style="color: #3568e8; font-style: normal"
        >点击选择文件</em
      >
    </p>
    <template #tip
      ><p class="caption">
        单个文件最大 {{ maxSize }} MB，上传到
        {{ folder ? `/data/${folder}` : '/data' }}。
      </p>
      <el-progress
        v-if="busy"
        :percentage="progress"
        :stroke-width="5"
        style="margin-top: 12px" /></template
  ></el-upload>
</template>
<script setup lang="ts">
import { ref } from 'vue'
import {
  ElMessage,
  type UploadInstance,
  type UploadRequestOptions,
  type UploadProgressEvent,
  type UploadRawFile,
} from 'element-plus'
import { storageApi } from '@/api'
import { reportError } from '@/utils/feedback'
const props = withDefaults(
  defineProps<{ folder?: string; maxSize?: number }>(),
  { folder: '', maxSize: 100 },
)
const emit = defineEmits<{ success: [] }>()
const busy = ref(false),
  progress = ref(0),
  upload = ref<UploadInstance>()
function beforeUpload(file: UploadRawFile) {
  if (file.size > props.maxSize * 1024 * 1024) {
    ElMessage.warning(`单个文件不能超过 ${props.maxSize} MB`)
    return false
  }
  busy.value = true
  progress.value = 0
  return true
}
function requestUpload(options: UploadRequestOptions) {
  return storageApi.upload(
    options.file,
    (value) => options.onProgress({ percent: value } as UploadProgressEvent),
    props.folder,
  )
}
function onProgress(event: { percent: number }) {
  progress.value = event.percent
}
function onSuccess() {
  busy.value = false
  progress.value = 100
  upload.value?.clearFiles()
  ElMessage.success('文件已上传')
  emit('success')
}
function onError(error: unknown) {
  busy.value = false
  upload.value?.clearFiles()
  reportError(error, '上传失败')
}
function onExceed() {
  ElMessage.warning('请等待当前文件上传完成')
}
</script>
