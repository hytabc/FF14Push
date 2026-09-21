<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { api } from '@/api'
import { toApiError } from '@/api/client'
import Modal from '@/components/Modal.vue'
import { useAuthStore } from '@/stores/auth'
import { useToastStore } from '@/stores/toast'
import { formatNumber } from '@/utils/format'

interface AdminUser {
  id: number
  username: string
  nickname: string
  gold: number
  level: number | null
  hasHero: boolean
  isAdmin: boolean
  banned: boolean
}

const auth = useAuthStore()
const toast = useToastStore()

const query = ref('')
const users = ref<AdminUser[]>([])
const loading = ref(false)
const resetting = ref(false)
const banning = ref<number | null>(null)

const target = ref<AdminUser | null>(null)
const newPassword = ref('')
const confirmPassword = ref('')

const canSubmit = computed(
  () => newPassword.value.length >= 6 && newPassword.value === confirmPassword.value && !resetting.value,
)

async function search() {
  loading.value = true
  try {
    const res = await api.adminUsers(query.value, 50)
    users.value = res.users
  } catch (e) {
    toast.push(toApiError(e).message, 'error')
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  if (auth.isAdmin) void search()
})

function openReset(user: AdminUser) {
  if (user.isAdmin) return
  target.value = user
  newPassword.value = ''
  confirmPassword.value = ''
}

async function submitReset() {
  const user = target.value
  if (!user || !canSubmit.value) return
  resetting.value = true
  try {
    const res = await api.adminResetPassword(user.id, newPassword.value)
    toast.push(res.message, 'success')
    target.value = null
  } catch (e) {
    toast.push(toApiError(e).message, 'error')
  } finally {
    resetting.value = false
  }
}

async function toggleBan(user: AdminUser) {
  if (user.isAdmin || banning.value !== null) return
  banning.value = user.id
  try {
    const res = await api.adminBanUser(user.id, !user.banned)
    user.banned = res.banned
    toast.push(res.message, 'success')
  } catch (e) {
    toast.push(toApiError(e).message, 'error')
  } finally {
    banning.value = null
  }
}
</script>

<template>
  <div class="space-y-4">
    <section class="card p-4">
      <div class="flex flex-wrap items-center gap-3">
        <h2 class="text-lg font-semibold text-white">管理员 · 账号管理</h2>
        <span class="text-xs text-ink-400">重置密码 / 封禁账号</span>
      </div>
      <p class="mt-1 text-[11px] text-ink-500">
        管理员账号由环境变量配置，不参与排行榜；管理员自己的密码不能在此修改。
        封禁后该账号无法登录、已登录会话立即失效，并从排行榜隐藏；页面不会向被封账号展示任何提示。
      </p>
    </section>

    <section v-if="!auth.isAdmin" class="card p-6 text-center text-sm text-rose-300">
      需要管理员权限才能访问本页面。
    </section>

    <template v-else>
      <section class="card p-4">
        <div class="flex flex-wrap gap-2">
          <input
            v-model="query"
            class="min-w-0 flex-1 rounded border border-ink-600 bg-ink-900 px-2 py-1.5 text-xs"
            placeholder="搜索登录账号或昵称"
            @keyup.enter="search"
          />
          <button
            class="rounded-md bg-amber-500 px-4 py-1.5 text-xs font-medium text-ink-950 hover:bg-amber-400 disabled:opacity-50"
            :disabled="loading"
            @click="search"
          >
            {{ loading ? '搜索中…' : '搜索' }}
          </button>
        </div>
      </section>

      <section class="card overflow-hidden">
        <table class="w-full text-xs">
          <thead class="bg-ink-800/80 text-ink-400">
            <tr>
              <th class="w-16 px-3 py-2 text-left">ID</th>
              <th class="px-3 py-2 text-left">登录账号</th>
              <th class="px-3 py-2 text-left">昵称</th>
              <th class="px-3 py-2 text-left">英雄等级</th>
              <th class="px-3 py-2 text-right">金币</th>
              <th class="w-40 px-3 py-2 text-right">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="user in users" :key="user.id" class="border-t border-ink-800">
              <td class="px-3 py-2 font-mono text-ink-500">{{ user.id }}</td>
              <td class="px-3 py-2 text-ink-100">
                {{ user.username }}
                <span v-if="user.isAdmin" class="ml-1 rounded bg-rose-500/20 px-1.5 py-0.5 text-[10px] text-rose-200">
                  管理员
                </span>
                <span v-if="user.banned" class="ml-1 rounded bg-red-700/40 px-1.5 py-0.5 text-[10px] text-red-100">
                  已封禁
                </span>
              </td>
              <td class="px-3 py-2 text-ink-300">{{ user.nickname }}</td>
              <td class="px-3 py-2 text-ink-400">{{ user.level ?? '—' }}</td>
              <td class="px-3 py-2 text-right font-mono text-ink-300">{{ formatNumber(user.gold) }}</td>
              <td class="px-3 py-2 text-right">
                <button
                  class="rounded bg-indigo-600/80 px-2 py-1 text-[11px] text-white hover:bg-indigo-500 disabled:opacity-40"
                  :disabled="user.isAdmin"
                  @click="openReset(user)"
                >
                  重置密码
                </button>
                <button
                  class="ml-1 rounded px-2 py-1 text-[11px] text-white disabled:opacity-40"
                  :class="user.banned ? 'bg-emerald-600/80 hover:bg-emerald-500' : 'bg-red-600/80 hover:bg-red-500'"
                  :disabled="user.isAdmin || banning === user.id"
                  @click="toggleBan(user)"
                >
                  {{ user.banned ? '解封' : '封禁' }}
                </button>
              </td>
            </tr>
            <tr v-if="!users.length && !loading">
              <td colspan="6" class="px-3 py-10 text-center text-ink-600">没有匹配的用户</td>
            </tr>
          </tbody>
        </table>
      </section>
    </template>

    <Modal :open="!!target" title="重置用户密码" @close="target = null">
      <div v-if="target" class="space-y-3 text-sm">
        <p class="text-ink-200">
          将把
          <b class="text-white">{{ target.nickname }}</b>
          <span class="text-ink-500">（{{ target.username }}）</span>
          的登录密码重置为：
        </p>
        <input
          v-model="newPassword"
          type="text"
          class="w-full rounded border border-ink-600 bg-ink-900 px-2 py-1.5 text-xs"
          placeholder="新密码（至少 6 位）"
        />
        <input
          v-model="confirmPassword"
          type="text"
          class="w-full rounded border border-ink-600 bg-ink-900 px-2 py-1.5 text-xs"
          placeholder="再输入一次"
        />
        <p v-if="newPassword && newPassword.length < 6" class="text-[11px] text-rose-300">密码至少 6 位</p>
        <p
          v-else-if="confirmPassword && newPassword !== confirmPassword"
          class="text-[11px] text-rose-300"
        >
          两次输入不一致
        </p>
        <p class="text-[11px] text-ink-500">请把新密码通过安全渠道告知玩家；已登录的会话不会立即失效。</p>
      </div>
      <template #footer>
        <button class="rounded-md bg-ink-700 px-3 py-2 text-sm hover:bg-ink-600" @click="target = null">
          取消
        </button>
        <button
          class="rounded-md bg-amber-500 px-3 py-2 text-sm font-medium text-ink-950 disabled:opacity-50"
          :disabled="!canSubmit"
          @click="submitReset"
        >
          {{ resetting ? '处理中…' : '确认重置' }}
        </button>
      </template>
    </Modal>
  </div>
</template>
