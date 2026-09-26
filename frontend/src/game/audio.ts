/**
 * 游戏音效引擎：用 Web Audio API 现场合成 8-bit 风格音效。
 *
 * 刻意不引入任何音频素材文件与第三方音频库：每个音效都是一段「纯数据谱面」
 * （振荡器 / 噪声的包络描述），运行时再调度给 AudioContext。好处是零体积、
 * 零版权风险、与像素风一致；且谱面是纯数据，可在 node（测试）环境下断言。
 *
 * 引擎不依赖 Vue。设置（开关 / 音量）由 `stores/sound.ts` 通过 `configure()` 注入。
 * 浏览器自动播放策略：AudioContext 必须在用户手势里 `unlock()` 后才会出声，
 * 未解锁前 `play()` 静默返回。
 */

export type SoundCategory = 'battle' | 'ui' | 'ambient'

/** 所有音效标识（联合类型即唯一事实来源，新增音效必须同时补 CUES）。 */
export type SoundCue =
  // 战斗
  | 'battle.spawn'
  | 'battle.hit'
  | 'battle.crit'
  | 'battle.miss'
  | 'battle.skill'
  | 'battle.signature'
  | 'battle.heal'
  | 'battle.hurt'
  | 'battle.kill'
  | 'battle.clear'
  | 'battle.death'
  | 'battle.revive'
  | 'battle.levelup'
  | 'battle.boss.spawn'
  | 'battle.boss.charge'
  | 'battle.boss.skill'
  // 世界BOSS（服务端推送的事件）
  | 'wb.bossSkill'
  | 'wb.death'
  | 'wb.revive'
  | 'wb.phase'
  // 界面 / 通用
  | 'ui.success'
  | 'ui.error'
  | 'ui.loot'
  | 'ui.modal.open'
  | 'ui.modal.close'
  | 'loot.drop'
  // 抽箱 / 挖宝转盘
  | 'chest.spin'
  | 'chest.reveal'
  | 'wheel.spin'
  | 'wheel.tick'
  | 'wheel.done'
  | 'treasure.door.ok'
  | 'treasure.door.bad'
  | 'treasure.chest.open'
  // 重铸 / 附魔 / 魔晶石
  | 'reroll.roll'
  | 'reroll.up'
  | 'reroll.down'
  | 'enchant.cast'
  | 'enchant.rare'
  | 'materia.ok'
  | 'materia.fail'
  // 生活职业（采集 / 生产 / 钓鱼 / 序列 / 种田）
  | 'gather.gain'
  | 'produce.craft'
  | 'produce.high'
  | 'fish.cast'
  | 'fish.catch'
  | 'fish.rare'
  | 'seq.step'
  | 'seq.done'
  | 'farm.plant'
  | 'farm.harvest'
  // 死者宫殿（roguelike 深层迷宫）
  | 'palace.enter'
  | 'palace.choose'
  | 'palace.node'
  | 'palace.floor'
  | 'palace.clear'
  | 'palace.growth'
  | 'palace.exchange'

type Wave = 'sine' | 'square' | 'triangle' | 'sawtooth'
type FilterWave = 'lowpass' | 'highpass' | 'bandpass'

/** 振荡器步骤：一段带包络的音。 */
interface ToneStep {
  kind: 'tone'
  freq: number
  /** 频率滑动的目标（Hz），省略则为固定音高。 */
  sweepTo?: number
  duration: number
  gain: number
  type: Wave
  /** 相对本音效起点的延迟（秒）。 */
  delay?: number
  /** 起音时长（秒），默认 0.005。 */
  attack?: number
}

/** 噪声步骤：撞击 / 沙沙声。 */
interface NoiseStep {
  kind: 'noise'
  duration: number
  gain: number
  delay?: number
  attack?: number
  filterHz?: number
  filterType?: FilterWave
}

export type CueStep = ToneStep | NoiseStep

