<script setup lang="ts">
import { ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import SiteFooter from '@/components/SiteFooter.vue'
import { useAuthStore } from '@/stores/auth'
import { useGameStore } from '@/stores/game'

const auth = useAuthStore()
const game = useGameStore()
const router = useRouter()
const route = useRoute()

const mode = ref<'login' | 'register'>('login')
const username = ref('')
const password = ref('')
const nickname = ref('')

async function submit() {
  if (!username.value || !password.value) return
  const ok =
    mode.value === 'login'
      ? await auth.login(username.value, password.value)
      : await auth.register(username.value, password.value, nickname.value || undefined)
  if (!ok) return
  await game.loadState()
  void router.push((route.query.redirect as string) || '/')
}
</script>

<template>
  <div class="flex min-h-screen flex-col">
    <div class="flex flex-1 items-center justify-center px-4">
      <div class="card w-full max-w-sm p-6">
        <h1 class="text-xl font-bold text-amber-200">艾欧泽亚放置录</h1>
        <p class="mt-1 text-xs text-ink-400">挂机自动战斗 · 抽箱 · 合成 · 图鉴</p>

        <div class="mt-5 flex gap-1 rounded-lg bg-ink-800 p-1 text-xs">
          <button
            class="flex-1 rounded-md py-1.5 transition"
            :class="mode === 'login' ? 'bg-amber-500 text-ink-950' : 'text-ink-400'"
            @click="mode = 'login'"
          >
            登录
          </button>
          <button
            class="flex-1 rounded-md py-1.5 transition"
            :class="mode === 'register' ? 'bg-amber-500 text-ink-950' : 'text-ink-400'"
            @click="mode = 'register'"
          >
            注册
          </button>
        </div>

        <form class="mt-4 space-y-3" @submit.prevent="submit">
          <input
            v-model="username"
            class="w-full rounded-lg border border-ink-600 bg-ink-900 px-3 py-2 text-sm outline-none focus:border-amber-400"
            placeholder="用户名（3-32 位）"
            autocomplete="username"
          />
          <input
            v-model="password"
            type="password"
            class="w-full rounded-lg border border-ink-600 bg-ink-900 px-3 py-2 text-sm outline-none focus:border-amber-400"
            placeholder="密码（至少 6 位）"
            autocomplete="current-password"
          />
          <input
            v-if="mode === 'register'"
            v-model="nickname"
            class="w-full rounded-lg border border-ink-600 bg-ink-900 px-3 py-2 text-sm outline-none focus:border-amber-400"
            placeholder="昵称（可选，排行榜展示用）"
          />

          <p v-if="auth.error" class="rounded bg-rose-500/10 px-3 py-2 text-xs text-rose-300">
            {{ auth.error }}
          </p>

          <button
            type="submit"
            class="w-full rounded-lg bg-amber-500 py-2 text-sm font-medium text-ink-950 transition hover:bg-amber-400 disabled:opacity-50"
            :disabled="auth.loading"
          >
            {{ auth.loading ? '处理中…' : mode === 'login' ? '进入艾欧泽亚' : '创建账号并开始冒险' }}
          </button>
        </form>

        <p class="mt-4 text-center text-[11px] text-ink-600">
          注册即免费获得 1 名均衡型初始英雄
        </p>
      </div>
    </div>

    <SiteFooter />
  </div>
</template>
