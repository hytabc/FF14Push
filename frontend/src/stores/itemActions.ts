import { defineStore } from 'pinia'
import { ref } from 'vue'

import { useGameStore } from './game'
import { useToastStore } from './toast'
import type { Item } from '@/game/types'

export type ItemActionKind = 'refine' | 'enchant' | 'sell' | 'enchantAuto'

export const useItemActions = defineStore('itemActions', () => {
  const game = useGameStore()
  const toast = useToastStore()

  const pending = ref<{ kind: ItemActionKind; item: Item } | null>(null)
  const busy = ref(false)

  function requestRefine(item: Item) {
    pending.value = { kind: 'refine', item }
  }

  function requestEnchant(item: Item, auto = false) {
    pending.value = { kind: auto ? 'enchantAuto' : 'enchant', item }
  }

  function requestSell(item: Item) {
    pending.value = { kind: 'sell', item }
  }

  function cancel() {
    pending.value = null
  }

  async function confirm() {
    const current = pending.value
    if (!current || busy.value) return
    busy.value = true
    try {
      if (current.kind === 'refine') await game.refine(current.item.id)
      else if (current.kind === 'enchant') await game.enchant(current.item.id, false)
      else if (current.kind === 'enchantAuto') await game.enchant(current.item.id, true)
      else if (current.kind === 'sell') await game.sell([current.item.id])
      pending.value = null
    } catch {
      toast.push('操作失败', 'error')
    } finally {
      busy.value = false
    }
  }

  return { pending, busy, requestRefine, requestEnchant, requestSell, cancel, confirm }
})