export interface CueSpec {
  category: SoundCategory
  /** 同一音效的最小间隔（毫秒），0 = 不节流。 */
  throttleMs: number
  /** 基础音量倍率。 */
  gain: number
  steps: CueStep[]
}

export interface SoundSettings {
  enabled: boolean
  master: number
  battle: number
  ui: number
  ambient: number
}

export const DEFAULT_SOUND_SETTINGS: SoundSettings = {
  enabled: true,
  master: 0.6,
  battle: 0.7,
  ui: 0.7,
  ambient: 0.7,
}

/** 全局窗口内的最大并发音效数（防止 DoT / proc 高峰爆音）。 */
const MAX_VOICES_PER_WINDOW = 14
/** 并发窗口长度（毫秒）。 */
const VOICE_WINDOW_MS = 100
/** 合成提前量（秒）：给节点留出调度余量，避免起点被吃掉。 */
const LEAD_SECONDS = 0.02

function tone(freq: number, duration: number, gain: number, type: Wave = 'square', extra?: Partial<ToneStep>): ToneStep {
  return { kind: 'tone', freq, duration, gain, type, ...extra }
}

function sweep(
  freq: number,
  sweepTo: number,
  duration: number,
  gain: number,
  type: Wave = 'square',
  extra?: Partial<ToneStep>,
): ToneStep {
  return { kind: 'tone', freq, sweepTo, duration, gain, type, ...extra }
}

function noise(duration: number, gain: number, filterHz = 1400, filterType: FilterWave = 'lowpass', delay?: number): NoiseStep {
  return { kind: 'noise', duration, gain, filterHz, filterType, delay }
}

function cue(category: SoundCategory, throttleMs: number, gain: number, steps: CueStep[]): CueSpec {
  return { category, throttleMs, gain, steps }
}

/** 上行音阶（成功 / 升级感）。 */
function arpeggio(freqs: number[], step = 0.1, duration = 0.12, gain = 0.4): CueStep[] {
  return freqs.map((freq, index) => tone(freq, duration, gain, 'square', { delay: index * step }))
}

/**
 * 音效谱面。键集由 `SoundCue` 联合类型穷尽校验（缺项即编译报错）。
 */
