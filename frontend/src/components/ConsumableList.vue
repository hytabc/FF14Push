<script setup lang="ts">
import { computed, ref } from 'vue'

import ItemIcon from '@/components/ItemIcon.vue'
import type { MaterialStackItem } from '@/game/types'
import { useDohDolStore } from '@/stores/dohdol'
import { consumableBonus } from '@/utils/consumables'
import {
  CONSUMABLE_SORT_OPTIONS,
  type ConsumableFilterState,
  type ConsumableSortKey,
  applyConsumableFilters,
  consumableEffectOptions,
  createConsumableFilters,
  hasActiveConsumableFilters,
} from '@/utils/consumableFilters'

const props = withDefaults(
  defineProps<{
    items: MaterialStackItem[]
    /** cards：背包卡片样式；rows：生产页紧凑行。 */
    variant?: 'cards' | 'rows'
    emptyText?: string
  }>(),
  { variant: 'cards', emptyText: '没有符合条件的消耗品。' },
)

const dohdol = useDohDolStore()

const sort = ref<ConsumableSortKey>('group')
const filters = ref<ConsumableFilterState>(createConsumableFilters())

const effects = computed(() => consumableEffectOptions(props.items))
const visible = computed(() => applyConsumableFilters(props.items, filters.value, sort.value))
const hasFilters = computed(() => hasActiveConsumableFilters(filters.value))

function resetFilters() {
  filters.value = createConsumableFilters()
}
</script>

<template>
  <div>
    <div v-if="items.length" class="mt-3 flex flex-wrap items-center gap-2 text-xs">
      <select v-model="filters.kind" class="rounded border border-ink-600 bg-ink-900 px-2 py-1.5">
        <option value="all">全部分类</option>
        <option value="potion">药水</option>
        <option value="food">食物</option>
      </select>
      <select v-model="filters.effect" class="rounded border border-ink-600 bg-ink-900 px-2 py-1.5">
        <option value="all">全部效果</option>
        <option v-for="e in effects" :key="e.id" :value="e.id">{{ e.label }}</option>
      </select>
      <input
        v-model="filters.search"
        type="search"
        placeholder="搜索名称"
        class="w-full rounded border border-ink-600 bg-ink-900 px-2 py-1.5 sm:w-40"
      />
      <select v-model="sort" class="rounded border border-ink-600 bg-ink-900 px-2 py-1.5">
        <option v-for="o in CONSUMABLE_SORT_OPTIONS" :key="o.id" :value="o.id">{{ o.label }}</option>
      </select>
      <button
        v-if="hasFilters"
        class="rounded border border-ink-600 px-2 py-1.5 text-ink-300 hover:border-ink-400"
        @click="resetFilters"
      >
        清除筛选
      </button>
    </div>

    <div v-if="variant === 'cards'" class="mt-3 flex flex-wrap gap-2">
      <div
        v-for="c in visible"
        :key="c.itemId"
        class="flex flex-wrap items-center gap-2 rounded border border-ink-700 bg-ink-900/50 px-2 py-1 text-[11px]"
        :title="c.desc"
      >
        <ItemIcon :base-id="c.itemId" variant="plain" :size="20" />
        <span class="min-w-0 text-ink-200">
          {{ c.name }}<span class="block text-emerald-300">{{ consumableBonus(c.itemId) }}</span>
        </span>
        <span class="font-mono text-ink-400">×{{ c.count }}</span>
        <button
          class="rounded bg-emerald-600/80 px-2 py-0.5 text-white hover:bg-emerald-500"
          @click="dohdol.useConsumable(c.itemId)"
        >
          使用
        </button>
        <button
          class="rounded bg-amber-600/70 px-2 py-0.5 text-white hover:bg-amber-500 disabled:opacity-40"
          :disabled="(c.sell ?? 0) <= 0"
          @click="dohdol.sellStack(c.kind, c.itemId, 1)"
        >
          出售
        </button>
      </div>
    </div>

    <div v-else class="max-h-56 space-y-1 overflow-y-auto text-xs">
      <div v-for="c in visible" :key="c.itemId" class="flex items-center justify-between text-ink-200">
        <span class="flex min-w-0 items-center gap-1.5">
          <ItemIcon :base-id="c.itemId" variant="plain" :size="18" />
          <span class="min-w-0">
            <span class="block">{{ c.name }}</span>
            <span class="block text-[11px] leading-relaxed text-emerald-300">{{ consumableBonus(c.itemId) }}</span>
          </span>
        </span>
        <span class="flex shrink-0 items-center gap-2">
          <span class="font-mono text-ink-400">×{{ c.count }}</span>
          <button
            class="rounded bg-ink-800 px-2 py-0.5 text-[10px] text-emerald-300 hover:bg-ink-700"
            @click="dohdol.useConsumable(c.itemId)"
          >
            使用
          </button>
          <button
            class="rounded bg-ink-800 px-2 py-0.5 text-[10px] text-amber-300 hover:bg-ink-700 disabled:opacity-40"
            :disabled="(c.sell ?? 0) <= 0"
            @click="dohdol.sellStack(c.kind, c.itemId, 1)"
          >
            出售
          </button>
        </span>
      </div>
    </div>

    <p v-if="!visible.length" class="mt-2 text-xs text-ink-500">{{ emptyText }}</p>
  </div>
</template>
