import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

import { describe, expect, it } from 'vitest'

import { NAV_GROUPS, flattenNav, groupForPath, itemForPath, visibleGroups } from '@/navigation'

/**
 * 从路由源码里取出「登录后页面」的路径。
 * 不 import router：`createWebHistory()` 依赖浏览器 `window`，而 Vitest 跑在 Node 环境。
 */
function authenticatedRoutePaths(): string[] {
  const source = readFileSync(fileURLToPath(new URL('./router/index.ts', import.meta.url)), 'utf8')
  return [...source.matchAll(/path:\s*'([^']+)'/g)]
    .map((match) => match[1])
    .filter((path) => path !== '/login' && !path.includes('pathMatch'))
}

describe('顶部导航分组', () => {
  it('菜单条目与登录后路由一一对应（不重不漏）', () => {
    const navPaths = flattenNav().map((item) => item.to)
    expect(new Set(navPaths).size).toBe(navPaths.length)
    expect([...navPaths].sort()).toEqual([...authenticatedRoutePaths()].sort())
  })

  it('分组与小节均非空，条目字段齐备', () => {
    for (const group of NAV_GROUPS) {
      expect(group.sections.length).toBeGreaterThan(0)
      for (const section of group.sections) {
        expect(section.items.length).toBeGreaterThan(0)
        for (const item of section.items) {
          expect(item.to.startsWith('/')).toBe(true)
          expect(item.label.length).toBeGreaterThan(0)
          expect(item.icon.length).toBeGreaterThan(0)
        }
      }
    }
  })

  it('按路径定位分组与条目', () => {
    expect(groupForPath('/worldboss')?.id).toBe('combat')
    expect(groupForPath('/farm')?.id).toBe('dohdol')
    expect(groupForPath('/settings')?.id).toBe('system')
    expect(itemForPath('/farm')?.label).toBe('种田')
    expect(groupForPath('/not-a-page')).toBeNull()
    expect(itemForPath('/not-a-page')).toBeNull()
  })

  it('管理入口仅管理员可见', () => {
    const playerPaths = flattenNav(visibleGroups(false)).map((item) => item.to)
    const adminPaths = flattenNav(visibleGroups(true)).map((item) => item.to)
    expect(playerPaths).not.toContain('/admin')
    expect(adminPaths).toContain('/admin')
    expect(adminPaths.length).toBe(playerPaths.length + 1)
  })
})