export const CUES: Record<SoundCue, CueSpec> = {
  // ---------------- 战斗 ----------------
  'battle.spawn': cue('battle', 150, 0.5, [sweep(320, 560, 0.12, 0.5, 'triangle')]),
  'battle.hit': cue('battle', 70, 0.32, [
    noise(0.05, 0.5, 2800),
    sweep(240, 140, 0.06, 0.24, 'square'),
  ]),
  'battle.crit': cue('battle', 110, 0.6, [
    sweep(880, 1320, 0.09, 0.5, 'square'),
    noise(0.07, 0.5, 4200, 'highpass'),
    tone(1760, 0.12, 0.3, 'triangle', { delay: 0.03 }),
  ]),
  'battle.miss': cue('battle', 200, 0.3, [sweep(420, 170, 0.14, 0.32, 'sine')]),
  'battle.skill': cue('battle', 130, 0.42, [
    sweep(300, 900, 0.18, 0.4, 'sawtooth'),
    tone(1180, 0.1, 0.2, 'triangle', { delay: 0.05 }),
  ]),
  'battle.signature': cue('battle', 400, 0.62, [
    sweep(220, 1400, 0.4, 0.5, 'sawtooth'),
    tone(660, 0.34, 0.32, 'square', { delay: 0.08, sweepTo: 1760 }),
    noise(0.3, 0.28, 5200, 'highpass'),
  ]),
  'battle.heal': cue('battle', 220, 0.4, [
    tone(660, 0.14, 0.34, 'sine'),
    tone(880, 0.16, 0.34, 'sine', { delay: 0.08 }),
    tone(1174, 0.2, 0.3, 'sine', { delay: 0.16 }),
  ]),
  'battle.hurt': cue('battle', 110, 0.42, [
    sweep(180, 80, 0.16, 0.5, 'square'),
    noise(0.12, 0.36, 700),
  ]),
  'battle.kill': cue('battle', 140, 0.48, [
    noise(0.13, 0.5, 1900),
    sweep(520, 150, 0.18, 0.36, 'square'),
  ]),
  'battle.clear': cue('battle', 700, 0.68, [
    ...arpeggio([523, 659, 784], 0.12, 0.13, 0.42),
    tone(1046, 0.42, 0.46, 'square', { delay: 0.36 }),
    tone(784, 0.42, 0.24, 'triangle', { delay: 0.36 }),
  ]),
  'battle.death': cue('battle', 800, 0.58, [
    sweep(440, 110, 0.6, 0.5, 'sawtooth'),
    sweep(220, 70, 0.5, 0.3, 'square', { delay: 0.1 }),
  ]),
  'battle.revive': cue('battle', 600, 0.52, [
    sweep(220, 900, 0.45, 0.42, 'triangle'),
    tone(1320, 0.24, 0.28, 'sine', { delay: 0.34 }),
  ]),
  'battle.levelup': cue('battle', 800, 0.68, [
    ...arpeggio([523, 659, 784, 1046], 0.09, 0.1, 0.4),
    tone(1318, 0.32, 0.5, 'square', { delay: 0.36 }),
  ]),
  'battle.boss.spawn': cue('battle', 900, 0.62, [
    tone(110, 0.62, 0.5, 'sawtooth'),
    tone(165, 0.6, 0.32, 'sawtooth', { delay: 0.02 }),
    noise(0.5, 0.3, 500),
  ]),
  'battle.boss.charge': cue('battle', 700, 0.48, [
    sweep(200, 720, 0.55, 0.4, 'triangle'),
    tone(900, 0.12, 0.24, 'square', { delay: 0.5 }),
  ]),
  'battle.boss.skill': cue('battle', 350, 0.58, [
    sweep(700, 170, 0.3, 0.5, 'sawtooth'),
    noise(0.26, 0.38, 900),
    sweep(150, 70, 0.3, 0.38, 'square', { delay: 0.05 }),
  ]),

  // ---------------- 世界BOSS ----------------
  'wb.bossSkill': cue('battle', 900, 0.55, [
    sweep(620, 160, 0.34, 0.46, 'sawtooth'),
    tone(200, 0.3, 0.34, 'square', { delay: 0.06, sweepTo: 90 }),
    noise(0.24, 0.3, 800, 'lowpass', 0.04),
  ]),
  'wb.death': cue('battle', 1200, 0.55, [
    sweep(360, 90, 0.55, 0.46, 'sawtooth'),
    tone(180, 0.4, 0.3, 'square', { delay: 0.12 }),
  ]),
  'wb.revive': cue('battle', 1200, 0.5, [
    sweep(200, 780, 0.4, 0.38, 'triangle'),
    tone(1046, 0.22, 0.26, 'sine', { delay: 0.3 }),
  ]),
  'wb.phase': cue('battle', 1500, 0.6, [
    tone(98, 0.5, 0.5, 'sawtooth'),
    tone(147, 0.5, 0.34, 'sawtooth', { delay: 0.04 }),
    tone(196, 0.7, 0.32, 'square', { delay: 0.18 }),
  ]),

  // ---------------- 界面 / 通用 ----------------
  'ui.success': cue('ui', 150, 0.4, [...arpeggio([784, 1046], 0.08, 0.1, 0.34)]),
  'ui.error': cue('ui', 200, 0.42, [
    tone(330, 0.12, 0.38, 'square'),
    tone(196, 0.18, 0.38, 'square', { delay: 0.1 }),
  ]),
  'ui.loot': cue('ui', 140, 0.42, [
    tone(1046, 0.1, 0.34, 'triangle'),
    tone(1568, 0.16, 0.3, 'triangle', { delay: 0.06 }),
  ]),
  'ui.modal.open': cue('ui', 120, 0.3, [sweep(520, 780, 0.1, 0.3, 'sine')]),
  'ui.modal.close': cue('ui', 120, 0.3, [sweep(780, 480, 0.1, 0.28, 'sine')]),
  'loot.drop': cue('ui', 90, 0.38, [
    tone(880, 0.09, 0.3, 'triangle'),
    tone(1318, 0.14, 0.26, 'triangle', { delay: 0.05 }),
  ]),

  // ---------------- 抽箱 / 挖宝转盘 ----------------
  'chest.spin': cue('ui', 200, 0.36, [
    noise(0.18, 0.28, 2200, 'bandpass'),
    sweep(400, 900, 0.2, 0.28, 'square'),
  ]),
  'chest.reveal': cue('ui', 120, 0.5, [
    tone(1046, 0.12, 0.38, 'triangle'),
    tone(1568, 0.22, 0.34, 'triangle', { delay: 0.07 }),
    noise(0.12, 0.22, 5000, 'highpass', 0.02),
  ]),
  'wheel.spin': cue('ui', 200, 0.34, [sweep(360, 820, 0.18, 0.3, 'square')]),
  'wheel.tick': cue('ui', 120, 0.34, [
    tone(1200, 0.05, 0.3, 'square'),
    noise(0.04, 0.28, 3600, 'highpass'),
  ]),
  'wheel.done': cue('ui', 500, 0.55, [
    ...arpeggio([698, 880, 1046], 0.1, 0.12, 0.38),
    tone(1396, 0.3, 0.4, 'triangle', { delay: 0.3 }),
  ]),
  'treasure.door.ok': cue('ui', 400, 0.5, [
    sweep(300, 720, 0.24, 0.4, 'triangle'),
    tone(1174, 0.22, 0.32, 'sine', { delay: 0.2 }),
  ]),
  'treasure.door.bad': cue('ui', 400, 0.5, [
    sweep(400, 150, 0.3, 0.44, 'sawtooth'),
    noise(0.2, 0.3, 600),
  ]),
  'treasure.chest.open': cue('ui', 250, 0.5, [
    noise(0.16, 0.4, 1600),
    sweep(300, 1000, 0.26, 0.38, 'triangle'),
    tone(1318, 0.2, 0.3, 'triangle', { delay: 0.18 }),
  ]),

  // ---------------- 重铸 / 附魔 / 魔晶石 ----------------
  'reroll.roll': cue('ui', 120, 0.4, [
    sweep(500, 1100, 0.16, 0.34, 'square'),
    noise(0.1, 0.24, 3000, 'bandpass'),
  ]),
  'reroll.up': cue('ui', 150, 0.46, [...arpeggio([880, 1174, 1568], 0.07, 0.1, 0.34)]),
  'reroll.down': cue('ui', 150, 0.42, [...arpeggio([784, 587, 440], 0.07, 0.12, 0.34)]),
  'enchant.cast': cue('ui', 150, 0.4, [
    sweep(420, 1320, 0.28, 0.36, 'triangle'),
    noise(0.2, 0.22, 4200, 'highpass', 0.04),
  ]),
  'enchant.rare': cue('ui', 400, 0.6, [
    ...arpeggio([1046, 1318, 1568], 0.08, 0.12, 0.4),
    tone(2093, 0.34, 0.34, 'triangle', { delay: 0.24 }),
  ]),
  'materia.ok': cue('ui', 200, 0.46, [
    tone(1318, 0.1, 0.34, 'triangle'),
    tone(1760, 0.2, 0.32, 'triangle', { delay: 0.07 }),
  ]),
  'materia.fail': cue('ui', 200, 0.44, [
    sweep(320, 160, 0.16, 0.4, 'square'),
    noise(0.14, 0.3, 800),
  ]),

  // ---------------- 生活职业 ----------------
  'gather.gain': cue('ambient', 120, 0.36, [
    noise(0.08, 0.34, 2400, 'bandpass'),
    tone(659, 0.1, 0.26, 'triangle', { delay: 0.02 }),
  ]),
  'produce.craft': cue('ambient', 120, 0.38, [
    noise(0.08, 0.36, 1500),
    tone(440, 0.12, 0.3, 'square', { delay: 0.02, sweepTo: 660 }),
  ]),
  'produce.high': cue('ambient', 300, 0.52, [
    ...arpeggio([784, 988, 1318], 0.08, 0.11, 0.36),
    tone(1568, 0.28, 0.34, 'triangle', { delay: 0.24 }),
  ]),
  'fish.cast': cue('ambient', 250, 0.36, [
    noise(0.12, 0.3, 3000, 'highpass'),
    sweep(600, 300, 0.2, 0.26, 'sine'),
  ]),
  'fish.catch': cue('ambient', 150, 0.42, [
    tone(880, 0.09, 0.32, 'triangle'),
    tone(1174, 0.14, 0.3, 'triangle', { delay: 0.06 }),
  ]),
  'fish.rare': cue('ambient', 500, 0.58, [
    ...arpeggio([1046, 1318, 1568, 2093], 0.09, 0.12, 0.4),
  ]),
  'seq.step': cue('ambient', 150, 0.4, [...arpeggio([698, 880], 0.08, 0.1, 0.32)]),
  'seq.done': cue('ambient', 600, 0.55, [
    ...arpeggio([659, 784, 988, 1318], 0.1, 0.12, 0.38),
  ]),
  'farm.plant': cue('ambient', 200, 0.38, [
    noise(0.1, 0.3, 900),
    sweep(300, 620, 0.16, 0.3, 'sine'),
  ]),
  'farm.harvest': cue('ambient', 200, 0.46, [...arpeggio([784, 1046, 1318], 0.08, 0.11, 0.36)]),

  // ---------------- 死者宫殿 ----------------
  'palace.enter': cue('ui', 400, 0.5, [
    tone(146, 0.5, 0.42, 'sawtooth'),
    tone(220, 0.46, 0.3, 'sawtooth', { delay: 0.05 }),
    noise(0.4, 0.24, 480),
  ]),
  'palace.choose': cue('ui', 150, 0.44, [...arpeggio([698, 988, 1318], 0.08, 0.1, 0.34)]),
  'palace.node': cue('ui', 120, 0.36, [
    sweep(420, 700, 0.12, 0.28, 'square'),
    noise(0.06, 0.2, 2600, 'bandpass'),
  ]),
  'palace.floor': cue('battle', 700, 0.6, [
    ...arpeggio([440, 587, 880], 0.12, 0.14, 0.4),
    tone(1174, 0.4, 0.42, 'square', { delay: 0.36 }),
  ]),
  'palace.clear': cue('battle', 1200, 0.7, [
    ...arpeggio([523, 659, 784, 1046], 0.12, 0.14, 0.42),
    tone(1568, 0.5, 0.44, 'triangle', { delay: 0.5 }),
  ]),
  'palace.growth': cue('ui', 200, 0.46, [
    tone(880, 0.1, 0.32, 'triangle'),
    tone(1318, 0.22, 0.34, 'triangle', { delay: 0.08 }),
  ]),
  'palace.exchange': cue('ui', 200, 0.46, [
    tone(988, 0.09, 0.32, 'triangle'),
    tone(1244, 0.2, 0.34, 'triangle', { delay: 0.07 }),
  ]),
}

