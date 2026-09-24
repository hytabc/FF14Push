<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'

import data from '@shared/schema'

import InfoTip from '@/components/InfoTip.vue'
import ItemIcon from '@/components/ItemIcon.vue'
import ItemPickerModal from '@/components/ItemPickerModal.vue'
import Modal from '@/components/Modal.vue'
import TermBadges from '@/components/TermBadges.vue'
import { api } from '@/api'
import { marketFeeExplain } from '@/game/explanations'
import type { Item, MarketBuyOrder, MarketListing, MaterialStackItem } from '@/game/types'
import { useDohDolStore } from '@/stores/dohdol'
import { useGameStore } from '@/stores/game'
import { useToastStore } from '@/stores/toast'
import { RARITY_ORDER, attrName, baseAttrName, formatNumber, rarityName } from '@/utils/format'

type Tab = 'all' | 'equipment' | 'wanted' | 'material' | 'consumable' | 'materia' | 'seed' | 'mine'
type ViewMode = 'card' | 'list' | 'grid'
/** 可上架 / 可求购的堆叠物种类（与后端 StackKind 对齐）。 */
type StackKind = 'material' | 'potion' | 'food' | 'materia' | 'seed'
type StackTab = 'material' | 'consumable' | 'materia' | 'seed'

const PAGE_SIZE = 20
const VIEW_KEY = 'eorzea.marketView'

const TABS: { id: Tab; label: string }[] = [
  { id: 'all', label: '全部' },
  { id: 'equipment', label: '装备' },
  { id: 'wanted', label: '收购' },
  { id: 'material', label: '素材' },
  { id: 'consumable', label: '消耗品' },
  { id: 'materia', label: '魔晶石' },
  { id: 'seed', label: '种子' },
  { id: 'mine', label: '我的寄售' },
]

const VIEWS: { id: ViewMode; label: string }[] = [
  { id: 'card', label: '卡片' },
  { id: 'list', label: '列表' },
  { id: 'grid', label: '网格' },
]

const SORTS: { id: string; label: string }[] = [
  { id: 'time_desc', label: '最新上架' },
  { id: 'price_asc', label: '价格从低到高' },
  { id: 'price_desc', label: '价格从高到低' },
]

function readView(): ViewMode {
  const v = localStorage.getItem(VIEW_KEY)
  return v === 'list' || v === 'grid' || v === 'card' ? v : 'card'
}

const game = useGameStore()
const dohdol = useDohDolStore()
const toast = useToastStore()

const marketCfg = data.economy.market
const feePct = ref(marketCfg.feePct)
const listingDays = ref(marketCfg.listingDays)
const maxActiveListings = ref(marketCfg.maxActiveListings)

const tab = ref<Tab>('all')
const sort = ref('time_desc')
const rarity = ref('all')
const q = ref('')
const page = ref(1)
const view = ref<ViewMode>(readView())

const listings = ref<MarketListing[]>([])
const total = ref(0)
const loading = ref(false)

const mineActive = ref<MarketListing[]>([])
const mineClosed = ref<MarketListing[]>([])

// 收购单（求购）
const buyOrders = ref<MarketBuyOrder[]>([])
const buyTotal = ref(0)
const maxActiveBuyOrders = ref(marketCfg.maxActiveBuyOrders)
const myBuyActive = ref<MarketBuyOrder[]>([])
const myBuyClosed = ref<MarketBuyOrder[]>([])
const buyOrderOpen = ref(false)
const buyTab = ref<StackTab>('material')
const buySearch = ref('')
const buyEdits = ref<Record<string, { count: number; price: number }>>({})
const fillTarget = ref<MarketBuyOrder | null>(null)
const fillCount = ref(1)

const listingOpen = ref(false)
const equipPickOpen = ref(false)
const equipmentTab = ref<StackTab>('material')
const busy = ref(false)

// 上架装备：选中一件后填写单价
const pendingEquip = ref<Item | null>(null)
const equipPrice = ref(1)

// 上架堆叠物：每个物品一行，键 = kind:itemId
interface StackRow {
  key: string
  kind: StackKind
  itemId: string
  name: string
  have: number
  sell: number
  reference: number
}
const stackEdits = ref<Record<string, { count: number; price: number }>>({})

/** 堆叠物参考价（按来源成本折算，来自共享配置），回退到系统回收价。 */
function stackReference(kind: StackKind, itemId: string, sell: number): number {
  const table = data.marketReference.stacks[kind] ?? {}
  return Math.max(table[itemId] ?? 0, sell)
}

// 购买确认
const buyTarget = ref<MarketListing | null>(null)

const feeExplain = marketFeeExplain()

const listableItems = computed<Item[]>(() => game.items.filter((i) => !i.equippedSlot))

function toStackRows(items: MaterialStackItem[] | undefined): StackRow[] {
  return (items ?? []).map((m) => ({
    key: `${m.kind}:${m.itemId}`,
    kind: m.kind as StackKind,
    itemId: m.itemId,
    name: m.name,
    have: m.count,
    sell: m.sell ?? 0,
    reference: stackReference(m.kind as StackKind, m.itemId, m.sell ?? 0),
  }))
}

const materialRows = computed<StackRow[]>(() => toStackRows(dohdol.state?.materials))
const consumableRows = computed<StackRow[]>(() => toStackRows(dohdol.state?.consumables))
const materiaRows = computed<StackRow[]>(() => toStackRows(dohdol.state?.materia))
const seedRows = computed<StackRow[]>(() => toStackRows(dohdol.state?.seeds))

/** 当前上架子页签对应的可上架行。 */
const stackRows = computed<StackRow[]>(() => {
  switch (equipmentTab.value) {
    case 'consumable':
      return consumableRows.value
    case 'materia':
      return materiaRows.value
    case 'seed':
      return seedRows.value
    default:
      return materialRows.value
  }
})

const kindParam = computed(() =>
  tab.value === 'mine' || tab.value === 'wanted' ? 'all' : tab.value,
)

const STACK_TABS: { id: StackTab; label: string }[] = [
  { id: 'material', label: '素材' },
  { id: 'consumable', label: '消耗品' },
  { id: 'materia', label: '魔晶石' },
  { id: 'seed', label: '种子' },
]

