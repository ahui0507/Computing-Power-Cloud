import type { ApplyResourceRequest } from '@/types'

const prefix = 'cloud-resource-request:'

function scope() {
  try {
    return String(JSON.parse(localStorage.getItem('userInfo') || '{}').user_id || 'current')
  } catch {
    return 'current'
  }
}

function storageKey(data: ApplyResourceRequest) {
  return prefix + scope() + ':' + JSON.stringify({
    pool_id: data.pool_id, gpu_count: data.gpu_count, image_id: data.image_id,
    billing_mode: data.billing_mode || 'on_demand', duration: data.duration || null,
  })
}

export function applicationKey(data: ApplyResourceRequest) {
  const key = storageKey(data)
  const existing = sessionStorage.getItem(key)
  if (existing) return existing
  const bytes = crypto.getRandomValues(new Uint8Array(16))
  const generated = Array.from(bytes, (value) => value.toString(16).padStart(2, '0')).join('')
  sessionStorage.setItem(key, generated)
  return generated
}

export function finishApplication(data: ApplyResourceRequest) {
  sessionStorage.removeItem(storageKey(data))
}

export function resetApplications() {
  const own = prefix + scope() + ':'
  for (let index = sessionStorage.length - 1; index >= 0; index--) {
    const key = sessionStorage.key(index)
    if (key?.startsWith(own)) sessionStorage.removeItem(key)
  }
}
