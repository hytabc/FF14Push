import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const mocks = vi.hoisted(() => ({
  api: {
    ishgardState: vi.fn(),
    ishgardProduceStart: vi.fn(),
    ishgardProduceReport: vi.fn(),
    ishgardProduceStop: vi.fn(),
    ishgardGatherStart: vi.fn(),
    ishgardGatherReport: vi.fn(),
    ishgardGatherStop: vi.fn(),
  },
  game: { stopBattle: vi.fn() },
  toast: { push: vi.fn() },
}))
vi.mock('@/api', () => ({ api: mocks.api }))
vi.mock('@/stores/game', () => ({ useGameStore: () => mocks.game }))
vi.mock('@/stores/toast', () => ({ useToastStore: () => mocks.toast }))

import { useIshgardStore } from './ishgard'

const cycle = (seconds: number, credit = 0) => ({ seconds, credit, at: 0 })

/** 构造一个 axios 风格的错误响应（`toApiError` 依赖 isAxiosError 标记）。 */
function httpError(status: number, detail: string) {
  return { isAxiosError: true, response: { status, data: { detail } } }
}

const produceStart = { sessionId: 1, jobId: 'CRP', recipeId: 'r1', targetActions: 10, stage: 1, cycle: cycle(2) }

function produceReport(overrides: Record<string, unknown> = {}) {
  return {
    crafts: 1,
    recipeId: 'r1',
    materials: [],
    produced: [{ itemId: 's1_p_x', name: '脚手架', count: 1 }],
    xp: 0,
    xpBreakdown: { base: 0, rarityMultiplier: 1, bonusPct: 0, amount: 0, sources: [] },
    level: { levelsGained: 0, level: 1, exp: 0 },
    targetActions: 10,
    producedTotal: 1,
    finished: false,
    cycle: cycle(2),
    ...overrides,
  }
}

beforeEach(() => {
  vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout', 'setInterval', 'clearInterval', 'Date', 'performance'] })
  vi.stubGlobal('window', globalThis)
  setActivePinia(createPinia())
  vi.resetAllMocks()
  mocks.api.ishgardState.mockResolvedValue({})
  mocks.api.ishgardProduceStop.mockResolvedValue({ ok: true })
})
afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

describe('挂机循环的失败重试', () => {
  it('网络抖动不结束会话，退避后自动重试并继续生产', async () => {
    mocks.api.ishgardProduceStart.mockResolvedValue(produceStart)
    mocks.api.ishgardProduceReport
      .mockRejectedValueOnce(new Error('Network Error'))
      .mockResolvedValue(produceReport())

    const store = useIshgardStore()
    await store.startProduce('CRP', 'r1', 10)

    // 首次上报失败 → 保留会话，不调用 stop
    await vi.advanceTimersByTimeAsync(1500)
    expect(mocks.api.ishgardProduceReport).toHaveBeenCalledTimes(1)
    expect(store.mode).toBe('produce')
    expect(store.sessionId).toBe(1)
    expect(mocks.api.ishgardProduceStop).not.toHaveBeenCalled()
    expect(store.logEntries.some((e) => e.text.includes('重试'))).toBe(true)

    // 退避期内不重试（3 秒），避免猛打接口
    await vi.advanceTimersByTimeAsync(1000)
    expect(mocks.api.ishgardProduceReport).toHaveBeenCalledTimes(1)

    // 退避结束后自动重试并恢复
    await vi.advanceTimersByTimeAsync(2000)
    expect(mocks.api.ishgardProduceReport).toHaveBeenCalledTimes(2)
    expect(store.mode).toBe('produce')
    expect(store.producedCount).toBe(1)

    await store.stop()
  })

  it('会话已在服务端结束（404）时收尾并给出提示，而非静默停止', async () => {
    mocks.api.ishgardProduceStart.mockResolvedValue(produceStart)
    mocks.api.ishgardProduceReport.mockRejectedValue(httpError(404, '会话不存在或已结束'))

    const store = useIshgardStore()
    await store.startProduce('CRP', 'r1', 10)
    await vi.advanceTimersByTimeAsync(1500)

    expect(store.mode).toBe('idle')
    expect(store.sessionId).toBeNull()
    expect(mocks.api.ishgardProduceStop).toHaveBeenCalledWith(1)
    expect(mocks.toast.push).toHaveBeenCalledWith('挂机已中断：会话不存在或已结束', 'error')

    await vi.advanceTimersByTimeAsync(10000)
    expect(mocks.api.ishgardProduceReport).toHaveBeenCalledTimes(1)
  })
})
