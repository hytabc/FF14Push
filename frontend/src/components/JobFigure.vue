<script setup lang="ts">
import { computed } from 'vue'

import { jobName } from '@/utils/format'
import { JOB_FIGURE_RATIO, jobFigureUrl } from '@/utils/jobs'

const props = withDefaults(
  defineProps<{
    /** 职业 id（shared/data/jobs.json 的 job.id）；无对应素材时不渲染。 */
    jobId?: string | null
    /** 渲染宽度（px），高度按立绘比例等比。 */
    size?: number
  }>(),
  { jobId: null, size: 52 },
)

const url = computed(() => jobFigureUrl(props.jobId))
const name = computed(() => (props.jobId ? jobName(props.jobId) : ''))
const height = computed(() => Math.round(props.size * JOB_FIGURE_RATIO))
</script>

<template>
  <img
    v-if="url"
    class="pixel-icon shrink-0 select-none"
    :src="url"
    :width="size"
    :height="height"
    :alt="name"
    :title="name"
    decoding="async"
    draggable="false"
  />
</template>