/** 节流 / 并发闸门状态（独立于音频硬件，便于测试）。 */
export interface GateState {
  lastPlayed: Map<SoundCue, number>
  windowStart: number
  windowCount: number
}

export function createGateState(): GateState {
  return { lastPlayed: new Map(), windowStart: 0, windowCount: 0 }
}

/**
 * 判断某个音效此刻是否允许播放，并在允许时推进闸门状态（纯函数式副作用）。
 *
 * - 未知音效直接拒绝；
 * - 同一音效在 `throttleMs` 内重复触发被节流；
 * - 全局 `VOICE_WINDOW_MS` 窗口内超过 `MAX_VOICES_PER_WINDOW` 个音效被丢弃。
 */
export function gate(state: GateState, cue: SoundCue, nowMs: number): boolean {
  const spec = CUES[cue]
  if (!spec) return false
  const last = state.lastPlayed.get(cue)
  if (last !== undefined && nowMs - last < spec.throttleMs) return false
  if (nowMs - state.windowStart >= VOICE_WINDOW_MS) {
    state.windowStart = nowMs
    state.windowCount = 0
  }
  if (state.windowCount >= MAX_VOICES_PER_WINDOW) return false
  state.lastPlayed.set(cue, nowMs)
  state.windowCount += 1
  return true
}

