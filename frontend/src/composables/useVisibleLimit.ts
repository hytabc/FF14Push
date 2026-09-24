import { computed, ref, watch, type Ref } from 'vue'

/**
 * 长列表渐进渲染：先渲染首批，由用户点「显示更多」按批追加。
 *
 * 用于「一次性挂载上千个节点」的浏览型列表（图鉴、选择装备弹窗）：首屏只创建
 * `step` 个节点，配合 CSS `gallery-cell`（content-visibility）把屏外元素排除在
 * 布局/绘制之外，避免切分类或打开弹窗时出现长时间的单帧任务。
 *
 * 数据源（含筛选/排序结果）变化时自动回到首批，避免沿用上一批的展开量。
 */
export function useVisibleLimit<T>(source: Ref<T[]>, step = 60) {
  const limit = ref(step)

  // 同步 flush：数据源一变就立刻回到首批，避免渲染前出现「已是新筛选、却仍展开上一批」的一帧。
  watch(
    source,
    () => {
      limit.value = step
    },
    { flush: 'sync' },
  )

  const visible = computed(() =>
    limit.value >= source.value.length ? source.value : source.value.slice(0, limit.value),
  )
  const remaining = computed(() => Math.max(0, source.value.length - limit.value))

  function showMore() {
    limit.value += step
  }

  return { visible, remaining, showMore }
}
