import { describe, expect, it, vi } from 'vitest'

import {
  applyFishFilters,
  createFishFilters,
  hasFishFilters,
  presentFishValues,
  type FishFilterEntry,
} from './fishFilters'

/** 与后端 codex 接口返回的鱼获条目同构的最小样本。 */
function fish(overrides: Partial<FishFilterEntry> & { name?: string }): FishFilterEntry & { name: string } {
  return {
    name: '样本鱼',
    kind: 'normal',
    rarity: 'white',
    regionId: 1,
    weather: null,
    timeOfDay: null,
    requires: null,
    sizeMin: 20,
    sizeMax: 60,
    ...overrides,
  }
}

/** 覆盖各种场景的样本集：无门槛普通鱼 / 带天气普通鱼 / 带时段蓝鱼 / 鱼王 / 困难鱼（带前置）。 */
const ENTRIES = [
  fish({ name: '河鲈', rarity: 'white' }),
  fish({ name: '珊瑚蝶鱼', rarity: 'blue', weather: ['clearSkies'], sizeMin: 75, sizeMax: 135 }),
  fish({ name: '银鳞鲳', rarity: 'blue', weather: ['rain'], sizeMin: 75, sizeMax: 135 }),
  fish({ name: '雷鸣鱼', rarity: 'purple', weather: ['rain', 'thunder'], sizeMin: 90, sizeMax: 160 }),
  fish({ name: '夜光鱼', rarity: 'blue', timeOfDay: ['night'], sizeMin: 40, sizeMax: 90 }),
  fish({ name: '拂晓鱼', rarity: 'purple', timeOfDay: ['dawn', 'dusk'], regionId: 2, sizeMin: 30, sizeMax: 70 }),
  fish({ name: '旧鱼王', kind: 'king', rarity: null, regionId: 1, sizeMin: 100, sizeMax: 200 }),
  fish({
    name: '镜中蝶',
    kind: 'legend',
    rarity: null,
    regionId: 31,
    weather: ['fog'],
    requires: [{ fishId: 'f31_1', count: 3 }],
    sizeMin: 120,
    sizeMax: 220,
  }),
]

function names(list: Array<FishFilterEntry & { name: string }>): string[] {
  return list.map((e) => e.name)
}

