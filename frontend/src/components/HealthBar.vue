<script setup lang="ts">
import { computed } from 'vue'

/**
 * 通用血条：血量填充 + 护盾浅绿覆盖层。
 *
 * 全游戏所有血条（英雄 / 怪物 / BOSS）统一使用本组件，护盾一律以浅绿色覆盖在血条上，
 * 宽度 = 护盾 / 最大生命（护盾上限由 combat.json:equipEffects.shield 约束，最多 30%）。
 */
const props = withDefaults(
  defineProps<{
    value: number
    max: number
    shield?: number
    /** 轨道高度（Tailwind 类，如 'h-2.5'）。 */
    height?: string
    /** 血量填充色（Tailwind 类，如 'bg-emerald-500'）。 */
    fillClass?: string
    /** 轨道底色（Tailwind 类）。 */
    trackClass?: string
    animated?: boolean
  }>(),
  {
    shield: 0,
    height: 'h-2.5',
    fillClass: 'bg-emerald-500',
    trackClass: 'bg-ink-800',
    animated: true,
  },
)

const clampPct = (n: number) => Math.max(0, Math.min(100, n))
const hpPct = computed(() => (props.max > 0 ? clampPct((props.value / props.max) * 100) : 0))
const shieldPct = computed(() => (props.max > 0 ? clampPct(((props.shield ?? 0) / props.max) * 100) : 0))
</script>

<template>
  <div class="relative overflow-hidden rounded-full" :class="[height, trackClass]">
    <div
      class="h-full rounded-full"
      :class="[fillClass, animated && 'transition-all']"
      :style="{ width: `${hpPct}%` }"
    />
    <div
      v-if="shieldPct > 0"
      class="pointer-events-none absolute inset-y-0 left-0 rounded-full bg-emerald-300/80 ring-1 ring-emerald-100/70"
      :class="animated && 'transition-all'"
      :style="{ width: `${shieldPct}%` }"
      :title="`护盾 ${Math.round(props.shield ?? 0)}`"
    />
    <slot />
  </div>
</template>
