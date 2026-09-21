import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

import { useGameStore } from './game'
import type { Item } from '@/game/types'

/** 装备标签的弹窗状态与操作：给某件装备贴标签，或管理标签本身。 */
export const useTagsStore = defineStore('tags', () => {
  const game = useGameStore()

  // 正在贴标签的装备 id（null 表示未在贴标签）
  const assignItemId = ref<number | null>(null)
  // 是否打开「管理标签」
  const manageOpen = ref(false)
  const busy = ref(false)

  const open = computed(() => assignItemId.value !== null || manageOpen.value)
  const assignItem = computed<Item | null>(() =>
    assignItemId.value === null ? null : (game.items.find((i) => i.id === assignItemId.value) ?? null),
  )

  function openAssign(item: Item) {
    manageOpen.value = false
    assignItemId.value = item.id
  }

  function openManage() {
    assignItemId.value = null
    manageOpen.value = true
  }

  function close() {
    assignItemId.value = null
    manageOpen.value = false
  }

  async function toggleOnItem(tagId: number) {
    const item = assignItem.value
    if (!item || busy.value) return
    const current = item.tagIds ?? []
    const next = current.includes(tagId) ? current.filter((id) => id !== tagId) : [...current, tagId]
    busy.value = true
    try {
      await game.setItemTags(item.id, next)
    } finally {
      busy.value = false
    }
  }

  /** 新建标签；若正在给某件装备贴标签，则创建后直接贴上。 */
  async function createTag(name: string, color: string) {
    if (busy.value || !name.trim()) return null
    busy.value = true
    try {
      const tag = await game.createTag(name.trim(), color)
      const item = assignItem.value
      if (tag && item) await game.setItemTags(item.id, [...(item.tagIds ?? []), tag.id])
      return tag
    } finally {
      busy.value = false
    }
  }

  async function rename(id: number, name: string) {
    if (busy.value || !name.trim()) return
    busy.value = true
    try {
      await game.updateTag(id, { name: name.trim() })
    } finally {
      busy.value = false
    }
  }

  async function recolor(id: number, color: string) {
    if (busy.value) return
    busy.value = true
    try {
      await game.updateTag(id, { color })
    } finally {
      busy.value = false
    }
  }

  async function remove(id: number) {
    if (busy.value) return
    busy.value = true
    try {
      return await game.deleteTag(id)
    } finally {
      busy.value = false
    }
  }

  return {
    assignItem,
    manageOpen,
    busy,
    open,
    openAssign,
    openManage,
    close,
    toggleOnItem,
    createTag,
    rename,
    recolor,
    remove,
  }
})
