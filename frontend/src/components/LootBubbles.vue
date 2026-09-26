<script setup lang="ts">
import ItemIcon from '@/components/ItemIcon.vue'
import { useLootStore } from '@/stores/loot'
import { rarityClass, rarityName } from '@/utils/format'

const loot = useLootStore()
</script>

<template>
  <!-- 右下角避让：手势条 / 刘海区域不放内容（--app-safe-* 见 style.css） -->
  <div
    class="pointer-events-none fixed z-[105] flex w-72 flex-col items-end gap-2"
    :style="{
      bottom: 'calc(1rem + var(--app-safe-bottom))',
      right: 'calc(1rem + var(--app-safe-right))',
    }"
  >
    <TransitionGroup name="bubble">
      <div
        v-for="bubble in loot.bubbles"
        :key="bubble.id"
        class="pointer-events-auto flex max-w-full animate-rise items-center gap-2 rounded-2xl border border-amber-400/40 bg-ink-900/90 px-3 py-1.5 shadow-lg backdrop-blur"
        @click="loot.dismiss(bubble.id)"
      >
        <ItemIcon :base-id="bubble.baseId" :rarity="bubble.rarity" :size="18" />
        <span class="min-w-0">
          <span class="block truncate text-xs font-medium" :class="rarityClass(bubble.rarity)">
            {{ bubble.name }}
          </span>
          <span class="block text-[10px] text-ink-400">
            {{ bubble.note ?? rarityName(bubble.rarity) }}
          </span>
        </span>
      </div>
    </TransitionGroup>
  </div>
</template>

<style scoped>
.bubble-enter-active,
.bubble-leave-active {
  transition: all 0.3s ease;
}
.bubble-enter-from,
.bubble-leave-to {
  opacity: 0;
  transform: translateY(8px) scale(0.95);
}
</style>
