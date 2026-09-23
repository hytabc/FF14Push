<script setup lang="ts">
import { consumableBonus } from "@/utils/consumables"
import { computed, onMounted, ref, watch } from 'vue'

import data from '@shared/schema'
import { api } from '@/api'
import ItemCard from '@/components/ItemCard.vue'
import ItemIcon from '@/components/ItemIcon.vue'
import { useDohDolStore } from '@/stores/dohdol'
import { useGameStore } from '@/stores/game'
import { useTagsStore } from '@/stores/tags'
import type { Category, Item, JobRole, RarityId, TermQuality } from '@/game/types'
import { RARITY_ORDER, attrName, categoryName, formatNumber, rarityName, slotName, tagColorHex } from '@/utils/format'
import {
  ROLE_LABELS,
  TERM_BY_ID,
  WEAPON_TYPE_LABELS,
  roleOfBaseId,
} from '@/utils/itemFilters'

const game = useGameStore()
const tagsStore = useTagsStore()
const dohdol = useDohDolStore()

const consumables = computed(() => game.state?.dohdol?.consumables ?? [])
const activeBuffs = computed(() => game.state?.dohdol?.active ?? [])

const category = ref<'all' | Category>('all')
const rarityFilter = ref<'all' | RarityId>('all')
const sortBy = ref<'rarity' | 'level' | 'name' | 'power'>('rarity')
const tagFilter = ref<Set<number>>(new Set())
const selected = ref<Set<number>>(new Set())
const page = ref(1)
const PAGE_SIZE = 24
const confirmBatch = ref(false)

/** 背包分页：战斗职业装备 / 生产采集专用装备。 */
const tab = ref<'combat' | 'dohdol'>('combat')
const DEDICATED_CATEGORIES = new Set(['doh_tool', 'doh_gear', 'dol_tool', 'dol_gear'])
const DEDICATED_ORDER = ['doh_tool', 'doh_gear', 'dol_tool', 'dol_gear']

/** 高级筛选：物品种类 / 武器种类 / 战斗职能 / 等级 / 副词条 / 词条 / 品质 / 专用加成。 */
const showAdvanced = ref(false)
const slotFilter = ref('all')
const weaponTypeFilter = ref('all')
const roleFilter = ref<'all' | JobRole>('all')
const levelMin = ref<number | ''>('')
const levelMax = ref<number | ''>('')
const subAttrFilter = ref<Set<string>>(new Set())
const termFilter = ref<Set<string>>(new Set())
const qualityFilter = ref<Set<TermQuality>>(new Set())
const dohdolCatFilter = ref('all')
const bonusFilter = ref<Set<string>>(new Set())

const ROLE_ORDER: JobRole[] = ['tank', 'healer', 'melee', 'physicalRanged', 'magicalRanged']
const TERM_QUALITIES: TermQuality[] = ['common', 'rare', 'ancient']
const QUALITY_LABEL: Record<TermQuality, string> = { common: '普通', rare: '稀有', ancient: '太古' }
const DOHDOL_BONUS_NAMES: Record<string, string> = data.dohdolEquipment.bonusNames

/** 当前分页内的物品（不含已装备），供筛选选项列表派生。 */
const tabItems = computed(() =>
  game.items.filter((i) =>
    tab.value === 'dohdol' ? DEDICATED_CATEGORIES.has(i.category) : !DEDICATED_CATEGORIES.has(i.category),
  ),
)

const slotOptions = computed(() => {
  const present = new Set(tabItems.value.map((i) => i.equipSlots?.[0] ?? i.slot))
  return [
    { id: 'all', label: '全部部位' },
    ...[...present].sort().map((s) => ({ id: s, label: slotName(s) })),
  ]
})

