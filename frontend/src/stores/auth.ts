import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

import { api } from '@/api'
import { TOKEN_KEY, toApiError } from '@/api/client'

export const useAuthStore = defineStore('auth', () => {
  const token = ref<string | null>(localStorage.getItem(TOKEN_KEY))
  const nickname = ref<string>('')
  const username = ref<string>('')
  const loading = ref(false)
  const error = ref<string | null>(null)

  const isLoggedIn = computed(() => Boolean(token.value))

  function setToken(value: string) {
    token.value = value
    localStorage.setItem(TOKEN_KEY, value)
  }

  async function loadProfile() {
    if (!token.value) return null
    try {
      const me = await api.me()
      nickname.value = me.nickname
      username.value = me.username
      return me
    } catch {
      logout()
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
      error.value = toApiError(e).message
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
      error.value = toApiError(e).message
      return false
    } finally {
      loading.value = false
    }
  }

  function logout() {
    token.value = null
    nickname.value = ''
    username.value = ''
    localStorage.removeItem(TOKEN_KEY)
  }

  return { token, nickname, username, loading, error, isLoggedIn, login, register, logout, loadProfile }
})
