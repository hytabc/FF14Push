/** 挖宝开箱转盘的纯几何逻辑（与渲染无关，便于单测）。
 *
 * 约定：角度单位为度，0° 指向 12 点方向、顺时针增大（与 CSS `conic-gradient(from 0deg)` 一致）；
 * 指针固定在 12 点方向，因此「整盘顺时针旋转 `-centerAngle`」即可让该扇区中心对准指针。
 */

import type { TreasureReward } from '@/game/types'

/** 转盘最少扇区数：奖励件数不足时用干扰项补足，视觉上更接近真实转盘。 */
export const MIN_WHEEL_SECTORS = 8

export interface WheelSector {
  /** 扇区展示的奖励（真实奖励或干扰项）。 */
  reward: TreasureReward
  /** 是否为本次真实奖励（只有真实奖励才会被指针命中）。 */
  isReward: boolean
  /** 扇区角度区间 [startAngle, endAngle) 与中心角。 */
  startAngle: number
  endAngle: number
  centerAngle: number
}

/** 干扰项兜底：池子为空时用奖励本身占位，保证扇区始终可渲染。 */
function pickDecoy(pool: TreasureReward[], rewards: TreasureReward[]): TreasureReward {
  const source = pool.length ? pool : rewards
  if (!source.length) return { kind: 'gold', amount: 0 }
  return source[Math.floor(Math.random() * source.length)]
}

/**
 * 构建转盘扇区：每件奖励占一个扇区（均匀分散），其余用 `pool` 里的干扰项补足到
 * 至少 `MIN_WHEEL_SECTORS` 个扇区。
 */
export function buildWheelSectors(
  rewards: TreasureReward[],
  pool: TreasureReward[] = [],
): WheelSector[] {
  if (!rewards.length) return []

  const total = Math.max(MIN_WHEEL_SECTORS, rewards.length * 2)
  const rewardAt = new Map<number, number>()
  for (let i = 0; i < rewards.length; i += 1) {
    const slot = Math.min(total - 1, Math.floor((i * total) / rewards.length))
    rewardAt.set(slot, i)
  }

  const step = 360 / total
  const sectors: WheelSector[] = []
  for (let slot = 0; slot < total; slot += 1) {
    const index = rewardAt.get(slot)
    const isReward = index !== undefined
    const startAngle = slot * step
    sectors.push({
      reward: isReward ? rewards[index] : pickDecoy(pool, rewards),
      isReward,
      startAngle,
      endAngle: startAngle + step,
      centerAngle: startAngle + step / 2,
    })
  }
  return sectors
}

/**
 * 从当前角度正向旋转到目标扇区（含 `turns` 圈减速），保证结果严格大于 `current`，
 * 避免「往回转」的观感。`jitter` 为扇区内的随机偏移（度），绝对值应小于半个扇区。
 */
export function nextRotation(
  current: number,
  sector: WheelSector,
  turns = 2,
  jitter = 0,
): number {
  const base = turns * 360 - sector.centerAngle + jitter
  const floor = current + 360
  if (base >= floor) return base
  return base + Math.ceil((floor - base) / 360) * 360
}
