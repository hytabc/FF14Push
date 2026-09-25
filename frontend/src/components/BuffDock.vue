<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'

import ItemIcon from '@/components/ItemIcon.vue'
import type { ActiveConsumable } from '@/game/types'
import { useGameStore } from '@/stores/game'
import { consumableBonus } from '@/utils/consumables'

/**
 * 食物 / 秘药 BUFF 悬浮窗：全站常驻，可拖动、可最小化，位置与折叠状态记在 localStorage。
 * 剩余时长按服务端绝对到期时间 `expiresAt` 本地每秒重算，归零后自动刷新状态（后端顺带清理过期行）。
 */
const game = useGameStore()

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
  const maxX = Math.max(MARGIN, window.innerWidth - w - MARGIN)
  const maxY = Math.max(MARGIN, window.innerHeight - h - MARGIN)
  pos.value = {
    x: Math.min(Math.max(MARGIN, current.x), maxX),
    y: Math.min(Math.max(MARGIN, current.y), maxY),
  }
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
  if (!pos.value) pos.value = { x: MARGIN + 4, y: Math.max(MARGIN, window.innerHeight - 180) }
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
    :style="pos ? { left: `${pos.x}px`, top: `${pos.y}px` } : { left: '12px', bottom: '96px' }"
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
          <div class="mt-1 h-1 overflow-hidden rounded bg-ink-800">
            <div class="h-full rounded bg-emerald-500/70" :style="{ width: `${progressPct(b)}%` }"></div>
          </div>
        </div>
      </div>

      <div v-else class="flex items-center gap-1 px-2 py-1">
        <ItemIcon v-for="b in buffs" :key="b.kind" :base-id="b.itemId" variant="plain" :size="18" />
      </div>
    </div>
  </div>
</template>
