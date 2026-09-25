/**
 * 版本更新公告的弹窗状态。
 *
 * 「是否已读」按版本号记录在 localStorage（`eorzea.announcement.seenVersion`）：
 * 只有当前版本与已读版本不一致时才弹出，因此每次版本号更新后用户进入游戏会看到一次公告。
 * 存储读写的防御式写法仿 `stores/sound.ts`。
 */
import { defineStore } from 'pinia'
import { ref } from 'vue'

import { APP_VERSION } from '@/version'

const SEEN_KEY = 'eorzea.announcement.seenVersion'

function readSeen(): string | null {
  try {
    if (typeof localStorage === 'undefined') return null
    return localStorage.getItem(SEEN_KEY)
  } catch {
    return null
  }
}

function writeSeen(version: string): void {
  try {
    if (typeof localStorage !== 'undefined') localStorage.setItem(SEEN_KEY, version)
  } catch {
    /* 隐私模式等写入失败时忽略 */
  }
}

export const useAnnouncementStore = defineStore('announcement', () => {
  const open = ref(false)
  const expanded = ref(false)

  /** 进入页面时调用：版本号与已读版本不一致则弹出公告。 */
  function maybeShow(): void {
    if (readSeen() !== APP_VERSION) open.value = true
  }

  /** 关闭公告并记为已读（版本号更新后会再次弹出）。 */
  function dismiss(): void {
    writeSeen(APP_VERSION)
    open.value = false
    expanded.value = false
  }

  /** 展开 / 收起历史版本列表。 */
  function toggleExpanded(): void {
    expanded.value = !expanded.value
  }

  return { open, expanded, version: APP_VERSION, maybeShow, dismiss, toggleExpanded }
})
