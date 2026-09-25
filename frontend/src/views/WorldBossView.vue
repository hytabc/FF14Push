<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, shallowRef, watch } from 'vue'

import { api } from '@/api'
import { http, toApiError } from '@/api/client'
import BossFigure from '@/components/BossFigure.vue'
import InfoTip from '@/components/InfoTip.vue'
import ItemIcon from '@/components/ItemIcon.vue'
import JobIcon from '@/components/JobIcon.vue'
import Modal from '@/components/Modal.vue'
import { sound } from '@/game/audio'
import { WorldBossSimulator, type WorldBossSnapshot } from '@/game/core/worldboss'
import { useAuthStore } from '@/stores/auth'
import { useGameStore } from '@/stores/game'
import { useToastStore } from '@/stores/toast'
import { jobName, formatNumber, rarityClass, rarityName } from '@/utils/format'
import {
  periodIn,
  respawnIn,
  reviveIn,
  tierProgress,
  weaknessHint,
  type WorldBossLeaderboard,
  type WorldBossLeaderboardEntry,
  type WorldBossReceipt,
  type WorldBossState,
} from '@/game/worldboss'
import type { Hero } from '@/game/types'

const game = useGameStore()
const auth = useAuthStore()
const toast = useToastStore()

/** 本地模拟的上报间隔（毫秒）与单帧最大推进（与地区战斗同一套墙钟预算策略）。 */
const REPORT_MS = 1500
const MAX_FRAME_MS = 400

const uid = computed(() => game.state?.user.id ?? 0)
const state = ref<WorldBossState | null>(null)
const roster = ref<(Hero & { id: number })[]>([])
const selected = ref<number[]>([])
const receipt = ref<WorldBossReceipt | null>(null)
const detail = ref<WorldBossLeaderboardEntry | null>(null)
const error = ref('')
const notice = ref('')
const busy = ref(false)
/** 首次载入骨架屏。 */
const loading = ref(true)
/** 秒级节拍（倒计时）与 0.1s 节拍（战斗面板刷新，避免每帧重渲染）。 */
const tick = ref(0)
const frame = ref(0)

/**
 * 战斗运算下放客户端：本地跑与后端同一套引擎（`game/core/worldboss.ts`），
 * 按窗口上报伤害增量；服务端用理论模型夹取并结算共享血量 / 贡献 / 奖励。
 */
const sim = shallowRef<WorldBossSimulator | null>(null)

/** 榜单展开：各英雄占比条的颜色（按名次轮换）。 */
const HERO_COLORS = ['bg-rose-400', 'bg-amber-400', 'bg-emerald-400', 'bg-sky-400', 'bg-violet-400', 'bg-orange-400', 'bg-teal-400', 'bg-pink-400']

let socket: WebSocket | undefined
let interval: ReturnType<typeof setInterval> | undefined
let clock: ReturnType<typeof setInterval> | undefined
let uiTimer: ReturnType<typeof setInterval> | undefined
let rafId = 0
let disposed = false
let connecting = false
let polling = false
let reporting = false
let reportSeq = 0
let reportAccum = 0
let lastWallMs = 0
let simBudgetMs = 0
/** 已播放音效的最大事件序号（只对新增事件发声）。 */
let playedEventSeq = 0
/** 已上报的各英雄累计伤害：用于计算增量。 */
const reportedHeroDamage = new Map<number, number>()

/** 对本地模拟新增的事件播放音效（BOSS 技能 / 死亡 / 复活 / 阶段）。 */
function playSimSounds(): void {
  const events = sim.value?.events ?? []
  for (const event of events) {
    if (event.seq <= playedEventSeq) continue
    playedEventSeq = event.seq
    if (event.kind === 'bossSkill') sound.play('wb.bossSkill')
    else if (event.kind === 'death') sound.play('wb.death')
    else if (event.kind === 'revive') sound.play('wb.revive')
    else if (event.kind === 'phase') sound.play('wb.phase')
  }
}

const boss = computed(() => state.value?.boss ?? null)
const rules = computed(() => state.value?.rules ?? { heroSlots: 8, levelRequirement: 80, fullPowerLevel: 100, weaknessFloor: 0.1 })
const leaderboard = computed<WorldBossLeaderboard | null>(() => state.value?.leaderboard ?? null)
/** BOSS 存活时才推进本地模拟（休整期间战斗暂停，与全局状态一致）。 */
const bossAlive = computed(() => (boss.value?.status ?? 'alive') === 'alive')
/** 全局剩余血量占比：驱动本地模拟的阶段（防御越厚、技能越强）。 */
const bossHpRatio = computed(() => {
  const b = boss.value
  return b && b.maxHp > 0 ? Math.max(0, Math.min(1, b.hp / b.maxHp)) : 1
})

/**
 * 战斗面板数据：由**本地模拟**提供（服务端不再推进会话），沿用原会话视图的字段形状，
 * 因此模板无需改动。依赖 0.1s 的 `frame` 而非每帧，避免整页 60fps 重渲染。
 */
const session = computed(() => {
  void frame.value
  const current = sim.value
  if (!current) return null
  return {
    status: current.state.status,
    elapsedMs: current.elapsedMs,
    damageDealt: current.damageDealt,
    eventSequence: current.state.eventSequence,
    events: current.events,
    heroes: current.heroes.map((hero) => ({
      slot: hero.slot,
      heroId: hero.snapshot.heroId,
      name: hero.snapshot.name,
      jobId: hero.snapshot.jobId,
      level: hero.snapshot.level,
      levelMultiplier: hero.levelMultiplier,
      maxHp: hero.snapshot.stats.max_hp,
      hp: hero.hp,
      mp: hero.mp,
      maxMp: hero.snapshot.stats.max_mp,
      deadUntil: hero.deadUntil,
      damage: Math.round(hero.damage),
      deaths: hero.deaths,
    })),
  }
})

