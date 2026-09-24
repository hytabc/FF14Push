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

export interface WorldBossRewardConfig {
  minDamage: number
  rankItems: Record<string, number>
  defaultItems: number
}

export interface WorldBossState {
  boss: WorldBossBoss | null
  rules: WorldBossRules
  phases: WorldBossPhase[]
  reward: WorldBossRewardConfig
  session: WorldBossSessionView | null
  sequence: number
  myDamage: number
  unclaimedCycle: number | null
  leaderboard: WorldBossLeaderboard
}

export interface WorldBossReceipt {
  cycle: number
  rank: number
  items: number
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

/** 按剩余血量占比取阶段（与服务端 `phase_for_ratio` 同源）：满足 ratio ≥ minHpRatio 的最高阶段。 */
export function phaseForRatio(ratio: number, table: WorldBossPhase[]): WorldBossPhase | null {
  const valid = table.filter((p) => p.minHpRatio <= ratio)
  if (!valid.length) return table[0] ?? null
  return valid.reduce((best, p) => (p.minHpRatio > best.minHpRatio ? p : best))
}

/** 等级削弱提示文案（80~99 被削弱，满级不再削弱）。 */
export function weaknessHint(level: number, rules: WorldBossRules): string {
  if (level >= rules.fullPowerLevel) return '满级：无削弱'
  const floor = rules.weaknessFloor
  const ratio = (level - rules.levelRequirement) / (rules.fullPowerLevel - rules.levelRequirement)
  const mult = floor + (1 - floor) * Math.max(0, Math.min(1, ratio))
  return `削弱中：输出/治疗 ×${mult.toFixed(2)}（${rules.fullPowerLevel} 级解除）`
}
