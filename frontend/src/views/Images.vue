<template>
  <PageHeader
    title="镜像目录"
    eyebrow="ENVIRONMENTS"
    description="选择你的开发环境，或添加已准备好的容器镜像地址。"
    ><el-button type="primary" @click="dialog = true"
      ><el-icon><Plus /></el-icon>添加镜像地址</el-button
    ></PageHeader
  >
  <div class="toolbar">
    <el-radio-group v-model="tab"
      ><el-radio-button label="public">公共镜像</el-radio-button
      ><el-radio-button label="my">我的镜像</el-radio-button></el-radio-group
    ><el-input
      v-model="search"
      clearable
      placeholder="搜索镜像名称"
      aria-label="搜索镜像"
      ><template #prefix
        ><el-icon><Search /></el-icon></template
    ></el-input>
  </div>
  <AsyncState
    :loading="images.loading"
    :error="images.error"
    :empty="filtered.length === 0"
    empty-text="暂无匹配镜像，可以添加已有镜像地址"
    @retry="refresh"
    ><div class="image-grid">
      <article
        v-for="image in filtered"
        :key="image.image_id"
        class="image-card"
      >
        <div class="image-card-top">
          <div class="gpu-symbol">
            <el-icon><Box /></el-icon>
          </div>
          <el-tag
            :type="tab === 'public' ? 'success' : 'info'"
            effect="plain"
            >{{ tab === 'public' ? '公共环境' : '个人目录' }}</el-tag
          >
        </div>
        <h2 style="font-size: 15px">{{ image.display_name || image.name }}</h2>
        <span class="mono muted">{{ image.tag }}</span>
        <p class="caption">
          {{ image.supports_ssh ? 'JupyterLab · SSH / SFTP' : 'JupyterLab'
          }}<span v-if="image.is_snapshot"> · 个人环境归档</span>
        </p>
        <el-tag v-if="image.snapshot_status === 'saving'" type="warning"
          >正在保存，请等待</el-tag
        >
        <el-tag v-if="image.snapshot_status === 'deleting'" type="info"
          >正在删除归档</el-tag
        >
        <el-alert
          v-if="image.snapshot_status === 'failed'"
          :title="image.snapshot_error || '镜像保存失败'"
          type="error"
          :closable="false"
        />
        <p class="image-description">
          {{ image.desc || '自定义容器开发环境' }}
        </p>
        <div class="table-actions">
          <el-button
            type="primary"
            :disabled="
              image.snapshot_status !== 'ready' ||
              !images.isAvailable(image.image_id)
            "
            @click="
              router.push({
                path: '/compute/apply',
                query: { image_id: image.image_id },
              })
            "
            >使用此镜像<el-icon><ArrowRight /></el-icon></el-button
          ><el-button
            v-if="
              tab === 'my' &&
              !['saving', 'deleting'].includes(image.snapshot_status || '')
            "
            link
            type="danger"
            @click="remove(image)"
            >移除</el-button
          >
        </div>
      </article>
    </div></AsyncState
  >
  <div class="hint-box section-gap">
    <strong>关于镜像和文件</strong
    >　在「我的实例」点击「保存镜像」，可保留已安装的软件和系统盘文件，再用个人镜像创建实例。镜像不保存进程和内存状态；请将代码、数据和结果保存到
    /data，释放实例后仍可使用。
  </div>
  <el-dialog v-model="dialog" title="添加已有镜像地址" width="520px"
    ><el-form ref="formRef" :model="form" :rules="rules" label-position="top"
      ><el-form-item label="镜像仓库名称" prop="name"
        ><el-input
          v-model="form.name"
          placeholder="例如 docker.io/library/jupyter-test" /></el-form-item
      ><el-form-item label="版本标签" prop="tag"
        ><el-input v-model="form.tag" placeholder="例如 latest" /></el-form-item
      ><el-form-item label="环境说明"
        ><el-input
          v-model="form.desc"
          type="textarea"
          :rows="3"
          maxlength="500" /></el-form-item></el-form
    ><template #footer
      ><el-button @click="dialog = false">取消</el-button
      ><el-button type="primary" :loading="saving" @click="save"
        >添加到我的镜像</el-button
      ></template
    ></el-dialog
  >
</template>
<script setup lang="ts">
import { ref, reactive, computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox, type FormInstance } from 'element-plus'
import { useImageStore } from '@/stores/image'
import { consoleApi } from '@/api/console'
import { useAutoRefresh } from '@/composables/useAutoRefresh'
import { reportError } from '@/utils/feedback'
import type { Image } from '@/types'
import PageHeader from '@/components/PageHeader.vue'
import AsyncState from '@/components/AsyncState.vue'
const images = useImageStore(),
  router = useRouter()
const tab = ref(useRoute().query.tab === 'my' ? 'my' : 'public'),
  search = ref(''),
  dialog = ref(false),
  saving = ref(false),
  formRef = ref<FormInstance>()
const form = reactive({ name: '', tag: 'latest', desc: '' })
const rules = {
  name: [
    {
      required: true,
      pattern: /^[A-Za-z0-9][A-Za-z0-9._:/-]*$/,
      message: '请输入有效的镜像仓库名称',
      trigger: 'blur',
    },
  ],
  tag: [
    {
      required: true,
      pattern: /^[A-Za-z0-9_][A-Za-z0-9_.-]*$/,
      message: '请输入有效的版本标签',
      trigger: 'blur',
    },
  ],
}
const filtered = computed(() =>
  (tab.value === 'public' ? images.publicImages : images.myImages).filter(
    (image) =>
      `${image.display_name || ''} ${image.name}:${image.tag} ${image.desc}`
        .toLowerCase()
        .includes(search.value.toLowerCase()),
  ),
)
const refresh = useAutoRefresh(async () => {
  await Promise.allSettled([
    images.fetchPublicImages(),
    images.fetchMyImages(),
    images.fetchAvailability(),
  ])
}, 5000)
async function save() {
  if (saving.value || !formRef.value) return
  saving.value = true
  try {
    if (!(await formRef.value.validate().catch(() => false))) return
    await consoleApi.registerImage(form)
    ElMessage.success('镜像地址已添加')
    dialog.value = false
    tab.value = 'my'
    await images.fetchMyImages()
    form.name = ''
    form.tag = 'latest'
    form.desc = ''
  } catch (error) {
    reportError(error)
  } finally {
    saving.value = false
  }
}
async function remove(image: Image) {
  try {
    await ElMessageBox.confirm(
      image.is_snapshot
        ? '删除此个人镜像的归档和缓存？/data 个人存储不会被删除。'
        : '仅从你的目录移除此镜像地址，不删除远端镜像。',
      image.is_snapshot ? '删除个人镜像' : '移除镜像',
      { confirmButtonText: '移除', cancelButtonText: '取消' },
    )
    await consoleApi.deleteImage(image.image_id)
    ElMessage.success(
      image.is_snapshot ? '删除已提交，归档清理完成后会从列表移除' : '已移除',
    )
    await images.fetchMyImages()
  } catch (error) {
    reportError(error)
  }
}
</script>
