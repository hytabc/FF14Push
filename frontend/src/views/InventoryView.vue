<script setup lang="ts">
import { consumableBonus } from "@/utils/consumables"
import { computed, onMounted, ref, watch } from 'vue'

import { api } from '@/api'
import ItemCard from '@/components/ItemCard.vue'
import ItemIcon from '@/components/ItemIcon.vue'
import { useDohDolStore } from '@/stores/dohdol'
import { useGameStore } from '@/stores/game'
import { useTagsStore } from '@/stores/tags'
import ItemFilterBar from '@/components/ItemFilterBar.vue'
import type { Item } from '@/game/types'
import { categoryName, formatNumber, tagColorHex } from '@/utils/format'
import {
  type ItemFilterState,
  type SortKey,
  applyItemFilters,
  createItemFilters,
  hasActiveFilters,
} from '@/utils/itemFilters'

const game = useGameStore()
const tagsStore = useTagsStore()
const dohdol = useDohDolStore()

const consumables = computed(() => game.state?.dohdol?.consumables ?? [])
const activeBuffs = computed(() => game.state?.dohdol?.active ?? [])

const sortBy = ref<SortKey>('rarity')
const tagFilter = ref<Set<number>>(new Set())
const selected = ref<Set<number>>(new Set())
const page = ref(1)
const PAGE_SIZE = 24
const confirmBatch = ref(false)

/** 背包分页：战斗职业装备 / 生产采集专用装备。 */
const tab = ref<'combat' | 'dohdol'>('combat')
const DEDICATED_CATEGORIES = new Set(['doh_tool', 'doh_gear', 'dol_tool', 'dol_gear'])
const DEDICATED_ORDER = ['doh_tool', 'doh_gear', 'dol_tool', 'dol_gear']

/** 高级筛选（种类 / 部位 / 武器种类 / 职能 / 等级 / 副词条 / 词条 / 品质 / 专用加成），与选择装备弹窗共用。 */
const showAdvanced = ref(false)
const filters = ref<ItemFilterState>(createItemFilters())

/** 当前页签的候选（不含已装备），用于派生筛选选项并作为筛选输入。 */
const baseItems = computed(() =>
  game.items.filter(
    (i) =>
      !i.equippedSlot &&
      (tab.value === 'dohdol' ? DEDICATED_CATEGORIES.has(i.category) : !DEDICATED_CATEGORIES.has(i.category)),
  ),
)

const hasAdvancedFilters = computed(() => hasActiveFilters(filters.value))

function resetAdvancedFilters() {
  filters.value = createItemFilters()
}

const filtered = computed(() => {
  let list = applyItemFilters(baseItems.value, filters.value, sortBy.value)
  if (tagFilter.value.size) {
    // 多选标签：命中任一即显示（OR）
    list = list.filter((i) => (i.tagIds ?? []).some((id) => tagFilter.value.has(id)))
  }
  return list
})

watch([sortBy, tagFilter], () => {
  page.value = 1
})

watch(filters, () => {
  page.value = 1
}, { deep: true })

watch(tab, () => {
  page.value = 1
  resetAdvancedFilters()
})

function toggleTagFilter(tagId: number) {
  const next = new Set(tagFilter.value)
  if (next.has(tagId)) next.delete(tagId)
  else next.add(tagId)
  tagFilter.value = next
}

function clearTagFilter() {
  tagFilter.value = new Set()
}

function tagChipStyle(colorId: string) {
  const hex = tagColorHex(colorId)
  return { color: hex, borderColor: hex, backgroundColor: `${hex}22` }
}

const totalPages = computed(() => Math.max(1, Math.ceil(filtered.value.length / PAGE_SIZE)))
const pageItems = computed(() => filtered.value.slice((page.value - 1) * PAGE_SIZE, page.value * PAGE_SIZE))
const selectedItems = computed(() => game.items.filter((i) => selected.value.has(i.id)))
const selectedValue = computed(() => selectedItems.value.reduce((sum, i) => sum + i.sellPriceMax, 0))

const counts = computed(() => {
  const map: Record<string, number> = {}
  for (const item of game.items) {
    if (item.equippedSlot) continue
    map[item.category] = (map[item.category] ?? 0) + 1
  }
  return map
})

