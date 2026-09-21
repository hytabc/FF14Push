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
})