const hpPct = computed(() => {
  const b = boss.value
  return b && b.maxHp > 0 ? Math.max(0, Math.min(100, (b.hp / b.maxHp) * 100)) : 0
})
const eligible = computed(() => roster.value.filter((h) => h.level >= rules.value.levelRequirement))
const bossSkills = computed(() => (session.value?.events ?? []).filter((e) => e.kind === 'bossSkill').slice(-12).reverse())
const respawnLeft = computed(() => {
  void tick.value
  return boss.value ? respawnIn(boss.value.respawnAt, Date.now() / 1000) : 0
})
/** 血条上的阶段分界（P2/P3 进入点）。 */
const phaseMarks = computed(() => (state.value?.phases ?? []).filter((p) => p.minHpRatio > 0))
/** 讨伐周期剩余秒数（每秒随 tick 刷新）。 */
const periodLeft = computed(() => {
  void tick.value
  return boss.value ? periodIn(boss.value.periodEndsAt, Date.now() / 1000) : 0
})
const rewardTiers = computed(() => state.value?.reward.tiers ?? [])
/** 名次加成表（按名次升序，用于规则说明）。 */
const rankBonusList = computed(() => {
  const table = state.value?.reward.rankBonus ?? {}
  return Object.keys(table)
    .map((key) => ({ rank: Number(key), items: table[key] }))
    .sort((a, b) => a.rank - b.rank)
})
/** 我的周期累计伤害（档位只看它，与他人无关）。 */
const myDamage = computed(() => state.value?.myDamage ?? 0)
/** 我的档位进度（进度条与文案同源）。 */
const progress = computed(() => tierProgress(myDamage.value, rewardTiers.value))
/** 榜单首名伤害：行内伤害条按此归一化。 */
const topDamage = computed(() => {
  const entries = leaderboard.value?.entries ?? []
  return entries.length ? Math.max(...entries.map((e) => e.damage)) : 0
})

/** BOSS 关键数值（拆成「标签 + 数值」，不再写成整句）。 */
const bossStats = computed(() => {
  const b = boss.value
  if (!b) return []
  return [
    { label: '攻击力', value: formatNumber(b.attack) },
    { label: '技能间隔', value: `${b.skillIntervalSeconds} 秒` },
    { label: '英雄复活', value: `${b.reviveSeconds} 秒` },
  ]
})

// ---- 版面说明（原本铺在版面上的整段文字，收进「?」说明卡） ----

const phaseInfo = computed(() => {
  const b = boss.value
  if (!b) return { title: '阶段机制', lines: [] as string[] }
  return {
    title: `阶段 P${b.phase} · ${b.phaseName}`,
    lines: [
      `全服剩余血量越低，BOSS 防御越厚、技能越强：`,
      `英雄输出 ×${(1 / (b.defenseMultiplier || 1)).toFixed(2)}（防御 ×${b.defenseMultiplier}）`,
      `BOSS 技能威力 ×${b.skillPotencyMultiplier}（普攻不受影响）`,
      ...(state.value?.phases ?? []).map(
        (p) => `P${p.id} ${p.name}：血量 ≤ ${(p.minHpRatio * 100).toFixed(0)}% → 防御 ×${p.defenseMultiplier} · 技能 ×${p.skillPotencyMultiplier}`,
      ),
    ],
  }
})

const progressInfo = {
  title: '我的本周期进度',
  lines: [
    '档位只看你自己的周期累计伤害，与他人无关：达到阈值即拿对应基础件数（保底）。',
    '名次加成按榜单排名额外发放，仅前 10 名。',
  ],
}

const deployInfo = computed(() => ({
  title: '上阵规则',
  lines: [
    `每周期最多上阵 ${rules.value.heroSlots} 名英雄，需 Lv.${rules.value.levelRequirement} 以上。`,
    `${rules.value.levelRequirement}–${rules.value.fullPowerLevel - 1} 级英雄会被削弱，达到 Lv.${rules.value.fullPowerLevel} 才不受影响。`,
    '周期内 BOSS 可反复讨伐；奖励只看你自己的周期累计伤害，别人打得再快也不影响你的奖励。',
  ],
}))

const leaderboardInfo = computed(() => ({
  title: '本周期伤害榜',
  lines: [
    `周期累计伤害 ≥ ${formatNumber(leaderboard.value?.minDamage ?? 0)} 才能入榜并参与奖励。`,
    '奖励件数 = 档位件数（按周期累计伤害）+ 名次加成（仅前 10 名）。',
    '点击任一行可查看该玩家各英雄的伤害与占比。',
  ],
}))

// ---- 无障碍播报：阶段 / 存亡变化（倒计时本身不进 live region，避免每秒刷屏） ----
const announcement = ref('')
const bossStatusKey = computed(() => (boss.value ? `${boss.value.status}:${boss.value.phase}` : ''))
watch(
  bossStatusKey,
  (next, prev) => {
    const b = boss.value
    if (!prev || !b || next === prev) return
    announcement.value =
      b.status === 'alive' ? `BOSS 进入第 ${b.phase} 阶段 · ${b.phaseName}` : 'BOSS 已被击破，进入休整'
  },
  { immediate: true },
)

