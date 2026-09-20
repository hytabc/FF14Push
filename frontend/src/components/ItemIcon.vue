<script setup lang="ts">
import { computed } from 'vue'

import type { RarityId } from '@/game/types'
import { rarityHex } from '@/utils/format'
import { itemIconName, itemIconUrl } from '@/utils/icons'

const props = withDefaults(
  defineProps<{
    baseId: string
    rarity: RarityId
    /** 渲染边长（px）。源图为 16×16，建议取 16 的整数倍。 */
    size?: number
    /** full：品阶色描边 + 光晕；lite：仅单侧光晕（用于图鉴等大批量场景）。 */
    variant?: 'full' | 'lite'
    /** 灰黑剪影，用于图鉴未解锁条目。 */
    silhouette?: boolean
  }>(),
  { size: 32, variant: 'full', silhouette: false },
)

const url = computed(() => itemIconUrl(props.baseId))

const style = computed(() => {
  const box = { width: `${props.size}px`, height: `${props.size}px` }
  if (props.silhouette) {
    return { ...box, filter: 'grayscale(1) brightness(0.35)' }
  }

  const color = rarityHex(props.rarity)
  if (props.variant === 'lite') {
    return { ...box, filter: `drop-shadow(0 0 2px ${color})` }
  }

  const offset = props.size >= 40 ? 2 : 1
  const filter = [
    `drop-shadow(${offset}px 0 0 ${color})`,
    `drop-shadow(${-offset}px 0 0 ${color})`,
    `drop-shadow(0 ${offset}px 0 ${color})`,
    `drop-shadow(0 ${-offset}px 0 ${color})`,
    `drop-shadow(0 0 3px ${color})`,
  ].join(' ')
  return { ...box, filter }
})
</script>

<template>
  <img
    v-if="url"
    class="pixel-icon shrink-0 select-none"
    :src="url"
    :width="size"
    :height="size"
    :style="style"
    :alt="itemIconName(baseId)"
    decoding="async"
    draggable="false"
  />
</template>
