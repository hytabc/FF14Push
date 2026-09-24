<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'

import data from '@shared/schema'

import { api } from '@/api'
import { toApiError } from '@/api/client'
import InfoTip from '@/components/InfoTip.vue'
import ItemIcon from '@/components/ItemIcon.vue'
import Modal from '@/components/Modal.vue'
import type { FarmPlotState, FarmState, Hero } from '@/game/types'
import { useGameStore } from '@/stores/game'
import { useToastStore } from '@/stores/toast'
import { formatDuration, formatNumber } from '@/utils/format'

const game = useGameStore()
const toast = useToastStore()

const LEVEL_CAP = Number(data.heroes.levelCap ?? 100)

const farm = ref<FarmState | null>(null)
const loading = ref(false)
const busy = ref(false)
/** 每片田的本地成熟时刻（anchor）：用服务端 remainingMs 锚定，避免客户端时钟偏差。 */
const anchors = ref<Record<number, number>>({})
const nowMs = ref(Date.now())
const plantAt = ref<number | null>(null)
const harvestAt = ref<number | null>(null)
const maxLevelWarn = ref<{ index: number; heroId: number; heroName: string } | null>(null)

let ticker = 0

const heroes = computed<Hero[]>(() => game.state?.heroes ?? (game.hero ? [game.hero] : []))
const nextLockedIndex = computed(() => {
  const plots = farm.value?.plots ?? []
  const locked = plots.filter((p) => p.locked)
  return locked.length ? locked[0].index : null
})

const seedsById = computed(() => {
  const out: Record<string, string> = {}
  for (const seed of farm.value?.seeds ?? []) out[seed.id] = seed.name
  return out
})

function syncAnchors() {
  const stamp = Date.now()
  const out: Record<number, number> = {}
  for (const plot of farm.value?.plots ?? []) {
    out[plot.index] = stamp + Math.max(0, plot.remainingMs)
  }
  anchors.value = out
}

async function load() {
  loading.value = true
  try {
    farm.value = await api.farmState()
    syncAnchors()
  } catch (e) {
    toast.push(toApiError(e).message, 'error')
  } finally {
    loading.value = false
  }
}

onMounted(async () => {
  if (!game.state) await game.loadState()
  await load()
  ticker = window.setInterval(() => {
    nowMs.value = Date.now()
  }, 1000)
})

onUnmounted(() => {
  if (ticker) window.clearInterval(ticker)
})

/** 用本地单调时钟插值生长进度（不依赖客户端绝对时间，进度只前进）。 */
function progress(plot: FarmPlotState) {
  const config = farm.value
  if (!plot.seedId || !config) return null
  const totalMs = config.stages * config.stageSeconds * 1000
  const readyAt = anchors.value[plot.index]
  if (readyAt === undefined || totalMs <= 0) {
    return { pct: 0, remainingMs: plot.remainingMs, stage: plot.stage, ready: plot.ready }
  }
  const remaining = Math.max(0, readyAt - nowMs.value)
  const elapsed = Math.max(0, totalMs - remaining)
  const stageMs = config.stageSeconds * 1000
  return {
    pct: Math.min(100, (elapsed / totalMs) * 100),
    remainingMs: remaining,
    stage: Math.min(config.stages, Math.floor(elapsed / stageMs)),
    ready: remaining <= 0,
  }
}

async function expand() {
  if (busy.value) return
  busy.value = true
  try {
    const res = await api.farmExpand()
    farm.value = res.state
    syncAnchors()
    toast.push(`扩张成功，消耗 ${formatNumber(res.cost)} 金币`, 'success')
    await game.loadState()
  } catch (e) {
    toast.push(toApiError(e).message, 'error')
  } finally {
    busy.value = false
  }
}

