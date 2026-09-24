import { defineStore } from 'pinia'
import { computed, ref, shallowRef } from 'vue'

import data from '@shared/schema'

import { api } from '@/api'
import { toApiError } from '@/api/client'
import { BattleSimulator } from '@/game/core/battle'
import type {
  RaidBossEntry,
  TreasureChestResult,
  TreasureConfig,
  TreasureEvent,
  TreasureGambleResult,
  TreasureRunState,
} from '@/game/types'

import { useGameStore } from './game'
import { useToastStore } from './toast'

const TICK_MS = 100
/** 单帧最多推进的模拟时间（毫秒），把后台补算分摊到多帧，避免卡住主线程。 */
const MAX_FRAME_MS = 400
/** 后台补算上限（毫秒）：与地区战斗同源（shared/data/combat.json:catchUpSeconds）。 */
const CATCH_UP_MS = Number(data.combat.catchUpSeconds ?? 300) * 1000

/** 挖宝会话：每层客户端模拟战斗，服务端权威结算门 / 宝箱 / 猜大小。 */
export const useTreasureStore = defineStore('treasure', () => {
  const game = useGameStore()
  const toast = useToastStore()

  const config = ref<TreasureConfig | null>(null)
  const run = ref<TreasureRunState | null>(null)
  const sim = shallowRef<BattleSimulator | null>(null)
  const running = ref(false)
  const busy = ref(false)
  const logVersion = ref(0)
  const uiTick = ref(0)
  /** 本层事件（触发时非空）。 */
  const event = ref<TreasureEvent | null>(null)
  /** 猜大小结果（用于展示本次对局）。 */
  const gamble = ref<TreasureGambleResult | null>(null)
  /** 开箱结果。 */
  const chest = ref<TreasureChestResult | null>(null)
  /** 最近一次选门结果。 */
  const door = ref<{ correct: boolean } | null>(null)

  let rafId = 0
  let tickTimer = 0
  let lastWallMs = 0
  let simBudgetMs = 0
  let reporting = false

  const hero = computed(() => game.hero)
  const stats = computed(() => game.hero?.stats ?? null)
  const floor = computed(() => run.value?.floor ?? 0)
  const phase = computed(() => sim.value?.phase ?? 'idle')
  const inBattle = computed(() => running.value && sim.value !== null)
  const log = computed(() => {
    logVersion.value
    return sim.value?.log ?? []
  })
  const floating = computed(() => {
    logVersion.value
    return sim.value?.floating ?? []
  })
  const bosses = computed<RaidBossEntry[]>(() => {
    void uiTick.value
    logVersion.value
    return sim.value?.bossEntries() ?? []
  })

  function pushError(e: unknown) {
    const err = toApiError(e)
    if (err.code === 'banned') return
    toast.push(err.message, 'error')
  }

  async function load() {
    const res = await api.treasureState()
    config.value = res.config
    run.value = res.run
    return res
  }

  function stopLoop() {
    if (rafId) cancelAnimationFrame(rafId)
    rafId = 0
    if (tickTimer) window.clearInterval(tickTimer)
    tickTimer = 0
  }

  /** 启动本层战斗（进入下一层或阵亡重试时复用）。 */
  function beginFloor(target: TreasureRunState) {
    if (!target.boss || !game.hero) return
    event.value = null
    gamble.value = null
    chest.value = null
    door.value = null
    sim.value = new BattleSimulator({
      // 怪物数值已按难度烘焙进 boss 对象，玩家侧不再套用难度缩放（difficulty 恒为 0）。
      stats: game.hero.stats,
      raid: { bosses: [target.boss], enrage: null },
      eggId: game.hero.eggId,
    })
    sim.value.start()
    running.value = true
    logVersion.value += 1
    startLoop()
  }

  function startLoop() {
    if (rafId) return
    lastWallMs = Date.now()
    simBudgetMs = 0
    tickTimer = window.setInterval(() => {
      uiTick.value += 1
    }, TICK_MS)
    const step = () => {
      const wallNow = Date.now()
      const wallDelta = Math.min(CATCH_UP_MS, Math.max(0, wallNow - lastWallMs))
      lastWallMs = wallNow
      simBudgetMs = Math.min(CATCH_UP_MS, simBudgetMs + wallDelta)

      const dtMs = Math.min(MAX_FRAME_MS, simBudgetMs)
      simBudgetMs -= dtMs
      if (sim.value && running.value) {
        sim.value.tick(dtMs / 1000)
        logVersion.value += 1
        void finishFloorIfDone()
      }
      if (running.value) {
        rafId = requestAnimationFrame(step)
      } else {
        rafId = 0
        if (tickTimer) window.clearInterval(tickTimer)
        tickTimer = 0
      }
    }
    rafId = requestAnimationFrame(step)
  }

  /** 一层结束（击败怪物或阵亡）时上报一次。 */
  async function finishFloorIfDone() {
    const current = sim.value
    const target = run.value
    if (!current || !target || reporting) return
    if (current.phase !== 'cleared' && current.phase !== 'dead') return

    reporting = true
    running.value = false
    stopLoop()
    current.pause()
    try {
      if (current.phase === 'cleared') {
        const res = await api.treasureFloorClear(target.runId, Math.round(current.bossFightMs))
        run.value = res.run
        event.value = res.event
        if (res.event) toast.push(`特殊事件：猜大小（当前牌面 ${res.event.card}）`, 'loot')
      } else {
        // 阵亡：不结束副本，原地重试本层。
        toast.push('英雄阵亡！可原地重试本层', 'error')
        const res = await api.treasureRetry(target.runId)
        run.value = res.run
        beginFloor(res.run)
      }
    } catch (e) {
      pushError(e)
    } finally {
      reporting = false
    }
  }

  async function start() {
    if (busy.value) return
    busy.value = true
    try {
      if (game.isRunning || game.raid) await game.stopBattle(true)
      const res = await api.treasureStart()
      run.value = res.run
      await game.loadState()
      beginFloor(res.run)
    } catch (e) {
      pushError(e)
    } finally {
      busy.value = false
    }
  }

  async function gambleGuess(guess: 'high' | 'low') {
    if (!run.value || busy.value) return
    busy.value = true
    try {
      const res = await api.treasureGamble(run.value.runId, guess)
      gamble.value = res
      run.value = res.run
      if (res.result === 'lose') {
        event.value = null
        toast.push('猜错了，本层宝箱奖励已清空', 'error')
      } else if (res.finished) {
        event.value = null
      }
    } catch (e) {
      pushError(e)
    } finally {
      busy.value = false
    }
  }

  async function stopGamble() {
    if (!run.value || busy.value) return
    busy.value = true
    try {
      const res = await api.treasureGambleStop(run.value.runId)
      run.value = res.run
      event.value = null
    } catch (e) {
      pushError(e)
    } finally {
      busy.value = false
    }
  }

  async function openChest() {
    if (!run.value || busy.value) return
    busy.value = true
    try {
      const res = await api.treasureChestOpen(run.value.runId)
      chest.value = res
      run.value = res.run
      if (res.expGained > 0 && res.level && res.level.levelsGained > 0) {
        toast.push(`英雄升到 ${res.level.level} 级！`, 'success')
      }
      if (res.completed) {
        toast.push(`通关第 5 层！额外获得 ${res.bonusGold.toLocaleString()} 金币`, 'loot')
      }
      await game.loadState()
    } catch (e) {
      pushError(e)
    } finally {
      busy.value = false
    }
  }

  async function chooseDoor(index: number) {
    if (!run.value || busy.value) return
    busy.value = true
    try {
      const res = await api.treasureDoor(run.value.runId, index)
      door.value = { correct: res.correct }
      run.value = res.run
      if (res.correct) {
        toast.push(`选对了！进入第 ${res.run.floor} 层`, 'success')
        beginFloor(res.run)
      } else {
        toast.push('选错了门，本次挖宝结束', 'error')
      }
    } catch (e) {
      pushError(e)
    } finally {
      busy.value = false
    }
  }

  async function retryFloor() {
    if (!run.value || busy.value) return
    busy.value = true
    try {
      const res = await api.treasureRetry(run.value.runId)
      run.value = res.run
      beginFloor(res.run)
    } catch (e) {
      pushError(e)
    } finally {
      busy.value = false
    }
  }

  async function abandon() {
    if (!run.value || busy.value) return
    busy.value = true
    try {
      const res = await api.treasureAbandon(run.value.runId)
      reset()
      // 保留已结束的 run，便于页面展示结束原因。
      run.value = res.run
    } catch (e) {
      pushError(e)
    } finally {
      busy.value = false
    }
  }

  /** 停止本地战斗循环并清空会话状态（离开页面 / 结算后调用）。 */
  function reset() {
    running.value = false
    stopLoop()
    sim.value?.pause()
    sim.value = null
    event.value = null
    gamble.value = null
    chest.value = null
    door.value = null
    logVersion.value += 1
  }

  /** 离开挖宝页：仅停本地循环，副本状态保留在服务端（可回来继续）。 */
  function leave() {
    reset()
  }

  return {
    config,
    run,
    sim,
    event,
    gamble,
    chest,
    door,
    busy,
    hero,
    stats,
    floor,
    phase,
    inBattle,
    log,
    floating,
    bosses,
    load,
    start,
    gambleGuess,
    stopGamble,
    openChest,
    chooseDoor,
    retryFloor,
    abandon,
    reset,
    leave,
  }
})