const weaponTypeOptions = computed(() => {
  const present = new Set(
    tabItems.value.map((i) => i.weaponType).filter((w): w is string => typeof w === 'string'),
  )
  return [
    { id: 'all', label: '全部武器' },
    ...[...present]
      .sort()
      .map((w) => ({ id: w, label: WEAPON_TYPE_LABELS[w] ?? w })),
  ]
})

const roleOptions = computed(() => [
  { id: 'all', label: '全部职能' },
  ...ROLE_ORDER.map((r) => ({ id: r as string, label: ROLE_LABELS[r] ?? r })),
])

const subAttrOptions = computed(() => {
  const ids = new Set<string>()
  for (const i of tabItems.value) for (const a of i.subAttrs ?? []) ids.add(a.attr)
  return [...ids].sort().map((id) => ({ id, label: attrName(id) }))
})

/** 词条候选：战斗看战斗词条池，专用看生产/采集词条池。 */
const termOptions = computed(() => {
  const pool = tab.value === 'combat' ? data.terms.terms : data.dohdolEquipment.terms
  return pool.map((t) => ({ id: t.id, label: TERM_BY_ID[t.id]?.name ?? t.name }))
})

const bonusOptions = computed(() =>
  Object.keys(DOHDOL_BONUS_NAMES).map((id) => ({ id, label: DOHDOL_BONUS_NAMES[id] })),
)

const dohdolCategoryOptions = computed(() => [
  { id: 'all', label: '全部种类' },
  ...DEDICATED_ORDER.map((c) => ({ id: c, label: categoryName(c) })),
])

function toggleSet<T>(set: Set<T>, id: T): Set<T> {
  const next = new Set(set)
  if (next.has(id)) next.delete(id)
  else next.add(id)
  return next
}

function toggleSubAttr(id: string) {
  subAttrFilter.value = toggleSet(subAttrFilter.value, id)
}

function toggleTerm(id: string) {
  termFilter.value = toggleSet(termFilter.value, id)
}

function toggleQuality(q: TermQuality) {
  qualityFilter.value = toggleSet(qualityFilter.value, q)
}

function toggleBonus(id: string) {
  bonusFilter.value = toggleSet(bonusFilter.value, id)
}

const hasAdvancedFilters = computed(
  () =>
    slotFilter.value !== 'all' ||
    weaponTypeFilter.value !== 'all' ||
    roleFilter.value !== 'all' ||
    levelMin.value !== '' ||
    levelMax.value !== '' ||
    subAttrFilter.value.size > 0 ||
    termFilter.value.size > 0 ||
    qualityFilter.value.size > 0 ||
    dohdolCatFilter.value !== 'all' ||
    bonusFilter.value.size > 0,
)

function resetAdvancedFilters() {
  slotFilter.value = 'all'
  weaponTypeFilter.value = 'all'
  roleFilter.value = 'all'
  levelMin.value = ''
  levelMax.value = ''
  subAttrFilter.value = new Set()
  termFilter.value = new Set()
  qualityFilter.value = new Set()
  dohdolCatFilter.value = 'all'
  bonusFilter.value = new Set()
}