/** 秒数 → 人类可读时长（用于周期倒计时）。 */
function durationText(seconds: number): string {
  const total = Math.max(0, Math.floor(seconds))
  const hours = Math.floor(total / 3600)
  const minutes = Math.floor((total % 3600) / 60)
  if (hours) return `${hours} 小时 ${minutes} 分`
  if (minutes) return `${minutes} 分 ${total % 60} 秒`
  return `${total} 秒`
}

/** 英雄血量占比（0-100）。 */
function hpPctOf(hero: { hp: number; maxHp: number }): number {
  return hero.maxHp > 0 ? Math.max(0, Math.min(100, (hero.hp / hero.maxHp) * 100)) : 0
}

/** 该英雄本场输出占全队输出的比例（0-100）。 */
function heroShare(damage: number): number {
  const total = session.value?.damageDealt ?? 0
  return total > 0 ? Math.max(0, Math.min(100, (damage / total) * 100)) : 0
}

/** 榜单行伤害条宽度（相对首名归一化，最少 2% 以保证可见）。 */
function damageShare(damage: number): number {
  return topDamage.value > 0 ? Math.max(2, Math.min(100, (damage / topDamage.value) * 100)) : 0
}

/** 上阵顺序（1-based；未选中为 0）。 */
function selectedIndex(heroId: number): number {
  return selected.value.indexOf(heroId) + 1
}

/** 本地模拟的上报：把各英雄累计伤害的增量提交给服务端（服务端按上限夹取）。 */
async function reportDamage(): Promise<void> {
  const current = sim.value
  if (!current || reporting) return
  const perHero: Array<{ heroId: number; damage: number }> = []
  const cumulative = new Map<number, number>()
  for (const hero of current.heroes) {
    const heroId = hero.snapshot.heroId
    const total = Math.round(hero.damage)
    cumulative.set(heroId, total)
    const delta = total - (reportedHeroDamage.get(heroId) ?? 0)
    if (delta > 0) perHero.push({ heroId, damage: delta })
  }
  const damage = perHero.reduce((sum, entry) => sum + entry.damage, 0)
  if (damage <= 0) return

  reporting = true
  reportSeq += 1
  try {
    const res = await api.worldbossReport({ reportSeq, damage, perHero })
    for (const [heroId, total] of cumulative) reportedHeroDamage.set(heroId, total)
    if (state.value) {
      state.value.boss = res.boss
      state.value.myDamage = res.myDamage
    }
    current.setBossHpRatio(bossHpRatio.value)
  } catch (e) {
    const err = toApiError(e)
    // 会话已结束（服务端结束了会话 / 换轮）：本地静默停战，不重试不弹窗。
    if (err.status === 404) {
      stopSim()
      sim.value = null
      return
    }
    // 被服务端拒绝（超出上限）或限速：停止推进，避免继续产生无法结算的伤害。
    if (err.status === 422 || err.status === 429) {
      notice.value = '已达服务端结算上限，战斗已暂停。'
      stopSim()
      return
    }
    error.value = err.message
  } finally {
    reporting = false
  }
}

/** 本地战斗循环：墙钟预算推进模拟（防加速），按窗口上报伤害。 */
function simStep(): void {
  const wallNow = Date.now()
  const wallDelta = Math.min(MAX_FRAME_MS, Math.max(0, wallNow - lastWallMs))
  lastWallMs = wallNow
  simBudgetMs = Math.min(MAX_FRAME_MS, simBudgetMs + wallDelta)
  const dtMs = Math.min(MAX_FRAME_MS, simBudgetMs)
  simBudgetMs -= dtMs

  const current = sim.value
  if (current && bossAlive.value) {
    current.setBossHpRatio(bossHpRatio.value)
    current.tick(dtMs)
    reportAccum += dtMs
    if (reportAccum >= REPORT_MS) {
      reportAccum = 0
      void reportDamage()
    }
  }
  rafId = requestAnimationFrame(simStep)
}

function startSim(): void {
  if (rafId) return
  lastWallMs = Date.now()
  simBudgetMs = 0
  reportAccum = 0
  rafId = requestAnimationFrame(simStep)
}

function stopSim(): void {
  if (rafId) cancelAnimationFrame(rafId)
  rafId = 0
}

/** 用服务端下发的英雄快照重建本地模拟（进入战场 / 刷新页面恢复）。 */
function buildSim(party: WorldBossSnapshot[] | null | undefined): void {
  stopSim()
  reportedHeroDamage.clear()
  reportSeq = 0
  playedEventSeq = 0
  if (!party || !party.length) {
    sim.value = null
    return
  }
  sim.value = new WorldBossSimulator(party, bossHpRatio.value)
  startSim()
}

async function act(fn: () => Promise<unknown>) {
  busy.value = true
  error.value = ''
  notice.value = ''
  try {
    await fn()
  } catch (e) {
    error.value = toApiError(e).message
  } finally {
    busy.value = false
  }
}

async function load() {
  const [st, ro] = await Promise.all([api.worldbossState(), http.get<{ heroes: (Hero & { id: number })[] }>('/heroes')])
  state.value = st
  roster.value = ro.data.heroes
  // 刷新页面后按服务端下发的快照恢复本地模拟（无会话则 party 为空）。
  buildSim(st.party)
}

