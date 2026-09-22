<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'

import { api } from '@/api'
import { toApiError } from '@/api/client'
import Modal from '@/components/Modal.vue'
import { useGameStore } from '@/stores/game'
import { useToastStore } from '@/stores/toast'
import type { TutorialState } from '@/game/types'

const game = useGameStore()
const toast = useToastStore()
const route = useRoute()
const router = useRouter()

const tutorial = ref<TutorialState | null>(null)
const confirmSkip = ref(false)
const busy = ref(false)

/** 每步对应的页面路由，用于自动导航。 */
const STEP_ROUTE: Record<string, string> = {
  welcome: '/',
  recruitHero: '/tavern',
  viewHero: '/hero',
  enterRegion: '/region',
  watchBattle: '/',
  deathReset: '/',
  defeatBoss: '/',
  openChestEquip: '/equipment',
  drawChest: '/chest',
  craft: '/craft',
  sell: '/inventory',
  refine: '/inventory',
  enchant: '/inventory',
  regionAdvance: '/region',
  rankingOffline: '/ranking',
}

const visible = computed(() => {
  const t = tutorial.value
  if (!t) return false
  return !t.completed && !t.skipped
})

const current = computed(() => tutorial.value?.steps.find((s) => s.step === tutorial.value?.currentStep) ?? null)

const isLast = computed(() => (tutorial.value?.currentStep ?? 1) >= (tutorial.value?.totalSteps ?? 15))

async function load() {
  try {
    tutorial.value = await api.tutorial()
  } catch {
    tutorial.value = null
  }
}

async function next() {
  if (!tutorial.value || busy.value) return
  busy.value = true
  try {
    if (isLast.value) {
      const res = await api.tutorialComplete()
      tutorial.value = { ...tutorial.value, ...res }
      if (res.granted) {
        toast.push(`新手指引完成！获得 ${res.goldGained} 金币与 3 个宝箱`, 'success')
      }
      await game.loadState()
    } else {
      const step = tutorial.value.currentStep + 1
      const res = await api.tutorialStep(step)
      tutorial.value = { ...tutorial.value, ...res }
      await game.loadState()
    }
  } catch (e) {
    toast.push(toApiError(e).message, 'error')
  } finally {
    busy.value = false
  }
}

async function doSkip() {
  if (busy.value || !tutorial.value) return
  busy.value = true
  try {
    const res = await api.tutorialSkip()
    tutorial.value = { ...tutorial.value, ...res }
    confirmSkip.value = false
    toast.push(res.message, 'info')
  } catch (e) {
    toast.push(toApiError(e).message, 'error')
  } finally {
    busy.value = false
  }
}

const collapsed = ref(false)
const panel = ref<HTMLElement | null>(null)
const targetFound = ref(false)
const targetRoute = computed(() => STEP_ROUTE[current.value?.key ?? ''] ?? '/')
const TARGETS: Record<string, string> = {
  welcome: 'battle', recruitHero: 'recruit', viewHero: 'hero',
  enterRegion: 'region', watchBattle: 'battle', deathReset: 'battle', defeatBoss: 'battle',
  openChestEquip: 'equipment', drawChest: 'chest', craft: 'craft',
  sell: 'sell', refine: 'refine', enchant: 'enchant', regionAdvance: 'region', rankingOffline: 'ranking',
}
let highlighted: HTMLElement | null = null
let pendingScroll = false
let mutationObserver: MutationObserver | undefined
let resizeObserver: ResizeObserver | undefined
let frame = 0

function clearHighlight() {
  highlighted?.classList.remove('tutorial-highlight')
  highlighted = null
  targetFound.value = false
}

function refreshTarget() {
  if (!visible.value || route.path !== targetRoute.value) {
    clearHighlight()
    return
  }
  const key = current.value?.key ?? ''
  const container = document.querySelector('.tutorial-layout')
  const target = container?.querySelector<HTMLElement>('[data-tutorial="' + TARGETS[key] + '"]')
    ?? (['sell', 'refine', 'enchant'].includes(key)
      ? container?.querySelector<HTMLElement>('[data-tutorial="inventory"]') : null)
  if (highlighted !== target) {
    clearHighlight()
    highlighted = target ?? null
    highlighted?.classList.add('tutorial-highlight')
  }
  targetFound.value = !!highlighted
  if (highlighted && pendingScroll) {
    pendingScroll = false
    highlighted.scrollIntoView({ block: 'start', behavior: 'instant' })
  }
}

function scheduleTarget() {
  cancelAnimationFrame(frame)
  frame = requestAnimationFrame(refreshTarget)
}

async function locate() {
  if (!visible.value) return
  pendingScroll = true
  if (route.path !== targetRoute.value) await router.push(targetRoute.value)
  await nextTick()
  scheduleTarget()
}

// Only step changes navigate automatically; players can freely visit other pages.
watch([visible, () => current.value?.key], async () => {
  clearHighlight()
  collapsed.value = false
  if (visible.value) await locate()
})
watch(() => route.path, () => {
  pendingScroll = true
  scheduleTarget()
})

