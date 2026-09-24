<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'

import type { TermEntry } from '@/game/types'
import { equipEffectExplain } from '@/game/explanations'
import { termCategoryName, termLabel, termQualityClass, termRange } from '@/utils/format'

const props = defineProps<{ terms: TermEntry[] }>()

const buffs = computed(() => props.terms.filter((t) => t.type === 'buff'))
const debuffs = computed(() => props.terms.filter((t) => t.type === 'debuff'))

const active = ref<TermEntry | null>(null)
const pos = ref({ top: 0, left: 0, width: 240 })

const activeRange = computed(() => (active.value ? termRange(active.value.id) : null))
const activeExplain = computed(() => (active.value ? equipEffectExplain(active.value.stat) : null))

/** 点击 Buff/Debuff 标签：弹出效果、数值与数值上下限区间（再点一次收起）。 */
function toggle(term: TermEntry, event: MouseEvent) {
  if (active.value?.id === term.id) {
    active.value = null
    return
  }
  const rect = (event.currentTarget as HTMLElement).getBoundingClientRect()
  const width = Math.min(240, window.innerWidth - 16)
  const left = Math.min(Math.max(8, rect.left), Math.max(8, window.innerWidth - width - 8))
  const top =
    rect.bottom + 6 + 150 > window.innerHeight ? Math.max(8, rect.top - 156) : rect.bottom + 6
  pos.value = { top, left, width }
  active.value = term
}

function close() {
  active.value = null
}

function onKey(e: KeyboardEvent) {
  if (e.key === 'Escape') close()
}
function onScroll() {
  close()
}

onMounted(() => {
  window.addEventListener('keydown', onKey)
  window.addEventListener('scroll', onScroll, true)
})
onBeforeUnmount(() => {
  window.removeEventListener('keydown', onKey)
  window.removeEventListener('scroll', onScroll, true)
})

/** 词条数值：整数原样，非整数保留一位小数。 */
function valueText(term: TermEntry): string {
  return Number.isInteger(term.value) ? String(term.value) : term.value.toFixed(1)
}

/** 词条效果文案：替换 {v}（主值）与 {c}（风险代价折算值）。 */
function descText(term: TermEntry): string {
  let text = term.desc.replace('{v}', valueText(term))
  if (term.cost) {
    const cost = Number.isInteger(term.cost.value) ? String(term.cost.value) : term.cost.value.toFixed(1)
    text = text.replace('{c}', cost)
  }
  return text
}
</script>

<template>
  <div v-if="terms.length" class="flex flex-wrap gap-1">
    <button
      v-for="term in buffs"
      :key="term.id"
      type="button"
      class="cursor-pointer rounded border px-1.5 py-0.5 text-[10px] transition hover:brightness-125"
      :class="termQualityClass(term.quality)"
      :title="descText(term)"
      @click.stop="toggle(term, $event)"
    >
      {{ termLabel(term) }}
    </button>
    <button
      v-for="term in debuffs"
      :key="term.id"
      type="button"
      class="cursor-pointer rounded border border-rose-500/40 px-1.5 py-0.5 text-[10px] text-rose-300 transition hover:brightness-125"
      :title="descText(term)"
      @click.stop="toggle(term, $event)"
    >
      {{ termLabel(term) }}
    </button>

    <Teleport to="body">
      <div v-if="active" class="fixed inset-0 z-[99]" @click="close" />
      <div
        v-if="active"
        class="fixed z-[100] space-y-1 rounded-lg border bg-ink-900 p-3 text-[11px] leading-relaxed text-ink-300 shadow-xl"
        :class="active.type === 'buff' ? 'border-term-common/50' : 'border-rose-500/40'"
        :style="{ top: `${pos.top}px`, left: `${pos.left}px`, width: `${pos.width}px` }"
      >
        <div class="flex items-start justify-between gap-2">
          <p class="text-xs font-semibold text-ink-100">{{ termLabel(active) }}</p>
          <span
            class="shrink-0 rounded px-1.5 py-0.5 text-[10px]"
            :class="active.type === 'buff' ? 'bg-emerald-500/20 text-emerald-300' : 'bg-rose-500/20 text-rose-300'"
          >
            {{ active.type === 'buff' ? 'Buff' : 'Debuff' }}
          </span>
        </div>
        <p class="text-ink-200">{{ descText(active) }}</p>
        <p v-if="activeRange" class="text-ink-400">
          数值范围（{{ activeRange[0] }} ~ {{ activeRange[1] }}）
        </p>
        <p class="text-ink-500">
          <template v-if="termCategoryName(active.category)">类别：{{ termCategoryName(active.category) }} · </template>触发：{{ active.trigger }}
        </p>
        <div v-if="activeExplain" class="space-y-0.5 border-t border-ink-700/60 pt-1 text-ink-400">
          <p v-for="(line, i) in activeExplain.lines" :key="i">{{ line }}</p>
        </div>
      </div>
    </Teleport>
  </div>
</template>
