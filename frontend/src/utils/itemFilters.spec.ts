import { describe, expect, it } from 'vitest'

import {
  ROLE_LABELS,
  TERM_BY_ID,
  WEAPON_TYPE_LABELS,
  equipGroup,
  possibleTermIds,
  roleOfBaseId,
} from '@/utils/itemFilters'

describe('equipGroup', () => {
  it('战斗大类归 combat', () => {
    expect(equipGroup('weapon')).toBe('combat')
    expect(equipGroup('armor')).toBe('combat')
    expect(equipGroup('accessory')).toBe('combat')
  })

  it('生产/采集专用大类分组正确', () => {
    expect(equipGroup('doh_tool')).toBe('doh')
    expect(equipGroup('doh_gear')).toBe('doh')
    expect(equipGroup('dol_tool')).toBe('dol')
    expect(equipGroup('dol_gear')).toBe('dol')
  })

  it('未知大类回落到 combat', () => {
    expect(equipGroup('bogus')).toBe('combat')
  })
})

describe('roleOfBaseId', () => {
  it('武器按 jobId 精确取职能（长枪 = 龙骑士 = 近战）', () => {
    expect(roleOfBaseId('w_lance_4')).toBe('melee')
  })

  it('防具按职能词缀近似映射', () => {
    expect(roleOfBaseId('a_body_tank_4')).toBe('tank')
    expect(roleOfBaseId('a_body_bal_4')).toBe('healer')
    expect(roleOfBaseId('a_body_str_4')).toBe('melee')
  })

  it('基础型与精准/制敌型视为通用（null）', () => {
    expect(roleOfBaseId('a_body_4')).toBeNull()
    expect(roleOfBaseId('a_body_crit_4')).toBeNull()
  })

  it('专用装备与未知/空 id 返回 null', () => {
    expect(roleOfBaseId('dh_dohTool_0')).toBeNull()
    expect(roleOfBaseId('nope')).toBeNull()
    expect(roleOfBaseId(null)).toBeNull()
    expect(roleOfBaseId(undefined)).toBeNull()
  })
})

describe('possibleTermIds', () => {
  it('无 slots 限制的战斗词条对所有部位生效', () => {
    const head = possibleTermIds('head', 'combat')
    expect(head).toContain('strBoost')
    // 生产词条不进入战斗部位
    expect(head).not.toContain('dohRarityLuck')
  })

  it('限定 slots 的词条只在对应部位生效', () => {
    const ring = possibleTermIds('ring1', 'combat')
    const head = possibleTermIds('head', 'combat')
    expect(ring).toContain('goldGain')
    expect(head).not.toContain('goldGain')
  })

  it('采集/生产分组取生产词条池', () => {
    expect(possibleTermIds('dohTool', 'doh')).toContain('dohRarityLuck')
    expect(possibleTermIds('dohTool', 'doh')).not.toContain('strBoost')
  })
})

describe('映射表完整性', () => {
  it('战斗职能与武器种类都有中文名', () => {
    expect(Object.values(ROLE_LABELS).every((name) => name.length > 0)).toBe(true)
    expect(Object.keys(WEAPON_TYPE_LABELS).length).toBeGreaterThan(0)
    expect(TERM_BY_ID['strBoost']?.name).toBe('力量增幅')
  })
})