const filtered = computed(() => {
  let list = game.items.filter((i) => !i.equippedSlot)
  list =
    tab.value === 'dohdol'
      ? list.filter((i) => DEDICATED_CATEGORIES.has(i.category))
      : list.filter((i) => !DEDICATED_CATEGORIES.has(i.category))
  if (tab.value === 'combat' && category.value !== 'all') list = list.filter((i) => i.category === category.value)
  if (rarityFilter.value !== 'all') list = list.filter((i) => i.rarity === rarityFilter.value)
  if (tagFilter.value.size) {
    // 多选标签：命中任一即显示（OR）
    list = list.filter((i) => (i.tagIds ?? []).some((id) => tagFilter.value.has(id)))
  }

  // 高级筛选：部位 / 武器种类 / 职能 / 等级 / 副词条 / 词条 / 品质 / 专用种类与加成
  if (slotFilter.value !== 'all') list = list.filter((i) => (i.equipSlots?.[0] ?? i.slot) === slotFilter.value)
  if (weaponTypeFilter.value !== 'all') list = list.filter((i) => i.weaponType === weaponTypeFilter.value)
  if (roleFilter.value !== 'all') list = list.filter((i) => roleOfBaseId(i.baseId) === roleFilter.value)
  if (dohdolCatFilter.value !== 'all') list = list.filter((i) => i.category === dohdolCatFilter.value)
  if (bonusFilter.value.size) list = list.filter((i) => (i.baseAttrs ?? []).some((a) => bonusFilter.value.has(a.attr)))
  {
    const min = typeof levelMin.value === 'number' ? levelMin.value : null
    const max = typeof levelMax.value === 'number' ? levelMax.value : null
    if (min !== null) list = list.filter((i) => i.levelReq >= min)
    if (max !== null) list = list.filter((i) => i.levelReq <= max)
  }
  if (subAttrFilter.value.size) list = list.filter((i) => (i.subAttrs ?? []).some((a) => subAttrFilter.value.has(a.attr)))
  if (termFilter.value.size) list = list.filter((i) => (i.terms ?? []).some((t) => termFilter.value.has(t.id)))
  if (qualityFilter.value.size) {
    list = list.filter(
      (i) =>
        (i.subAttrs ?? []).some((a) => qualityFilter.value.has(a.quality ?? 'common')) ||
        (i.terms ?? []).some((t) => qualityFilter.value.has(t.quality)),
    )
  }

  const rarityIndex = (r: RarityId) => RARITY_ORDER.indexOf(r)
  return list.sort((a, b) => {
    if (sortBy.value === 'power') return b.score - a.score || rarityIndex(b.rarity) - rarityIndex(a.rarity)
    if (sortBy.value === 'rarity') return rarityIndex(b.rarity) - rarityIndex(a.rarity) || b.levelReq - a.levelReq
    if (sortBy.value === 'level') return b.levelReq - a.levelReq
    return a.name.localeCompare(b.name, 'zh-Hans-CN')
  })
})

watch(
  [
    sortBy,
    category,
    rarityFilter,
    tagFilter,
    slotFilter,
    weaponTypeFilter,
    roleFilter,
    levelMin,
    levelMax,
    subAttrFilter,
    termFilter,
    qualityFilter,
    dohdolCatFilter,
    bonusFilter,
  ],
  () => {
    page.value = 1
  },
)

