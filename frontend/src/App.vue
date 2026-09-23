<script setup lang="ts">
import { computed, onMounted, watch } from 'vue'
import { RouterLink, RouterView, useRoute, useRouter } from 'vue-router'

import ItemActionDialogs from '@/components/ItemActionDialogs.vue'
import LootBubbles from '@/components/LootBubbles.vue'
import SiteFooter from '@/components/SiteFooter.vue'
import TagDialog from '@/components/TagDialog.vue'
import ToastStack from '@/components/ToastStack.vue'
import TutorialOverlay from '@/components/TutorialOverlay.vue'
import { useAuthStore } from '@/stores/auth'
import { useGameStore } from '@/stores/game'

const auth = useAuthStore()
const game = useGameStore()
const route = useRoute()
const router = useRouter()

const isPublicOnly = computed(() => route.name === 'login')

const NAV = [
  { to: '/', label: '战斗', icon: '⚔' },
  { to: '/equipment', label: '装备', icon: '🛡' },
  { to: '/inventory', label: '背包', icon: '🎒' },
  { to: '/chest', label: '抽箱', icon: '📦' },
  { to: '/craft', label: '合成', icon: '⚗' },
  { to: '/gather', label: '采集', icon: '⛏' },
  { to: '/produce', label: '生产', icon: '🔨' },
  { to: '/fish', label: '钓鱼', icon: '🎣' },
  { to: '/roster', label: '名册', icon: '👥' },
  { to: '/coop', label: '远征', icon: '⚑' },
  { to: '/arena', label: '竞技场', icon: '⚔' },
  { to: '/hero', label: '英雄', icon: '🧙' },
  { to: '/region', label: '地区', icon: '🗺' },
  { to: '/raid', label: '高难', icon: '☠' },
  { to: '/tavern', label: '酒馆', icon: '🍺' },
  { to: '/codex', label: '图鉴', icon: '📖' },
  { to: '/ranking', label: '排行', icon: '🏆' },
  { to: '/settings', label: '设置', icon: '⚙' },
]

/** 管理入口只对管理员可见。 */
const navItems = computed(() =>
  auth.isAdmin ? [...NAV, { to: '/admin', label: '管理', icon: '🔧' }] : NAV,
)

// 命中封号：立即停止本地战斗循环，页面只保留空白（不展示任何文案）。
watch(
  () => auth.banned,
  (value) => {
    if (value) {
      void game.stopBattle(true)
      game.reset()
    }
  },
)

onMounted(async () => {
  if (auth.isLoggedIn) {
    await auth.loadProfile()
    await game.loadState()
  }
})

async function logout() {
  await game.stopBattle(true)
  game.reset()
  auth.logout()
  void router.push({ name: 'login' })
}
</script>

<template>
  <!-- 封号：整页留白，不渲染任何文案（防止被封用户反推封禁原因）。 -->
  <div v-if="auth.banned" class="min-h-full"></div>

  <div v-else-if="isPublicOnly" class="min-h-full">
    <RouterView />
  </div>

  <div v-else class="flex min-h-full flex-col">
    <header data-app-header class="sticky top-0 z-40 border-b border-ink-700/70 bg-ink-950/85 backdrop-blur">
      <div class="mx-auto flex max-w-6xl flex-wrap items-center gap-3 px-3 py-2">
        <RouterLink to="/" class="text-sm font-bold tracking-wide text-amber-200">
          艾欧泽亚放置录
        </RouterLink>

        <div class="ml-auto flex items-center gap-3 text-xs">
          <span class="rounded bg-ink-800 px-2 py-1 font-mono text-amber-300">
            💰 {{ game.gold.toLocaleString() }}
          </span>
          <span v-if="game.hero" class="hidden rounded bg-ink-800 px-2 py-1 text-ink-200 sm:inline">
            Lv.{{ game.hero.level }} · {{ game.hero.name }}
          </span>
          <RouterLink to="/settings#profile" class="hidden max-w-40 truncate text-ink-400 hover:text-white md:inline" title="个人信息">
            {{ auth.nickname }}
          </RouterLink>
          <button class="text-ink-400 transition hover:text-white" @click="logout">退出</button>
        </div>
      </div>

      <nav aria-label="主导航" class="mx-auto flex w-full min-w-0 max-w-6xl gap-1 overflow-x-auto px-2 pb-2 text-xs md:flex-wrap md:overflow-x-visible">
        <RouterLink
          v-for="nav in navItems"
          :key="nav.to"
          :to="nav.to"
          class="shrink-0 rounded-md px-2.5 py-1.5 transition"
          :class="
            route.path === nav.to
              ? 'bg-amber-500/20 text-amber-200'
              : 'text-ink-400 hover:bg-ink-800 hover:text-ink-200'
          "
        >
          <span class="mr-1">{{ nav.icon }}</span>{{ nav.label }}
        </RouterLink>
      </nav>
    </header>

    <main class="tutorial-layout mx-auto w-full max-w-6xl flex-1 px-3 py-4">
      <div class="min-w-0"><RouterView /></div>
      <TutorialOverlay />
    </main>

    <SiteFooter />

    <ToastStack />
    <LootBubbles />
    <ItemActionDialogs />
    <TagDialog />
  </div>
</template>
