import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

import { api } from '@/api'
import { sound } from '@/game/audio'
import { ProgressClock } from '@/game/core/progress'
import type { ActivityLogEntry, IshgardLeaderboardEntry, IshgardState } from '@/game/types'
import { activityExpLog } from '@/utils/battleLog'
import { formatNumber } from '@/utils/format'
import { useGameStore } from '@/stores/game'
import { useToastStore } from '@/stores/toast'

/** 最长轮询间隔；临近动作完成时提前结算。 */
const REPORT_MS = 1500
/** 页面切到后台时的上报间隔：服务端按真实窗口结算，产出不变。 */
const HIDDEN_REPORT_MS = 5000
/** 全量状态刷新节流。 */
const STATE_REFRESH_MS = 5000
const MAX_LOG = 120

function isPageHidden(): boolean {
  return typeof document !== 'undefined' && document.hidden
}

export type IshgardMode = 'idle' | 'gather' | 'fish' | 'produce'

/**
 * 「重建伊修加德」的后台自动循环：与采集 / 生产 / 钓鱼同构——
 * 客户端只负责定时上报与渲染，产量、积分与阶段推进全由服务端结算。
 */
export const useIshgardStore = defineStore('ishgard', () => {
  const game = useGameStore()
  const toast = useToastStore()

  const state = ref<IshgardState | null>(null)
  const loading = ref(false)
  const mode = ref<IshgardMode>('idle')
  const sessionId = ref<number | null>(null)
  const busy = ref(false)
  const recipeId = ref<string | null>(null)
  const targetCount = ref<number | null>(null)
  const producedCount = ref(0)
  const lastGained = ref<Array<{ itemId: string; name: string; count: number }>>([])
  const logEntries = ref<ActivityLogEntry[]>([])
  const leaderboard = ref<IshgardLeaderboardEntry[]>([])
  const boardPage = ref(1)

  const progress = ref(0)
  const clock = new ProgressClock()

  let timer: number | null = null
  let ticker: number | null = null
  let lastTickMs = 0
  let nextActionAt = 0
  let logSeq = 0
  let lastStateRefreshAt = 0

  const isRunning = computed(() => mode.value !== 'idle')
  const progressPct = computed(() => Math.round(progress.value * 100))

  function pushLog(text: string, tone: ActivityLogEntry['tone']) {
    logEntries.value.push({ id: ++logSeq, text, tone })
    if (logEntries.value.length > MAX_LOG) {
      logEntries.value.splice(0, logEntries.value.length - MAX_LOG)
    }
  }

  function renderProgress() {
    progress.value = clock.position()
  }

  function syncCycle(cycle: { seconds: number; credit: number } | undefined, rttMs = 0) {
    const seconds = cycle?.seconds ?? 0
    clock.sync((cycle?.credit ?? 0) * 1000 + Math.max(0, rttMs) / 2, seconds)
    lastTickMs = performance.now()
    nextActionAt =
      lastTickMs + Math.max(0, seconds * 1000 - (cycle?.credit ?? 0) * 1000 - Math.max(0, rttMs) / 2)
    renderProgress()
  }

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
      if (!isPageHidden()) progress.value = clock.advance(delta)
    }, 100)
  }

  function stopTicker() {
    if (ticker !== null) {
      window.clearInterval(ticker)
      ticker = null
    }
    progress.value = 0
  }

  function startLoop() {
    stopLoop()
    scheduleReport()
    startTicker()
  }

  function scheduleReport() {
    if (!isRunning.value) return
    const due = nextActionAt - performance.now()
    const interval = isPageHidden()
      ? Math.min(HIDDEN_REPORT_MS, Math.max(2000, due))
      : Math.min(REPORT_MS, due)
    timer = window.setTimeout(() => {
      timer = null
      void reportOnce()
    }, Math.max(50, interval))
  }

  function stopLoop() {
    if (timer !== null) {
      window.clearTimeout(timer)
      timer = null
    }
    stopTicker()
  }

  function refreshStateIfDue(force: boolean) {
    if (!force && performance.now() - lastStateRefreshAt < STATE_REFRESH_MS) return
    lastStateRefreshAt = performance.now()
    void load()
  }

  function settle() {
    stopLoop()
    clock.reset()
    mode.value = 'idle'
    sessionId.value = null
    recipeId.value = null
    lastStateRefreshAt = 0
  }

  async function reportOnce() {
    if (sessionId.value === null) return
    if (busy.value) {
      scheduleReport()
      return
    }
    const id = sessionId.value
    busy.value = true
    let leveledUp = false
    try {
      if (mode.value === 'gather') {
        const [r, rtt] = await timed(() => api.ishgardGatherReport(id))
        if (sessionId.value !== id) return
        lastGained.value = r.gained
        if (r.gained.length) {
          pushLog(`采集 ${r.actions} 次：${r.gained.map((g) => `${g.name} ×${g.count}`).join('、')}`, 'loot')
          sound.play('gather.gain')
        }
        if (r.xp > 0 && r.xpBreakdown) pushLog(activityExpLog(r.xpBreakdown), 'exp')
        if (r.level?.levelsGained > 0) leveledUp = true
        syncCycle(r.cycle, rtt)
      } else if (mode.value === 'fish') {
        const [r, rtt] = await timed(() => api.ishgardFishReport(id))
        if (sessionId.value !== id) return
        lastGained.value = r.gained
        if (r.gained.length) {
          pushLog(`钓起：${r.gained.map((g) => `${g.name} ×${g.count}`).join('、')}`, 'loot')
          sound.play('fish.catch')
        }
        if (r.xp > 0 && r.xpBreakdown) pushLog(activityExpLog(r.xpBreakdown), 'exp')
        if (r.level?.levelsGained > 0) leveledUp = true
        syncCycle(r.cycle, rtt)
      } else if (mode.value === 'produce') {
        const [r, rtt] = await timed(() => api.ishgardProduceReport(id))
        if (sessionId.value !== id) return
        if (r.expired) {
          // 阶段推进 → 本阶段配方失效：静默收尾（不弹窗、不再重试）。
          settle()
          toast.push('本次重建阶段已推进，本阶段配方已失效', 'info')
          await load()
          return
        }
        targetCount.value = r.targetActions
        producedCount.value = r.producedTotal
        if (r.crafts > 0) {
          const produced = r.produced.map((p) => `${p.name} ×${p.count}`).join('、')
          pushLog(`生产 ${r.crafts} 次：${produced}`, 'loot')
          sound.play('produce.craft')
        }
        if (r.xp > 0 && r.xpBreakdown) pushLog(activityExpLog(r.xpBreakdown), 'exp')
        if (r.level?.levelsGained > 0) leveledUp = true
        if (r.finished) {
          settle()
          leveledUp = true
          toast.push(`生产完成，共 ${r.producedTotal} 件`, 'success')
        } else {
          syncCycle(r.cycle, rtt)
        }
      }
      refreshStateIfDue(leveledUp)
    } catch {
      if (sessionId.value === id) await stop(true)
    } finally {
      busy.value = false
      if (timer === null && isRunning.value) scheduleReport()
    }
  }

  async function load() {
    loading.value = true
    try {
      state.value = await api.ishgardState()
    } finally {
      loading.value = false
    }
  }

  async function loadLeaderboard(page = 1) {
    const body = await api.ishgardLeaderboard(page)
    leaderboard.value = body.entries
    boardPage.value = body.page
    return body
  }

  async function startGather(jobId: string) {
    await stop(true)
    await game.stopBattle(true)
    const [res, rtt] = await timed(() => api.ishgardGatherStart(jobId))
    sessionId.value = res.sessionId
    mode.value = 'gather'
    recipeId.value = null
    lastGained.value = []
    logEntries.value = []
    syncCycle(res.cycle, rtt)
    startLoop()
  }

  async function startFish() {
    await stop(true)
    await game.stopBattle(true)
    const [res, rtt] = await timed(() => api.ishgardFishStart())
    sessionId.value = res.sessionId
    mode.value = 'fish'
    recipeId.value = null
    lastGained.value = []
    logEntries.value = []
    syncCycle(res.cycle, rtt)
    startLoop()
    sound.play('fish.cast')
  }

  async function startProduce(jobId: string, recipeIdValue: string, count: number | null = null) {
    await stop(true)
    await game.stopBattle(true)
    const [res, rtt] = await timed(() => api.ishgardProduceStart(jobId, recipeIdValue, count))
    sessionId.value = res.sessionId
    mode.value = 'produce'
    recipeId.value = res.recipeId
    targetCount.value = res.targetActions
    producedCount.value = 0
    lastGained.value = []
    logEntries.value = []
    syncCycle(res.cycle, rtt)
    startLoop()
  }

  async function stop(silent = false) {
    const id = sessionId.value
    const current = mode.value
    if (id !== null && current !== 'idle') {
      try {
        if (current === 'gather') await api.ishgardGatherStop(id)
        else if (current === 'fish') await api.ishgardFishStop(id)
        else if (current === 'produce') await api.ishgardProduceStop(id)
      } catch {
        // 服务端可能已自动结束会话：忽略
      }
    }
    settle()
    if (!silent) await load()
  }

  async function submit(itemId: string, count: number) {
    const result = await api.ishgardSubmit(itemId, count)
    sound.play('produce.high')
    toast.push(`提交成功，获得 ${formatNumber(result.gained)} 积分`, 'success')
    for (const stage of result.completedStages) {
      toast.push(`全服已完成第 ${stage} 次重建！`, 'success')
    }
    lastStateRefreshAt = 0
    await load()
    return result
  }

  async function sell(itemId: string, count: number) {
    const result = await api.ishgardSell(itemId, count)
    toast.push(`出售 +${formatNumber(result.gold)} 金币`, 'loot')
    await load()
    return result
  }

  async function claimTool(kind: 'doh' | 'dol') {
    const tool = await api.ishgardToolClaim(kind)
    toast.push(`获得天穹主手工具（Lv.${tool.level}）`, 'success')
    await load()
    return tool
  }

  async function upgradeTool(kind: 'doh' | 'dol') {
    const tool = await api.ishgardToolUpgrade(kind)
    toast.push(`主手工具升级至 Lv.${tool.level}`, 'success')
    await load()
    return tool
  }

  async function rerollPink(kind: 'doh' | 'dol') {
    const tool = await api.ishgardToolEnchant(kind)
    toast.push(`紫色附魔已重铸：${tool.pink?.name ?? ''}`, 'success')
    await load()
    return tool
  }

  return {
    state,
    loading,
    mode,
    sessionId,
    busy,
    recipeId,
    targetCount,
    producedCount,
    lastGained,
    logEntries,
    leaderboard,
    boardPage,
    progress,
    progressPct,
    isRunning,
    load,
    loadLeaderboard,
    startGather,
    startFish,
    startProduce,
    stop,
    submit,
    sell,
    claimTool,
    upgradeTool,
    rerollPink,
  }
})
