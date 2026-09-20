import { defineStore } from 'pinia'
import { ref } from 'vue'

import { useGameStore } from './game'
import { useToastStore } from './toast'
import type { Item, RerollMode } from '@/game/types'

export type ItemActionKind = 'refine' | 'enchant' | 'sell' | 'enchantAuto'

export const useItemActions = defineStore('itemActions', () => {
  const game = useGameStore()
  const toast = useToastStore()

  const pending = ref<{ kind: ItemActionKind; item: Item; mode: RerollMode } | null>(null)
  const busy = ref(false)

  function requestRefine(item: Item) {
    pending.value = { kind: 'refine', item, mode: 'random' }
  }

  function requestEnchant(item: Item, auto = false) {
    pending.value = { kind: auto ? 'enchantAuto' : 'enchant', item, mode: 'random' }
  }

  function requestSell(item: Item) {
    pending.value = { kind: 'sell', item, mode: 'random' }
  }

  function setMode(mode: RerollMode) {
    if (pending.value) pending.value.mode = mode
  }

  function cancel() {
    pending.value = null
  }

  async function confirm() {
    const current = pending.value
    if (!current || busy.value) return
    busy.value = true
    try {
      if (current.kind === 'refine') await game.refine(current.item.id, current.mode)
      else if (current.kind === 'enchant') await game.enchant(current.item.id, false, current.mode)
      else if (current.kind === 'enchantAuto') await game.enchant(current.item.id, true)
      else if (current.kind === 'sell') await game.sell([current.item.id])
      pending.value = null
    } catch {
      toast.push('操作失败', 'error')
    } finally {
      busy.value = false
    }
  }

  return { pending, busy, requestRefine, requestEnchant, requestSell, setMode, cancel, confirm }
})
