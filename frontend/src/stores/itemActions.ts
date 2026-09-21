import { defineStore } from 'pinia'
import { ref } from 'vue'

import { useGameStore } from './game'
import { useToastStore } from './toast'
import type { Item, RerollMode } from '@/game/types'

export type ItemActionKind = 'refine' | 'enchant' | 'sell' | 'enchantAuto'

/** 重造 / 附魔结果：用于展示逐条涨跌。 */
export interface RerollResult {
  kind: 'refine' | 'enchant'
  before: Item
  after: Item
}

export const useItemActions = defineStore('itemActions', () => {
  const game = useGameStore()
  const toast = useToastStore()

  const pending = ref<{ kind: ItemActionKind; item: Item; mode: RerollMode } | null>(null)
  const result = ref<RerollResult | null>(null)
  const busy = ref(false)

  function requestRefine(item: Item) {
    result.value = null
    pending.value = { kind: 'refine', item, mode: 'random' }
  }

  function requestEnchant(item: Item, auto = false) {
    result.value = null
    pending.value = { kind: auto ? 'enchantAuto' : 'enchant', item, mode: 'random' }
  }

  function requestSell(item: Item) {
    result.value = null
    pending.value = { kind: 'sell', item, mode: 'random' }
  }

  function setMode(mode: RerollMode) {
    if (pending.value) pending.value.mode = mode
  }

  function cancel() {
    pending.value = null
  }

  function closeResult() {
    result.value = null
  }

  async function confirm() {
    const current = pending.value
    if (!current || busy.value) return
    busy.value = true
    try {
      if (current.kind === 'refine') {
        const res = await game.refine(current.item.id, current.mode)
        if (res) result.value = { kind: 'refine', before: res.before, after: res.after }
      } else if (current.kind === 'enchant') {
        const res = await game.enchant(current.item.id, false, current.mode)
        if (res) result.value = { kind: 'enchant', before: res.before, after: res.after }
      } else if (current.kind === 'enchantAuto') {
        const res = await game.enchant(current.item.id, true)
        if (res) result.value = { kind: 'enchant', before: res.before, after: res.after }
      } else if (current.kind === 'sell') {
        await game.sell([current.item.id])
      }
      pending.value = null
    } catch {
      toast.push('操作失败', 'error')
    } finally {
      busy.value = false
    }
  }

  return {
    pending,
    result,
    busy,
    requestRefine,
    requestEnchant,
    requestSell,
    setMode,
    cancel,
    closeResult,
    confirm,
  }
})
