<script setup lang="ts">
import { computed, ref, watch } from 'vue'

import ItemCard from '@/components/ItemCard.vue'
import ItemFilterBar from '@/components/ItemFilterBar.vue'
import ItemPickerTile from '@/components/ItemPickerTile.vue'
import Modal from '@/components/Modal.vue'
import { useVisibleLimit } from '@/composables/useVisibleLimit'
import type { Item, JobRole } from '@/game/types'
import { RARITY_ORDER, rarityName } from '@/utils/format'
import {
  type ItemFilterState,
  type SortKey,
  ROLE_LABELS,
  SORT_OPTIONS,
  applyItemFilters,
  createItemFilters,
  roleOfBaseId,
} from '@/utils/itemFilters'

const props = withDefaults(
  defineProps<{
    open: boolean
    title: string
    candidates: Item[]
    equipped?: Item | null
    /** 候选池已按栏位收窄时，隐藏「部位 / 种类」筛选。 */
    slotScoped?: boolean
    /** 当前英雄职能（用于标记「职能不符」的候选）；武器栏位不校验。 */
    heroRole?: JobRole | null
    /** 本弹窗是否在选武器（武器栏位不受职能限制）。 */
    slotIsWeapon?: boolean
    /** 是否显示「全部状态 / 仅未装备」筛选（装备页需要）。 */
    showEquippedFilter?: boolean
  }>(),
  { equipped: null, slotScoped: false, heroRole: null, slotIsWeapon: false, showEquippedFilter: false },
)

const emit = defineEmits<{ close: []; equip: [item: Item]; unequip: [] }>()

/** 该候选与当前英雄职能不符（基础型 / 无武器时不限制）。 */
function roleMismatch(item: Item): boolean {
  if (props.slotIsWeapon || !props.heroRole) return false
  const role = roleOfBaseId(item.baseId)
  return !!role && role !== props.heroRole
}

const mismatchCount = computed(() => props.candidates.filter(roleMismatch).length)
const heroRoleLabel = computed(() => (props.heroRole ? ROLE_LABELS[props.heroRole] ?? props.heroRole : ''))

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

const filtered = computed(() => {
  const list = applyItemFilters(props.candidates, filters.value, sort.value)
  // 职能不符的候选排到最后（仍列出，符合「显式提示而非隐藏」）。
  const ok: Item[] = []
  const bad: Item[] = []
  for (const item of list) (roleMismatch(item) ? bad : ok).push(item)
  return bad.length ? [...ok, ...bad] : list
})

/** 职能不符的候选不可装备（点击无反应，由徽章说明原因）。 */
function pick(item: Item) {
  if (roleMismatch(item)) return
  emit('equip', item)
}

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
        :show-equipped="showEquippedFilter"
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

      <p v-if="mismatchCount" class="rounded border border-rose-500/30 bg-rose-500/10 px-2 py-1 text-[11px] text-rose-200">
        当前职能：{{ heroRoleLabel }}。其中 {{ mismatchCount }} 件为其他职能专用（标「职能不符」），无法装备。
      </p>

      <button
        v-if="equipped"
        class="w-full rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-left text-xs text-rose-200"
        @click="emit('unequip')"
      >
        卸下当前装备（{{ equipped.name }}）
      </button>

      <!-- 卡片视图 -->
      <div v-if="view === 'card'" class="space-y-2">
        <div v-for="item in visible" :key="item.id" class="relative" :class="roleMismatch(item) ? 'opacity-50' : ''">
          <ItemCard
            :item="item"
            :show-actions="false"
            :equipped="isEquipped(item)"
            @select="pick($event)"
          />
          <span
            v-if="roleMismatch(item)"
            class="pointer-events-none absolute right-2 top-2 rounded bg-rose-600/80 px-1.5 py-0.5 text-[10px] text-white"
          >
            职能不符
          </span>
        </div>
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
          :incompatible="roleMismatch(item)"
          @select="pick($event)"
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
          :incompatible="roleMismatch(item)"
          @select="pick($event)"
        />
      </div>

      <button
        v-if="remaining > 0"
        class="mx-auto block rounded-lg border border-ink-700 bg-ink-800/60 px-4 py-2 text-xs text-ink-200 transition hover:border-amber-400"
        @click="showMore"
      >
        显示更多（剩余 {{ remaining }} 件）
      </button>

      <p v-if="!filtered.length" class="py-8 text-center text-xs text-ink-400">
        没有符合条件的装备。
      </p>
    </div>
  </Modal>
</template>
