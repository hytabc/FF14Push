import { defineStore } from 'pinia'
import { computed, ref, shallowRef } from 'vue'

import data from '@shared/schema'

import { api } from '@/api'
import { toApiError } from '@/api/client'
import { sound } from '@/game/audio'
import { BattleSimulator } from '@/game/core/battle'
import type {
  PalaceConfig,
  PalaceExchangeView,
  PalaceGrowthView,
  PalaceNodeContext,
  PalaceProfile,
  PalaceRunState,
} from '@/game/types'

import { useToastStore } from './toast'

const TICK_MS = 100
const MAX_FRAME_MS = 400
const CATCH_UP_MS = Number(data.combat.catchUpSeconds ?? 300) * 1000
const CLEAR_RETRY_MS = 700
const CLEAR_MAX_RETRIES = 8

const BATTLE_TYPES = new Set(['battle', 'elite', 'boss'])

/** 死者宫殿：客户端模拟当前节点战斗，服务端权威结算路径 / 奖励 / 成长 / 代币。 */
export const usePalaceStore = defineStore('palace', () => {
  const toast = useToastStore()

  const config = ref<PalaceConfig | null>(null)
  const profile = ref<PalaceProfile | null>(null)
  const run = ref<PalaceRunState | null>(null)
  const context = ref<PalaceNodeContext | null>(null)
  const growth = ref<PalaceGrowthView | null>(null)
  const exchange = ref<PalaceExchangeView | null>(null)

  const sim = shallowRef<BattleSimulator | null>(null)
  const running = ref(false)
  const busy = ref(false)
  const logVersion = ref(0)
  const uiTick = ref(0)

  let rafId = 0
  let tickTimer = 0
  let lastWallMs = 0
  let simBudgetMs = 0
  let reporting = false

  const inBattle = computed(() => running.value && sim.value !== null)
  const log = computed(() => {
    logVersion.value
    return sim.value?.log ?? []
  })
  const floating = computed(() => {
    logVersion.value
    return sim.value?.floating ?? []
  })
  const enemies = computed(() => {
    // 只依赖 0.1s 节拍：bossEntries() 每次求值都新建对象。
    void uiTick.value
    return sim.value?.bossEntries() ?? []
  })
  const stats = computed(() => run.value?.stats ?? null)

  function pushError(e: unknown) {
    const err = toApiError(e)
    if (err.code === 'banned') return
    toast.push(err.message, 'error')
  }

  async function load() {
    const res = await api.palaceState()
    config.value = res.config
    profile.value = res.profile
    run.value = res.run
    context.value = null
    return res
  }

  function stopLoop() {
    if (rafId) cancelAnimationFrame(rafId)
    rafId = 0
    if (tickTimer) window.clearInterval(tickTimer)
    tickTimer = 0
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
        void finishNodeIfDone()
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

  function beginBattle(target: PalaceRunState, enemy: NonNullable<PalaceNodeContext['enemy']>) {
    if (!target.stats) return
    sim.value = new BattleSimulator({
      stats: target.stats,
      raid: { bosses: [enemy], enrage: null },
      onSound: (cue) => sound.play(cue),
    })
    sim.value.start()
    running.value = true
    logVersion.value += 1
    startLoop()
  }

  async function clearNodeWithRetry(nodeId: string, elapsedMs: number, result: 'win' | 'lose') {
    for (let attempt = 0; ; attempt += 1) {
      try {
        return await api.palaceClearNode(nodeId, elapsedMs, result)
      } catch (e) {
        const err = toApiError(e)
        if (err.status !== 400 || !err.message.includes('时长') || attempt >= CLEAR_MAX_RETRIES) {
          throw e
        }
        await new Promise((resolve) => setTimeout(resolve, CLEAR_RETRY_MS))
      }
    }
  }

  async function finishNodeIfDone() {
    const current = sim.value
    const target = run.value
    const ctx = context.value
    if (!current || !target || !ctx || reporting) return
    if (current.phase !== 'cleared' && current.phase !== 'dead') return

    reporting = true
    running.value = false
    stopLoop()
    current.pause()
    const nodeId = ctx.nodeId
    try {
      if (current.phase === 'cleared') {
        const res = await clearNodeWithRetry(nodeId, Math.round(current.bossFightMs), 'win')
        run.value = res.run
        profile.value = res.profile
        if (res.level && res.level.levelsGained > 0) {
          toast.push(`副本英雄升到 ${res.level.level} 级！`, 'success')
          sound.play('battle.levelup')
        }
        if (res.bossReward) {
          const b = res.bossReward
          const tokens = [
            b.flameCrest > 0 ? `烈火纹章 ×${b.flameCrest}` : '',
            b.glassPumpkin > 0 ? `玻璃南瓜 ×${b.glassPumpkin}` : '',
          ].filter(Boolean).join('、')
          toast.push(
            `击败第 ${b.floor} 层 BOSS！成长点 +${b.growthPoints}${tokens ? `，${tokens}` : ''}`,
            'loot',
          )
          sound.play(b.completed ? 'palace.clear' : 'palace.floor')
          if (b.completed) toast.push('通关死者宫殿第 10 层！', 'success')
        } else {
          sound.play('battle.kill')
        }
      } else {
        const res = await api.palaceClearNode(nodeId, Math.round(current.bossFightMs), 'lose')
        run.value = res.run as PalaceRunState
        if ((res as { revived?: boolean }).revived) {
          toast.push('英雄倒下，但复活之息让你重返战场', 'error')
          context.value = null
        } else {
          toast.push('英雄阵亡，本次死者宫殿结束', 'error')
          context.value = null
        }
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
      const res = await api.palaceStart()
      run.value = res.run
      profile.value = res.profile
      context.value = null
      sound.play('palace.enter')
    } catch (e) {
      pushError(e)
    } finally {
      busy.value = false
    }
  }

  async function chooseHero(index: number) {
    if (busy.value) return
    busy.value = true
    try {
      const res = await api.palaceChooseHero(index)
      run.value = res.run
      sound.play('palace.choose')
    } catch (e) {
      pushError(e)
    } finally {
      busy.value = false
    }
  }

  async function chooseWeapon(index: number) {
    if (busy.value) return
    busy.value = true
    try {
      const res = await api.palaceChooseWeapon(index)
      run.value = res.run
      sound.play('palace.choose')
    } catch (e) {
      pushError(e)
    } finally {
      busy.value = false
    }
  }

  async function enterNode(nodeId: string) {
    if (busy.value) return
    busy.value = true
    try {
      resetSim()
      const res = await api.palaceEnterNode(nodeId)
      run.value = res.run
      context.value = res.context
      sound.play('palace.node')
      if (BATTLE_TYPES.has(res.context.type) && res.context.enemy) {
        beginBattle(res.run, res.context.enemy)
      } else if (res.context.type === 'chest' || res.context.type === 'rest') {
        toast.push('节点已结算', 'loot')
      }
    } catch (e) {
      pushError(e)
    } finally {
      busy.value = false
    }
  }

  async function claimReward(index: number) {
    if (busy.value) return
    busy.value = true
    try {
      const res = await api.palaceClaimReward(index)
      run.value = res.run
      sound.play('loot.drop')
    } catch (e) {
      pushError(e)
    } finally {
      busy.value = false
    }
  }

  async function eventChoose(choiceIndex: number) {
    const ctx = context.value
    if (!ctx || busy.value) return
    busy.value = true
    try {
      const res = await api.palaceEventChoose(ctx.nodeId, choiceIndex)
      run.value = res.run
      profile.value = res.profile
      context.value = null
      sound.play('ui.success')
    } catch (e) {
      pushError(e)
    } finally {
      busy.value = false
    }
  }

  async function shopBuy(offerIndex: number) {
    const ctx = context.value
    if (!ctx || busy.value) return
    busy.value = true
    try {
      const res = await api.palaceShopBuy(ctx.nodeId, offerIndex)
      run.value = res.run
      sound.play('loot.drop')
    } catch (e) {
      pushError(e)
    } finally {
      busy.value = false
    }
  }

  async function equip(index: number) {
    if (busy.value) return
    busy.value = true
    try {
      const res = await api.palaceEquip(index)
      run.value = res.run
      sound.play('ui.modal.close')
    } catch (e) {
      pushError(e)
    } finally {
      busy.value = false
    }
  }

  async function abandon() {
    if (busy.value) return
    busy.value = true
    try {
      resetSim()
      const res = await api.palaceAbandon()
      run.value = res.run
      context.value = null
      toast.push('已放弃本次死者宫殿', 'error')
    } catch (e) {
      pushError(e)
    } finally {
      busy.value = false
    }
  }

  async function loadGrowth() {
    growth.value = await api.palaceGrowth()
    return growth.value
  }

  async function unlockGrowth(nodeId: string) {
    if (busy.value) return
    busy.value = true
    try {
      const res = await api.palaceGrowthUnlock(nodeId)
      growth.value = res.view
      sound.play('palace.growth')
    } catch (e) {
      pushError(e)
    } finally {
      busy.value = false
    }
  }

  async function loadExchange() {
    exchange.value = await api.palaceExchange()
    return exchange.value
  }

  async function exchangeBuy(exchangeId: string, count = 1) {
    if (busy.value) return
    busy.value = true
    try {
      const res = await api.palaceExchangeBuy(exchangeId, count)
      exchange.value = res.view
      sound.play('palace.exchange')
    } catch (e) {
      pushError(e)
    } finally {
      busy.value = false
    }
  }

  function resetSim() {
    running.value = false
    stopLoop()
    sim.value?.pause()
    sim.value = null
    logVersion.value += 1
  }

  /** 离开页面：仅停本地循环，run 状态保留在服务端。 */
  function leave() {
    resetSim()
    context.value = null
  }

  return {
    config,
    profile,
    run,
    context,
    growth,
    exchange,
    sim,
    busy,
    inBattle,
    log,
    floating,
    enemies,
    stats,
    load,
    start,
    chooseHero,
    chooseWeapon,
    enterNode,
    claimReward,
    eventChoose,
    shopBuy,
    equip,
    abandon,
    loadGrowth,
    unlockGrowth,
    loadExchange,
    exchangeBuy,
    resetSim,
    leave,
  }
})
