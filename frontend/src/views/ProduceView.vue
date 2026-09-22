<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'

import data from '@shared/schema'
import { consumableBonus } from '@/utils/consumables'

import InfoTip from '@/components/InfoTip.vue'
import ItemIcon from '@/components/ItemIcon.vue'
import { findGatherTarget } from '@/game/core/gather'
import { craftQualityExplain, craftRarityExplain } from '@/game/explanations'
import { useAuthStore } from '@/stores/auth'
import { useDohDolStore } from '@/stores/dohdol'
import { useGameStore } from '@/stores/game'
import { useToastStore } from '@/stores/toast'
import type { RarityId } from '@/game/types'
import { rarityClass, rarityName } from '@/utils/format'

const game = useGameStore()
const dohdol = useDohDolStore()
const auth = useAuthStore()
const toast = useToastStore()
const router = useRouter()

const job = ref('CRP')
const error = ref('')

/** 配方筛选：名称 / 种类 / 等级范围。 */
const keyword = ref('')
const kindFilter = ref('all')
const levelMin = ref<number | ''>('')
const levelMax = ref<number | ''>('')

const kindOptions = [
  { id: 'all', label: '全部种类' },
  { id: 'material', label: '材料' },
  { id: 'equipment', label: '装备' },
  { id: 'consumable', label: '消耗品' },
]

const dohJobs = data.dohdolJobs.jobs.filter((j) => j.kind === 'doh')
const progress = computed(() => dohdol.state?.progress?.doh ?? null)
const running = computed(() => dohdol.isRunning && dohdol.mode === 'produce')

const hasFilters = computed(
  () => !!keyword.value.trim() || kindFilter.value !== 'all' || levelMin.value !== '' || levelMax.value !== '',
)

function resetFilters() {
  keyword.value = ''
  kindFilter.value = 'all'
  levelMin.value = ''
  levelMax.value = ''
}

const recipes = computed(() => {
  const kw = keyword.value.trim()
  const min = typeof levelMin.value === 'number' ? levelMin.value : null
  const max = typeof levelMax.value === 'number' ? levelMax.value : null
  return (dohdol.state?.recipes ?? [])
    .filter((r) => r.jobId === job.value)
    .filter((r) => kindFilter.value === 'all' || r.output.kind === kindFilter.value)
    .filter((r) => (min === null || r.requiredLevel >= min) && (max === null || r.requiredLevel <= max))
    .filter((r) => !kw || r.output.name.includes(kw))
    .sort((a, b) => a.requiredLevel - b.requiredLevel)
})

const materials = computed(() => dohdol.state?.materials ?? [])
const consumables = computed(() => dohdol.state?.consumables ?? [])
const bonus = computed(() => dohdol.state?.bonus ?? {})

const craft = computed(() => dohdol.state?.craft ?? null)
const craftInfo = computed(() => craftRarityExplain(craft.value))
const craftWeightRows = computed(() =>
  data.rarities.order.map((rarity) => ({ rarity: rarity as RarityId, weight: craft.value?.odds?.[rarity] ?? 0 })),
)
const qualityBonusInfo = computed(() => craftQualityExplain((bonus.value.craftQualityPct ?? 0) / 100))
function fmtWeight(weight: number): string {
  const value = (weight ?? 0) * 100
  return `${value % 1 === 0 ? value.toFixed(0) : value.toFixed(1)}%`
}

function isRegionUnlocked(regionId: number): boolean {
  const entry = game.state?.regionProgress?.[String(regionId)]
  return entry ? entry.unlocked : regionId === 1
}

/** 可采集材料 → 采集点（用于「快速跳转采集」按钮）。 */
const gatherTargets = computed(() => {
  const map = new Map<string, { jobId: string; regionId: number }>()
  for (const material of data.materials.materials) {
    if (material.kind !== 'gather') continue
    const target = findGatherTarget(material.id, isRegionUnlocked)
    if (target) map.set(material.id, target)
  }
  return map
})

/** 跳到采集页面、选中对应采集点并自动开始采集。 */
function goGather(itemId: string) {
  const target = gatherTargets.value.get(itemId)
  if (!target) return
  void router.push({
    name: 'gather',
    query: { job: target.jobId, region: String(target.regionId), auto: '1' },
  })
}

onMounted(async () => {
  if (auth.isLoggedIn) await game.loadState()
})
onUnmounted(() => {
  void dohdol.stop(true)
})

/** 每个配方卡片上的「制作 X 个」数量，默认 1。 */
const amounts = ref<Record<string, number>>({})
watch(
  () => dohdol.state?.recipes,
  (list) => {
    if (!list) return
    const next = { ...amounts.value }
    for (const r of list) if (next[r.id] === undefined) next[r.id] = 1
    amounts.value = next
  },
  { immediate: true },
)

