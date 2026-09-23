import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const mocks = vi.hoisted(() => ({
  api: {
    gatherStart: vi.fn(), gatherReport: vi.fn(), gatherStop: vi.fn(),
    produceStart: vi.fn(), produceReport: vi.fn(), produceStop: vi.fn(),
    fishStart: vi.fn(), fishReport: vi.fn(), fishStop: vi.fn(),
  },
  game: { state: null, stopBattle: vi.fn(), loadState: vi.fn() },
}))
vi.mock('@/api', () => ({ api: mocks.api }))
vi.mock('@/stores/game', () => ({ useGameStore: () => mocks.game }))
vi.mock('@/stores/toast', () => ({ useToastStore: () => ({ push: vi.fn() }) }))

import { useDohDolStore } from './dohdol'

beforeEach(() => {
  vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout', 'setInterval', 'clearInterval', 'Date', 'performance'] })
  vi.stubGlobal('window', globalThis)
  setActivePinia(createPinia())
  vi.resetAllMocks()
})
afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

const cycle = (seconds: number, credit = 0) => ({ seconds, credit, at: 0 })

describe('活动结算与进度同步', () => {
  it.each(['gather', 'produce', 'fish'] as const)('%s 在实际动作截止时结算', async (mode) => {
    mocks.api[`${mode}Start`].mockResolvedValue({ sessionId: 1, cycle: cycle(2), recipeId: 'recipe', targetActions: 10 })
    mocks.api[`${mode}Report`].mockResolvedValue({
      cycle: cycle(2, 1.5), gained: [], materials: [], items: [], caught: [], newTitles: [],
      targetActions: 10, producedTotal: 0, finished: false,
    })
    const store = useDohDolStore()
    if (mode === 'gather') await store.startGather('MIN', 1)
    else if (mode === 'produce') await store.startProduce('CRP', 'recipe', 10)
    else await store.startFish(1)
    await vi.advanceTimersByTimeAsync(1500)
    expect(mocks.api[`${mode}Report`]).toHaveBeenCalledTimes(1)
    mocks.api[`${mode}Report`].mockResolvedValue({
      cycle: cycle(2), gained: [], materials: [], items: [], caught: [], newTitles: [],
      targetActions: 10, producedTotal: 1, finished: false,
    })
    await vi.advanceTimersByTimeAsync(500)
    expect(mocks.api[`${mode}Report`]).toHaveBeenCalledTimes(2)
    expect(store.progressPct).toBe(0)
    await store.stop()
  })

  it('上报返回装备加速后的周期，下一次结算和进度均采用新耗时', async () => {
    mocks.api.gatherStart.mockResolvedValue({ sessionId: 1, cycle: cycle(4) })
    mocks.api.gatherReport.mockResolvedValue({ gained: [], cycle: cycle(2, 1.5) })
    const store = useDohDolStore()
    await store.startGather('MIN', 1)
    await vi.advanceTimersByTimeAsync(1500)
    expect(store.progressPct).toBe(75)
    await vi.advanceTimersByTimeAsync(500)
    expect(mocks.api.gatherReport).toHaveBeenCalledTimes(2)
    await store.stop()
  })

  it('高速度动作不受 1.5 秒轮询间隔限制', async () => {
    mocks.api.gatherStart.mockResolvedValue({ sessionId: 1, cycle: cycle(0.2) })
    mocks.api.gatherReport.mockResolvedValue({ gained: [], cycle: cycle(0.2) })
    const store = useDohDolStore()
    await store.startGather('MIN', 1)
    await vi.advanceTimersByTimeAsync(1000)
    expect(mocks.api.gatherReport).toHaveBeenCalledTimes(5)
    await store.stop()
  })

  it('状态刷新耗时跨过动作截止点时立即补报', async () => {
    mocks.api.gatherStart.mockResolvedValue({ sessionId: 1, cycle: cycle(2) })
    mocks.api.gatherReport.mockResolvedValue({ gained: [], cycle: cycle(2, 1.5) })
    mocks.game.loadState.mockImplementationOnce(() => new Promise<void>((done) => setTimeout(done, 800)))
    const store = useDohDolStore()
    await store.startGather('MIN', 1)
    await vi.advanceTimersByTimeAsync(2350)
    expect(mocks.api.gatherReport).toHaveBeenCalledTimes(2)
    await store.stop()
  })

  it('停止后的迟到响应不能恢复进度或重启结算', async () => {
    mocks.api.gatherStart.mockResolvedValue({ sessionId: 1, cycle: cycle(2) })
    let resolve!: (value: unknown) => void
    mocks.api.gatherReport.mockImplementation(() => new Promise((done) => { resolve = done }))
    const store = useDohDolStore()
    await store.startGather('MIN', 1)
    await vi.advanceTimersByTimeAsync(1500)
    await store.stop()
    resolve({ gained: [], cycle: cycle(2, 1.5) })
    await vi.advanceTimersByTimeAsync(3000)
    expect(store.progressPct).toBe(0)
    expect(store.mode).toBe('idle')
    expect(mocks.api.gatherReport).toHaveBeenCalledTimes(1)
  })
})

