/**
 * 世界BOSS：前端类型与辅助。战斗由服务端权威模拟（worldboss-worker 推进），
 * 前端只渲染通过 WebSocket 下发的 boss / session / leaderboard 快照。
 */
import type { BattleEvent } from './multiplayer'
import type { Item } from './types'

export { mergeEvents } from './multiplayer'
export type { BattleEvent } from './multiplayer'

export interface WorldBossPhase {
  id: number
  name: string
  minHpRatio: number
  defenseMultiplier: number
  skillPotencyMultiplier: number
}

export interface WorldBossBoss {
  key: string
  name: string
  cycle: number
  hp: number
  maxHp: number
  attack: number
  status: 'alive' | 'dead'
  killedAt: number | null
  respawnAt: number | null
  /** 讨伐周期长度（秒）：周期内可反复讨伐，周期到时才换轮结算。 */
  periodSeconds: number
  /** 当前周期结束时间（服务端 epoch 秒）。 */
  periodEndsAt: number | null
  /** 本周期已击杀次数。 */
  kills: number
  reviveSeconds: number
  skillIntervalSeconds: number
  /** 当前阶段（由全服剩余血量占比决定）。 */
  phase: number
  phaseName: string
  defenseMultiplier: number
  skillPotencyMultiplier: number
}

/** 榜单展开：某玩家本周期各英雄的伤害与占比。 */
export interface WorldBossHeroDamage {
  slot: number
  heroId: number
  name: string
  jobId: string
  level: number
  damage: number
  pct: number
}

export interface WorldBossHero {
  slot: number
  heroId: number
  name: string
  jobId: string
  level: number
  levelMultiplier: number
  maxHp: number
  hp: number
  mp: number
  maxMp: number
  /** 护盾值（吸收受到的伤害），用于血条浅绿覆盖层。 */
  shield: number
  deadUntil: number
  damage: number
  deaths: number
}

export interface WorldBossSessionView {
  status: string
  elapsedMs: number
  damageDealt: number
  heroes: WorldBossHero[]
  events: BattleEvent[]
  eventSequence: number
}

export interface WorldBossLeaderboardEntry {
  rank: number
  userId: number
  nickname: string
  username: string
  damage: number
  items: number
  /** 档位序号（1-based，0 表示未达档）。 */
  tier: number
  /** 档位件数（按周期累计伤害）。 */
  tierItems: number
  /** 名次加成件数（仅前 10 名）。 */
  rankBonus: number
  /** 该玩家本周期各英雄的伤害与占比（点击榜单行展开查看）。 */
  heroes: WorldBossHeroDamage[]
}

export interface WorldBossLeaderboard {
  cycle: number
  minDamage: number
  total: number
  page: number
  pageSize: number
  entries: WorldBossLeaderboardEntry[]
  me: WorldBossLeaderboardEntry | null
}

export interface WorldBossRules {
  heroSlots: number
  levelRequirement: number
  fullPowerLevel: number
  weaknessFloor: number
}

export interface WorldBossRewardTier {
  minDamage: number
  items: number
}

export interface WorldBossRewardConfig {
  minDamage: number
  /** 档位：按周期累计伤害取最高达标档的件数（保底来源）。 */
  tiers: WorldBossRewardTier[]
  /** 名次加成：仅前 10 名（键为名次字符串）。 */
  rankBonus: Record<string, number>
}

export interface WorldBossState {
  boss: WorldBossBoss | null
  rules: WorldBossRules
  phases: WorldBossPhase[]
  reward: WorldBossRewardConfig
  session: WorldBossSessionView | null
  /** 上阵英雄快照：客户端本地模拟的输入（运算下放，见 `game/core/worldboss.ts`）。 */
  party: import('./core/worldboss').WorldBossSnapshot[] | null
  /** 服务端已处理的最大上报序号：刷新 / 重进后客户端据此续接，避免重放被判重丢弃。 */
  lastReportSeq?: number
  sequence: number
  myDamage: number
  unclaimedCycle: number | null
  leaderboard: WorldBossLeaderboard
}

/** `POST /worldboss/report` 的响应：服务端对本地模拟伤害的夹取结果。 */
export interface WorldBossReportResult {
  boss: WorldBossBoss
  damageAccepted: number
  myDamage: number
  /** 同一 reportSeq 重放（幂等）。 */
  duplicate: boolean
  /** BOSS 休整中：本次未结算。 */
  paused?: boolean
}

