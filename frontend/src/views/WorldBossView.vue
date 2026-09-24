<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'

import { api } from '@/api'
import { http, toApiError } from '@/api/client'
import JobIcon from '@/components/JobIcon.vue'
import Modal from '@/components/Modal.vue'
import { sound } from '@/game/audio'
import { useAuthStore } from '@/stores/auth'
import { useGameStore } from '@/stores/game'
import { useToastStore } from '@/stores/toast'
import { jobName, formatNumber } from '@/utils/format'
import {
  mergeEvents,
  nextRewardTier,
  periodIn,
  respawnIn,
  rewardTier,
  reviveIn,
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

const uid = computed(() => game.state?.user.id ?? 0)
const state = ref<WorldBossState | null>(null)
const roster = ref<(Hero & { id: number })[]>([])
const selected = ref<number[]>([])
const receipt = ref<WorldBossReceipt | null>(null)
const detail = ref<WorldBossLeaderboardEntry | null>(null)
const error = ref('')
const notice = ref('')
const busy = ref(false)
const tick = ref(0)

/** 榜单展开：各英雄占比条的颜色（按名次轮换）。 */
const HERO_COLORS = ['bg-rose-400', 'bg-amber-400', 'bg-emerald-400', 'bg-sky-400', 'bg-violet-400', 'bg-orange-400', 'bg-teal-400', 'bg-pink-400']

let socket: WebSocket | undefined
let interval: ReturnType<typeof setInterval> | undefined
let clock: ReturnType<typeof setInterval> | undefined
let disposed = false
let connecting = false
let polling = false
/** 已播放过音效的最大事件序号：只对增量事件发声，避免快照重复触发。 */
let lastEventSeq = 0

/** 世界BOSS 由服务端权威推进：对新增事件（BOSS 技能 / 死亡 / 复活 / 阶段）播放对应音效。 */
function playEventSounds(events: Array<{ seq: number; kind: string }>): void {
  for (const event of events) {
    if (event.seq <= lastEventSeq) continue
    lastEventSeq = event.seq
    if (event.kind === 'bossSkill') sound.play('wb.bossSkill')
    else if (event.kind === 'death') sound.play('wb.death')
    else if (event.kind === 'revive') sound.play('wb.revive')
    else if (event.kind === 'phase') sound.play('wb.phase')
  }
}

/** 快照同步：把事件游标推到当前快照的最新序号，避免把历史事件当成新增来播放。 */
function syncEventCursor(): void {
  for (const event of state.value?.session?.events ?? []) {
    if (event.seq > lastEventSeq) lastEventSeq = event.seq
  }
}

const boss = computed(() => state.value?.boss ?? null)
const session = computed(() => state.value?.session ?? null)
const rules = computed(() => state.value?.rules ?? { heroSlots: 8, levelRequirement: 80, fullPowerLevel: 100, weaknessFloor: 0.1 })
const leaderboard = computed<WorldBossLeaderboard | null>(() => state.value?.leaderboard ?? null)
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
/** 名次加成表（按名次升序，用于说明文案）。 */
const rankBonusList = computed(() => {
  const table = state.value?.reward.rankBonus ?? {}
  return Object.keys(table)
    .map((key) => ({ rank: Number(key), items: table[key] }))
    .sort((a, b) => a.rank - b.rank)
})
/** 我的周期档位进度（档位只看个人累计伤害，与他人无关）。 */
const myProgress = computed(() => {
  const damage = state.value?.myDamage ?? 0
  const tiers = rewardTiers.value
  const next = nextRewardTier(damage, tiers)
  return {
    damage,
    items: rewardTier(damage, tiers)?.items ?? 0,
    nextDamage: next?.minDamage ?? null,
    remaining: next ? Math.max(0, next.minDamage - damage) : 0,
  }
})

/** 秒数 → 人类可读时长（用于周期倒计时）。 */
function durationText(seconds: number): string {
  const total = Math.max(0, Math.floor(seconds))
  const hours = Math.floor(total / 3600)
  const minutes = Math.floor((total % 3600) / 60)
  if (hours) return `${hours} 小时 ${minutes} 分`
  if (minutes) return `${minutes} 分 ${total % 60} 秒`
  return `${total} 秒`
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
  syncEventCursor()
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
        session: WorldBossState['session']
        leaderboard?: WorldBossLeaderboard
      }
      if (!state.value) return
      if (msg.session && state.value.session && msg.sequence < state.value.sequence) return
      if (msg.boss) state.value.boss = msg.boss
      if (msg.session) {
        playEventSounds(msg.session.events ?? [])
        msg.session.events = mergeEvents(state.value.session?.events ?? [], msg.session.events)
        state.value.session = msg.session
      }
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
    syncEventCursor()
    await connect()
  })
}

