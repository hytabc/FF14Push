import type { Hero, Item } from './types'

export type Mode = 'solo' | 'offline' | 'online'
export type Role = 'tank' | 'healer' | 'dps'
export interface Snapshot {
  heroId: number; ownerId: number; name: string; level: number; role: Role; jobId: string
  strategy: 'assist' | 'manual'; stats: Record<string, number>; panel: Hero
  items: { id: number; slot: string; rarity: string }[]
}
export interface Registration { id: number; userId: number; kind: string; snapshot: Snapshot }
export interface Roster {
  activeHeroId: number | null
  capacity: number
  maxCapacity: number
  /** 再开一席的金币价格；已达上限为 null。 */
  expandCost: number | null
  heroes: (Hero & { id: number; loadout: Record<string, Item> })[]
}
export interface Dungeon {
  id: string; name: string; difficulty: string; requiredLevel: number; seats: number
  prerequisite: string | null; enrageSeconds: number
  phases: { name: string; bosses: string[]; mechanics: { name: string; action: string }[] }[]
}
export interface BattleHero {
  slot: number; controllerId: number; snapshot: Snapshot; clone: boolean; registeredClone: boolean
  hp: number; mp: number; shield: number; weakUntil: number; deadUntil: number
  damage: number; healing: number; deaths: number; trialPassed: boolean
}
export interface BattleEvent { seq: number; at: number; kind: string; text: string }
export interface BattleState {
  elapsedMs: number; phase: number; status: string; reason: string | null; heroes: BattleHero[]
  bosses: { id: number; name: string; hp: number; maxHp: number }[]
  mechanics: { id: string; name: string; action: string; opened: boolean; resolved: boolean; deadline: number; responses: Record<string, number> }[]
  events: BattleEvent[]; hadClone: boolean; trialDone: boolean
  trial: null | { endsAt: number; checks: Record<string, { role: string; remaining: number }> }
}
export interface RoomBrief { id: number; code: string; dungeonId: string; mode: Mode; status: string }
export interface Room {
  id: number; code: string; ownerId: number; mode: Mode; status: string; dungeon: Dungeon
  members: { userId: number; ready: boolean; online: boolean }[]
  seats: { slot: number; controllerId: number; heroId: number; registrationId: number | null; snapshot: Snapshot }[]
  entryFailures: string[]; battle: null | { id: number; sequence: number; state: BattleState }
}
export const modes: Record<Mode, string> = { solo: '个人挑战', offline: '离线合作', online: '在线合作' }
export const roles: Record<Role, string> = { tank: '坦克', healer: '治疗', dps: '输出' }
export const difficulties: Record<string, string> = { normal: '普通合作', extreme: '歼殛战 · 极', savage: '零式副本', ultimate: '绝境战' }
export const actions: Record<string, string> = { focus: '集火', interrupt: '打断', spread: '散开', stack: '分摊', mitigate: '减伤', swap: '换坦', rescue: '解救', dispel: '驱散' }
export function seatQuota(total: number, players: number): string {
  if (players < 1) return '0'
  const low = Math.floor(total / players), high = Math.ceil(total / players)
  return low === high ? `${low}` : `${low}—${high}`
}
export function remaining(until: number, elapsed: number) { return Math.max(0, Math.ceil((until - elapsed) / 1000)) }
export function mergeEvents(previous: BattleEvent[], incoming: BattleEvent[]) {
  const byId = new Map([...previous, ...incoming].map(e => [e.seq, e]))
  return [...byId.values()].sort((a, b) => a.seq - b.seq).slice(-200)
}

/** 远征通关记录中的单个席位（含分角色战斗信息，来自服务端权威模拟）。 */
export interface CoopPartyMember {
  slot: number; heroId: number; ownerId: number; account: string; name: string
  jobId: string; role: Role; level: number; clone: boolean
  damage: number; healing: number; damageTaken: number
  deaths: number; minHpRatio: number; dangerMs: number
}

/** 远征榜条目 payload（服务端实时聚合）。 */
export interface CoopClearPayload {
  nickname: string; level: number; clearMs: number; mode: Mode; hadClone: boolean
  dungeonId: string; createdAt: number; party: CoopPartyMember[]
}
