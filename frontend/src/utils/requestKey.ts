/** 请求幂等键，不用作身份凭证；兼容 HTTP 环境缺少 randomUUID 的浏览器。 */
export function requestKey(): string {
  const crypto = globalThis.crypto
  if (typeof crypto?.randomUUID === 'function') return crypto.randomUUID()

  const bytes = new Uint8Array(16)
  if (typeof crypto?.getRandomValues === 'function') {
    crypto.getRandomValues(bytes)
  } else {
    // 极旧浏览器无 Web Crypto 时仍可提交请求。
    for (let i = 0; i < bytes.length; i++) bytes[i] = Math.floor(Math.random() * 256)
  }
  bytes[6] = (bytes[6]! & 0x0f) | 0x40
  bytes[8] = (bytes[8]! & 0x3f) | 0x80
  const hex = Array.from(bytes, byte => byte.toString(16).padStart(2, '0')).join('')
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`
}
