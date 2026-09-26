<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import data from '@shared/schema'

import InfoTip from '@/components/InfoTip.vue'
import ItemIcon from '@/components/ItemIcon.vue'
import { fishChanceExplain, fishPriceExplain } from '@/game/explanations'
import type { Explain } from '@/game/explanations'
import { conditionsFor, forecast, secondsUntilWeatherChange, timeOfDayName, weatherName } from '@/game/weather'
import { useAuthStore } from '@/stores/auth'
import { useConfirmStore } from '@/stores/confirm'
import { useDohDolStore } from '@/stores/dohdol'
import { useGameStore } from '@/stores/game'
import { useToastStore } from '@/stores/toast'
import { fishKindRarity, fishRarity } from '@/utils/icons'

const game = useGameStore()
const dohdol = useDohDolStore()
const auth = useAuthStore()
const toast = useToastStore()
const confirm = useConfirmStore()
const route = useRoute()
const router = useRouter()

const regionId = ref<number | null>(null)
const error = ref('')

/** 每秒节拍：让天气 / ET /「捕鱼人之识」按绝对时间实时更新。 */
const nowMs = ref(Date.now())
let timer: number | undefined

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
    .map((r) => ({ id: r.regionId, name: r.name, levelReq: r.levelReq })),
)

const currentRegion = computed(() => data.fish.regions.find((r) => r.regionId === regionId.value) ?? null)
const specials = computed(() => currentRegion.value?.specials ?? [])

/** 当前钓场的天气 / 艾欧泽亚时间（与后端 `weather.conditions_for` 同源）。 */
const conditions = computed(() => (regionId.value === null ? null : conditionsFor(regionId.value, nowMs.value)))
const weatherForecast = computed(() => (regionId.value === null ? [] : forecast(regionId.value, 6, nowMs.value)))
const nextWeatherIn = computed(() => secondsUntilWeatherChange(nowMs.value))

/** 生效中的「捕鱼人之识」（每次直觉只绑定一条鱼，可同时存在多个）。 */
const insights = computed(() =>
  dohdol.insights
    .map((i) => ({ ...i, remaining: Math.max(0, Math.ceil((Date.parse(i.expiresAt) - nowMs.value) / 1000)) }))
    .filter((i) => i.remaining > 0),
)

/** 钓场还需采集等级达到 levelReq 才能开始。 */
const regionLevelLocked = computed(() =>
  currentRegion.value ? currentRegion.value.levelReq > (progress.value?.level ?? 1) : false,
)

/** 「特殊鱼概率」加成来自专用装备（药水加成在服务端结算时另计），对鱼王 / 鱼皇 / 困难鱼同样生效。 */
const chanceBonus = computed(() => dohdol.state?.bonus?.fishChancePct ?? 0)
function fishInfo(region: (typeof data.fish.regions)[number]) {
  return fishChanceExplain(region, chanceBonus.value)
}

/** 困难鱼（legend）的单价定价依据，按鱼 id 缓存给「?」气泡用。 */
const priceInfoById = computed(() => {
  const out: Record<string, Explain> = {}
  for (const s of specials.value) {
    const info = fishPriceExplain(s)
    if (info) out[s.id] = info
  }
  return out
})

/** 鱼获库存（鱼作为可出售材料存储）。 */
const fishBag = computed(() =>
  (dohdol.state?.materials ?? []).filter((m) => m.materialKind === 'fish').sort((a, b) => b.count - a.count),
)
const fishBagValue = computed(() => fishBag.value.reduce((sum, f) => sum + (f.sell ?? 0) * f.count, 0))

async function sellAllFish() {
  const rows = fishBag.value.filter((f) => (f.sell ?? 0) > 0)
  if (!rows.length) return
  const ok = await confirm.ask({
    title: '确认全部出售',
    message: `将出售 ${rows.length} 种鱼获，预计获得 ${fishBagValue.value} 金币。\n出售后物品永久消失。`,
    confirmLabel: '确认出售',
    tone: 'danger',
  })
  if (!ok) return
  await dohdol.sellStacks(rows.map((f) => ({ kind: f.kind, itemId: f.itemId, count: f.count })))
}

