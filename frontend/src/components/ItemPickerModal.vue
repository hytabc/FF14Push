<script setup lang="ts">
import { computed, ref, watch } from 'vue'

import ItemCard from '@/components/ItemCard.vue'
import ItemFilterBar from '@/components/ItemFilterBar.vue'
import ItemPickerTile from '@/components/ItemPickerTile.vue'
import Modal from '@/components/Modal.vue'
import { useVisibleLimit } from '@/composables/useVisibleLimit'
import type { Item } from '@/game/types'
import { RARITY_ORDER, rarityName } from '@/utils/format'
import {
  type ItemFilterState,
  type SortKey,
  SORT_OPTIONS,
  applyItemFilters,
  createItemFilters,
} from '@/utils/itemFilters'

const props = withDefaults(
  defineProps<{
    open: boolean
    title: string
    candidates: Item[]
    equipped?: Item | null
    /** 候选池已按栏位收窄时，隐藏「部位 / 种类」筛选。 */
    slotScoped?: boolean
  }>(),
  { equipped: null, slotScoped: false },
)

const emit = defineEmits<{ close: []; equip: [item: Item]; unequip: [] }>()

type ViewMode = 'card' | 'list' | 'grid'
const VIEW_KEY = 'eorzea.pickerView'
const VIEWS: { id: ViewMode; label: string }[] = [
  { id: 'card', label: '卡片' },
  { id: 'list', label: '列表' },
  { id: 'grid', label: '网格' },
]

function readView(): ViewMode {
  const v = localStorage.getItem(VIEW_KEY)
  return v === 'list' || v === 'grid' || v === 'card' ? v : 'card'
}

const filters = ref<ItemFilterState>(createItemFilters())
const sort = ref<SortKey>('power')
const view = ref<ViewMode>(readView())

function setView(v: ViewMode) {
  view.value = v
  localStorage.setItem(VIEW_KEY, v)
}

const filtered = computed(() => applyItemFilters(props.candidates, filters.value, sort.value))

// 候选可达上百件（卡片视图每件还是很重的 ItemCard），首批只渲染一部分，其余由「显示更多」追加。
const { visible, remaining, showMore } = useVisibleLimit(filtered, 60)

// 每次打开都重置筛选与排序（记住视图模式），避免上一个栏位的筛选把候选全部隐藏。
watch(
  () => props.open,
  (open) => {
    if (open) {
      filters.value = createItemFilters()
      sort.value = 'power'
    }
  },
)

function isEquipped(item: Item): boolean {
  return props.equipped?.id === item.id
}
</script>

<template>
  <Modal :open="open" :title="title" max-width="max-w-4xl" @close="emit('close')">
    <div class="space-y-3">
      <ItemFilterBar
        v-model="filters"
        :pool="candidates"
        :show-slot="!slotScoped"
        :show-category="!slotScoped"
      />

      <div class="flex flex-wrap items-center gap-2 text-xs">
        <select v-model="filters.rarity" class="rounded border border-ink-600 bg-ink-900 px-2 py-1.5">
          <option value="all">全部品阶</option>
          <option v-for="r in RARITY_ORDER" :key="r" :value="r">{{ rarityName(r) }}</option>
        </select>
        <select v-model="sort" class="rounded border border-ink-600 bg-ink-900 px-2 py-1.5">
          <option v-for="o in SORT_OPTIONS" :key="o.id" :value="o.id">{{ o.label }}</option>
        </select>

        <div class="flex gap-0.5 rounded-lg bg-ink-800 p-0.5">
          <button
            v-for="v in VIEWS"
            :key="v.id"
            class="rounded px-2.5 py-1 transition"
            :class="view === v.id ? 'bg-amber-500 text-ink-950' : 'text-ink-400 hover:text-ink-200'"
            @click="setView(v.id)"
          >
            {{ v.label }}
          </button>
        </div>

        <span class="ml-auto text-ink-500">共 {{ filtered.length }} 件</span>
      </div>

      <button
        v-if="equipped"
        class="w-full rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-left text-xs text-rose-200"
        @click="emit('unequip')"
      >
        卸下当前装备（{{ equipped.name }}）
      </button>

      <!-- 卡片视图 -->
      <div v-if="view === 'card'" class="space-y-2">
        <ItemCard
          v-for="item in visible"
          :key="item.id"
          :item="item"
          :show-actions="false"
          :equipped="isEquipped(item)"
          @select="emit('equip', $event)"
        />
      </div>

      <!-- 列表视图 -->
      <div
        v-else-if="view === 'list'"
        class="divide-y divide-ink-800 overflow-hidden rounded-lg border border-ink-700"
      >
        <ItemPickerTile
          v-for="item in visible"
          :key="item.id"
          :item="item"
          variant="list"
          :equipped="isEquipped(item)"
          @select="emit('equip', $event)"
        />
      </div>

      <!-- 网格视图 -->
      <div v-else class="grid grid-cols-3 gap-2 sm:grid-cols-4 lg:grid-cols-6">
        <ItemPickerTile
          v-for="item in visible"
          :key="item.id"
          :item="item"
          variant="grid"
          :equipped="isEquipped(item)"
          @select="emit('equip', $event)"
        />
      </div>

      <button
        v-if="remaining > 0"
        class="mx-auto block rounded-lg border border-ink-700 bg-ink-800/60 px-4 py-2 text-xs text-ink-200 transition hover:border-amber-400"
        @click="showMore"
      >
        显示更多（剩余 {{ remaining }} 件）
      </button>

      <p v-if="!filtered.length" class="py-8 text-center text-xs text-ink-600">
        没有符合条件的装备。
      </p>
    </div>
  </Modal>
</template>
