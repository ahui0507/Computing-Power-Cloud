export const navigation = [
  {
    title: '算力服务',
    items: [
      { path: '/compute/pools', title: '资源市场', icon: 'Cpu' },
      { path: '/compute/instances', title: '我的实例', icon: 'Monitor' },
    ],
  },
  {
    title: '工作空间',
    items: [
      { path: '/dashboard', title: '概览', icon: 'Odometer' },
      { path: '/compute/history', title: '历史订单', icon: 'Tickets' },
    ],
  },
  {
    title: '开发与账户',
    items: [
      { path: '/images', title: '镜像目录', icon: 'Box' },
      { path: '/storage', title: '我的文件', icon: 'FolderOpened' },
      { path: '/jobs', title: '运行任务', icon: 'VideoPlay' },
      { path: '/billing', title: '费用中心', icon: 'Wallet' },
      { path: '/notices', title: '站内提醒', icon: 'Bell' },
      { path: '/profile', title: '账户设置', icon: 'User' },
      { path: '/guide', title: '使用指南', icon: 'Reading' },
    ],
  },
]
export const adminNavigation = {
  title: '平台管理',
  items: [
    { path: '/admin/nodes', title: '节点监控', icon: 'SetUp' },
    { path: '/admin/users', title: '用户管理', icon: 'UserFilled' },
    { path: '/admin/pools', title: '资源池管理', icon: 'Grid' },
    { path: '/admin/audit', title: '操作审计', icon: 'DocumentChecked' },
    { path: '/admin/maintenance', title: '存储与运行保障', icon: 'Files' },
  ],
}