async function connect() {
  if (connecting || disposed || (socket && socket.readyState < 2) || !auth.isLoggedIn) return
  connecting = true
  try {
    const { ticket } = await api.worldbossTicket()
    if (disposed) return
    const url = new URL(`${http.defaults.baseURL}/worldboss/ws`, location.origin)
    url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:'
    url.searchParams.set('ticket', ticket)
    socket = new WebSocket(url)
    socket.onmessage = (event) => {
      const msg = JSON.parse(event.data) as {
        type: string
        sequence: number
        boss: WorldBossState['boss']
        leaderboard?: WorldBossLeaderboard
      }
      if (!state.value) return
      // 战斗由本地模拟驱动：WS 只用于同步全局 BOSS 状态与榜单。
      if (msg.boss) state.value.boss = msg.boss
      state.value.sequence = msg.sequence
      if (msg.leaderboard) state.value.leaderboard = msg.leaderboard
    }
    socket.onerror = () => {
      notice.value = '连接恢复中，正在通过快照同步。'
    }
  } catch (e) {
    error.value = toApiError(e).message
  } finally {
    connecting = false
  }
}

function toggle(heroId: number) {
  const at = selected.value.indexOf(heroId)
  if (at >= 0) selected.value.splice(at, 1)
  else if (selected.value.length < rules.value.heroSlots) selected.value.push(heroId)
  else notice.value = `最多上阵 ${rules.value.heroSlots} 名英雄`
}

async function enter() {
  await act(async () => {
    if (!selected.value.length) throw new Error('请选择至少 1 名英雄')
    await game.stopBattle(true)
    await game.stopRaid(true)
    state.value = await api.worldbossEnter([...selected.value])
    receipt.value = null
    buildSim(state.value.party)
    await connect()
  })
}

async function leave() {
  await act(async () => {
    stopSim()
    sim.value = null
    await api.worldbossLeave()
    socket?.close()
    socket = undefined
    await load()
    await connect()
  })
}

async function claim() {
  await act(async () => {
    if (!state.value?.unclaimedCycle) return
    receipt.value = await api.worldbossClaim(state.value.unclaimedCycle)
    await game.loadState()
    toast.push(`获得 ${receipt.value.items} 件绝境龙神装备`, 'loot')
    sound.play('ui.loot')
    await load()
  })
}

async function heartbeat() {
  if (disposed || polling || !auth.isLoggedIn) return
  polling = true
  try {
    await api.worldbossHeartbeat()
    // 状态已由 WebSocket 快照驱动：仅在 WS 未连通时用快照接口兜底。
    // 注意只同步全局状态，**不重建本地模拟**，避免打断进行中的战斗。
    const live = socket !== undefined && socket.readyState === WebSocket.OPEN
    if (!live) {
      const fresh = await api.worldbossState()
      if (state.value) {
        state.value.boss = fresh.boss
        state.value.leaderboard = fresh.leaderboard
        state.value.myDamage = fresh.myDamage
        state.value.unclaimedCycle = fresh.unclaimedCycle
        state.value.sequence = fresh.sequence
      }
    }
    await connect()
  } catch (e) {
    error.value = toApiError(e).message
  } finally {
    polling = false
  }
}

onMounted(() => {
  void act(async () => {
    await game.loadState()
    await load()
    await connect()
  }).finally(() => {
    loading.value = false
  })
  interval = setInterval(() => void heartbeat(), 5000)
  clock = setInterval(() => (tick.value += 1), 1000)
  // 0.1s 节拍：驱动战斗面板刷新（不随每帧重渲染）。
  uiTimer = setInterval(() => {
    frame.value += 1
    playSimSounds()
  }, 100)
})

onUnmounted(() => {
  disposed = true
  if (interval) clearInterval(interval)
  if (clock) clearInterval(clock)
  if (uiTimer) clearInterval(uiTimer)
  stopSim()
  socket?.close()
})
</script>

