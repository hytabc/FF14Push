import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

import { api } from '@/api'
import { sound } from '@/game/audio'
import { resolveGatherAvailability } from '@/game/core/gather'
import { ProgressClock } from '@/game/core/progress'
import type { SequenceLoopMode, SequenceStep, StepResult, StepStatus } from '@/game/core/sequence'
import { gatherStepIssue, SEQ_STEP_LIMIT, stepKey } from '@/game/core/sequence'
import type { FishCatch, ActivityLogEntry, FishConditionsView, FishInsightView } from '@/game/types'
import { activityExpLog } from '@/utils/battleLog'
import { titleName } from '@/utils/titles'
import { useGameStore } from '@/stores/game'
import { useToastStore } from '@/stores/toast'

/** 最长轮询间隔；临近动作完成时提前结算，同时定期获取属性变化后的周期。 */
const REPORT_MS = 1500
/** 页面切到后台时的上报间隔：服务端按真实窗口结算（上限见 dohdol-levels.json），产出不变。 */
const HIDDEN_REPORT_MS = 5000
/** 全量状态刷新节流：产出 / 进度已由上报响应驱动界面，不必每次上报都拉 `/game/state`。 */
const STATE_REFRESH_MS = 5000

/** 页面是否处于后台（Node 测试环境没有 document，按「可见」处理以免误降频）。 */
function isPageHidden(): boolean {
  return typeof document !== 'undefined' && document.hidden
}

