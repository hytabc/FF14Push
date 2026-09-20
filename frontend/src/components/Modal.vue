<script setup lang="ts">
withDefaults(
  defineProps<{
    title?: string
    open: boolean
    maxWidth?: string
  }>(),
  { title: '', maxWidth: 'max-w-lg' },
)

const emit = defineEmits<{ close: [] }>()
</script>

<template>
  <Teleport to="body">
    <Transition name="fade">
      <div
        v-if="open"
        class="fixed inset-0 z-[70] flex items-center justify-center bg-black/60 p-4"
        @click.self="emit('close')"
      >
        <div class="card w-full animate-rise p-5" :class="maxWidth">
          <header v-if="title" class="mb-3 flex items-center justify-between">
            <h2 class="text-lg font-semibold text-white">{{ title }}</h2>
            <button class="text-ink-400 transition hover:text-white" @click="emit('close')">✕</button>
          </header>
          <slot />
          <footer v-if="$slots.footer" class="mt-4 flex justify-end gap-2">
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