describe('采集 / 制作序列', () => {
  it('采集序列：达到目标数量后自动切换到下一步（并切换采集点）', async () => {
    mocks.api.gatherStart
      .mockResolvedValueOnce({ sessionId: 1, cycle: cycle(2) })
      .mockResolvedValueOnce({ sessionId: 2, cycle: cycle(2) })
    mocks.api.gatherReport.mockResolvedValue({
      gained: [{ itemId: 'ore7', name: '铁矿石', count: 3 }],
      cycle: cycle(2),
    })
    const store = useDohDolStore()
    store.addStep({ kind: 'gather', id: 'a', materialId: 'ore7', name: '铁矿石', jobId: 'MIN', regionId: 7, target: 3 })
    store.addStep({ kind: 'gather', id: 'b', materialId: 'ore3', name: '铜矿石', jobId: 'MIN', regionId: 3, target: 2 })

    await store.startSequence()
    expect(store.seqActive).toBe(true)
    expect(mocks.api.gatherStart).toHaveBeenLastCalledWith('MIN', 7)

    await vi.advanceTimersByTimeAsync(1500)
    expect(mocks.api.gatherStart).toHaveBeenCalledTimes(2)
    expect(mocks.api.gatherStart).toHaveBeenLastCalledWith('MIN', 3)
    expect(mocks.api.gatherStop).toHaveBeenCalledWith(1)
    expect(store.seqIndex).toBe(1)
    expect(store.seqGained).toBe(0)
    expect(store.seqResults[0]).toMatchObject({ id: 'a', done: 3, target: 3, status: 'done' })

    await store.stopSequence(true)
  })

  it('采集序列：只统计序列开始后新采到的目标材料（未达标不切换）', async () => {
    mocks.api.gatherStart.mockResolvedValue({ sessionId: 1, cycle: cycle(2) })
    mocks.api.gatherReport.mockResolvedValue({
      gained: [{ itemId: 'ore3', name: '铜矿石', count: 1 }],
      cycle: cycle(2),
    })
    const store = useDohDolStore()
    store.addStep({ kind: 'gather', id: 'a', materialId: 'ore7', name: '铁矿石', jobId: 'MIN', regionId: 7, target: 2 })

    await store.startSequence()
    await vi.advanceTimersByTimeAsync(1500)
    expect(store.seqGained).toBe(0)
    expect(store.seqIndex).toBe(0)
    expect(mocks.api.gatherStart).toHaveBeenCalledTimes(1)

    await store.stopSequence(true)
  })

  it('制作序列：启动失败（材料不足）的步骤被跳过并继续', async () => {
    mocks.api.produceStart
      .mockRejectedValueOnce(new Error('材料不足，无法制造'))
      .mockResolvedValueOnce({ sessionId: 2, recipeId: 'r2', targetActions: 5, cycle: cycle(2) })
    const store = useDohDolStore()
    store.addStep({ kind: 'produce', id: 'a', recipeId: 'r1', name: 'A', jobId: 'CRP', target: 1 })
    store.addStep({ kind: 'produce', id: 'b', recipeId: 'r2', name: 'B', jobId: 'CRP', target: 5 })

    await store.startSequence()
    expect(mocks.api.produceStart).toHaveBeenCalledTimes(2)
    expect(store.seqResults[0]).toMatchObject({ id: 'a', done: 0, status: 'skipped', reason: '材料不足，无法制造' })
    expect(store.seqIndex).toBe(1)
    expect(store.seqActive).toBe(true)

    await store.stopSequence(true)
  })

  it('制作序列：最后一步达标后结束并汇总', async () => {
    mocks.api.produceStart.mockResolvedValue({ sessionId: 1, recipeId: 'r1', targetActions: 5, cycle: cycle(2) })
    mocks.api.produceReport.mockResolvedValue({
      crafts: 5, recipeId: 'r1', materials: [], items: [], xp: 0,
      level: { levelsGained: 0, level: 1, exp: 0 },
      targetActions: 5, producedTotal: 5, finished: true, cycle: cycle(2),
    })
    const store = useDohDolStore()
    store.addStep({ kind: 'produce', id: 'a', recipeId: 'r1', name: 'A', jobId: 'CRP', target: 5 })

    await store.startSequence()
    await vi.advanceTimersByTimeAsync(1500)
    expect(store.seqActive).toBe(false)
    expect(store.mode).toBe('idle')
    expect(store.seqResults).toEqual([{ id: 'a', name: 'A', done: 5, target: 5, status: 'done' }])
  })

  it('制作序列：材料只够部分时记为未完成', async () => {
    mocks.api.produceStart.mockResolvedValue({ sessionId: 1, recipeId: 'r1', targetActions: 3, cycle: cycle(2) })
    mocks.api.produceReport.mockResolvedValue({
      crafts: 3, recipeId: 'r1', materials: [], items: [], xp: 0,
      level: { levelsGained: 0, level: 1, exp: 0 },
      targetActions: 3, producedTotal: 3, finished: true, cycle: cycle(2),
    })
    const store = useDohDolStore()
    // 目标 5，但服务端按材料上限只做到 3（targetActions 回落为 3）
    store.addStep({ kind: 'produce', id: 'a', recipeId: 'r1', name: 'A', jobId: 'CRP', target: 5 })

    await store.startSequence()
    await vi.advanceTimersByTimeAsync(1500)
    expect(store.seqResults[0]).toMatchObject({ done: 3, target: 3, status: 'done' })
  })
})

