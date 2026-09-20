<script setup lang="ts">
import { useToastStore } from '@/stores/toast'

const toast = useToastStore()

const toneClass: Record<string, string> = {
  info: 'border-ink-600 bg-ink-800 text-ink-200',
  success: 'border-emerald-500/60 bg-emerald-500/10 text-emerald-200',
  error: 'border-rose-500/60 bg-rose-500/10 text-rose-200',
  loot: 'border-amber-400/60 bg-amber-400/10 text-amber-100',
}
</script>

<template>
  <div class="pointer-events-none fixed inset-x-0 top-3 z-[110] flex flex-col items-center gap-2 px-3">
    <TransitionGroup name="toast">
      <div
        v-for="item in toast.items"
        :key="item.id"
        class="pointer-events-auto animate-rise max-w-md rounded-lg border px-4 py-2 text-sm shadow-lg"
        :class="toneClass[item.tone]"
        @click="toast.dismiss(item.id)"
      >
        {{ item.text }}
      </div>
    </TransitionGroup>
  </div>
</template>

<style scoped>
.toast-enter-active,
.toast-leave-active {
  transition: all 0.2s ease;
}
.toast-enter-from,
.toast-leave-to {
  opacity: 0;
  transform: translateY(-8px);
}
</style>
