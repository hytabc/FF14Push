<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'

import { api } from '@/api'
import data from '@shared/schema'
import ItemIcon from '@/components/ItemIcon.vue'
import SearchSelect, { type SearchOption } from '@/components/SearchSelect.vue'
import { useVisibleLimit } from '@/composables/useVisibleLimit'
import { useToastStore } from '@/stores/toast'
import type { CodexProgress, JobRole, RarityId, TermQuality } from '@/game/types'
import { RARITY_ORDER, TERM_CATEGORY_OPTIONS, attrName, baseAttrName, categoryName, jobName, rarityName, slotName, termCategoryName, termQualityClass, termQualityName } from '@/utils/format'
import {
  applyFishFilters,
  createFishFilters,
  hasFishFilters,
  presentFishValues,
  type FishFilterState,
} from '@/utils/fishFilters'
import {
  EQUIP_GROUP_LABEL,
  ROLE_LABELS,
  TERM_BY_ID,
  WEAPON_TYPE_LABELS,
  equipGroup as groupOfCategory,
  possibleTermIds,
  roleOfBaseId,
  type EquipGroup,
} from '@/utils/itemFilters'
import { fishRarity } from '@/utils/icons'

type Entry = Record<string, any>

const toast = useToastStore()

const category = ref<'equipment' | 'monster' | 'material' | 'fish' | 'term'>('equipment')
const entries = ref<Entry[]>([])
const progress = ref<CodexProgress | null>(null)
const loading = ref(false)
const keyword = ref('')
const onlyUnlocked = ref(false)

/** 装备图鉴专属筛选：分组 / 种类 / 部位 / 武器种类 / 战斗职能 / 等级范围 / 副词条 / 词条。 */
const equipGroup = ref<'all' | EquipGroup>('all')
const equipCategory = ref('all')
const equipSlot = ref('all')
const equipWeaponType = ref('all')
const equipRole = ref<'all' | JobRole>('all')
const equipLevelMin = ref<number | ''>('')
const equipLevelMax = ref<number | ''>('')
const equipSubAttrs = ref<Set<string>>(new Set())
const equipTerms = ref<Set<string>>(new Set())
const showEquipAdvanced = ref(false)

/** 词条图鉴专属筛选：来源 / 类别 / 类型 / 已解锁品质。 */
const termSource = ref<'all' | 'combat' | 'production'>('all')
const termCategory = ref<string>('all')
const termType = ref<'all' | 'buff' | 'debuff'>('all')
const termQualities = ref<Set<TermQuality>>(new Set())

/** 鱼获图鉴专属筛选：钓场 / 种类 / 品质 / 天气 / 时段 / 直觉前置 / 尺寸区间。 */
const fishFilters = ref<FishFilterState>(createFishFilters())

const EQUIP_CATEGORY_ORDER = ['weapon', 'armor', 'accessory'] as const
const DEDICATED_CATEGORY_ORDER = ['doh_tool', 'doh_gear', 'dol_tool', 'dol_gear'] as const
const ROLE_ORDER: JobRole[] = ['tank', 'healer', 'melee', 'physicalRanged', 'magicalRanged']

/** 装备图鉴条目按「分组」预筛，供各选项列表与筛选共用。 */
const groupEntries = computed(() =>
  equipGroup.value === 'all'
    ? entries.value
    : entries.value.filter((e) => groupOfCategory(e.category) === equipGroup.value),
)

const equipGroupOptions = computed(() => {
  const present = new Set(entries.value.map((e) => groupOfCategory(e.category)))
  return [
    { id: 'all', label: '全部' },
    ...(['combat', 'doh', 'dol'] as EquipGroup[])
      .filter((g) => present.has(g))
      .map((g) => ({ id: g as string, label: EQUIP_GROUP_LABEL[g] })),
  ]
})

const equipCategoryOptions = computed(() => {
  const present = new Set(groupEntries.value.map((e) => String(e.category)))
  const order = [...EQUIP_CATEGORY_ORDER, ...DEDICATED_CATEGORY_ORDER]
  return [
    { id: 'all', label: '全部种类' },
    ...order.filter((c) => present.has(c)).map((c) => ({ id: c as string, label: categoryName(c) })),
  ]
})

const equipSlotOptions = computed(() => {
  const present = new Set(
    groupEntries.value
      .filter((e) => equipCategory.value === 'all' || e.category === equipCategory.value)
      .map((e) => String(e.equipSlots?.[0] ?? e.slot)),
  )
  const slotDefs = [...data.slots, ...data.dohdolEquipment.slots]
  return [
    { id: 'all', label: '全部部位' },
    ...slotDefs.filter((s) => present.has(s.id)).map((s) => ({ id: s.id as string, label: s.name })),
  ]
})

const equipWeaponTypeOptions = computed(() => {
  const present = new Set(
    groupEntries.value.map((e) => e.weaponType).filter((w: unknown): w is string => typeof w === 'string'),
  )
  return [
    { id: 'all', label: '全部武器' },
    ...data.weaponFamilies
      .filter((w) => present.has(w.weaponType))
      .map((w) => ({ id: w.weaponType, label: WEAPON_TYPE_LABELS[w.weaponType] ?? w.suffix })),
  ]
})

const equipRoleOptions = computed(() => [
  { id: 'all', label: '全部职能' },
  ...ROLE_ORDER.map((r) => ({ id: r as string, label: ROLE_LABELS[r] ?? r })),
])