function amountOf(recipeId: string): number {
  const value = amounts.value[recipeId]
  return Number.isFinite(value) && value >= 1 ? Math.floor(value) : 1
}

async function startRecipe(recipeId: string, count: number | null) {
  error.value = ''
  if (running.value) {
    await dohdol.stop()
  }
  try {
    await dohdol.startProduce(job.value, recipeId, count)
    toast.push(count === null ? '开始制作全部' : `开始制作 ${count} 个`, 'success')
  } catch (e) {
    error.value = e instanceof Error ? e.message : '生产失败'
    toast.push(error.value, 'error')
  }
}

async function stop() {
  await dohdol.stop()
}
</script>

<template>
  <div class="space-y-4">
    <section class="rounded-lg border border-ink-700/60 bg-ink-900/40 p-3">
      <div class="flex flex-wrap items-center gap-3">
        <h1 class="text-sm font-bold text-amber-200">生产 · 能工巧匠</h1>
        <span v-if="progress" class="rounded bg-ink-800 px-2 py-1 text-xs text-ink-300">
          生产等级 Lv.{{ progress.level }} · {{ progress.exp }}/{{ progress.expToNext }}
        </span>
        <span class="ml-auto flex flex-wrap items-center gap-3 text-xs text-ink-400">
          <span class="flex items-center">
            制造品阶幸运 {{ (bonus.craftRarityPct ?? 0) >= 0 ? '+' : '' }}{{ (bonus.craftRarityPct ?? 0).toFixed(1) }}%
          </span>
          <span class="flex items-center">
            制造品质 +{{ (bonus.craftQualityPct ?? 0).toFixed(0) }}%
            <InfoTip :title="qualityBonusInfo.title">
              <p v-for="(line, i) in qualityBonusInfo.lines" :key="i">{{ line }}</p>
            </InfoTip>
          </span>
        </span>
      </div>
      <p class="mt-1 text-[11px] text-ink-500">
        制造装备恒为「高品质」：属性区间上移、必带太古词条；品阶概率随英雄等级 / 通关地区数 / 生产等级 / 专用装备品阶幸运提升（极限时神话 20%），专用装备还会带 Buff/Debuff 词条。
      </p>
      <p class="mt-0.5 text-[11px] text-ink-500">
        制造品阶概率：
        <span v-for="(row, idx) in craftWeightRows" :key="row.rarity">
          <span :class="rarityClass(row.rarity)">{{ rarityName(row.rarity) }}</span> {{ fmtWeight(row.weight) }}<span
            v-if="idx < craftWeightRows.length - 1"
            class="text-ink-600"
          >
            /
          </span>
        </span>
        <InfoTip :title="craftInfo.title">
          <p v-for="(line, i) in craftInfo.lines" :key="i">{{ line }}</p>
        </InfoTip>
      </p>
    </section>

    <section class="rounded-lg border border-ink-700/60 bg-ink-900/40 p-3">
      <div class="flex flex-wrap gap-2">
        <button
          v-for="j in dohJobs"
          :key="j.id"
          class="rounded-md px-2.5 py-1 text-xs transition"
          :class="job === j.id ? 'bg-amber-500/20 text-amber-200' : 'bg-ink-800 text-ink-400 hover:text-white'"
          @click="job = j.id"
        >
          {{ j.name }}
        </button>
        <button
          v-if="running"
          class="ml-auto rounded-md bg-red-500/20 px-4 py-1.5 text-xs font-semibold text-red-300"
          @click="stop"
        >
          停止生产
        </button>
      </div>

      <div class="mt-3 flex flex-wrap items-center gap-2 text-xs">
        <input
          v-model="keyword"
          placeholder="按名称搜索"
          class="rounded border border-ink-600 bg-ink-900 px-2 py-1.5 outline-none focus:border-amber-400"
        >
        <select v-model="kindFilter" class="rounded border border-ink-600 bg-ink-900 px-2 py-1.5">
          <option v-for="k in kindOptions" :key="k.id" :value="k.id">{{ k.label }}</option>
        </select>
        <label class="flex items-center gap-1 text-ink-400">
          等级
          <input
            v-model.number="levelMin"
            type="number"
            min="1"
            step="1"
            placeholder="最低"
            class="w-16 rounded border border-ink-600 bg-ink-900 px-2 py-1.5 outline-none focus:border-amber-400"
          >
          <span class="text-ink-600">-</span>
          <input
            v-model.number="levelMax"
            type="number"
            min="1"
            step="1"
            placeholder="最高"
            class="w-16 rounded border border-ink-600 bg-ink-900 px-2 py-1.5 outline-none focus:border-amber-400"
          >
        </label>
        <button
          v-if="hasFilters"
          class="rounded bg-ink-800 px-2.5 py-1.5 text-ink-300 transition hover:text-white"
          @click="resetFilters"
        >
          重置
        </button>
        <span class="ml-auto text-ink-500">共 {{ recipes.length }} 个配方</span>
      </div>

      <p v-if="error" class="mt-2 text-xs text-red-400">{{ error }}</p>

      <div v-if="running" class="mt-3">
        <div class="mb-1 flex justify-between text-[11px] text-ink-400">
          <span>
            正在制造…
            <span v-if="dohdol.targetCount !== null" class="text-ink-300">
              （{{ dohdol.producedCount }}/{{ dohdol.targetCount }}）
            </span>
            <span v-if="dohdol.starved" class="text-rose-400">材料不足，已暂停（补充材料后自动继续）</span>
          </span>
          <span class="font-mono" :class="dohdol.starved ? 'text-rose-400' : 'text-emerald-300'">
            {{ dohdol.progressPct }}%
          </span>
        </div>
        <div class="h-2 overflow-hidden rounded-full bg-ink-800">
          <div
            class="h-full rounded-full transition-[width] duration-100 ease-linear"
            :class="dohdol.starved ? 'bg-rose-500' : 'bg-emerald-500'"
            :style="{ width: `${dohdol.progressPct}%` }"
          />
        </div>
      </div>
    </section>

    <section class="space-y-2">
      <div
        v-for="r in recipes"
        :key="r.id"
        class="rounded-lg border p-3"
        :class="r.unlocked ? 'border-ink-700/60 bg-ink-900/40' : 'border-ink-800/60 bg-ink-950/40 opacity-60'"
      >
        <div class="flex flex-wrap items-center gap-2">
          <ItemIcon :base-id="r.output.baseId ?? r.output.itemId ?? ''" variant="plain" :size="24" />
          <span class="text-sm text-ink-100">{{ r.output.name }}</span>
          <span v-if="r.output.kind === 'consumable'" class="text-xs leading-relaxed text-emerald-300">
            {{ consumableBonus(r.output.itemId) }}
          </span>
          <span v-if="r.output.quality === 'high'" class="rounded bg-amber-500/20 px-1.5 py-0.5 text-[10px] text-amber-200">
            高品质
          </span>
          <span v-if="r.output.supply === 'dohdol'" class="rounded bg-sky-500/20 px-1.5 py-0.5 text-[10px] text-sky-200">
            专用装备
          </span>
          <span
            v-if="!r.unlocked"
            class="rounded bg-ink-800 px-1.5 py-0.5 text-[10px] text-ink-400"
          >需生产等级 Lv.{{ r.requiredLevel }}</span>
          <div class="ml-auto flex items-center gap-1.5">
            <input
              v-model.number="amounts[r.id]"
              type="number"
              min="1"
              step="1"
              class="w-16 rounded-md border border-ink-700 bg-ink-900 px-2 py-1 text-right text-xs text-ink-100 disabled:opacity-40"
              :disabled="!r.unlocked || r.craftable <= 0"
              title="要制作的数量"
            >
            <button
              class="rounded-md px-2.5 py-1 text-xs transition"
              :class="r.unlocked && r.craftable > 0 ? 'bg-emerald-500/20 text-emerald-300' : 'bg-ink-800 text-ink-500'"
              :disabled="!r.unlocked || r.craftable <= 0"
              @click="startRecipe(r.id, amountOf(r.id))"
            >
              制作{{ amountOf(r.id) }}个
            </button>
            <button
              class="rounded-md px-2.5 py-1 text-xs transition"
              :class="r.unlocked && r.craftable > 0 ? 'bg-sky-500/20 text-sky-300' : 'bg-ink-800 text-ink-500'"
              :disabled="!r.unlocked || r.craftable <= 0"
              @click="startRecipe(r.id, null)"
            >
              制作全部
            </button>
          </div>
        </div>
        <div class="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-[11px]">
          <span
            v-for="i in r.inputs"
            :key="i.itemId"
            class="inline-flex items-center gap-1"
            :class="i.have >= i.count ? 'text-ink-300' : 'text-red-400'"
          >
            <ItemIcon :base-id="i.itemId" variant="plain" :size="16" />
            {{ i.name }} {{ i.have }}/{{ i.count }}
            <button
              v-if="i.have < i.count && gatherTargets.get(i.itemId)"
              class="rounded bg-emerald-500/15 px-1.5 py-0.5 text-[10px] text-emerald-300 transition hover:bg-emerald-500/25"
              title="跳转到采集页面并开始采集"
              @click="goGather(i.itemId)"
            >
              ⛏ 采集
            </button>
          </span>
          <span class="text-ink-500">可制造 {{ r.craftable }} 次 · 每次 {{ r.craftSeconds }}s · +{{ r.xp }} 经验</span>
        </div>
      </div>
      <p v-if="!recipes.length" class="text-xs text-ink-500">
        {{ hasFilters ? '没有符合筛选条件的配方。' : '该职业暂无可制造配方。' }}
      </p>
    </section>

    <section class="grid gap-3 md:grid-cols-3">
      <div class="rounded-lg border border-ink-700/60 bg-ink-900/40 p-3">
        <h2 class="mb-2 text-xs font-semibold text-ink-300">本次生产</h2>
        <ul v-if="dohdol.lastGained.length" class="space-y-1 text-xs">
          <li v-for="g in dohdol.lastGained" :key="g.itemId" class="flex justify-between text-ink-200">
            <span class="flex min-w-0 items-center gap-1.5">
              <ItemIcon :base-id="g.itemId" variant="plain" :size="18" />
              <span class="min-w-0"><span class="block">{{ g.name }}</span><span class="block text-[11px] leading-relaxed text-emerald-300">{{ consumableBonus(g.itemId) }}</span></span>
            </span>
            <span class="text-emerald-300">+{{ g.count }}</span>
          </li>
        </ul>
        <ul v-if="dohdol.lastProduced.length" class="space-y-1 text-xs">
          <li v-for="(p, i) in dohdol.lastProduced" :key="i" class="flex items-center gap-1.5 text-amber-200">
            <ItemIcon :base-id="p.baseId" variant="plain" :size="18" />
            <span class="truncate">★ {{ p.name }}（高品质）</span>
          </li>
        </ul>
        <p v-if="!dohdol.lastGained.length && !dohdol.lastProduced.length" class="text-xs text-ink-500">尚未生产。</p>
      </div>

      <div class="rounded-lg border border-ink-700/60 bg-ink-900/40 p-3">
        <h2 class="mb-2 text-xs font-semibold text-ink-300">材料库存</h2>
        <div class="max-h-56 space-y-1 overflow-y-auto text-xs">
          <div v-for="m in materials" :key="m.itemId" class="flex items-center justify-between text-ink-200">
            <span class="flex min-w-0 items-center gap-1.5">
              <ItemIcon :base-id="m.itemId" variant="plain" :size="18" />
              <span class="truncate">{{ m.name }}</span>
            </span>
            <span class="flex shrink-0 items-center gap-2">
              <span class="font-mono text-ink-400">×{{ m.count }}</span>
              <span class="font-mono text-ink-500">{{ (m.sell ?? 0) * m.count }}</span>
              <button
                class="rounded bg-ink-800 px-2 py-0.5 text-[10px] text-amber-300 hover:bg-ink-700 disabled:opacity-40"
                :disabled="(m.sell ?? 0) <= 0"
                @click="dohdol.sellStack(m.kind, m.itemId, m.count)"
              >
                出售
              </button>
            </span>
          </div>
          <p v-if="!materials.length" class="text-ink-500">暂无材料。</p>
        </div>
      </div>

      <div class="rounded-lg border border-ink-700/60 bg-ink-900/40 p-3">
        <h2 class="mb-2 text-xs font-semibold text-ink-300">药水 / 食物</h2>
        <div class="max-h-56 space-y-1 overflow-y-auto text-xs">
          <div v-for="c in consumables" :key="c.itemId" class="flex items-center justify-between text-ink-200">
            <span class="flex min-w-0 items-center gap-1.5">
              <ItemIcon :base-id="c.itemId" variant="plain" :size="18" />
              <span class="min-w-0"><span class="block">{{ c.name }}</span><span class="block text-[11px] leading-relaxed text-emerald-300">{{ consumableBonus(c.itemId) }}</span></span>
            </span>
            <span class="flex shrink-0 items-center gap-2">
              <span class="font-mono text-ink-400">×{{ c.count }}</span>
              <button class="rounded bg-ink-800 px-2 py-0.5 text-[10px] text-emerald-300 hover:bg-ink-700" @click="dohdol.useConsumable(c.itemId)">
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
          <p v-if="!consumables.length" class="text-ink-500">暂无药水食物。</p>
        </div>
      </div>
    </section>
  </div>
</template>
