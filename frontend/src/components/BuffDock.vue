<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'

import ItemIcon from '@/components/ItemIcon.vue'
import type { ActiveConsumable } from '@/game/types'
import { useDohDolStore } from '@/stores/dohdol'
import { useGameStore } from '@/stores/game'
import { consumableBonus } from '@/utils/consumables'
import { clampToViewport, readSafeArea } from '@/utils/safeArea'

/**
 * 食物 / 秘药 BUFF 悬浮窗：全站常驻，可拖动、可最小化，位置与折叠状态记在 localStorage。
 * 剩余时长按服务端绝对到期时间 `expiresAt` 本地每秒重算，归零后自动刷新状态（后端顺带清理过期行）。
 * 每行提供「续期」按钮：消耗背包中同种物品，在同槽位上叠加一份时长（需持有该物品）。
 */
const game = useGameStore()
const dohdol = useDohDolStore()

const POS_KEY = 'eorzea.buffdock.pos'
const COLLAPSED_KEY = 'eorzea.buffdock.collapsed'
const MARGIN = 8

interface DockBuff {
  kind: string
  itemId: string
  name: string
  remaining: number
  /** 进度条基准（叠加使用时长会抬高）。 */
  total: number
}

const el = ref<HTMLElement | null>(null)
const nowMs = ref(Date.now())
/** 每个槽位的进度条基准；同槽位换物品时重置，同类叠加时抬高到新的剩余时长。 */
const totals = ref<Record<string, { itemId: string; total: number }>>({})

const active = computed(() => game.state?.dohdol?.active ?? [])

function remainingOf(buff: ActiveConsumable, at: number): number {
  const end = Date.parse(buff.expiresAt)
  return Number.isFinite(end) ? Math.max(0, Math.ceil((end - at) / 1000)) : buff.remainingSec
}

const buffs = computed<DockBuff[]>(() =>
  active.value.map((b) => {
    const remaining = remainingOf(b, nowMs.value)
    return {
      kind: b.kind,
      itemId: b.itemId,
      name: b.name,
      remaining,
      total: totals.value[b.kind]?.total ?? remaining,
    }
  }),
)

const nextExpiry = computed(() => Math.min(...buffs.value.map((b) => b.remaining)))

function mmss(seconds: number): string {
  const safe = Number.isFinite(seconds) ? Math.max(0, seconds) : 0
  const m = Math.floor(safe / 60)
  return `${m}:${String(safe % 60).padStart(2, '0')}`
}

function progressPct(buff: DockBuff): number {
  return Math.round(Math.min(1, buff.remaining / Math.max(1, buff.total)) * 100)
}

// ---------- 续期 ----------

/** 各消耗品的持有数量（用于判断能否续期）。 */
const owned = computed<Map<string, number>>(
  () => new Map((game.state?.dohdol?.consumables ?? []).map((c) => [c.itemId, c.count])),
)
const renewing = ref(false)

/** 消耗 1 个同种物品为对应槽位续期（同槽位叠加时长）；未持有则按钮置灰。 */
async function renew(itemId: string) {
  if (renewing.value || (owned.value.get(itemId) ?? 0) <= 0) return
  renewing.value = true
  try {
    await dohdol.useConsumable(itemId)
  } catch {
    /* 服务端会在持有不足时返回 400；这里静默，按钮状态随状态刷新恢复。 */
  } finally {
    renewing.value = false
  }
}

// ---------- 位置与折叠 ----------

function loadPos(): { x: number; y: number } | null {
  try {
    const parsed = JSON.parse(localStorage.getItem(POS_KEY) ?? 'null')
    if (typeof parsed?.x === 'number' && typeof parsed?.y === 'number') return { x: parsed.x, y: parsed.y }
  } catch {
    /* 忽略损坏的本地存储 */
  }
  return null
}

const pos = ref<{ x: number; y: number } | null>(loadPos())
const collapsed = ref(localStorage.getItem(COLLAPSED_KEY) === '1')

function clampPos() {
  const current = pos.value
  if (!current) return
  const w = el.value?.offsetWidth ?? 190
  const h = el.value?.offsetHeight ?? 44
  // 收进安全区：不让悬浮窗被状态栏 / 手势条 / 刘海盖住（桌面安全区为 0，等价于原来的行为）。
  const clamped = clampToViewport({ left: current.x, top: current.y }, { width: w, height: h }, MARGIN)
  pos.value = { x: clamped.left, y: clamped.top }
}

let dragging = false
let dragOffset = { x: 0, y: 0 }

function onPointerDown(event: PointerEvent) {
  if (event.pointerType === 'mouse' && event.button !== 0) return
  const current = pos.value
  if (!current) return
  dragging = true
  dragOffset = { x: event.clientX - current.x, y: event.clientY - current.y }
  window.addEventListener('pointermove', onPointerMove)
  window.addEventListener('pointerup', onPointerUp)
  event.preventDefault()
}

function onPointerMove(event: PointerEvent) {
  if (!dragging) return
  pos.value = { x: event.clientX - dragOffset.x, y: event.clientY - dragOffset.y }
  clampPos()
}

