import data from '@shared/schema'
import { describe, expect, it } from 'vitest'

import { weatherIconUrl } from './weatherIcons'

describe('天气图标', () => {
  it('shared/data/weather.json 的每个天气类型都有对应图标（防止漏配）', () => {
    for (const type of data.weather.types) {
      expect(weatherIconUrl(type.id), `缺少图标：${type.id}（${type.name}）`).toBeTruthy()
    }
  })

  it('未知天气 id 回落为 undefined（由 WeatherIcon 退化到色点）', () => {
    expect(weatherIconUrl('__not_a_weather__')).toBeUndefined()
  })
})
