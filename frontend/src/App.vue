<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { RouterLink, RouterView, useRoute, useRouter } from 'vue-router'

import { api } from '@/api'
import BuffDock from '@/components/BuffDock.vue'
import ConfirmDialog from '@/components/ConfirmDialog.vue'
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
import { groupForPath, itemForPath, visibleGroups } from '@/navigation'
import { installSafeAreaSync } from '@/utils/safeArea'
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

// ---------- 顶部导航：桌面端分组下拉 + 移动端抽屉 ----------

/** 当前身份可见的分组（「管理」仅管理员可见）。 */
const groups = computed(() => visibleGroups(auth.isAdmin))
/** 当前页所属分组（高亮一级菜单）与当前页名（窄屏标题旁显示）。 */
const activeGroupId = computed(() => groupForPath(route.path)?.id ?? null)
const currentLabel = computed(() => itemForPath(route.path)?.label ?? '')

/** 桌面端展开的分组；移动端抽屉开合与已展开分组。 */
const openGroup = ref<string | null>(null)
const drawerOpen = ref(false)
const expandedGroups = ref<Set<string>>(new Set())

function toggleGroup(id: string) {
  openGroup.value = openGroup.value === id ? null : id
}

function closeGroup() {
  openGroup.value = null
}

function openDrawer() {
  // 打开时只展开当前页所属分组，其余收起，方便一眼扫到全部分类。
  expandedGroups.value = new Set(activeGroupId.value ? [activeGroupId.value] : [])
  closeGroup()
  drawerOpen.value = true
}

function toggleDrawerGroup(id: string) {
  const next = new Set(expandedGroups.value)
  if (next.has(id)) next.delete(id)
  else next.add(id)
  expandedGroups.value = next
}

function closeDrawer() {
  drawerOpen.value = false
}

/** 点导航区域外空白处收起桌面下拉（抽屉自带遮罩，不受影响）。 */
function onDocumentClick(event: MouseEvent) {
  const target = event.target as HTMLElement | null
  if (!target?.closest('[data-nav-group]')) closeGroup()
}

function onKeydown(event: KeyboardEvent) {
  if (event.key !== 'Escape') return
  closeGroup()
  closeDrawer()
}

// 跳转页面后收起所有菜单，避免残留展开的浮层。
watch(
  () => route.path,
  () => {
    closeGroup()
    closeDrawer()
  },
)

// 抽屉打开时锁定页面滚动，避免背景跟着滑动。
watch(drawerOpen, (open) => {
  document.documentElement.style.overflow = open ? 'hidden' : ''
})

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

/** 全面屏安全区同步的清理函数（见 utils/safeArea.ts）。 */
let disposeSafeAreaSync: (() => void) | undefined

onMounted(async () => {
  if (auth.isLoggedIn) {
    await auth.loadProfile()
    await game.loadState()
  }
  heartbeat()
  heartbeatTimer = window.setInterval(heartbeat, HEARTBEAT_MS)
  window.addEventListener('pointerdown', unlockSound)
  window.addEventListener('keydown', unlockSound)
  document.addEventListener('click', onDocumentClick)
  document.addEventListener('keydown', onKeydown)
  // 全面屏适配：读安全区（原生注入优先）并同步 <html> class，尺寸/旋转/注入变化时重算。
  disposeSafeAreaSync = installSafeAreaSync()
})

