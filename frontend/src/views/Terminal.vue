<template>
  <div class="terminal-page">
    <el-card>
      <template #header>
        <div class="terminal-header">
          <span>终端 - {{ displayName }}</span>
          <el-button @click="$router.push('/compute/instances')">返回实例列表</el-button>
        </div>
      </template>
      <el-result v-if="error" icon="error" title="暂时无法连接终端" :sub-title="error">
        <template #extra>
          <el-button type="primary" @click="connectTerminal">重试</el-button>
        </template>
      </el-result>
      <div v-else v-loading="true" class="connecting">正在连接实例终端…</div>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'
import { useRoute } from 'vue-router'
import { resourceApi } from '@/api/resource'
import { createJupyterTerminal } from '@/utils/jupyter-terminal'

const route = useRoute()
const containerId = String(route.params.containerId)
const error = ref('')
const displayName = ref('正在加载实例')
let active = true
let connection: AbortController | undefined

async function connectTerminal() {
  error.value = ''
  connection?.abort()
  const request = new AbortController()
  connection = request
  try {
    const response = await resourceApi.getMyResources()
    if (!active) return
    const instance = response.data?.find((item) => item.container_id === containerId)
    displayName.value = instance?.instance_name || '实例终端'
    if (instance?.status !== 'running' || !instance.jupyter_url) {
      throw new Error('实例尚未就绪或已释放，请返回实例列表刷新')
    }
    const destination = await createJupyterTerminal(instance.jupyter_url, request.signal)
    // 使用实例自带的终端和 WebSocket；浏览器返回时回到实例列表。
    if (active) window.location.replace(destination)
  } catch (reason) {
    if (active && !request.signal.aborted) {
      error.value = reason instanceof Error ? reason.message : '终端连接失败，请重试'
    }
  }
}

onMounted(() => { void connectTerminal() })
onUnmounted(() => { active = false; connection?.abort() })
</script>

<style scoped>
.terminal-page {
  width: 100%;
}

.terminal-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.connecting {
  min-height: 300px;
  display: grid;
  place-items: center;
}
</style>

