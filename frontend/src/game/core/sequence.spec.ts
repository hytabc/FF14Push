import { describe, expect, it } from 'vitest'

import { resolveGatherStep, stepKey } from '@/game/core/sequence'

describe('resolveGatherStep（采集序列规划）', () => {
  it('解析出已解锁且等级足够的采集点', () => {
    const step = resolveGatherStep('g_wood', 5, () => true, 6, 'id1')
    expect(step).toMatchObject({
      kind: 'gather',
      id: 'id1',
      materialId: 'g_wood',
      jobId: 'BTN',
      regionId: 3,
      target: 5,
    })
    expect(step?.name).toBeTruthy()
  })

  it('等级不足时回退到要求更低的采集点', () => {
    const step = resolveGatherStep('g_wood', 2, () => true, 3, 'id2')
    expect(step?.regionId).toBe(2)
  })

  it('无可用采集点（未解锁 / 等级不够）返回 null', () => {
    expect(resolveGatherStep('ore40', 1, () => false, 100, 'id3')).toBeNull()
    expect(resolveGatherStep('g_wood', 1, () => true, 2, 'id4')).toBeNull()
  })

  it('非采集材料（半成品）返回 null', () => {
    expect(resolveGatherStep('h_plank', 1, () => true, 100, 'id5')).toBeNull()
  })

  it('数量至少为 1', () => {
    expect(resolveGatherStep('g_wood', 0, () => true, 6, 'id6')?.target).toBe(1)
  })
})

describe('stepKey（同目标合并判定）', () => {
  it('同种材料 / 配方 key 一致，与数量无关', () => {
    expect(
      stepKey({ kind: 'gather', id: 'a', materialId: 'g_wood', name: '', jobId: 'BTN', regionId: 2, target: 1 }),
    ).toBe(
      stepKey({ kind: 'gather', id: 'b', materialId: 'g_wood', name: '', jobId: 'BTN', regionId: 2, target: 9 }),
    )
    expect(
      stepKey({ kind: 'produce', id: 'a', recipeId: 'r1', name: '', jobId: 'CRP', target: 1 }),
    ).not.toBe(stepKey({ kind: 'gather', id: 'b', materialId: 'r1', name: '', jobId: 'CRP', regionId: 2, target: 1 }))
  })
})