describe('applyFishFilters', () => {
  it('未设置任何筛选时返回全部', () => {
    expect(applyFishFilters(ENTRIES, createFishFilters())).toHaveLength(ENTRIES.length)
  })

  it('按钓场（地区）过滤', () => {
    const f = { ...createFishFilters(), regionId: 2 }
    expect(names(applyFishFilters(ENTRIES, f))).toEqual(['拂晓鱼'])
  })

  it('按鱼种类过滤', () => {
    const f = { ...createFishFilters(), kind: 'legend' as const }
    expect(names(applyFishFilters(ENTRIES, f))).toEqual(['镜中蝶'])
  })

  it('按品质过滤，且排除没有品质的特殊鱼', () => {
    const f = { ...createFishFilters(), rarity: 'purple' as const }
    expect(names(applyFishFilters(ENTRIES, f))).toEqual(['雷鸣鱼', '拂晓鱼'])
    // 鱼王 / 困难鱼的 rarity 为 null，选具体品质时不应出现在结果里
    expect(names(applyFishFilters(ENTRIES, f))).not.toContain('旧鱼王')
    expect(names(applyFishFilters(ENTRIES, f))).not.toContain('镜中蝶')
  })

  describe('天气：严格匹配', () => {
    it('只保留把该天气列为条件的鱼（无门槛的鱼不算命中）', () => {
      const f = { ...createFishFilters(), weather: new Set(['rain']) }
      expect(names(applyFishFilters(ENTRIES, f))).toEqual(['银鳞鲳', '雷鸣鱼'])
      // 无天气门槛的河鲈不应因为「随时可钓」而被算作可在雨天钓到
      expect(names(applyFishFilters(ENTRIES, f))).not.toContain('河鲈')
    })

    it('多选时任一命中即可', () => {
      const f = { ...createFishFilters(), weather: new Set(['rain', 'thunder']) }
      expect(names(applyFishFilters(ENTRIES, f))).toEqual(['银鳞鲳', '雷鸣鱼'])
      const fog = { ...createFishFilters(), weather: new Set(['fog']) }
      expect(names(applyFishFilters(ENTRIES, fog))).toEqual(['镜中蝶'])
    })
  })

  describe('时段：严格匹配', () => {
    it('只保留把该时段列为条件的鱼', () => {
      const night = { ...createFishFilters(), timeOfDay: new Set(['night']) }
      expect(names(applyFishFilters(ENTRIES, night))).toEqual(['夜光鱼'])
      const dusk = { ...createFishFilters(), timeOfDay: new Set(['dusk']) }
      expect(names(applyFishFilters(ENTRIES, dusk))).toEqual(['拂晓鱼'])
    })
  })

  describe('直觉前置', () => {
    it("requires: 'has' 只留带非空前置的条目", () => {
      const f = { ...createFishFilters(), requires: 'has' as const }
      expect(names(applyFishFilters(ENTRIES, f))).toEqual(['镜中蝶'])
    })

    it("requires: 'none' 只留没有前置的条目", () => {
      const f = { ...createFishFilters(), requires: 'none' as const }
      const result = names(applyFishFilters(ENTRIES, f))
      expect(result).not.toContain('镜中蝶')
      expect(result).toHaveLength(ENTRIES.length - 1)
    })
  })

  describe('尺寸：区间相交', () => {
    it('只填下限：保留可钓到该尺寸及以上的鱼', () => {
      const f = { ...createFishFilters(), sizeMin: 150 }
      // 只要 sizeMax >= 150 就命中（雷鸣鱼 160 / 旧鱼王 200 / 镜中蝶 220）
      expect(names(applyFishFilters(ENTRIES, f))).toEqual(['雷鸣鱼', '旧鱼王', '镜中蝶'])
    })

    it('只填上限：保留可钓到该尺寸及以下的鱼', () => {
      const f = { ...createFishFilters(), sizeMax: 20 }
      // 只要 sizeMin <= 20 就命中（河鲈 20）
      expect(names(applyFishFilters(ENTRIES, f))).toEqual(['河鲈'])
    })

    it('同时填写上下限时取相交区间（含边界相切）', () => {
      const f = { ...createFishFilters(), sizeMin: 70, sizeMax: 100 }
      // 与 [70,100] 有交集：
      // 珊瑚蝶鱼 75-135、银鳞鲳 75-135、雷鸣鱼 90-160、夜光鱼 40-90、拂晓鱼 30-70、旧鱼王 100-200
      // （拂晓鱼上限 70、旧鱼王下限 100 与区间相切，算命中；镜中蝶 120-220 不相交）
      expect(names(applyFishFilters(ENTRIES, f))).toEqual([
        '珊瑚蝶鱼',
        '银鳞鲳',
        '雷鸣鱼',
        '夜光鱼',
        '拂晓鱼',
        '旧鱼王',
      ])
    })

    it('尺寸字段缺失的条目不受尺寸筛选影响', () => {
      const noSize = [fish({ name: '未知尺寸', sizeMin: null, sizeMax: null })]
      const f = { ...createFishFilters(), sizeMin: 999 }
      expect(names(applyFishFilters(noSize, f))).toEqual(['未知尺寸'])
    })
  })

  it('多维度组合取交集', () => {
    const f = {
      ...createFishFilters(),
      regionId: 1,
      rarity: 'blue' as const,
      weather: new Set(['rain']),
      sizeMin: 100,
    }
    // 地区 1 + 蓝鱼 + 天气小雨 + 能钓到 ≥100cm
    expect(names(applyFishFilters(ENTRIES, f))).toEqual(['银鳞鲳'])
  })

  it('筛选结果为空时返回空数组', () => {
    const f = { ...createFishFilters(), regionId: 1, kind: 'emperor' as const }
    expect(applyFishFilters(ENTRIES, f)).toEqual([])
  })

  describe('只看当前可钓', () => {
    it('开关关闭时不调用可钓判定，结果不变', () => {
      const isCatchable = vi.fn(() => false)
      const result = applyFishFilters(ENTRIES, createFishFilters(), isCatchable)
      expect(result).toHaveLength(ENTRIES.length)
      expect(isCatchable).not.toHaveBeenCalled()
    })

    it('开关打开时按注入的判定过滤', () => {
      const catchable = new Set(['河鲈', '雷鸣鱼'])
      const f = { ...createFishFilters(), catchableOnly: true }
      const result = applyFishFilters(ENTRIES, f, (e) => catchable.has(e.name))
      expect(names(result)).toEqual(['河鲈', '雷鸣鱼'])
    })

    it('未注入判定时开关不生效（避免调用方漏传导致空列表）', () => {
      const f = { ...createFishFilters(), catchableOnly: true }
      expect(applyFishFilters(ENTRIES, f)).toHaveLength(ENTRIES.length)
    })

    it('与其它维度取交集', () => {
      const f = { ...createFishFilters(), catchableOnly: true, kind: 'normal' as const }
      const result = applyFishFilters(ENTRIES, f, (e) => e.regionId === 1)
      // 地区 1 的普通鱼（旧鱼王是 king，被 kind 维度排除）
      expect(names(result)).toEqual(['河鲈', '珊瑚蝶鱼', '银鳞鲳', '雷鸣鱼', '夜光鱼'])
    })
  })
})

describe('hasFishFilters', () => {
  it('默认状态下为 false', () => {
    expect(hasFishFilters(createFishFilters())).toBe(false)
  })

  it.each([
    ['regionId', { regionId: 3 }],
    ['kind', { kind: 'king' as const }],
    ['rarity', { rarity: 'blue' as const }],
    ['weather', { weather: new Set(['rain']) }],
    ['timeOfDay', { timeOfDay: new Set(['night']) }],
    ['requires', { requires: 'has' as const }],
    ['sizeMin', { sizeMin: 50 }],
    ['sizeMax', { sizeMax: 50 }],
    ['catchableOnly', { catchableOnly: true }],
  ])('设置 %s 后为 true', (_label, patch) => {
    expect(hasFishFilters({ ...createFishFilters(), ...patch })).toBe(true)
  })
})

describe('presentFishValues', () => {
  it('只返回实际出现过的取值', () => {
    const present = presentFishValues(ENTRIES)
    expect([...present.regions].sort((a, b) => a - b)).toEqual([1, 2, 31])
    expect([...present.kinds].sort()).toEqual(['king', 'legend', 'normal'])
    expect([...present.rarities].sort()).toEqual(['blue', 'purple', 'white'])
    expect([...present.weather].sort()).toEqual(['clearSkies', 'fog', 'rain', 'thunder'])
    expect([...present.timeOfDay].sort()).toEqual(['dawn', 'dusk', 'night'])
  })

  it('空列表返回空集合', () => {
    const present = presentFishValues([])
    expect(present.regions.size).toBe(0)
    expect(present.kinds.size).toBe(0)
    expect(present.rarities.size).toBe(0)
    expect(present.weather.size).toBe(0)
    expect(present.timeOfDay.size).toBe(0)
  })
})