onUnmounted(() => {
  if (heartbeatTimer) window.clearInterval(heartbeatTimer)
  window.removeEventListener('pointerdown', unlockSound)
  window.removeEventListener('keydown', unlockSound)
  document.removeEventListener('click', onDocumentClick)
  document.removeEventListener('keydown', onKeydown)
  disposeSafeAreaSync?.()
  document.documentElement.style.overflow = ''
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
      <div class="mx-auto flex max-w-6xl items-center gap-2 px-3 py-2">
        <!-- 移动端：汉堡按钮 + 当前页名（页头只留最常用信息，其余收进抽屉） -->
        <button
          class="-ml-1 grid h-9 w-9 shrink-0 place-items-center rounded-md text-base text-ink-200 transition hover:bg-ink-800 md:hidden"
          :aria-expanded="drawerOpen"
          aria-controls="app-nav-drawer"
          aria-label="打开导航菜单"
          @click.stop="openDrawer"
        >
          ☰
        </button>
        <RouterLink to="/" class="shrink-0 text-sm font-bold tracking-wide text-amber-200">
          艾欧泽亚放置录
        </RouterLink>
        <span v-if="currentLabel" class="truncate text-xs text-ink-400 md:hidden">{{ currentLabel }}</span>
        <button
          class="shrink-0 rounded bg-ink-800 px-1.5 py-0.5 font-mono text-[10px] text-ink-400 transition hover:text-amber-200"
          title="当前版本 · 点击查看更新公告"
          @click="announcement.open = true"
        >
          V{{ APP_VERSION }}
        </button>

        <div class="ml-auto flex shrink-0 items-center gap-3 text-xs">
          <span class="rounded bg-ink-800 px-2 py-1 font-mono text-amber-300">
            💰 {{ game.gold.toLocaleString() }}
          </span>
          <span v-if="game.hero" class="hidden rounded bg-ink-800 px-2 py-1 text-ink-200 sm:inline">
            Lv.{{ game.hero.level }} · {{ game.hero.name }}
          </span>
          <RouterLink to="/settings#profile" class="hidden max-w-40 truncate text-ink-400 hover:text-white md:inline" title="个人信息">
            {{ auth.nickname }}
          </RouterLink>
          <button class="hidden text-ink-400 transition hover:text-white md:inline" @click="logout">退出</button>
        </div>
      </div>

      <!-- 桌面端：一级分组 + 二级下拉（组内小标题 = 三级菜单） -->
      <nav aria-label="主导航" class="relative mx-auto hidden w-full max-w-6xl gap-1 px-2 pb-2 text-xs md:flex">
        <div v-for="group in groups" :key="group.id" data-nav-group class="relative">
          <button
            class="flex items-center rounded-md px-2.5 py-1.5 transition"
            :class="
              activeGroupId === group.id || openGroup === group.id
                ? 'bg-amber-500/20 text-amber-200'
                : 'text-ink-400 hover:bg-ink-800 hover:text-ink-200'
            "
            :aria-expanded="openGroup === group.id"
            aria-haspopup="true"
            @click.stop="toggleGroup(group.id)"
          >
            <span class="mr-1">{{ group.icon }}</span>{{ group.label }}
            <span class="ml-1 text-[9px] opacity-70">{{ openGroup === group.id ? '▴' : '▾' }}</span>
          </button>

          <div
            v-if="openGroup === group.id"
            class="absolute left-0 top-full z-50 mt-1 min-w-44 rounded-lg border border-ink-700 bg-ink-900 p-2 shadow-xl"
          >
            <template v-for="(section, index) in group.sections" :key="section.title ?? index">
              <p v-if="section.title" class="px-2 pb-1 pt-1 text-[10px] text-ink-500">{{ section.title }}</p>
              <RouterLink
                v-for="item in section.items"
                :key="item.to"
                :to="item.to"
                class="flex min-h-9 items-center gap-2 rounded px-2 py-1.5 transition"
                :class="
                  route.path === item.to ? 'bg-amber-500/20 text-amber-200' : 'text-ink-200 hover:bg-ink-800'
                "
              >
                <span class="w-4 shrink-0 text-center">{{ item.icon }}</span>{{ item.label }}
              </RouterLink>
            </template>
          </div>
        </div>
      </nav>
    </header>

    <!-- 移动端导航抽屉：分组折叠，打开时展开当前页所属分组 -->
    <Teleport to="body">
      <div v-if="drawerOpen" class="fixed inset-0 z-[90] md:hidden">
        <div class="absolute inset-0 bg-black/60" @click="closeDrawer"></div>
        <aside
          id="app-nav-drawer"
          role="dialog"
          aria-label="导航菜单"
          class="absolute inset-y-0 left-0 flex w-[84%] max-w-sm flex-col border-r border-ink-700 bg-ink-950 shadow-2xl"
        >
          <div
            class="flex items-center gap-2 border-b border-ink-700 px-3 py-3"
            :style="{ paddingTop: 'max(12px, var(--app-safe-top))' }"
          >
            <span class="text-sm font-bold tracking-wide text-amber-200">导航</span>
            <span class="rounded bg-ink-800 px-1.5 py-0.5 font-mono text-[10px] text-ink-400">
              V{{ APP_VERSION }}
            </span>
            <button
              class="ml-auto grid h-9 w-9 place-items-center rounded-md text-lg text-ink-300 transition hover:bg-ink-800"
              aria-label="关闭导航菜单"
              @click="closeDrawer"
            >
              ✕
            </button>
          </div>

          <nav class="flex-1 space-y-1 overflow-y-auto p-2 text-sm">
            <div v-for="group in groups" :key="group.id">
              <button
                class="flex min-h-11 w-full items-center gap-2 rounded-md px-3 text-left transition"
                :class="
                  activeGroupId === group.id ? 'bg-amber-500/15 text-amber-200' : 'text-ink-200 hover:bg-ink-900'
                "
                :aria-expanded="expandedGroups.has(group.id)"
                @click="toggleDrawerGroup(group.id)"
              >
                <span>{{ group.icon }}</span>
                <span class="flex-1">{{ group.label }}</span>
                <span class="text-[10px] opacity-70">{{ expandedGroups.has(group.id) ? '▴' : '▾' }}</span>
              </button>

              <div v-if="expandedGroups.has(group.id)" class="mt-0.5 space-y-0.5 pb-1">
                <template v-for="(section, index) in group.sections" :key="section.title ?? index">
                  <p v-if="section.title" class="px-4 pt-1 text-[10px] text-ink-500">{{ section.title }}</p>
                  <RouterLink
                    v-for="item in section.items"
                    :key="item.to"
                    :to="item.to"
                    class="flex min-h-11 items-center gap-2 rounded-md px-3 pl-6 text-sm transition"
                    :class="
                      route.path === item.to ? 'bg-amber-500/20 text-amber-200' : 'text-ink-300 hover:bg-ink-900'
                    "
                    @click="closeDrawer"
                  >
                    <span class="w-4 shrink-0 text-center">{{ item.icon }}</span>{{ item.label }}
                  </RouterLink>
                </template>
              </div>
            </div>
          </nav>

          <div
            class="space-y-2 border-t border-ink-700 px-3 py-3 text-xs"
            :style="{ paddingBottom: 'max(12px, var(--app-safe-bottom))' }"
          >
            <div class="flex items-center justify-between gap-2 text-ink-300">
              <RouterLink to="/settings#profile" class="min-w-0 truncate hover:text-white" @click="closeDrawer">
                {{ auth.nickname }}
              </RouterLink>
              <span v-if="game.hero" class="shrink-0 font-mono text-ink-400">
                Lv.{{ game.hero.level }} · {{ game.hero.name }}
              </span>
            </div>
            <button
              class="min-h-11 w-full rounded-md bg-ink-800 text-sm text-ink-200 transition hover:bg-ink-700"
              @click="logout"
            >
              退出登录
            </button>
          </div>
        </aside>
      </div>
    </Teleport>

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
    <ConfirmDialog />
    <TagDialog />
  </div>
</template>
