import data from '@shared/schema'
import { describe, expect, it } from 'vitest'

import { jobFigureUrl, jobIconUrl } from '@/utils/jobs'

describe('战斗职业素材索引', () => {
  it('每个战斗职业都有小人立绘与职业图标', () => {
    for (const job of data.jobs.jobs) {
      expect(jobFigureUrl(job.id), `缺少 ${job.id}（${job.name}）的小人，请重跑 npm run fetch:jobs`).toBeTruthy()
      expect(jobIconUrl(job.id), `缺少 ${job.id}（${job.name}）的职业图标，请重跑 npm run fetch:jobs`).toBeTruthy()
    }
  })

  it('每个职业使用各自独立的小人与图标（不共用素材）', () => {
    const figures = new Set<string>()
    const icons = new Set<string>()
    for (const job of data.jobs.jobs) {
      const figure = jobFigureUrl(job.id)!
      expect(figures.has(figure), `${job.id}（${job.name}）与其它职业共用了同一张小人`).toBe(false)
      figures.add(figure)

      const icon = jobIconUrl(job.id)!
      expect(icons.has(icon), `${job.id}（${job.name}）与其它职业共用了同一张图标`).toBe(false)
      icons.add(icon)
    }
  })

  it('无对应职业的 id 返回 undefined（冒险者 / 未知职业 / 空值）', () => {
    expect(jobFigureUrl('adventurer')).toBeUndefined()
    expect(jobIconUrl('adventurer')).toBeUndefined()
    expect(jobFigureUrl('NOT_A_JOB')).toBeUndefined()
    expect(jobIconUrl('NOT_A_JOB')).toBeUndefined()
    expect(jobFigureUrl(null)).toBeUndefined()
    expect(jobIconUrl(undefined)).toBeUndefined()
  })
})
