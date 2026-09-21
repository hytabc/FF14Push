/**
 * 单次动作进度时钟（采集 / 生产 / 钓鱼）。
 *
 * 服务端下发的 `cycle { seconds, credit }` 只是「某一刻距下一次动作的余额」。
 * 客户端需要据此插值出连续进度条，但直接用 `credit + elapsed` 反复重算会在每次上报时
 * 产生相位跳变（旧实现甚至直接 `progress = 0`），导致进度条运行到一半来回抽搐。
 *
 * 这里用一个**单调推进**的虚拟毫秒数来驱动展示：
 * - 时间只前进，且对齐服务端时只做周期内的最小修正，不重置；
 * - 同一轮内展示进度只增不减，抵消网络抖动带来的轻微回退；
 * - 只有真正跨轮时才回绕到 0（进度条本该重新开始）。
 */
export class ProgressClock {
  /** 单调推进的「距下一次动作」虚拟毫秒数。 */
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
    this.setPeriod(seconds)
    if (this.periodMs <= 0) return
    const period = this.periodMs
    const targetPos = ((creditMs % period) + period) % period
    const index = Math.floor(this.cycleMs / period)
    const currentPos = this.cycleMs - index * period
    // 周期内最短偏差：正常运行时服务端与本地相位差远小于半周期，取最短即正确方向。
    let diff = targetPos - currentPos
    if (diff > period / 2) diff -= period
    else if (diff < -period / 2) diff += period
    this.cycleMs = Math.max(0, this.cycleMs + diff)
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
    this.cycleMs = 0
    this.shownCycle = 0
    this.shownPos = 0
  }
}
