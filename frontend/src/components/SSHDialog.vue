<template>
  <el-dialog
    :model-value="modelValue"
    title="SSH 连接"
    width="600px"
    @update:model-value="$emit('update:modelValue', $event)"
  >
    <AsyncState
      :loading="remote.loading.value"
      :error="remote.error.value"
      :empty="!remote.data.value"
      @retry="remote.refresh"
    >
      <template v-if="remote.data.value">
        <p class="caption">在本机终端粘贴命令，按提示输入下方密码。</p>
        <div class="ssh-credential">
          <label>连接命令</label>
          <div>
            <code>{{ remote.data.value.command }}</code
            ><el-button
              link
              type="primary"
              @click="copyText(remote.data.value.command)"
              >复制</el-button
            >
          </div>
        </div>
        <div class="ssh-credential">
          <label>登录密码</label>
          <div>
            <code>{{ remote.data.value.password }}</code
            ><el-button
              link
              type="primary"
              @click="copyText(remote.data.value.password)"
              >复制</el-button
            >
          </div>
        </div>
        <p class="caption">
          支持 SSH、SFTP 和 VS Code Remote SSH。实例工作目录为
          /workspace；需要长期保留的个人文件请保存到
          {{ remote.data.value.persistent_path || '/workspace' }}。
        </p>
      </template>
    </AsyncState>
    <template #footer
      ><el-button @click="$emit('update:modelValue', false)">关闭</el-button
      ><el-button type="primary" @click="remote.refresh"
        >刷新连接信息</el-button
      ></template
    >
  </el-dialog>
</template>
<script setup lang="ts">
import { watch } from 'vue'
import request from '@/utils/request'
import type { ApiResponse } from '@/types'
import { useRemoteData } from '@/composables/useRemoteData'
import { copyText } from '@/utils/feedback'
import AsyncState from './AsyncState.vue'
const props = defineProps<{ modelValue: boolean; containerId: string }>()
defineEmits<{ 'update:modelValue': [value: boolean] }>()
type Connection = {
  command: string
  password: string
  persistent_path?: string
}
const remote = useRemoteData<Connection | null>(
  async () =>
    (
      await request.post<ApiResponse<Connection>>(
        `/resource/${props.containerId}/ssh`,
      )
    ).data || null,
  null,
)
watch(
  () => [props.modelValue, props.containerId],
  () => {
    if (props.modelValue) void remote.refresh()
    else remote.data.value = null
  },
)
</script>
<style scoped>
.ssh-credential {
  margin: 20px 0;
}
.ssh-credential label {
  display: block;
  margin-bottom: 8px;
  font-size: 12px;
  color: #6b7c93;
}
.ssh-credential > div {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 16px;
  padding: 15px;
  border: 1px solid #dce5f2;
  border-radius: 10px;
  background: #f4f8ff;
}
.ssh-credential code {
  overflow-wrap: anywhere;
}
</style>
