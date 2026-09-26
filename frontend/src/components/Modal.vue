<script setup lang="ts">
import { watch } from 'vue'

import { sound } from '@/game/audio'

const props = withDefaults(
  defineProps<{
    title?: string
    open: boolean
    maxWidth?: string
    zIndex?: number
    /** 面板是否使用毛玻璃背景。内部有大量动画子元素时关掉可避免反复重算模糊。 */
    blur?: boolean
  }>(),
  { title: '', maxWidth: 'max-w-lg', zIndex: 70, blur: true },
)

const emit = defineEmits<{ close: [] }>()

// 弹窗开关音：所有 Modal 共用，统一界面反馈。
watch(
  () => props.open,
  (open) => sound.play(open ? 'ui.modal.open' : 'ui.modal.close'),
)
</script>

<template>
  <Teleport to="body">
    <Transition name="fade">
      <div
        v-if="open"
        class="fixed inset-0 flex items-center justify-center bg-black/60"
        :style="{
          zIndex,
          paddingTop: 'max(1rem, var(--app-safe-top))',
          paddingBottom: 'max(1rem, var(--app-safe-bottom))',
          paddingLeft: 'max(1rem, var(--app-safe-left))',
          paddingRight: 'max(1rem, var(--app-safe-right))',
        }"
        @click.self="emit('close')"
      >
        <div
          class="flex max-h-full w-full animate-rise flex-col p-5"
          :class="[blur ? 'card' : 'card-flat', maxWidth]"
        >
          <header v-if="title" class="mb-3 flex shrink-0 items-center justify-between">
            <h2 class="text-lg font-semibold text-white">{{ title }}</h2>
            <button class="text-ink-400 transition hover:text-white" @click="emit('close')">✕</button>
          </header>
          <div class="min-h-0 flex-1 overflow-y-auto">
            <slot />
          </div>
          <footer v-if="$slots.footer" class="mt-4 flex shrink-0 justify-end gap-2">
            <slot name="footer" />
          </footer>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.18s ease;
}
.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}
</style>