describe('序列循环', () => {
  const finishedReport = {
    crafts: 5, recipeId: 'r1', materials: [], items: [], xp: 0,
    level: { levelsGained: 0, level: 1, exp: 0 },
    targetActions: 5, producedTotal: 5, finished: true, cycle: cycle(2),
  }

  it('一直循环：一轮跑完后自动进入下一轮', async () => {
    mocks.api.produceStart.mockResolvedValue({ sessionId: 1, recipeId: 'r1', targetActions: 5, cycle: cycle(2) })
    mocks.api.produceReport.mockResolvedValue(finishedReport)
    const store = useDohDolStore()
    store.loopMode = 'infinite'
    store.addStep({ kind: 'produce', id: 'a', recipeId: 'r1', name: 'A', jobId: 'CRP', target: 5 })

    await store.startSequence()
    expect(store.loopRound).toBe(1)

    await vi.advanceTimersByTimeAsync(1500)
    expect(store.seqActive).toBe(true)
    expect(store.loopRound).toBe(2)
    expect(store.seqIndex).toBe(0)
    expect(store.seqResults).toEqual([])
    expect(mocks.api.produceStart).toHaveBeenCalledTimes(2)

    await store.stopSequence(true)
  })

  it('循环指定次数：跑满轮数后停止', async () => {
    mocks.api.produceStart.mockResolvedValue({ sessionId: 1, recipeId: 'r1', targetActions: 5, cycle: cycle(2) })
    mocks.api.produceReport.mockResolvedValue(finishedReport)
    const store = useDohDolStore()
    store.loopMode = 'count'
    store.loopTotal = 2
    store.addStep({ kind: 'produce', id: 'a', recipeId: 'r1', name: 'A', jobId: 'CRP', target: 5 })

    await store.startSequence()
    await vi.advanceTimersByTimeAsync(1500)
    expect(store.loopRound).toBe(2)
    expect(store.seqActive).toBe(true)

    await vi.advanceTimersByTimeAsync(1500)
    expect(store.seqActive).toBe(false)
    expect(store.loopRound).toBe(2)
    expect(store.seqIndex).toBe(-1)
  })

  it('循环时不产出的一轮会停止循环（防空转）', async () => {
    mocks.api.produceStart.mockRejectedValue(new Error('材料不足，无法制造'))
    const store = useDohDolStore()
    store.loopMode = 'infinite'
    store.addStep({ kind: 'produce', id: 'a', recipeId: 'r1', name: 'A', jobId: 'CRP', target: 1 })

    await store.startSequence()
    expect(mocks.api.produceStart).toHaveBeenCalledTimes(1)
    expect(store.seqResults[0]).toMatchObject({ id: 'a', done: 0, status: 'skipped' })
    expect(store.seqActive).toBe(false)
    expect(store.loopRound).toBe(1)
  })

  it('不循环（默认）时跑完一轮即结束', async () => {
    mocks.api.produceStart.mockResolvedValue({ sessionId: 1, recipeId: 'r1', targetActions: 5, cycle: cycle(2) })
    mocks.api.produceReport.mockResolvedValue(finishedReport)
    const store = useDohDolStore()
    store.addStep({ kind: 'produce', id: 'a', recipeId: 'r1', name: 'A', jobId: 'CRP', target: 5 })

    await store.startSequence()
    await vi.advanceTimersByTimeAsync(1500)
    expect(store.seqActive).toBe(false)
    expect(mocks.api.produceStart).toHaveBeenCalledTimes(1)
  })
})

