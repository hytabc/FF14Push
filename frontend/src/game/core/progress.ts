/**
 * 用服务端实际耗时与余额驱动采集 / 生产 / 钓鱼进度。
 * 只抑制同周期内的小幅网络抖动；初次同步、速度变化及大幅校正必须以服务端为准。
 */
export class ProgressClock {
  /** 用于周期插值的累计毫秒数；服务端校正时可重新定位。 */
  private cycleMs = 0
  /** 一个动作的周期（毫秒）；0 表示未开始 / 无周期。 */
  private periodMs = 0
  /** 上次展示的轮次序号与轮内进度，用于夹住同轮内的回退。 */
  private shownCycle = 0
  private shownPos = 0

  /** 复用当前周期（秒），语义同 sync 的 seconds 参数。 */
  setPeriod(seconds: number): void {
    this.periodMs = seconds > 0 ? seconds * 1000 : 0
  }

  /** 按服务端 cycle 对齐。creditMs 已含半 RTT 补偿。 */
  sync(creditMs: number, seconds: number): void {
    const previousPeriod = this.periodMs
    this.setPeriod(seconds)
    if (this.periodMs <= 0) {
      this.reset()
      return
    }
    // 不能把旧周期累计的毫秒数按新周期重新分轮，也不能沿用旧展示进度。
    if (previousPeriod !== this.periodMs) {
      this.rebase(creditMs)
      return
    }
    const period = this.periodMs
    const targetPos = ((creditMs % period) + period) % period
    const index = Math.floor(this.cycleMs / period)
    const currentPos = this.cycleMs - index * period
    // 周期内最短偏差：正常运行时服务端与本地相位差远小于半周期，取最短即正确方向。
    let diff = targetPos - currentPos
    if (diff > period / 2) diff -= period
    else if (diff < -period / 2) diff += period
    if (Math.abs(diff) > Math.min(100, period * 0.05)) {
      this.rebase(creditMs)
      return
    }
    this.cycleMs = Math.max(0, this.cycleMs + diff)
  }

  private rebase(creditMs: number): void {
    this.cycleMs = Math.max(0, creditMs)
    this.shownCycle = Math.floor(this.cycleMs / this.periodMs)
    this.shownPos = 0
  }

  /** 推进 deltaMs 毫秒，返回当前轮内进度 0..1。 */
  advance(deltaMs: number): number {
    if (this.periodMs <= 0) return 0
    this.cycleMs += Math.max(0, deltaMs)
    return this.position()
  }

  /** 重新计算并返回轮内进度（同一轮内不回退）。 */
  position(): number {
    if (this.periodMs <= 0) return 0
    const period = this.periodMs
    const index = Math.floor(this.cycleMs / period)
    let pos = this.cycleMs / period - index
    if (index === this.shownCycle && pos < this.shownPos) pos = this.shownPos
    this.shownCycle = index
    this.shownPos = pos
    return pos
  }

  /** 停止 / 切换活动时清空。 */
  reset(): void {
    this.periodMs = 0
    this.cycleMs = 0
    this.shownCycle = 0
    this.shownPos = 0
  }
}
