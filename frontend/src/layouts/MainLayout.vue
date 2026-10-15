<template>
  <div class="console-shell">
    <div v-if="menuOpen" class="sidebar-mask" @click="menuOpen = false" />
    <aside class="console-sidebar" :class="{ 'is-open': menuOpen }">
      <router-link class="brand" to="/dashboard"
        ><span class="brand-symbol"
          ><el-icon><Cpu /></el-icon></span
        ><span
          >算力云<span class="brand-caption">COMPUTE CONSOLE</span></span
        ></router-link
      >
      <div class="workspace-label">
        <span class="online-dot" />个人工作空间<el-tag
          size="small"
          effect="plain"
          >{{ auth.isAdmin ? '管理' : '个人' }}</el-tag
        >
      </div>
      <nav class="sidebar-nav" aria-label="主导航">
        <div v-for="group in groups" :key="group.title" class="nav-group">
          <p class="nav-group-label">{{ group.title }}</p>
          <router-link
            v-for="item in group.items"
            :key="item.path"
            :to="item.path"
            :class="{
              primary:
                item.path === '/compute/pools' ||
                item.path === '/compute/instances',
              active:
                route.path === item.path ||
                (item.path === '/compute/pools' &&
                  route.path === '/compute/apply'),
            }"
            @click="menuOpen = false"
          >
            <el-icon><component :is="item.icon" /></el-icon
            ><span>{{ item.title }}</span>
            <span
              v-if="
                item.path === '/compute/instances' &&
                resources.activeInstances.length
              "
              class="nav-count"
              >{{ resources.activeInstances.length }}</span
            >
          </router-link>
        </div>
      </nav>
      <router-link to="/guide" class="sidebar-help"
        ><el-icon><Connection /></el-icon>
        <div>
          <strong>从代码到算力</strong><span>创建实例，开始你的工作</span>
        </div>
        <el-icon><ArrowRight /></el-icon
      ></router-link>
      <div class="sidebar-foot">GPU COMPUTING PLATFORM<span>v0.9.0</span></div>
    </aside>
    <div class="console-workspace">
      <header class="console-topbar">
        <div class="topbar-title">
          <el-button
            class="mobile-menu"
            text
            aria-label="展开导航"
            @click="menuOpen = !menuOpen"
            ><el-icon><Expand /></el-icon></el-button
          ><span class="topbar-context">控制台</span
          ><el-icon class="muted"><ArrowRight /></el-icon
          ><span>{{ title }}</span>
        </div>
        <div class="topbar-tools">
          <NoticeBell />
          <el-select
            v-model="destination"
            filterable
            clearable
            placeholder="快速前往…"
            class="quick-search"
            aria-label="快速前往"
            @change="navigate"
          >
            <el-option
              v-for="item in searchItems"
              :key="item.path"
              :value="item.path"
              :label="item.title"
            />
          </el-select>
          <router-link to="/billing" class="wallet-link"
            ><el-icon><Wallet /></el-icon
            ><span>¥ {{ auth.userInfo?.balance.toFixed(4) }}</span></router-link
          >
          <el-dropdown trigger="click" @command="accountAction"
            ><button class="account-trigger" aria-label="账户菜单">
              <span class="avatar">{{
                auth.userInfo?.email.slice(0, 1).toUpperCase()
              }}</span
              ><el-icon><ArrowDown /></el-icon></button
            ><template #dropdown
              ><el-dropdown-menu
                ><el-dropdown-item disabled>{{
                  auth.userInfo?.email
                }}</el-dropdown-item
                ><el-dropdown-item command="profile">账户设置</el-dropdown-item
                ><el-dropdown-item command="logout" divided
                  >退出登录</el-dropdown-item
                ></el-dropdown-menu
              ></template
            ></el-dropdown
          >
        </div>
      </header>
      <main class="console-content">
        <div class="content-width"><BudgetNotice /><router-view /></div>
      </main>
    </div>
  </div>
</template>
<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessageBox } from 'element-plus'
import { useAuthStore } from '@/stores/auth'
import { useResourceStore } from '@/stores/resource'
import { navigation, adminNavigation } from '@/utils/navigation'
import { reportError } from '@/utils/feedback'
import BudgetNotice from '@/components/BudgetNotice.vue'
import NoticeBell from '@/components/NoticeBell.vue'
const auth = useAuthStore()
const resources = useResourceStore()
const route = useRoute()
const router = useRouter()
const menuOpen = ref(false)
const destination = ref('')
const groups = computed(() =>
  auth.isAdmin ? [...navigation, adminNavigation] : navigation,
)
const searchItems = computed(() => groups.value.flatMap((group) => group.items))
const title = computed(
  () =>
    [...route.matched].reverse().find((item) => item.meta.title)?.meta.title ||
    '工作空间',
)
function navigate(path: string) {
  if (path) {
    void router.push(path)
    destination.value = ''
  }
}
async function accountAction(command: string) {
  if (command === 'profile') return router.push('/profile')
  try {
    await ElMessageBox.confirm(
      '退出后，正在运行的实例仍会继续运行和计费。',
      '退出登录',
      { confirmButtonText: '退出登录', cancelButtonText: '继续使用' },
    )
    auth.logout()
  } catch (error) {
    reportError(error)
  }
}
</script>
