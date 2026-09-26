<script setup lang="ts">
import { computed } from 'vue'

import type { PalaceMap } from '@/game/types'

const props = defineProps<{
  map: PalaceMap | null
  currentNode: string | null
  availableNodes: string[]
  /** 已走过的节点 id（用于高亮行进路线）。 */
  visited?: string[]
}>()

const emit = defineEmits<{ select: [nodeId: string] }>()

/** 每行最多 3 个节点，按 3 列居中排布；行距与列宽固定，便于 SVG 连线。 */
const MAX_COLS = 3
const COL_W = 84
const ROW_H = 74

const NODE_ICON: Record<string, string> = {
  battle: '⚔',
  elite: '☠',
  event: '❓',
  shop: '🛒',
  chest: '🎁',
  rest: '🔥',
  boss: '👑',
}

const NODE_LABEL: Record<string, string> = {
  battle: '战斗',
  elite: '精英',
  event: '事件',
  shop: '商店',
  chest: '宝箱',
  rest: '休整',
  boss: '层主',
}

interface Positioned {
  id: string
  type: string
  x: number
  y: number
  step: number
  available: boolean
  current: boolean
  visited: boolean
}

const positioned = computed<Positioned[]>(() => {
  const map = props.map
  if (!map) return []
  const out: Positioned[] = []
  const steps = map.rows.length
  map.rows.forEach((row, rowIndex) => {
    const count = row.nodes.length
    row.nodes.forEach((node, i) => {
      const col = (MAX_COLS - count) / 2 + i
      out.push({
        id: node.id,
        type: node.type,
        x: col * COL_W + COL_W / 2,
        y: (steps - 1 - rowIndex) * ROW_H + ROW_H / 2,
        step: row.step,
        available: props.availableNodes.includes(node.id),
        current: props.currentNode === node.id,
        visited: (props.visited ?? []).includes(node.id),
      })
    })
  })
  return out
})

const byId = computed(() => Object.fromEntries(positioned.value.map((n) => [n.id, n])))

const width = computed(() => MAX_COLS * COL_W)
const height = computed(() => (props.map?.rows.length ?? 0) * ROW_H)

const lines = computed(() => {
  const map = props.map
  if (!map) return []
  const nodes = byId.value
  const reached = new Set<string>([props.currentNode ?? '', ...(props.visited ?? [])])
  return map.edges
    .filter((e) => nodes[e.from] && nodes[e.to])
    .map((e) => {
      const a = nodes[e.from]
      const b = nodes[e.to]
      const active = reached.has(e.from) && (e.from === props.currentNode || props.availableNodes.includes(e.to))
      return { x1: a.x, y1: a.y, x2: b.x, y2: b.y, active }
    })
})
</script>

<template>
  <div class="overflow-x-auto">
    <div class="relative mx-auto" :style="{ width: `${width}px`, height: `${height}px` }">
      <svg class="absolute inset-0" :width="width" :height="height">
        <line
          v-for="(line, i) in lines"
          :key="i"
          :x1="line.x1"
          :y1="line.y1"
          :x2="line.x2"
          :y2="line.y2"
          :stroke="line.active ? 'rgb(251 191 36)' : 'rgb(71 85 105)'"
          :stroke-width="line.active ? 2.5 : 1.5"
          stroke-linecap="round"
        />
      </svg>
      <button
        v-for="node in positioned"
        :key="node.id"
        type="button"
        class="absolute flex flex-col items-center justify-center rounded-xl border text-[10px] leading-none transition"
        :class="[
          node.available
            ? 'border-amber-400 bg-amber-500/20 text-amber-100 hover:bg-amber-500/30 cursor-pointer'
            : node.current
              ? 'border-emerald-400 bg-emerald-500/20 text-emerald-100'
              : node.visited
                ? 'border-slate-600 bg-slate-800/70 text-slate-400'
                : 'border-slate-700 bg-slate-900/60 text-slate-500',
        ]"
        :style="{
          left: `${node.x - 30}px`,
          top: `${node.y - 26}px`,
          width: '60px',
          height: '52px',
        }"
        :disabled="!node.available"
        @click="emit('select', node.id)"
      >
        <span class="text-base">{{ NODE_ICON[node.type] ?? '•' }}</span>
        <span class="mt-0.5">{{ NODE_LABEL[node.type] ?? node.type }}</span>
      </button>
    </div>
  </div>
</template>