const stackTabLabel = computed(
  () => STACK_TABS.find((t) => t.id === equipmentTab.value)?.label ?? '堆叠物',
)

// ------------------------------------------------------------------ 收购单（求购）
/** 可求购的堆叠物目录（来自共享配置，与后端 material_def / sellable_kind 同源，不是我的库存）。 */
interface BuyCandidate {
  kind: StackKind
  itemId: string
  name: string
  sell: number
  reference: number
}

const buyCatalog = computed<BuyCandidate[]>(() => [
  ...Object.values(data.materialById).map((m) => ({
    kind: 'material' as const,
    itemId: m.id,
    name: m.name,
    sell: m.sell ?? 0,
    reference: stackReference('material', m.id, m.sell ?? 0),
  })),
  ...data.consumables.items.map((c) => ({
    kind: c.kind as StackKind,
    itemId: c.id,
    name: c.name,
    sell: c.sell ?? 0,
    reference: stackReference(c.kind as StackKind, c.id, c.sell ?? 0),
  })),
  ...Object.values(data.materiaById).map((m) => ({
    kind: 'materia' as const,
    itemId: m.id,
    name: m.name,
    sell: m.sell,
    reference: stackReference('materia', m.id, m.sell),
  })),
  ...data.farm.seeds.map((s) => ({
    kind: 'seed' as const,
    itemId: s.id,
    name: s.name,
    sell: s.sell,
    reference: stackReference('seed', s.id, s.sell),
  })),
])

const buyTabLabel = computed(() => STACK_TABS.find((t) => t.id === buyTab.value)?.label ?? '堆叠物')

/** 当前子页签 + 搜索词下的求购候选。 */
const buyCandidates = computed<BuyCandidate[]>(() => {
  const kinds = buyTab.value === 'consumable' ? ['potion', 'food'] : [buyTab.value]
  const needle = buySearch.value.trim().toLowerCase()
  return buyCatalog.value
    .filter((c) => kinds.includes(c.kind))
    .filter((c) => !needle || c.name.toLowerCase().includes(needle))
})

function buyKey(row: BuyCandidate): string {
  return `${row.kind}:${row.itemId}`
}

function buyEditOf(row: BuyCandidate) {
  return buyEdits.value[buyKey(row)] ?? { count: 1, price: Math.max(1, row.reference) }
}

function setBuyEdit(row: BuyCandidate, field: 'count' | 'price', e: Event) {
  const raw = Number((e.target as HTMLInputElement).value)
  const value = Number.isFinite(raw) ? Math.max(0, Math.floor(raw)) : 0
  buyEdits.value = { ...buyEdits.value, [buyKey(row)]: { ...buyEditOf(row), [field]: value } }
}

/** 我在该堆叠物上的持有量（「卖给 TA」的数量上限）。 */
function ownedCount(kind: string, itemId: string): number {
  const list =
    kind === 'material'
      ? dohdol.state?.materials
      : kind === 'materia'
        ? dohdol.state?.materia
        : kind === 'seed'
          ? dohdol.state?.seeds
          : dohdol.state?.consumables
  return list?.find((m) => m.itemId === itemId)?.count ?? 0
}

async function submitBuyOrder(row: BuyCandidate) {
  const edit = buyEditOf(row)
  if (busy.value) return
  if (edit.count < 1) {
    toast.push('求购数量至少为 1', 'error')
    return
  }
  if (edit.price < marketCfg.minPrice) {
    toast.push(`单价不能低于 ${marketCfg.minPrice}`, 'error')
    return
  }
  busy.value = true
  try {
    await api.marketBuyOrderCreate({
      kind: row.kind,
      itemId: row.itemId,
      quantity: edit.count,
      unitPrice: edit.price,
    })
    toast.push(
      `已发布收购：${row.name} ×${edit.count}（托管 ${formatNumber(edit.count * edit.price)} 金币）`,
      'success',
    )
    delete buyEdits.value[buyKey(row)]
    buyEdits.value = { ...buyEdits.value }
    buyOrderOpen.value = false
    await refreshState()
    await refresh()
  } catch (err) {
    toast.push(err instanceof Error ? err.message : '发布收购失败', 'error')
  } finally {
    busy.value = false
  }
}

function openFill(order: MarketBuyOrder) {
  fillTarget.value = order
  fillCount.value = Math.max(1, Math.min(order.remaining, ownedCount(order.kind, order.itemKey)))
}

async function confirmFill() {
  const order = fillTarget.value
  if (!order || busy.value) return
  const count = Math.max(1, Math.floor(fillCount.value))
  busy.value = true
  try {
    const res = await api.marketBuyOrderFill(order.id, count)
    toast.push(
      `卖出 ${order.name} ×${res.count}，实收 ${formatNumber(res.total - res.fee)} 金币` +
        (res.status === 'filled' ? '（收购单已完成）' : ''),
      'success',
    )
    fillTarget.value = null
    await refreshState()
    await refresh()
  } catch (err) {
    toast.push(err instanceof Error ? err.message : '出售失败', 'error')
  } finally {
    busy.value = false
  }
}

async function cancelBuyOrder(order: MarketBuyOrder) {
  if (busy.value) return
  busy.value = true
  try {
    const res = await api.marketBuyOrderCancel(order.id)
    toast.push(`已取消收购，退还 ${formatNumber(res.refund)} 金币`, 'info')
    await refreshState()
    await refresh()
  } catch (err) {
    toast.push(err instanceof Error ? err.message : '取消收购失败', 'error')
  } finally {
    busy.value = false
  }
}

function setView(v: ViewMode) {
  view.value = v
  localStorage.setItem(VIEW_KEY, v)
}

function kindLabel(kind: string): string {
  if (kind === 'equipment') return '装备'
  if (kind === 'material') return '素材'
  if (kind === 'materia') return '魔晶石'
  if (kind === 'seed') return '种子'
  return '消耗品'
}

const REQ_KIND_LABEL: Record<string, string> = {
  combat: '任一英雄',
  doh: '生产职业',
  dol: '采集职业',
}