/** 分组范围内实际可能出现的副属性（subAttrPool 并集）。 */
const equipSubAttrOptions = computed(() => {
  const ids = new Set<string>()
  for (const e of groupEntries.value) for (const a of e.subAttrPool ?? []) ids.add(a)
  return [...ids].sort().map((id) => ({ id, label: attrName(id) }))
})

/** 分组范围内各部位「可能出现」的词条并集。 */
const equipTermOptions = computed(() => {
  const ids = new Set<string>()
  for (const e of groupEntries.value) {
    const slot = String(e.equipSlots?.[0] ?? e.slot)
    for (const id of possibleTermIds(slot, groupOfCategory(e.category))) ids.add(id)
  }
  return [...ids].sort().map((id) => ({ id, label: TERM_BY_ID[id]?.name ?? id }))
})

const hasEquipFilters = computed(
  () =>
    equipGroup.value !== 'all' ||
    equipCategory.value !== 'all' ||
    equipSlot.value !== 'all' ||
    equipWeaponType.value !== 'all' ||
    equipRole.value !== 'all' ||
    equipLevelMin.value !== '' ||
    equipLevelMax.value !== '' ||
    equipSubAttrs.value.size > 0 ||
    equipTerms.value.size > 0,
)

function resetEquipFilters() {
  equipGroup.value = 'all'
  equipCategory.value = 'all'
  equipSlot.value = 'all'
  equipWeaponType.value = 'all'
  equipRole.value = 'all'
  equipLevelMin.value = ''
  equipLevelMax.value = ''
  equipSubAttrs.value = new Set()
  equipTerms.value = new Set()
}

const hasTermFilters = computed(
  () =>
    termSource.value !== 'all' ||
    termCategory.value !== 'all' ||
    termType.value !== 'all' ||
    termQualities.value.size > 0,
)

function resetTermFilters() {
  termSource.value = 'all'
  termCategory.value = 'all'
  termType.value = 'all'
  termQualities.value = new Set()
}

function toggleSet(set: Set<string>, id: string): Set<string> {
  const next = new Set(set)
  if (next.has(id)) next.delete(id)
  else next.add(id)
  return next
}

function toggleSubAttr(id: string) {
  equipSubAttrs.value = toggleSet(equipSubAttrs.value, id)
}

function toggleEquipTerm(id: string) {
  equipTerms.value = toggleSet(equipTerms.value, id)
}

function toggleTermQuality(q: TermQuality) {
  termQualities.value = toggleSet(termQualities.value, q) as Set<TermQuality>
}

/** 鱼获筛选：整体替换状态（含 Set），保证响应式与「重置」判定都简单可靠。 */
function patchFishFilters(patch: Partial<FishFilterState>) {
  fishFilters.value = { ...fishFilters.value, ...patch }
}

function toggleFishWeather(id: string) {
  patchFishFilters({ weather: toggleSet(fishFilters.value.weather, id) })
}

function toggleFishTimeOfDay(id: string) {
  patchFishFilters({ timeOfDay: toggleSet(fishFilters.value.timeOfDay, id) })
}

const fishFiltersActive = computed(() => hasFishFilters(fishFilters.value))

function resetFishFilters() {
  fishFilters.value = createFishFilters()
}

const TABS = [
  { id: 'equipment', label: '装备图鉴' },
  { id: 'monster', label: '怪物图鉴' },
  { id: 'material', label: '材料图鉴' },
  { id: 'fish', label: '鱼获图鉴' },
  { id: 'term', label: '词条图鉴' },
] as const

const FISH_KIND_LABEL: Record<string, string> = { normal: '普通鱼', king: '鱼王', emperor: '鱼皇', legend: '困难鱼' }
const FISH_KIND_CLASS: Record<string, string> = {
  normal: 'bg-ink-700/60 text-ink-200',
  king: 'bg-amber-500/20 text-amber-200',
  emperor: 'bg-fuchsia-500/20 text-fuchsia-200',
  legend: 'bg-rose-500/20 text-rose-200',
}
const FISH_RARITY_LABEL: Record<string, string> = { white: '白鱼', blue: '蓝鱼', purple: '紫鱼' }
const FISH_RARITY_CLASS: Record<string, string> = {
  white: 'bg-ink-700/60 text-ink-300',
  blue: 'bg-sky-500/20 text-sky-200',
  purple: 'bg-violet-500/20 text-violet-200',
}
const WEATHER_NAME: Record<string, string> = Object.fromEntries(
  data.weather.types.map((t) => [t.id, t.name]),
)
const TOD_NAME: Record<string, string> = data.weather.timeOfDayNames

/** 鱼获条目里实际出现过的取值：筛选选项只列出有内容的项，避免一堆必然空结果的选择。 */
const fishPresent = computed(() => presentFishValues(entries.value))

/** 钓场共 40 个，用可搜索选择而非原生下拉（可直接输入名称过滤）。 */
const fishRegionOptions = computed<SearchOption[]>(() => [
  { value: 'all', label: '全部钓场' },
  ...data.regions.regions
    .filter((r) => fishPresent.value.regions.has(r.id))
    .map((r) => ({ value: String(r.id), label: r.name })),
])