interface AudioContextLike {
  state: string
  currentTime: number
  sampleRate: number
  destination: AudioNode
  createGain(): GainNode
  createOscillator(): OscillatorNode
  createBufferSource(): AudioBufferSourceNode
  createBiquadFilter(): BiquadFilterNode
  createBuffer(channels: number, length: number, sampleRate: number): AudioBuffer
  resume(): Promise<void>
}

function audioContextCtor(): (new () => AudioContextLike) | null {
  if (typeof window === 'undefined') return null
  const w = window as unknown as {
    AudioContext?: new () => AudioContextLike
    webkitAudioContext?: new () => AudioContextLike
  }
  return w.AudioContext ?? w.webkitAudioContext ?? null
}

function nowMs(): number {
  if (typeof performance !== 'undefined' && typeof performance.now === 'function') return performance.now()
  return Date.now()
}

function isHidden(): boolean {
  return typeof document !== 'undefined' && document.hidden === true
}

export interface PlayOptions {
  /** 音量缩放（1 = 谱面默认）。 */
  gain?: number
}

/**
 * 音效引擎单例。调用方（store / core / 组件）只需 `sound.play('battle.crit')`。
 */
export class SoundEngine {
  private settings: SoundSettings = { ...DEFAULT_SOUND_SETTINGS }
  private ctx: AudioContextLike | null = null
  private masterGain: GainNode | null = null
  private categoryGains: Record<SoundCategory, GainNode> | null = null
  private noiseBuffer: AudioBuffer | null = null
  private readonly gateState = createGateState()

