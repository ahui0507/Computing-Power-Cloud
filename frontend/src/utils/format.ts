import dayjs from 'dayjs'
import relativeTime from 'dayjs/plugin/relativeTime'
import 'dayjs/locale/zh-cn'

dayjs.extend(relativeTime)
dayjs.locale('zh-cn')

/**
 * 格式化时间
 */
export function formatTime(
  time: string | Date,
  format = 'YYYY-MM-DD HH:mm:ss',
): string {
  return dayjs(time).format(format)
}

/**
 * 相对时间
 */
export function formatRelativeTime(time: string | Date): string {
  return dayjs(time).fromNow()
}

/**
 * 格式化文件大小
 */
export function formatFileSize(bytes: number): string {
  if (bytes === 0) return '0 B'
  const k = 1024
  const sizes = ['B', 'KB', 'MB', 'GB', 'TB']
  const i = Math.floor(Math.log(bytes) / Math.log(k))
  return Math.round((bytes / Math.pow(k, i)) * 100) / 100 + ' ' + sizes[i]
}

/**
 * 格式化金额
 */
export function formatCurrency(amount: number): string {
  return '¥' + amount.toFixed(2)
}

/**
 * 格式化时长（秒转小时/分钟）
 */
export function formatDuration(seconds: number): string {
  if (seconds < 60) return `${seconds}秒`
  if (seconds < 3600) return `${Math.floor(seconds / 60)}分钟`
  const hours = Math.floor(seconds / 3600)
  const minutes = Math.floor((seconds % 3600) / 60)
  return `${hours}小时${minutes}分钟`
}

/**
 * 获取状态颜色
 */
export function getStatusColor(status: string): string {
  const statusMap: Record<string, string> = {
    running: 'success',
    completed: 'success',
    online: 'success',
    offline: 'danger',
    occupied: 'warning',
    unknown: 'info',
    external: 'warning',
    free: 'success',
    stopped: 'info',
    pending: 'warning',
    failed: 'danger',
    released: 'info',
    releasing: 'warning',
    allocated: 'warning',
    maintenance: 'info',
  }
  return statusMap[status] || 'info'
}

/**
 * 获取状态文本
 */
export function getStatusText(status: string): string {
  const statusMap: Record<string, string> = {
    running: '运行中',
    online: '在线',
    offline: '离线',
    occupied: '占用中',
    unknown: '归属待确认',
    external: '平台外占用',
    free: '空闲',
    stopped: '已停止',
    pending: '等待中',
    cancelled: '已取消',
    interrupted: '已中断',
    completed: '已完成',
    failed: '失败',
    released: '已释放',
    releasing: '释放处理中',
    allocated: '已分配',
    maintenance: '维护中',
  }
  return statusMap[status] || status
}