function onPointerUp() {
  dragging = false
  window.removeEventListener('pointermove', onPointerMove)
  window.removeEventListener('pointerup', onPointerUp)
  if (pos.value) localStorage.setItem(POS_KEY, JSON.stringify(pos.value))
}

function toggleCollapsed() {
  collapsed.value = !collapsed.value
  localStorage.setItem(COLLAPSED_KEY, collapsed.value ? '1' : '0')
}

// ---------- 生命周期 ----------

let tickTimer: number | undefined

onMounted(() => {
  if (!pos.value) {
    // 默认落在左下角，且让出状态栏 / 手势条（安全区在全面屏上非 0）。
    const area = readSafeArea()
    pos.value = {
      x: area.left + MARGIN + 4,
      y: Math.max(area.top + MARGIN, window.innerHeight - area.bottom - 180),
    }
  }
  clampPos()
  window.addEventListener('resize', clampPos)
  tickTimer = window.setInterval(() => (nowMs.value = Date.now()), 1000)
})

onUnmounted(() => {
  if (tickTimer !== undefined) window.clearInterval(tickTimer)
  window.removeEventListener('resize', clampPos)
  window.removeEventListener('pointermove', onPointerMove)
  window.removeEventListener('pointerup', onPointerUp)
})

// 生效中的药水 / 食物集合变化时重建进度基准。
watch(
  active,
  (list) => {
    const next: Record<string, { itemId: string; total: number }> = {}
    for (const b of list) {
      const remaining = remainingOf(b, nowMs.value)
      const prev = totals.value[b.kind]
      next[b.kind] =
        prev && prev.itemId === b.itemId
          ? { itemId: b.itemId, total: Math.max(prev.total, remaining) }
          : { itemId: b.itemId, total: remaining }
    }
    totals.value = next
  },
  { immediate: true, deep: true },
)

// 倒计时归零后刷新状态（后端会清理过期行）。
watch(
  () => buffs.value.some((b) => b.remaining <= 0),
  (expired) => {
    if (expired) void game.loadState({ force: true })
  },
)
</script>

<template>
  <div
    v-if="buffs.length"
    ref="el"
    class="fixed z-[60] select-none"
    :style="
      pos
        ? { left: `${pos.x}px`, top: `${pos.y}px` }
        : { left: 'calc(12px + var(--app-safe-left))', bottom: 'calc(96px + var(--app-safe-bottom))' }
    "
  >
    <div class="overflow-hidden rounded-lg border border-emerald-500/30 bg-ink-950/90 shadow-lg backdrop-blur">
      <div
        class="flex cursor-move items-center gap-2 border-b border-emerald-500/20 bg-emerald-500/10 px-2 py-1 text-[11px] text-emerald-200"
        style="touch-action: none"
        @pointerdown="onPointerDown"
      >
        <span class="font-semibold">生效中</span>
        <span v-if="collapsed" class="font-mono">{{ mmss(nextExpiry) }}</span>
        <button
          class="ml-auto rounded px-1 text-emerald-200/80 hover:text-white"
          :title="collapsed ? '展开' : '收起'"
          @pointerdown.stop
          @click="toggleCollapsed"
        >
          {{ collapsed ? '▲' : '▼' }}
        </button>
      </div>

      <div v-if="!collapsed" class="w-56 space-y-2 p-2">
        <div v-for="b in buffs" :key="b.kind" class="text-[11px]" :title="consumableBonus(b.itemId)">
          <div class="flex items-center gap-1.5">
            <ItemIcon :base-id="b.itemId" variant="plain" :size="18" />
            <span class="min-w-0 flex-1 truncate text-ink-100">{{ b.name }}</span>
            <span class="shrink-0 font-mono text-emerald-300">{{ mmss(b.remaining) }}</span>
          </div>
          <div class="mt-1 flex items-center gap-1.5">
            <div class="h-1 min-w-0 flex-1 overflow-hidden rounded bg-ink-800">
              <div class="h-full rounded bg-emerald-500/70" :style="{ width: `${progressPct(b)}%` }"></div>
            </div>
            <button
              class="shrink-0 rounded bg-emerald-600/80 px-1.5 py-0.5 text-[10px] leading-none text-white transition hover:bg-emerald-500 disabled:cursor-not-allowed disabled:opacity-40"
              :disabled="renewing || (owned.get(b.itemId) ?? 0) <= 0"
              :title="
                (owned.get(b.itemId) ?? 0) > 0
                  ? `续期：消耗 1 个「${b.name}」叠加一份时长（持有 ${owned.get(b.itemId)}）`
                  : '背包中没有该物品，无法续期'
              "
              @pointerdown.stop
              @click.stop="renew(b.itemId)"
            >
              续期 ×{{ owned.get(b.itemId) ?? 0 }}
            </button>
          </div>
        </div>
      </div>

      <div v-else class="flex items-center gap-1 px-2 py-1">
        <ItemIcon v-for="b in buffs" :key="b.kind" :base-id="b.itemId" variant="plain" :size="18" />
      </div>
    </div>
  </div>
</template>
