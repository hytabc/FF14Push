import { defineStore } from 'pinia'
import { ref } from 'vue'

import type { RarityId } from '@/game/types'

export interface LootBubble {
  id: number
  baseId: string
  name: string
  rarity: RarityId
  /** 附加说明；缺省时展示品阶名（如「史诗」）。 */
  note?: string
}

/** 单条气泡默认停留时长（毫秒）。 */
const DEFAULT_TTL = 4200
/** 同屏最多展示的气泡数，超出后丢弃最早的。 */
const MAX_VISIBLE = 5

let seq = 0

/** 掉落气泡：物品掉落时的轻量提示，替代会打断视野的弹窗。 */
export const useLootStore = defineStore('loot', () => {
  const bubbles = ref<LootBubble[]>([])

  function push(bubble: Omit<LootBubble, 'id'>, ttl = DEFAULT_TTL) {
    const id = ++seq
    bubbles.value = [...bubbles.value, { id, ...bubble }].slice(-MAX_VISIBLE)
    window.setTimeout(() => dismiss(id), ttl)
  }

  function dismiss(id: number) {
    bubbles.value = bubbles.value.filter((b) => b.id !== id)
  }

  function clear() {
    bubbles.value = []
  }

  return { bubbles, push, dismiss, clear }
})