async function plant(seedId: string) {
  const index = plantAt.value
  if (index === null || busy.value) return
  busy.value = true
  try {
    const res = await api.farmPlant(index, seedId)
    farm.value = res.state
    syncAnchors()
    plantAt.value = null
    toast.push(`已种下 ${seedsById.value[seedId] ?? '种子'}`, 'success')
  } catch (e) {
    toast.push(toApiError(e).message, 'error')
  } finally {
    busy.value = false
  }
}

async function doHarvest(index: number, heroId: number | null, confirm: boolean) {
  if (busy.value) return
  busy.value = true
  try {
    const res = await api.farmHarvest(index, heroId, confirm)
    farm.value = res.state
    syncAnchors()
    harvestAt.value = null
    maxLevelWarn.value = null
    const result = res.result
    if (result.type === 'gold') {
      toast.push(`收获 ${formatNumber(result.amount ?? 0)} 金币`, 'loot')
    } else if (result.noEffect) {
      toast.push(`${result.heroName} 已满级，本次收获无任何效果`, 'error')
    } else {
      toast.push(`${result.heroName} 升到 ${result.level} 级！`, 'success')
    }
    await game.loadState()
  } catch (e) {
    const err = toApiError(e)
    if (err.code === 'hero_max_level' && heroId !== null && !confirm) {
      const hero = heroes.value.find((h) => h.id === heroId)
      harvestAt.value = null
      maxLevelWarn.value = { index, heroId, heroName: hero?.name ?? '' }
    } else {
      toast.push(err.message, 'error')
    }
  } finally {
    busy.value = false
  }
}

/** 收获：金币种子直接收；经验种子先选英雄。 */
function harvest(plot: FarmPlotState) {
  const seed = farm.value?.seeds.find((s) => s.id === plot.seedId)
  if (!seed) return
  if (seed.yield?.type === 'heroLevel') {
    harvestAt.value = plot.index
    return
  }
  void doHarvest(plot.index, null, false)
}

function pickHero(hero: Hero) {
  const index = harvestAt.value
  if (index === null || hero.id === null) return
  if (hero.level >= LEVEL_CAP) {
    // 满级：直接弹二次确认（服务端同样会校验）
    harvestAt.value = null
    maxLevelWarn.value = { index, heroId: hero.id, heroName: hero.name }
    return
  }
  void doHarvest(index, hero.id, false)
}
</script>