/** 顶部计数随页签切换：战斗看武器/防具/饰品，专用看生产/采集 4 类。 */
const countSummary = computed(() => {
  if (tab.value === 'combat') {
    return `武器 ${counts.value.weapon ?? 0} · 防具 ${counts.value.armor ?? 0} · 饰品 ${counts.value.accessory ?? 0}`
  }
  return DEDICATED_ORDER.map((c) => `${categoryName(c)} ${counts.value[c] ?? 0}`).join(' · ')
})

onMounted(async () => {
  if (!game.state) await game.loadState()
})

function toggle(item: Item) {
  const next = new Set(selected.value)
  if (next.has(item.id)) next.delete(item.id)
  else next.add(item.id)
  selected.value = next
}

/** 装备分流：专用装备走 /dohdol/equip（槽位为字符），战斗装备走 /inventory/equip。 */
async function equipItem(item: Item) {
  if (DEDICATED_CATEGORIES.has(item.category)) {
    await api.dohdolEquip(item.id, item.slot)
    await game.loadState()
  } else {
    await game.equip(item.id, item.equipSlots[0])
  }
}

function selectPage() {
  const next = new Set(selected.value)
  for (const item of pageItems.value) next.add(item.id)
  selected.value = next
}

function clearSelection() {
  selected.value = new Set()
}

async function batchSell() {
  confirmBatch.value = false
  const ids = [...selected.value]
  if (!ids.length) return
  await game.sell(ids)
  clearSelection()
}
</script>

