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
        <p class="caption">
          在 PowerShell 或本机终端粘贴下方命令。<template v-if="!remote.data.value.jump_host">按提示输入下方实例密码。</template>
        </p>
        <p v-if="remote.data.value.jump_uses_instance_password" class="caption">
          已为本实例配置专用 SSH 转发账号。两次密码提示均输入下方实例密码。
        </p>
        <p v-else-if="remote.data.value.jump_host" class="caption">
          第一次提示 {{ remote.data.value.jump_host.split('@')[0] }} 的密码时，请输入该账号的控制节点 SSH 密码；第二次提示 root 的密码时，再输入下方实例密码。平台登录密码和下方实例密码均不能代替控制节点 SSH 密码。
        </p>
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
          <label>{{ remote.data.value.jump_uses_instance_password ? '实例密码（两次均使用此密码）' : remote.data.value.jump_host ? '实例 root 密码（第二次输入）' : '实例登录密码' }}</label>
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
  jump_host?: string | null
  jump_uses_instance_password?: boolean
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
