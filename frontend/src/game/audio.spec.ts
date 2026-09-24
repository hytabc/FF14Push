import { describe, expect, it } from 'vitest'

import {
  CUES,
  DEFAULT_SOUND_SETTINGS,
  SoundEngine,
  createGateState,
  gate,
  sound,
  type SoundCue,
} from './audio'

const entries = Object.entries(CUES) as Array<[SoundCue, (typeof CUES)[SoundCue]]>

describe('音效谱面（纯数据）', () => {
  it('每个音效都有合法的分类 / 节流 / 音量与非空步骤', () => {
    expect(entries.length).toBeGreaterThan(30)
    for (const [cue, spec] of entries) {
      expect(cue).toMatch(/^[a-z]+(\.[a-zA-Z]+)+$/)
      expect(['battle', 'ui', 'ambient']).toContain(spec.category)
      expect(spec.throttleMs).toBeGreaterThanOrEqual(0)
      expect(spec.gain).toBeGreaterThan(0)
      expect(spec.gain).toBeLessThanOrEqual(2)
      expect(spec.steps.length).toBeGreaterThan(0)
      for (const step of spec.steps) {
        expect(step.duration).toBeGreaterThan(0)
        expect(step.gain).toBeGreaterThan(0)
        expect(step.delay ?? 0).toBeGreaterThanOrEqual(0)
        if (step.kind === 'tone') {
          expect(step.freq).toBeGreaterThan(0)
          if (step.sweepTo !== undefined) expect(step.sweepTo).toBeGreaterThan(0)
        } else {
          expect(step.filterHz ?? 1).toBeGreaterThan(0)
        }
      }
    }
  })

  it('战斗 / 界面 / 生活 三类都有音效', () => {
    const categories = new Set(entries.map(([, spec]) => spec.category))
    expect(categories).toEqual(new Set(['battle', 'ui', 'ambient']))
  })

  it('各场景的关键音效齐备', () => {
    const required: SoundCue[] = [
      // 战斗
      'battle.hit',
      'battle.crit',
      'battle.skill',
      'battle.signature',
      'battle.kill',
      'battle.clear',
      'battle.death',
      'battle.revive',
      'battle.levelup',
      'battle.boss.spawn',
      'battle.boss.charge',
      'battle.boss.skill',
      // 世界BOSS
      'wb.bossSkill',
      'wb.death',
      'wb.revive',
      'wb.phase',
      // 抽箱 / 挖宝转盘
      'chest.spin',
      'chest.reveal',
      'wheel.spin',
      'wheel.tick',
      'wheel.done',
      'treasure.door.ok',
      'treasure.door.bad',
      'treasure.chest.open',
      // 重铸 / 附魔 / 魔晶石
      'reroll.roll',
      'reroll.up',
      'reroll.down',
      'enchant.cast',
      'enchant.rare',
      'materia.ok',
      'materia.fail',
      // 生活职业
      'gather.gain',
      'produce.craft',
      'produce.high',
      'fish.cast',
      'fish.catch',
      'fish.rare',
      'seq.step',
      'seq.done',
      'farm.plant',
      'farm.harvest',
      // 通用
      'loot.drop',
    ]
    for (const cue of required) expect(CUES[cue]).toBeDefined()
  })

  it('默认设置取值合法且默认开启', () => {
    expect(DEFAULT_SOUND_SETTINGS.enabled).toBe(true)
    for (const value of [DEFAULT_SOUND_SETTINGS.master, DEFAULT_SOUND_SETTINGS.battle, DEFAULT_SOUND_SETTINGS.ui, DEFAULT_SOUND_SETTINGS.ambient]) {
      expect(value).toBeGreaterThan(0)
      expect(value).toBeLessThanOrEqual(1)
    }
  })
})

describe('节流与并发闸门', () => {
  it('同一音效在节流窗口内只放行一次', () => {
    const state = createGateState()
    const spec = CUES['battle.hit']
    expect(gate(state, 'battle.hit', 1000)).toBe(true)
    expect(gate(state, 'battle.hit', 1000 + spec.throttleMs - 1)).toBe(false)
    expect(gate(state, 'battle.hit', 1000 + spec.throttleMs)).toBe(true)
  })

  it('不同音效互不节流', () => {
    const state = createGateState()
    expect(gate(state, 'battle.hit', 0)).toBe(true)
    expect(gate(state, 'battle.crit', 0)).toBe(true)
    expect(gate(state, 'battle.hit', 0)).toBe(false)
  })

  it('同一窗口内超过上限的请求被丢弃，窗口滑动后恢复', () => {
    const state = createGateState()
    const cues = Object.keys(CUES) as SoundCue[]
    expect(cues.length).toBeGreaterThan(20)

    // 轮换不同音效绕开自身节流，只考验全局并发上限。
    let allowed = 0
    for (const cue of cues) if (gate(state, cue, 10)) allowed += 1
    expect(allowed).toBe(14)

    // 窗口滑动（≥100ms）后，此前未播放过的音效可重新放行。
    const fresh = cues.find((cue) => !state.lastPlayed.has(cue))
    expect(fresh).toBeDefined()
    expect(gate(state, fresh as SoundCue, 110)).toBe(true)
  })

  it('未知音效被拒绝', () => {
    const state = createGateState()
    expect(gate(state, 'nope.nothing' as SoundCue, 0)).toBe(false)
  })
})

describe('引擎在无音频环境下安全降级', () => {
  it('node（无 AudioContext）下 configure / unlock / play 均不抛错且静态返回 false', () => {
    const engine = new SoundEngine()
    expect(() => engine.configure({ ...DEFAULT_SOUND_SETTINGS })).not.toThrow()
    expect(() => engine.unlock()).not.toThrow()
    expect(engine.play('battle.crit')).toBe(false)
    expect(engine.ready).toBe(false)
  })

  it('总开关关闭时不发声', () => {
    const engine = new SoundEngine()
    engine.configure({ ...DEFAULT_SOUND_SETTINGS, enabled: false })
    expect(engine.play('battle.crit')).toBe(false)
  })

  it('未知音效返回 false', () => {
    const engine = new SoundEngine()
    engine.configure({ ...DEFAULT_SOUND_SETTINGS })
    expect(engine.play('nope.nothing' as SoundCue)).toBe(false)
  })

  it('导出的单例可直接调用', () => {
    expect(() => sound.play('ui.success')).not.toThrow()
    expect(sound.ready).toBe(false)
  })
})
