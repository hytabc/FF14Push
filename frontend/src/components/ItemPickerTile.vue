<script setup lang="ts">
import { computed } from 'vue'

import ItemIcon from '@/components/ItemIcon.vue'
import type { Item } from '@/game/types'
import { formatNumber, rarityClass, rarityName } from '@/utils/format'
import { dohdolBonusName, equipGroup } from '@/utils/itemFilters'

const props = defineProps<{
  item: Item
  variant: 'list' | 'grid'
  equipped?: boolean
}>()

const emit = defineEmits<{ select: [item: Item] }>()

const isDedicated = computed(() => equipGroup(props.item.category) !== 'combat')

/** 专用装备的首条加成（列表视图右侧展示）。 */
const bonusText = computed(() => {
  const first = props.item.baseAttrs?.[0]
  return first ? `${dohdolBonusName(first.attr)} +${first.value}` : ''
})

const tooltip = computed(
  () =>
    `${props.item.name} · ${rarityName(props.item.rarity)} · Lv.${props.item.levelReq}` +
    (isDedicated.value ? '' : ` · 战力 ${formatNumber(props.item.score)}`),
)
</script>

<template>
  <button
    v-if="variant === 'grid'"
    class="gallery-cell flex flex-col items-center gap-1 rounded-lg border border-ink-700 bg-ink-900/40 p-2 text-center transition hover:border-white/50"
    :title="tooltip"
    @click="emit('select', item)"
  >
    <ItemIcon :base-id="item.baseId" :rarity="item.rarity" :size="32" />
    <span class="w-full truncate text-[11px] font-medium" :class="rarityClass(item.rarity)">{{ item.name }}</span>
    <span class="text-[10px] text-ink-400">
      <template v-if="isDedicated">Lv.{{ item.levelReq }}</template>
      <template v-else>战力 {{ formatNumber(item.score) }}</template>
    </span>
    <span v-if="equipped" class="rounded bg-emerald-500/20 px-1 text-[9px] text-emerald-300">已装备</span>
  </button>

  <button
    v-else
    class="flex w-full items-center gap-2 rounded px-2 py-1.5 text-left transition hover:bg-ink-800/60"
    :title="tooltip"
    @click="emit('select', item)"
  >
    <ItemIcon :base-id="item.baseId" :rarity="item.rarity" :size="24" />
    <span class="min-w-0 flex-1 truncate text-xs font-medium" :class="rarityClass(item.rarity)">{{ item.name }}</span>
    <span class="shrink-0 text-[10px] text-ink-400">{{ rarityName(item.rarity) }} · Lv.{{ item.levelReq }}</span>
    <span v-if="!isDedicated" class="shrink-0 font-mono text-[10px] text-amber-300">战力 {{ formatNumber(item.score) }}</span>
    <span v-else-if="bonusText" class="shrink-0 text-[10px] text-emerald-300">{{ bonusText }}</span>
    <span v-if="equipped" class="shrink-0 rounded bg-emerald-500/20 px-1 py-0.5 text-[10px] text-emerald-300">已装备</span>
  </button>
</template>
