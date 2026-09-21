<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'

defineProps<{ title?: string }>()

const open = ref(false)
const btn = ref<HTMLElement | null>(null)
const pos = ref({ top: 0, left: 0, width: 320 })

function toggle() {
  if (open.value) {
    open.value = false
    return
  }
  const rect = btn.value?.getBoundingClientRect()
  if (rect) {
    const width = Math.min(320, window.innerWidth - 16)
    const left = Math.min(Math.max(8, rect.left), Math.max(8, window.innerWidth - width - 8))
    const top =
      rect.bottom + 6 + 200 > window.innerHeight
        ? Math.max(8, rect.top - 206)
        : rect.bottom + 6
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
        class="fixed z-[80] space-y-1 rounded-lg border border-ink-600 bg-ink-900 p-3 text-[11px] leading-relaxed text-ink-300 shadow-xl"
        :style="{ top: `${pos.top}px`, left: `${pos.left}px`, width: `${pos.width}px` }"
      >
        <p v-if="title" class="text-xs font-semibold text-ink-100">{{ title }}</p>
        <slot />
      </div>
    </Teleport>
  </span>
</template>
