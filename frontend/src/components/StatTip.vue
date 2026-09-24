<script setup lang="ts">
import type { Explain } from '@/game/explanations'

import InfoTip from './InfoTip.vue'

defineProps<{ explain: Explain }>()
</script>

<template>
  <InfoTip :title="explain.title">
    <p v-if="explain.usage" class="break-words">
      <span class="text-amber-300">作用：</span><span class="text-ink-200">{{ explain.usage }}</span>
    </p>
    <p v-for="(line, i) in explain.lines" :key="i" class="break-words font-mono">{{ line }}</p>
  </InfoTip>
</template>