/** SearchSelect 以字符串为值，这里与 `regionId: number | 'all'` 互转。 */
const fishRegionValue = computed({
  get: () => String(fishFilters.value.regionId),
  set: (value: string) => {
    patchFishFilters({ regionId: !value || value === 'all' ? 'all' : Number(value) })
  },
})

const fishKindOptions = computed(() => [
  { id: 'all' as const, label: '全部种类' },
  ...Object.entries(FISH_KIND_LABEL)
    .filter(([id]) => fishPresent.value.kinds.has(id))
    .map(([id, label]) => ({ id: id as FishFilterState['kind'], label })),
])

const fishRarityOptions = computed(() => [
  { id: 'all' as const, label: '全部品质' },
  ...Object.entries(FISH_RARITY_LABEL)
    .filter(([id]) => fishPresent.value.rarities.has(id))
    .map(([id, label]) => ({ id: id as FishFilterState['rarity'], label })),
])

/** 天气 / 时段保持配置顺序（与钓鱼页展示一致），只列出实际出现过的。 */
const fishWeatherOptions = computed(() =>
  data.weather.types
    .filter((t) => fishPresent.value.weather.has(t.id))
    .map((t) => ({ id: t.id, label: t.name })),
)

const fishTimeOfDayOptions = computed(() =>
  (['dawn', 'day', 'dusk', 'night'] as const)
    .filter((id) => fishPresent.value.timeOfDay.has(id))
    .map((id) => ({ id, label: TOD_NAME[id] ?? id })),
)

/** 天气 / 时间门槛文案。 */
function gateText(entry: Entry): string {
  const parts: string[] = []
  if (Array.isArray(entry.weather) && entry.weather.length) {
    parts.push(entry.weather.map((w: string) => WEATHER_NAME[w] ?? w).join(' / '))
  }
  if (Array.isArray(entry.timeOfDay) && entry.timeOfDay.length) {
    parts.push(entry.timeOfDay.map((t: string) => TOD_NAME[t] ?? t).join(' / '))
  }
  return parts.join(' · ')
}

/** 计数型前置文案（如「蓝彩鱼 ×3、橙彩鱼 ×3、绿彩鱼 ×5」）。 */
function requiresText(entry: Entry): string {
  const req = entry.requires
  if (!Array.isArray(req)) return ''
  return req
    .map((r: { fishId: string; count: number }) => `${data.fishById[r.fishId]?.name ?? r.fishId} ×${r.count}`)
    .join('、')
}
const MATERIAL_KIND_LABEL: Record<string, string> = { gather: '采集材料', half: '半成品' }

function regionName(regionId: number | null | undefined): string {
  if (!regionId) return ''
  return data.regions.regions.find((r) => r.id === regionId)?.name ?? `地区 ${regionId}`
}

function dohJobName(jobId: string | null | undefined): string {
  if (!jobId) return ''
  return data.dohdolJobById[jobId]?.name ?? jobId
}

async function load() {
  loading.value = true
  try {
    const res = await api.codex(category.value)
    entries.value = res.entries
    progress.value = res.progress
  } catch {
    toast.push('图鉴加载失败', 'error')
  } finally {
    loading.value = false
  }
}

onMounted(load)
watch(category, () => {
  resetEquipFilters()
  resetTermFilters()
  resetFishFilters()
  showEquipAdvanced.value = false
  void load()
})

// 切换分组时，清掉不再适用的子筛选（种类/部位/武器种类/职能）。
watch(equipGroup, () => {
  equipCategory.value = 'all'
  equipSlot.value = 'all'
  equipWeaponType.value = 'all'
  equipRole.value = 'all'
})

watch(equipCategory, () => {
  equipSlot.value = 'all'
})

const filtered = computed(() => {
  let list = entries.value
  if (onlyUnlocked.value) list = list.filter((e) => e.unlocked)
  const kw = keyword.value.trim()
  if (kw) list = list.filter((e) => String(e.name ?? '').includes(kw))
  if (category.value === 'equipment') {
    const min = typeof equipLevelMin.value === 'number' ? equipLevelMin.value : null
    const max = typeof equipLevelMax.value === 'number' ? equipLevelMax.value : null
    list = list
      .filter((e) => equipGroup.value === 'all' || groupOfCategory(e.category) === equipGroup.value)
      .filter((e) => equipCategory.value === 'all' || e.category === equipCategory.value)
      .filter((e) => equipSlot.value === 'all' || (e.equipSlots?.[0] ?? e.slot) === equipSlot.value)
      .filter((e) => equipWeaponType.value === 'all' || e.weaponType === equipWeaponType.value)
      .filter((e) => equipRole.value === 'all' || roleOfBaseId(e.baseId) === equipRole.value)
      .filter(
        (e) =>
          !equipSubAttrs.value.size ||
          (e.subAttrPool ?? []).some((a: string) => equipSubAttrs.value.has(a)),
      )
      .filter(
        (e) =>
          !equipTerms.value.size ||
          possibleTermIds(String(e.equipSlots?.[0] ?? e.slot), groupOfCategory(e.category)).some((id) =>
            equipTerms.value.has(id),
          ),
      )
      .filter((e) => (min === null || e.levelReq >= min) && (max === null || e.levelReq <= max))
  }
  if (category.value === 'term') {
    if (termSource.value !== 'all') list = list.filter((e) => e.source === termSource.value)
    if (termCategory.value !== 'all') list = list.filter((e) => e.category === termCategory.value)
    if (termType.value !== 'all') list = list.filter((e) => e.type === termType.value)
    if (termQualities.value.size) {
      const picked = [...termQualities.value]
      list = list.filter((e) => picked.some((q) => e.qualities?.[q]?.unlocked))
    }
  }
  if (category.value === 'fish') list = applyFishFilters(list, fishFilters.value)
  return list
})

