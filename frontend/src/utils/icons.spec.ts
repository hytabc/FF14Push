import data from '@shared/schema'
import { describe, expect, it } from 'vitest'

import { ICON_BASE_IDS, itemIconName, itemIconUrl } from '@/utils/icons'

/** 全部应有像素图的物品 id：战斗底材 + 材料/半成品/鱼获（materialById 已在 loader 内合并鱼）+ 专用装备 + 药水食物 + 魔晶石 + 作物种子。 */
const expectedIds = [
  ...Object.keys(data.baseItemById),
  ...Object.keys(data.materialById),
  ...Object.keys(data.dohdolItemById),
  ...Object.keys(data.consumableById),
  ...Object.keys(data.materiaById),
  ...Object.keys(data.seedById),
].sort()

describe('物品像素图标索引', () => {
  it('与 shared 展开出的全部物品一一对应，无缺失也无多余', () => {
    expect([...ICON_BASE_IDS].sort()).toEqual(expectedIds)
  })

  it('每个物品都能取到非空的图标 URL', () => {
    for (const id of expectedIds) {
      const url = itemIconUrl(id)
      expect(url, `缺少 ${id} 的图标，请重跑 npm run gen:icons`).toBeTruthy()
    }
  })

  it('每件战斗装备都有各自独立的像素图（同职能同色，改名后图名仍对应）', () => {
    const owner = new Map<string, string>()
    for (const id of Object.keys(data.baseItemById)) {
      const url = itemIconUrl(id)!
      const prev = owner.get(url)
      expect(prev, `${id} 与 ${prev} 使用了同一张像素图`).toBeUndefined()
      owner.set(url, id)
    }
  })

  it('名称可解析到中文名而非 id 本身', () => {
    expect(itemIconName('w_sword_shield_0')).not.toBe('w_sword_shield_0')
    expect(itemIconName('g_ore')).toBe('铁矿')
    expect(itemIconName('ore1')).toBe('铜矿')
    expect(itemIconName('flora40')).toBe('仙人掌果')
    expect(itemIconName('h_plank')).toBe('木板')
    expect(itemIconName('dh_dohTool_0')).not.toBe('dh_dohTool_0')
    expect(itemIconName('f1_1')).toBe('河鲈')
    expect(itemIconName('k1')).toBe('涅普特之龙')
    expect(itemIconName('p_expGainPct')).toBe('经验获取秘药')
    expect(itemIconName('m_crit_1')).toBe('武略魔晶石壹型')
    expect(itemIconName('m_str_3')).toBe('刚力魔晶石叁型')
    expect(itemIconName('seed_gold')).toBe('金币种子')
    expect(itemIconName('seed_exp')).toBe('经验种子')
  })

  it('未知 id 回落到 id 本身作为名称', () => {
    expect(itemIconUrl('w_not_exists_9')).toBeUndefined()
    expect(itemIconName('w_not_exists_9')).toBe('w_not_exists_9')
  })
})