export interface WorldBossReceipt {
  cycle: number
  rank: number
  items: number
  tier: number
  tierItems: number
  rankBonus: number
  damage: number
  grants: { items: Item[]; autoSold: Item[]; autoGold: number }
  gold: number
}

/** 英雄剩余复活秒数（基于会话内 elapsedMs，deadUntil 同为会话内毫秒）。 */
export function reviveIn(deadUntil: number, elapsedMs: number): number {
  return Math.max(0, Math.ceil((deadUntil - elapsedMs) / 1000))
}

/** BOSS 刷新倒计时秒数（respawnAt 为服务端 epoch 秒）。 */
export function respawnIn(respawnAt: number | null, nowSeconds = Date.now() / 1000): number {
  if (!respawnAt) return 0
  return Math.max(0, Math.ceil(respawnAt - nowSeconds))
}

/** 讨伐周期剩余秒数（periodEndsAt 为服务端 epoch 秒）。 */
export function periodIn(periodEndsAt: number | null, nowSeconds = Date.now() / 1000): number {
  if (!periodEndsAt) return 0
  return Math.max(0, Math.ceil(periodEndsAt - nowSeconds))
}

/** 周期累计伤害命中的最高档位（未达任何档返回 null，与服务端 tier_for_damage 同源）。 */
export function rewardTier(damage: number, tiers: WorldBossRewardTier[]): WorldBossRewardTier | null {
  let hit: WorldBossRewardTier | null = null
  for (const tier of tiers) if (damage >= tier.minDamage) hit = tier
  return hit
}

/** 下一档（用于「距下一档还差多少」提示）；已是顶档返回 null。 */
export function nextRewardTier(damage: number, tiers: WorldBossRewardTier[]): WorldBossRewardTier | null {
  return tiers.find((tier) => damage < tier.minDamage) ?? null
}

/**
 * 档位区间进度：当前档到下一档之间的完成比例（0-1，已封顶或空表为 1）。
 * 与 `rewardTier` / `nextRewardTier` 同源，保证进度条随伤害单调前进、不抽搐。
 */
export function tierProgress(
  damage: number,
  tiers: WorldBossRewardTier[],
): {
  /** 已达的最高档（未达任何档为 null）。 */
  current: WorldBossRewardTier | null
  /** 下一档（已封顶为 null）。 */
  next: WorldBossRewardTier | null
  /** 当前档的阈值（未达档为 0）。 */
  floor: number
  /** 当前档 → 下一档的完成比例（0-1）。 */
  fraction: number
  /** 距下一档还差多少（已封顶为 0）。 */
  remaining: number
} {
  const current = rewardTier(damage, tiers)
  const next = nextRewardTier(damage, tiers)
  const floor = current?.minDamage ?? 0
  if (!next) return { current, next: null, floor, fraction: 1, remaining: 0 }
  const span = next.minDamage - floor
  const fraction = span > 0 ? Math.max(0, Math.min(1, (damage - floor) / span)) : 0
  return { current, next, floor, fraction, remaining: Math.max(0, next.minDamage - damage) }
}

/** 按剩余血量占比取阶段（与服务端 `phase_for_ratio` 同源）：满足 ratio ≥ minHpRatio 的最高阶段。 */
export function phaseForRatio(ratio: number, table: WorldBossPhase[]): WorldBossPhase | null {
  const valid = table.filter((p) => p.minHpRatio <= ratio)
  if (!valid.length) return table[0] ?? null
  return valid.reduce((best, p) => (p.minHpRatio > best.minHpRatio ? p : best))
}

/**
 * 等级削弱提示文案（80~99 被削弱，满级不再削弱）。
 * `compact` 用于狭窄的上阵卡片：省去「（100 级解除）」括注（该规则已在说明卡里讲清）。
 */
export function weaknessHint(level: number, rules: WorldBossRules, compact = false): string {
  if (level >= rules.fullPowerLevel) return compact ? '满级' : '满级：无削弱'
  const floor = rules.weaknessFloor
  const ratio = (level - rules.levelRequirement) / (rules.fullPowerLevel - rules.levelRequirement)
  const mult = floor + (1 - floor) * Math.max(0, Math.min(1, ratio))
  return compact
    ? `削弱 ×${mult.toFixed(2)}`
    : `削弱中：输出/治疗 ×${mult.toFixed(2)}（${rules.fullPowerLevel} 级解除）`
}
