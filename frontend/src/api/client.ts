import axios from 'axios'

const baseURL = import.meta.env.VITE_API_BASE ?? 'http://localhost:8000/api/v1'

export const TOKEN_KEY = 'eorzea.token'

export const http = axios.create({
  baseURL,
  timeout: 15000,
})

http.interceptors.request.use((config) => {
  const token = localStorage.getItem(TOKEN_KEY)
  if (token) {
    config.headers = config.headers ?? {}
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

export interface ApiError {
  status: number
  message: string
}

export function toApiError(error: unknown): ApiError {
  if (axios.isAxiosError(error)) {
    const detail = error.response?.data?.detail
    let message: string
    if (typeof detail === 'string') message = detail
    else if (detail && typeof detail === 'object') {
      message = detail.rejected ? `数据校验未通过：${detail.rejected.join('；')}` : JSON.stringify(detail)
    } else message = error.message
    return { status: error.response?.status ?? 0, message }
  }
  return { status: 0, message: error instanceof Error ? error.message : '未知错误' }
}