<template>
  <div class="space-y-4">
    <section v-if="consumables.length || activeBuffs.length" class="card p-4">
      <div class="flex flex-wrap items-center gap-3">
        <h2 class="text-sm font-semibold text-white">药水 / 食物</h2>
        <div class="flex flex-wrap gap-2 text-[11px]">
          <span
            v-for="b in activeBuffs"
            :key="b.kind"
            class="rounded bg-emerald-500/20 px-2 py-1 text-emerald-200"
          >
            生效中：{{ b.name }} · {{ b.remainingSec }}s
          </span>
        </div>
      </div>
      <div class="mt-3 flex flex-wrap gap-2">
        <div
          v-for="c in consumables"
          :key="c.itemId"
          class="flex flex-wrap items-center gap-2 rounded border border-ink-700 bg-ink-900/50 px-2 py-1 text-[11px]"
          :title="c.desc"
        >
          <ItemIcon :base-id="c.itemId" variant="plain" :size="20" />
          <span class="min-w-0 text-ink-200">{{ c.name }}<span class="block text-emerald-300">{{ consumableBonus(c.itemId) }}</span></span>
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
    </section>

    <section class="card p-4">
      <div class="flex flex-wrap items-center gap-3">
        <h2 class="text-lg font-semibold text-white">背包</h2>
        <span class="text-xs text-ink-400">{{ countSummary }}</span>
        <span class="ml-auto text-xs text-ink-400">已选 {{ selected.size }} 件 · 约 {{ formatNumber(selectedValue) }} 金币</span>
      </div>

      <!-- 战斗装备 / 生产采集专用装备分页 -->
      <div class="mt-3 flex gap-1 rounded-lg bg-ink-800 p-1 text-xs">
        <button
          class="flex-1 rounded-md py-1.5 transition"
          :class="tab === 'combat' ? 'bg-amber-500 text-ink-950' : 'text-ink-400 hover:text-ink-200'"
          @click="tab = 'combat'"
        >
          战斗装备
        </button>
        <button
          class="flex-1 rounded-md py-1.5 transition"
          :class="tab === 'dohdol' ? 'bg-amber-500 text-ink-950' : 'text-ink-400 hover:text-ink-200'"
          @click="tab = 'dohdol'"
        >
          生产采集装备
        </button>
      </div>

      <div class="mt-3 flex flex-wrap gap-2 text-xs">
        <select v-model="sortBy" class="rounded border border-ink-600 bg-ink-900 px-2 py-1.5">
          <option value="power">按战力排序</option>
          <option value="rarity">按品阶排序</option>
          <option value="level">按等级需求排序</option>
          <option value="name">按名称排序</option>
        </select>
        <button
          class="rounded border px-2 py-1.5 transition"
          :class="showAdvanced || hasAdvancedFilters ? 'border-amber-400 text-amber-200' : 'border-ink-600 text-ink-300 hover:border-ink-400'"
          @click="showAdvanced = !showAdvanced"
        >
          高级筛选<span v-if="hasAdvancedFilters"> ·</span>
        </button>

        <div class="ml-auto flex gap-2">
          <button class="rounded bg-ink-700 px-2 py-1.5 hover:bg-ink-600" @click="selectPage">选中本页</button>
          <button class="rounded bg-ink-700 px-2 py-1.5 hover:bg-ink-600" @click="clearSelection">清空</button>
          <button
            class="rounded bg-amber-600 px-2 py-1.5 text-white hover:bg-amber-500 disabled:opacity-40"
            :disabled="!selected.size"
            @click="confirmBatch = true"
          >
            批量出售
          </button>
        </div>
      </div>

      <div v-if="showAdvanced" class="mt-2 rounded-lg border border-ink-700 bg-ink-900/40 p-2">
        <ItemFilterBar
          v-model="filters"
          :pool="baseItems"
          :show-rarity="true"
          :show-role="tab === 'combat'"
        />
      </div>

      <div class="mt-2 flex flex-wrap items-center gap-1.5 text-xs">
        <template v-if="game.tags.length">
          <span class="text-ink-400">标签：</span>
          <button
            v-for="tag in game.tags"
            :key="tag.id"
            class="rounded-full border px-2.5 py-1 transition"
            :class="tagFilter.has(tag.id) ? '' : 'border-ink-600 text-ink-300 hover:border-ink-400'"
            :style="tagFilter.has(tag.id) ? tagChipStyle(tag.color) : undefined"
            @click="toggleTagFilter(tag.id)"
          >
            {{ tag.name }}
          </button>
          <button v-if="tagFilter.size" class="px-2 py-1 text-ink-400 hover:text-white" @click="clearTagFilter">
            清除筛选
          </button>
        </template>
        <button class="ml-auto rounded bg-ink-700 px-2 py-1.5 hover:bg-ink-600" @click="tagsStore.openManage()">
          管理标签
        </button>
      </div>
    </section>

    <section data-tutorial="inventory" class="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
      <ItemCard
        v-for="item in pageItems"
        :key="item.id"
        :item="item"
        :selected="selected.has(item.id)"
        @select="toggle(item)"
        @equip="equipItem"
        @filter-tag="toggleTagFilter"
      />
      <p v-if="!pageItems.length" class="col-span-full py-10 text-center text-xs text-ink-600">
        {{ tab === 'dohdol' ? '没有未装备的生产 / 采集专用装备。' : '背包是空的，去「抽箱」页面获取装备吧。' }}
      </p>
    </section>

    <nav v-if="totalPages > 1" class="flex items-center justify-center gap-2 text-xs">
      <button
        class="rounded bg-ink-700 px-3 py-1.5 disabled:opacity-40"
        :disabled="page <= 1"
        @click="page = Math.max(1, page - 1)"
      >
        上一页
      </button>
      <span class="text-ink-400">{{ page }} / {{ totalPages }}</span>
      <button
        class="rounded bg-ink-700 px-3 py-1.5 disabled:opacity-40"
        :disabled="page >= totalPages"
        @click="page = Math.min(totalPages, page + 1)"
      >
        下一页
      </button>
    </nav>

    <Teleport to="body">
      <div
        v-if="confirmBatch"
        class="fixed inset-0 z-[70] flex items-center justify-center bg-black/60 p-4"
        @click.self="confirmBatch = false"
      >
        <div class="card w-full max-w-md p-5">
          <h3 class="text-lg font-semibold text-white">确认批量出售</h3>
          <p class="mt-2 text-sm text-ink-200">
            将出售 {{ selected.size }} 件装备，预计获得约
            <b class="text-amber-300">{{ formatNumber(selectedValue) }}</b> 金币。出售后装备永久消失（图鉴记录保留）。
          </p>
          <div class="mt-4 flex justify-end gap-2">
            <button class="rounded-md bg-ink-700 px-3 py-2 text-sm hover:bg-ink-600" @click="confirmBatch = false">
              取消
            </button>
            <button class="rounded-md bg-amber-600 px-3 py-2 text-sm text-white hover:bg-amber-500" @click="batchSell">
              确认出售
            </button>
          </div>
        </div>
      </div>
    </Teleport>
  </div>
</template>
