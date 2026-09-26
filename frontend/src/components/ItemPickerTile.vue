<script setup lang="ts">
import { computed } from 'vue'

import ItemIcon from '@/components/ItemIcon.vue'
import { useGameStore } from '@/stores/game'
import type { Item } from '@/game/types'
import { formatNumber, rarityClass, rarityName } from '@/utils/format'
import { dohdolBonusName, equipGroup } from '@/utils/itemFilters'

const props = defineProps<{
  item: Item
  variant: 'list' | 'grid'
  equipped?: boolean
  /** 与当前英雄职能不符：置灰并禁止选择。 */
  incompatible?: boolean
}>()

const emit = defineEmits<{ select: [item: Item] }>()

const game = useGameStore()

function pick() {
  if (props.incompatible) return
  emit('select', props.item)
}

const isDedicated = computed(() => equipGroup(props.item.category) !== 'combat')

/** 已装备时的徽章文案：优先显示装备者「英雄名#ID」。 */
const ownerLabel = computed(() =>
  props.item.equippedHeroId ? game.heroLabel(props.item.equippedHeroId) : '已装备',
)

/** 专用装备的首条加成（列表视图右侧展示）。 */
const bonusText = computed(() => {
  const first = props.item.baseAttrs?.[0]
  return first ? `${dohdolBonusName(first.attr)} +${first.value}` : ''
})

const tooltip = computed(() => {
  const base =
    `${props.item.name} · ${rarityName(props.item.rarity)} · Lv.${props.item.levelReq}` +
    (isDedicated.value ? '' : ` · 战力 ${formatNumber(props.item.score)}`)
  return props.item.equippedHeroId ? `${base} · 装备者 ${game.heroLabel(props.item.equippedHeroId)}` : base
})
</script>

<template>
  <button
    v-if="variant === 'grid'"
    class="gallery-cell flex flex-col items-center gap-1 rounded-lg border border-ink-700 bg-ink-900/40 p-2 text-center transition hover:border-white/50"
    :class="incompatible ? 'cursor-not-allowed opacity-50 hover:border-ink-700' : ''"
    :title="tooltip"
    @click="pick"
  >
    <ItemIcon :base-id="item.baseId" :rarity="item.rarity" :size="32" />
    <span class="w-full truncate text-[11px] font-medium" :class="rarityClass(item.rarity)">{{ item.name }}</span>
    <span class="text-[10px] text-ink-400">
      <template v-if="isDedicated">Lv.{{ item.levelReq }}</template>
      <template v-else>战力 {{ formatNumber(item.score) }}</template>
    </span>
    <span v-if="incompatible" class="rounded bg-rose-600/80 px-1 text-[9px] text-white">职能不符</span>
    <span v-else-if="item.equippedSlot || equipped" class="max-w-full truncate rounded bg-emerald-500/20 px-1 text-[9px] text-emerald-300">{{ ownerLabel }}</span>
  </button>

  <button
    v-else
    class="flex w-full items-center gap-2 rounded px-2 py-1.5 text-left transition hover:bg-ink-800/60"
    :class="incompatible ? 'cursor-not-allowed opacity-50 hover:bg-transparent' : ''"
    :title="tooltip"
    @click="pick"
  >
    <ItemIcon :base-id="item.baseId" :rarity="item.rarity" :size="24" />
    <span class="min-w-0 flex-1 truncate text-xs font-medium" :class="rarityClass(item.rarity)">{{ item.name }}</span>
    <span class="shrink-0 text-[10px] text-ink-400">{{ rarityName(item.rarity) }} · Lv.{{ item.levelReq }}</span>
    <span v-if="!isDedicated" class="shrink-0 font-mono text-[10px] text-amber-300">战力 {{ formatNumber(item.score) }}</span>
    <span v-else-if="bonusText" class="shrink-0 text-[10px] text-emerald-300">{{ bonusText }}</span>
    <span v-if="incompatible" class="shrink-0 rounded bg-rose-600/80 px-1 py-0.5 text-[10px] text-white">职能不符</span>
    <span v-else-if="item.equippedSlot || equipped" class="shrink-0 rounded bg-emerald-500/20 px-1 py-0.5 text-[10px] text-emerald-300">{{ ownerLabel }}</span>
  </button>
</template>
