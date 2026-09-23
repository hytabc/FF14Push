<script setup lang="ts">
import { computed } from 'vue'

import { jobName } from '@/utils/format'
import { jobIconUrl } from '@/utils/jobs'

const props = withDefaults(
  defineProps<{
    /** 职业 id（shared/data/jobs.json 的 job.id）；无对应素材时不渲染。 */
    jobId?: string | null
    /** 渲染边长（px）。 */
    size?: number
  }>(),
  { jobId: null, size: 20 },
)

const url = computed(() => jobIconUrl(props.jobId))
const name = computed(() => (props.jobId ? jobName(props.jobId) : ''))
</script>

<template>
  <img
    v-if="url"
    class="shrink-0 select-none rounded-[3px]"
    :src="url"
    :width="size"
    :height="size"
    :alt="name"
    :title="name"
    decoding="async"
    draggable="false"
  />
</template>
