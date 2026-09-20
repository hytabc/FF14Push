import data from '@shared/schema'
import { describe, expect, it } from 'vitest'

import { attrName, baseAttrName, skillEffectLabel } from '@/utils/format'

const HAS_LATIN = /[A-Za-z]/

describe('属性与技能文案中文化', () => {
  it('每个副属性 id 都能取到中文名', () => {
    expect(data.attributes.length).toBeGreaterThan(0)
    for (const attribute of data.attributes) {
      expect(attrName(attribute.id), `${attribute.id} 缺少中文名`).not.toBe(attribute.id)
    }
  })

  it('每个底材固定属性 id 都能取到中文名', () => {
    expect(data.baseItems.length).toBeGreaterThan(0)
    for (const base of data.baseItems) {
      for (const entry of base.baseAttrs) {
        expect(baseAttrName(entry.attr), `${entry.attr} 缺少中文名`).not.toBe(entry.attr)
      }
    }
  })

  it('jobs.json 里出现的每个技能效果都有中文文案', () => {
    const types = new Set<string>()
    for (const job of data.jobs.jobs) {
      for (const skill of job.skills) {
        for (const effect of skill.effects) types.add(effect.type)
      }
    }
    expect(types.size).toBeGreaterThan(0)

    for (const type of types) {
      const label = skillEffectLabel({ type })
      expect(label, `${type} 缺少中文文案`).not.toBe('未知效果')
      expect(HAS_LATIN.test(label), `${type} 的文案仍含英文：${label}`).toBe(false)
    }
  })

  it('未知效果类型回落为「未知效果」，不暴露英文枚举', () => {
    expect(skillEffectLabel({ type: 'brandNewEffect' })).toBe('未知效果')
    expect(skillEffectLabel({})).toBe('未知效果')
  })
})
