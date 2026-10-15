<template>
  <PageHeader
    title="站内提醒"
    eyebrow="NOTIFICATIONS"
    description="留意实例到期、欠费保存期限与存储额度。"
  >
    <el-button @click="refresh">刷新</el-button>
    <el-button :disabled="!store.list.unread_count" @click="readAll"
      >全部已读</el-button
    >
  </PageHeader>
  <section class="panel">
    <AsyncState
      :loading="store.loading && !store.list.items.length"
      :error="store.error"
      :empty="!store.list.items.length"
      empty-text="暂无提醒"
      @retry="refresh"
    >
      <article
        v-for="notice in store.list.items"
        :key="notice.id"
        class="notice-row"
        :class="{ expired: notice.expired }"
      >
        <div>
          <strong>{{ notice.title }}</strong>
          <el-tag v-if="!notice.read && !notice.expired" size="small"
            >未读</el-tag
          ><el-tag v-if="notice.expired" type="info" size="small"
            >已过期</el-tag
          >
        </div>
        <p>{{ notice.message }}</p>
        <div class="notice-footer">
          <span class="caption">{{ formatTime(notice.created_at) }}</span
          ><el-button link type="primary" @click="open(notice)"
            >查看相关页面</el-button
          >
        </div>
      </article>
    </AsyncState>
  </section>
</template>
<script setup lang="ts">
import { useRouter } from 'vue-router'
import { noticesApi, type Notice } from '@/api/notices'
import { useNoticesStore } from '@/stores/notices'
import { useAutoRefresh } from '@/composables/useAutoRefresh'
import { formatTime } from '@/utils/format'
import { reportError } from '@/utils/feedback'
import PageHeader from '@/components/PageHeader.vue'
import AsyncState from '@/components/AsyncState.vue'
const store = useNoticesStore()
const router = useRouter()
const refresh = useAutoRefresh(store.refresh, 60000)
async function readAll() {
  try {
    await noticesApi.readAll()
    await store.refresh()
  } catch (error) {
    reportError(error)
  }
}
async function open(notice: Notice) {
  try {
    await noticesApi.read(notice.id)
    await store.refresh()
    await router.push(notice.link)
  } catch (error) {
    reportError(error)
  }
}
</script>
<style scoped>
.notice-row {
  padding: 22px 0;
  border-bottom: 1px solid #edf1f6;
}
.notice-row:last-child {
  border-bottom: 0;
}
.notice-row p {
  line-height: 1.7;
  color: #526580;
}
.notice-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}
.expired {
  opacity: 0.6;
}
</style>
