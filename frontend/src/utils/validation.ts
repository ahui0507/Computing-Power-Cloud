/**
 * 验证手机号
 */
export function validatePhone(phone: string): boolean {
  const phoneRegex = /^1[3-9]\d{9}$/
  return phoneRegex.test(phone)
}

/**
 * 验证密码强度
 */
export function validatePassword(password: string): {
  valid: boolean
  message?: string
} {
  if (new TextEncoder().encode(password).length > 72) {
    return { valid: false, message: '密码最多72字节，请缩短密码' }
  }
  if (password.length < 8) {
    return { valid: false, message: '密码长度至少8位' }
  }
  if (!/[A-Za-z]/.test(password)) {
    return { valid: false, message: '密码必须包含字母' }
  }
  if (!/[0-9]/.test(password)) {
    return { valid: false, message: '密码必须包含数字' }
  }
  return { valid: true }
}

/**
 * 验证邮箱
 */
export function validateEmail(email: string): boolean {
  const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/
  return emailRegex.test(email)
}

/**
 * 验证验证码
 */
export function validateCode(code: string): boolean {
  return /^\d{4,6}$/.test(code)
}
