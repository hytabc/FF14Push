import { conditionsFor, matchesGate } from '@/game/weather'
import type { FishFilterEntry } from '@/utils/fishFilters'

/**
 * 一条鱼相对「此刻 + 该玩家」的可钓状态。
 *
 * - `catchable`：天气 / 时段命中，且地区已解锁、采集等级达标 —— 现在就能钓。
 * - `level_locked`：天气 / 时段命中、地区已解锁，但采集等级不足。
 * - `region_locked`：天气 / 时段命中，但地区未解锁。
 * - `gate_closed`：天气 / 时段条件当前不满足（图鉴不标记，保持原样）。
 *
 * 判定与图鉴的「是否已收集」无关。
 */
export type FishAvailability = 'catchable' | 'level_locked' | 'region_locked' | 'gate_closed'

export interface FishAvailabilityContext {
  /** 玩家已解锁的钓场（地区）id。 */
  unlockedRegions: Set<number>
  /** 玩家当前采集（大地使者）等级。 */
  dolLevel: number
  /** 各钓场的等级要求（来自 `fish.json` 的 `regions[].levelReq`）。 */
  regionLevelReq: Record<number, number>
  /** 用于复算天气 / 艾欧泽亚时间的时刻。 */
  nowMs: number
}

/**
 * 判定一条鱼的可钓状态。
 *
 * **先看天气 / 时段，再看地区 / 等级**：这样只有「出现条件已满足」的鱼才会带标记，
 * 不会给整张表（约 360 条）都挂上「地区未解锁」之类与当前时刻无关的标签。
 * 天气 / 时段不满足时一律返回 `gate_closed`（不标记）。
 */
export function fishAvailability(entry: FishFilterEntry, ctx: FishAvailabilityContext): FishAvailability {
  const regionId = entry.regionId
  if (typeof regionId !== 'number') return 'gate_closed'
  if (!matchesGate(conditionsFor(regionId, ctx.nowMs), entry.weather, entry.timeOfDay)) return 'gate_closed'
  if (!ctx.unlockedRegions.has(regionId)) return 'region_locked'
  if (ctx.dolLevel < (ctx.regionLevelReq[regionId] ?? 1)) return 'level_locked'
  return 'catchable'
}

/** 现在是否就能钓起（用于「只看当前可钓」筛选）。 */
export function isFishCatchable(entry: FishFilterEntry, ctx: FishAvailabilityContext): boolean {
  return fishAvailability(entry, ctx) === 'catchable'
}
