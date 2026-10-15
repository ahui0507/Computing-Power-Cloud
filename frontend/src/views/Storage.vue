<template>
  <PageHeader
    title="我的文件"
    eyebrow="PERSISTENT WORKSPACE"
    description="控制节点上的个人存储，供同一账号的实例共享；只有主动保存到这里的文件长期保留。"
    ><el-button @click="refresh"
      ><el-icon><Refresh /></el-icon>刷新</el-button
    ><el-button @click="createFolder"
      ><el-icon><FolderAdd /></el-icon>新建文件夹</el-button
    ><TrainingExample @created="remote.refresh" /><el-button
      type="primary"
      @click="uploadOpen = true"
      ><el-icon><Upload /></el-icon>上传文件</el-button
    ></PageHeader
  >
  <div class="hint-box" style="margin-bottom: 22px">
    实例内路径
    <strong class="mono">/data{{ currentPath ? `/${currentPath}` : '' }}</strong
    ><el-button
      link
      type="primary"
      style="margin-left: 16px"
      @click="copyText(`/data${currentPath ? '/' + currentPath : ''}`)"
      >复制路径</el-button
    >
    <p class="caption">
      /data 挂载控制节点的个人目录，原有文件继续保留。/workspace
      是每个实例独立的临时工作目录，释放后会删除；需要保存时请复制到 /data。
    </p>
  </div>
  <StorageCapacity />
  <section class="panel">
    <div class="toolbar">
      <el-breadcrumb separator="/"
        ><el-breadcrumb-item
          ><el-button link @click="navigate('')"
            >我的文件</el-button
          ></el-breadcrumb-item
        ><el-breadcrumb-item v-for="(part, index) in parts" :key="index"
          ><el-button
            link
            @click="navigate(parts.slice(0, index + 1).join('/'))"
            >{{ part }}</el-button
          ></el-breadcrumb-item
        ></el-breadcrumb
      ><el-input
        v-model="search"
        placeholder="搜索当前目录"
        clearable
        aria-label="搜索文件"
      />
    </div>
    <AsyncState
      :loading="remote.loading.value"
      :error="remote.error.value"
      :empty="remote.data.value.length === 0"
      empty-text="此目录暂无文件，上传代码或在 JupyterLab 中创建文件"
      @retry="refresh"
      ><el-table :data="filtered" v-loading="remote.loading.value"
        ><el-table-column label="名称" min-width="260"
          ><template #default="{ row }"
            ><div style="display: flex; align-items: center; gap: 12px">
              <el-icon
                :size="22"
                :color="row.type === 'folder' ? '#d6ad5d' : '#8ca5d0'"
                ><Folder v-if="row.type === 'folder'" /><Document
                  v-else /></el-icon
              ><el-button
                v-if="row.type === 'folder'"
                link
                type="primary"
                @click="navigate(path(row))"
                >{{ row.name }}</el-button
              ><span v-else class="table-primary">{{ row.name }}</span>
            </div></template
          ></el-table-column
        ><el-table-column label="大小" width="130"
          ><template #default="{ row }"
            ><span class="caption">{{
              row.type === 'folder' ? '—' : formatFileSize(row.size)
            }}</span></template
          ></el-table-column
        ><el-table-column label="类型" width="110"
          ><template #default="{ row }"
            ><span class="caption">{{
              row.type === 'folder' ? '文件夹' : '文件'
            }}</span></template
          ></el-table-column
        ><el-table-column label="操作" width="180" fixed="right"
          ><template #default="{ row }"
            ><div class="table-actions">
              <el-button
                v-if="row.type === 'file'"
                link
                type="primary"
                :loading="downloading === row.name"
                @click="download(row)"
                >下载</el-button
              ><el-button
                v-else
                link
                type="primary"
                @click="navigate(path(row))"
                >打开</el-button
              ><el-button link type="danger" @click="remove(row)"
                >删除</el-button
              >
            </div></template
          ></el-table-column
        ></el-table
      ></AsyncState
    >
  </section>
  <el-dialog
    v-model="uploadOpen"
    title="上传文件"
    width="520px"
    :close-on-click-modal="false"
    ><FileUploader :key="currentPath" :folder="currentPath" @success="uploaded"
  /></el-dialog>
</template>
<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { storageApi } from '@/api'
import request from '@/utils/request'
import { useRemoteData } from '@/composables/useRemoteData'
import { useAutoRefresh } from '@/composables/useAutoRefresh'
import { formatFileSize } from '@/utils/format'
import { reportError, copyText } from '@/utils/feedback'
import type { FileItem } from '@/types'
import PageHeader from '@/components/PageHeader.vue'
import AsyncState from '@/components/AsyncState.vue'
import FileUploader from '@/components/FileUploader.vue'
import StorageCapacity from '@/components/StorageCapacity.vue'
import TrainingExample from '@/components/TrainingExample.vue'
const currentPath = ref(''),
  search = ref(''),
  uploadOpen = ref(false),
  downloading = ref('')
const remote = useRemoteData<FileItem[]>(
  async () =>
    (await storageApi.getFileList(currentPath.value || undefined)).data || [],
  [],
)
const parts = computed(() => currentPath.value.split('/').filter(Boolean))
const filtered = computed(() =>
  [...remote.data.value]
    .filter((file) =>
      file.name.toLowerCase().includes(search.value.toLowerCase()),
    )
    .sort(
      (a, b) =>
        (a.type === b.type ? 0 : a.type === 'folder' ? -1 : 1) ||
        a.name.localeCompare(b.name),
    ),
)
const refresh = useAutoRefresh(remote.refresh, 30000)
watch(currentPath, () => {
  search.value = ''
  void remote.refresh()
})
function navigate(value: string) {
  currentPath.value = value
}
function path(file: FileItem) {
  return (
    file.path ||
    (currentPath.value ? `${currentPath.value}/${file.name}` : file.name)
  )
}
function uploaded() {
  uploadOpen.value = false
  void remote.refresh()
}
async function download(file: FileItem) {
  downloading.value = file.name
  try {
    const blob = await storageApi.download(path(file))
    const url = URL.createObjectURL(blob),
      link = document.createElement('a')
    link.href = url
    link.download = file.name
    link.click()
    setTimeout(() => URL.revokeObjectURL(url), 1000)
  } catch (error) {
    reportError(error)
  } finally {
    downloading.value = ''
  }
}
async function remove(file: FileItem) {
  try {
    await ElMessageBox.confirm(
      `删除“${file.name}”？${file.type === 'folder' ? '仅支持删除空文件夹。' : '删除后不可恢复。'}`,
      '删除文件',
      { confirmButtonText: '删除', cancelButtonText: '取消', type: 'warning' },
    )
    await storageApi.deleteFile(path(file))
    ElMessage.success('已删除')
    await remote.refresh()
  } catch (error) {
    reportError(error)
  }
}
async function createFolder() {
  try {
    const result = await ElMessageBox.prompt(
      '在当前目录下创建文件夹',
      '新建文件夹',
      {
        confirmButtonText: '创建',
        cancelButtonText: '取消',
        inputValidator: (value: string) =>
          (!!value?.trim() &&
            !/[\\/\x00-\x1f]/.test(value) &&
            !['.', '..'].includes(value)) ||
          '请输入有效的文件夹名称',
      },
    )
    await request.post('/storage/folder', {
      path: currentPath.value
        ? `${currentPath.value}/${result.value}`
        : result.value,
    })
    ElMessage.success('文件夹已创建')
    await remote.refresh()
  } catch (error) {
    reportError(error)
  }
}
</script>