/**
 * 图鉴条目可达上千（装备展开后），一次性挂载会让切分类 / 改筛选出现长时间单帧任务。
 * 首批只渲染 60 条，其余由「显示更多」按批追加；筛选变化会自动回到首批。
 */
const { visible, remaining, showMore } = useVisibleLimit(filtered, 60)

const progressRow = computed(() => {
  if (!progress.value) return null
  return progress.value[category.value]
})

/** 已解锁品阶中最高的一个，用作图标描边色；未解锁回落到普通（剪影态）。 */
function entryRarity(entry: Entry): RarityId {
  const list = (entry.unlockedRarities ?? []) as RarityId[]
  if (!list.length) return 'common'
  return list.reduce((best, r) => (RARITY_ORDER.indexOf(r) > RARITY_ORDER.indexOf(best) ? r : best), list[0])
}
</script>

<template>
  <div class="space-y-4">
    <section class="card p-4">
      <div class="flex flex-wrap items-center gap-3">
        <h2 class="text-lg font-semibold text-white">图鉴</h2>
        <span v-if="progressRow" class="text-xs text-ink-400">
          解锁进度 {{ progressRow.unlocked }} / {{ progressRow.total }}
        </span>
        <div class="ml-auto flex gap-2 text-xs">
          <input
            v-model="keyword"
            placeholder="按名称搜索"
            class="rounded border border-ink-600 bg-ink-900 px-2 py-1.5 outline-none focus:border-amber-400"
          />
          <label class="flex items-center gap-1 text-ink-400">
            <input v-model="onlyUnlocked" type="checkbox" /> 仅看已解锁
          </label>
        </div>
      </div>

      <div v-if="progressRow" class="mt-3">
        <div class="h-2 overflow-hidden rounded-full bg-ink-800">
          <div
            class="h-full rounded-full bg-amber-400 transition-all"
            :style="{ width: `${progressRow.total ? (progressRow.unlocked / progressRow.total) * 100 : 0}%` }"
          />
        </div>
      </div>

      <div class="mt-3 flex gap-1 overflow-x-auto rounded-lg bg-ink-800 p-1 text-xs">
        <button
          v-for="tab in TABS"
          :key="tab.id"
          class="shrink-0 rounded-md px-3 py-1.5 transition"
          :class="category === tab.id ? 'bg-amber-500 text-ink-950' : 'text-ink-400 hover:text-ink-200'"
          @click="category = tab.id"
        >
          {{ tab.label }}
        </button>
      </div>

      <div v-if="category === 'equipment'" class="mt-3 space-y-2 text-xs">
        <div class="flex flex-wrap items-center gap-2">
          <select v-model="equipGroup" class="rounded border border-ink-600 bg-ink-900 px-2 py-1.5 outline-none focus:border-amber-400">
            <option v-for="opt in equipGroupOptions" :key="opt.id" :value="opt.id">{{ opt.label }}</option>
          </select>
          <select v-model="equipCategory" class="rounded border border-ink-600 bg-ink-900 px-2 py-1.5 outline-none focus:border-amber-400">
            <option v-for="opt in equipCategoryOptions" :key="opt.id" :value="opt.id">{{ opt.label }}</option>
          </select>
          <select v-model="equipSlot" class="rounded border border-ink-600 bg-ink-900 px-2 py-1.5 outline-none focus:border-amber-400">
            <option v-for="opt in equipSlotOptions" :key="opt.id" :value="opt.id">{{ opt.label }}</option>
          </select>
          <select
            v-if="equipWeaponTypeOptions.length > 1"
            v-model="equipWeaponType"
            class="rounded border border-ink-600 bg-ink-900 px-2 py-1.5 outline-none focus:border-amber-400"
          >
            <option v-for="opt in equipWeaponTypeOptions" :key="opt.id" :value="opt.id">{{ opt.label }}</option>
          </select>
          <select
            v-if="equipGroup !== 'doh' && equipGroup !== 'dol'"
            v-model="equipRole"
            class="rounded border border-ink-600 bg-ink-900 px-2 py-1.5 outline-none focus:border-amber-400"
          >
            <option v-for="opt in equipRoleOptions" :key="opt.id" :value="opt.id">{{ opt.label }}</option>
          </select>
          <label class="flex items-center gap-1 text-ink-400">
            等级
            <input
              v-model.number="equipLevelMin"
              type="number"
              min="1"
              step="1"
              placeholder="最低"
              class="w-16 rounded border border-ink-600 bg-ink-900 px-2 py-1.5 outline-none focus:border-amber-400"
            />
            <span class="text-ink-600">-</span>
            <input
              v-model.number="equipLevelMax"
              type="number"
              min="1"
              step="1"
              placeholder="最高"
              class="w-16 rounded border border-ink-600 bg-ink-900 px-2 py-1.5 outline-none focus:border-amber-400"
            />
          </label>
          <button
            v-if="equipSubAttrOptions.length || equipTermOptions.length"
            class="rounded bg-ink-800 px-2.5 py-1.5 text-ink-300 transition hover:bg-ink-700"
            @click="showEquipAdvanced = !showEquipAdvanced"
          >
            {{ showEquipAdvanced ? '收起词条筛选' : '词条 / 副词条' }}
          </button>
          <button
            v-if="hasEquipFilters"
            class="rounded bg-ink-800 px-2.5 py-1.5 text-ink-300 transition hover:bg-ink-700"
            @click="resetEquipFilters"
          >
            重置
          </button>
          <span class="ml-auto text-ink-500">共 {{ filtered.length }} 件</span>
        </div>

        <div v-if="showEquipAdvanced" class="space-y-2 border-t border-ink-700 pt-2">
          <div v-if="equipSubAttrOptions.length" class="flex flex-wrap items-center gap-1.5">
            <span class="shrink-0 text-ink-400">副词条（可能出现）：</span>
            <button
              v-for="opt in equipSubAttrOptions"
              :key="opt.id"
              class="rounded-full border px-2.5 py-1 transition"
              :class="equipSubAttrs.has(opt.id) ? 'border-amber-400 bg-amber-500/20 text-amber-200' : 'border-ink-600 text-ink-300 hover:border-ink-400'"
              @click="toggleSubAttr(opt.id)"
            >
              {{ opt.label }}
            </button>
          </div>
          <div v-if="equipTermOptions.length" class="flex flex-wrap items-center gap-1.5">
            <span class="shrink-0 text-ink-400">词条（可能出现）：</span>
            <button
              v-for="opt in equipTermOptions"
              :key="opt.id"
              class="rounded-full border px-2.5 py-1 transition"
              :class="equipTerms.has(opt.id) ? 'border-amber-400 bg-amber-500/20 text-amber-200' : 'border-ink-600 text-ink-300 hover:border-ink-400'"
              @click="toggleEquipTerm(opt.id)"
            >
              {{ opt.label }}
            </button>
          </div>
        </div>
      </div>

      <div v-if="category === 'term'" class="mt-3 flex flex-wrap items-center gap-2 text-xs">
        <select v-model="termSource" class="rounded border border-ink-600 bg-ink-900 px-2 py-1.5 outline-none focus:border-amber-400">
          <option value="all">全部来源</option>
          <option value="combat">战斗装备</option>
          <option value="production">生产采集装备</option>
        </select>
        <select v-model="termCategory" class="rounded border border-ink-600 bg-ink-900 px-2 py-1.5 outline-none focus:border-amber-400">
          <option value="all">全部类别</option>
          <option v-for="c in TERM_CATEGORY_OPTIONS" :key="c.id" :value="c.id">{{ c.name }}</option>
        </select>
        <select v-model="termType" class="rounded border border-ink-600 bg-ink-900 px-2 py-1.5 outline-none focus:border-amber-400">
          <option value="all">全部类型</option>
          <option value="buff">Buff</option>
          <option value="debuff">Debuff</option>
        </select>
        <span class="shrink-0 text-ink-400">已解锁品质：</span>
        <button
          v-for="q in (['common', 'rare', 'ancient'] as const)"
          :key="q"
          class="rounded-full border px-2.5 py-1 transition"
          :class="termQualities.has(q) ? 'border-amber-400 bg-amber-500/20 text-amber-200' : 'border-ink-600 text-ink-300 hover:border-ink-400'"
          @click="toggleTermQuality(q)"
        >
          {{ termQualityName(q) }}
        </button>
        <button
          v-if="hasTermFilters"
          class="rounded bg-ink-800 px-2.5 py-1.5 text-ink-300 transition hover:bg-ink-700"
          @click="resetTermFilters"
        >
          重置
        </button>
        <span class="ml-auto text-ink-500">共 {{ filtered.length }} 条</span>
      </div>

      <div v-if="category === 'fish'" class="mt-3 space-y-2 text-xs">
        <div class="flex flex-wrap items-center gap-2">
          <SearchSelect
            v-model="fishRegionValue"
            :options="fishRegionOptions"
            placeholder="搜索钓场…"
            empty-text="无匹配钓场"
          />
          <select
            v-model="fishFilters.kind"
            class="rounded border border-ink-600 bg-ink-900 px-2 py-1.5 outline-none focus:border-amber-400"
          >
            <option v-for="opt in fishKindOptions" :key="opt.id" :value="opt.id">{{ opt.label }}</option>
          </select>
          <select
            v-model="fishFilters.rarity"
            class="rounded border border-ink-600 bg-ink-900 px-2 py-1.5 outline-none focus:border-amber-400"
          >
            <option v-for="opt in fishRarityOptions" :key="opt.id" :value="opt.id">{{ opt.label }}</option>
          </select>
          <select
            v-model="fishFilters.requires"
            class="rounded border border-ink-600 bg-ink-900 px-2 py-1.5 outline-none focus:border-amber-400"
          >
            <option value="all">前置不限</option>
            <option value="has">需直觉前置</option>
            <option value="none">无需前置</option>
          </select>
          <label class="flex items-center gap-1 text-ink-400">
            尺寸
            <input
              v-model.number="fishFilters.sizeMin"
              type="number"
              min="0"
              step="1"
              placeholder="最小"
              class="w-16 rounded border border-ink-600 bg-ink-900 px-2 py-1.5 outline-none focus:border-amber-400"
            />
            <span class="text-ink-600">-</span>
            <input
              v-model.number="fishFilters.sizeMax"
              type="number"
              min="0"
              step="1"
              placeholder="最大"
              class="w-16 rounded border border-ink-600 bg-ink-900 px-2 py-1.5 outline-none focus:border-amber-400"
            />
            <span class="text-ink-600">cm</span>
          </label>
          <button
            v-if="fishFiltersActive"
            class="rounded bg-ink-800 px-2.5 py-1.5 text-ink-300 transition hover:bg-ink-700"
            @click="resetFishFilters"
          >
            重置
          </button>
          <span class="ml-auto text-ink-500">共 {{ filtered.length }} 条</span>
        </div>

        <div v-if="fishWeatherOptions.length" class="flex flex-wrap items-center gap-1.5">
          <span class="shrink-0 text-ink-400">天气：</span>
          <button
            v-for="opt in fishWeatherOptions"
            :key="opt.id"
            class="rounded-full border px-2.5 py-1 transition"
            :class="fishFilters.weather.has(opt.id) ? 'border-amber-400 bg-amber-500/20 text-amber-200' : 'border-ink-600 text-ink-300 hover:border-ink-400'"
            @click="toggleFishWeather(opt.id)"
          >
            {{ opt.label }}
          </button>
        </div>

        <div v-if="fishTimeOfDayOptions.length" class="flex flex-wrap items-center gap-1.5">
          <span class="shrink-0 text-ink-400">时段：</span>
          <button
            v-for="opt in fishTimeOfDayOptions"
            :key="opt.id"
            class="rounded-full border px-2.5 py-1 transition"
            :class="fishFilters.timeOfDay.has(opt.id) ? 'border-amber-400 bg-amber-500/20 text-amber-200' : 'border-ink-600 text-ink-300 hover:border-ink-400'"
            @click="toggleFishTimeOfDay(opt.id)"
          >
            {{ opt.label }}
          </button>
        </div>

        <p class="text-[10px] text-ink-600">
          天气 / 时段为严格匹配：只显示把该条件列为要求的鱼（无门槛的鱼不在其中）；品质仅适用于普通鱼；尺寸按「可钓范围与输入区间有交集」判定。
        </p>
      </div>
    </section>

    <p v-if="loading" class="py-10 text-center text-xs text-ink-600">加载中…</p>

    <!-- 装备图鉴 -->
    <section v-else-if="category === 'equipment'" class="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
      <article
        v-for="entry in visible"
        :key="entry.baseId"
        class="card gallery-cell p-3"
        :class="entry.unlocked ? '' : 'opacity-55'"
      >
        <div class="flex items-start justify-between gap-2">
          <div class="flex min-w-0 items-center gap-2">
            <ItemIcon
              :base-id="entry.baseId"
              :rarity="entryRarity(entry)"
              :size="32"
              :variant="entry.jobGroup === 'combat' ? 'lite' : 'plain'"
              :silhouette="!entry.unlocked"
            />
            <div class="min-w-0">
              <p class="truncate text-sm font-medium" :class="entry.unlocked ? 'text-ink-100' : 'text-ink-500'">
                {{ entry.unlocked ? entry.name : '未解锁' }}
              </p>
              <p class="flex flex-wrap items-center gap-1 text-[10px] text-ink-400">
                <span class="rounded bg-ink-700/60 px-1 py-0.5 text-ink-300">
                  {{ EQUIP_GROUP_LABEL[groupOfCategory(entry.category)] }}
                </span>
                {{ categoryName(entry.category) }} · {{ slotName(entry.equipSlots?.[0] ?? entry.slot) }} · Lv.{{ entry.levelReq }}
              </p>
            </div>
          </div>
          <span v-if="entry.jobId" class="shrink-0 text-[10px] text-sky-300">{{ jobName(entry.jobId) }}</span>
        </div>

        <div class="mt-2 flex gap-1">
          <span
            v-for="r in RARITY_ORDER"
            :key="r"
            class="h-2 w-2 rounded-full"
            :style="{ backgroundColor: data.rarities.byId[r].hex, opacity: entry.unlockedRarities?.includes(r) ? 1 : 0.18 }"
            :title="rarityName(r)"
          />
        </div>

        <ul class="mt-2 space-y-0.5 text-[10px] text-ink-400">
          <li v-for="attr in entry.baseAttrs" :key="attr.attr">
            <template v-if="entry.jobGroup === 'combat'">
              {{ baseAttrName(attr.attr) }} {{ Math.floor(attr.base * 0.8) }} ~ {{ Math.ceil(attr.base * 1.2) }}
              <span class="text-ink-600">（基准 {{ Math.round(attr.base) }}，±20%）</span>
            </template>
            <template v-else>{{ baseAttrName(attr.attr) }} +{{ attr.base }}</template>
          </li>
        </ul>

        <p v-if="entry.subAttrPool?.length" class="mt-2 text-[10px] text-ink-500">
          副属性池：{{ entry.subAttrPool.map((a: string) => attrName(a)).join('、') }}
        </p>

        <p v-if="!entry.unlocked" class="mt-2 text-[10px] text-amber-300">
          来源：{{ entry.sources?.join('、') }}
        </p>
        <p v-else class="mt-2 text-[10px] text-ink-600">
          累计获得 {{ entry.totalCount }} 件 · 首次解锁 {{ entry.firstUnlockAt?.slice(0, 10) }}
        </p>
      </article>
    </section>

    <!-- 怪物图鉴 -->
    <section v-else-if="category === 'monster'" class="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
      <article
        v-for="entry in visible"
        :key="entry.monsterId"
        class="card gallery-cell p-3"
        :class="entry.unlocked ? '' : 'opacity-55'"
      >
        <div class="flex items-start justify-between gap-2">
          <div class="min-w-0">
            <p class="truncate text-sm font-medium" :class="entry.unlocked ? 'text-ink-100' : 'text-ink-500'">
              {{ entry.unlocked ? entry.name : '未击败' }}
            </p>
            <p class="text-[10px] text-ink-400">
              {{ { normal: '普通怪', elite: '精英怪', boss: '关底 BOSS' }[entry.kind as string] }}
              <span v-if="entry.levelMin"> · Lv.{{ entry.levelMin }}-{{ entry.levelMax }}</span>
            </p>
          </div>
          <span v-if="entry.bossType" class="shrink-0 text-[10px] text-fuchsia-300">
            {{ data.bosses.types.find((t) => t.id === entry.bossType)?.name }}
          </span>
        </div>

        <p v-if="entry.examples?.length" class="mt-2 text-[10px] text-ink-500">
          示例：{{ entry.examples.join('、') }}
        </p>

        <div v-if="entry.bossType" class="mt-2 space-y-1">
          <p
            v-for="skill in data.bosses.types.find((t) => t.id === entry.bossType)?.skills ?? []"
            :key="skill.id"
            class="text-[10px] text-ink-400"
          >
            <b class="text-fuchsia-300">{{ skill.name }}</b>：{{ skill.desc }}
          </p>
        </div>

        <p v-if="!entry.unlocked" class="mt-2 text-[10px] text-amber-300">
          出现地区：{{ entry.regionId ? `第 ${entry.regionId} 关` : '各地区' }}
        </p>
        <p v-else class="mt-2 text-[10px] text-ink-600">
          累计击杀 {{ entry.killCount }} 次 · 首次击败 {{ entry.firstDefeatAt?.slice(0, 10) }}
        </p>
      </article>
    </section>

    <!-- 材料图鉴 -->
    <section v-else-if="category === 'material'" class="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
      <article
        v-for="entry in visible"
        :key="entry.itemId"
        class="card gallery-cell p-3"
        :class="entry.unlocked ? '' : 'opacity-55'"
      >
        <div class="flex items-start justify-between gap-2">
          <div class="flex min-w-0 items-start gap-2">
            <ItemIcon :base-id="entry.itemId" variant="plain" :size="32" :silhouette="!entry.unlocked" />
            <div class="min-w-0">
              <p class="truncate text-sm font-medium" :class="entry.unlocked ? 'text-ink-100' : 'text-ink-500'">
                {{ entry.unlocked ? entry.name : '未获得' }}
              </p>
              <p class="text-[10px] text-ink-400">
                {{ MATERIAL_KIND_LABEL[entry.kind] ?? '材料' }}
                <span v-if="entry.jobId"> · {{ dohJobName(entry.jobId) }}</span>
                <span v-if="entry.regionId"> · {{ regionName(entry.regionId) }}</span>
              </p>
            </div>
          </div>
          <span v-if="entry.common" class="shrink-0 rounded bg-ink-700/60 px-1.5 py-0.5 text-[10px] text-ink-300">
            通用
          </span>
        </div>

        <p class="mt-2 text-[10px] text-ink-500">
          品阶 {{ entry.tier ?? '-' }} · 出售单价 {{ entry.sell ?? 0 }} 金币
        </p>

        <p v-if="!entry.unlocked" class="mt-2 text-[10px] text-amber-300">
          来源：{{ entry.kind === 'half' ? '生产合成' : entry.common ? '各采集点通用产出' : `${regionName(entry.regionId)} 采集点` }}
        </p>
        <p v-else class="mt-2 text-[10px] text-ink-600">
          累计获得 {{ entry.totalCount }} 个 · 首次获得 {{ entry.firstUnlockAt?.slice(0, 10) }}
        </p>
      </article>
    </section>

    <!-- 鱼获图鉴 -->
    <section v-else-if="category === 'fish'" class="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
      <article
        v-for="entry in visible"
        :key="entry.fishId"
        class="card gallery-cell p-3"
        :class="entry.unlocked ? '' : 'opacity-55'"
      >
        <div class="flex items-start justify-between gap-2">
          <div class="flex min-w-0 items-start gap-2">
            <ItemIcon :base-id="entry.fishId" :rarity="fishRarity(entry.fishId)" :size="32" :silhouette="!entry.unlocked" />
            <div class="min-w-0">
              <p class="truncate text-sm font-medium" :class="entry.unlocked ? 'text-ink-100' : 'text-ink-500'">
                {{ entry.unlocked ? entry.name : '未钓起' }}
              </p>
              <p class="text-[10px] text-ink-400">{{ entry.regionName }} 钓场</p>
            </div>
          </div>
          <span class="shrink-0 rounded px-1.5 py-0.5 text-[10px]" :class="FISH_KIND_CLASS[entry.kind]">
            {{ FISH_KIND_LABEL[entry.kind] ?? '普通鱼' }}
          </span>
        </div>

        <div class="mt-1 flex flex-wrap gap-1">
          <span
            v-if="entry.kind === 'normal'"
            class="rounded px-1.5 py-0.5 text-[10px]"
            :class="FISH_RARITY_CLASS[entry.rarity] ?? FISH_RARITY_CLASS.white"
          >
            {{ FISH_RARITY_LABEL[entry.rarity] ?? '白鱼' }}
          </span>
          <span v-if="gateText(entry)" class="rounded bg-ink-700/60 px-1.5 py-0.5 text-[10px] text-sky-200">
            {{ gateText(entry) }}
          </span>
        </div>

        <p class="mt-2 text-[10px] text-ink-500">
          尺寸 {{ entry.sizeMin }} ~ {{ entry.sizeMax }} cm · 出售 {{ entry.sell }} 金币 · 经验 {{ entry.exp }}
        </p>
        <p v-if="entry.chance" class="text-[10px] text-ink-500">
          出现概率 {{ (entry.chance * 100).toFixed(2) }}%（仅在「{{ entry.buffName || '捕鱼人之识' }}」期间判定）
        </p>
        <p v-if="requiresText(entry)" class="text-[10px] text-ink-500">
          直觉前置：{{ requiresText(entry) }}
        </p>

        <p v-if="!entry.unlocked" class="mt-2 text-[10px] text-amber-300">
          钓场：{{ entry.regionName }}
          <span v-if="entry.kind !== 'normal'">（需先钓齐前置开启「{{ entry.buffName || '捕鱼人之识' }}」）</span>
        </p>
        <p v-else class="mt-2 text-[10px] text-ink-600">
          累计钓起 {{ entry.count }} 条 · 最大 {{ entry.maxSize }} cm · 首次 {{ entry.firstCaughtAt?.slice(0, 10) }}
        </p>
      </article>
    </section>

    <!-- 词条图鉴 -->
    <section v-else class="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
      <article v-for="entry in visible" :key="entry.termId" class="card gallery-cell p-3">
        <div class="flex items-start justify-between gap-2">
          <div class="flex min-w-0 items-center gap-1.5">
            <p class="truncate text-sm font-medium text-ink-100">{{ entry.name }}</p>
            <span
              v-if="entry.source === 'production'"
              class="shrink-0 rounded bg-amber-500/20 px-1 py-0.5 text-[10px] text-amber-200"
            >
              生产
            </span>
            <span
              v-if="termCategoryName(entry.category)"
              class="shrink-0 rounded bg-ink-700/60 px-1 py-0.5 text-[10px] text-ink-300"
            >
              {{ termCategoryName(entry.category) }}
            </span>
          </div>
          <span
            class="shrink-0 rounded px-1.5 py-0.5 text-[10px]"
            :class="entry.type === 'buff' ? 'bg-emerald-500/20 text-emerald-300' : 'bg-rose-500/20 text-rose-300'"
          >
            {{ entry.type === 'buff' ? 'Buff' : 'Debuff' }}
          </span>
        </div>
        <p class="mt-1 text-[11px] text-ink-400">{{ entry.desc.replace('{v}', 'X').replace('{c}', 'X') }}</p>
        <p class="mt-1 text-[10px] text-ink-500">
          数值范围：{{ entry.range?.[0] }} ~ {{ entry.range?.[1] }}
        </p>
        <p v-if="entry.slots?.length" class="text-[10px] text-ink-500">
          可出现部位：{{ entry.slots.map((s: string) => slotName(s)).join('、') }}
        </p>

        <div class="mt-2 flex gap-1">
          <span
            v-for="q in (['common', 'rare', 'ancient'] as const)"
            :key="q"
            class="rounded border px-1.5 py-0.5 text-[10px]"
            :class="[
              termQualityClass(q),
              entry.qualities?.[q]?.unlocked ? '' : 'opacity-35',
            ]"
          >
            {{ q === 'ancient' ? `${termQualityName(q)}🌟` : termQualityName(q) }}
          </span>
        </div>
      </article>
    </section>

    <p v-if="!loading && !filtered.length" class="py-10 text-center text-xs text-ink-600">
      没有符合条件的条目。
    </p>

    <!-- 图鉴条目可达上千，首批只渲染一部分，避免切分类时一次性挂载全部卡片。 -->
    <button
      v-if="!loading && remaining > 0"
      class="mx-auto block rounded-lg border border-ink-700 bg-ink-800/60 px-4 py-2 text-xs text-ink-200 transition hover:border-amber-400"
      @click="showMore"
    >
      显示更多（剩余 {{ remaining }} 条）
    </button>

    <p class="text-center text-[10px] text-ink-600">
      图鉴完成度仅提供称号、头像框与徽章展示，不提供金币或宝箱奖励。
    </p>
    <p class="text-center text-[10px] text-ink-700">
      当前总完成度：装备 {{ progress?.equipment.unlocked ?? 0 }}/{{ progress?.equipment.total ?? 0 }} ·
      怪物 {{ progress?.monster.unlocked ?? 0 }}/{{ progress?.monster.total ?? 0 }} ·
      材料 {{ progress?.material.unlocked ?? 0 }}/{{ progress?.material.total ?? 0 }} ·
      鱼获 {{ progress?.fish.unlocked ?? 0 }}/{{ progress?.fish.total ?? 0 }} ·
      词条 {{ progress?.term.unlocked ?? 0 }}/{{ progress?.term.total ?? 0 }}
    </p>
  </div>
</template>
