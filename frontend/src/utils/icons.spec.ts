import data from '@shared/schema'
import { describe, expect, it } from 'vitest'

import { ICON_BASE_IDS, itemIconName, itemIconUrl } from '@/utils/icons'

describe('装备像素图标索引', () => {
  it('与 shared 展开出的底材一一对应，无缺失也无多余', () => {
    const expected = Object.keys(data.baseItemById).sort()
    expect([...ICON_BASE_IDS].sort()).toEqual(expected)
  })

  it('每个底材都能取到非空的图标 URL', () => {
    for (const baseId of Object.keys(data.baseItemById)) {
      const url = itemIconUrl(baseId)
      expect(url, `缺少 ${baseId} 的图标，请重跑 npm run gen:icons`).toBeTruthy()
    }
  })

  it('未知底材回落到 id 本身作为名称', () => {
    expect(itemIconUrl('w_not_exists_9')).toBeUndefined()
    expect(itemIconName('w_not_exists_9')).toBe('w_not_exists_9')
  })
})
