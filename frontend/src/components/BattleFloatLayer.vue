<script setup lang="ts">
import { useGameStore } from '@/stores/game'

/**
 * 伤害浮动数字层。
 *
 * 刻意让本组件**自己**从 store 读 `floating`：飘字每出现一次都会让读取它的组件重渲染，
 * 若由 `MainView` 读取，整个战斗页（160 条日志 + 技能条 + 属性面板）都会被带着重渲染。
 * 拆出来后高频更新只影响这一层。
 */
const game = useGameStore()

/** 飘字色调 → 颜色（与战斗日志的 tone 语义一致）。 */
const FLOAT_TONE: Record<string, string> = {
  hero: 'text-emerald-300',
  crit: 'text-orange-300',
  dh: 'text-cyan-300',
  critDh: 'text-yellow-200',
  miss: 'text-ink-400',
}

function floatTone(tone: string): string {
  return FLOAT_TONE[tone] ?? 'text-rose-300'
}
</script>

<template>
  <transition-group name="float">
    <span
      v-for="f in game.floating"
      :key="f.id"
      class="animate-float font-mono text-sm font-bold"
      :class="floatTone(f.tone)"
    >
      {{ f.text }}
    </span>
  </transition-group>
</template>

<style scoped>
.float-enter-active {
  transition: all 0.15s ease;
}
.float-leave-active {
  transition: opacity 0.5s ease;
}
.float-enter-from {
  opacity: 0;
}
.float-leave-to {
  opacity: 0;
}
</style>
