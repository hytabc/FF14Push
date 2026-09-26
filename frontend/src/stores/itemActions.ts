import { defineStore } from 'pinia'
import { ref } from 'vue'

import { sound } from '@/game/audio'
import type { Item, RerollMode } from '@/game/types'
import { diffReroll } from '@/utils/rerollDiff'

import { useGameStore } from './game'
import { useToastStore } from './toast'

export type ItemActionKind = 'refine' | 'enchant' | 'sell' | 'enchantAuto'

/** 重造 / 附魔结果：用于展示逐条涨跌。 */
export interface RerollResult {
  kind: 'refine' | 'enchant'
  before: Item
  after: Item
  /** 本次实际连做的次数（金币/卡不足时可能小于请求值）。 */
  times: number
  /** 本次实际消耗的金币。 */
  cost: number
  /** 使用「重新打造卡」时实际消耗的张数（生产/采集专用装备）。 */
  useCard: boolean
  cardsCost: number
  /** 本次使用的模式，供「继续」沿用。 */
  mode: RerollMode
}

export const useItemActions = defineStore('itemActions', () => {
  const game = useGameStore()
  const toast = useToastStore()

  const pending = ref<{ kind: ItemActionKind; item: Item; mode: RerollMode; times: number; useCard: boolean } | null>(
    null,
  )
  const result = ref<RerollResult | null>(null)
  const busy = ref(false)

  function requestRefine(item: Item, useCard = false) {
    result.value = null
    // 「重新打造卡」只走「基于当前」逻辑。
    pending.value = { kind: 'refine', item, mode: useCard ? 'basedOnCurrent' : 'random', times: 1, useCard }
  }

  function requestEnchant(item: Item, auto = false, useCard = false) {
    result.value = null
    pending.value = {
      kind: auto ? 'enchantAuto' : 'enchant',
      item,
      mode: useCard ? 'basedOnCurrent' : 'random',
      times: 1,
      useCard,
    }
  }

  function requestSell(item: Item) {
    result.value = null
    pending.value = { kind: 'sell', item, mode: 'random', times: 1, useCard: false }
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

  /** 重造 / 附魔结果音效：先播滚动音，再按属性涨跌播升 / 降音；命中稀有词条额外加音。 */
  function playReroll(kind: 'refine' | 'enchant', before: Item, after: Item, hit = false): void {
    sound.play(kind === 'refine' ? 'reroll.roll' : 'enchant.cast')
    const changes = diffReroll(kind, before, after)
    if (changes.some((c) => c.direction === 'up')) sound.play('reroll.up')
    else if (changes.some((c) => c.direction === 'down')) sound.play('reroll.down')
    if (hit) sound.play('enchant.rare')
  }

  async function confirm() {
    const current = pending.value
    if (!current || busy.value) return
    busy.value = true
    try {
      if (current.kind === 'refine') {
        const res = await game.refine(current.item.id, current.mode, current.times, current.useCard)
        if (res) {
          result.value = {
            kind: 'refine',
            before: res.before,
            after: res.after,
            times: res.times,
            cost: res.cost,
            useCard: current.useCard,
            cardsCost: res.cardsCost ?? 0,
            mode: current.mode,
          }
          playReroll(current.kind, res.before, res.after)
        }
      } else if (current.kind === 'enchant') {
        const res = await game.enchant(current.item.id, false, current.mode, current.times, current.useCard)
        if (res) {
          result.value = {
            kind: 'enchant',
            before: res.before,
            after: res.after,
            times: res.times ?? res.attempts,
            cost: res.cost,
            useCard: current.useCard,
            cardsCost: res.cardsCost ?? 0,
            mode: current.mode,
          }
          playReroll('enchant', res.before, res.after, res.hit)
        }
      } else if (current.kind === 'enchantAuto') {
        const res = await game.enchant(current.item.id, true)
        if (res) {
          result.value = {
            kind: 'enchant',
            before: res.before,
            after: res.after,
            times: res.attempts,
            cost: res.cost,
            useCard: false,
            cardsCost: 0,
            mode: current.mode,
          }
          playReroll('enchant', res.before, res.after, res.hit)
        }
      } else if (current.kind === 'sell') {
        await game.sell([current.item.id])
        sound.play('ui.loot')
      }
      pending.value = null
    } catch {
      toast.push('操作失败', 'error')
      sound.play('ui.error')
    } finally {
      busy.value = false
    }
  }

  /** 结果页「继续」：用最新装备（含最新次数/价格）沿用上次模式与次数再操作一次。 */
  async function repeat() {
    const current = result.value
    if (!current || busy.value) return
    // 保留旧结果直到新结果返回，避免「继续」时弹窗闪回确认视图。
    pending.value = {
      kind: current.kind,
      item: current.after,
      mode: current.mode,
      times: current.times,
      useCard: current.useCard,
    }
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
