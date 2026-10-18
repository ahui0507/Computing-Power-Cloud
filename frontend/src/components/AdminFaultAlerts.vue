<template>
  <el-dialog :model-value="visible" title="运行故障提醒" width="min(620px, 94vw)"
    :close-on-click-modal="false" :close-on-press-escape="false" :before-close="dismiss">
    <p class="hint">提醒会保留到手动关闭；关闭表示已阅，故障复发时会再次提醒。</p>
    <div class="incident-list"><div v-for="incident in inbox.pending" :key="incidentKey(incident)" class="incident" role="alert">
      <div><el-tag :type="incident.active ? 'danger' : 'success'">{{ incident.active ? '待处理' : '已恢复' }}</el-tag>
        <strong>{{ incident.title }}</strong></div>
      <p>{{ incident.message }}</p>
      <small>首次发现：{{ formatTime(incident.first_seen) }}</small>
    </div></div>
    <template #footer>
      <a href="/ops-alerts/" target="_blank" rel="noopener">查看独立故障记录</a>
      <el-button type="primary" @click="dismiss()">已阅，手动关闭</el-button>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useAuthStore } from '@/stores/auth'
import { acknowledgeFaults, incidentKey, mergeFaultInbox, readIncidents, type FaultInbox, type FaultIncident } from '@/utils/faultInbox'

const auth = useAuthStore()
const inbox = ref<FaultInbox>({ acknowledged: [], pending: [] })
const visible = computed(() => auth.isAdmin && inbox.value.pending.length > 0)
let storageKey = ''
let generation = 0
let timer: ReturnType<typeof setInterval> | undefined
let controller: AbortController | undefined
let failures = 0
let feedOutage: FaultIncident | undefined
const formatTime = (stamp: number) => new Date(stamp * 1000).toLocaleString()

function save() {
  try { localStorage.setItem(storageKey, JSON.stringify({ ...inbox.value, feed_outage: feedOutage })) } catch { /* Keep reminders in memory when storage is unavailable. */ }
}
function dismiss(done?: () => void) {
  inbox.value = acknowledgeFaults(inbox.value)
  save()
  done?.()
}
async function poll(version: number) {
  if (controller) return
  const request = new AbortController()
  controller = request
  const timeout = setTimeout(() => request.abort(), 8000)
  try {
    const response = await fetch('/ops-alerts/status.json', { cache: 'no-store', signal: request.signal, credentials: 'omit' })
    if (!response.ok) throw new Error('Feed unavailable')
    const feed = await response.json()
    const age = Date.now() / 1000 - feed.generated_at
    if (!Number.isFinite(age) || age > 120 || age < -60) throw new Error('Feed stale')
    const incidents = readIncidents(feed.incidents)
    if (version !== generation) return
    failures = 0
    if (feedOutage) {
      incidents.push({ ...feedOutage, active: false, resolved_at: Date.now() / 1000 })
      feedOutage = undefined
    }
    inbox.value = mergeFaultInbox(inbox.value, incidents)
    save()
  } catch {
    if (version !== generation) return
    failures += 1
    if (failures >= 3) {
      const now = Date.now() / 1000
      feedOutage ??= { id: `browser-monitor-${now}`, code: 'monitor-control', title: '独立监测入口不可用',
        message: '无法获取新的故障记录，请检查平台入口或独立监测服务。', severity: 'critical', active: true,
        first_seen: now, last_seen: now, resolved_at: null }
      inbox.value = mergeFaultInbox(inbox.value, [{ ...feedOutage, last_seen: now }])
      save()
    }
  } finally {
    clearTimeout(timeout)
    if (controller === request) controller = undefined
  }
}
watch(() => auth.isAdmin ? auth.userInfo?.user_id : undefined, (userId) => {
  generation += 1
  if (timer) clearInterval(timer)
  controller?.abort()
  controller = undefined
  inbox.value = { acknowledged: [], pending: [] }
  failures = 0
  feedOutage = undefined
  if (userId === undefined) return
  storageKey = `cpcloud-fault-inbox-v1:${userId}`
  try {
    const saved = JSON.parse(localStorage.getItem(storageKey) || 'null')
    if (saved && Array.isArray(saved.acknowledged)) {
      inbox.value = { acknowledged: saved.acknowledged.filter((key: unknown) => typeof key === 'string').slice(-1000), pending: readIncidents(saved.pending) }
      feedOutage = saved.feed_outage ? readIncidents([saved.feed_outage])[0] : undefined
    }
  } catch { /* Ignore malformed local state. */ }
  const version = generation
  void poll(version)
  timer = setInterval(() => void poll(version), 30000)
}, { immediate: true })
onBeforeUnmount(() => {
  generation += 1
  if (timer) clearInterval(timer)
  controller?.abort()
})
</script>

<style scoped>
.hint { color: var(--el-text-color-secondary); }
.incident-list { max-height: 50vh; overflow-y: auto; }
.incident { border-bottom: 1px solid var(--el-border-color-lighter); padding: 14px 0; }
.incident strong { margin-left: 10px; }
.incident small { color: var(--el-text-color-secondary); }
a { margin-right: 16px; color: var(--el-color-primary); }
</style>
