<script setup lang="ts">
import { computed, onMounted, onUnmounted, watch } from 'vue'
import { RouterLink, RouterView, useRoute, useRouter } from 'vue-router'

import { api } from '@/api'
import BuffDock from '@/components/BuffDock.vue'
import ItemActionDialogs from '@/components/ItemActionDialogs.vue'
import LootBubbles from '@/components/LootBubbles.vue'
import SiteFooter from '@/components/SiteFooter.vue'
import TagDialog from '@/components/TagDialog.vue'
import ToastStack from '@/components/ToastStack.vue'
import TutorialOverlay from '@/components/TutorialOverlay.vue'
import VersionAnnouncementModal from '@/components/VersionAnnouncementModal.vue'
import { useAnnouncementStore } from '@/stores/announcement'
import { useAuthStore } from '@/stores/auth'
import { useDohDolStore } from '@/stores/dohdol'
import { useGameStore } from '@/stores/game'
import { useSoundStore } from '@/stores/sound'
import { useTreasureStore } from '@/stores/treasure'
import { APP_VERSION } from '@/version'

const announcement = useAnnouncementStore()
const auth = useAuthStore()
const game = useGameStore()
const sound = useSoundStore()
const dohdol = useDohDolStore()
const treasure = useTreasureStore()
const route = useRoute()
const router = useRouter()

const isPublicOnly = computed(() => route.name === 'login')

const NAV = [
  { to: '/', label: '战斗', icon: '⚔' },
  { to: '/equipment', label: '装备', icon: '🛡' },
  { to: '/inventory', label: '背包', icon: '🎒' },
  { to: '/market', label: '市场', icon: '🏪' },
  { to: '/chest', label: '抽箱', icon: '📦' },
  { to: '/craft', label: '合成', icon: '⚗' },
  { to: '/gather', label: '采集', icon: '⛏' },
  { to: '/produce', label: '生产', icon: '🔨' },
  { to: '/fish', label: '钓鱼', icon: '🎣' },
  { to: '/roster', label: '名册', icon: '👥' },
  { to: '/coop', label: '远征', icon: '⚑' },
  { to: '/worldboss', label: '世界BOSS', icon: '🐲' },
  { to: '/arena', label: '竞技场', icon: '⚔' },
  { to: '/hero', label: '英雄', icon: '🧙' },
  { to: '/region', label: '地区', icon: '🗺' },
  { to: '/raid', label: '高难', icon: '☠' },
  { to: '/treasure', label: '挖宝', icon: '🏺' },
  { to: '/materia', label: '魔晶石', icon: '💎' },
  { to: '/farm', label: '种田', icon: '🌱' },
  { to: '/tavern', label: '酒馆', icon: '🍺' },
  { to: '/codex', label: '图鉴', icon: '📖' },
  { to: '/ranking', label: '排行', icon: '🏆' },
  { to: '/grants', label: '补偿公示', icon: '📢' },
  { to: '/friends', label: '好友', icon: '🤝' },
  { to: '/chat', label: '聊天室', icon: '💬' },
  { to: '/settings', label: '设置', icon: '⚙' },
  { to: '/gametest', label: '游戏测试', icon: '🎮' },
]

/** 管理入口只对管理员可见。 */
const navItems = computed(() =>
  auth.isAdmin ? [...NAV, { to: '/admin', label: '管理', icon: '🔧' }] : NAV,
)

// 版本更新公告：已登录且版本号变化时弹出一次。
// App 是根组件，登录不会重新挂载，故用 watch（而非 onMounted）覆盖「登录后」与「刷新时」两种情况。
watch(
  () => auth.isLoggedIn,
  (loggedIn) => {
    if (loggedIn) announcement.maybeShow()
  },
  { immediate: true },
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

// 同一设备并发在线超限：立即停掉本账号全部后台循环；关闭其他账号后由心跳自动恢复。
watch(
  () => auth.deviceBlocked,
  (blocked) => {
    if (!blocked) return
    void game.stopBattle(true)
    void game.stopRaid(true)
    void dohdol.stop(true)
    treasure.leave()
  },
)

/** 好友在线心跳：登录后在任意页面（含后台标签页可见时）定期上报，好友据此看到在线状态。 */
const HEARTBEAT_MS = 20000
let heartbeatTimer: number | undefined

function heartbeat() {
  if (!auth.isLoggedIn || document.visibilityState !== 'visible') return
  void api
    .friendHeartbeat()
    .then((res) => {
      // 反多开：服务端按「同一设备并发在线」下发暂停状态，前端据此暂停 / 恢复本地循环。
      auth.deviceBlocked = res.blocked
      auth.deviceLimit = res.maxOnline
    })
    .catch(() => {})
}

/** 浏览器自动播放策略：必须在首个用户手势里解锁 AudioContext，之后音效才会出声。 */
function unlockSound() {
  sound.unlock()
  window.removeEventListener('pointerdown', unlockSound)
  window.removeEventListener('keydown', unlockSound)
}

onMounted(async () => {
  if (auth.isLoggedIn) {
    await auth.loadProfile()
    await game.loadState()
  }
  heartbeat()
  heartbeatTimer = window.setInterval(heartbeat, HEARTBEAT_MS)
  window.addEventListener('pointerdown', unlockSound)
  window.addEventListener('keydown', unlockSound)
})

onUnmounted(() => {
  if (heartbeatTimer) window.clearInterval(heartbeatTimer)
  window.removeEventListener('pointerdown', unlockSound)
  window.removeEventListener('keydown', unlockSound)
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
        <button
          class="rounded bg-ink-800 px-1.5 py-0.5 font-mono text-[10px] text-ink-400 transition hover:text-amber-200"
          title="当前版本 · 点击查看更新公告"
          @click="announcement.open = true"
        >
          V{{ APP_VERSION }}
        </button>

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

    <!-- 反多开：同一设备并发在线超限时本账号被暂停，关闭其他账号后自动恢复 -->
    <div
      v-if="auth.deviceBlocked"
      role="status"
      class="border-b border-amber-500/40 bg-amber-500/10 px-3 py-2 text-center text-xs text-amber-200"
    >
      同一设备同时仅允许 {{ auth.deviceLimit || 1 }} 个账号在线，本账号已暂停；关闭其他账号后将自动恢复。
    </div>

    <main class="tutorial-layout mx-auto w-full max-w-6xl flex-1 px-3 py-4">
      <div class="min-w-0"><RouterView /></div>
      <TutorialOverlay />
    </main>

    <SiteFooter />

    <VersionAnnouncementModal />
    <ToastStack />
    <LootBubbles />
    <BuffDock />
    <ItemActionDialogs />
    <TagDialog />
  </div>
</template>
