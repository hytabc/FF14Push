<script setup lang="ts">
import { computed } from 'vue'

import ItemIcon from '@/components/ItemIcon.vue'
import { useItemActions } from '@/stores/itemActions'
import type { Item } from '@/game/types'
import {
  attrName,
  attrSuffix,
  baseAttrName,
  categoryName,
  rarityBg,
  rarityClass,
  rarityHex,
  rarityName,
  slotName,
  termQualityClass,
  termQualityName,
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
}>()

const itemActions = useItemActions()

const style = computed(() => ({
  borderColor: rarityHex(props.item.rarity),
  backgroundColor: 'transparent',
}))

const buffs = computed(() => props.item.terms.filter((t) => t.type === 'buff'))
const debuffs = computed(() => props.item.terms.filter((t) => t.type === 'debuff'))

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
          </h3>
          <p class="mt-0.5 text-[11px] text-ink-400">
            {{ rarityName(item.rarity) }} · {{ categoryName(item.category) }} ·
            {{ slotName(item.equipSlots[0] ?? item.slot) }} · 需 Lv.{{ item.levelReq }}
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
      </li>
      <li v-for="(entry, index) in item.subAttrs" :key="`s${index}`" class="text-sky-300">
        {{ attrName(entry.attr) }}
        <span class="font-mono">+{{ entry.value.toFixed(entry.type === 'percent' ? 2 : 0) }}{{ attrSuffix(entry.attr) }}</span>
      </li>
    </ul>

    <div v-if="item.terms.length" class="mt-2 flex flex-wrap gap-1">
      <span
        v-for="term in buffs"
        :key="term.id"
        class="rounded border px-1.5 py-0.5 text-[10px]"
        :class="termQualityClass(term.quality)"
        :title="term.desc.replace('{v}', String(term.value))"
      >
        {{ term.name }}{{ term.quality !== 'common' ? `（${termQualityName(term.quality)}）` : '' }}
      </span>
      <span
        v-for="term in debuffs"
        :key="term.id"
        class="rounded border border-rose-500/40 px-1.5 py-0.5 text-[10px] text-rose-300"
        :title="term.desc.replace('{v}', String(term.value))"
      >
        {{ term.name }}{{ term.quality !== 'common' ? `（${termQualityName(term.quality)}）` : '' }}
      </span>
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
        class="rounded bg-indigo-600/70 px-2 py-1 text-[11px] text-white hover:bg-indigo-500"
        @click="itemActions.requestRefine(item)"
      >
        重造
      </button>
      <button
        class="rounded bg-fuchsia-600/70 px-2 py-1 text-[11px] text-white hover:bg-fuchsia-500"
        @click="itemActions.requestEnchant(item)"
      >
        附魔
      </button>
      <button
        v-if="!item.equippedSlot"
        class="rounded bg-amber-600/70 px-2 py-1 text-[11px] text-white hover:bg-amber-500"
        @click="itemActions.requestSell(item)"
      >
        出售 {{ item.sellPriceMin }}~{{ item.sellPriceMax }}
      </button>
    </div>
  </article>
</template>
