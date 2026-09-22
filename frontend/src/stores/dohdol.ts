import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

import data from '@shared/schema'

import { api } from '@/api'
import { ProgressClock } from '@/game/core/progress'
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
  const lastGained = ref<Array<{ itemId: string; name: string; count: number }>>([])
  const lastProduced = ref<Array<{ baseId: string; name: string; rarity: string }>>([])
  const lastCaught = ref<FishCatch[]>([])
  const insightRemaining = ref(0)
  /** 当前生产会话选中的配方（用于判断材料是否耗尽）。 */
  const recipeId = ref<string | null>(null)
  /** 本次生产的目标件数（null = 不限）与已制造件数。 */
  const targetCount = ref<number | null>(null)
  const producedCount = ref(0)

  // 单次动作进度：与服务端下发的 cycle（秒/余额）对齐，用单调时钟插值展示。
  const progress = ref(0)
  const clock = new ProgressClock()

  let timer: number | null = null
  let ticker: number | null = null
  let lastTickMs = 0

  const state = computed(() => game.state?.dohdol ?? null)
  const isRunning = computed(() => mode.value !== 'idle')
  const active = computed(() => state.value?.active ?? [])
  const progressPct = computed(() => Math.round(progress.value * 100))
  /** 生产时材料不足 → 循环空转，UI 需要提示。 */
  const starved = computed(() => {
    if (mode.value !== 'produce' || !recipeId.value) return false
    const recipe = state.value?.recipes.find((r) => r.id === recipeId.value)
    return recipe ? recipe.craftable <= 0 : false
  })

  function renderProgress() {
    progress.value = clock.position()
  }

  function syncCycle(cycle: { seconds: number; credit: number } | undefined, rttMs = 0) {
    // 半 RTT 校正：响应到达时，服务端时间约为「响应生成时刻 + RTT/2」。
    // credit 是服务端生成响应那一刻的余额，把它推进到「客户端现在」，
    // 进度条跑满的时刻才与服务端产出时刻对齐（也不用依赖客户端时钟）。
    const seconds = cycle?.seconds ?? 0
    clock.sync((cycle?.credit ?? 0) * 1000 + Math.max(0, rttMs) / 2, seconds)
    lastTickMs = performance.now()
    renderProgress()
  }

  /** 发请求并返回 [结果, 往返毫秒]，供 cycle 做半 RTT 校正。 */
  async function timed<T>(fn: () => Promise<T>): Promise<[T, number]> {
    const started = performance.now()
    const result = await fn()
    return [result, performance.now() - started]
  }

  function startTicker() {
    if (ticker !== null) return
    lastTickMs = performance.now()
    renderProgress()
    ticker = window.setInterval(() => {
      const now = performance.now()
      const delta = now - lastTickMs
      lastTickMs = now
      progress.value = clock.advance(delta)
    }, 100)
  }

  function stopTicker() {
    if (ticker !== null) {
      window.clearInterval(ticker)
      ticker = null
    }
    // 注意：这里不能清空时钟 —— startLoop() 会先 stopLoop() 再 startTicker()，
    // 而时钟相位由紧接着 startLoop 之前的 syncCycle 写入；清掉会把刚对齐的进度打回 0。
    progress.value = 0
  }

  function startLoop() {
    stopLoop()
    timer = window.setInterval(() => {
      void reportOnce()
    }, REPORT_MS)
    startTicker()
  }

  function stopLoop() {
    if (timer !== null) {
      window.clearInterval(timer)
      timer = null
    }
    stopTicker()
  }

  async function reportOnce() {
    if (sessionId.value === null || busy.value) return
    busy.value = true
    try {
      if (mode.value === 'gather') {
        const [r, rtt] = await timed(() => api.gatherReport(sessionId.value!))
        lastGained.value = r.gained
        syncCycle(r.cycle, rtt)
      } else if (mode.value === 'produce') {
        const [r, rtt] = await timed(() => api.produceReport(sessionId.value!))
        lastGained.value = r.materials
        targetCount.value = r.targetActions
        producedCount.value = r.producedTotal
        if (r.finished) {
          // 达到目标件数：服务端已结束会话，本地直接收尾（不再调用 stop 接口）。
          settle()
          toast.push(`制造完成，共 ${r.producedTotal} 件`, 'success')
        } else {
          syncCycle(r.cycle, rtt)
        }
        if (r.items.length) {
          lastProduced.value = r.items.map((i) => ({ baseId: i.baseId, name: i.name, rarity: i.rarity }))
          for (const item of r.items) {
            toast.push(`制造出 ${item.name}（高品质）`, 'loot')
          }
        }
      } else if (mode.value === 'fish') {
        const [r, rtt] = await timed(() => api.fishReport(sessionId.value!))
        lastGained.value = r.gained
        lastCaught.value = r.caught
        insightRemaining.value = r.insightRemainingSec
        syncCycle(r.cycle, rtt)
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
    const [res, rtt] = await timed(() => api.gatherStart(jobId, regionId))
    sessionId.value = res.sessionId
    mode.value = 'gather'
    recipeId.value = null
    lastGained.value = []
    syncCycle(res.cycle, rtt)
    startLoop()
  }

  /** 开始生产。count=null 表示「制作全部」（按当前材料上限）。 */
  async function startProduce(jobId: string, recipeId_: string, count: number | null = null) {
    await stop(true)
    await game.stopBattle(true)
    const [res, rtt] = await timed(() => api.produceStart(jobId, recipeId_, count))
    sessionId.value = res.sessionId
    mode.value = 'produce'
    recipeId.value = res.recipeId
    targetCount.value = res.targetActions
    producedCount.value = 0
    lastGained.value = []
    lastProduced.value = []
    syncCycle(res.cycle, rtt)
    startLoop()
  }

  async function startFish(regionId: number) {
    await stop(true)
    await game.stopBattle(true)
    const [res, rtt] = await timed(() => api.fishStart(regionId))
    sessionId.value = res.sessionId
    mode.value = 'fish'
    recipeId.value = null
    lastCaught.value = []
    insightRemaining.value = 0
    syncCycle(res.cycle, rtt)
    startLoop()
  }

  /** 本地收尾：清空会话状态但不调用 stop 接口（服务端已自动结束会话时用）。 */
  function settle() {
    stopLoop()
    clock.reset()
    mode.value = 'idle'
    sessionId.value = null
    recipeId.value = null
  }

  async function stop(silent = false) {
    const id = sessionId.value
    const current = mode.value
    settle()
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
    // 同一件叠加 / 换种类重置：提示当前该槽位的剩余时长，而不是单次时长
    const active = res.active.find((a) => a.kind === res.kind)
    const remaining = active ? `，剩余 ${active.remainingSec}s` : ''
    toast.push(`已使用 ${res.name}（+${res.durationSec}s${remaining}）`, 'success')
    await game.loadState()
  }

  /** 出售堆叠物品（采集材料 / 半成品 / 鱼获 / 药水食物）。 */
  async function sellStack(kind: string, itemId: string, count: number) {
    const res = await api.sellStack(kind, itemId, count)
    toast.push(`出售 ${res.name} ×${res.count}，获得 ${res.goldGained} 金币`, 'success')
    await game.loadState()
  }

  /** 批量出售：逐项结算，最后统一刷新一次状态。 */
  async function sellStacks(entries: Array<{ kind: string; itemId: string; count: number }>) {
    let gold = 0
    let sold = 0
    for (const entry of entries) {
      if (entry.count <= 0) continue
      try {
        const res = await api.sellStack(entry.kind, entry.itemId, entry.count)
        gold += res.goldGained
        sold += res.count
      } catch {
        /* 单项失败（如数量不足）不影响其余 */
      }
    }
    if (sold > 0) {
      toast.push(`出售 ${sold} 件，获得 ${gold} 金币`, 'success')
      await game.loadState()
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
    recipeId,
    targetCount,
    producedCount,
    progressPct,
    starved,
    state,
    isRunning,
    active,
    startGather,
    startProduce,
    startFish,
    stop,
    useConsumable,
    sellStack,
    sellStacks,
  }
})
