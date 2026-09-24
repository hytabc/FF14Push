import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

import { api } from '@/api'
import {
  TOKEN_KEY,
  isBannedError,
  setBannedHandler,
  setDeviceLimitHandler,
  setSessionReplacedHandler,
  toApiError,
} from '@/api/client'

export const useAuthStore = defineStore('auth', () => {
  const token = ref<string | null>(localStorage.getItem(TOKEN_KEY))
  const nickname = ref<string>('')
  const username = ref<string>('')
  const friendCode = ref<string>('')
  const isAdmin = ref(false)
  // 封号：置位后前端只渲染空白页，不显示任何文案（防止被封用户反推）。
  const banned = ref(false)
  const loading = ref(false)
  const error = ref<string | null>(null)
  /** 非错误类提示（如「账号已在其它端登录」），登录页展示一次后即可清除。 */
  const notice = ref<string | null>(null)
  /** 同一设备并发在线超限：本账号被服务端暂停，前端据此停掉战斗 / 采集循环。 */
  const deviceBlocked = ref(false)
  /** 同一设备并发在线上限（由心跳下发，用于提示文案）。 */
  const deviceLimit = ref(0)

  const isLoggedIn = computed(() => Boolean(token.value))

  function setToken(value: string) {
    token.value = value
    localStorage.setItem(TOKEN_KEY, value)
  }

  /** 命中封号：静默清除会话（不展示任何提示）。 */
  function markBanned() {
    banned.value = true
    token.value = null
    nickname.value = ''
    username.value = ''
    friendCode.value = ''
    isAdmin.value = false
    localStorage.removeItem(TOKEN_KEY)
  }

  /** 被其它端登录顶替：清理会话并提示重新登录（这是账号策略，可以给文案）。 */
  function markSessionReplaced() {
    if (!token.value) return
    logout(true)
    notice.value = '账号已在其他设备登录，请重新登录。'
  }

  // 任何已认证请求被拒绝（令牌未过期但已封号）都会走到这里 → 强制下线。
  setBannedHandler(markBanned)
  setSessionReplacedHandler(markSessionReplaced)
  setDeviceLimitHandler(() => {
    deviceBlocked.value = true
  })

  async function loadProfile() {
    if (!token.value) return null
    try {
      const me = await api.me()
      nickname.value = me.nickname
      username.value = me.username
      friendCode.value = me.friendCode
      isAdmin.value = Boolean(me.isAdmin)
      banned.value = false
      return me
    } catch (e) {
      if (isBannedError(e)) markBanned()
      else logout()
      return null
    }
  }

  async function login(user: string, password: string) {
    loading.value = true
    error.value = null
    try {
      const res = await api.login(user, password)
      setToken(res.accessToken)
      await loadProfile()
      return true
    } catch (e) {
      if (isBannedError(e)) markBanned()
      else error.value = toApiError(e).message
      return false
    } finally {
      loading.value = false
    }
  }

  async function register(user: string, password: string, nick?: string) {
    loading.value = true
    error.value = null
    try {
      const res = await api.register(user, password, nick)
      setToken(res.accessToken)
      await loadProfile()
      return true
    } catch (e) {
      if (isBannedError(e)) markBanned()
      else error.value = toApiError(e).message
      return false
    } finally {
      loading.value = false
    }
  }

  function logout(silent = false) {
    // 服务端推进会话纪元，使本账号（含其它端）的令牌立即失效。
    // 放在清 token 之前，保证请求带上 Authorization。silent 用于「已被顶替」等无需再登出的路径。
    if (!silent && token.value) void api.logout().catch(() => {})
    token.value = null
    nickname.value = ''
    username.value = ''
    friendCode.value = ''
    isAdmin.value = false
    deviceBlocked.value = false
    localStorage.removeItem(TOKEN_KEY)
  }

  function clearNotice() {
    notice.value = null
  }

  return {
    token,
    nickname,
    username,
    friendCode,
    isAdmin,
    banned,
    loading,
    error,
    notice,
    deviceBlocked,
    deviceLimit,
    isLoggedIn,
    login,
    register,
    logout,
    loadProfile,
    markBanned,
    markSessionReplaced,
    clearNotice,
  }
})