<template>
  <div class="space-y-4">
    <section class="card p-4">
      <div class="flex flex-wrap items-center gap-3">
        <h2 class="text-lg font-semibold text-white">种田</h2>
        <span class="text-xs text-ink-400">
          田地 {{ farm?.unlocked ?? 0 }} / {{ farm?.maxPlots ?? 10 }} 片 · 作物按
          <strong class="text-ink-200">真实时间</strong>生长（离线也生长）
        </span>
        <InfoTip title="生长与收获">
          <p>从种植到成熟共 {{ farm?.stages ?? 5 }} 个阶段，每阶段 {{ (farm?.stageSeconds ?? 600) / 60 }} 分钟。</p>
          <p>金币种子：收获 {{ formatNumber(10000000) }} 金币。</p>
          <p>经验种子：为指定英雄提升 1 级；满级英雄收获无任何效果。</p>
          <p class="text-ink-400">来源：shared/data/farm.json。</p>
        </InfoTip>
        <span class="ml-auto text-xs text-ink-400">
          金币 <span class="font-mono text-amber-300">{{ formatNumber(farm?.gold ?? game.gold) }}</span>
        </span>
      </div>
    </section>

    <!-- 田地 -->
    <section class="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
      <div
        v-for="plot in farm?.plots ?? []"
        :key="plot.index"
        class="card flex flex-col gap-2 p-4"
        :class="plot.locked ? 'opacity-60' : ''"
      >
        <div class="flex items-center justify-between">
          <span class="text-sm font-medium text-ink-100">田地 {{ plot.index + 1 }}</span>
          <span v-if="plot.locked" class="rounded bg-ink-800 px-2 py-0.5 text-[10px] text-ink-400">未解锁</span>
          <span
            v-else-if="progress(plot)?.ready"
            class="rounded bg-emerald-500/20 px-2 py-0.5 text-[10px] text-emerald-200"
          >
            可收获
          </span>
          <span v-else-if="plot.seedId" class="rounded bg-ink-800 px-2 py-0.5 text-[10px] text-ink-300">生长中</span>
          <span v-else class="rounded bg-ink-800 px-2 py-0.5 text-[10px] text-ink-400">空闲</span>
        </div>

        <!-- 未解锁 -->
        <template v-if="plot.locked">
          <p class="text-[11px] text-ink-500">
            扩张价格
            <span v-if="plot.index === nextLockedIndex" class="font-mono text-amber-300">
              {{ formatNumber(farm?.expansionCost ?? 0) }}
            </span>
            <span v-else class="text-ink-600">（需先解锁前一片）</span>
          </p>
          <button
            v-if="plot.index === nextLockedIndex"
            class="mt-auto rounded-md bg-amber-500 px-3 py-1.5 text-xs font-medium text-ink-950 hover:bg-amber-400 disabled:opacity-50"
            :disabled="busy || (farm?.expansionCost ?? 0) > (farm?.gold ?? 0)"
            @click="expand"
          >
            扩张田地
          </button>
        </template>

        <!-- 空闲：种植 -->
        <template v-else-if="!plot.seedId">
          <p class="text-[11px] text-ink-500">选择种子开始种植。</p>
          <button
            class="mt-auto rounded-md bg-emerald-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-emerald-500 disabled:opacity-50"
            :disabled="busy"
            @click="plantAt = plot.index"
          >
            种植
          </button>
        </template>

        <!-- 生长中 / 成熟 -->
        <template v-else>
          <div class="flex items-center gap-2">
            <ItemIcon :base-id="plot.seedId" :size="24" variant="plain" />
            <div class="min-w-0 flex-1">
              <p class="truncate text-sm text-ink-100">{{ plot.seedName }}</p>
              <p class="text-[11px] text-ink-400">
                阶段 {{ progress(plot)?.stage ?? plot.stage }} / {{ plot.stages }} ·
                <span v-if="progress(plot)?.ready" class="text-emerald-300">已成熟</span>
                <span v-else>剩余 {{ formatDuration(progress(plot)?.remainingMs ?? plot.remainingMs) }}</span>
              </p>
            </div>
          </div>
          <div class="h-2 overflow-hidden rounded-full bg-ink-800">
            <div
              class="h-full rounded-full bg-emerald-500 transition-[width] duration-1000 ease-linear"
              :style="{ width: `${progress(plot)?.pct ?? 0}%` }"
            />
          </div>
          <button
            class="mt-auto rounded-md px-3 py-1.5 text-xs font-medium disabled:opacity-50"
            :class="
              progress(plot)?.ready
                ? 'bg-amber-500 text-ink-950 hover:bg-amber-400'
                : 'cursor-not-allowed bg-ink-800 text-ink-600'
            "
            :disabled="busy || !progress(plot)?.ready"
            @click="harvest(plot)"
          >
            收获
          </button>
        </template>
      </div>
    </section>

    <!-- 种子库存 -->
    <section class="card p-4">
      <h3 class="text-sm font-semibold text-white">种子库存</h3>
      <p class="mt-1 text-[11px] text-ink-500">种子由挖宝产出。</p>
      <div class="mt-3 grid gap-2 text-xs sm:grid-cols-2">
        <div
          v-for="seed in farm?.seeds ?? []"
          :key="seed.id"
          class="flex items-center gap-2 rounded-lg border border-ink-700 bg-ink-800/40 p-2"
        >
          <ItemIcon :base-id="seed.id" :size="24" variant="plain" />
          <div class="min-w-0 flex-1">
            <p class="text-ink-100">{{ seed.name }}</p>
            <p class="text-[11px] text-ink-400">{{ seed.desc }}</p>
          </div>
          <span class="font-mono" :class="seed.count > 0 ? 'text-amber-300' : 'text-ink-600'">×{{ seed.count }}</span>
        </div>
      </div>
    </section>

    <!-- 选择种子 -->
    <Modal :open="plantAt !== null" title="选择种子" @close="plantAt = null">
      <div class="grid gap-2 text-xs sm:grid-cols-2">
        <button
          v-for="seed in farm?.seeds ?? []"
          :key="seed.id"
          class="flex items-center gap-2 rounded-lg border border-ink-700 bg-ink-800/40 p-2 text-left transition hover:border-amber-400 disabled:opacity-40"
          :disabled="busy || seed.count <= 0"
          @click="plant(seed.id)"
        >
          <ItemIcon :base-id="seed.id" :size="24" variant="plain" />
          <div class="min-w-0 flex-1">
            <p class="text-ink-100">{{ seed.name }}</p>
            <p class="text-[11px] text-ink-400">{{ seed.desc }}</p>
          </div>
          <span class="font-mono text-amber-300">×{{ seed.count }}</span>
        </button>
      </div>
      <template #footer>
        <button class="rounded-md bg-ink-700 px-3 py-2 text-sm text-ink-200 hover:bg-ink-600" @click="plantAt = null">
          取消
        </button>
      </template>
    </Modal>

    <!-- 选择英雄（经验种子） -->
    <Modal :open="harvestAt !== null" title="选择获得 1 级的英雄" @close="harvestAt = null">
      <div class="grid gap-2 text-xs sm:grid-cols-2">
        <button
          v-for="heroItem in heroes"
          :key="heroItem.id ?? heroItem.name"
          class="flex items-center gap-2 rounded-lg border border-ink-700 bg-ink-800/40 p-2 text-left transition hover:border-amber-400 disabled:opacity-40"
          :disabled="busy"
          @click="pickHero(heroItem)"
        >
          <div class="min-w-0 flex-1">
            <p class="truncate text-ink-100">{{ heroItem.name }}</p>
            <p class="text-[11px]" :class="heroItem.level >= LEVEL_CAP ? 'text-rose-300' : 'text-ink-400'">
              Lv.{{ heroItem.level }} / {{ LEVEL_CAP }}
              <span v-if="heroItem.level >= LEVEL_CAP">（已满级）</span>
            </p>
          </div>
        </button>
      </div>
      <template #footer>
        <button class="rounded-md bg-ink-700 px-3 py-2 text-sm text-ink-200 hover:bg-ink-600" @click="harvestAt = null">
          取消
        </button>
      </template>
    </Modal>

    <!-- 满级二次确认 -->
    <Modal :open="maxLevelWarn !== null" title="英雄已满级" @close="maxLevelWarn = null">
      <p class="text-sm text-ink-200">
        「{{ maxLevelWarn?.heroName }}」已达到 {{ LEVEL_CAP }} 级，本次收获<strong class="text-rose-300">不会有任何效果</strong>，
        种子仍会被消耗。
      </p>
      <p class="mt-2 text-[11px] text-ink-400">可以选择取消收获（保留成熟作物）或执意收获。</p>
      <template #footer>
        <button class="rounded-md bg-ink-700 px-3 py-2 text-sm text-ink-200 hover:bg-ink-600" @click="maxLevelWarn = null">
          取消收获
        </button>
        <button
          class="rounded-md bg-rose-600 px-3 py-2 text-sm font-medium text-white hover:bg-rose-500 disabled:opacity-50"
          :disabled="busy"
          @click="maxLevelWarn && doHarvest(maxLevelWarn.index, maxLevelWarn.heroId, true)"
        >
          执意收获
        </button>
      </template>
    </Modal>
  </div>
</template>