/** 出售单个鱼获（二次确认，避免误触）。 */
async function sellOne(item: { kind: string; itemId: string; name: string; count: number; sell?: number }) {
  const ok = await confirm.ask({
    title: '确认出售',
    message: `出售「${item.name}」×${item.count}，获得 ${(item.sell ?? 0) * item.count} 金币。\n出售后物品永久消失。`,
    confirmLabel: '确认出售',
    tone: 'danger',
  })
  if (ok) await dohdol.sellStack(item.kind, item.itemId, item.count)
}

onMounted(async () => {
  timer = window.setInterval(() => (nowMs.value = Date.now()), 1000)
  if (auth.isLoggedIn) await game.loadState()
  applyJump()
  if (regionOptions.value.length && regionId.value === null) regionId.value = regionOptions.value[0].id
})
onUnmounted(() => {
  if (timer !== undefined) window.clearInterval(timer)
  void dohdol.stop(true)
})

/** 从图鉴跳转过来时：选中对应钓场（不自动开始钓鱼）。 */
function applyJump() {
  const regionParam = typeof route.query.region === 'string' ? Number(route.query.region) : NaN
  if (!Number.isFinite(regionParam)) return
  // 清掉 query，避免刷新 / 前进后退时重复触发
  void router.replace({ name: 'fish' })
  if (!regionOptions.value.some((r) => r.id === regionParam)) return
  regionId.value = regionParam
}

function kindLabel(kind: string) {
  if (kind === 'king') return '鱼王'
  if (kind === 'emperor') return '鱼皇'
  if (kind === 'legend') return '困难鱼'
  return '普通'
}

function kindClass(kind: string) {
  if (kind === 'legend') return 'text-rose-300'
  if (kind === 'emperor') return 'text-red-400'
  if (kind === 'king') return 'text-amber-300'
  return 'text-ink-200'
}

/** 特殊鱼的天气 / 时间窗口文案。 */
function specialGate(special: (typeof data.fish.regions)[number]['specials'][number]): string {
  const parts: string[] = []
  if (special.weather?.length) parts.push(special.weather.map((w) => weatherName(w)).join('/'))
  if (special.timeOfDay?.length) parts.push(special.timeOfDay.map((t) => timeOfDayName(t)).join('/'))
  return parts.join(' · ')
}

