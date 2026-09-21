<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'

import data from '@shared/schema'

import InfoTip from '@/components/InfoTip.vue'
import { fishChanceExplain } from '@/game/explanations'
import { useAuthStore } from '@/stores/auth'
import { useDohDolStore } from '@/stores/dohdol'
import { useGameStore } from '@/stores/game'
import { useToastStore } from '@/stores/toast'

const game = useGameStore()
const dohdol = useDohDolStore()
const auth = useAuthStore()
const toast = useToastStore()

const regionId = ref<number | null>(null)
const error = ref('')

const progress = computed(() => dohdol.state?.progress?.dol ?? null)
const running = computed(() => dohdol.isRunning && dohdol.mode === 'fish')
const stats = computed(() => dohdol.state?.fishStats ?? null)
const titles = computed(() => dohdol.state?.titles ?? [])

const regionOptions = computed(() =>
  data.fish.regions
    .filter((r) => {
      const p = game.state?.regionProgress?.[String(r.regionId)]
      return p ? p.unlocked : r.regionId === 1
    })
    .map((r) => ({ id: r.regionId, name: r.name })),
)

const currentRegion = computed(() => data.fish.regions.find((r) => r.regionId === regionId.value) ?? null)

/** 鱼王/鱼皇「鱼识加成」来自专用装备（药水加成在服务端结算时另计）。 */
const chanceBonus = computed(() => dohdol.state?.bonus?.fishChancePct ?? 0)
function fishInfo(region: (typeof data.fish.regions)[number]) {
  return fishChanceExplain(region, chanceBonus.value)
}

/** 鱼获库存（鱼作为可出售材料存储）。 */
const fishBag = computed(() =>
  (dohdol.state?.materials ?? []).filter((m) => m.materialKind === 'fish').sort((a, b) => b.count - a.count),
)
const fishBagValue = computed(() => fishBag.value.reduce((sum, f) => sum + (f.sell ?? 0) * f.count, 0))

function sellAllFish() {
  void dohdol.sellStacks(
    fishBag.value
      .filter((f) => (f.sell ?? 0) > 0)
      .map((f) => ({ kind: f.kind, itemId: f.itemId, count: f.count })),
  )
}

onMounted(async () => {
  if (auth.isLoggedIn) await game.loadState()
  if (regionOptions.value.length && regionId.value === null) regionId.value = regionOptions.value[0].id
  document.addEventListener('visibilitychange', onVisibility)
})
onUnmounted(() => {
  document.removeEventListener('visibilitychange', onVisibility)
  void dohdol.stop(true)
})

function onVisibility() {
  dohdol.handleVisibility()
}

function kindLabel(kind: string) {
  return kind === 'king' ? '鱼王' : kind === 'emperor' ? '鱼皇' : '普通'
}

function kindClass(kind: string) {
  if (kind === 'emperor') return 'text-red-400'
  if (kind === 'king') return 'text-amber-300'
  return 'text-ink-200'
}

async function toggle() {
  error.value = ''
  if (running.value) {
    await dohdol.stop()
    return
  }
  if (regionId.value === null) {
    error.value = '请选择钓场'
    return
  }
  try {
    await dohdol.startFish(regionId.value)
  } catch (e) {
    error.value = e instanceof Error ? e.message : '钓鱼失败'
    toast.push(error.value, 'error')
  }
}
</script>

