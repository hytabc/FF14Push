import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const mocks = vi.hoisted(() => ({
  api: { state: vi.fn(), startBattle: vi.fn(), stopBattle: vi.fn(), reportBattle: vi.fn() },
  toast: { push: vi.fn() },
}))

vi.mock('@/api', () => ({ api: mocks.api }))
vi.mock('@/stores/toast', () => ({ useToastStore: () => mocks.toast }))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({ isLoggedIn: true, logout: vi.fn() }) }))
vi.mock('@/stores/loot', () => ({ useLootStore: () => ({ push: vi.fn(), clear: vi.fn() }) }))

import { useGameStore } from './game'

const pendingReport = () => ({
  kills: [{ monsterId: 'x', at: 0 }],
  skillCasts: {},
  bossKilled: false,
  died: false,
  bossFightMs: 0,
})

beforeEach(() => {
  vi.stubGlobal('localStorage', { getItem: () => null, setItem: () => {}, removeItem: () => {} })
  setActivePinia(createPinia())
  vi.resetAllMocks()
})

describe('地区战斗上报', () => {
  it('会话被服务端结束时静默停战，不重试也不弹窗', async () => {
    const game = useGameStore()
    const restorePending = vi.fn()
    game.state = { user: { gold: 0 } } as never
    game.sessionId = 1
    game.sim = { region: { id: 1 }, killCount: 1, drainPending: pendingReport, restorePending, pause: vi.fn() } as never
    mocks.api.reportBattle.mockRejectedValue({
      isAxiosError: true,
      response: { status: 404, data: { detail: '战斗会话不存在或已结束' } },
    })

    await game.report()

    expect(mocks.api.reportBattle).toHaveBeenCalledTimes(1)
    expect(game.sessionId).toBeNull()
    expect(game.running).toBe(false)
    expect(restorePending).not.toHaveBeenCalled()
    expect(mocks.toast.push).not.toHaveBeenCalled()
  })

  it('其它错误仍放回击杀并提示一次', async () => {
    const game = useGameStore()
    const restorePending = vi.fn()
    game.state = { user: { gold: 0 } } as never
    game.sessionId = 1
    game.sim = { region: { id: 1 }, killCount: 1, drainPending: pendingReport, restorePending, pause: vi.fn() } as never
    mocks.api.reportBattle.mockRejectedValue({
      isAxiosError: true,
      response: { status: 500, data: { detail: '服务器错误' } },
    })

    await game.report()

    expect(restorePending).toHaveBeenCalledTimes(1)
    expect(mocks.toast.push).toHaveBeenCalledWith('服务器错误', 'error')
    expect(game.sessionId).toBe(1)
  })
})