/** 生产 / 采集日志保留的最大条数，超出后裁掉最旧的（与战斗日志同策略）。 */
const MAX_LOG = 120

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
  /** 生效中的「捕鱼人之识」列表（每种直觉只绑定一条鱼，各自倒计时）。 */
  const insights = ref<FishInsightView[]>([])
  /** 当前钓场的天气 / 艾欧泽亚时间条件（服务端下发）。 */
  const conditions = ref<FishConditionsView | null>(null)
  /** 生产 / 采集日志：按结算轮次追加「获取数量 + 经验明细」。 */
  const logEntries = ref<ActivityLogEntry[]>([])
  /** 当前生产会话选中的配方（用于判断材料是否耗尽）。 */
  const recipeId = ref<string | null>(null)
  /** 本次生产的目标件数（null = 不限）与已制造件数。 */
  const targetCount = ref<number | null>(null)
  const producedCount = ref(0)

  // 采集 / 制作序列：按顺序自动执行多个会话。仅当前页面会话有效（离开页面即停止）。
  const sequence = ref<SequenceStep[]>([])
  const seqActive = ref(false)
  const seqIndex = ref(-1)
  /** 当前采集步「序列开始后」新采到的目标材料数量。 */
  const seqGained = ref(0)
  const seqResults = ref<StepResult[]>([])
  /** 循环模式（默认不循环，保持旧行为）；count 表示跑完 loopTotal 轮后停止。 */
  const loopMode = ref<SequenceLoopMode>('once')
  const loopTotal = ref(3)
  /** 当前轮次，从 1 起。 */
  const loopRound = ref(1)

  // 单次动作进度：与服务端下发的 cycle（秒/余额）对齐，用单调时钟插值展示。
  const progress = ref(0)
  const clock = new ProgressClock()

  let timer: number | null = null
  let ticker: number | null = null
  let lastTickMs = 0
  let nextActionAt = 0
  let logSeq = 0
  /** 上次全量状态刷新时刻（节流用）。 */
  let lastStateRefreshAt = 0

  /** 按节流刷新全量状态；升级等关键变化传 force 立即刷新。 */
  function refreshStateIfDue(force: boolean) {
    if (!force && performance.now() - lastStateRefreshAt < STATE_REFRESH_MS) return
    lastStateRefreshAt = performance.now()
    void game.loadState({ force: true })
  }

  function pushLog(text: string, tone: ActivityLogEntry['tone']) {
    logEntries.value.push({ id: ++logSeq, text, tone })
    if (logEntries.value.length > MAX_LOG) {
      logEntries.value.splice(0, logEntries.value.length - MAX_LOG)
    }
  }

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
  /** 当前正在执行的序列步骤（未运行序列时为 null）。 */
  const currentSeqStep = computed(() =>
    seqActive.value ? sequence.value[seqIndex.value] ?? null : null,
  )

  /** 状态已加载时判断地区是否解锁；未加载时乐观视为已解锁，避免误拦。 */
  function isRegionUnlocked(regionId: number): boolean {
    if (!game.state) return true
    const entry = game.state.regionProgress?.[String(regionId)]
    return entry ? entry.unlocked : regionId === 1
  }

  const dolLevel = computed(() => state.value?.progress?.dol?.level ?? 1)

  /** 序列中当前无法执行的步骤及原因（状态未加载时返回空，避免误拦）。 */
  const sequenceIssues = computed<Array<{ id: string; name: string; reason: string }>>(() => {
    const s = state.value
    if (!s) return []
    const issues: Array<{ id: string; name: string; reason: string }> = []
    for (const step of sequence.value) {
      if (step.kind === 'gather') {
        const reason = gatherStepIssue(step, isRegionUnlocked, dolLevel.value)
        if (reason) issues.push({ id: step.id, name: step.name, reason })
      } else {
        const recipe = s.recipes.find((r) => r.id === step.recipeId)
        if (recipe && !recipe.unlocked) {
          issues.push({ id: step.id, name: step.name, reason: `需要生产等级 Lv.${recipe.requiredLevel}` })
        }
      }
    }
    return issues
  })
  const sequenceBlocked = computed(() => sequenceIssues.value.length > 0)

  function renderProgress() {
    progress.value = clock.position()
  }

  function syncCycle(cycle: { seconds: number; credit: number } | undefined, rttMs = 0) {
    // 半 RTT 校正：响应到达时，服务端时间约为「响应生成时刻 + RTT/2」。
    // credit 是服务端结算时刻的余额，把它近似推进到「客户端现在」，
    // 进度条跑满的时刻才与服务端产出时刻对齐（也不用依赖客户端时钟）。
    const seconds = cycle?.seconds ?? 0
    clock.sync((cycle?.credit ?? 0) * 1000 + Math.max(0, rttMs) / 2, seconds)
    lastTickMs = performance.now()
    // 以未平滑的服务端余额安排结算；错过截止点时立即补报，不能取模跳过一轮。
    nextActionAt = lastTickMs + Math.max(0, seconds * 1000 - (cycle?.credit ?? 0) * 1000 - Math.max(0, rttMs) / 2)
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
      // 页面在后台时不推进本地插值（不影响服务端结算，回到前台会重新对齐）。
      if (!isPageHidden()) progress.value = clock.advance(delta)
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
    scheduleReport()
    startTicker()
  }

  function scheduleReport() {
    if (!isRunning.value) return
    const due = nextActionAt - performance.now()
    // 后台标签页拉长上报间隔（服务端按真实窗口结算，产出不变），降低持续请求量。
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

  async function reportOnce() {
    if (sessionId.value === null) return
    if (busy.value) {
      scheduleReport()
      return
    }
    const id = sessionId.value
    busy.value = true
    // 序列：本步若已达标，则在状态刷新后切到下一步（见下方 completeStep）。
    let stepComplete: { done: number; target: number } | null = null
    // 升级会让面板 / 门槛变化，需立即刷新全量状态（其余情况走节流）。
    let leveledUp = false
    try {
      if (mode.value === 'gather') {
        const [r, rtt] = await timed(() => api.gatherReport(id))
        if (sessionId.value !== id) return
        lastGained.value = r.gained
        if (r.gained.length) {
          pushLog(
            `采集 ${r.actions} 次：${r.gained.map((g) => `${g.name} ×${g.count}`).join('、')}`,
            'loot',
          )
          sound.play('gather.gain')
        }
        if (r.xp > 0 && r.xpBreakdown) pushLog(activityExpLog(r.xpBreakdown), 'exp')
        for (const title of r.newTitles ?? []) {
          toast.push(`达成彩蛋称号「${titleName(title)}」`, 'success')
        }
        if (r.level?.levelsGained > 0) leveledUp = true
        syncCycle(r.cycle, rtt)
        const step = currentSeqStep.value
        if (step?.kind === 'gather') {
          // 只统计序列开始后新采到的目标材料，达到数量即完成本步。
          seqGained.value += r.gained
            .filter((g) => g.itemId === step.materialId)
            .reduce((sum, g) => sum + g.count, 0)
          if (seqGained.value >= step.target) {
            stepComplete = { done: seqGained.value, target: step.target }
          }
        }
      } else if (mode.value === 'produce') {
        const [r, rtt] = await timed(() => api.produceReport(id))
        if (sessionId.value !== id) return
        lastGained.value = r.materials
        targetCount.value = r.targetActions
        producedCount.value = r.producedTotal
        if (r.level?.levelsGained > 0) leveledUp = true
        if (r.finished) {
          // 达到目标件数：服务端已结束会话，本地直接收尾（不再调用 stop 接口）。
          settle()
          leveledUp = true
          stepComplete = { done: r.producedTotal, target: r.targetActions ?? r.producedTotal }
          if (!seqActive.value) toast.push(`制造完成，共 ${r.producedTotal} 件`, 'success')
        } else {
          syncCycle(r.cycle, rtt)
        }
        if (r.items.length) {
          lastProduced.value = r.items.map((i) => ({ baseId: i.baseId, name: i.name, rarity: i.rarity }))
          for (const item of r.items) {
            toast.push(`制造出 ${item.name}（高品质）`, 'loot')
          }
          sound.play('produce.high')
        }
        if (r.crafts > 0) {
          const produced = r.materials.map((m) => `${m.name} ×${m.count}`)
          if (r.items.length) {
            const groups = new Map<string, number>()
            for (const item of r.items) groups.set(item.name, (groups.get(item.name) ?? 0) + 1)
            const shown = [...groups.entries()].slice(0, 8).map(([name, n]) => `${name} ×${n}`)
            if (groups.size > 8) shown.push(`等 ${groups.size} 种`)
            produced.push(...shown)
          }
          pushLog(`制造 ${r.crafts} 次：${produced.join('、')}`, 'loot')
          if (!r.items.length) sound.play('produce.craft')
        }
        if (r.xp > 0 && r.xpBreakdown) pushLog(activityExpLog(r.xpBreakdown), 'exp')
      } else if (mode.value === 'fish') {
        const [r, rtt] = await timed(() => api.fishReport(id))
        if (sessionId.value !== id) return
        lastGained.value = r.gained
        lastCaught.value = r.caught
        insights.value = r.insights
        conditions.value = r.conditions
        // 鱼王 / 鱼皇 / 困难鱼用更华丽的音效与普通鱼获区分。
        if (r.caught.length) {
          sound.play(r.caught.some((f) => f.kind !== 'normal') ? 'fish.rare' : 'fish.catch')
        }
        if (r.level?.levelsGained > 0) leveledUp = true
        syncCycle(r.cycle, rtt)
        for (const title of r.newTitles) {
          toast.push(`达成称号「${titleName(title)}」`, 'success')
        }
      }
      // 产出 / 进度已由上报响应驱动界面；全量状态按 5s 节流，升级 / 生产完成时才立即刷新。
      refreshStateIfDue(leveledUp)
      if (stepComplete) await completeStep(stepComplete.done, stepComplete.target)
    } catch {
      if (sessionId.value === id) await stop(true)
    } finally {
      busy.value = false
      if (timer === null) scheduleReport()
    }
  }

  async function startGather(jobId: string, regionId: number, opts?: { fromSequence?: boolean }) {
    // 手动开始会取消正在跑的序列（保留队列定义）；序列内部启动则不动。
    if (!opts?.fromSequence) resetRun()
    await stop(true)
    await game.stopBattle(true)
    const [res, rtt] = await timed(() => api.gatherStart(jobId, regionId))
    sessionId.value = res.sessionId
    mode.value = 'gather'
    recipeId.value = null
    lastGained.value = []
    logEntries.value = []
    syncCycle(res.cycle, rtt)
    startLoop()
  }

  /** 开始生产。count=null 表示「制作全部」（按当前材料上限）。 */
  async function startProduce(
    jobId: string,
    recipeId_: string,
    count: number | null = null,
    opts?: { fromSequence?: boolean },
  ) {
    if (!opts?.fromSequence) resetRun()
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
    logEntries.value = []
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
    insights.value = []
    conditions.value = res.conditions
    syncCycle(res.cycle, rtt)
    startLoop()
    sound.play('fish.cast')
  }

  /** 本地收尾：清空会话状态但不调用 stop 接口（服务端已自动结束会话时用）。 */
  function settle() {
    stopLoop()
    clock.reset()
    mode.value = 'idle'
    sessionId.value = null
    recipeId.value = null
    // 下次会话的首次上报立即刷新全量状态（材料 / 库存已变化）。
    lastStateRefreshAt = 0
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

  // ------------------------------------------------------------------ 序列
  /** 清空「运行态」但保留队列定义（手动开始 / 序列结束时用）。 */
  function resetRun() {
    seqActive.value = false
    seqIndex.value = -1
    seqGained.value = 0
    seqResults.value = []
    loopRound.value = 1
  }

  /** 入列：同一目标的步骤合并数量；超出上限拒绝。 */
  function addStep(step: SequenceStep) {
    if (seqActive.value) {
      toast.push('序列运行中，请先停止再编辑', 'error')
      return
    }
    const key = stepKey(step)
    const existing = sequence.value.find((s) => stepKey(s) === key)
    if (existing) {
      existing.target += step.target
      toast.push(`已合并到「${existing.name}」，数量 ${existing.target}`, 'info')
      return
    }
    if (sequence.value.length >= SEQ_STEP_LIMIT) {
      toast.push(`序列最多 ${SEQ_STEP_LIMIT} 步`, 'error')
      return
    }
    sequence.value.push(step)
  }

  function removeStep(id: string) {
    if (seqActive.value) return
    sequence.value = sequence.value.filter((s) => s.id !== id)
  }

  function moveStep(id: string, dir: -1 | 1) {
    if (seqActive.value) return
    const i = sequence.value.findIndex((s) => s.id === id)
    const j = i + dir
    if (i < 0 || j < 0 || j >= sequence.value.length) return
    const next = sequence.value.slice()
    ;[next[i], next[j]] = [next[j], next[i]]
    sequence.value = next
  }

  function clearSequence() {
    if (seqActive.value) return
    sequence.value = []
    seqResults.value = []
    loopRound.value = 1
  }

  /** 开始执行序列：按顺序自动采集 / 制作，直到全部完成或用户停止。 */
  async function startSequence() {
    if (seqActive.value) return
    if (!sequence.value.length) {
      toast.push('序列为空，请先添加步骤', 'error')
      return
    }
    if (sequenceBlocked.value) {
      toast.push('序列中存在无法执行的步骤，请先提升等级或解锁地区', 'error')
      return
    }
    // 状态已加载时按当前等级 / 解锁重解析采集点（升级后自愈）。
    if (state.value) {
      for (const step of sequence.value) {
        if (step.kind !== 'gather') continue
        const found = resolveGatherAvailability(step.materialId, isRegionUnlocked, dolLevel.value)
        if (!found) continue
        step.jobId = found.jobId
        step.regionId = found.regionId
        step.blocked = found.blocked
        step.requiredLevel = found.requiredLevel
      }
    }
    await stop(true)
    await game.stopBattle(true)
    seqResults.value = []
    seqIndex.value = 0
    seqGained.value = 0
    loopRound.value = 1
    seqActive.value = true
    await runStep()
  }

  /** 停止序列：结束当前会话，本步记为「中断」，保留队列定义。 */
  async function stopSequence(silent = false) {
    const step = currentSeqStep.value
    if (step) {
      const done = step.kind === 'gather' ? seqGained.value : producedCount.value
      seqResults.value.push({
        id: step.id,
        name: step.name,
        done,
        target: step.target,
        status: 'interrupted',
      })
    }
    resetRun()
    await stop(silent)
  }

  /** 启动当前步（采集 / 制作）。启动失败（材料不足 / 等级不足等）→ 跳过并继续。 */
  async function runStep() {
    if (!seqActive.value) return
    const step = sequence.value[seqIndex.value]
    if (!step) {
      finishSequence()
      return
    }
    seqGained.value = 0
    try {
      if (step.kind === 'gather') {
        await startGather(step.jobId, step.regionId, { fromSequence: true })
      } else {
        await startProduce(step.jobId, step.recipeId, step.target, { fromSequence: true })
      }
    } catch (err) {
      const reason = err instanceof Error ? err.message : '启动失败'
      seqResults.value.push({
        id: step.id,
        name: step.name,
        done: 0,
        target: step.target,
        status: 'skipped',
        reason,
      })
      toast.push(`「${step.name}」已跳过：${reason}`, 'error')
      seqIndex.value += 1
      await runStep()
    }
  }

  /** 当前步达标后的收尾：记录结果并切到下一步。 */
  async function completeStep(done: number, target: number) {
    const step = currentSeqStep.value
    if (!step) return
    const status: StepStatus = done >= target ? 'done' : 'partial'
    seqResults.value.push({ id: step.id, name: step.name, done, target, status })
    toast.push(
      status === 'done'
        ? `「${step.name}」完成（${done}/${target}）`
        : `「${step.name}」仅完成 ${done}/${target}`,
      status === 'done' ? 'success' : 'info',
    )
    if (status === 'done') sound.play('seq.step')
    seqIndex.value += 1
    await runStep()
  }

  function finishSequence() {
    const total = sequence.value.length
    const ok = seqResults.value.filter((r) => r.status === 'done').length
    // 本轮是否有实际产出：全部步骤都被跳过 / 未产出时不继续循环，避免空转刷接口。
    const progressed = seqResults.value.some((r) => r.done > 0)
    const wantMore =
      loopMode.value === 'infinite' ||
      (loopMode.value === 'count' && loopRound.value < Math.max(1, Math.floor(loopTotal.value)))

    if (wantMore && progressed) {
      loopRound.value += 1
      seqResults.value = []
      seqGained.value = 0
      seqIndex.value = 0
      toast.push(`第 ${loopRound.value} 轮`, 'info')
      void runStep()
      return
    }

    seqActive.value = false
    seqIndex.value = -1
    seqGained.value = 0
    // 保留 seqResults 供界面展示本轮汇总。
    if (wantMore && !progressed) {
      toast.push('本轮无任何产出，已停止循环', 'info')
    } else {
      toast.push(
        ok >= total ? `序列完成：共 ${total} 步` : `序列结束：${ok}/${total} 步完成`,
        ok >= total ? 'success' : 'info',
      )
      if (ok >= total) sound.play('seq.done')
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
    insights,
    conditions,
    logEntries,
    recipeId,
    targetCount,
    producedCount,
    progressPct,
    starved,
    state,
    isRunning,
    active,
    // 序列
    sequence,
    seqActive,
    seqIndex,
    seqGained,
    seqResults,
    loopMode,
    loopTotal,
    loopRound,
    currentSeqStep,
    sequenceIssues,
    sequenceBlocked,
    addStep,
    removeStep,
    moveStep,
    clearSequence,
    startSequence,
    stopSequence,
    startGather,
    startProduce,
    startFish,
    stop,
    useConsumable,
    sellStack,
    sellStacks,
  }
})