/** 购买等级门槛文案；素材 / 消耗品等无门槛返回空串。 */
function reqText(l: MarketListing): string {
  if (!l.requiredKind || l.levelReq == null) return ''
  return `${REQ_KIND_LABEL[l.requiredKind] ?? ''}等级需达到 ${l.levelReq}`
}

/** 当前玩家是否因等级不足无法购买该寄售单。 */
function levelLocked(l: MarketListing): boolean {
  return l.levelMet === false
}

/** 四舍五入到 1 位小数，整数则省略小数。 */
function attrValue(value: number): string {
  return Number.isInteger(value) ? String(value) : value.toFixed(1)
}

function feeOf(total_: number): number {
  return Math.floor(total_ * feePct.value)
}

function netOf(total_: number): number {
  return total_ - feeOf(total_)
}

function expireText(iso: string | null): string {
  if (!iso) return ''
  const ms = Date.parse(iso) - Date.now()
  if (ms <= 0) return '即将到期'
  const hours = Math.floor(ms / 3_600_000)
  if (hours >= 24) return `${Math.floor(hours / 24)} 天后到期`
  if (hours >= 1) return `${hours} 小时后到期`
  return `${Math.max(1, Math.floor(ms / 60_000))} 分钟后到期`
}

async function refreshState() {
  await game.loadState()
}

async function loadListings() {
  loading.value = true
  try {
    const res = await api.marketListings({
      kind: kindParam.value,
      rarity: rarity.value === 'all' ? undefined : rarity.value,
      q: q.value.trim() || undefined,
      sort: sort.value,
      page: page.value,
      pageSize: PAGE_SIZE,
    })
    listings.value = res.listings
    total.value = res.total
    feePct.value = res.feePct
    listingDays.value = res.listingDays
    maxActiveListings.value = res.maxActiveListings
  } catch (err) {
    toast.push(err instanceof Error ? err.message : '加载市场失败', 'error')
  } finally {
    loading.value = false
  }
}

async function loadMine() {
  loading.value = true
  try {
    const res = await api.marketMine()
    mineActive.value = res.active
    mineClosed.value = res.closed
    feePct.value = res.feePct
    maxActiveListings.value = res.maxActiveListings
    await loadMyBuyOrders()
  } catch (err) {
    toast.push(err instanceof Error ? err.message : '加载我的寄售失败', 'error')
  } finally {
    loading.value = false
  }
}

async function loadBuyOrders() {
  loading.value = true
  try {
    const res = await api.marketBuyOrders({
      kind: kindParam.value,
      sort: sort.value,
      page: page.value,
      pageSize: PAGE_SIZE,
    })
    buyOrders.value = res.orders
    buyTotal.value = res.total
    feePct.value = res.feePct
    listingDays.value = res.listingDays
    maxActiveBuyOrders.value = res.maxActiveBuyOrders
  } catch (err) {
    toast.push(err instanceof Error ? err.message : '加载收购单失败', 'error')
  } finally {
    loading.value = false
  }
}

async function loadMyBuyOrders() {
  try {
    const res = await api.marketBuyOrdersMine()
    myBuyActive.value = res.active
    myBuyClosed.value = res.closed
    maxActiveBuyOrders.value = res.maxActiveBuyOrders
  } catch (err) {
    toast.push(err instanceof Error ? err.message : '加载我的收购失败', 'error')
  }
}

async function refresh() {
  if (tab.value === 'mine') await loadMine()
  else if (tab.value === 'wanted') await loadBuyOrders()
  else await loadListings()
}

let searchTimer: number | null = null
watch([tab, sort, rarity, page], () => {
  if (tab.value === 'mine') void loadMine()
  else if (tab.value === 'wanted') void loadBuyOrders()
  else void loadListings()
})
watch(q, () => {
  if (searchTimer !== null) window.clearTimeout(searchTimer)
  searchTimer = window.setTimeout(() => {
    page.value = 1
    if (tab.value !== 'mine' && tab.value !== 'wanted') void loadListings()
  }, 300)
})

onMounted(async () => {
  if (!game.state) await game.loadState()
  await loadListings()
})

// ------------------------------------------------------------------ 上架
function onEquipPicked(item: Item) {
  pendingEquip.value = item
  const suggested = item.referencePrice || item.sellPriceMax || 1
  equipPrice.value = Math.max(1, Math.min(suggested, marketCfg.maxPrice))
  equipPickOpen.value = false
}

function editOf(row: StackRow) {
  return stackEdits.value[row.key] ?? { count: row.have, price: Math.max(1, row.reference) }
}

function setEdit(row: StackRow, field: 'count' | 'price', e: Event) {
  const raw = Number((e.target as HTMLInputElement).value)
  const value = Number.isFinite(raw) ? Math.max(0, Math.floor(raw)) : 0
  stackEdits.value = { ...stackEdits.value, [row.key]: { ...editOf(row), [field]: value } }
}

function useAll(row: StackRow) {
  stackEdits.value = { ...stackEdits.value, [row.key]: { ...editOf(row), count: row.have } }
}

async function submitEquipment() {
  if (!pendingEquip.value || busy.value) return
  if (equipPrice.value < marketCfg.minPrice) {
    toast.push(`单价不能低于 ${marketCfg.minPrice}`, 'error')
    return
  }
  busy.value = true
  try {
    await api.marketList([
      { type: 'equipment', itemId: pendingEquip.value.id, count: 1, unitPrice: equipPrice.value },
    ])
    toast.push(`已上架「${pendingEquip.value.name}」`, 'success')
    pendingEquip.value = null
    await refreshState()
    await refresh()
  } catch (err) {
    toast.push(err instanceof Error ? err.message : '上架失败', 'error')
  } finally {
    busy.value = false
  }
}

async function submitStack(row: StackRow) {
  const edit = editOf(row)
  if (busy.value) return
  if (edit.count < 1) {
    toast.push('数量至少为 1', 'error')
    return
  }
  if (edit.price < marketCfg.minPrice) {
    toast.push(`单价不能低于 ${marketCfg.minPrice}`, 'error')
    return
  }
  busy.value = true
  try {
    await api.marketList([
      { type: 'stack', stackKind: row.kind, stackItemId: row.itemId, count: edit.count, unitPrice: edit.price },
    ])
    toast.push(`已上架 ${row.name} ×${edit.count}`, 'success')
    delete stackEdits.value[row.key]
    stackEdits.value = { ...stackEdits.value }
    await refreshState()
    await refresh()
  } catch (err) {
    toast.push(err instanceof Error ? err.message : '上架失败', 'error')
  } finally {
    busy.value = false
  }
}