<template>
  <main class="space-y-6">
    <p v-if="error" role="alert" class="rounded-lg bg-rose-500/15 px-4 py-3 text-sm text-rose-200">{{ error }}</p>
    <p v-if="notice" role="status" class="rounded-lg bg-amber-500/15 px-4 py-3 text-sm text-amber-200">{{ notice }}</p>

    <!-- 首次载入：骨架屏（避免空壳数字） -->
    <template v-if="loading && !state">
      <section class="card h-48 animate-pulse p-6">
        <div class="h-6 w-48 rounded bg-ink-700"></div>
        <div class="mt-4 h-3 w-2/3 rounded bg-ink-700"></div>
        <div class="mt-8 h-6 w-full rounded bg-ink-700"></div>
      </section>
      <div class="grid gap-6 lg:grid-cols-[1.5fr_1fr]">
        <div class="space-y-6">
          <section class="card h-36 animate-pulse"></section>
          <section class="card h-52 animate-pulse"></section>
        </div>
        <section class="card h-72 animate-pulse"></section>
      </div>
    </template>

    <template v-else>
      <!-- ① BOSS 主视觉带 -->
      <section class="card relative overflow-hidden">
        <div class="pointer-events-none absolute -bottom-16 -right-12 h-80 w-80 rounded-full bg-amber-500/15 blur-3xl"></div>

        <div class="relative flex flex-col gap-5 p-6 sm:flex-row sm:items-end sm:gap-6">
          <div class="min-w-0 flex-1 space-y-5">
            <div class="flex flex-wrap items-start justify-between gap-3">
              <div class="min-w-0">
                <div class="flex flex-wrap items-center gap-2">
                  <h1 class="text-2xl font-bold text-amber-200">{{ boss?.name ?? '世界BOSS' }}</h1>
                  <span
                    v-if="boss"
                    class="rounded px-2 py-0.5 text-xs font-medium"
                    :class="boss.phase >= 3 ? 'bg-rose-500/25 text-rose-100' : boss.phase === 2 ? 'bg-amber-500/25 text-amber-100' : 'bg-ink-700 text-white'"
                  >
                    P{{ boss.phase }} · {{ boss.phaseName }}
                  </span>
                  <InfoTip :title="phaseInfo.title">
                    <p v-for="(line, i) in phaseInfo.lines" :key="i" class="font-mono">{{ line }}</p>
                  </InfoTip>
                </div>
                <p v-if="boss" class="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-ink-400">
                  <span>第 {{ boss.cycle }} 周期</span>
                  <span>本周期已讨伐 {{ boss.kills }} 次</span>
                  <span :class="boss.status === 'alive' ? 'text-emerald-300' : 'text-amber-300'">
                    {{ boss.status === 'alive' ? '讨伐中' : `休整中 · ${respawnLeft}s 后重生` }}
                  </span>
                </p>
              </div>
              <div class="text-right">
                <p class="text-xs text-ink-400">周期剩余</p>
                <p class="font-mono text-lg text-amber-200">{{ durationText(periodLeft) }}</p>
              </div>
            </div>

            <!-- 共享血量条：分段 + 阶段刻度 -->
            <div class="space-y-1.5">
              <div class="flex items-end justify-between gap-2">
                <span class="text-xs text-ink-400">全服共享血量</span>
                <span class="font-mono text-sm text-ink-200">
                  {{ formatNumber(boss?.hp ?? 0) }}
                  <span class="text-ink-400">/ {{ formatNumber(boss?.maxHp ?? 0) }}</span>
                  <span class="ml-2 text-rose-200">{{ hpPct.toFixed(1) }}%</span>
                </span>
              </div>
              <div class="relative pb-4">
                <div
                  class="relative h-6 overflow-hidden rounded-full bg-ink-950/80 ring-1 ring-ink-700"
                  role="progressbar"
                  aria-label="全服共享血量"
                  :aria-valuemin="0"
                  :aria-valuemax="boss?.maxHp ?? 0"
                  :aria-valuenow="boss?.hp ?? 0"
                >
                  <div
                    class="h-full rounded-full bg-gradient-to-r from-rose-700 via-rose-500 to-rose-400 shadow-lg shadow-rose-500/30 transition-all duration-500"
                    :style="{ width: `${hpPct}%` }"
                  />
                  <span
                    v-for="p in phaseMarks"
                    :key="p.id"
                    class="absolute inset-y-0 w-px bg-white/50"
                    :style="{ left: `${p.minHpRatio * 100}%` }"
                  />
                </div>
                <span
                  v-for="p in phaseMarks"
                  :key="`tick-${p.id}`"
                  class="absolute bottom-0 -translate-x-1/2 font-mono text-[10px] text-ink-400"
                  :style="{ left: `${p.minHpRatio * 100}%` }"
                >
                  P{{ p.id + 1 }}
                </span>
              </div>
            </div>

            <dl class="grid grid-cols-2 gap-3 border-t border-ink-700/60 pt-4 sm:grid-cols-4">
              <div v-for="s in bossStats" :key="s.label">
                <dt class="text-[11px] text-ink-400">{{ s.label }}</dt>
                <dd class="font-mono text-sm text-white">{{ s.value }}</dd>
              </div>
              <div>
                <dt class="text-[11px] text-ink-400">本周期讨伐</dt>
                <dd class="font-mono text-sm text-white">{{ boss?.kills ?? 0 }} 次</dd>
              </div>
            </dl>

            <p v-if="boss && boss.status !== 'alive'" class="rounded-lg bg-amber-500/10 px-3 py-2 text-xs text-amber-200">
              BOSS 正在重整旗鼓，{{ respawnLeft }} 秒后重生；此刻进场后会自动开战。
            </p>
          </div>

          <div class="hidden h-40 shrink-0 sm:block lg:h-56">
            <BossFigure
              :boss-key="boss?.key"
              :name="boss?.name ?? '世界BOSS'"
              class="brightness-110 contrast-105 drop-shadow-[0_10px_28px_rgba(0,0,0,0.65)]"
            />
          </div>
        </div>
      </section>
      <p role="status" aria-live="polite" class="sr-only">{{ announcement }}</p>

      <div class="grid gap-6 lg:grid-cols-[1.5fr_1fr]">
        <div class="space-y-6">
          <!-- ② 我的周期进度 -->
          <section class="card space-y-4 p-6">
            <div class="flex flex-wrap items-center justify-between gap-2">
              <div class="flex items-center gap-1">
                <h2 class="text-sm font-semibold text-white">我的本周期进度</h2>
                <InfoTip :title="progressInfo.title">
                  <p v-for="(line, i) in progressInfo.lines" :key="i">{{ line }}</p>
                </InfoTip>
              </div>
              <span class="text-xs text-ink-400">周期剩余 {{ durationText(periodLeft) }}</span>
            </div>

            <div class="flex flex-wrap items-end justify-between gap-3">
              <p class="text-sm text-ink-200">
                累计伤害 <span class="font-mono text-xl text-amber-200">{{ formatNumber(myDamage) }}</span>
              </p>
              <span v-if="progress.current" class="rounded bg-amber-500/20 px-2 py-1 text-xs font-medium text-amber-100">
                当前档位 {{ progress.current.items }} 件
              </span>
              <span v-else class="rounded bg-ink-700 px-2 py-1 text-xs text-ink-400">
                未达保底 {{ formatNumber(leaderboard?.minDamage ?? 0) }}
              </span>
            </div>

            <div class="space-y-2">
              <div
                class="h-3 overflow-hidden rounded-full bg-ink-950/70 ring-1 ring-ink-700"
                role="progressbar"
                aria-label="距下一档进度"
                :aria-valuemin="0"
                :aria-valuemax="100"
                :aria-valuenow="Math.round(progress.fraction * 100)"
              >
                <div
                  class="h-full rounded-full bg-gradient-to-r from-amber-600 to-amber-400 transition-all duration-500"
                  :style="{ width: `${progress.fraction * 100}%` }"
                />
              </div>
              <div class="flex justify-between gap-2 font-mono text-[11px] text-ink-400">
                <span>{{ formatNumber(progress.floor) }}</span>
                <span v-if="progress.next">距下一档 {{ formatNumber(progress.remaining) }} → {{ formatNumber(progress.next.minDamage) }}</span>
                <span v-else class="text-emerald-300">已达最高档位</span>
              </div>
            </div>

            <div class="flex flex-wrap gap-1.5">
              <span
                v-for="(t, i) in rewardTiers"
                :key="t.minDamage"
                class="rounded px-2 py-0.5 text-[11px]"
                :class="myDamage >= t.minDamage ? 'bg-amber-500/20 text-amber-100' : 'bg-ink-800 text-ink-400'"
              >
                第 {{ i + 1 }} 档 {{ formatNumber(t.minDamage) }} · {{ t.items }} 件
              </span>
            </div>
          </section>

          <!-- ③ 行动区：上阵 / 战斗中 -->
          <section v-if="!session" class="card space-y-4 p-6">
            <div class="flex flex-wrap items-center justify-between gap-3">
              <div class="flex flex-wrap items-center gap-2">
                <h2 class="text-sm font-semibold text-white">上阵英雄</h2>
                <InfoTip :title="deployInfo.title">
                  <p v-for="(line, i) in deployInfo.lines" :key="i">{{ line }}</p>
                </InfoTip>
                <span class="font-mono text-xs text-ink-400">{{ selected.length }} / {{ rules.heroSlots }}</span>
              </div>
              <button
                class="min-h-11 rounded-lg bg-amber-500 px-4 text-sm font-semibold text-ink-950 transition hover:bg-amber-400 focus-visible:ring-2 focus-visible:ring-amber-300 disabled:opacity-40"
                :disabled="busy || !selected.length"
                @click="enter"
              >
                {{ busy ? '进入中…' : `进入战场（${selected.length}）` }}
              </button>
            </div>

            <p v-if="!eligible.length" class="text-sm text-ink-400">
              没有符合条件的英雄（需 Lv.{{ rules.levelRequirement }} 以上）。可前往
              <RouterLink to="/roster" class="text-amber-300 underline decoration-dotted">名册</RouterLink> 或
              <RouterLink to="/tavern" class="text-amber-300 underline decoration-dotted">酒馆</RouterLink> 培养。
            </p>
            <div v-else class="grid gap-2 sm:grid-cols-2 xl:grid-cols-3">
              <button
                v-for="h in eligible"
                :key="h.id"
                class="relative flex min-h-14 items-center gap-3 rounded-lg border px-3 py-2 text-left text-sm transition focus-visible:ring-2 focus-visible:ring-amber-300 disabled:opacity-60"
                :class="selected.includes(h.id) ? 'border-amber-400 bg-amber-500/10' : 'border-ink-700 hover:border-ink-400'"
                :disabled="busy"
                :aria-pressed="selected.includes(h.id)"
                @click="toggle(h.id)"
              >
                <JobIcon :job-id="h.jobId" :size="24" />
                <span class="min-w-0 flex-1">
                  <span class="block truncate text-white">{{ h.name }} <span class="text-ink-400">Lv.{{ h.level }}</span></span>
                  <span class="block text-xs text-ink-400">{{ jobName(h.jobId) }} · {{ weaknessHint(h.level, rules, true) }}</span>
                </span>
                <span
                  v-if="selectedIndex(h.id)"
                  class="absolute -left-1 -top-1 grid h-5 w-5 place-items-center rounded-full bg-amber-400 text-[11px] font-bold text-ink-950"
                >
                  {{ selectedIndex(h.id) }}
                </span>
              </button>
            </div>
          </section>

          <template v-else>
            <section class="card space-y-4 p-6">
              <div class="flex flex-wrap items-center justify-between gap-3">
                <h2 class="text-sm font-semibold text-white">战斗进行中</h2>
                <button
                  class="min-h-9 rounded-lg border border-ink-600 px-3 text-sm text-ink-200 transition hover:border-ink-400 focus-visible:ring-2 focus-visible:ring-amber-300 disabled:opacity-40"
                  :disabled="busy"
                  @click="leave"
                >
                  撤离
                </button>
              </div>
              <dl class="grid grid-cols-3 gap-3">
                <div>
                  <dt class="text-[11px] text-ink-400">已战斗</dt>
                  <dd class="font-mono text-sm text-white">{{ (session.elapsedMs / 1000).toFixed(0) }} 秒</dd>
                </div>
                <div>
                  <dt class="text-[11px] text-ink-400">本场输出</dt>
                  <dd class="font-mono text-sm text-white">{{ formatNumber(session.damageDealt) }}</dd>
                </div>
                <div>
                  <dt class="text-[11px] text-ink-400">本轮累计</dt>
                  <dd class="font-mono text-sm text-amber-200">{{ formatNumber(myDamage) }}</dd>
                </div>
              </dl>
            </section>

            <div class="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
              <article v-for="h in session.heroes" :key="h.slot" class="card space-y-2 p-3 text-sm">
                <div class="flex items-center gap-2">
                  <JobIcon :job-id="h.jobId" :size="22" />
                  <span class="min-w-0 flex-1 truncate text-white">{{ h.name }}</span>
                  <span class="text-xs text-ink-400">Lv.{{ h.level }}</span>
                </div>
                <div class="h-2 overflow-hidden rounded-full bg-ink-800">
                  <div
                    class="h-full transition-all"
                    :class="h.hp > 0 ? 'bg-emerald-500' : 'bg-ink-600'"
                    :style="{ width: `${hpPctOf(h)}%` }"
                  />
                </div>
                <div class="flex justify-between text-xs text-ink-400">
                  <span>HP {{ formatNumber(Math.round(h.hp)) }}</span>
                  <span v-if="h.hp <= 0" class="text-rose-300">复活 {{ reviveIn(h.deadUntil, session.elapsedMs) }}s</span>
                  <span v-else>MP {{ Math.round(h.mp) }}</span>
                </div>
                <div class="flex justify-between text-xs text-ink-400">
                  <span>输出 {{ formatNumber(h.damage) }}</span>
                  <span>倒下 {{ h.deaths }}</span>
                </div>
                <div class="h-1 overflow-hidden rounded-full bg-ink-800" :title="`本场输出占比 ${heroShare(h.damage).toFixed(1)}%`">
                  <div class="h-full bg-amber-400/70" :style="{ width: `${heroShare(h.damage)}%` }" />
                </div>
              </article>
            </div>

            <section class="card space-y-2 p-6">
              <h2 class="text-sm font-semibold text-white">BOSS 技能</h2>
              <p v-if="!bossSkills.length" class="text-sm text-ink-400">尚未释放技能。</p>
              <ul class="space-y-1 text-sm">
                <li v-for="e in bossSkills" :key="e.seq" class="flex gap-2 text-rose-200">
                  <span class="shrink-0 font-mono text-xs text-ink-400">{{ (e.at / 1000).toFixed(1) }}s</span>
                  <span class="min-w-0 flex-1">{{ e.text }}</span>
                </li>
              </ul>
            </section>
          </template>

          <!-- ④ 结算领取 -->
          <section v-if="state?.unclaimedCycle" class="space-y-4 rounded-xl border border-amber-500/50 bg-amber-500/10 p-6">
            <div class="flex flex-wrap items-center justify-between gap-3">
              <div class="min-w-0">
                <h2 class="text-sm font-semibold text-amber-100">第 {{ state.unclaimedCycle }} 周期已结算</h2>
                <p class="mt-0.5 text-xs text-amber-200/80">
                  周期累计伤害 {{ formatNumber(myDamage) }}，可按「档位 + 名次加成」领取「绝境龙神」装备。
                </p>
              </div>
              <button
                class="min-h-11 rounded-lg bg-amber-500 px-4 text-sm font-semibold text-ink-950 transition hover:bg-amber-400 focus-visible:ring-2 focus-visible:ring-amber-300 disabled:opacity-40"
                :disabled="busy || !!receipt"
                @click="claim"
              >
                {{ receipt ? '已领取' : '领取奖励' }}
              </button>
            </div>
            <template v-if="receipt">
              <p class="text-sm text-emerald-200">
                第 {{ receipt.rank }} 名 · 档位 {{ receipt.tierItems }} 件 + 名次加成 {{ receipt.rankBonus }} 件 = {{ receipt.items }} 件
              </p>
              <ul class="grid gap-1.5 sm:grid-cols-2">
                <li v-for="it in receipt.grants.items" :key="it.id" class="flex items-center gap-2 text-xs">
                  <ItemIcon :base-id="it.baseId" :rarity="it.rarity" :size="20" />
                  <span class="min-w-0 flex-1 truncate" :class="rarityClass(it.rarity)">{{ it.name }}</span>
                  <span class="shrink-0 text-ink-400">{{ rarityName(it.rarity) }}</span>
                </li>
              </ul>
            </template>
          </section>
        </div>

        <!-- ⑤ 侧栏：伤害榜 + 奖励规则 -->
        <aside class="space-y-6">
          <section class="card space-y-3 p-6">
            <div class="flex flex-wrap items-center justify-between gap-2">
              <div class="flex items-center gap-1">
                <h2 class="text-sm font-semibold text-white">本周期伤害榜</h2>
                <InfoTip :title="leaderboardInfo.title">
                  <p v-for="(line, i) in leaderboardInfo.lines" :key="i">{{ line }}</p>
                </InfoTip>
              </div>
              <span class="text-xs text-ink-400">第 {{ leaderboard?.cycle ?? boss?.cycle ?? 1 }} 周期</span>
            </div>

            <ol class="space-y-1">
              <li v-for="e in leaderboard?.entries ?? []" :key="e.userId">
                <button
                  type="button"
                  class="relative flex min-h-11 w-full items-center gap-2 overflow-hidden rounded-lg px-2 text-left text-sm transition hover:bg-ink-700/50 focus-visible:ring-2 focus-visible:ring-amber-300"
                  :class="e.userId === uid ? 'bg-amber-500/15' : ''"
                  aria-haspopup="dialog"
                  @click="detail = e"
                >
                  <span
                    class="absolute inset-y-0 left-0 bg-gradient-to-r from-amber-400/25 to-amber-400/5"
                    :style="{ width: `${damageShare(e.damage)}%` }"
                  />
                  <span
                    class="relative w-6 shrink-0 text-center font-mono"
                    :class="e.rank === 1 ? 'text-amber-300' : e.rank === 2 ? 'text-ink-200' : e.rank === 3 ? 'text-orange-300' : 'text-ink-400'"
                  >
                    {{ e.rank }}
                  </span>
                  <span class="relative min-w-0 flex-1 truncate text-ink-200">
                    {{ e.nickname }}<span class="text-ink-400">#{{ e.username }}</span>
                  </span>
                  <span class="relative shrink-0 font-mono text-xs text-ink-200">{{ formatNumber(e.damage) }}</span>
                  <span class="relative w-10 shrink-0 text-right text-xs text-amber-300">×{{ e.items }}</span>
                  <span class="relative shrink-0 text-ink-400">›</span>
                </button>
              </li>
              <li v-if="!(leaderboard?.entries ?? []).length" class="px-2 py-3 text-ink-400">本周期还没有人达标。</li>
            </ol>

            <div class="border-t border-ink-700 pt-3 text-sm">
              <div v-if="leaderboard?.me" class="flex items-center justify-between gap-2 text-amber-200">
                <span class="min-w-0">
                  我的排名：第 {{ leaderboard.me.rank }} 名 · {{ formatNumber(leaderboard.me.damage) }} · ×{{ leaderboard.me.items }}
                </span>
                <button
                  type="button"
                  class="shrink-0 text-xs underline decoration-dotted focus-visible:ring-2 focus-visible:ring-amber-300"
                  @click="detail = leaderboard!.me"
                >
                  分英雄
                </button>
              </div>
              <p v-else class="text-xs text-ink-400">
                我本周期累计 {{ formatNumber(myDamage) }}，未达入榜门槛 {{ formatNumber(leaderboard?.minDamage ?? 0) }}。
              </p>
            </div>
          </section>

          <details class="card p-6 text-xs text-ink-200">
            <summary class="cursor-pointer text-sm font-semibold text-white">奖励规则</summary>
            <div class="mt-3 space-y-3">
              <p>
                按「讨伐周期」结算（每 {{ durationText(boss?.periodSeconds ?? 0) }} 一轮）：周期内 BOSS 可反复击杀，
                奖励只看你自己的周期累计伤害，别人打得再快也不影响你的奖励。
              </p>
              <div>
                <p class="mb-1 font-medium text-ink-200">档位（周期累计伤害）</p>
                <table class="w-full text-left">
                  <thead>
                    <tr class="text-ink-400">
                      <th class="py-0.5 font-normal">档位</th>
                      <th class="py-0.5 font-normal">累计伤害 ≥</th>
                      <th class="py-0.5 text-right font-normal">件数</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr v-for="(t, i) in rewardTiers" :key="t.minDamage" class="border-t border-ink-800">
                      <td class="py-1">第 {{ i + 1 }} 档</td>
                      <td class="py-1 font-mono">{{ formatNumber(t.minDamage) }}</td>
                      <td class="py-1 text-right">{{ t.items }}</td>
                    </tr>
                  </tbody>
                </table>
              </div>
              <div>
                <p class="mb-1 font-medium text-ink-200">名次加成（仅前 10 名）</p>
                <p class="flex flex-wrap gap-x-2 gap-y-0.5">
                  <span v-for="row in rankBonusList" :key="row.rank">第 {{ row.rank }} 名 +{{ row.items }}</span>
                </p>
              </div>
              <p>「绝境龙神」固定红色品质 / 100 级，仅世界BOSS 掉落；可重造 / 附魔但代价远高于其他装备。</p>
            </div>
          </details>
        </aside>
      </div>
    </template>

    <!-- 榜单展开：单玩家分英雄伤害与占比 -->
    <Modal
      :open="!!detail"
      :title="detail ? `第 ${detail.rank} 名 · ${detail.nickname}#${detail.username}` : ''"
      @close="detail = null"
    >
      <div v-if="detail" class="space-y-4 text-sm">
        <p class="text-ink-200">
          本周期累计伤害 <span class="font-mono text-amber-200">{{ formatNumber(detail.damage) }}</span>
          · 预计奖励 ×{{ detail.items }}（档位 {{ detail.tierItems }} + 名次加成 {{ detail.rankBonus }}）
        </p>

        <div class="flex h-3 w-full overflow-hidden rounded bg-ink-800">
          <span
            v-for="(h, i) in detail.heroes"
            :key="h.heroId"
            class="h-full"
            :class="HERO_COLORS[i % HERO_COLORS.length]"
            :style="{ width: `${h.pct}%` }"
          />
        </div>

        <ul class="space-y-2">
          <li v-for="(h, i) in detail.heroes" :key="h.heroId" class="flex items-center gap-2">
            <span class="h-2.5 w-2.5 shrink-0 rounded-sm" :class="HERO_COLORS[i % HERO_COLORS.length]" />
            <JobIcon :job-id="h.jobId" :size="18" />
            <span class="min-w-0 flex-1 truncate">
              {{ h.name }} <span class="text-ink-400">Lv.{{ h.level }} · {{ jobName(h.jobId) }}</span>
            </span>
            <span class="font-mono text-xs text-ink-200">{{ formatNumber(h.damage) }}</span>
            <span class="w-14 shrink-0 text-right font-mono text-xs text-amber-300">{{ h.pct.toFixed(1) }}%</span>
          </li>
          <li v-if="!detail.heroes.length" class="text-ink-400">暂无分英雄数据（可能在本轮较早版本入场）。</li>
        </ul>
      </div>
    </Modal>
  </main>
</template>
