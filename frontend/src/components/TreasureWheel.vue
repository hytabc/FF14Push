<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'

import ItemIcon from '@/components/ItemIcon.vue'
import { buildWheelSectors, nextRotation, type WheelSector } from '@/game/core/wheel'
import type { TreasureReward } from '@/game/types'

const props = withDefaults(
  defineProps<{
    /** 本层真实奖励（服务端已结算，转盘只负责展示落点）。 */
    rewards: TreasureReward[]
    /** 干扰项候选池（本层可产出的物品）；为空时用奖励本身占位。 */
    pool?: TreasureReward[]
    /** 所在层数（中心轴展示）。 */
    floor?: number
    /** 单次旋转时长（毫秒）。 */
    spinMs?: number
  }>(),
  { pool: () => [], floor: 0, spinMs: 2200 },
)
const emit = defineEmits<{ done: [] }>()

const REDUCED_MOTION =
  typeof window !== 'undefined' && !!window.matchMedia?.('(prefers-reduced-motion: reduce)').matches

/** 扇区底色按奖励类别区分（奖励不下发品阶，只能按 kind 取色）。 */
const SECTOR_COLORS: Record<string, string> = {
  gold: '#a16207',
  bonusGold: '#a16207',
  exp: '#0e7490',
  potion: '#15803d',
  materia: '#6d28d9',
  seed: '#7c2d12',
}

const sectors = ref<WheelSector[]>([])
const rotation = ref(0)
const spun = ref(0)
let cancelled = false

const step = computed(() => 360 / Math.max(1, sectors.value.length))

const wheelBackground = computed(() => {
  if (!sectors.value.length) return 'transparent'
  const stops = sectors.value
    .map((sector, index) => {
      const color = SECTOR_COLORS[sector.reward.kind] ?? '#334155'
      return `${color} ${index * step.value}deg ${(index + 1) * step.value}deg`
    })
    .join(', ')
  return `conic-gradient(from 0deg, ${stops})`
})

const spokesBackground = computed(
  () =>
    `repeating-conic-gradient(from 0deg, rgba(255,255,255,.22) 0deg 1deg, transparent 1deg ${step.value}deg)`,
)

function labelOf(reward: TreasureReward): string {
  if (reward.kind === 'gold' || reward.kind === 'bonusGold') return '金币'
  if (reward.kind === 'exp') return '经验'
  return reward.name ?? ''
}

function emojiOf(reward: TreasureReward): string {
  return reward.kind === 'exp' ? '✨' : '💰'
}

function wait(ms: number): Promise<void> {
  return new Promise((resolve) => {
    window.setTimeout(resolve, ms)
  })
}

onMounted(async () => {
  sectors.value = buildWheelSectors(props.rewards, props.pool)
  const targets = sectors.value.filter((sector) => sector.isReward)
  if (!targets.length) {
    emit('done')
    return
  }
  if (REDUCED_MOTION) {
    // 尊重「减少动态效果」：直接落到终态，不播放旋转。
    spun.value = targets.length
    emit('done')
    return
  }
  for (let index = 0; index < targets.length; index += 1) {
    if (cancelled) return
    // 落点抖动控制在该扇区中心附近，避免停到扇区边缘。
    const jitter = (Math.random() - 0.5) * step.value * 0.5
    rotation.value = nextRotation(rotation.value, targets[index], 2, jitter)
    await wait(props.spinMs)
    if (cancelled) return
    spun.value = index + 1
  }
  emit('done')
})

onUnmounted(() => {
  cancelled = true
})
</script>

<template>
  <div class="flex flex-col items-center gap-3 py-4">
    <div class="relative aspect-square w-64 max-w-full">
      <!-- 指针 -->
      <div class="absolute left-1/2 top-0 z-20 -translate-x-1/2 -translate-y-1">
        <div
          class="h-0 w-0 border-x-[10px] border-t-[16px] border-x-transparent border-t-amber-300 drop-shadow"
        />
      </div>

      <!-- 盘面 -->
      <div
        class="absolute inset-0 rounded-full border-4 border-ink-600 shadow-xl"
        :style="{
          background: wheelBackground,
          transform: `rotate(${rotation}deg)`,
          transitionProperty: 'transform',
          transitionTimingFunction: 'cubic-bezier(0.12, 0.72, 0.08, 1)',
          transitionDuration: REDUCED_MOTION ? '0ms' : `${spinMs}ms`,
        }"
      >
        <div class="absolute inset-0 rounded-full" :style="{ background: spokesBackground }" />
        <div
          v-for="(sector, index) in sectors"
          :key="index"
          class="absolute inset-0 flex justify-center"
          :style="{ transform: `rotate(${sector.centerAngle}deg)` }"
        >
          <div class="flex w-14 flex-col items-center gap-0.5 pt-3 text-center">
            <ItemIcon
              v-if="sector.reward.itemId"
              :base-id="sector.reward.itemId"
              :size="22"
              variant="plain"
            />
            <span v-else class="text-lg leading-none">{{ emojiOf(sector.reward) }}</span>
            <span class="w-14 truncate text-[9px] text-white/90">{{ labelOf(sector.reward) }}</span>
          </div>
        </div>
      </div>

      <!-- 中心轴 -->
      <div
        class="pointer-events-none absolute left-1/2 top-1/2 z-10 flex h-14 w-14 -translate-x-1/2 -translate-y-1/2 items-center justify-center rounded-full border-2 border-amber-300/60 bg-ink-900/90 text-[10px] font-medium text-amber-200"
      >
        第 {{ floor }} 层
      </div>
    </div>
    <p class="text-xs text-ink-400">转盘转动中… {{ spun }} / {{ rewards.length }}</p>
  </div>
</template>
