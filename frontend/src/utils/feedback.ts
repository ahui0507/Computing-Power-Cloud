import { ElMessage } from 'element-plus'
import { ApiError } from '@/utils/request'
export function reportError(error: unknown, fallback = '操作失败，请重试') {
  if (error === 'cancel' || error === 'close' || error instanceof ApiError)
    return
  ElMessage.error(error instanceof Error ? error.message : fallback)
}
export async function copyText(text: string) {
  try {
    if (navigator.clipboard && window.isSecureContext)
      await navigator.clipboard.writeText(text)
    else {
      const field = document.createElement('textarea')
      field.value = text
      field.style.position = 'fixed'
      field.style.opacity = '0'
      document.body.appendChild(field)
      field.select()
      const copied = document.execCommand('copy')
      field.remove()
      if (!copied) throw new Error('复制失败，请手动复制')
    }
    ElMessage.success('已复制')
  } catch (error) {
    reportError(error)
  }
}