function measure() {
  const style = document.documentElement.style
  style.setProperty('--tutorial-panel-height', (panel.value?.getBoundingClientRect().height ?? 0) + 'px')
  style.setProperty('--app-header-height', (document.querySelector('[data-app-header]')?.getBoundingClientRect().height ?? 100) + 'px')
}
watch(panel, (value, previous) => {
  if (previous) resizeObserver?.unobserve(previous)
  if (value) resizeObserver?.observe(value)
  measure()
})
onMounted(() => {
  resizeObserver = new ResizeObserver(measure)
  const header = document.querySelector('[data-app-header]')
  if (header) resizeObserver.observe(header)
  if (panel.value) resizeObserver.observe(panel.value)
  mutationObserver = new MutationObserver(scheduleTarget)
  const content = document.querySelector('.tutorial-layout > div')
  if (content) mutationObserver.observe(content, { childList: true, subtree: true })
  window.addEventListener('resize', scheduleTarget)
  measure()
})
onBeforeUnmount(() => {
  clearHighlight()
  cancelAnimationFrame(frame)
  mutationObserver?.disconnect()
  resizeObserver?.disconnect()
  window.removeEventListener('resize', scheduleTarget)
  document.documentElement.style.removeProperty('--tutorial-panel-height')
  document.documentElement.style.removeProperty('--app-header-height')
})

onMounted(load)
watch(() => game.state?.tutorial, (v) => {
  if (v && tutorial.value) {
    tutorial.value = { ...tutorial.value, currentStep: v.currentStep, completed: v.completed, skipped: v.skipped }
  }
})

defineExpose({ load })
</script>

<template>
  <aside v-if="visible && current" class="tutorial-rail" aria-label="新手指引">
    <section ref="panel" class="tutorial-panel flex flex-col rounded-xl border border-amber-500/50 bg-ink-950 p-3 shadow-xl">
      <header class="flex shrink-0 items-start justify-between gap-2">
        <h2 class="text-sm font-semibold text-amber-200" aria-live="polite">
          新手指引 {{ current.step }}/{{ tutorial?.totalSteps }} · {{ current.title }}
        </h2>
        <button class="shrink-0 px-2 py-1 text-xs text-ink-200" :aria-expanded="!collapsed" aria-controls="tutorial-details" @click="collapsed = !collapsed">
          {{ collapsed ? '展开' : '收起' }}
        </button>
      </header>
      <div v-show="!collapsed" id="tutorial-details" class="mt-2 min-h-0 overflow-y-auto space-y-2 text-xs leading-relaxed">
        <p>{{ current.text }}</p>
        <p class="rounded-md bg-amber-500/10 p-2 text-amber-200">操作提示：{{ current.action }}</p>
        <p class="text-ink-400">可直接操作高亮区域；条件不足时可先了解，再继续下一步。</p>
        <p v-if="route.path !== targetRoute" class="text-amber-200">你已离开本步页面，点击下方按钮可返回。</p>
        <p v-else-if="!targetFound" class="text-ink-400">操作区域尚未显示，请等待页面加载后重新定位。</p>
        <div v-if="current.key === 'openChestEquip'" class="flex gap-3">
          <RouterLink to="/chest" class="text-amber-200 underline">前往抽箱</RouterLink>
          <RouterLink to="/equipment" class="text-amber-200 underline">前往穿戴</RouterLink>
        </div>
        <p class="text-ink-400">完成全部步骤可领取 500 金币与 3 个宝箱（仅一次）。</p>
        <button class="text-ink-400 underline" :disabled="busy" @click="confirmSkip = true">跳过全部指引</button>
      </div>
      <div class="mt-2 flex shrink-0 flex-wrap gap-2">
        <button class="rounded-md bg-ink-700 px-3 py-2 text-xs hover:bg-ink-600" @click="locate">查看操作位置</button>
        <button class="flex-1 rounded-md bg-amber-500 px-3 py-2 text-xs font-medium text-ink-950 hover:bg-amber-400 disabled:opacity-50" :disabled="busy" @click="next">
          {{ busy ? '保存中…' : isLast ? '完成并领取奖励' : current.key === 'welcome' ? '开始冒险' : '了解了，下一步' }}
        </button>
      </div>
    </section>
  </aside>

  <Modal :open="confirmSkip" :z-index="100" title="确认跳过新手指引？" @close="confirmSkip = false">
    <p class="text-sm text-ink-200">
      跳过后续所有步骤后，将<b class="text-rose-300">无法获得</b>指引完成奖励。之后可在「设置 → 新手指引」中重新开启。
    </p>
    <template #footer>
      <button class="rounded-md bg-ink-700 px-3 py-2 text-sm hover:bg-ink-600" @click="confirmSkip = false">
        继续指引
      </button>
      <button class="rounded-md bg-rose-600 px-3 py-2 text-sm text-white hover:bg-rose-500" :disabled="busy" @click="doSkip">
        确认跳过
      </button>
    </template>
  </Modal>
</template>
