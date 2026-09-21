import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

import data from '@shared/schema'

import { api } from '@/api'
import type { FishCatch } from '@/game/types'
import { useGameStore } from '@/stores/game'
import { useToastStore } from '@/stores/toast'

/** 上报节拍：与服务端窗口对齐即可（服务端只认自己的时钟）。 */
const REPORT_MS = 1500

const TITLE_NAMES: Record<string, string> = Object.fromEntries(
  data.titles.titles.map((t) => [t.id, t.name]),
)

export type ActivityMode = 'idle' | 'gather' | 'produce' | 'fish'

/**
 * 生产 / 采集 / 钓鱼的后台自动循环。
 *
 * 与战斗一致：客户端只负责「定时上报 + 渲染」，产量与随机结果全由服务端结算。
 */
export const useDohDolStore = defineStore('dohdol', () => {
  const game = useGameStore()
  const toast = useToastStore()

  const mode = ref<ActivityMode>('idle')
  const sessionId = ref<number | null>(null)
  const busy = ref(false)
  const lastGained = ref<Array<{ name: string; count: number }>>([])
  const lastProduced = ref<Array<{ name: string; rarity: string }>>([])
  const lastCaught = ref<FishCatch[]>([])
  const insightRemaining = ref(0)

  let timer: number | null = null

  const state = computed(() => game.state?.dohdol ?? null)
  const isRunning = computed(() => mode.value !== 'idle')
  const active = computed(() => state.value?.active ?? [])

  function startLoop() {
    stopLoop()
    timer = window.setInterval(() => {
      void reportOnce()
    }, REPORT_MS)
  }

  function stopLoop() {
    if (timer !== null) {
      window.clearInterval(timer)
      timer = null
    }
  }

  async function reportOnce() {
    if (sessionId.value === null || busy.value) return
    busy.value = true
    try {
      if (mode.value === 'gather') {
        const r = await api.gatherReport(sessionId.value)
        lastGained.value = r.gained
      } else if (mode.value === 'produce') {
        const r = await api.produceReport(sessionId.value)
        lastGained.value = r.materials
        if (r.items.length) {
          lastProduced.value = r.items.map((i) => ({ name: i.name, rarity: i.rarity }))
          for (const item of r.items) {
            toast.push(`制造出 ${item.name}（高品质）`, 'loot')
          }
        }
      } else if (mode.value === 'fish') {
        const r = await api.fishReport(sessionId.value)
        lastGained.value = r.gained
        lastCaught.value = r.caught
        insightRemaining.value = r.insightRemainingSec
        for (const title of r.newTitles) {
          toast.push(`达成称号「${TITLE_NAMES[title] ?? title}」`, 'success')
        }
      }
      await game.loadState()
    } catch {
      await stop(true)
    } finally {
      busy.value = false
    }
  }

  async function startGather(jobId: string, regionId: number) {
    await stop(true)
    await game.stopBattle(true)
    const res = await api.gatherStart(jobId, regionId)
    sessionId.value = res.sessionId
    mode.value = 'gather'
    lastGained.value = []
    startLoop()
  }

  async function startProduce(jobId: string, recipeId: string) {
    await stop(true)
    await game.stopBattle(true)
    const res = await api.produceStart(jobId, recipeId)
    sessionId.value = res.sessionId
    mode.value = 'produce'
    lastGained.value = []
    lastProduced.value = []
    startLoop()
  }

  async function startFish(regionId: number) {
    await stop(true)
    await game.stopBattle(true)
    const res = await api.fishStart(regionId)
    sessionId.value = res.sessionId
    mode.value = 'fish'
    lastCaught.value = []
    insightRemaining.value = 0
    startLoop()
  }

  async function stop(silent = false) {
    stopLoop()
    const id = sessionId.value
    const current = mode.value
    mode.value = 'idle'
    sessionId.value = null
    if (id === null) return
    try {
      if (current === 'gather') await api.gatherStop(id)
      else if (current === 'produce') await api.produceStop(id)
      else if (current === 'fish') await api.fishStop(id)
    } catch (err) {
      if (!silent) throw err
    }
  }

  async function useConsumable(itemId: string) {
    const res = await api.consume(itemId)
    toast.push(`已使用 ${res.name}（${res.durationSec}s）`, 'success')
    await game.loadState()
  }

  function handleVisibility() {
    if (document.hidden && isRunning.value) {
      void stop(true)
    }
  }

  return {
    mode,
    sessionId,
    busy,
    lastGained,
    lastProduced,
    lastCaught,
    insightRemaining,
    state,
    isRunning,
    active,
    startGather,
    startProduce,
    startFish,
    stop,
    useConsumable,
    handleVisibility,
  }
})