describe('生产 / 采集日志', () => {
  it('采集结算追加产出与经验明细', async () => {
    mocks.api.gatherStart.mockResolvedValue({ sessionId: 1, cycle: cycle(2) })
    mocks.api.gatherReport.mockResolvedValue({
      gained: [{ itemId: 'g_ore', name: '铁矿', count: 2 }],
      actions: 3,
      xp: 18,
      xpBreakdown: { base: 18, rarityMultiplier: 1, bonusPct: 0, amount: 18, sources: [] },
      cycle: cycle(2),
    })
    const store = useDohDolStore()
    await store.startGather('MIN', 1)
    await vi.advanceTimersByTimeAsync(1500)
    expect(store.logEntries.map((e) => e.text)).toEqual(['采集 3 次：铁矿 ×2', '获得经验 18（基础 18）'])
    expect(store.logEntries.map((e) => e.tone)).toEqual(['loot', 'exp'])
    await store.stop()
  })

  it('生产结算按品阶与来源展示经验', async () => {
    mocks.api.produceStart.mockResolvedValue({ sessionId: 1, recipeId: 'r1', targetActions: 5, cycle: cycle(2) })
    mocks.api.produceReport.mockResolvedValue({
      crafts: 2,
      recipeId: 'r1',
      materials: [{ itemId: 'h_plank', name: '木板', count: 2 }],
      items: [],
      xp: 62,
      xpBreakdown: { base: 48, rarityMultiplier: 1, bonusPct: 30, amount: 62, sources: [{ label: '灵感', pct: 30 }] },
      targetActions: 5,
      producedTotal: 2,
      finished: false,
      cycle: cycle(2),
    })
    const store = useDohDolStore()
    await store.startProduce('CRP', 'r1', 5)
    await vi.advanceTimersByTimeAsync(1500)
    expect(store.logEntries.map((e) => e.text)).toEqual([
      '制造 2 次：木板 ×2',
      '获得经验 62（基础 48，经验加成 +30%：灵感 +30%）',
    ])
    await store.stop()
  })

  it('开始新会话时清空上一轮日志', async () => {
    mocks.api.gatherStart.mockResolvedValue({ sessionId: 1, cycle: cycle(2) })
    mocks.api.gatherReport.mockResolvedValue({
      gained: [{ itemId: 'g_ore', name: '铁矿', count: 1 }],
      actions: 1,
      xp: 6,
      xpBreakdown: { base: 6, rarityMultiplier: 1, bonusPct: 0, amount: 6, sources: [] },
      cycle: cycle(2),
    })
    const store = useDohDolStore()
    await store.startGather('MIN', 1)
    await vi.advanceTimersByTimeAsync(1500)
    expect(store.logEntries.length).toBe(2)

    await store.stop()
    await store.startGather('MIN', 1)
    expect(store.logEntries.length).toBe(0)
    await store.stop()
  })
})
