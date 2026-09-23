<script setup lang="ts">
import { computed, nextTick, onMounted, ref } from 'vue'

import data from '@shared/schema'
import ItemIcon from '@/components/ItemIcon.vue'
import type { Category, Item, RarityId } from '@/game/types'
import { rarityHex } from '@/utils/format'

const props = withDefaults(
  defineProps<{
    /** 中奖物品（转盘最终停在它上面）。 */
    item: Item
    /** 箱子大类：用于生成同类的诱饵底材。 */
    category: Category
    /** 箱子档位：诱饵品阶按该档位的爆率加权。 */
    tier?: 'normal' | 'advanced'
    /** 滚动时长（毫秒）。 */
    duration?: number
    /** 起步延迟（毫秒），十连时错峰停下。 */
    delay?: number
    /** 单个格子的宽度（px）。 */
    slotWidth?: number
    /** 紧凑模式：更小的图标与高度（十连用）。 */
    compact?: boolean
  }>(),
  { tier: 'normal', duration: 2600, delay: 0, slotWidth: 64, compact: false },
)

/** 转盘格数（尾部留几格作为减速缓冲）。 */
const SLOT_COUNT = 30
const TARGET_INDEX = SLOT_COUNT - 4

interface ReelSlot {
  baseId: string
  rarity: RarityId
}

const rarities = data.rarities.order
const pool = computed(() => data.baseItems.filter((b) => b.category === props.category))

const container = ref<HTMLElement | null>(null)
const slots = ref<ReelSlot[]>([])
const target = ref(0)
const ready = ref(false)

const height = computed(() => (props.compact ? 52 : 84))
const iconSize = computed(() => (props.compact ? 28 : 40))
const iconVariant = computed(() => (props.compact ? 'lite' : 'full') as 'lite' | 'full')

const stripStyle = computed(() => ({
  // 动画终值通过 CSS 变量注入，@keyframes 只负责 translateX
  '--reel-end': `${target.value}px`,
  animationDuration: `${props.duration}ms`,
  animationDelay: `${props.delay}ms`,
}))

function pickRarity(roll: number): RarityId {
  const weights = rarities.map((r) => data.rarities.byId[r].boxChance[props.tier] ?? 0)
  const total = weights.reduce((sum, w) => sum + w, 0) || 1
  let cursor = roll * total
  for (let i = 0; i < rarities.length; i += 1) {
    cursor -= weights[i]
    if (cursor <= 0) return rarities[i]
  }
  return rarities[0]
}

function buildSlots() {
  const candidates = pool.value
  const list: ReelSlot[] = []
  for (let i = 0; i < SLOT_COUNT; i += 1) {
    if (i === TARGET_INDEX) {
      list.push({ baseId: props.item.baseId, rarity: props.item.rarity })
      continue
    }
    const decoy = candidates.length
      ? candidates[Math.floor(Math.random() * candidates.length)]
      : null
    list.push({ baseId: decoy?.id ?? props.item.baseId, rarity: pickRarity(Math.random()) })
  }
  slots.value = list
}

async function spin() {
  buildSlots()
  // 先渲染条带（未定位），量到容器宽度后再设终值，动画随 v-if 挂载自然播放一次
  await nextTick()
  const width = container.value?.clientWidth ?? 320
  const slotW = props.slotWidth
  const jitter = (Math.random() - 0.5) * slotW * 0.6
  target.value = -(TARGET_INDEX * slotW + slotW / 2 - width / 2) + jitter
  ready.value = true
}

onMounted(() => {
  void spin()
})
</script>

<template>
  <div ref="container" class="reel" :style="{ height: `${height}px` }">
    <div
      v-if="ready"
      class="reel-strip"
      :style="stripStyle"
    >
      <div
        v-for="(slot, index) in slots"
        :key="index"
        class="reel-slot"
        :style="{ width: `${slotWidth}px`, borderColor: `${rarityHex(slot.rarity)}55` }"
      >
        <ItemIcon :base-id="slot.baseId" :rarity="slot.rarity" :size="iconSize" :variant="iconVariant" />
      </div>
    </div>
    <div class="reel-marker" aria-hidden="true" />
  </div>
</template>

<style scoped>
.reel {
  position: relative;
  width: 100%;
  overflow: hidden;
  border-radius: 0.5rem;
  border: 1px solid var(--color-ink-700);
  background: color-mix(in srgb, var(--color-ink-950) 72%, transparent);
}

.reel-strip {
  display: flex;
  height: 100%;
  will-change: transform;
  animation-name: reel-spin;
  animation-timing-function: cubic-bezier(0.12, 0.72, 0.08, 1);
  animation-fill-mode: both;
}

.reel-slot {
  display: flex;
  height: 100%;
  flex: 0 0 auto;
  align-items: center;
  justify-content: center;
  border-right-width: 1px;
  border-right-style: solid;
  background: rgb(255 255 255 / 0.02);
}

.reel-marker {
  position: absolute;
  top: 0;
  bottom: 0;
  left: 50%;
  width: 2px;
  transform: translateX(-50%);
  background: linear-gradient(
    to bottom,
    color-mix(in srgb, var(--color-rarity-legendary) 0%, transparent),
    var(--color-rarity-legendary),
    color-mix(in srgb, var(--color-rarity-legendary) 0%, transparent)
  );
  box-shadow: 0 0 6px var(--color-rarity-legendary);
  pointer-events: none;
}

@keyframes reel-spin {
  from {
    transform: translateX(0);
  }
  to {
    transform: translateX(var(--reel-end, 0px));
  }
}

@media (prefers-reduced-motion: reduce) {
  .reel-strip {
    animation: none;
    transform: translateX(var(--reel-end, 0px));
  }
}
</style>