  /** 注入设置（开关 / 各级音量）。未创建 AudioContext 时先记住，下次创建时应用。 */
  configure(settings: SoundSettings): void {
    this.settings = { ...settings }
    this.applyGains()
  }

  /** 在首个用户手势里调用：创建 / 恢复 AudioContext，之后才可能出声。 */
  unlock(): void {
    const ctx = this.ensureContext()
    if (!ctx) return
    if (ctx.state !== 'running') {
      try {
        void ctx.resume().catch(() => {})
      } catch {
        /* 忽略：某些实现可能同步抛错 */
      }
    }
  }

  /** 是否允许发声（开关 + 已解锁 + 页面可见）。用于 UI 提示 / 试听。 */
  get ready(): boolean {
    return this.settings.enabled && this.ctx !== null && this.ctx.state === 'running'
  }

  /**
   * 播放一个音效。返回是否真的调度了（被节流 / 静音 / 未解锁 / 环境不支持时返回 false）。
   */
  play(cue: SoundCue, opts?: PlayOptions): boolean {
    if (!this.settings.enabled) return false
    if (!CUES[cue]) return false
    if (!gate(this.gateState, cue, nowMs())) return false
    const ctx = this.ensureContext()
    if (!ctx || ctx.state !== 'running') return false
    if (isHidden()) return false
    const dest = this.categoryGains?.[CUES[cue].category]
    if (!dest) return false
    const base = CUES[cue].gain * (opts?.gain ?? 1)
    if (base <= 0) return false
    const start = ctx.currentTime + LEAD_SECONDS
    for (const step of CUES[cue].steps) {
      try {
        this.scheduleStep(ctx, dest, step, base, start)
      } catch {
        /* 单个步骤失败不影响其余 */
      }
    }
    return true
  }

