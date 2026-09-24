<script setup lang="ts">
import { computed } from 'vue'

import { bossFigureUrl } from '@/utils/boss'

const props = withDefaults(
  defineProps<{
    /** BOSS id（`shared/data/worldboss.json` 的 `boss.id`）；无对应素材时渲染兜底徽章。 */
    bossKey?: string | null
    /** BOSS 名（无障碍替代文本）。 */
    name?: string
  }>(),
  { bossKey: null, name: '' },
)

const url = computed(() => bossFigureUrl(props.bossKey))
</script>

<template>
  <!-- 高度由父容器的 h-* 决定（h-full）：同一张立绘在移动端 / 桌面端可自适应缩放 -->
  <img
    v-if="url"
    class="pixel-icon h-full w-auto max-w-full select-none object-contain object-bottom"
    :src="url"
    :alt="name"
    decoding="async"
    draggable="false"
  />
  <span
    v-else
    class="grid h-full aspect-square place-items-center rounded-full bg-ink-900 text-3xl ring-1 ring-amber-500/40"
    :title="name"
    aria-hidden="true"
  >
    🐲
  </span>
</template>
