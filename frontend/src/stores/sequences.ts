import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

import { api } from '@/api'
import { toApiError } from '@/api/client'
import type { SavedSequence } from '@/game/types'
import { useDohDolStore } from './dohdol'
import { useToastStore } from './toast'

/** 每账号最多保存的序列数（与后端 services/sequences.MAX_SEQUENCES_PER_USER 一致）。 */
export const MAX_SEQUENCES = 5

interface SequencePayload {
  name: string
  steps: SavedSequence['steps']
  loopMode: SavedSequence['loopMode']
  loopTotal: number
}

/** 自定义序列库：保存 / 覆盖 / 读取序列，以及凭蓝图ID导入。 */
export const useSequencesStore = defineStore('sequences', () => {
  const dohdol = useDohDolStore()
  const toast = useToastStore()

  const list = ref<SavedSequence[]>([])
  const loading = ref(false)
  const busy = ref(false)
  const open = ref(false)

  const count = computed(() => list.value.length)
  const full = computed(() => count.value >= MAX_SEQUENCES)
  const canSave = computed(() => dohdol.sequence.length > 0)

  function byName(name: string): SavedSequence | undefined {
    const key = name.trim()
    return list.value.find((s) => s.name === key)
  }

  function fail(e: unknown) {
    const err = toApiError(e)
    // 封号 / 顶号 / 设备超限由全局拦截器处理，不在这里弹提示。
    if (err.code === 'banned' || err.code === 'session_replaced' || err.code === 'device_limit') return
    toast.push(err.message, 'error')
  }

  async function load() {
    loading.value = true
    try {
      list.value = (await api.sequences()).sequences
    } catch (e) {
      fail(e)
    } finally {
      loading.value = false
    }
  }

  async function openLib() {
    open.value = true
    await load()
  }

  function close() {
    open.value = false
  }

  /** 当前编辑区的快照（保存 / 覆盖的来源）。 */
  function currentQueue(): { steps: SavedSequence['steps']; loopMode: SavedSequence['loopMode']; loopTotal: number } {
    return {
      steps: dohdol.sequence.map((s) => ({ ...s })),
      loopMode: dohdol.loopMode,
      loopTotal: dohdol.loopTotal,
    }
  }

  /** 保存当前编辑区为序列；同名则覆盖已有序列（蓝图ID不变）。 */
  async function saveCurrent(name: string): Promise<boolean> {
    const clean = name.trim()
    if (!clean || busy.value) return false
    if (!dohdol.sequence.length) {
      toast.push('序列为空，请先添加步骤', 'error')
      return false
    }
    busy.value = true
    const existed = byName(clean)
    try {
      await api.saveSequence({ name: clean, ...currentQueue() })
      list.value = (await api.sequences()).sequences
      toast.push(existed ? `已覆盖序列「${clean}」` : `已保存序列「${clean}」`, 'success')
      return true
    } catch (e) {
      fail(e)
      return false
    } finally {
      busy.value = false
    }
  }

  /** 用当前编辑区覆盖指定槽位（蓝图ID不变）。 */
  async function overwriteSlot(slot: SavedSequence): Promise<boolean> {
    if (busy.value) return false
    if (!dohdol.sequence.length) {
      toast.push('序列为空，请先添加步骤', 'error')
      return false
    }
    busy.value = true
    try {
      await api.overwriteSequence(slot.id, currentQueue())
      list.value = (await api.sequences()).sequences
      toast.push(`已覆盖序列「${slot.name}」`, 'success')
      return true
    } catch (e) {
      fail(e)
      return false
    } finally {
      busy.value = false
    }
  }

  async function remove(id: number): Promise<boolean> {
    if (busy.value) return false
    busy.value = true
    try {
      await api.deleteSequence(id)
      list.value = list.value.filter((s) => s.id !== id)
      toast.push('已删除序列', 'success')
      return true
    } catch (e) {
      fail(e)
      return false
    } finally {
      busy.value = false
    }
  }

  /** 把一条序列载入编辑区（替换当前队列，不占用槽位）。 */
  function applyPayload(payload: SequencePayload): boolean {
    if (!dohdol.loadSequence({ steps: payload.steps, loopMode: payload.loopMode, loopTotal: payload.loopTotal })) {
      return false
    }
    close()
    return true
  }

  /** 读取已保存的序列到编辑区。 */
  function readSlot(slot: SavedSequence): boolean {
    if (!applyPayload(slot)) return false
    toast.push(`已读取序列「${slot.name}」`, 'success')
    return true
  }

  /** 凭蓝图ID导入其他玩家的序列（载入编辑区，不占用槽位）。 */
  async function importByCode(code: string): Promise<boolean> {
    const clean = code.trim().toUpperCase()
    if (!clean || busy.value) return false
    busy.value = true
    try {
      const res = await api.importBlueprint(clean)
      if (!applyPayload(res.sequence)) return false
      toast.push(`已导入蓝图「${res.sequence.name}」`, 'success')
      return true
    } catch (e) {
      const err = toApiError(e)
      toast.push(err.status === 404 ? '蓝图ID不存在' : err.message, 'error')
      return false
    } finally {
      busy.value = false
    }
  }

  return {
    list,
    loading,
    busy,
    open,
    count,
    full,
    canSave,
    byName,
    load,
    openLib,
    close,
    saveCurrent,
    overwriteSlot,
    remove,
    readSlot,
    importByCode,
  }
})
