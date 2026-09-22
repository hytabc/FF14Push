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

describe('服务端周期校正', () => {
  it('首次同步超过半周期的余额时仍显示真实进度', () => {
    const clock = new ProgressClock()
    clock.sync(1800, 2)
    expect(clock.position()).toBeCloseTo(0.9)
  })

  it.each([
    [4, 2, 500, 0.25],
    [2, 4, 500, 0.125],
  ])('耗时从 %s 秒变为 %s 秒后按新余额重新计时', (before, after, credit, expected) => {
    const clock = new ProgressClock()
    clock.sync(0, before)
    clock.advance(before * 1000 * 3.8)
    clock.sync(credit, after)
    expect(clock.position()).toBeCloseTo(expected)
    expect(clock.advance(after * 1000 - credit + 50)).toBeCloseTo(50 / (after * 1000))
  })

  it('后台恢复或服务端大幅修正时不被旧进度夹住', () => {
    const clock = new ProgressClock()
    clock.sync(0, 4)
    clock.advance(2800)
    clock.sync(1800, 4)
    expect(clock.position()).toBeCloseTo(0.45)
  })

  it('停止后不再按上一个活动的周期推进', () => {
    const clock = new ProgressClock()
    clock.sync(1200, 2)
    clock.reset()
    expect(clock.advance(1000)).toBe(0)
    clock.sync(1800, 2)
    expect(clock.position()).toBeCloseTo(0.9)
  })
})
