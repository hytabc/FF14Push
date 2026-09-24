<script setup lang="ts">
import { computed } from 'vue'

import ItemIcon from '@/components/ItemIcon.vue'
import TermBadges from '@/components/TermBadges.vue'
import { useGameStore } from '@/stores/game'
import { useItemActions } from '@/stores/itemActions'
import { useTagsStore } from '@/stores/tags'
import type { Item, ItemTag } from '@/game/types'
import {
  attrName,
  attrRangeLabel,
  attrSuffix,
  baseAttrName,
  categoryName,
  formatNumber,
  rarityBg,
  rarityClass,
  rarityHex,
  rarityName,
  slotName,
  subAttrQualityClass,
  tagColorHex,
} from '@/utils/format'

const props = withDefaults(
  defineProps<{
    item: Item
    selected?: boolean
    compact?: boolean
    showActions?: boolean
    equipped?: boolean
  }>(),
  { selected: false, compact: false, showActions: true, equipped: false },
)

const emit = defineEmits<{
  select: [item: Item]
  equip: [item: Item]
  unequip: [item: Item]
  filterTag: [tagId: number]
}>()

const itemActions = useItemActions()
const tagsStore = useTagsStore()
const game = useGameStore()

/** 生产/采集专用装备：无战斗战力、也不能重造 / 附魔。 */
const DEDICATED_CATEGORIES = new Set(['doh_tool', 'doh_gear', 'dol_tool', 'dol_gear'])
const isDedicated = computed(() => DEDICATED_CATEGORIES.has(props.item.category))

const style = computed(() => ({
  borderColor: rarityHex(props.item.rarity),
  backgroundColor: 'transparent',
}))

const itemTags = computed<ItemTag[]>(() => {
  const ids = props.item.tagIds ?? []
  if (!ids.length) return []
  const byId = new Map(game.tags.map((t) => [t.id, t]))
  return ids.map((id) => byId.get(id)).filter((t): t is ItemTag => t != null)
})

function tagStyle(colorId: string) {
  const hex = tagColorHex(colorId)
  return { color: hex, borderColor: hex, backgroundColor: `${hex}22` }
}

</script>

<template>
  <article
    class="card group relative cursor-pointer p-3 transition"
    :class="[rarityBg(item.rarity), selected ? 'ring-2 ring-white/70' : 'hover:border-white/40']"
    :style="style"
    @click="emit('select', item)"
  >
    <div class="flex items-start justify-between gap-2">
      <div class="flex min-w-0 items-center gap-2">
        <ItemIcon :base-id="item.baseId" :rarity="item.rarity" :size="32" />
        <div class="min-w-0">
          <h3 class="truncate text-sm font-semibold" :class="rarityClass(item.rarity)">
            {{ item.name }}
            <span v-if="item.highQuality" class="rounded bg-amber-500/20 px-1 py-0.5 text-[10px] text-amber-200">高品质</span>
            <span v-if="item.exclusive" class="rounded bg-rose-500/25 px-1 py-0.5 text-[10px] text-rose-200">绝境龙神</span>
          </h3>
          <p class="mt-0.5 text-[11px] text-ink-400">
            {{ rarityName(item.rarity) }} · {{ categoryName(item.category) }} ·
            {{ slotName(item.equipSlots[0] ?? item.slot) }} · Lv.{{ item.levelReq }}
            <span v-if="!isDedicated" class="ml-1 font-mono text-amber-300">战力 {{ formatNumber(item.score) }}</span>
          </p>
        </div>
      </div>
      <span
        v-if="item.equippedSlot"
        class="shrink-0 rounded bg-emerald-500/20 px-1.5 py-0.5 text-[10px] text-emerald-300"
      >
        已装备
      </span>
    </div>

    <ul class="mt-2 space-y-0.5 text-[12px]">
      <li v-for="(entry, index) in item.baseAttrs" :key="`b${index}`" class="text-ink-200">
        {{ baseAttrName(entry.attr) }} <span class="font-mono text-white">+{{ Math.round(entry.value) }}</span>
        <span class="font-mono text-ink-400">{{ attrRangeLabel(entry.min, entry.max) }}</span>
      </li>
      <li v-for="(entry, index) in item.subAttrs" :key="`s${index}`" :class="subAttrQualityClass(entry.quality)">
        {{ attrName(entry.attr) }}
        <span class="font-mono">+{{ entry.value.toFixed(entry.type === 'percent' ? 2 : 0) }}{{ attrSuffix(entry.attr) }}</span>
        <span v-if="entry.quality === 'ancient'" class="ml-0.5">🌟</span>
        <template v-else>
          <span class="font-mono text-ink-400">{{ attrRangeLabel(entry.min, entry.max, entry.type === 'percent' ? 2 : 0) }}</span>
          <span v-if="entry.quality === 'rare'" class="ml-0.5">（稀有）</span>
        </template>
      </li>
    </ul>

    <TermBadges class="mt-2" :terms="item.terms" />

    <div v-if="itemTags.length" class="mt-2 flex flex-wrap gap-1">
      <button
        v-for="tag in itemTags"
        :key="tag.id"
        class="rounded border px-1.5 py-0.5 text-[10px] transition hover:opacity-80"
        :style="tagStyle(tag.color)"
        :title="`按「${tag.name}」筛选`"
        @click.stop="emit('filterTag', tag.id)"
      >
        {{ tag.name }}
      </button>
    </div>

    <div
      v-if="showActions"
      class="mt-3 flex flex-wrap gap-1.5 opacity-90 transition group-hover:opacity-100"
      @click.stop
    >
      <button
        v-if="item.equippedSlot"
        class="rounded bg-ink-700 px-2 py-1 text-[11px] text-ink-200 hover:bg-ink-600"
        @click="emit('unequip', item)"
      >
        卸下
      </button>
      <button
        v-else
        class="rounded bg-emerald-600/80 px-2 py-1 text-[11px] text-white hover:bg-emerald-500"
        @click="emit('equip', item)"
      >
        装备
      </button>
      <button
        v-if="!isDedicated"
        class="rounded bg-indigo-600/70 px-2 py-1 text-[11px] text-white hover:bg-indigo-500"
        data-tutorial="refine"
        @click="itemActions.requestRefine(item)"
      >
        重造
      </button>
      <button
        v-if="!isDedicated"
        class="rounded bg-fuchsia-600/70 px-2 py-1 text-[11px] text-white hover:bg-fuchsia-500"
        data-tutorial="enchant"
        @click="itemActions.requestEnchant(item)"
      >
        附魔
      </button>
      <button
        class="rounded bg-teal-600/70 px-2 py-1 text-[11px] text-white hover:bg-teal-500"
        @click="tagsStore.openAssign(item)"
      >
        标签
      </button>
      <button
        v-if="!item.equippedSlot"
        class="rounded bg-amber-600/70 px-2 py-1 text-[11px] text-white hover:bg-amber-500"
        data-tutorial="sell"
        @click="itemActions.requestSell(item)"
      >
        出售 {{ item.sellPriceMin }}~{{ item.sellPriceMax }}
      </button>
    </div>
  </article>
</template>
