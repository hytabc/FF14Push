import { describe, expect, it } from 'vitest'

import { findGatherTarget } from '@/game/core/gather'

describe('findGatherTarget（生产页 → 采集跳转）', () => {
  it('地区专属材料定位到唯一的采集点', () => {
    const target = findGatherTarget('ore7', () => true)
    expect(target).toEqual({ jobId: 'MIN', regionId: 7, weight: expect.any(Number) })
  })

  it('通用材料优先已解锁且产出权重最高的地区', () => {
    // g_wood（榆木）在多个 BTN 采集点产出；已解锁 ≤6 的地区里权重最高是 3、6（w3），取更靠前的 3
    const target = findGatherTarget('g_wood', (region) => region <= 6)
    expect(target).toMatchObject({ jobId: 'BTN', regionId: 3 })
  })

  it('未解锁产出地区时返回 null（不引导到无法采集的地方）', () => {
    expect(findGatherTarget('ore40', () => false)).toBeNull()
  })

  it('非采集材料（半成品）返回 null', () => {
    expect(findGatherTarget('h_plank', () => true)).toBeNull()
    expect(findGatherTarget('unknown', () => true)).toBeNull()
  })

  it('传入采集等级时只选等级足够的采集点（序列规划用）', () => {
    // g_wood：地区 2（要求 Lv.3，权重 1）与地区 3（要求 Lv.6，权重 3）
    expect(findGatherTarget('g_wood', () => true, 6)).toMatchObject({ regionId: 3 })
    // Lv.3 时地区 3 不可用，回退到地区 2
    expect(findGatherTarget('g_wood', () => true, 3)).toMatchObject({ regionId: 2 })
    // Lv.2 时两个采集点都采不了
    expect(findGatherTarget('g_wood', () => true, 2)).toBeNull()
    // 不传等级时保持原行为（不受等级限制）
    expect(findGatherTarget('g_wood', () => true)).toMatchObject({ jobId: 'BTN' })
  })
})
