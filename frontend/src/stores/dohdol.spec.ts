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