// ------------------------------------------------------------------ 购买 / 下架
function openBuy(listing: MarketListing) {
  buyTarget.value = listing
}

async function confirmBuy() {
  if (!buyTarget.value || busy.value) return
  busy.value = true
  try {
    const res = await api.marketBuy(buyTarget.value.id)
    toast.push(`购买成功，花费 ${formatNumber(res.total)} 金币`, 'success')
    buyTarget.value = null
    await refreshState()
    await refresh()
  } catch (err) {
    toast.push(err instanceof Error ? err.message : '购买失败', 'error')
  } finally {
    busy.value = false
  }
}

async function cancel(listing: MarketListing) {
  if (busy.value) return
  busy.value = true
  try {
    await api.marketCancel(listing.id)
    toast.push('已下架，物品已退回', 'success')
    await refreshState()
    await refresh()
  } catch (err) {
    toast.push(err instanceof Error ? err.message : '下架失败', 'error')
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <div class="space-y-4">
    <!-- 标题 + 手续费说明 -->
    <section class="card p-4">
      <div class="flex flex-wrap items-center justify-between gap-2">
        <h2 class="text-lg font-semibold text-white">市场交易板</h2>
        <button
          class="rounded-lg bg-amber-500 px-3 py-1.5 text-xs font-medium text-ink-950 transition hover:bg-amber-400"
          @click="listingOpen = !listingOpen"
        >
          {{ listingOpen ? '收起上架' : '我要上架' }}
        </button>
      </div>
      <p class="mt-2 text-xs leading-relaxed text-ink-400">
        玩家之间自由定价交易装备 / 素材 / 消耗品，整单买断成交，成交价抽取
        {{ (feePct * 100).toFixed(0) }}% 手续费。上架即从背包 / 库存扣除进入托管，未售出
        {{ listingDays }} 天自动退回。
        <InfoTip :title="feeExplain.title">
          <p v-for="(line, i) in feeExplain.lines" :key="i">{{ line }}</p>
        </InfoTip>
      </p>
    </section>

    <!-- 上架区 -->
    <section v-if="listingOpen" class="card space-y-4 p-4">
      <div class="text-sm font-semibold text-ink-100">上架物品</div>

      <!-- 装备 -->
      <div class="space-y-2 rounded-lg border border-ink-700 p-3">
        <div class="flex items-center justify-between">
          <span class="text-xs font-medium text-ink-200">装备（唯一实例，数量恒为 1）</span>
          <button
            class="rounded border border-ink-600 px-2 py-1 text-xs text-ink-200 transition hover:border-amber-400 hover:text-amber-200"
            @click="equipPickOpen = true"
          >
            选择装备
          </button>
        </div>
        <div v-if="pendingEquip" class="flex flex-wrap items-center gap-2 text-xs">
          <ItemIcon :base-id="pendingEquip.baseId" :rarity="pendingEquip.rarity" :size="24" />
          <span class="text-ink-200">{{ pendingEquip.name }}</span>
          <span class="text-ink-500">参考价 {{ formatNumber(pendingEquip.referencePrice) }} · 回收 {{ pendingEquip.sellPriceMin }}~{{ pendingEquip.sellPriceMax }}</span>
          <label class="ml-auto flex items-center gap-1 text-ink-400">
            单价
            <input
              v-model.number="equipPrice"
              type="number"
              min="1"
              class="w-24 rounded border border-ink-600 bg-ink-900 px-2 py-1 text-right text-ink-100"
            />
          </label>
          <button
            class="rounded bg-amber-500 px-3 py-1 font-medium text-ink-950 transition hover:bg-amber-400 disabled:opacity-50"
            :disabled="busy"
            @click="submitEquipment"
          >
            上架
          </button>
        </div>
        <p v-else class="text-xs text-ink-500">选择一件未装备的物品上架。</p>
      </div>

      <!-- 素材 / 消耗品 / 魔晶石 / 种子 -->
      <div class="space-y-2 rounded-lg border border-ink-700 p-3">
        <div class="flex flex-wrap items-center gap-2">
          <button
            v-for="t in STACK_TABS"
            :key="t.id"
            class="rounded px-2.5 py-1 text-xs transition"
            :class="equipmentTab === t.id ? 'bg-amber-500 text-ink-950' : 'text-ink-400 hover:text-ink-200'"
            @click="equipmentTab = t.id"
          >
            {{ t.label }}
          </button>
        </div>

        <div
          v-for="row in stackRows"
          :key="row.key"
          class="flex flex-wrap items-center gap-2 border-t border-ink-800 py-2 text-xs first:border-t-0"
        >
          <ItemIcon :base-id="row.itemId" variant="plain" :size="20" />
          <span class="text-ink-200">{{ row.name }}</span>
          <span class="text-ink-500">持有 {{ formatNumber(row.have) }} · 参考价 {{ formatNumber(row.reference) }} · 回收 {{ row.sell }}</span>
          <label class="ml-auto flex items-center gap-1 text-ink-400">
            数量
            <input
              type="number"
              min="1"
              :max="row.have"
              class="w-20 rounded border border-ink-600 bg-ink-900 px-2 py-1 text-right text-ink-100"
              :value="editOf(row).count"
              @input="setEdit(row, 'count', $event)"
            />
            <button class="text-[10px] text-amber-300 hover:text-amber-200" @click="useAll(row)">全部</button>
          </label>
          <label class="flex items-center gap-1 text-ink-400">
            单价
            <input
              type="number"
              min="1"
              class="w-20 rounded border border-ink-600 bg-ink-900 px-2 py-1 text-right text-ink-100"
              :value="editOf(row).price"
              @input="setEdit(row, 'price', $event)"
            />
          </label>
          <button
            class="rounded bg-amber-500 px-3 py-1 font-medium text-ink-950 transition hover:bg-amber-400 disabled:opacity-50"
            :disabled="busy"
            @click="submitStack(row)"
          >
            上架
          </button>
        </div>
        <p v-if="!stackRows.length" class="py-4 text-center text-xs text-ink-400">
          暂无可上架的{{ stackTabLabel }}。
        </p>
      </div>
    </section>

    <!-- 浏览 / 我的寄售 -->
    <section class="card space-y-3 p-4">
      <!-- 桌面子页签 -->
      <div class="hidden gap-1 overflow-x-auto rounded-lg bg-ink-800 p-1 text-xs md:flex">
        <button
          v-for="t in TABS"
          :key="t.id"
          class="flex-1 rounded px-3 py-1.5 transition"
          :class="tab === t.id ? 'bg-amber-500 text-ink-950' : 'text-ink-400 hover:text-ink-200'"
          @click="tab = t.id"
        >
          {{ t.label }}
        </button>
      </div>
      <!-- 移动端子页签 -->
      <select v-model="tab" class="w-full rounded border border-ink-600 bg-ink-900 px-2 py-1.5 text-xs md:hidden">
        <option v-for="t in TABS" :key="t.id" :value="t.id">{{ t.label }}</option>
      </select>

      <!-- 筛选 -->
      <div v-if="tab !== 'mine'" class="flex flex-wrap items-center gap-2 text-xs">
        <template v-if="tab !== 'wanted'">
          <input
            v-model="q"
            type="text"
            placeholder="按名称搜索"
            class="rounded border border-ink-600 bg-ink-900 px-2 py-1.5 text-ink-100"
          />
          <select v-model="rarity" class="rounded border border-ink-600 bg-ink-900 px-2 py-1.5">
            <option value="all">全部品阶</option>
            <option v-for="r in RARITY_ORDER" :key="r" :value="r">{{ rarityName(r) }}</option>
          </select>
        </template>
        <select v-model="sort" class="rounded border border-ink-600 bg-ink-900 px-2 py-1.5">
          <option v-for="s in SORTS" :key="s.id" :value="s.id">{{ s.label }}</option>
        </select>

        <div v-if="tab !== 'wanted'" class="ml-auto flex gap-0.5 rounded-lg bg-ink-800 p-0.5">
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
        <button
          v-else
          class="ml-auto rounded bg-amber-500 px-3 py-1.5 font-medium text-ink-950 transition hover:bg-amber-400"
          @click="buyOrderOpen = true"
        >
          发布收购
        </button>
      </div>

      <!-- 我的寄售 -->
      <div v-if="tab === 'mine'" class="space-y-3">
        <p class="text-xs text-ink-400">
          在售 {{ mineActive.length }} / {{ maxActiveListings }} 单
        </p>
        <div v-if="mineActive.length" class="space-y-2">
          <div
            v-for="l in mineActive"
            :key="l.id"
            class="flex flex-wrap items-center gap-2 rounded-lg border border-ink-700 p-2 text-xs"
          >
            <ItemIcon :base-id="l.itemKey" :rarity="l.rarity ?? undefined" :size="24" :variant="l.kind === 'equipment' ? 'full' : 'plain'" />
            <span class="text-ink-100">{{ l.name }}</span>
            <span v-if="l.quantity > 1" class="text-ink-500">×{{ l.quantity }}</span>
            <span class="text-amber-300">{{ formatNumber(l.unitPrice) }} / 件</span>
            <span class="text-ink-500">总价 {{ formatNumber(l.totalPrice) }}</span>
            <span class="text-ink-500">{{ expireText(l.expiresAt) }}</span>
            <button
              class="ml-auto rounded border border-rose-500/40 px-2 py-1 text-rose-300 transition hover:bg-rose-500/10 disabled:opacity-50"
              :disabled="busy"
              @click="cancel(l)"
            >
              下架
            </button>
          </div>
        </div>
        <p v-else class="py-6 text-center text-xs text-ink-400">暂无在售寄售。</p>

        <details class="text-xs">
          <summary class="cursor-pointer text-ink-400">已结束记录（{{ mineClosed.length }}）</summary>
          <div class="mt-2 space-y-1">
            <div v-for="l in mineClosed" :key="l.id" class="flex flex-wrap items-center gap-2 text-ink-500">
              <span>{{ l.name }}</span>
              <span v-if="l.quantity > 1">×{{ l.quantity }}</span>
              <span>{{ formatNumber(l.unitPrice) }} / 件</span>
              <span
                class="rounded px-1.5 py-0.5"
                :class="l.status === 'sold' ? 'bg-emerald-500/20 text-emerald-300' : 'bg-ink-700 text-ink-300'"
              >
                {{ l.status === 'sold' ? '已售出' : l.status === 'expired' ? '已过期' : '已下架' }}
              </span>
              <span v-if="l.status === 'sold' && l.buyerNickname" class="text-emerald-300/80">
                被 {{ l.buyerNickname }} 买走
              </span>
            </div>
          </div>
        </details>

        <!-- 我的收购（求购） -->
        <div class="border-t border-ink-800 pt-3">
          <p class="text-xs text-ink-400">
            我的收购 {{ myBuyActive.length }} / {{ maxActiveBuyOrders }} 单
          </p>
          <div v-if="myBuyActive.length" class="mt-2 space-y-2">
            <div
              v-for="o in myBuyActive"
              :key="o.id"
              class="flex flex-wrap items-center gap-2 rounded-lg border border-ink-700 p-2 text-xs"
            >
              <ItemIcon :base-id="o.itemKey" :size="24" variant="plain" />
              <span class="text-ink-100">{{ o.name }}</span>
              <span class="text-amber-300">{{ formatNumber(o.unitPrice) }} / 件</span>
              <span class="text-ink-500">剩余 {{ formatNumber(o.remaining) }} / {{ formatNumber(o.quantity) }}</span>
              <span class="text-ink-500">托管 {{ formatNumber(o.remainingPrice) }}</span>
              <span class="text-ink-500">{{ expireText(o.expiresAt) }}</span>
              <button
                class="ml-auto rounded border border-rose-500/40 px-2 py-1 text-rose-300 transition hover:bg-rose-500/10 disabled:opacity-50"
                :disabled="busy"
                @click="cancelBuyOrder(o)"
              >
                取消
              </button>
            </div>
          </div>
          <p v-else class="mt-2 text-center text-xs text-ink-400">暂无进行中的收购。</p>

          <details v-if="myBuyClosed.length" class="mt-2 text-xs">
            <summary class="cursor-pointer text-ink-400">收购记录（{{ myBuyClosed.length }}）</summary>
            <div class="mt-2 space-y-1">
              <div v-for="o in myBuyClosed" :key="o.id" class="flex flex-wrap items-center gap-2 text-ink-500">
                <span>{{ o.name }}</span>
                <span>{{ formatNumber(o.unitPrice) }} / 件</span>
                <span>已成交 {{ formatNumber(o.filled) }} / {{ formatNumber(o.quantity) }}</span>
                <span
                  class="rounded px-1.5 py-0.5"
                  :class="o.status === 'filled' ? 'bg-emerald-500/20 text-emerald-300' : 'bg-ink-700 text-ink-300'"
                >
                  {{ o.status === 'filled' ? '已完成' : o.status === 'expired' ? '已过期' : '已取消' }}
                </span>
              </div>
            </div>
          </details>
        </div>
      </div>

      <!-- 收购单（求购） -->
      <div v-else-if="tab === 'wanted'" class="space-y-3">
        <p class="text-xs text-ink-400">
          发布收购会按「单价 × 数量」全额托管金币；卖家可分批卖出，未成交部分在下架 / 到期时退还。
        </p>
        <p v-if="loading" class="py-8 text-center text-xs text-ink-500">加载中…</p>
        <p v-else-if="!buyOrders.length" class="py-10 text-center text-xs text-ink-400">
          暂无收购单，点击「发布收购」成为第一个买家。
        </p>
        <div v-else class="space-y-2">
          <div
            v-for="o in buyOrders"
            :key="o.id"
            class="flex flex-wrap items-center gap-2 rounded-lg border border-ink-700 p-2 text-xs"
          >
            <ItemIcon :base-id="o.itemKey" :size="24" variant="plain" />
            <span class="text-ink-100">{{ o.name }}</span>
            <span class="rounded bg-ink-800 px-1.5 py-0.5 text-[10px] text-ink-400">{{ kindLabel(o.kind) }}</span>
            <span class="text-amber-300">{{ formatNumber(o.unitPrice) }} / 件</span>
            <span class="text-ink-500">剩余 {{ formatNumber(o.remaining) }} / {{ formatNumber(o.quantity) }}</span>
            <span class="text-ink-500">买家 {{ o.buyerNickname }}</span>
            <span class="text-ink-500">{{ expireText(o.expiresAt) }}</span>
            <span v-if="ownedCount(o.kind, o.itemKey) < 1" class="text-ink-400">（你没有该物品）</span>
            <button
              class="ml-auto rounded bg-amber-500 px-3 py-1 font-medium text-ink-950 transition hover:bg-amber-400 disabled:opacity-50"
              :disabled="busy || ownedCount(o.kind, o.itemKey) < 1"
              @click="openFill(o)"
            >
              卖给 TA
            </button>
          </div>
        </div>
        <div v-if="buyTotal > PAGE_SIZE" class="flex items-center justify-center gap-2 text-xs">
          <button
            class="rounded border border-ink-600 px-2 py-1 text-ink-200 transition hover:border-amber-400 disabled:opacity-50"
            :disabled="page <= 1"
            @click="page -= 1"
          >
            上一页
          </button>
          <span class="text-ink-400">
            {{ page }} / {{ Math.max(1, Math.ceil(buyTotal / PAGE_SIZE)) }}
          </span>
          <button
            class="rounded border border-ink-600 px-2 py-1 text-ink-200 transition hover:border-amber-400 disabled:opacity-50"
            :disabled="page * PAGE_SIZE >= buyTotal"
            @click="page += 1"
          >
            下一页
          </button>
        </div>
      </div>

      <!-- 市场列表 -->
      <div v-else>
        <p v-if="loading" class="py-8 text-center text-xs text-ink-500">加载中…</p>
        <p v-else-if="!listings.length" class="py-10 text-center text-xs text-ink-400">暂无寄售，点击「我要上架」成为第一个卖家。</p>

        <!-- 卡片视图 -->
        <div v-else-if="view === 'card'" class="space-y-2">
          <div v-for="l in listings" :key="l.id" class="rounded-lg border border-ink-700 p-3">
            <div class="flex flex-wrap items-start gap-3">
              <ItemIcon :base-id="l.itemKey" :rarity="l.rarity ?? undefined" :size="40" :variant="l.kind === 'equipment' ? 'full' : 'plain'" />
              <div class="min-w-0 flex-1">
                <div class="flex flex-wrap items-center gap-2 text-sm">
                  <span class="text-ink-100">{{ l.name }}</span>
                  <span v-if="l.rarity" class="text-xs text-ink-400">{{ rarityName(l.rarity) }}</span>
                  <span v-if="l.levelReq" class="text-xs text-ink-500">Lv.{{ l.levelReq }}</span>
                  <span v-if="levelLocked(l)" class="rounded bg-rose-500/15 px-1.5 py-0.5 text-[10px] text-rose-300">{{ reqText(l) }}</span>
                  <span class="rounded bg-ink-800 px-1.5 py-0.5 text-[10px] text-ink-400">{{ kindLabel(l.kind) }}</span>
                </div>
                <div v-if="l.equipment" class="mt-1 flex flex-wrap gap-1 text-[10px] text-ink-400">
                  <span v-for="(a, i) in l.equipment.baseAttrs" :key="`b${i}`" class="rounded bg-ink-800 px-1.5 py-0.5">
                    {{ baseAttrName(a.attr) }}+{{ attrValue(a.value) }}
                  </span>
                  <span v-for="(a, i) in l.equipment.subAttrs" :key="`s${i}`" class="rounded bg-ink-800 px-1.5 py-0.5">
                    {{ attrName(a.attr) }}+{{ attrValue(a.value) }}
                  </span>
                </div>
                <TermBadges v-if="l.equipment?.terms?.length" class="mt-1" :terms="l.equipment.terms" />
                <p class="mt-1 text-xs text-ink-500">
                  卖家 {{ l.sellerNickname ?? '—' }} · 参考价 {{ formatNumber(l.referencePrice) }}
                  <template v-if="l.referencePrice > 0 && l.unitPrice > l.referencePrice">
                    （高于参考价 {{ ((l.unitPrice / l.referencePrice - 1) * 100).toFixed(0) }}%）
                  </template>
                </p>
              </div>
              <div class="flex flex-col items-end gap-1 text-xs">
                <span class="text-amber-300">{{ formatNumber(l.unitPrice) }} / 件</span>
                <span v-if="l.quantity > 1" class="text-ink-400">×{{ l.quantity }} = {{ formatNumber(l.totalPrice) }}</span>
                <button
                  class="rounded bg-amber-500 px-3 py-1 font-medium text-ink-950 transition hover:bg-amber-400 disabled:opacity-50"
                  :disabled="busy || levelLocked(l)"
                  :title="levelLocked(l) ? reqText(l) : ''"
                  @click="openBuy(l)"
                >
                  购买
                </button>
              </div>
            </div>
          </div>
        </div>

        <!-- 列表视图 -->
        <div v-else-if="view === 'list'" class="divide-y divide-ink-800 overflow-hidden rounded-lg border border-ink-700">
          <div v-for="l in listings" :key="l.id" class="flex flex-wrap items-center gap-2 p-2 text-xs">
            <ItemIcon :base-id="l.itemKey" :rarity="l.rarity ?? undefined" :size="20" :variant="l.kind === 'equipment' ? 'full' : 'plain'" />
            <span class="text-ink-100">{{ l.name }}</span>
            <span class="text-ink-500">{{ kindLabel(l.kind) }}</span>
            <span v-if="l.quantity > 1" class="text-ink-500">×{{ l.quantity }}</span>
            <span class="text-ink-500">卖家 {{ l.sellerNickname ?? '—' }}</span>
            <span class="ml-auto text-amber-300">{{ formatNumber(l.unitPrice) }} / 件</span>
            <span v-if="levelLocked(l)" class="text-rose-300">{{ reqText(l) }}</span>
            <button
              class="rounded bg-amber-500 px-3 py-1 font-medium text-ink-950 transition hover:bg-amber-400 disabled:opacity-50"
              :disabled="busy || levelLocked(l)"
              :title="levelLocked(l) ? reqText(l) : ''"
              @click="openBuy(l)"
            >
              购买
            </button>
          </div>
        </div>

        <!-- 网格视图 -->
        <div v-else class="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-5">
          <button
            v-for="l in listings"
            :key="l.id"
            class="flex flex-col items-center gap-1 rounded-lg border border-ink-700 p-2 text-center transition hover:border-amber-400/60 disabled:opacity-60"
            :disabled="busy || levelLocked(l)"
            :title="levelLocked(l) ? reqText(l) : ''"
            @click="openBuy(l)"
          >
            <ItemIcon :base-id="l.itemKey" :rarity="l.rarity ?? undefined" :size="40" :variant="l.kind === 'equipment' ? 'full' : 'plain'" />
            <span class="line-clamp-1 w-full text-[11px] text-ink-200">{{ l.name }}</span>
            <span v-if="l.quantity > 1" class="text-[10px] text-ink-500">×{{ l.quantity }}</span>
            <span class="text-[11px] text-amber-300">{{ formatNumber(l.unitPrice) }}</span>
            <span v-if="levelLocked(l)" class="line-clamp-2 text-[9px] text-rose-300">{{ reqText(l) }}</span>
          </button>
        </div>

        <!-- 翻页 -->
        <nav v-if="total > PAGE_SIZE" class="mt-3 flex items-center justify-center gap-3 text-xs">
          <button
            class="rounded border border-ink-600 px-3 py-1 text-ink-300 transition hover:border-amber-400 disabled:opacity-40"
            :disabled="page <= 1"
            @click="page -= 1"
          >
            上一页
          </button>
          <span class="text-ink-400">第 {{ page }} 页 / 共 {{ Math.max(1, Math.ceil(total / PAGE_SIZE)) }} 页</span>
          <button
            class="rounded border border-ink-600 px-3 py-1 text-ink-300 transition hover:border-amber-400 disabled:opacity-40"
            :disabled="page >= Math.ceil(total / PAGE_SIZE)"
            @click="page += 1"
          >
            下一页
          </button>
        </nav>
      </div>
    </section>

    <!-- 选择要上架的装备 -->
    <ItemPickerModal
      :open="equipPickOpen"
      title="选择要上架的装备"
      :candidates="listableItems"
      @close="equipPickOpen = false"
      @equip="onEquipPicked"
    />

    <!-- 购买确认 -->
    <Modal :open="buyTarget !== null" title="确认购买" @close="buyTarget = null">
      <div v-if="buyTarget" class="space-y-3 text-sm">
        <div class="flex items-center gap-3">
          <ItemIcon :base-id="buyTarget.itemKey" :rarity="buyTarget.rarity ?? undefined" :size="40" :variant="buyTarget.kind === 'equipment' ? 'full' : 'plain'" />
          <div>
            <p class="text-ink-100">{{ buyTarget.name }}<span v-if="buyTarget.quantity > 1"> ×{{ buyTarget.quantity }}</span></p>
            <p class="text-xs text-ink-500">卖家 {{ buyTarget.sellerNickname ?? '—' }} · {{ kindLabel(buyTarget.kind) }}</p>
          </div>
        </div>
        <div class="space-y-1 rounded-lg bg-ink-800/60 p-3 text-xs">
          <div class="flex justify-between text-ink-300">
            <span>单价 × 数量</span>
            <span>{{ formatNumber(buyTarget.unitPrice) }} × {{ buyTarget.quantity }}</span>
          </div>
          <div class="flex justify-between text-ink-100">
            <span>你将支付</span>
            <span class="text-amber-300">{{ formatNumber(buyTarget.totalPrice) }} 金币</span>
          </div>
          <div class="flex justify-between text-ink-400">
            <span>手续费（{{ (feePct * 100).toFixed(0) }}%）</span>
            <span>{{ formatNumber(feeOf(buyTarget.totalPrice)) }}</span>
          </div>
          <div class="flex justify-between text-ink-400">
            <span>卖家实收</span>
            <span>{{ formatNumber(netOf(buyTarget.totalPrice)) }}</span>
          </div>
          <p class="pt-1 text-[10px] text-ink-500">当前持有 {{ formatNumber(game.gold) }} 金币</p>
        </div>
      </div>
      <template #footer>
        <button class="rounded border border-ink-600 px-3 py-1.5 text-xs text-ink-300" @click="buyTarget = null">
          取消
        </button>
        <button
          class="rounded bg-amber-500 px-3 py-1.5 text-xs font-medium text-ink-950 transition hover:bg-amber-400 disabled:opacity-50"
          :disabled="busy"
          @click="confirmBuy"
        >
          确认购买
        </button>
      </template>
    </Modal>

    <!-- 发布收购 -->
    <Modal :open="buyOrderOpen" title="发布收购（托管金币）" max-width="max-w-2xl" @close="buyOrderOpen = false">
      <div class="space-y-3 text-xs">
        <p class="text-ink-400">
          按「单价 × 数量」全额托管金币；卖家可分批卖出，未成交部分在下架 / 到期时自动退还。
        </p>
        <div class="flex flex-wrap items-center gap-2">
          <button
            v-for="t in STACK_TABS"
            :key="t.id"
            class="rounded px-2.5 py-1 transition"
            :class="buyTab === t.id ? 'bg-amber-500 text-ink-950' : 'text-ink-400 hover:text-ink-200'"
            @click="buyTab = t.id"
          >
            {{ t.label }}
          </button>
          <input
            v-model="buySearch"
            type="text"
            placeholder="按名称搜索"
            class="ml-auto rounded border border-ink-600 bg-ink-900 px-2 py-1 text-ink-100"
          />
        </div>
        <div class="max-h-[50vh] overflow-y-auto pr-1">
          <div
            v-for="row in buyCandidates"
            :key="buyKey(row)"
            class="flex flex-wrap items-center gap-2 border-t border-ink-800 py-2 first:border-t-0"
          >
            <ItemIcon :base-id="row.itemId" variant="plain" :size="20" />
            <span class="text-ink-200">{{ row.name }}</span>
            <span class="text-ink-500">参考价 {{ formatNumber(row.reference) }}</span>
            <label class="ml-auto flex items-center gap-1 text-ink-400">
              数量
              <input
                type="number"
                min="1"
                class="w-20 rounded border border-ink-600 bg-ink-900 px-2 py-1 text-right text-ink-100"
                :value="buyEditOf(row).count"
                @input="setBuyEdit(row, 'count', $event)"
              />
            </label>
            <label class="flex items-center gap-1 text-ink-400">
              单价
              <input
                type="number"
                min="1"
                class="w-20 rounded border border-ink-600 bg-ink-900 px-2 py-1 text-right text-ink-100"
                :value="buyEditOf(row).price"
                @input="setBuyEdit(row, 'price', $event)"
              />
            </label>
            <button
              class="rounded bg-amber-500 px-3 py-1 font-medium text-ink-950 transition hover:bg-amber-400 disabled:opacity-50"
              :disabled="busy"
              @click="submitBuyOrder(row)"
            >
              发布
            </button>
          </div>
          <p v-if="!buyCandidates.length" class="py-4 text-center text-ink-400">
            没有匹配的{{ buyTabLabel }}。
          </p>
        </div>
        <p class="text-[10px] text-ink-500">当前持有 {{ formatNumber(game.gold) }} 金币</p>
      </div>
    </Modal>

    <!-- 卖给收购单 -->
    <Modal :open="fillTarget !== null" title="卖给收购单" @close="fillTarget = null">
      <div v-if="fillTarget" class="space-y-3 text-sm">
        <div class="flex items-center gap-3">
          <ItemIcon :base-id="fillTarget.itemKey" :size="40" variant="plain" />
          <div>
            <p class="text-ink-100">{{ fillTarget.name }}</p>
            <p class="text-xs text-ink-500">
              买家 {{ fillTarget.buyerNickname ?? '—' }} · {{ kindLabel(fillTarget.kind) }}
            </p>
          </div>
        </div>
        <div class="space-y-1 rounded-lg bg-ink-800/60 p-3 text-xs">
          <div class="flex justify-between text-ink-300">
            <span>单价</span>
            <span>{{ formatNumber(fillTarget.unitPrice) }} 金币</span>
          </div>
          <div class="flex justify-between text-ink-300">
            <span>收购单剩余</span>
            <span>{{ formatNumber(fillTarget.remaining) }} 件</span>
          </div>
          <div class="flex justify-between text-ink-300">
            <span>我的持有</span>
            <span>{{ formatNumber(ownedCount(fillTarget.kind, fillTarget.itemKey)) }} 件</span>
          </div>
          <div class="flex justify-between text-ink-400">
            <span>手续费（{{ (feePct * 100).toFixed(0) }}%）</span>
            <span>{{ formatNumber(feeOf(fillTarget.unitPrice * fillCount)) }}</span>
          </div>
          <div class="flex justify-between text-ink-100">
            <span>你将实收</span>
            <span class="text-amber-300">
              {{ formatNumber(netOf(fillTarget.unitPrice * fillCount)) }} 金币
            </span>
          </div>
        </div>
        <label class="flex items-center gap-2 text-xs text-ink-400">
          卖出数量
          <input
            v-model.number="fillCount"
            type="number"
            min="1"
            :max="Math.min(fillTarget.remaining, ownedCount(fillTarget.kind, fillTarget.itemKey))"
            class="w-24 rounded border border-ink-600 bg-ink-900 px-2 py-1 text-right text-ink-100"
          />
        </label>
      </div>
      <template #footer>
        <button class="rounded border border-ink-600 px-3 py-1.5 text-xs text-ink-300" @click="fillTarget = null">
          取消
        </button>
        <button
          class="rounded bg-amber-500 px-3 py-1.5 text-xs font-medium text-ink-950 transition hover:bg-amber-400 disabled:opacity-50"
          :disabled="busy || fillCount < 1"
          @click="confirmFill"
        >
          确认卖出
        </button>
      </template>
    </Modal>
  </div>
</template>
