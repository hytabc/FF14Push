<script setup lang="ts">
import { ref, watch } from 'vue'

import { baseSlotName } from '@/utils/format'

const props = defineProps<{ count: number; slots: string[]; busy?: boolean }>()
const emit = defineEmits<{ claim: [slot: string] }>()

const selected = ref<string>(props.slots[0] ?? '')
watch(
  () => props.slots,
  (slots) => {
    if (!slots.includes(selected.value)) selected.value = slots[0] ?? ''
  },
  { immediate: true },
)
</script>

<template>
  <div class="rounded-lg border border-amber-500/40 bg-amber-500/5 p-3">
    <p class="text-xs text-amber-200">
      高难宝箱 ×{{ count }} · 品质高于抽奖箱，可自选装备种类（戒指可放入任一戒指栏）
    </p>
    <div class="mt-2 flex flex-wrap gap-1.5">
      <button
        v-for="slot in slots"
        :key="slot"
        class="rounded border px-2 py-1 text-[11px] transition"
        :class="
          selected === slot
            ? 'border-amber-400 bg-amber-400/15 text-amber-200'
            : 'border-ink-600 text-ink-300 hover:border-ink-400'
        "
        @click="selected = slot"
      >
        {{ baseSlotName(slot) }}
      </button>
    </div>
    <button
      class="mt-2 w-full rounded-md bg-amber-500 py-2 text-xs font-medium text-ink-950 hover:bg-amber-400 disabled:opacity-40"
      :disabled="!selected || busy"
      @click="emit('claim', selected)"
    >
      {{ busy ? '开启中…' : `开启全部（${count} 件${selected ? ' · ' + baseSlotName(selected) : ''}）` }}
    </button>
  </div>
</template>
