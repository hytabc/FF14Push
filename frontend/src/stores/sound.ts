/**
 * 音效设置（本地偏好，随设备持久化）。
 *
 * 唯一持有音效设置状态：初始化与每次变更都把配置推给 `game/audio.ts` 的引擎单例，
 * 同时写入 localStorage（仿 `stores/game.ts` 的 `autoAdvance` 模式）。
 *
 * 刻意不依赖其它 store（尤其是 `stores/game.ts`），避免循环依赖 —— 引擎的
 * `play()` 是单例，任意 store / core / 组件都可直接调用。
 */
import { defineStore } from 'pinia'
import { ref, watch } from 'vue'

import { DEFAULT_SOUND_SETTINGS, sound, type SoundCue, type SoundSettings } from '@/game/audio'

const KEYS = {
  enabled: 'eorzea.sound.enabled',
  master: 'eorzea.sound.master',
  battle: 'eorzea.sound.battle',
  ui: 'eorzea.sound.ui',
  ambient: 'eorzea.sound.ambient',
} as const

function readBool(key: string, fallback: boolean): boolean {
  try {
    if (typeof localStorage === 'undefined') return fallback
    const raw = localStorage.getItem(key)
    return raw === null ? fallback : raw === '1'
  } catch {
    return fallback
  }
}

function readLevel(key: string, fallback: number): number {
  try {
    if (typeof localStorage === 'undefined') return fallback
    const raw = localStorage.getItem(key)
    if (raw === null) return fallback
    const value = Number(raw)
    return Number.isFinite(value) ? Math.min(1, Math.max(0, value)) : fallback
  } catch {
    return fallback
  }
}

function write(key: string, value: string): void {
  try {
    if (typeof localStorage !== 'undefined') localStorage.setItem(key, value)
  } catch {
    /* 隐私模式等写入失败时忽略 */
  }
}

export const useSoundStore = defineStore('sound', () => {
  const enabled = ref(readBool(KEYS.enabled, DEFAULT_SOUND_SETTINGS.enabled))
  const master = ref(readLevel(KEYS.master, DEFAULT_SOUND_SETTINGS.master))
  const battle = ref(readLevel(KEYS.battle, DEFAULT_SOUND_SETTINGS.battle))
  const ui = ref(readLevel(KEYS.ui, DEFAULT_SOUND_SETTINGS.ui))
  const ambient = ref(readLevel(KEYS.ambient, DEFAULT_SOUND_SETTINGS.ambient))

  function settings(): SoundSettings {
    return {
      enabled: enabled.value,
      master: master.value,
      battle: battle.value,
      ui: ui.value,
      ambient: ambient.value,
    }
  }

  function apply(): void {
    sound.configure(settings())
  }

  // 初始即注入配置（App.vue 启动时会创建本 store）。
  apply()

  watch(enabled, (value) => {
    write(KEYS.enabled, value ? '1' : '0')
    apply()
  })
  watch(master, (value) => {
    write(KEYS.master, String(value))
    apply()
  })
  watch(battle, (value) => {
    write(KEYS.battle, String(value))
    apply()
  })
  watch(ui, (value) => {
    write(KEYS.ui, String(value))
    apply()
  })
  watch(ambient, (value) => {
    write(KEYS.ambient, String(value))
    apply()
  })

  /** 播放音效（转发到引擎单例；未解锁 / 静音时静默返回 false）。 */
  function play(cue: SoundCue, opts?: { gain?: number }): boolean {
    return sound.play(cue, opts)
  }

  /** 首个用户手势里调用，解锁浏览器自动播放。 */
  function unlock(): void {
    sound.unlock()
  }

  /** 试听（设置页用）：无视节流地放一个代表音效。 */
  function preview(cue: SoundCue): void {
    sound.unlock()
    sound.play(cue)
  }

  function reset(): void {
    enabled.value = DEFAULT_SOUND_SETTINGS.enabled
    master.value = DEFAULT_SOUND_SETTINGS.master
    battle.value = DEFAULT_SOUND_SETTINGS.battle
    ui.value = DEFAULT_SOUND_SETTINGS.ui
    ambient.value = DEFAULT_SOUND_SETTINGS.ambient
  }

  return { enabled, master, battle, ui, ambient, play, unlock, preview, reset }
})
