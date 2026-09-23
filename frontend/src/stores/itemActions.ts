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
  /** 本次实际连做的次数（金币不足时可能小于请求值）。 */
  times: number
  /** 本次实际消耗的金币。 */
  cost: number
  /** 本次使用的模式，供「继续」沿用。 */
  mode: RerollMode
}

export const useItemActions = defineStore('itemActions', () => {
  const game = useGameStore()
  const toast = useToastStore()

  const pending = ref<{ kind: ItemActionKind; item: Item; mode: RerollMode; times: number } | null>(null)
  const result = ref<RerollResult | null>(null)
  const busy = ref(false)

  function requestRefine(item: Item) {
    result.value = null
    pending.value = { kind: 'refine', item, mode: 'random', times: 1 }
  }

  function requestEnchant(item: Item, auto = false) {
    result.value = null
    pending.value = { kind: auto ? 'enchantAuto' : 'enchant', item, mode: 'random', times: 1 }
  }

  function requestSell(item: Item) {
    result.value = null
    pending.value = { kind: 'sell', item, mode: 'random', times: 1 }
  }

  function setMode(mode: RerollMode) {
    if (pending.value) pending.value.mode = mode
  }

  function setTimes(times: number) {
    if (pending.value) pending.value.times = Math.max(1, Math.min(50, Math.floor(times)))
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
        const res = await game.refine(current.item.id, current.mode, current.times)
        if (res)
          result.value = {
            kind: 'refine',
            before: res.before,
            after: res.after,
            times: res.times,
            cost: res.cost,
            mode: current.mode,
          }
      } else if (current.kind === 'enchant') {
        const res = await game.enchant(current.item.id, false, current.mode, current.times)
        if (res)
          result.value = {
            kind: 'enchant',
            before: res.before,
            after: res.after,
            times: res.times ?? res.attempts,
            cost: res.cost,
            mode: current.mode,
          }
      } else if (current.kind === 'enchantAuto') {
        const res = await game.enchant(current.item.id, true)
        if (res)
          result.value = {
            kind: 'enchant',
            before: res.before,
            after: res.after,
            times: res.attempts,
            cost: res.cost,
            mode: current.mode,
          }
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

  /** 结果页「继续」：用最新装备（含最新次数/价格）沿用上次模式与次数再操作一次。 */
  async function repeat() {
    const current = result.value
    if (!current || busy.value) return
    // 保留旧结果直到新结果返回，避免「继续」时弹窗闪回确认视图。
    pending.value = { kind: current.kind, item: current.after, mode: current.mode, times: current.times }
    await confirm()
  }

  return {
    pending,
    result,
    busy,
    requestRefine,
    requestEnchant,
    requestSell,
    setMode,
    setTimes,
    cancel,
    closeResult,
    confirm,
    repeat,
  }
})
