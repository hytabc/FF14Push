/**
 * 顶部导航的分组结构（二级菜单）：一级 = 分组，二级 = 页面，三级 = 组内小标题。
 *
 * 页面数量较多（20+），平铺会让页头过载；此处按「战斗 / 养成 / 生活 / 社交 / 其它」收敛。
 * `to` 必须与 `router/index.ts` 的路径一一对应（`navigation.spec.ts` 会断言覆盖完整）。
 * 仅调整展示结构，不改变任何页面与路由。
 */

export interface NavItem {
  /** 路由路径（与 `router/index.ts` 一致）。 */
  to: string
  label: string
  icon: string
  /** 仅管理员可见。 */
  adminOnly?: boolean
}

/** 分组内的三级小标题；不设标题时渲染为一组无标题条目。 */
export interface NavSection {
  title?: string
  items: NavItem[]
}

export interface NavGroup {
  id: string
  label: string
  icon: string
  sections: NavSection[]
}

export const NAV_GROUPS: NavGroup[] = [
  {
    id: 'combat',
    label: '战斗',
    icon: '⚔',
    sections: [
      {
        title: '地区与本机',
        items: [
          { to: '/', label: '战斗', icon: '⚔' },
          { to: '/region', label: '地区', icon: '🗺' },
          { to: '/raid', label: '高难', icon: '☠' },
          { to: '/treasure', label: '挖宝', icon: '🏺' },
          { to: '/palace', label: '死者宫殿', icon: '💀' },
        ],
      },
      {
        title: '联机与活动',
        items: [
          { to: '/arena', label: '竞技场', icon: '⚔' },
          { to: '/coop', label: '远征', icon: '⚑' },
          { to: '/worldboss', label: '世界BOSS', icon: '🐲' },
        ],
      },
    ],
  },
  {
    id: 'growth',
    label: '养成',
    icon: '🧙',
    sections: [
      {
        title: '英雄',
        items: [
          { to: '/hero', label: '英雄', icon: '🧙' },
          { to: '/roster', label: '名册', icon: '👥' },
          { to: '/tavern', label: '酒馆', icon: '🍺' },
        ],
      },
      {
        title: '装备',
        items: [
          { to: '/equipment', label: '装备', icon: '🛡' },
          { to: '/inventory', label: '背包', icon: '🎒' },
          { to: '/chest', label: '抽箱', icon: '📦' },
        ],
      },
    ],
  },
  {
    id: 'dohdol',
    label: '生活',
    icon: '⛏',
    sections: [
      {
        title: '采集与制作',
        items: [
          { to: '/gather', label: '采集', icon: '⛏' },
          { to: '/produce', label: '生产', icon: '🔨' },
          { to: '/fish', label: '钓鱼', icon: '🎣' },
        ],
      },
      {
        title: '全服活动',
        items: [
          { to: '/ishgard', label: '重建伊修加德', icon: '🏗' },
        ],
      },
      {
        title: '加工',
        items: [
          { to: '/craft', label: '合成', icon: '⚗' },
          { to: '/materia', label: '魔晶石', icon: '💎' },
          { to: '/farm', label: '种田', icon: '🌱' },
        ],
      },
    ],
  },
  {
    id: 'social',
    label: '社交',
    icon: '🤝',
    sections: [
      {
        items: [
          { to: '/market', label: '市场', icon: '🏪' },
          { to: '/friends', label: '好友', icon: '🤝' },
          { to: '/chat', label: '聊天室', icon: '💬' },
          { to: '/ranking', label: '排行', icon: '🏆' },
          { to: '/grants', label: '补偿公示', icon: '📢' },
        ],
      },
    ],
  },
  {
    id: 'system',
    label: '其它',
    icon: '⚙',
    sections: [
      {
        items: [
          { to: '/codex', label: '图鉴', icon: '📖' },
          { to: '/settings', label: '设置', icon: '⚙' },
          { to: '/gametest', label: '游戏测试', icon: '🎮' },
          { to: '/admin', label: '管理', icon: '🔧', adminOnly: true },
        ],
      },
    ],
  },
]

/** 只保留当前身份可见的条目，并丢弃因此变空的小节 / 分组。 */
export function visibleGroups(isAdmin: boolean): NavGroup[] {
  return NAV_GROUPS.map((group) => ({
    ...group,
    sections: group.sections
      .map((section) => ({
        ...section,
        items: section.items.filter((item) => isAdmin || !item.adminOnly),
      }))
      .filter((section) => section.items.length > 0),
  })).filter((group) => group.sections.length > 0)
}

/** 扁平化后的全部条目（用于测试与「当前页」查找）。 */
export function flattenNav(groups: NavGroup[] = NAV_GROUPS): NavItem[] {
  return groups.flatMap((group) => group.sections.flatMap((section) => section.items))
}

/** 当前路径所属的分组（用于高亮一级菜单）。 */
export function groupForPath(path: string): NavGroup | null {
  for (const group of NAV_GROUPS) {
    for (const section of group.sections) {
      if (section.items.some((item) => item.to === path)) return group
    }
  }
  return null
}

/** 当前路径对应的菜单条目（移动端在标题旁显示当前页名）。 */
export function itemForPath(path: string): NavItem | null {
  return flattenNav().find((item) => item.to === path) ?? null
}
