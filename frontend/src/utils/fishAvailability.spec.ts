import data from '@shared/schema'
import { describe, expect, it } from 'vitest'

import { conditionsFor } from '@/game/weather'

import { fishAvailability, isFishCatchable, type FishAvailabilityContext } from './fishAvailability'
import type { FishFilterEntry } from './fishFilters'

/** 固定时刻 → 天气 / ET 完全确定，测试无需 mock。 */
const NOW = 1_700_000_000_000
const REGION = 1
const COND = conditionsFor(REGION, NOW)

/** 与该钓场当前天气不同的另一个天气（用于构造「不命中」的门槛）。 */
const OTHER_WEATHER = data.weather.types.map((t) => t.id).find((id) => id !== COND.weather) as string
/** 与当前时段不同的另一个时段。 */
const OTHER_TOD = (Object.keys(data.weather.timeOfDay) as string[]).find((t) => t !== COND.timeOfDay) as string

function ctx(patch: Partial<FishAvailabilityContext> = {}): FishAvailabilityContext {
  return {
    unlockedRegions: new Set([REGION]),
    dolLevel: 100,
    regionLevelReq: { [REGION]: 1 },
    nowMs: NOW,
    ...patch,
  }
}

function fish(over: Partial<FishFilterEntry> = {}): FishFilterEntry {
  return { regionId: REGION, weather: null, timeOfDay: null, ...over }
}

describe('fishAvailability：天气 / 时段门槛', () => {
  it('没有天气 / 时段门槛的鱼，条件判定直接通过', () => {
    expect(fishAvailability(fish(), ctx())).toBe('catchable')
  })

  it('天气命中当前天气 → 通过', () => {
    expect(fishAvailability(fish({ weather: [COND.weather] }), ctx())).toBe('catchable')
  })

  it('天气不命中 → gate_closed', () => {
    expect(fishAvailability(fish({ weather: [OTHER_WEATHER] }), ctx())).toBe('gate_closed')
  })

  it('时段命中 / 不命中', () => {
    expect(fishAvailability(fish({ timeOfDay: [COND.timeOfDay] }), ctx())).toBe('catchable')
    expect(fishAvailability(fish({ timeOfDay: [OTHER_TOD] }), ctx())).toBe('gate_closed')
  })

  it('多条件里命中其一即可', () => {
    expect(fishAvailability(fish({ weather: [OTHER_WEATHER, COND.weather] }), ctx())).toBe('catchable')
  })
})

describe('fishAvailability：地区与等级', () => {
  it('天气命中但地区未解锁 → region_locked', () => {
    expect(fishAvailability(fish({ weather: [COND.weather] }), ctx({ unlockedRegions: new Set() }))).toBe(
      'region_locked',
    )
  })

  it('天气命中、地区已解锁但采集等级不足 → level_locked', () => {
    const c = ctx({ dolLevel: 3, regionLevelReq: { [REGION]: 50 } })
    expect(fishAvailability(fish({ weather: [COND.weather] }), c)).toBe('level_locked')
  })

  it('采集等级恰好达到要求即算可钓（边界）', () => {
    const c = ctx({ dolLevel: 50, regionLevelReq: { [REGION]: 50 } })
    expect(fishAvailability(fish(), c)).toBe('catchable')
  })

  it('钓场没有等级要求记录时按 Lv.1 处理', () => {
    expect(fishAvailability(fish(), ctx({ dolLevel: 1, regionLevelReq: {} }))).toBe('catchable')
  })
})

describe('fishAvailability：优先级', () => {
  it('天气 / 时段不满足时优先返回 gate_closed，不显示地区 / 等级原因', () => {
    // 地区未解锁 + 等级不足，但天气不符 —— 仍应是 gate_closed（图鉴不给当前时刻无关的鱼挂标签）
    const c = ctx({ unlockedRegions: new Set(), dolLevel: 1, regionLevelReq: { [REGION]: 50 } })
    expect(fishAvailability(fish({ weather: [OTHER_WEATHER] }), c)).toBe('gate_closed')
  })

  it('地区未解锁优先于等级不足', () => {
    const c = ctx({ unlockedRegions: new Set(), dolLevel: 1, regionLevelReq: { [REGION]: 50 } })
    expect(fishAvailability(fish(), c)).toBe('region_locked')
  })

  it('缺少 regionId 的条目不参与判定', () => {
    expect(fishAvailability({ weather: null, timeOfDay: null }, ctx())).toBe('gate_closed')
  })
})

describe('fishAvailability：特殊鱼', () => {
  it('鱼王 / 困难鱼用同一把尺（直觉前置不影响判定）', () => {
    const legend: FishFilterEntry = {
      regionId: REGION,
      kind: 'legend',
      rarity: null,
      weather: [COND.weather],
      requires: [{ fishId: 'f1_1', count: 3 }],
    }
    expect(fishAvailability(legend, ctx())).toBe('catchable')
  })
})

describe('isFishCatchable', () => {
  it('等价于可钓状态为 catchable', () => {
    expect(isFishCatchable(fish(), ctx())).toBe(true)
    expect(isFishCatchable(fish({ weather: [OTHER_WEATHER] }), ctx())).toBe(false)
    expect(isFishCatchable(fish(), ctx({ unlockedRegions: new Set() }))).toBe(false)
    expect(isFishCatchable(fish(), ctx({ dolLevel: 1, regionLevelReq: { [REGION]: 99 } }))).toBe(false)
  })
})