<template>
  <div class="space-y-4">
    <section class="rounded-lg border border-ink-700/60 bg-ink-900/40 p-3">
      <div class="flex flex-wrap items-center gap-3">
        <h1 class="text-sm font-bold text-amber-200">钓鱼 · 捕鱼人</h1>
        <span v-if="progress" class="rounded bg-ink-800 px-2 py-1 text-xs text-ink-300">
          采集等级 Lv.{{ progress.level }} · {{ progress.exp }}/{{ progress.expToNext }}
        </span>
        <span
          v-if="dohdol.insightRemaining > 0"
          class="rounded bg-sky-500/20 px-2 py-1 text-xs text-sky-200"
        >
          捕鱼人之识 {{ dohdol.insightRemaining }}s
        </span>
      </div>
      <p class="mt-1 text-[11px] text-ink-500">
        先钓起前置普通鱼开启「捕鱼人之识」，期间才有小概率钓起鱼王 / 鱼皇（鱼皇更稀有）。
        <InfoTip v-if="currentRegion" :title="fishInfo(currentRegion).title">
          <p v-for="(line, i) in fishInfo(currentRegion).lines" :key="i">{{ line }}</p>
        </InfoTip>
      </p>
    </section>

    <section class="rounded-lg border border-ink-700/60 bg-ink-900/40 p-3">
      <div class="flex flex-wrap items-center gap-2">
        <select v-model.number="regionId" class="rounded bg-ink-800 px-2 py-1 text-xs text-ink-200">
          <option :value="null" disabled>选择钓场</option>
          <option v-for="r in regionOptions" :key="r.id" :value="r.id">{{ r.name }}</option>
        </select>
        <button
          class="rounded-md px-4 py-1.5 text-xs font-semibold transition"
          :class="running ? 'bg-red-500/20 text-red-300' : 'bg-emerald-500/20 text-emerald-300'"
          @click="toggle"
        >
          {{ running ? '停止钓鱼' : '开始钓鱼' }}
        </button>
      </div>
      <p v-if="error" class="mt-2 text-xs text-red-400">{{ error }}</p>

      <div v-if="running" class="mt-3">
        <div class="mb-1 flex justify-between text-[11px] text-ink-400">
          <span>正在抛竿…</span>
          <span class="font-mono text-sky-300">{{ dohdol.progressPct }}%</span>
        </div>
        <div class="h-2 overflow-hidden rounded-full bg-ink-800">
          <div
            class="h-full rounded-full bg-sky-500 transition-[width] duration-100 ease-linear"
            :style="{ width: `${dohdol.progressPct}%` }"
          />
        </div>
      </div>
      <div v-if="currentRegion" class="mt-2 text-[11px] text-ink-500">
        鱼王：{{ currentRegion.king.name }}（{{ (currentRegion.king.chance * 100).toFixed(1) }}%，前置 {{ currentRegion.king.prereqFishIds.length }} 种普通鱼）·
        鱼皇：{{ currentRegion.emperor.name }}（{{ (currentRegion.emperor.chance * 100).toFixed(1) }}%）
      </div>
    </section>

    <section class="grid gap-3 md:grid-cols-3">
      <div class="rounded-lg border border-ink-700/60 bg-ink-900/40 p-3 md:col-span-2">
        <h2 class="mb-2 text-xs font-semibold text-ink-300">本次鱼获</h2>
        <ul v-if="dohdol.lastCaught.length" class="max-h-64 space-y-1 overflow-y-auto text-xs">
          <li v-for="(f, i) in dohdol.lastCaught" :key="i" class="flex justify-between">
            <span :class="kindClass(f.kind)">{{ f.name }}</span>
            <span class="text-ink-400">{{ kindLabel(f.kind) }} · {{ f.size }}cm</span>
          </li>
        </ul>
        <p v-else class="text-xs text-ink-500">尚未钓起。</p>
      </div>

      <div class="space-y-3">
        <div class="rounded-lg border border-ink-700/60 bg-ink-900/40 p-3">
          <h2 class="mb-2 text-xs font-semibold text-ink-300">钓鱼统计</h2>
          <div v-if="stats" class="space-y-1 text-xs text-ink-200">
            <div class="flex justify-between"><span>钓鱼种类</span><span>{{ stats.species }}</span></div>
            <div class="flex justify-between"><span>钓鱼数量</span><span>{{ stats.count }}</span></div>
            <div class="flex justify-between"><span>鱼王</span><span>{{ stats.king }}/{{ stats.kingTotal }}</span></div>
            <div class="flex justify-between"><span>鱼皇</span><span>{{ stats.emperor }}/{{ stats.emperorTotal }}</span></div>
          </div>
        </div>
        <div class="rounded-lg border border-ink-700/60 bg-ink-900/40 p-3">
          <h2 class="mb-2 text-xs font-semibold text-ink-300">称号</h2>
          <ul class="space-y-1 text-xs">
            <li v-for="t in titles" :key="t.id" :class="t.owned ? 'text-amber-300' : 'text-ink-500'">
              {{ t.owned ? '★' : '☆' }} {{ t.name }} — {{ t.desc }}
            </li>
          </ul>
        </div>
      </div>
    </section>

    <section class="rounded-lg border border-ink-700/60 bg-ink-900/40 p-3">
      <div class="mb-2 flex items-center justify-between">
        <h2 class="text-xs font-semibold text-ink-300">鱼获库存（可出售）</h2>
        <button
          v-if="fishBag.length"
          class="rounded bg-amber-600/70 px-2 py-0.5 text-[10px] text-white hover:bg-amber-500"
          @click="sellAllFish"
        >
          全部出售（+{{ fishBagValue }}）
        </button>
      </div>
      <div class="grid gap-1 text-xs sm:grid-cols-2 lg:grid-cols-3">
        <div
          v-for="f in fishBag"
          :key="f.itemId"
          class="flex items-center justify-between gap-2 rounded border border-ink-800 bg-ink-950/40 px-2 py-1"
        >
          <span class="truncate text-ink-200">{{ f.name }}</span>
          <span class="flex shrink-0 items-center gap-2">
            <span class="font-mono text-ink-400">×{{ f.count }}</span>
            <span class="font-mono text-ink-500">{{ (f.sell ?? 0) * f.count }}</span>
            <button
              class="rounded bg-ink-800 px-2 py-0.5 text-[10px] text-amber-300 hover:bg-ink-700"
              @click="dohdol.sellStack(f.kind, f.itemId, f.count)"
            >
              出售
            </button>
          </span>
        </div>
        <p v-if="!fishBag.length" class="text-ink-500">暂无鱼获。</p>
      </div>
    </section>
  </div>
</template>