watch(tab, () => {
  page.value = 1
  if (tab.value === 'combat') category.value = 'all'
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
        <select v-if="tab === 'combat'" v-model="category" class="rounded border border-ink-600 bg-ink-900 px-2 py-1.5">
          <option value="all">全部大类</option>
          <option value="weapon">武器</option>
          <option value="armor">防具</option>
          <option value="accessory">饰品</option>
        </select>
        <select v-model="rarityFilter" class="rounded border border-ink-600 bg-ink-900 px-2 py-1.5">
          <option value="all">全部品阶</option>
          <option v-for="r in RARITY_ORDER" :key="r" :value="r">{{ rarityName(r) }}</option>
        </select>
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

      <div v-if="showAdvanced" class="mt-2 space-y-2 rounded-lg border border-ink-700 bg-ink-900/40 p-2 text-xs">
        <div class="flex flex-wrap items-center gap-2">
          <select v-model="slotFilter" class="rounded border border-ink-600 bg-ink-900 px-2 py-1.5">
            <option v-for="opt in slotOptions" :key="opt.id" :value="opt.id">{{ opt.label }}</option>
          </select>
          <select v-if="tab === 'dohdol'" v-model="dohdolCatFilter" class="rounded border border-ink-600 bg-ink-900 px-2 py-1.5">
            <option v-for="opt in dohdolCategoryOptions" :key="opt.id" :value="opt.id">{{ opt.label }}</option>
          </select>
          <select
            v-if="tab === 'combat' && weaponTypeOptions.length > 1"
            v-model="weaponTypeFilter"
            class="rounded border border-ink-600 bg-ink-900 px-2 py-1.5"
          >
            <option v-for="opt in weaponTypeOptions" :key="opt.id" :value="opt.id">{{ opt.label }}</option>
          </select>
          <select v-if="tab === 'combat'" v-model="roleFilter" class="rounded border border-ink-600 bg-ink-900 px-2 py-1.5">
            <option v-for="opt in roleOptions" :key="opt.id" :value="opt.id">{{ opt.label }}</option>
          </select>
          <label class="flex items-center gap-1 text-ink-400">
            等级
            <input
              v-model.number="levelMin"
              type="number"
              min="1"
              step="1"
              placeholder="最低"
              class="w-16 rounded border border-ink-600 bg-ink-900 px-2 py-1.5"
            />
            <span class="text-ink-600">-</span>
            <input
              v-model.number="levelMax"
              type="number"
              min="1"
              step="1"
              placeholder="最高"
              class="w-16 rounded border border-ink-600 bg-ink-900 px-2 py-1.5"
            />
          </label>
          <button
            v-if="hasAdvancedFilters"
            class="rounded bg-ink-800 px-2.5 py-1.5 text-ink-300 transition hover:bg-ink-700"
            @click="resetAdvancedFilters"
          >
            重置筛选
          </button>
        </div>

        <div v-if="tab === 'combat' && subAttrOptions.length" class="flex flex-wrap items-center gap-1.5">
          <span class="shrink-0 text-ink-400">副词条：</span>
          <button
            v-for="opt in subAttrOptions"
            :key="opt.id"
            class="rounded-full border px-2.5 py-1 transition"
            :class="subAttrFilter.has(opt.id) ? 'border-amber-400 bg-amber-500/20 text-amber-200' : 'border-ink-600 text-ink-300 hover:border-ink-400'"
            @click="toggleSubAttr(opt.id)"
          >
            {{ opt.label }}
          </button>
        </div>

        <div v-if="termOptions.length" class="flex flex-wrap items-center gap-1.5">
          <span class="shrink-0 text-ink-400">词条：</span>
          <button
            v-for="opt in termOptions"
            :key="opt.id"
            class="rounded-full border px-2.5 py-1 transition"
            :class="termFilter.has(opt.id) ? 'border-amber-400 bg-amber-500/20 text-amber-200' : 'border-ink-600 text-ink-300 hover:border-ink-400'"
            @click="toggleTerm(opt.id)"
          >
            {{ opt.label }}
          </button>
        </div>

        <div v-if="tab === 'dohdol' && bonusOptions.length" class="flex flex-wrap items-center gap-1.5">
          <span class="shrink-0 text-ink-400">专用加成：</span>
          <button
            v-for="opt in bonusOptions"
            :key="opt.id"
            class="rounded-full border px-2.5 py-1 transition"
            :class="bonusFilter.has(opt.id) ? 'border-amber-400 bg-amber-500/20 text-amber-200' : 'border-ink-600 text-ink-300 hover:border-ink-400'"
            @click="toggleBonus(opt.id)"
          >
            {{ opt.label }}
          </button>
        </div>

        <div class="flex flex-wrap items-center gap-1.5">
          <span class="shrink-0 text-ink-400">品质：</span>
          <button
            v-for="q in TERM_QUALITIES"
            :key="q"
            class="rounded-full border px-2.5 py-1 transition"
            :class="qualityFilter.has(q) ? 'border-amber-400 bg-amber-500/20 text-amber-200' : 'border-ink-600 text-ink-300 hover:border-ink-400'"
            @click="toggleQuality(q)"
          >
            {{ QUALITY_LABEL[q] }}
          </button>
          <span class="text-ink-600">副属性或词条品质命中任一</span>
        </div>
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
