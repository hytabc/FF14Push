<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'

import { api } from '@/api'
import data from '@shared/schema'
import ItemIcon from '@/components/ItemIcon.vue'
import { useToastStore } from '@/stores/toast'
import type { CodexProgress, RarityId } from '@/game/types'
import { RARITY_ORDER, attrName, baseAttrName, categoryName, jobName, rarityName, slotName, termQualityClass, termQualityName } from '@/utils/format'
import { fishKindRarity } from '@/utils/icons'

type Entry = Record<string, any>

const toast = useToastStore()

const category = ref<'equipment' | 'monster' | 'material' | 'fish' | 'term'>('equipment')
const entries = ref<Entry[]>([])
const progress = ref<CodexProgress | null>(null)
const loading = ref(false)
const keyword = ref('')
const onlyUnlocked = ref(false)

/** 装备图鉴专属筛选：种类 / 部位 / 等级范围。 */
const equipCategory = ref('all')
const equipSlot = ref('all')
const equipLevelMin = ref<number | ''>('')
const equipLevelMax = ref<number | ''>('')

const EQUIP_CATEGORY_ORDER = ['weapon', 'armor', 'accessory'] as const

const equipCategoryOptions = computed(() => {
  const present = new Set(entries.value.map((e) => String(e.category)))
  return [
    { id: 'all', label: '全部种类' },
    ...EQUIP_CATEGORY_ORDER.filter((c) => present.has(c)).map((c) => ({ id: c as string, label: categoryName(c) })),
  ]
})

const equipSlotOptions = computed(() => {
  const present = new Set(entries.value.map((e) => String(e.equipSlots?.[0] ?? e.slot)))
  return [
    { id: 'all', label: '全部部位' },
    ...data.slots.filter((s) => present.has(s.id)).map((s) => ({ id: s.id as string, label: s.name })),
  ]
})

const hasEquipFilters = computed(
  () =>
    equipCategory.value !== 'all' ||
    equipSlot.value !== 'all' ||
    equipLevelMin.value !== '' ||
    equipLevelMax.value !== '',
)

function resetEquipFilters() {
  equipCategory.value = 'all'
  equipSlot.value = 'all'
  equipLevelMin.value = ''
  equipLevelMax.value = ''
}

const TABS = [
  { id: 'equipment', label: '装备图鉴' },
  { id: 'monster', label: '怪物图鉴' },
  { id: 'material', label: '材料图鉴' },
  { id: 'fish', label: '鱼获图鉴' },
  { id: 'term', label: '词条图鉴' },
] as const

