<script setup lang="ts">
import { nextTick, onMounted, onUnmounted, ref } from 'vue'

import { api } from '@/api'
import { http, toApiError } from '@/api/client'
import { useAuthStore } from '@/stores/auth'
import { useToastStore } from '@/stores/toast'
import type { ChatMessage } from '@/game/types'

const auth = useAuthStore()
const toast = useToastStore()

const MAX_LEN = 200
/** 本地最多保留的消息条数，与服务端滚动窗口一致。 */
const MAX_KEEP = 200
const RECONNECT_MS = 5000

const messages = ref<ChatMessage[]>([])
const announcements = ref<ChatMessage[]>([])
const text = ref('')
const announceText = ref('')
const loading = ref(false)
const sending = ref(false)
const connected = ref(false)
const pinned = ref(true)
const listEl = ref<HTMLElement | null>(null)

let socket: WebSocket | undefined
let reconnectTimer: number | undefined
let disposed = false
let connecting = false

function timeOf(iso: string): string {
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return ''
  return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
}

/** 按 id 去重追加普通发言（自己发送的消息与 WS 推送可能重复）；公告走置顶列表。 */
function pushMessage(msg: ChatMessage) {
  if (msg.kind === 'announcement') {
    pushAnnouncement(msg)
    return
  }
  if (messages.value.some((m) => m.id === msg.id)) return
  messages.value.push(msg)
  if (messages.value.length > MAX_KEEP) messages.value = messages.value.slice(-MAX_KEEP)
}

/** 公告置顶：按 id 去重、最新在前，长期保留（不参与滚动窗口）。 */
function pushAnnouncement(msg: ChatMessage) {
  if (announcements.value.some((m) => m.id === msg.id)) return
  announcements.value.unshift(msg)
}

function onScroll() {
  const el = listEl.value
  if (!el) return
  pinned.value = el.scrollHeight - el.scrollTop - el.clientHeight < 40
}

async function scrollToBottom() {
  if (!pinned.value) return
  await nextTick()
  const el = listEl.value
  if (el) el.scrollTop = el.scrollHeight
}

async function load() {
  loading.value = true
  try {
    const data = await api.chatMessages()
    messages.value = data.messages.slice(-MAX_KEEP)
    announcements.value = data.announcements
    pinned.value = true
    await scrollToBottom()
  } catch (e) {
    toast.push(toApiError(e).message, 'error')
  } finally {
    loading.value = false
  }
}

async function connect() {
  if (connecting || disposed) return
  if (socket && socket.readyState < 2) return // CONNECTING / OPEN
  connecting = true
  try {
    const ticket = (await http.post<{ ticket: string }>('/chat/ticket')).data.ticket
    if (disposed) return
    const url = new URL(`${http.defaults.baseURL}/chat/ws`, location.origin)
    url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:'
    url.searchParams.set('ticket', ticket)
    socket = new WebSocket(url)
    socket.onopen = () => {
      connected.value = true
    }
    socket.onmessage = (event) => {
      const msg = JSON.parse(event.data) as {
        type: string
        messages?: ChatMessage[]
        announcements?: ChatMessage[]
      }
      if (msg.type === 'history') {
        messages.value = (msg.messages ?? []).slice(-MAX_KEEP)
        announcements.value = msg.announcements ?? []
        pinned.value = true
        void scrollToBottom()
      } else if (msg.type === 'update') {
        for (const item of msg.messages ?? []) pushMessage(item)
        for (const item of msg.announcements ?? []) pushAnnouncement(item)
        void scrollToBottom()
      }
    }
    socket.onclose = () => {
      connected.value = false
      socket = undefined
    }
    socket.onerror = () => {
      connected.value = false
    }
  } catch {
    connected.value = false
  } finally {
    connecting = false
  }
}

async function send() {
  const body = text.value.trim()
  if (!body || sending.value) return
  sending.value = true
  try {
    const res = await api.chatSend(body)
    text.value = ''
    pushMessage(res.message)
    pinned.value = true
    await scrollToBottom()
  } catch (e) {
    toast.push(toApiError(e).message, 'error')
  } finally {
    sending.value = false
  }
}

async function announce() {
  const body = announceText.value.trim()
  if (!body || sending.value) return
  sending.value = true
  try {
    const res = await api.chatAnnounce(body)
    announceText.value = ''
    pushAnnouncement(res.message)
    pinned.value = true
    toast.push('公告已发布', 'success')
    await scrollToBottom()
  } catch (e) {
    toast.push(toApiError(e).message, 'error')
  } finally {
    sending.value = false
  }
}

onMounted(() => {
  void load()
  void connect()
  reconnectTimer = window.setInterval(() => void connect(), RECONNECT_MS)
})

onUnmounted(() => {
  disposed = true
  if (reconnectTimer) window.clearInterval(reconnectTimer)
  socket?.close()
})
</script>

