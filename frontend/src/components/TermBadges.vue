<script setup lang="ts">
import { computed } from 'vue'

import type { TermEntry } from '@/game/types'
import { termLabel, termQualityClass } from '@/utils/format'

const props = defineProps<{ terms: TermEntry[] }>()

const buffs = computed(() => props.terms.filter((t) => t.type === 'buff'))
const debuffs = computed(() => props.terms.filter((t) => t.type === 'debuff'))
</script>

<template>
  <div v-if="terms.length" class="flex flex-wrap gap-1">
    <span
      v-for="term in buffs"
      :key="term.id"
      class="rounded border px-1.5 py-0.5 text-[10px]"
      :class="termQualityClass(term.quality)"
      :title="term.desc.replace('{v}', String(term.value))"
    >
      {{ termLabel(term) }}
    </span>
    <span
      v-for="term in debuffs"
      :key="term.id"
      class="rounded border border-rose-500/40 px-1.5 py-0.5 text-[10px] text-rose-300"
      :title="term.desc.replace('{v}', String(term.value))"
    >
      {{ termLabel(term) }}
    </span>
  </div>
</template>
