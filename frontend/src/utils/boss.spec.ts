import data from '@shared/schema'
import { describe, expect, it } from 'vitest'

import { bossFigureUrl } from '@/utils/boss'

describe('世界BOSS 立绘索引', () => {
  it('配置中的 BOSS 有对应立绘', () => {
    const key = data.worldboss.boss.id
    expect(bossFigureUrl(key), `缺少 ${key} 的立绘，请重跑 node scripts/fetch-boss-asset.mjs`).toBeTruthy()
  })

  it('未知 / 空 key 返回 undefined', () => {
    expect(bossFigureUrl('NOT_A_BOSS')).toBeUndefined()
    expect(bossFigureUrl('')).toBeUndefined()
    expect(bossFigureUrl(null)).toBeUndefined()
    expect(bossFigureUrl(undefined)).toBeUndefined()
  })
})
