import { describe, expect, it } from 'vitest'

import { MIN_WHEEL_SECTORS, buildWheelSectors, nextRotation } from '@/game/core/wheel'
import type { TreasureReward } from '@/game/types'

function reward(kind: TreasureReward['kind'], itemId?: string): TreasureReward {
  return { kind, itemId, name: itemId ?? kind }
}

const POOL: TreasureReward[] = [
  reward('gold'),
  reward('exp'),
  reward('materia', 'm_crit_1'),
  reward('potion', 'p_str_1'),
  reward('seed', 'seed_gold'),
]

describe('挖宝转盘扇区', () => {
  it('没有奖励时不产生扇区', () => {
    expect(buildWheelSectors([], POOL)).toEqual([])
  })

  it('扇区数不少于下限，且角度均分 360°', () => {
    const rewards = [reward('materia', 'm_crit_1'), reward('seed', 'seed_gold')]
    const sectors = buildWheelSectors(rewards, POOL)
    expect(sectors.length).toBeGreaterThanOrEqual(MIN_WHEEL_SECTORS)

    const step = 360 / sectors.length
    sectors.forEach((sector, index) => {
      expect(sector.startAngle).toBeCloseTo(index * step)
      expect(sector.endAngle).toBeCloseTo((index + 1) * step)
      expect(sector.centerAngle).toBeCloseTo(index * step + step / 2)
    })
    expect(sectors[sectors.length - 1].endAngle).toBeCloseTo(360)
  })

  it('每件奖励恰好占一个扇区，其余扇区取自干扰池', () => {
    const rewards = [
      reward('materia', 'm_crit_1'),
      reward('materia', 'm_dh_2'),
      reward('gold'),
    ]
    const sectors = buildWheelSectors(rewards, POOL)

    const hits = sectors.filter((sector) => sector.isReward).map((sector) => sector.reward)
    expect(hits).toEqual(rewards)

    const poolIds = new Set(POOL.map((p) => `${p.kind}:${p.itemId ?? ''}`))
    for (const sector of sectors.filter((s) => !s.isReward)) {
      expect(poolIds.has(`${sector.reward.kind}:${sector.reward.itemId ?? ''}`)).toBe(true)
    }
  })

  it('奖励扇区均匀分散（不会挤在一起）', () => {
    const rewards = [reward('gold'), reward('exp'), reward('materia', 'm_crit_1')]
    const sectors = buildWheelSectors(rewards, POOL)
    const positions = sectors
      .map((sector, index) => (sector.isReward ? index : -1))
      .filter((index) => index >= 0)
    for (let i = 1; i < positions.length; i += 1) {
      expect(positions[i] - positions[i - 1]).toBeGreaterThan(1)
    }
  })
})

describe('挖宝转盘落点', () => {
  it('目标角度让指针正对扇区中心，且只正向旋转', () => {
    const sectors = buildWheelSectors([reward('gold'), reward('exp')], POOL)
    let current = 0
    for (const sector of sectors.filter((s) => s.isReward)) {
      const next = nextRotation(current, sector, 2)
      // 扇区中心旋转后落在 12 点方向（指针处）
      expect((((sector.centerAngle + next) % 360) + 360) % 360).toBeCloseTo(0)
      // 只正向旋转，且至少转过一圈
      expect(next).toBeGreaterThan(current)
      expect(next - current).toBeGreaterThanOrEqual(360)
      current = next
    }
  })

  it('扇区内抖动不会越出该扇区', () => {
    const sectors = buildWheelSectors([reward('gold'), reward('exp')], POOL)
    const step = 360 / sectors.length
    for (const sector of sectors.filter((s) => s.isReward)) {
      const jitter = (step / 2) * 0.5
      for (const offset of [-jitter, jitter]) {
        const next = nextRotation(0, sector, 2, offset)
        const landed = (((sector.centerAngle + next) % 360) + 360) % 360
        // 落点与指针（0°）的偏差不超过半个扇区
        expect(Math.min(landed, 360 - landed)).toBeLessThan(step / 2)
      }
    }
  })
})
