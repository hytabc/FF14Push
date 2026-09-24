import { describe, expect, it } from 'vitest'

import { expandRecipeSteps, gatherStepIssue, resolveGatherStep, stepKey } from '@/game/core/sequence'

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

  it('采不了的材料也返回步骤，并标记受阻原因', () => {
    const locked = resolveGatherStep('ore40', 1, () => false, 100, 'id3')
    expect(locked).toMatchObject({ kind: 'gather', blocked: 'region' })
    const lowLevel = resolveGatherStep('g_wood', 1, () => true, 2, 'id4')
    expect(lowLevel).toMatchObject({ blocked: 'level' })
    expect(lowLevel?.requiredLevel).toBeGreaterThan(2)
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

/** 展开上下文：id 自增，采集点全部视为已解锁且等级足够。 */
function expandCtx(dolLevel = 100) {
  let n = 0
  return { isUnlocked: () => true, dolLevel, nextId: () => `s${++n}` }
}

describe('expandRecipeSteps（炼金 / 烹调：展开整棵合成列表）', () => {
  it('经验获取秘药 = 采集 9 药草 + 制作 2 浓缩墨水 + 制作 1 秘药', () => {
    const { steps, warnings } = expandRecipeSteps('r_p_expGainPct', 1, expandCtx())
    expect(warnings).toEqual([])
    expect(
      steps.map((s) => (s.kind === 'gather' ? ['gather', s.materialId, s.target] : ['produce', s.recipeId, s.target])),
    ).toEqual([
      ['gather', 'g_herb', 9],
      ['produce', 'r_h_ink', 2],
      ['produce', 'r_p_expGainPct', 1],
    ])
  })

  it('递归展开跨职业中间品（雕琢宝石由雕金匠制作），且依赖排在目标之前', () => {
    const { steps } = expandRecipeSteps('r_p_chestLuck', 1, expandCtx())
    const gemIdx = steps.findIndex((s) => s.kind === 'produce' && s.recipeId === 'r_h_gemcut')
    expect(gemIdx).toBeGreaterThanOrEqual(0)
    expect(steps[gemIdx]).toMatchObject({ kind: 'produce', jobId: 'GSM' })
    expect(gemIdx).toBeLessThan(steps.length - 1)
    expect(steps[steps.length - 1]).toMatchObject({ kind: 'produce', recipeId: 'r_p_chestLuck' })
  })

  it('数量翻倍时同步放大采集与中间品数量', () => {
    const { steps } = expandRecipeSteps('r_p_expGainPct', 2, expandCtx())
    expect(steps[0]).toMatchObject({ kind: 'gather', materialId: 'g_herb', target: 18 })
    expect(steps[1]).toMatchObject({ kind: 'produce', recipeId: 'r_h_ink', target: 4 })
  })

  it('高阶原始材料在等级不足时被标记为无法采集', () => {
    const { steps } = expandRecipeSteps('r_p_expGainPct3', 1, expandCtx(1))
    const blocked = steps.find((s) => s.kind === 'gather' && s.blocked)
    expect(blocked).toMatchObject({ kind: 'gather', blocked: 'level' })
  })

  it('未知配方返回空步骤与告警', () => {
    const { steps, warnings } = expandRecipeSteps('r_unknown', 1, expandCtx())
    expect(steps).toEqual([])
    expect(warnings).toHaveLength(1)
  })
})

describe('gatherStepIssue（无法采集的显式原因）', () => {
  it('可采集时返回 null', () => {
    const step = resolveGatherStep('g_wood', 1, () => true, 100, 'x')
    expect(step && gatherStepIssue(step, () => true, 100)).toBeNull()
  })

  it('等级不足 / 地区未解锁给出中文原因', () => {
    const low = resolveGatherStep('g_wood', 1, () => true, 2, 'x')!
    expect(gatherStepIssue(low, () => true, 2)).toContain('采集等级')
    const locked = resolveGatherStep('ore40', 1, () => false, 100, 'y')!
    expect(gatherStepIssue(locked, () => false, 100)).toBe('所在地区未解锁')
  })
})
