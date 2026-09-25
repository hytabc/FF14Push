import { describe, expect, it } from 'vitest'

import type { MaterialStackItem } from '@/game/types'

import {
  applyConsumableFilters,
  consumableEffectKey,
  consumableEffectOptions,
  consumableTier,
  createConsumableFilters,
  hasActiveConsumableFilters,
} from './consumableFilters'

/** 用真实消耗品 id 构造库存条目（名称按服务端下发的显示名，用于搜索）。 */
function stack(itemId: string, count: number, name: string): MaterialStackItem {
  return { itemId, kind: itemId.startsWith('p_') ? 'potion' : 'food', count, name }
}

const ENTRIES: MaterialStackItem[] = [
  stack('f_expGainPct', 4, '经验获取料理'),
  stack('p_expGainPct', 3, '经验获取秘药'),
  stack('p_chestLuck', 5, '抽箱品阶概率秘药'),
  stack('p_expGainPct2', 1, '经验获取秘药 II'),
  stack('f_goldGainPct', 7, '金币获取料理'),
  stack('p_expGainPct3', 2, '经验获取秘药 III'),
]

const ids = (list: MaterialStackItem[]) => list.map((e) => e.itemId)

describe('applyConsumableFilters', () => {
  it('默认按类型分组：药水在食物前，同类效果聚拢，档位升序', () => {
    expect(ids(applyConsumableFilters(ENTRIES, createConsumableFilters(), 'group'))).toEqual([
      'p_expGainPct',
      'p_expGainPct2',
      'p_expGainPct3',
      'p_chestLuck',
      'f_expGainPct',
      'f_goldGainPct',
    ])
  })

  it('不改动原数组顺序', () => {
    const before = ids(ENTRIES)
    applyConsumableFilters(ENTRIES, createConsumableFilters(), 'group')
    expect(ids(ENTRIES)).toEqual(before)
  })

  it('按分类过滤', () => {
    const f = { ...createConsumableFilters(), kind: 'potion' as const }
    expect(ids(applyConsumableFilters(ENTRIES, f, 'group'))).toEqual([
      'p_expGainPct',
      'p_expGainPct2',
      'p_expGainPct3',
      'p_chestLuck',
    ])
  })

  it('按加成效果过滤（声明了该效果才命中）', () => {
    const f = { ...createConsumableFilters(), effect: 'expGainPct' }
    expect(ids(applyConsumableFilters(ENTRIES, f, 'group'))).toEqual([
      'p_expGainPct',
      'p_expGainPct2',
      'p_expGainPct3',
      'f_expGainPct',
    ])
  })

  it('按名称搜索（忽略大小写与首尾空白）', () => {
    expect(ids(applyConsumableFilters(ENTRIES, { ...createConsumableFilters(), search: '秘药' }, 'group'))).toEqual([
      'p_expGainPct',
      'p_expGainPct2',
      'p_expGainPct3',
      'p_chestLuck',
    ])
    const gold = { ...createConsumableFilters(), search: ' 金币 ' }
    expect(ids(applyConsumableFilters(ENTRIES, gold, 'group'))).toEqual(['f_goldGainPct'])
  })

  it('多维度组合取交集', () => {
    const f = { ...createConsumableFilters(), kind: 'food' as const, effect: 'goldGainPct', search: '料理' }
    expect(ids(applyConsumableFilters(ENTRIES, f, 'group'))).toEqual(['f_goldGainPct'])
  })

  it('按数量降序排序', () => {
    expect(ids(applyConsumableFilters(ENTRIES, createConsumableFilters(), 'count'))).toEqual([
      'f_goldGainPct',
      'p_chestLuck',
      'f_expGainPct',
      'p_expGainPct',
      'p_expGainPct3',
      'p_expGainPct2',
    ])
  })

  it('按名称排序时与中文名称比较一致', () => {
    const sorted = applyConsumableFilters(ENTRIES, createConsumableFilters(), 'name')
    const expected = [...ENTRIES]
      .map((e) => e.name)
      .sort((a, b) => a.localeCompare(b, 'zh-Hans-CN'))
    expect(sorted.map((e) => e.name)).toEqual(expected)
  })

  it('筛选结果为空时返回空数组', () => {
    const f = { ...createConsumableFilters(), kind: 'potion' as const, effect: 'goldGainPct', search: '料理' }
    expect(applyConsumableFilters(ENTRIES, f, 'group')).toEqual([])
  })
})

describe('consumableEffectKey / consumableTier', () => {
  it('取首个加成效果作为分组键', () => {
    expect(consumableEffectKey(stack('p_expGainPct', 1, '经验获取秘药'))).toBe('expGainPct')
    expect(consumableEffectKey(stack('p_fishInsightPct2', 1, '捕鱼人之识时长秘药 II'))).toBe('fishInsightPct')
  })

  it('从 id 尾缀解析档位（无尾缀为 1）', () => {
    expect(consumableTier('p_expGainPct')).toBe(1)
    expect(consumableTier('p_expGainPct2')).toBe(2)
    expect(consumableTier('p_expGainPct3')).toBe(3)
  })
})

describe('consumableEffectOptions', () => {
  it('只列出实际出现过的效果，并按配置顺序排列', () => {
    expect(consumableEffectOptions(ENTRIES)).toEqual([
      { id: 'expGainPct', label: '经验获取' },
      { id: 'goldGainPct', label: '金币获取' },
      { id: 'chestLuck', label: '抽箱品阶概率' },
    ])
  })

  it('空列表返回空选项', () => {
    expect(consumableEffectOptions([])).toEqual([])
  })
})

describe('hasActiveConsumableFilters', () => {
  it('默认状态下为 false（纯空白搜索不算）', () => {
    expect(hasActiveConsumableFilters(createConsumableFilters())).toBe(false)
    expect(hasActiveConsumableFilters({ ...createConsumableFilters(), search: '   ' })).toBe(false)
  })

  it.each([
    ['kind', { kind: 'potion' as const }],
    ['effect', { effect: 'expGainPct' }],
    ['search', { search: '秘药' }],
  ])('设置 %s 后为 true', (_label, patch) => {
    expect(hasActiveConsumableFilters({ ...createConsumableFilters(), ...patch })).toBe(true)
  })
})
