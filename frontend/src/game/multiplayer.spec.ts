import { describe, expect, it } from 'vitest'
import { mergeEvents, remaining, seatQuota } from './multiplayer'
describe('multiplayer presentation', () => {
  it('describes uneven eight-hero shares', () => {
    expect([1,2,3,4,5,6,7,8].map(n => seatQuota(8,n))).toEqual(['8','4','2—3','2','1—2','1—2','1—2','1'])
  })
  it('keeps revive and weakness timers bounded', () => {
    expect(remaining(5000,4900)).toBe(1)
    expect(remaining(65000,65000)).toBe(0)
    expect(remaining(5000,6000)).toBe(0)
  })
  it('deduplicates reconnect event snapshots without losing history', () => {
    const a = { seq:1, at:100, kind:'death', text:'死亡' }, b = { seq:2, at:5100, kind:'revive', text:'复活' }
    expect(mergeEvents([a,b],[a,b])).toEqual([a,b])
    expect(mergeEvents([b],[a])).toEqual([a,b])
  })
})