async function leave() {
  await act(async () => {
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
    const fresh = await api.worldbossState()
    if (state.value && session.value && fresh.session && fresh.sequence < state.value.sequence) return
    state.value = fresh
    syncEventCursor()
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
  })
  interval = setInterval(() => void heartbeat(), 5000)
  clock = setInterval(() => (tick.value += 1), 1000)
})

onUnmounted(() => {
  disposed = true
  if (interval) clearInterval(interval)
  if (clock) clearInterval(clock)
  socket?.close()
})
</script>

<template>
  <main class="space-y-4">
    <header class="flex flex-wrap items-end gap-3">
      <div>
        <p class="text-xs uppercase tracking-widest text-ink-400">全服共享血量 · 世界BOSS</p>
        <h1 class="text-xl font-bold text-amber-200">{{ boss?.name ?? '世界BOSS' }}</h1>
      </div>
      <span v-if="boss" class="rounded bg-ink-800 px-2 py-1 text-xs text-ink-300">第 {{ boss.cycle }} 周期</span>
      <span v-if="boss" class="rounded bg-ink-800 px-2 py-1 text-xs text-ink-300">
        本周期已讨伐 {{ boss.kills }} 次 · 剩余 {{ durationText(periodLeft) }}
      </span>
      <span
        v-if="boss"
        class="rounded px-2 py-1 text-xs"
        :class="boss.status === 'alive' ? 'bg-emerald-500/20 text-emerald-200' : 'bg-amber-500/20 text-amber-200'"
      >
        {{ boss.status === 'alive' ? '讨伐中' : `休整中 · ${respawnLeft}s 后重生` }}
      </span>
    </header>

    <p v-if="error" role="alert" class="rounded bg-rose-500/15 px-3 py-2 text-sm text-rose-200">{{ error }}</p>
    <p v-if="notice" role="status" class="rounded bg-amber-500/15 px-3 py-2 text-sm text-amber-200">{{ notice }}</p>

    <div class="grid gap-4 lg:grid-cols-[2fr_1fr]">
      <div class="space-y-4">
        <!-- BOSS 血量 / 阶段 -->
        <section class="panel space-y-2">
          <div class="flex flex-wrap items-baseline justify-between gap-2 text-sm">
            <div class="flex items-center gap-2">
              <strong class="text-rose-200">{{ boss?.name ?? '—' }}</strong>
              <span
                v-if="boss"
                class="rounded px-2 py-0.5 text-xs"
                :class="boss.phase >= 3 ? 'bg-rose-500/25 text-rose-200' : boss.phase === 2 ? 'bg-amber-500/25 text-amber-200' : 'bg-ink-700 text-ink-200'"
              >
                P{{ boss.phase }} · {{ boss.phaseName }}
              </span>
            </div>
            <span class="font-mono text-ink-300">
              {{ formatNumber(boss?.hp ?? 0) }} / {{ formatNumber(boss?.maxHp ?? 0) }}
            </span>
          </div>
          <div class="relative h-4 w-full overflow-hidden rounded bg-ink-800">
            <div class="h-full bg-rose-500 transition-all" :style="{ width: `${hpPct}%` }" />
            <!-- 阶段分界（P2/P3 进入点） -->
            <span
              v-for="p in phaseMarks"
              :key="p.id"
              class="absolute top-0 h-full w-px bg-white/50"
              :style="{ left: `${p.minHpRatio * 100}%` }"
              :title="`${p.name}：血量 ≤ ${(p.minHpRatio * 100).toFixed(0)}%`"
            />
          </div>
          <p class="text-xs text-ink-400">
            攻击力 {{ formatNumber(boss?.attack ?? 0) }} · 每 {{ boss?.skillIntervalSeconds ?? 6 }} 秒随机释放技能 ·
            英雄死亡后 {{ boss?.reviveSeconds ?? 10 }} 秒独立复活
          </p>
          <p v-if="boss" class="text-xs text-ink-400">
            当前阶段：英雄输出 ×{{ (1 / (boss.defenseMultiplier || 1)).toFixed(2) }}（防御 ×{{ boss.defenseMultiplier }}） ·
            BOSS 技能威力 ×{{ boss.skillPotencyMultiplier }}（普攻不变）
          </p>
          <div class="flex flex-wrap gap-2 text-[11px] text-ink-400">
            <span v-for="p in state?.phases ?? []" :key="p.id" class="rounded bg-ink-800 px-2 py-0.5">
              P{{ p.id }} {{ p.name }}：血量 ≤ {{ (p.minHpRatio * 100).toFixed(0) }}% · 防御 ×{{ p.defenseMultiplier }} · 技能 ×{{ p.skillPotencyMultiplier }}
            </span>
          </div>
        </section>

        <!-- 我的周期进度（档位只看个人累计伤害，与他人无关） -->
        <section class="panel space-y-2">
          <div class="flex flex-wrap items-baseline justify-between gap-2">
            <h2 class="font-semibold">我的本周期进度</h2>
            <span class="text-xs text-ink-400">周期剩余 {{ durationText(periodLeft) }}</span>
          </div>
          <p class="text-sm text-ink-300">
            本周期累计伤害 <span class="font-mono text-amber-200">{{ formatNumber(myProgress.damage) }}</span>
            <template v-if="myProgress.items">
              · 当前档位 <span class="text-amber-200">{{ myProgress.items }} 件</span>
            </template>
            <template v-else>
              · <span class="text-ink-400">未达保底门槛 {{ formatNumber(leaderboard?.minDamage ?? 0) }}</span>
            </template>
          </p>
          <p v-if="myProgress.nextDamage" class="text-xs text-ink-400">
            距下一档（累计 {{ formatNumber(myProgress.nextDamage) }}）还差 {{ formatNumber(myProgress.remaining) }}
          </p>
          <p v-else-if="myProgress.items" class="text-xs text-emerald-300">已达最高档位。</p>
        </section>

        <!-- 上阵 / 战斗 -->
        <section v-if="!session" class="panel space-y-3">
          <div class="flex items-center justify-between">
            <h2 class="font-semibold">上阵英雄（最多 {{ rules.heroSlots }} 名 · 需 Lv.{{ rules.levelRequirement }} 以上）</h2>
            <button
              class="rounded bg-amber-500/90 px-3 py-1.5 text-sm font-semibold text-ink-950 disabled:opacity-40"
              :disabled="busy || !selected.length"
              @click="enter"
            >
              进入战场（{{ selected.length }}）
            </button>
          </div>
          <p v-if="boss && boss.status !== 'alive'" class="text-xs text-amber-300">
            BOSS 正在重整旗鼓，{{ respawnLeft }} 秒后重生；此刻进场后会自动开战。
          </p>
          <p class="text-xs text-ink-400">
            本周期内 BOSS 可反复讨伐；奖励只看你自己的周期累计伤害，别人打得再快也不影响你的奖励。
          </p>
          <p class="text-xs text-ink-400">
            {{ rules.levelRequirement }}–{{ rules.fullPowerLevel - 1 }} 级英雄会被严重削弱，达到 Lv.{{ rules.fullPowerLevel }} 才不受影响。
          </p>
          <div v-if="!eligible.length" class="text-sm text-ink-400">
            没有符合条件的英雄：需达到 Lv.{{ rules.levelRequirement }}。可前往「名册 / 酒馆」培养。
          </div>
          <div v-else class="grid gap-2 sm:grid-cols-2 xl:grid-cols-3">
            <button
              v-for="h in eligible"
              :key="h.id"
              class="flex items-center gap-2 rounded border px-3 py-2 text-left text-sm transition"
              :class="selected.includes(h.id) ? 'border-amber-400 bg-amber-500/10' : 'border-ink-700 hover:border-ink-500'"
              :disabled="busy"
              @click="toggle(h.id)"
            >
              <JobIcon :job-id="h.jobId" :size="20" />
              <span class="min-w-0 flex-1">
                <span class="block truncate">{{ h.name }} · Lv.{{ h.level }}</span>
                <span class="block truncate text-xs text-ink-400">{{ jobName(h.jobId) }} · {{ weaknessHint(h.level, rules) }}</span>
              </span>
            </button>
          </div>
        </section>

        <template v-else>
          <section class="panel space-y-2">
            <div class="flex items-center justify-between">
              <h2 class="font-semibold">战斗进行中</h2>
              <button class="rounded border border-ink-600 px-3 py-1 text-sm" :disabled="busy" @click="leave">撤离</button>
            </div>
            <p class="text-xs text-ink-400">
              已战斗 {{ (session.elapsedMs / 1000).toFixed(0) }} 秒 · 本场输出 {{ formatNumber(session.damageDealt) }} ·
              本轮累计 {{ formatNumber(state?.myDamage ?? 0) }}
            </p>
          </section>

          <div class="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            <article v-for="h in session.heroes" :key="h.slot" class="panel space-y-1 text-sm">
              <div class="flex items-center gap-2">
                <JobIcon :job-id="h.jobId" :size="20" />
                <span class="min-w-0 flex-1 truncate">{{ h.name }}</span>
                <span class="text-xs text-ink-400">Lv.{{ h.level }}</span>
              </div>
              <div class="h-2 w-full overflow-hidden rounded bg-ink-800">
                <div
                  class="h-full transition-all"
                  :class="h.hp > 0 ? 'bg-emerald-500' : 'bg-ink-600'"
                  :style="{ width: `${h.maxHp > 0 ? Math.max(0, (h.hp / h.maxHp) * 100) : 0}%` }"
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
            </article>
          </div>

          <section class="panel space-y-1">
            <h2 class="font-semibold">BOSS 技能</h2>
            <p v-if="!bossSkills.length" class="text-sm text-ink-400">尚未释放技能。</p>
            <ul class="space-y-0.5 text-sm">
              <li v-for="e in bossSkills" :key="e.seq" class="animate-rise text-rose-200">
                <span class="font-mono text-xs text-ink-500">[{{ (e.at / 1000).toFixed(1) }}s]</span> {{ e.text }}
              </li>
            </ul>
          </section>
        </template>

        <!-- 结算领取 -->
        <section v-if="state?.unclaimedCycle" class="panel space-y-2">
          <h2 class="font-semibold text-amber-200">上周期已结算（第 {{ state.unclaimedCycle }} 周期）</h2>
          <p class="text-sm text-ink-300">
            你的周期累计伤害 {{ formatNumber(state.myDamage) }}，可按「档位 + 名次加成」领取「绝境龙神」系列装备。
          </p>
          <button
            class="rounded bg-amber-500/90 px-3 py-1.5 text-sm font-semibold text-ink-950 disabled:opacity-40"
            :disabled="busy || !!receipt"
            @click="claim"
          >
            {{ receipt ? '已领取' : '领取奖励' }}
          </button>
          <p v-if="receipt" class="text-sm text-emerald-200">
            第 {{ receipt.rank }} 名 · 档位 {{ receipt.tierItems }} 件 + 名次加成 {{ receipt.rankBonus }} 件 = {{ receipt.items }} 件绝境龙神装备
          </p>
          <ul v-if="receipt" class="max-h-40 space-y-0.5 overflow-auto text-xs text-ink-300">
            <li v-for="it in receipt.grants.items" :key="it.id">{{ it.name }}（{{ it.rarity }}）</li>
          </ul>
        </section>
      </div>

      <!-- 侧边：本周期伤害榜 -->
      <aside class="space-y-3">
        <section class="panel space-y-2">
          <div class="flex items-baseline justify-between">
            <h2 class="font-semibold">本周期伤害榜</h2>
            <span class="text-xs text-ink-400">第 {{ leaderboard?.cycle ?? boss?.cycle ?? 1 }} 周期</span>
          </div>
          <p class="text-xs text-ink-400">
            周期累计伤害 ≥ {{ formatNumber(leaderboard?.minDamage ?? 0) }} 才能入榜；件数 = 档位（累计伤害）+ 名次加成。
          </p>
          <p class="text-xs text-ink-500">点击任一行可展开查看该玩家各英雄的伤害与占比。</p>
          <ol class="space-y-1 text-sm">
            <li v-for="e in leaderboard?.entries ?? []" :key="e.userId">
              <button
                type="button"
                class="flex w-full items-center gap-2 rounded px-2 py-1 text-left transition hover:bg-ink-700/60"
                :class="e.userId === uid ? 'bg-amber-500/15' : 'odd:bg-ink-800/40'"
                @click="detail = e"
              >
                <span class="w-6 shrink-0 text-right font-mono" :class="e.rank <= 3 ? 'text-amber-300' : 'text-ink-400'">{{ e.rank }}</span>
                <span class="min-w-0 flex-1 truncate">
                  {{ e.nickname }}<span class="text-ink-500">#{{ e.username }}</span>
                </span>
                <span class="shrink-0 font-mono text-xs text-ink-200">{{ formatNumber(e.damage) }}</span>
                <span class="w-10 shrink-0 text-right text-xs text-amber-300">×{{ e.items }}</span>
                <span class="shrink-0 text-ink-500">›</span>
              </button>
            </li>
            <li v-if="!(leaderboard?.entries ?? []).length" class="px-2 py-1 text-ink-400">暂无达标玩家。</li>
          </ol>
          <p v-if="leaderboard?.me" class="border-t border-ink-700 pt-2 text-sm text-amber-200">
            我的排名：第 {{ leaderboard.me.rank }} 名 · {{ formatNumber(leaderboard.me.damage) }} · ×{{ leaderboard.me.items }}
            <button type="button" class="ml-2 underline decoration-dotted" @click="detail = leaderboard!.me">查看分英雄伤害</button>
          </p>
          <p v-else class="border-t border-ink-700 pt-2 text-xs text-ink-400">
            我本周期累计 {{ formatNumber(state?.myDamage ?? 0) }}，未达入榜门槛。
          </p>
        </section>

        <section class="panel space-y-1 text-xs text-ink-400">
          <h2 class="text-sm font-semibold text-ink-200">奖励说明</h2>
          <p>
            按「讨伐周期」结算（每 {{ durationText(boss?.periodSeconds ?? 0) }} 一轮）：周期内 BOSS 可反复击杀，
            奖励只看你自己的周期累计伤害 —— 别人打得再快也不影响你的奖励。
          </p>
          <p>件数 = 档位（周期累计伤害）+ 名次加成（仅前 10 名）。</p>
          <ul class="space-y-0.5">
            <li v-for="(tier, i) in rewardTiers" :key="tier.minDamage">
              第 {{ i + 1 }} 档：累计伤害 ≥ {{ formatNumber(tier.minDamage) }} → {{ tier.items }} 件
            </li>
          </ul>
          <p>
            名次加成：<span v-for="(row, i) in rankBonusList" :key="row.rank">{{ i ? ' · ' : ''
              }}第 {{ row.rank }} 名 +{{ row.items }}</span>
          </p>
          <p>「绝境龙神」固定红色品质 / 100 级，仅世界BOSS 掉落；可重造 / 附魔但代价远高于其他装备。</p>
        </section>
      </aside>
    </div>

    <!-- 榜单展开：单玩家分英雄伤害与占比 -->
    <Modal
      :open="!!detail"
      :title="detail ? `第 ${detail.rank} 名 · ${detail.nickname}#${detail.username}` : ''"
      @close="detail = null"
    >
      <div v-if="detail" class="space-y-3 text-sm">
        <p class="text-ink-300">
          本周期累计伤害 <span class="font-mono text-amber-200">{{ formatNumber(detail.damage) }}</span>
          · 预计奖励 ×{{ detail.items }}（档位 {{ detail.tierItems }} + 名次加成 {{ detail.rankBonus }}）
        </p>

        <!-- 占比堆叠条 -->
        <div class="flex h-3 w-full overflow-hidden rounded bg-ink-800">
          <span
            v-for="(h, i) in detail.heroes"
            :key="h.heroId"
            class="h-full"
            :class="HERO_COLORS[i % HERO_COLORS.length]"
            :style="{ width: `${h.pct}%` }"
          />
        </div>

        <ul class="space-y-1">
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
