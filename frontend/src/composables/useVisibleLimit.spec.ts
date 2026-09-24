import { computed, ref } from 'vue'
import { describe, expect, it } from 'vitest'

import { useVisibleLimit } from './useVisibleLimit'

function makeSource(length: number) {
  return ref(Array.from({ length }, (_, i) => i))
}

describe('useVisibleLimit', () => {
  it('只暴露首批 step 条，remaining 为剩余数量', () => {
    const source = makeSource(200)
    const { visible, remaining } = useVisibleLimit(source, 60)
    expect(visible.value).toHaveLength(60)
    expect(visible.value[0]).toBe(0)
    expect(visible.value[59]).toBe(59)
    expect(remaining.value).toBe(140)
  })

  it('showMore 按批追加，直到覆盖全部', () => {
    const source = makeSource(100)
    const { visible, remaining, showMore } = useVisibleLimit(source, 60)

    showMore()
    expect(visible.value).toHaveLength(100)
    expect(remaining.value).toBe(0)

    // 已全部渲染后再点不会越界
    showMore()
    expect(visible.value).toHaveLength(100)
    expect(remaining.value).toBe(0)
  })

  it('数据量小于 step 时直接返回全部且 remaining 为 0', () => {
    const source = makeSource(9)
    const { visible, remaining } = useVisibleLimit(source, 60)
    expect(visible.value).toHaveLength(9)
    expect(remaining.value).toBe(0)
  })

  it('数据源变化后回到首批', () => {
    const source = makeSource(200)
    const { visible, remaining, showMore } = useVisibleLimit(source, 60)
    showMore()
    showMore()
    expect(visible.value).toHaveLength(180)

    source.value = Array.from({ length: 150 }, (_, i) => i)
    expect(visible.value).toHaveLength(60)
    expect(remaining.value).toBe(90)
  })

  it('筛选结果缩小时不会残留旧的展开量', () => {
    const all = makeSource(200)
    const filtered = computed(() => all.value.filter((n) => n % 2 === 0))
    const { visible, remaining, showMore } = useVisibleLimit(filtered, 60)

    showMore()
    showMore()
    showMore()
    expect(visible.value).toHaveLength(100)
    expect(remaining.value).toBe(0)

    all.value = all.value.slice(0, 10)
    expect(visible.value).toHaveLength(5)
    expect(remaining.value).toBe(0)
  })
})