  private ensureContext(): AudioContextLike | null {
    if (this.ctx) return this.ctx
    const Ctor = audioContextCtor()
    if (!Ctor) return null
    try {
      const ctx = new Ctor()
      const master = ctx.createGain()
      master.connect(ctx.destination)
      const gains: Record<SoundCategory, GainNode> = {
        battle: ctx.createGain(),
        ui: ctx.createGain(),
        ambient: ctx.createGain(),
      }
      for (const node of Object.values(gains)) node.connect(master)
      this.ctx = ctx
      this.masterGain = master
      this.categoryGains = gains
      this.applyGains()
      return ctx
    } catch {
      return null
    }
  }

  private applyGains(): void {
    if (!this.masterGain || !this.categoryGains) return
    this.masterGain.gain.value = this.settings.enabled ? clamp01(this.settings.master) : 0
    this.categoryGains.battle.gain.value = clamp01(this.settings.battle)
    this.categoryGains.ui.gain.value = clamp01(this.settings.ui)
    this.categoryGains.ambient.gain.value = clamp01(this.settings.ambient)
  }

  private scheduleStep(ctx: AudioContextLike, dest: GainNode, step: CueStep, base: number, start: number): void {
    const at = start + (step.delay ?? 0)
    const peak = base * step.gain
    if (peak <= 0) return
    const duration = Math.max(0.01, step.duration)
    const attack = Math.max(0.001, step.attack ?? 0.005)
    const gain = ctx.createGain()
    gain.gain.setValueAtTime(0, at)
    gain.gain.linearRampToValueAtTime(peak, at + Math.min(attack, duration))
    // 指数收尾不能到 0，用一个极小值代替。
    gain.gain.exponentialRampToValueAtTime(0.0001, at + duration)

    if (step.kind === 'tone') {
      const osc = ctx.createOscillator()
      osc.type = step.type
      osc.frequency.setValueAtTime(Math.max(1, step.freq), at)
      if (step.sweepTo !== undefined) {
        osc.frequency.exponentialRampToValueAtTime(Math.max(1, step.sweepTo), at + duration)
      }
      osc.connect(gain)
      gain.connect(dest)
      osc.start(at)
      osc.stop(at + duration + 0.02)
    } else {
      const src = ctx.createBufferSource()
      src.buffer = this.ensureNoise(ctx)
      const filter = ctx.createBiquadFilter()
      filter.type = step.filterType ?? 'lowpass'
      filter.frequency.value = step.filterHz ?? 1400
      src.connect(filter)
      filter.connect(gain)
      gain.connect(dest)
      src.start(at)
      src.stop(at + duration + 0.02)
    }
  }

  private ensureNoise(ctx: AudioContextLike): AudioBuffer {
    if (this.noiseBuffer) return this.noiseBuffer
    const length = Math.max(1, Math.floor(ctx.sampleRate * 0.5))
    const buffer = ctx.createBuffer(1, length, ctx.sampleRate)
    const data = buffer.getChannelData(0)
    for (let i = 0; i < length; i += 1) data[i] = Math.random() * 2 - 1
    this.noiseBuffer = buffer
    return buffer
  }
}

function clamp01(value: number): number {
  if (!Number.isFinite(value)) return 0
  return Math.min(1, Math.max(0, value))
}

/** 全局音效引擎单例。 */
export const sound = new SoundEngine()
