import axios, { type AxiosResponse } from 'axios'

import { getDeviceId } from '@/utils/device'

const baseURL = import.meta.env.VITE_API_BASE ?? 'http://localhost:8000/api/v1'

export const TOKEN_KEY = 'eorzea.token'

export const http = axios.create({
  baseURL,
  timeout: 15000,
  // 反多开：服务端签发的设备 Cookie 是 httpOnly，需允许跨端口 / 同源携带（JS 读不到）。
  withCredentials: true,
})

/** 在途 GET 去重：多个页面 / store 同时首屏拉同一接口时只发一次网络请求。 */
const inflightGets = new Map<string, Promise<AxiosResponse>>()

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

  if ((config.method ?? 'get').toLowerCase() === 'get') {
    const key = `${config.url}::${JSON.stringify(config.params ?? {})}`
    const pending = inflightGets.get(key)
    if (pending) {
      config.adapter = () => pending
    } else {
      const dispatch = axios.getAdapter(http.defaults.adapter)
      config.adapter = (cfg) => {
        const promise = dispatch(cfg)
        inflightGets.set(key, promise)
        return promise.finally(() => {
          if (inflightGets.get(key) === promise) inflightGets.delete(key)
        })
      }
    }
  }
  return config
})

export interface ApiError {
  status: number
  message: string
  /** 后端机器码（如封号 'banned' / 会话顶替 'session_replaced' / 设备超限 'device_limit'）。 */
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

// 机器码 → 处理器：封号静默下线；会话被顶替 / 设备并发超限由 auth store 接管。
let bannedHandler: (() => void) | null = null
let sessionReplacedHandler: (() => void) | null = null
let deviceLimitHandler: (() => void) | null = null

export function setBannedHandler(handler: () => void) {
  bannedHandler = handler
}

/** 同一账号在其它端登录（本端被顶替）→ 清理会话并提示重新登录。 */
export function setSessionReplacedHandler(handler: () => void) {
  sessionReplacedHandler = handler
}

/** 同一设备并发在线超限 → 暂停本账号活动（不弹错误，由心跳自动恢复）。 */
export function setDeviceLimitHandler(handler: () => void) {
  deviceLimitHandler = handler
}

http.interceptors.response.use(
  (response) => response,
  (error) => {
    const code = axios.isAxiosError(error) ? detailCode(error.response?.data?.detail) : undefined
    if (code === 'banned') bannedHandler?.()
    else if (code === 'session_replaced') sessionReplacedHandler?.()
    else if (code === 'device_limit') deviceLimitHandler?.()
    return Promise.reject(error)
  },
)
