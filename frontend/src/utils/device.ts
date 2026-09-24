/**
 * 设备指纹：为反多开提供一个稳定的「设备标识」，随每个请求以 `X-Device-Id` 发送。
 *
 * 设计：
 * - 由浏览器/环境信号（UA、语言、平台、时区、屏幕、CPU 核数、内存、canvas 渲染）派生，
 *   **与浏览器无关** —— 同一台机器上的不同浏览器（含无痕）得到同一标识，用于识别多开。
 * - 结果缓存到 localStorage，避免重复计算，也让标识在浏览器升级等信号小幅变化时保持稳定。
 * - 全程 try/catch；任何失败都退化为空串，后端会用 UA 兜底（见 services/devices.fallback_device_id）。
 */

const CACHE_KEY = 'eorzea.device'

/** FNV-1a 32 位（同步）。两个种子拼接成 16 位十六进制，足够区分设备。 */
function fnv1a(input: string, seed: number): number {
  let hash = seed >>> 0
  for (let i = 0; i < input.length; i += 1) {
    hash ^= input.charCodeAt(i)
    hash = Math.imul(hash, 16777619) >>> 0
  }
  return hash >>> 0
}

function hashHex(input: string): string {
  const a = fnv1a(input, 2166136261)
  const b = fnv1a(input, 0x811c9dc5 ^ 0x9e3779b9)
  return a.toString(16).padStart(8, '0') + b.toString(16).padStart(8, '0')
}

function canvasSignature(): string {
  try {
    if (typeof document === 'undefined') return ''
    const canvas = document.createElement('canvas')
    canvas.width = 200
    canvas.height = 40
    const ctx = canvas.getContext('2d')
    if (!ctx) return ''
    ctx.textBaseline = 'top'
    ctx.font = '14px Arial'
    ctx.fillStyle = '#f60'
    ctx.fillRect(0, 0, 100, 20)
    ctx.fillStyle = '#069'
    ctx.fillText('EorzeaIdleChronicle', 2, 2)
    ctx.strokeStyle = 'rgba(102,204,0,0.7)'
    ctx.beginPath()
    ctx.arc(50, 20, 18, 0, Math.PI * 2)
    ctx.stroke()
    return canvas.toDataURL()
  } catch {
    return ''
  }
}

function collectSignals(): string {
  const nav = typeof navigator !== 'undefined' ? (navigator as Navigator & { deviceMemory?: number }) : undefined
  const scr = typeof screen !== 'undefined' ? screen : undefined
  const parts: Array<string | number> = [
    nav?.userAgent ?? '',
    (nav?.languages ?? (nav?.language ? [nav.language] : [])).join(','),
    nav?.platform ?? '',
    nav?.hardwareConcurrency ?? '',
    nav?.deviceMemory ?? '',
    scr?.width ?? '',
    scr?.height ?? '',
    scr?.colorDepth ?? '',
    scr?.pixelDepth ?? '',
    typeof window !== 'undefined' ? window.devicePixelRatio ?? '' : '',
    typeof Intl !== 'undefined' ? Intl.DateTimeFormat().resolvedOptions().timeZone ?? '' : '',
    new Date().getTimezoneOffset(),
    canvasSignature(),
  ]
  return parts.map(String).join('|')
}

let cached: string | null = null

/** 稳定设备标识（形如 `fp-xxxxxxxxxxxxxxxx`）；失败时返回空串。 */
export function getDeviceId(): string {
  if (cached !== null) return cached
  try {
    const stored = typeof localStorage !== 'undefined' ? localStorage.getItem(CACHE_KEY) : null
    if (stored) {
      cached = stored
      return cached
    }
    const id = `fp-${hashHex(collectSignals())}`
    cached = id
    try {
      if (typeof localStorage !== 'undefined') localStorage.setItem(CACHE_KEY, id)
    } catch {
      /* 隐私模式等写入失败：仍然返回本次计算值 */
    }
    return id
  } catch {
    cached = ''
    return ''
  }
}
