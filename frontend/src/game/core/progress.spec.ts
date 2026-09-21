import { describe, expect, it } from 'vitest'

import { ProgressClock } from '@/game/core/progress'

describe('ProgressClock（采集/生产/钓鱼进度条）', () => {
  it('同一轮内进度只前进：对齐服务端时的轻微回退会被夹住（不再抽搐）', () => {
    const clock = new ProgressClock()
    clock.sync(0, 2.5)
    expect(clock.advance(1250)).toBeCloseTo(0.5, 6)

    // 服务端 credit 比本地落后 50ms（网络抖动）：不能把进度打回去
    clock.sync(1200, 2.5)
    expect(clock.position()).toBeCloseTo(0.5, 6)

    // 之后继续正常前进
    expect(clock.advance(100)).toBeGreaterThan(0.5)
  })

  it('每次上报不再把进度重置为 0', () => {
    const clock = new ProgressClock()
    clock.sync(0, 2)
    expect(clock.advance(1500)).toBeCloseTo(0.75, 6)

    // 1.5s 后上报，服务端 credit 与本地对齐：应继续保持 0.75，而不是归零
    clock.sync(1500, 2)
    expect(clock.position()).toBeCloseTo(0.75, 6)
  })

  it('同一轮内持续前进，进度单调不减', () => {
    const clock = new ProgressClock()
    clock.sync(0, 2.5)
    let prev = 0
    for (let i = 0; i < 20; i += 1) {
      const pos = clock.advance(100)
      expect(pos).toBeGreaterThanOrEqual(prev)
      prev = pos
    }
  })

  it('跑满一轮后自然回绕到起点', () => {
    const clock = new ProgressClock()
    clock.sync(0, 1)
    expect(clock.advance(1100)).toBeCloseTo(0.1, 6)
  })

  it('服务端领先时向前对齐（不重置）', () => {
    const clock = new ProgressClock()
    clock.sync(0, 2)
    expect(clock.advance(1000)).toBeCloseTo(0.5, 6)

    clock.sync(1200, 2)
    expect(clock.position()).toBeCloseTo(0.6, 6)
  })

  it('未设置周期时进度恒为 0', () => {
    const clock = new ProgressClock()
    expect(clock.advance(500)).toBe(0)
    expect(clock.position()).toBe(0)
  })
})