const FISH_KIND_LABEL: Record<string, string> = { normal: '普通鱼', king: '鱼王', emperor: '鱼皇' }
const FISH_KIND_CLASS: Record<string, string> = {
  normal: 'bg-ink-700/60 text-ink-200',
  king: 'bg-amber-500/20 text-amber-200',
  emperor: 'bg-fuchsia-500/20 text-fuchsia-200',
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
  void load()
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
      .filter((e) => equipCategory.value === 'all' || e.category === equipCategory.value)
      .filter((e) => equipSlot.value === 'all' || (e.equipSlots?.[0] ?? e.slot) === equipSlot.value)
      .filter((e) => (min === null || e.levelReq >= min) && (max === null || e.levelReq <= max))
  }
  return list
})

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

      <div v-if="category === 'equipment'" class="mt-3 flex flex-wrap items-center gap-2 text-xs">
        <select v-model="equipCategory" class="rounded border border-ink-600 bg-ink-900 px-2 py-1.5 outline-none focus:border-amber-400">
          <option v-for="opt in equipCategoryOptions" :key="opt.id" :value="opt.id">{{ opt.label }}</option>
        </select>
        <select v-model="equipSlot" class="rounded border border-ink-600 bg-ink-900 px-2 py-1.5 outline-none focus:border-amber-400">
          <option v-for="opt in equipSlotOptions" :key="opt.id" :value="opt.id">{{ opt.label }}</option>
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
          v-if="hasEquipFilters"
          class="rounded bg-ink-800 px-2.5 py-1.5 text-ink-300 transition hover:bg-ink-700"
          @click="resetEquipFilters"
        >
          重置
        </button>
        <span class="ml-auto text-ink-500">共 {{ filtered.length }} 件</span>
      </div>
    </section>

    <p v-if="loading" class="py-10 text-center text-xs text-ink-600">加载中…</p>

    <!-- 装备图鉴 -->
    <section v-else-if="category === 'equipment'" class="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
      <article
        v-for="entry in filtered"
        :key="entry.baseId"
        class="card p-3"
        :class="entry.unlocked ? '' : 'opacity-55'"
      >
        <div class="flex items-start justify-between gap-2">
          <div class="flex min-w-0 items-center gap-2">
            <ItemIcon
              :base-id="entry.baseId"
              :rarity="entryRarity(entry)"
              :size="32"
              variant="lite"
              :silhouette="!entry.unlocked"
            />
            <div class="min-w-0">
              <p class="truncate text-sm font-medium" :class="entry.unlocked ? 'text-ink-100' : 'text-ink-500'">
                {{ entry.unlocked ? entry.name : '未解锁' }}
              </p>
              <p class="text-[10px] text-ink-400">
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
            {{ baseAttrName(attr.attr) }} {{ Math.floor(attr.base * 0.8) }} ~ {{ Math.ceil(attr.base * 1.2) }}
            <span class="text-ink-600">（基准 {{ Math.round(attr.base) }}，±20%）</span>
          </li>
        </ul>

        <p class="mt-2 text-[10px] text-ink-500">
          副属性池：{{ entry.subAttrPool?.map((a: string) => attrName(a)).join('、') }}
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
        v-for="entry in filtered"
        :key="entry.monsterId"
        class="card p-3"
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
        v-for="entry in filtered"
        :key="entry.itemId"
        class="card p-3"
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
        v-for="entry in filtered"
        :key="entry.fishId"
        class="card p-3"
        :class="entry.unlocked ? '' : 'opacity-55'"
      >
        <div class="flex items-start justify-between gap-2">
          <div class="flex min-w-0 items-start gap-2">
            <ItemIcon :base-id="entry.fishId" :rarity="fishKindRarity(entry.kind)" :size="32" :silhouette="!entry.unlocked" />
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

        <p class="mt-2 text-[10px] text-ink-500">
          尺寸 {{ entry.sizeMin }} ~ {{ entry.sizeMax }} cm · 出售 {{ entry.sell }} 金币 · 经验 {{ entry.exp }}
        </p>
        <p v-if="entry.chance" class="text-[10px] text-ink-500">
          出现概率 {{ (entry.chance * 100).toFixed(1) }}%（仅在「捕鱼人之识」期间判定）
        </p>

        <p v-if="!entry.unlocked" class="mt-2 text-[10px] text-amber-300">
          钓场：{{ entry.regionName }}
          <span v-if="entry.kind !== 'normal'">（需先钓起前置普通鱼开启捕鱼人之识）</span>
        </p>
        <p v-else class="mt-2 text-[10px] text-ink-600">
          累计钓起 {{ entry.count }} 条 · 最大 {{ entry.maxSize }} cm · 首次 {{ entry.firstCaughtAt?.slice(0, 10) }}
        </p>
      </article>
    </section>

    <!-- 词条图鉴 -->
    <section v-else class="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
      <article v-for="entry in filtered" :key="entry.termId" class="card p-3">
        <div class="flex items-start justify-between gap-2">
          <div class="flex min-w-0 items-center gap-1.5">
            <p class="truncate text-sm font-medium text-ink-100">{{ entry.name }}</p>
            <span
              v-if="entry.source === 'production'"
              class="shrink-0 rounded bg-amber-500/20 px-1 py-0.5 text-[10px] text-amber-200"
            >
              生产
            </span>
          </div>
          <span
            class="shrink-0 rounded px-1.5 py-0.5 text-[10px]"
            :class="entry.type === 'buff' ? 'bg-emerald-500/20 text-emerald-300' : 'bg-rose-500/20 text-rose-300'"
          >
            {{ entry.type === 'buff' ? 'Buff' : 'Debuff' }}
          </span>
        </div>
        <p class="mt-1 text-[11px] text-ink-400">{{ entry.desc.replace('{v}', 'X') }}</p>
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
