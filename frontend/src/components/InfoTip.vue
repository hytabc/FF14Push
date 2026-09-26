<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'

import { clampToViewport, readSafeArea } from '@/utils/safeArea'

defineProps<{ title?: string }>()

const open = ref(false)
const btn = ref<HTMLElement | null>(null)
const pos = ref({ top: 0, left: 0, width: 320 })

/** 面板高度的估算值，仅用于「下方放不下就向上弹」与安全区夹取。 */
const PANEL_HEIGHT = 200

function toggle() {
  if (open.value) {
    open.value = false
    return
  }
  const rect = btn.value?.getBoundingClientRect()
  if (rect) {
    const area = readSafeArea()
    // 宽度同时避开左右刘海（横屏）。
    const width = Math.min(320, window.innerWidth - area.left - area.right - 16)
    const below = rect.bottom + 6
    const desiredTop = below + PANEL_HEIGHT > window.innerHeight ? rect.top - 6 - PANEL_HEIGHT : below
    // 统一收进安全区：不让说明卡被状态栏 / 手势条 / 刘海遮住。
    const { top, left } = clampToViewport({ left: rect.left, top: desiredTop }, { width, height: PANEL_HEIGHT })
    pos.value = { top, left, width }
  }
  open.value = true
}

function onKey(e: KeyboardEvent) {
  if (e.key === 'Escape') open.value = false
}
function onScroll() {
  open.value = false
}

onMounted(() => {
  window.addEventListener('keydown', onKey)
  window.addEventListener('scroll', onScroll, true)
})
onBeforeUnmount(() => {
  window.removeEventListener('keydown', onKey)
  window.removeEventListener('scroll', onScroll, true)
})
</script>

<template>
  <span class="inline-flex align-middle">
    <button
      ref="btn"
      type="button"
      class="ml-1 inline-flex h-3.5 w-3.5 shrink-0 items-center justify-center rounded-full border border-ink-500 text-[9px] leading-none text-ink-400 transition hover:border-amber-400 hover:text-amber-300"
      title="查看该数值的计算方式"
      @click.stop="toggle"
    >
      ?
    </button>
    <Teleport to="body">
      <div v-if="open" class="fixed inset-0 z-[79]" @click="open = false" />
      <div
        v-if="open"
        class="fixed z-[80] max-h-[60vh] space-y-1 overflow-y-auto overscroll-contain rounded-lg border border-ink-600 bg-ink-900 p-3 text-[11px] leading-relaxed text-ink-300 shadow-xl"
        :style="{ top: `${pos.top}px`, left: `${pos.left}px`, width: `${pos.width}px` }"
      >
        <p v-if="title" class="text-xs font-semibold text-ink-100">{{ title }}</p>
        <slot />
      </div>
    </Teleport>
  </span>
</template>
