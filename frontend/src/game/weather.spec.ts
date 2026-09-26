import { describe, expect, it } from 'vitest'

import { etClock, etHour, etSeconds, timeOfDay, timeOfDayWindowsText, weatherFor } from '@/game/weather'

/** FF14 官方 ET：floor(unix × 3600/175) mod 86400（1 ET 日 = 70 现实分钟）。 */
function referenceClock(ts: number): string {
  const sec = Math.floor((ts * 3600) / 175) % 86400
  const h = Math.floor(sec / 3600)
  const m = Math.floor((sec % 3600) / 60)
  return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}`
}

describe('艾欧泽亚时间与 FF14 官方公式一致', () => {
  it('etClock 与 floor(unix × 3600/175) mod 86400 一致', () => {
    for (const ts of [0, 4201750, 1_700_000_000, 1_758_900_000]) {
      expect(etClock(ts * 1000)).toBe(referenceClock(ts))
    }
  })

  it('锚点：unix 4201750 = 艾欧泽亚第 1000 天 10:00（灰机 wiki 种子示例）', () => {
    expect(etClock(4201750 * 1000)).toBe('10:00')
    expect(etHour(4201750 * 1000)).toBe(10)
    expect(etSeconds(4201750 * 1000)).toBeCloseTo(36000, 6)
  })
})

describe('昼夜时段与 FF14 一致（白天 06:00–17:59 / 夜晚 18:00–05:59）', () => {
  it('时段窗口文案', () => {
    expect(timeOfDayWindowsText()).toBe(
      '拂晓 06:00–07:59 / 白昼 08:00–15:59 / 黄昏 16:00–17:59 / 深夜 18:00–05:59',
    )
  })

  it('每个 ET 小时落在正确时段', () => {
    const atEtHour = (hour: number): number => {
      let ts = 0
      while (etHour(ts * 1000) !== hour) ts += 60
      return ts * 1000
    }
    const expected: Record<number, string> = {}
    for (const h of [6, 7]) expected[h] = 'dawn'
    for (let h = 8; h <= 15; h += 1) expected[h] = 'day'
    for (const h of [16, 17]) expected[h] = 'dusk'
    for (const h of [18, 19, 20, 21, 22, 23, 0, 1, 2, 3, 4, 5]) expected[h] = 'night'

    for (const [h, name] of Object.entries(expected)) {
      expect(timeOfDay(atEtHour(Number(h)))).toBe(name)
    }
  })
})

describe('天气兜底', () => {
  it('无权重表的地区回落 clearSkies', () => {
    expect(weatherFor(99999, 0)).toBe('clearSkies')
  })
})
