import axios from 'axios'

import { getDeviceId } from '@/utils/device'

const baseURL = import.meta.env.VITE_API_BASE ?? 'http://localhost:8000/api/v1'

export const TOKEN_KEY = 'eorzea.token'

export const http = axios.create({
  baseURL,
  timeout: 15000,
})

http.interceptors.request.use((config) => {
  config.headers = config.headers ?? {}
  const token = localStorage.getItem(TOKEN_KEY)
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  // 反多开：随每个请求携带设备指纹（注册 / 登录 / 心跳据此登记与判定）。
  const deviceId = getDeviceId()
  if (deviceId) {
    config.headers['X-Device-Id'] = deviceId
  }
  return config
})

export interface ApiError {
  status: number
  message: string
  /** 后端机器码（如封号 'banned'）；用于静默处理，不向用户展示任何文案。 */
  code?: string
}

/** 后端错误 detail 若是对象且带 code，则取出该机器码。 */
function detailCode(detail: unknown): string | undefined {
  if (detail && typeof detail === 'object' && !Array.isArray(detail)) {
    const code = (detail as { code?: unknown }).code
    if (typeof code === 'string') return code
  }
  return undefined
}

/** 是否为封号响应（后端只回传 { code: 'banned' }，不含任何可读文案）。 */
export function isBannedError(error: unknown): boolean {
  if (!axios.isAxiosError(error)) return false
  return error.response?.status === 403 && detailCode(error.response.data?.detail) === 'banned'
}

export function toApiError(error: unknown): ApiError {
  if (axios.isAxiosError(error)) {
    const status = error.response?.status ?? 0
    const detail = error.response?.data?.detail
    const code = detailCode(detail)
    let message: string
    if (code === 'banned') message = '' // 封号不携带任何可用文案
    else if (typeof detail === 'string') message = detail
    else if (detail && typeof detail === 'object') {
      message = detail.rejected ? `数据校验未通过：${detail.rejected.join('；')}` : JSON.stringify(detail)
    } else message = error.message
    return { status, message, code }
  }
  return { status: 0, message: error instanceof Error ? error.message : '未知错误' }
}

// 任意请求命中封号 → 通知上层静默下线（由 auth store 注册处理器）。
let bannedHandler: (() => void) | null = null

export function setBannedHandler(handler: () => void) {
  bannedHandler = handler
}

http.interceptors.response.use(
  (response) => response,
  (error) => {
    if (isBannedError(error)) bannedHandler?.()
    return Promise.reject(error)
  },
)
