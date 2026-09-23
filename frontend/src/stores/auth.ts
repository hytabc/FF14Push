import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

import { api } from '@/api'
import { TOKEN_KEY, isBannedError, setBannedHandler, toApiError } from '@/api/client'

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

  // 任何已认证请求被拒绝（令牌未过期但已封号）都会走到这里 → 强制下线。
  setBannedHandler(markBanned)

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

  function logout() {
    token.value = null
    nickname.value = ''
    username.value = ''
    friendCode.value = ''
    isAdmin.value = false
    localStorage.removeItem(TOKEN_KEY)
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
    isLoggedIn,
    login,
    register,
    logout,
    loadProfile,
    markBanned,
  }
})
