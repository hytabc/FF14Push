<script setup lang="ts">
import type { ActivityLogEntry } from '@/game/types'

defineProps<{
  /** 面板标题，如「采集日志」/「生产日志」。 */
  title: string
  entries: ActivityLogEntry[]
  /** 无记录时的占位文案。 */
  empty?: string
}>()

const TONE_CLASS: Record<string, string> = {
  loot: 'text-emerald-300',
  exp: 'text-sky-300',
  system: 'text-ink-200',
}
</script>

<template>
  <section class="rounded-lg border border-ink-700/60 bg-ink-900/40 p-3">
    <div class="flex items-center justify-between">
      <h2 class="text-xs font-semibold text-ink-300">{{ title }}</h2>
      <span class="text-[11px] text-ink-400">最近 {{ entries.length }} 条</span>
    </div>
    <div
      class="mt-2 h-48 overflow-y-auto rounded-lg border border-ink-800 bg-ink-950/60 p-3 font-mono text-[11px] leading-relaxed"
    >
      <p v-for="entry in [...entries].reverse()" :key="entry.id" :class="TONE_CLASS[entry.tone]">
        {{ entry.text }}
      </p>
      <p v-if="!entries.length" class="text-ink-400">{{ empty ?? '尚无记录' }}</p>
    </div>
  </section>
</template>
