import { describe, expect, it } from 'vitest'

import {
  createMarketFilters,
  hasMarketFilters,
  marketQueryParams,
  resetMarketFilters,
} from '@/utils/marketFilters'

const BASE = { kind: 'equipment', sort: 'time_desc', page: 1, pageSize: 20 }

describe('hasMarketFilters / resetMarketFilters', () => {
  it('初始状态无筛选，改动后激活，重置后复原', () => {
    const f = createMarketFilters()
    expect(hasMarketFilters(f)).toBe(false)

    f.priceMin = 0
    expect(hasMarketFilters(f)).toBe(true)

    resetMarketFilters(f)
    expect(hasMarketFilters(f)).toBe(false)
    expect(f).toEqual(createMarketFilters())

    f.q = '剑'
    expect(hasMarketFilters(f)).toBe(true)
  })

  it('纯空白关键字不算筛选', () => {
    expect(hasMarketFilters({ ...createMarketFilters(), q: '   ' })).toBe(false)
  })
})

describe('marketQueryParams', () => {
  it('空筛选只保留分页与品类上下文', () => {
    expect(marketQueryParams(createMarketFilters(), BASE)).toEqual({
      kind: 'equipment',
      sort: 'time_desc',
      page: 1,
      pageSize: 20,
      q: undefined,
      rarity: undefined,
      category: undefined,
      slot: undefined,
      levelMin: undefined,
      levelMax: undefined,
      priceMin: undefined,
      priceMax: undefined,
    })
  })

  it('关键字去除前后空白，"all" 维度省略，区间转数字', () => {
    const f = {
      ...createMarketFilters(),
      q: '  长枪  ',
      rarity: 'rare' as const,
      category: 'weapon',
      slot: 'mainHand',
      levelMin: 60,
      levelMax: 90,
      priceMin: 100,
      priceMax: 5000,
    }
    expect(marketQueryParams(f, BASE)).toEqual({
      kind: 'equipment',
      sort: 'time_desc',
      page: 1,
      pageSize: 20,
      q: '长枪',
      rarity: 'rare',
      category: 'weapon',
      slot: 'mainHand',
      levelMin: 60,
      levelMax: 90,
      priceMin: 100,
      priceMax: 5000,
    })
  })

  it('价格下界 0 是合法边界，不能被当空值丢弃', () => {
    const f = { ...createMarketFilters(), priceMin: 0, priceMax: 0 }
    const params = marketQueryParams(f, BASE)
    expect(params.priceMin).toBe(0)
    expect(params.priceMax).toBe(0)
  })

  it('越界的等级 / 价格输入被丢弃，避免后端 422', () => {
    const f = { ...createMarketFilters(), levelMin: -5, levelMax: 0, priceMin: -1, priceMax: 10 }
    const params = marketQueryParams(f, BASE)
    expect(params.levelMin).toBeUndefined()
    expect(params.levelMax).toBeUndefined()
    expect(params.priceMin).toBeUndefined()
    expect(params.priceMax).toBe(10)
  })
})
