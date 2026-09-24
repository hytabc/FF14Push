import { createPinia, setActivePinia } from 'pinia'
import { nextTick } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { DEFAULT_SOUND_SETTINGS, sound } from '@/game/audio'

import { useSoundStore } from './sound'

/** 内存版 localStorage（node 环境没有原生实现）。 */
class MemoryStorage {
  private map = new Map<string, string>()

  getItem(key: string): string | null {
    return this.map.has(key) ? (this.map.get(key) as string) : null
  }

  setItem(key: string, value: string): void {
    this.map.set(key, value)
  }

  removeItem(key: string): void {
    this.map.delete(key)
  }

  clear(): void {
    this.map.clear()
  }
}

let storage: MemoryStorage

beforeEach(() => {
  storage = new MemoryStorage()
  vi.stubGlobal('localStorage', storage)
  setActivePinia(createPinia())
})

afterEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

describe('音效设置 store', () => {
  it('默认值与引擎默认一致，并在创建时注入引擎', () => {
    const configure = vi.spyOn(sound, 'configure')
    const store = useSoundStore()
    expect(store.enabled).toBe(DEFAULT_SOUND_SETTINGS.enabled)
    expect(store.master).toBe(DEFAULT_SOUND_SETTINGS.master)
    expect(store.battle).toBe(DEFAULT_SOUND_SETTINGS.battle)
    expect(configure).toHaveBeenCalledWith(
      expect.objectContaining({ enabled: DEFAULT_SOUND_SETTINGS.enabled, master: DEFAULT_SOUND_SETTINGS.master }),
    )
  })

  it('修改音量会持久化并重新注入引擎', async () => {
    const configure = vi.spyOn(sound, 'configure')
    const store = useSoundStore()
    configure.mockClear()

    store.battle = 0.25
    await nextTick()

    expect(storage.getItem('eorzea.sound.battle')).toBe('0.25')
    expect(configure).toHaveBeenCalledWith(expect.objectContaining({ battle: 0.25 }))
  })

  it('关闭总开关写入 0 且不影响其它音量', async () => {
    const store = useSoundStore()
    store.enabled = false
    await nextTick()

    expect(storage.getItem('eorzea.sound.enabled')).toBe('0')
    expect(store.master).toBe(DEFAULT_SOUND_SETTINGS.master)
  })

  it('读取持久化值并对越界音量做钳制', () => {
    storage.setItem('eorzea.sound.master', '5')
    storage.setItem('eorzea.sound.battle', '-2')
    storage.setItem('eorzea.sound.enabled', '0')

    const store = useSoundStore()

    expect(store.master).toBe(1)
    expect(store.battle).toBe(0)
    expect(store.enabled).toBe(false)
  })

  it('reset 恢复默认值', async () => {
    const store = useSoundStore()
    store.master = 0.1
    store.ambient = 0.2
    await nextTick()

    store.reset()
    await nextTick()

    expect(store.master).toBe(DEFAULT_SOUND_SETTINGS.master)
    expect(store.ambient).toBe(DEFAULT_SOUND_SETTINGS.ambient)
  })
})
