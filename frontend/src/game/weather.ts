import data from '@shared/schema'
import type { WeatherTypeDef } from '@shared/schema'

/**
 * 天气 / 艾欧泽亚时间：后端 `services/weather.py` 的镜像。
 *
 * 结算一律以服务端为准；这里用同一套 32 位整型哈希复算，用于展示当前条件与「天气预报」。
 * 修改本文件时必须同步 `backend/app/services/weather.py`，两者必须逐位一致。
 */

function imul(a: number, b: number): number {
  return Math.imul(a, b) >>> 0
}

/** 32 位整型混合器 → [0,1)。与 Python `weather.hash01` 逐位一致。 */
export function hash01(bucket: number, regionId: number): number {
  let x = imul(bucket, 0x9e3779b1)
  x = (x ^ imul(regionId, 0x85ebca77)) >>> 0
  x = imul(x ^ (x >>> 16), 0x7feb352d)
  x = imul(x ^ (x >>> 15), 0x846ca68b)
  x = (x ^ (x >>> 16)) >>> 0
  return x / 0x100000000
}

export function weatherPeriodSec(): number {
  return data.weather.weatherPeriodSec
}

const REGION_WEIGHTS: Record<number, Record<string, number>> = Object.fromEntries(
  data.weather.regions.map((r) => [r.regionId, r.weights]),
)

export function weatherType(weatherId: string): WeatherTypeDef | undefined {
  return data.weather.types.find((t) => t.id === weatherId)
}

export function weatherName(weatherId: string): string {
  return weatherType(weatherId)?.name ?? weatherId
}

/** 该地区当前天气 id。无权重表时回落 clear。 */
export function weatherFor(regionId: number, nowMs: number = Date.now()): string {
  const weights = REGION_WEIGHTS[regionId]
  if (!weights) return 'clear'
  const bucket = Math.floor(nowMs / 1000 / weatherPeriodSec())
  const entries = Object.entries(weights)
  const total = entries.reduce((sum, [, w]) => sum + w, 0)
  const roll = hash01(bucket, regionId) * total
  let acc = 0
  let last = entries[0][0]
  for (const [id, w] of entries) {
    acc += w
    last = id
    if (roll < acc) return id
  }
  return last
}

/** 当前 ET 时刻在一天内的秒数。 */
export function etSeconds(nowMs: number = Date.now()): number {
  const day = data.weather.eorzea.dayRealSeconds
  const epoch = Math.floor(nowMs / 1000)
  return ((epoch % day) / day) * 86400
}

export function etHour(nowMs: number = Date.now()): number {
  return Math.floor(etSeconds(nowMs) / 3600) % 24
}

export function etClock(nowMs: number = Date.now()): string {
  const total = etSeconds(nowMs)
  const h = Math.floor(total / 3600) % 24
  const m = Math.floor((total % 3600) / 60)
  return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}`
}

/** 拂晓 / 白昼 / 黄昏 / 深夜（窗口跨零点时按环处理）。 */
export function timeOfDay(nowMs: number = Date.now()): string {
  const hour = etHour(nowMs)
  for (const [name, span] of Object.entries(data.weather.timeOfDay)) {
    const [start, end] = span
    if (start <= end) {
      if (hour >= start && hour <= end) return name
    } else if (hour >= start || hour <= end) {
      return name
    }
  }
  return 'day'
}

export function timeOfDayName(name: string): string {
  return data.weather.timeOfDayNames[name] ?? name
}

/** 结算 / 展示用的当前环境条件（与后端 `conditions_for` 同结构）。 */
export interface FishConditions {
  weather: string
  weatherName: string
  weatherHex: string
  etHour: number
  etClock: string
  timeOfDay: string
  timeOfDayName: string
}

export function conditionsFor(regionId: number, nowMs: number = Date.now()): FishConditions {
  const weather = weatherFor(regionId, nowMs)
  const tod = timeOfDay(nowMs)
  return {
    weather,
    weatherName: weatherName(weather),
    weatherHex: weatherType(weather)?.hex ?? '#9aa4b2',
    etHour: etHour(nowMs),
    etClock: etClock(nowMs),
    timeOfDay: tod,
    timeOfDayName: timeOfDayName(tod),
  }
}

/** 天气 / 时间门槛：未声明即不限制；声明了则必须命中其一。 */
export function matchesGate(
  cond: FishConditions,
  weatherIds?: string[] | null,
  timeOfDayIds?: string[] | null,
): boolean {
  if (weatherIds?.length && !weatherIds.includes(cond.weather)) return false
  if (timeOfDayIds?.length && !timeOfDayIds.includes(cond.timeOfDay)) return false
  return true
}

export function secondsUntilWeatherChange(nowMs: number = Date.now()): number {
  const period = weatherPeriodSec()
  return period - (Math.floor(nowMs / 1000) % period)
}

export interface WeatherForecastEntry {
  atMs: number
  inSeconds: number
  weather: string
  weatherName: string
  weatherHex: string
  etClock: string
  timeOfDay: string
  timeOfDayName: string
  isNow: boolean
}

/** 未来 `count` 个天气时段（含当前），供「预报」面板使用。 */
export function forecast(regionId: number, count = 5, nowMs: number = Date.now()): WeatherForecastEntry[] {
  const period = weatherPeriodSec()
  const out: WeatherForecastEntry[] = []
  for (let i = 0; i < count; i += 1) {
    const atMs = nowMs + i * period * 1000
    const cond = conditionsFor(regionId, atMs)
    out.push({
      atMs,
      inSeconds: i === 0 ? 0 : Math.round((atMs - nowMs) / 1000),
      weather: cond.weather,
      weatherName: cond.weatherName,
      weatherHex: cond.weatherHex,
      etClock: cond.etClock,
      timeOfDay: cond.timeOfDay,
      timeOfDayName: cond.timeOfDayName,
      isNow: i === 0,
    })
  }
  return out
}
