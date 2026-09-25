import { describe, expect, it } from 'vitest'

import { parseChangelog } from '@/utils/changelog'
import { APP_VERSION, CHANGELOG } from '@/version'

describe('parseChangelog', () => {
  it('解析版本标题与条目（含日期），并忽略标题与说明段落', () => {
    const raw = [
      '# 更新日志',
      '',
      '这是一段说明，不应被当成条目。',
      '',
      '## V1.0.1 — 2026-09-25',
      '- 顶栏显示版本号',
      '- 新增更新公告',
      '',
      '## V1.0.0 — 2026-09-20',
      '- 初始版本',
    ].join('\n')

    expect(parseChangelog(raw)).toEqual([
      { version: '1.0.1', date: '2026-09-25', items: ['顶栏显示版本号', '新增更新公告'] },
      { version: '1.0.0', date: '2026-09-20', items: ['初始版本'] },
    ])
  })

  it('支持无日期标题与 * 条目，且忽略出现在任何标题之前的条目', () => {
    const raw = ['- 悬空条目应被忽略', '## 2.3.4', '* 星号条目'].join('\n')

    expect(parseChangelog(raw)).toEqual([{ version: '2.3.4', date: undefined, items: ['星号条目'] }])
  })

  it('没有版本标题时返回空数组', () => {
    expect(parseChangelog('# 更新日志\n\n没有版本条目')).toEqual([])
  })
})

describe('真实 CHANGELOG.md', () => {
  it('至少包含一个版本，且首条版本号形如 x.y.z', () => {
    expect(CHANGELOG.length).toBeGreaterThan(0)
    expect(APP_VERSION).toMatch(/^\d+\.\d+\.\d+$/)
  })
})
