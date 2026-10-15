import { createRouter, createWebHistory } from 'vue-router'
import type { RouteRecordRaw } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

const routes: RouteRecordRaw[] = [
  {
    path: '/login',
    name: 'Login',
    component: () => import('@/views/auth/Login.vue'),
    meta: { requiresAuth: false },
  },
  {
    path: '/register',
    redirect: '/login',
  },
  {
    path: '/',
    component: () => import('@/layouts/MainLayout.vue'),
    redirect: '/dashboard',
    meta: { requiresAuth: true },
    children: [
      {
        path: 'dashboard',
        name: 'Dashboard',
        component: () => import('@/views/Dashboard.vue'),
        meta: { title: '概览', icon: 'Odometer' },
      },
      {
        path: 'compute',
        name: 'Compute',
        redirect: '/compute/pools',
        meta: { title: '资源中心', icon: 'Cpu' },
        children: [
          {
            path: 'pools',
            name: 'GPUPools',
            component: () => import('@/views/compute/GPUPools.vue'),
            meta: { title: '资源市场', icon: 'Grid' },
          },
          {
            path: 'apply',
            name: 'ApplyResource',
            component: () => import('@/views/compute/ApplyResource.vue'),
            meta: { title: '创建实例', icon: 'Plus' },
          },
          {
            path: 'instances',
            name: 'MyInstances',
            component: () => import('@/views/compute/MyInstances.vue'),
            meta: { title: '我的实例', icon: 'List' },
          },
          {
            path: 'history',
            name: 'ResourceHistory',
            component: () => import('@/views/compute/ResourceHistory.vue'),
            meta: { title: '历史订单', icon: 'Document' },
          },
        ],
      },
      {
        path: 'images',
        name: 'Images',
        component: () => import('@/views/Images.vue'),
        meta: { title: '镜像目录', icon: 'Picture' },
      },
      {
        path: 'storage',
        name: 'Storage',
        component: () => import('@/views/Storage.vue'),
        meta: { title: '我的文件', icon: 'Folder' },
      },
      {
        path: 'jobs',
        name: 'Jobs',
        component: () => import('@/views/Jobs.vue'),
        meta: { title: '运行任务', icon: 'Document' },
      },
      {
        path: 'billing',
        name: 'Billing',
        component: () => import('@/views/Billing.vue'),
        meta: { title: '费用中心', icon: 'Money' },
      },
      {
        path: 'notices',
        name: 'Notices',
        component: () => import('@/views/Notices.vue'),
        meta: { title: '站内提醒' },
      },
      {
        path: 'admin',
        name: 'Admin',
        redirect: '/admin/nodes',
        meta: { title: '管理员面板', icon: 'Setting', requiresAdmin: true },
        children: [
          {
            path: 'maintenance',
            name: 'Maintenance',
            component: () => import('@/views/admin/Maintenance.vue'),
            meta: { title: '存储与备份' },
          },
          {
            path: 'nodes',
            name: 'NodeManagement',
            component: () => import('@/views/admin/NodeManagement.vue'),
            meta: { title: '节点监控', icon: 'Monitor' },
          },
          {
            path: 'users',
            name: 'UserManagement',
            component: () => import('@/views/admin/UserManagement.vue'),
            meta: { title: '用户管理', icon: 'User' },
          },
          {
            path: 'pools',
            name: 'PoolManagement',
            component: () => import('@/views/admin/PoolManagement.vue'),
            meta: { title: '资源池管理', icon: 'Grid' },
          },
          {
            path: 'audit',
            name: 'AuditLog',
            component: () => import('@/views/admin/AuditLog.vue'),
            meta: { title: '操作审计', icon: 'Document' },
          },
        ],
      },
      {
        path: 'profile',
        name: 'Profile',
        component: () => import('@/views/Profile.vue'),
        meta: { title: '账户设置', icon: 'User' },
      },
      {
        path: 'guide',
        name: 'Guide',
        component: () => import('@/views/Guide.vue'),
        meta: { title: '使用指南', icon: 'Reading' },
      },
    ],
  },
  {
    path: '/terminal/:containerId',
    name: 'Terminal',
    component: () => import('@/views/Terminal.vue'),
    meta: { requiresAuth: true },
  },
  {
    path: '/:pathMatch(.*)*',
    name: 'NotFound',
    component: () => import('@/views/NotFound.vue'),
  },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

// 路由守卫
router.beforeEach(async (to) => {
  const authStore = useAuthStore()

  try {
    await authStore.init()
  } catch {
    // 网络故障保留令牌，并通过 HTTP 层给出提示，禁止挂载受保护页面。
    return to.path === '/login' ? true : '/login'
  }

  // 检查是否需要认证
  if (to.meta.requiresAuth && !authStore.isAuthenticated) {
    return { path: '/login', query: { redirect: to.fullPath } }
  }

  // 检查管理员权限
  if (to.meta.requiresAdmin && !authStore.isAdmin) {
    return '/dashboard'
  }

  // 已登录用户访问登录页，重定向到首页
  if (
    (to.path === '/login' || to.path === '/register') &&
    authStore.isAuthenticated
  ) {
    return '/dashboard'
  }

  return true
})

export default router
