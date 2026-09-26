import { describe, expect, it } from 'vitest'

import type { Item } from '@/game/types'
import {
  ROLE_LABELS,
  TERM_BY_ID,
  WEAPON_TYPE_LABELS,
  applyItemFilters,
  createItemFilters,
  equipGroup,
  filterOptionSets,
  hasActiveFilters,
  possibleTermIds,
  roleOfBaseId,
} from '@/utils/itemFilters'

const ITEM_DEFAULTS: Record<string, unknown> = {
  id: 0,
  baseId: 'w_lance_4',
  name: '测试装备',
  category: 'weapon',
  slot: 'mainHand',
  equipSlots: ['mainHand'],
  rarity: 'common',
  levelReq: 1,
  score: 0,
  baseAttrs: [],
  subAttrs: [],
  terms: [],
  equippedSlot: null,
  refineCount: 0,
  enchantCount: 0,
  refineCost: 0,
  enchantCost: 0,
  refineCostBasedOnCurrent: 0,
  enchantCostBasedOnCurrent: 0,
  source: 'chest',
  weaponType: null,
  jobId: null,
  tagIds: [],
  sellPriceMin: 0,
  sellPriceMax: 0,
}

function makeItem(partial: Record<string, unknown> = {}): Item {
  return { ...ITEM_DEFAULTS, ...partial } as unknown as Item
}

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
  it('武器按 jobId 精确取职能（长枪 = 龙骑士 = 近战，咒杖 = 黑魔 = 法系）', () => {
    expect(roleOfBaseId('w_lance_4')).toBe('melee')
    expect(roleOfBaseId('w_lance_det_4')).toBe('melee')
    expect(roleOfBaseId('w_rod_int_4')).toBe('magicalRanged')
  })

  it('防具/饰品按职能词缀映射（FF14 国服：游击=忍者近战、精准=远敏）', () => {
    expect(roleOfBaseId('a_body_tank_4')).toBe('tank')
    expect(roleOfBaseId('a_body_bal_4')).toBe('healer')
    expect(roleOfBaseId('a_body_str_4')).toBe('melee')
    expect(roleOfBaseId('a_body_det_4')).toBe('melee')
    expect(roleOfBaseId('a_body_dex_4')).toBe('melee')
    expect(roleOfBaseId('a_body_crit_4')).toBe('physicalRanged')
    expect(roleOfBaseId('c_ring_gold_4')).toBe('physicalRanged')
    expect(roleOfBaseId('c_ring_vit_4')).toBe('tank')
  })

  it('基础型（无前缀）视为通用（null）', () => {
    expect(roleOfBaseId('a_body_4')).toBeNull()
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

describe('hasActiveFilters / createItemFilters', () => {
  it('初始状态无激活筛选，改动后激活', () => {
    const f = createItemFilters()
    expect(hasActiveFilters(f)).toBe(false)
    f.rarity = 'rare'
    expect(hasActiveFilters(f)).toBe(true)
    f.rarity = 'all'
    f.subAttrs.add('crit')
    expect(hasActiveFilters(f)).toBe(true)
  })

  it('名称关键字（非空白）视为激活筛选', () => {
    expect(hasActiveFilters({ ...createItemFilters(), query: '剑' })).toBe(true)
    expect(hasActiveFilters({ ...createItemFilters(), query: '   ' })).toBe(false)
  })

  it('「仅未装备」视为激活筛选', () => {
    expect(hasActiveFilters({ ...createItemFilters(), equipped: 'unequipped' })).toBe(true)
  })
})

describe('filterOptionSets', () => {
  it('只列出候选池里实际存在的值并给出中文名', () => {
    const pool = [
      makeItem({ id: 1, category: 'weapon', weaponType: 'lance' }),
      makeItem({ id: 2, category: 'armor', slot: 'body', equipSlots: ['body'] }),
    ]
    const sets = filterOptionSets(pool)
    expect(sets.categories.map((o) => o.id).sort()).toEqual(['armor', 'weapon'])
    expect(sets.weaponTypes.map((o) => o.id)).toEqual(['lance'])
    expect(sets.slots.map((o) => o.id).sort()).toEqual(['body', 'mainHand'])
  })
})

describe('applyItemFilters', () => {
  const items: Item[] = [
    makeItem({
      id: 1,
      baseId: 'w_lance_4',
      name: '长枪',
      rarity: 'rare',
      levelReq: 80,
      score: 100,
      weaponType: 'lance',
      subAttrs: [{ attr: 'crit', value: 10, type: 'flat', quality: 'common' }],
      terms: [{ id: 'strBoost', name: '力量增幅', type: 'buff', stat: 'attackPct', trigger: '常驻', value: 5, quality: 'ancient', desc: '' }],
    }),
    makeItem({
      id: 2,
      baseId: 'c_ring_4',
      name: '戒指',
      category: 'accessory',
      slot: 'ring',
      equipSlots: ['ring1', 'ring2'],
      rarity: 'epic',
      levelReq: 40,
      score: 50,
      subAttrs: [{ attr: 'dh', value: 5, type: 'flat', quality: 'rare' }],
    }),
  ]

  function state(patch: Partial<ReturnType<typeof createItemFilters>> = {}) {
    return { ...createItemFilters(), ...patch }
  }

  it('按品阶筛选', () => {
    expect(applyItemFilters(items, state({ rarity: 'epic' }), 'power').map((i) => i.id)).toEqual([2])
  })

  it('按种类 / 部位筛选', () => {
    expect(applyItemFilters(items, state({ category: 'accessory' }), 'power').map((i) => i.id)).toEqual([2])
    // 戒指底材 slot=ring，equipSlots[0]=ring1
    expect(applyItemFilters(items, state({ slot: 'ring1' }), 'power').map((i) => i.id)).toEqual([2])
  })

  it('按武器种类与战斗职能筛选', () => {
    expect(applyItemFilters(items, state({ weaponType: 'lance' }), 'power').map((i) => i.id)).toEqual([1])
    expect(applyItemFilters(items, state({ role: 'melee' }), 'power').map((i) => i.id)).toEqual([1])
    expect(applyItemFilters(items, state({ role: 'tank' }), 'power')).toEqual([])
  })

  it('按名称子串筛选（不区分大小写，忽略前后空白）', () => {
    const pool = [...items, makeItem({ id: 3, name: 'Hero Blade', category: 'weapon' })]
    expect(applyItemFilters(pool, state({ query: '长枪' }), 'power').map((i) => i.id)).toEqual([1])
    expect(applyItemFilters(pool, state({ query: 'hero' }), 'power').map((i) => i.id)).toEqual([3])
    expect(applyItemFilters(pool, state({ query: '  HERO  ' }), 'power').map((i) => i.id)).toEqual([3])
    expect(applyItemFilters(pool, state({ query: '不存在' }), 'power')).toEqual([])
  })

  it('按装备状态筛选（仅未装备）', () => {
    const pool = [
      makeItem({ id: 3, name: '已装备甲', category: 'armor', slot: 'body', equipSlots: ['body'], equippedSlot: 'body' }),
      makeItem({ id: 4, name: '未装备甲', category: 'armor', slot: 'body', equipSlots: ['body'] }),
    ]
    expect(applyItemFilters(pool, state({ equipped: 'unequipped' }), 'power').map((i) => i.id)).toEqual([4])
    expect(applyItemFilters(pool, state(), 'power').map((i) => i.id).sort()).toEqual([3, 4])
  })

  it('按等级区间筛选', () => {
    expect(applyItemFilters(items, state({ levelMin: 60 }), 'power').map((i) => i.id)).toEqual([1])
    expect(applyItemFilters(items, state({ levelMax: 50 }), 'power').map((i) => i.id)).toEqual([2])
  })

  it('按副词条 / 词条 / 品质筛选', () => {
    expect(applyItemFilters(items, state({ subAttrs: new Set(['crit']) }), 'power').map((i) => i.id)).toEqual([1])
    expect(applyItemFilters(items, state({ terms: new Set(['strBoost']) }), 'power').map((i) => i.id)).toEqual([1])
    // 太古只命中带太古词条的第 1 件
    expect(applyItemFilters(items, state({ quality: new Set(['ancient']) }), 'power').map((i) => i.id)).toEqual([1])
    // 稀有命中第 2 件的副属性
    expect(applyItemFilters(items, state({ quality: new Set(['rare']) }), 'power').map((i) => i.id)).toEqual([2])
  })

  it('按专用加成筛选', () => {
    const dedicated = makeItem({
      id: 3,
      category: 'doh_tool',
      slot: 'dohTool',
      equipSlots: ['dohTool'],
      baseAttrs: [{ attr: 'craftQualityPct', value: 4 }],
    })
    expect(applyItemFilters([...items, dedicated], state({ bonus: new Set(['craftQualityPct']) }), 'power').map((i) => i.id)).toEqual([3])
  })

  it('排序：战力降序 / 名称升序', () => {
    expect(applyItemFilters(items, state(), 'power').map((i) => i.id)).toEqual([1, 2])
    const byName = [...items].sort((a, b) => a.name.localeCompare(b.name, 'zh-Hans-CN')).map((i) => i.id)
    expect(applyItemFilters(items, state(), 'name').map((i) => i.id)).toEqual(byName)
  })
})