<template>
  <div class="space-y-4">
    <!-- 大厅说明 -->
    <section class="card p-4">
      <div class="flex flex-wrap items-center gap-2">
        <h1 class="text-lg font-semibold text-white">聊天室</h1>
        <span
          class="rounded px-1.5 py-0.5 text-[10px]"
          :class="connected ? 'bg-emerald-500/20 text-emerald-300' : 'bg-ink-700 text-ink-400'"
        >
          {{ connected ? '已连接' : '连接中…' }}
        </span>
      </div>
      <p class="mt-1 text-[11px] text-ink-500">
        单一大厅 · 实名（昵称#账号）· 仅文本 · 不保留聊天记录 · 每人每分钟最多 20 条
      </p>
    </section>

    <!-- 置顶公告（长期保留，不参与滚动窗口，始终显示在最顶部） -->
    <section
      v-if="announcements.length"
      class="card border-amber-500/50 bg-amber-500/5 p-4"
    >
      <div class="flex items-center gap-2">
        <span class="rounded bg-amber-500 px-1.5 py-0.5 text-[10px] font-medium text-ink-950">
          公告
        </span>
        <h2 class="text-sm font-semibold text-amber-200">管理员公告</h2>
      </div>
      <ul class="mt-2 max-h-48 space-y-2 overflow-y-auto">
        <li
          v-for="msg in announcements"
          :key="msg.id"
          class="rounded-lg border border-amber-500/40 bg-amber-500/10 px-3 py-2"
        >
          <div class="flex flex-wrap items-baseline gap-1.5 text-xs">
            <span class="font-semibold text-amber-200">{{ msg.nickname }}</span>
            <span class="rounded bg-amber-500/20 px-1 text-[10px] text-amber-200">管理员</span>
            <time class="ml-auto text-[10px] text-ink-600">{{ timeOf(msg.createdAt) }}</time>
          </div>
          <p class="mt-0.5 break-words whitespace-pre-wrap text-sm text-amber-50">{{ msg.text }}</p>
        </li>
      </ul>
    </section>

    <!-- 管理员公告 -->
    <section v-if="auth.isAdmin" class="card p-4">
      <h3 class="text-sm font-semibold text-white">发布公告</h3>
      <form class="mt-2 flex flex-wrap gap-2" @submit.prevent="announce">
        <input
          v-model="announceText"
          :maxlength="MAX_LEN"
          class="min-w-0 flex-1 rounded border border-amber-500/50 bg-ink-900 px-3 py-1.5 text-xs"
          placeholder="公告内容（全员高亮展示，不受发言限频）"
          :disabled="sending"
        />
        <button
          type="submit"
          class="rounded-md bg-amber-500 px-4 py-1.5 text-xs font-medium text-ink-950 hover:bg-amber-400 disabled:opacity-50"
          :disabled="sending || !announceText.trim()"
        >
          发布
        </button>
      </form>
    </section>

    <!-- 消息列表 -->
    <section class="card p-4">
      <div ref="listEl" class="max-h-[60vh] space-y-2 overflow-y-auto" @scroll="onScroll">
        <p v-if="loading" class="text-xs text-ink-500">加载中…</p>
        <p v-else-if="!messages.length" class="text-xs text-ink-500">
          还没有人发言，来说点什么吧。
        </p>
        <div v-for="msg in messages" :key="msg.id" class="px-1 py-1">
          <div class="flex flex-wrap items-baseline gap-1.5 text-xs">
            <span class="font-medium text-ink-100">{{ msg.nickname }}</span>
            <span v-if="!msg.isAdmin" class="text-ink-500">#{{ msg.username }}</span>
            <span
              v-if="msg.isAdmin"
              class="rounded bg-amber-500/20 px-1 text-[10px] text-amber-200"
            >
              管理员
            </span>
            <time class="ml-auto text-[10px] text-ink-600">{{ timeOf(msg.createdAt) }}</time>
          </div>
          <p class="mt-0.5 break-words whitespace-pre-wrap text-sm text-ink-200">
            {{ msg.text }}
          </p>
        </div>
      </div>

      <!-- 发言框 -->
      <form class="mt-3 flex items-center gap-2" @submit.prevent="send">
        <input
          v-model="text"
          :maxlength="MAX_LEN"
          class="min-w-0 flex-1 rounded border border-ink-600 bg-ink-900 px-3 py-2 text-sm"
          placeholder="说点什么…（仅文本）"
          :disabled="sending"
        />
        <span class="w-14 text-right text-[10px] text-ink-600">{{ text.length }}/{{ MAX_LEN }}</span>
        <button
          type="submit"
          class="rounded-md bg-amber-500 px-4 py-2 text-xs font-medium text-ink-950 hover:bg-amber-400 disabled:opacity-50"
          :disabled="sending || !text.trim()"
        >
          发送
        </button>
      </form>
    </section>
  </div>
</template>