/** 特殊鱼的计数型前置文案。 */
function specialRequires(special: (typeof data.fish.regions)[number]['specials'][number]): string {
  return special.intuition.requires
    .map((r) => `${data.fishById[r.fishId]?.name ?? r.fishId}×${r.count}`)
    .join('、')
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
          v-for="i in insights"
          :key="i.fishId"
          class="rounded bg-sky-500/20 px-2 py-1 text-xs text-sky-200"
        >
          {{ i.buffName }}：{{ i.name }} {{ i.remaining }}s
        </span>
      </div>

      <!-- 天气 / 时间（当前 + 预报） -->
      <div v-if="conditions" class="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-ink-300">
        <span class="inline-flex items-center gap-1.5">
          <span class="inline-block h-2.5 w-2.5 rounded-full" :style="{ backgroundColor: conditions.weatherHex }" />
          天气：<b class="text-ink-100">{{ conditions.weatherName }}</b>
          <span class="text-ink-500">（{{ nextWeatherIn }}s 后变化）</span>
        </span>
        <span>艾欧泽亚时间：<b class="text-ink-100">{{ conditions.etClock }}</b> · {{ conditions.timeOfDayName }}</span>
      </div>
      <div v-if="weatherForecast.length" class="mt-1 flex flex-wrap gap-1 text-[10px]">
        <span
          v-for="(f, i) in weatherForecast"
          :key="i"
          class="rounded px-1.5 py-0.5"
          :class="f.isNow ? 'bg-sky-500/20 text-sky-200' : 'bg-ink-800 text-ink-400'"
          :title="`${f.etClock} · ${f.timeOfDayName}`"
        >
          {{ f.isNow ? '现在' : `${Math.max(1, Math.round(f.inSeconds / 60))}分后` }} {{ f.weatherName }}
        </span>
      </div>

      <p class="mt-2 text-[11px] text-ink-500">
        普通鱼分白 / 蓝 / 紫三档；特殊鱼（鱼王 / 鱼皇 / 困难鱼）需在特定天气或时段先钓齐前置，开启对应「捕鱼人之识」后才有小概率钓起。
        「特殊鱼概率」加成（专用装备 / 料理 / 秘药）对鱼王、鱼皇与困难鱼同样生效。
        <InfoTip v-if="currentRegion" :title="fishInfo(currentRegion).title">
          <p v-for="(line, i) in fishInfo(currentRegion).lines" :key="i">{{ line }}</p>
        </InfoTip>
      </p>
    </section>

    <section class="rounded-lg border border-ink-700/60 bg-ink-900/40 p-3">
      <div class="flex flex-wrap items-center gap-2">
        <select v-model.number="regionId" class="rounded bg-ink-800 px-2 py-1 text-xs text-ink-200">
          <option :value="null" disabled>选择钓场</option>
          <option v-for="r in regionOptions" :key="r.id" :value="r.id">
            {{ r.name }}（要求 Lv.{{ r.levelReq }}）
          </option>
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
      <p v-else-if="regionLevelLocked && currentRegion" class="mt-2 text-xs text-amber-300">
        采集等级不足：该钓场需要 Lv.{{ currentRegion.levelReq }}，当前 Lv.{{ progress?.level ?? 1 }}。
      </p>

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

      <!-- 钓场特殊鱼清单 -->
      <div v-if="specials.length" class="mt-2 space-y-1">
        <div
          v-for="s in specials"
          :key="s.id"
          class="flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[11px]"
        >
          <ItemIcon :base-id="s.id" :rarity="fishKindRarity(s.kind)" :size="20" />
          <span :class="kindClass(s.kind)">{{ kindLabel(s.kind) }}：{{ s.name }}</span>
          <span class="text-ink-400">{{ (s.intuition.chance * 100).toFixed(3) }}%</span>
          <span v-if="s.sell" class="text-amber-200/80">单价 {{ s.sell.toLocaleString() }}</span>
          <InfoTip v-if="priceInfoById[s.id]" :title="priceInfoById[s.id].title">
            <p v-for="(line, i) in priceInfoById[s.id].lines" :key="i">{{ line }}</p>
          </InfoTip>
          <span v-if="specialGate(s)" class="text-sky-300">{{ specialGate(s) }}</span>
          <span class="text-ink-400">前置 {{ specialRequires(s) }}</span>
        </div>
      </div>
    </section>

    <section class="grid gap-3 md:grid-cols-3">
      <div class="rounded-lg border border-ink-700/60 bg-ink-900/40 p-3 md:col-span-2">
        <h2 class="mb-2 text-xs font-semibold text-ink-300">本次鱼获</h2>
        <ul v-if="dohdol.lastCaught.length" class="max-h-64 space-y-1 overflow-y-auto text-xs">
          <li v-for="(f, i) in dohdol.lastCaught" :key="i" class="flex justify-between">
            <span class="flex min-w-0 items-center gap-1.5" :class="kindClass(f.kind)">
              <ItemIcon :base-id="f.id" :rarity="fishRarity(f.id)" :size="20" />
              <span class="truncate">{{ f.name }}</span>
            </span>
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
            <div class="flex justify-between"><span>困难鱼</span><span>{{ stats.legend }}/{{ stats.legendTotal }}</span></div>
          </div>
        </div>
        <div class="rounded-lg border border-ink-700/60 bg-ink-900/40 p-3">
          <h2 class="mb-2 text-xs font-semibold text-ink-300">称号</h2>
          <ul class="max-h-64 space-y-1 overflow-y-auto text-xs">
            <li
              v-for="t in titles"
              :key="t.id"
              :class="t.owned ? (dohdol.state?.activeTitleId === t.id ? 'text-amber-200' : 'text-amber-300') : 'text-ink-500'"
            >
              {{ t.owned ? (dohdol.state?.activeTitleId === t.id ? '★' : '☆') : '☆' }} {{ t.name }}
              <span v-if="t.egg" class="text-rose-300">[彩蛋]</span>
              — {{ t.desc }}
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
          <span class="flex min-w-0 items-center gap-1.5 text-ink-200">
            <ItemIcon :base-id="f.itemId" :rarity="fishRarity(f.itemId)" :size="20" />
            <span class="truncate">{{ f.name }}</span>
          </span>
          <span class="flex shrink-0 items-center gap-2">
            <span class="font-mono text-ink-400">×{{ f.count }}</span>
            <span class="font-mono text-ink-500">{{ (f.sell ?? 0) * f.count }}</span>
            <button
              class="rounded bg-ink-800 px-2 py-0.5 text-[10px] text-amber-300 hover:bg-ink-700"
              @click="sellOne(f)"
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
