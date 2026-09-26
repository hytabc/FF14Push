<script setup lang="ts">
import { computed } from 'vue'

import { weatherIconUrl } from '@/utils/weatherIcons'

const props = withDefaults(
  defineProps<{
    /** 天气 id（`shared/data/weather.json` 的 `types[].id`）。 */
    weatherId: string
    /** 渲染边长（px）。源图为 40×40。 */
    size?: number
    /** 缺图标时的兜底色点颜色（`conditions.weatherHex`）。 */
    hex?: string
  }>(),
  { size: 16, hex: '' },
)

const url = computed(() => weatherIconUrl(props.weatherId))
</script>

<template>
  <img
    v-if="url"
    class="shrink-0 select-none"
    :src="url"
    :width="size"
    :height="size"
    :alt="weatherId"
    decoding="async"
    draggable="false"
  />
  <span
    v-else
    class="inline-block shrink-0 rounded-full"
    :style="{ width: `${Math.round(size * 0.7)}px`, height: `${Math.round(size * 0.7)}px`, backgroundColor: hex || '#9aa4b2' }"
  />
</template>
