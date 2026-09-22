<script setup lang="ts">
import { computed } from 'vue'

import Modal from '@/components/Modal.vue'
import { modes, roles, type CoopPartyMember } from '@/game/multiplayer'
import { formatDuration, formatNumber, jobName } from '@/utils/format'

const props = defineProps<{
  open: boolean
  dungeonName?: string
  clearMs?: number
  mode?: string
  hadClone?: boolean
  createdAt?: number
  party: CoopPartyMember[]
}>()

const emit = defineEmits<{ close: [] }>()

const ROLE_COLOR: Record<string, string> = {
  tank: 'bg-sky-500',
  healer: 'bg-emerald-500',
  dps: 'bg-rose-500',
}
const SHARE_COLORS = [
  'bg-amber-400',
  'bg-sky-400',
  'bg-emerald-400',
  'bg-fuchsia-400',
  'bg-rose-400',
  'bg-indigo-400',
  'bg-teal-400',
  'bg-orange-400',
]

const party = computed(() => [...props.party].sort((a, b) => a.slot - b.slot))
const totalDamage = computed(() => party.value.reduce((sum, m) => sum + m.damage, 0))

const METRICS = [
  { key: 'damage' as const, label: '伤害输出', color: 'bg-amber-500' },
  { key: 'damageTaken' as const, label: '承受伤害', color: 'bg-rose-500' },
  { key: 'healing' as const, label: '治疗量', color: 'bg-emerald-500' },
]

function share(member: CoopPartyMember): number {
  return totalDamage.value > 0 ? (member.damage / totalDamage.value) * 100 : 0
}

function maxOf(key: 'damage' | 'damageTaken' | 'healing'): number {
  return Math.max(1, ...party.value.map((m) => Number(m[key]) || 0))
}

function barPct(member: CoopPartyMember, key: 'damage' | 'damageTaken' | 'healing'): number {
  return Math.round(((Number(member[key]) || 0) / maxOf(key)) * 100)
}

function roleColor(member: CoopPartyMember): string {
  return ROLE_COLOR[member.role] ?? 'bg-ink-500'
}

const dateText = computed(() =>
  props.createdAt ? new Date(props.createdAt * 1000).toLocaleDateString() : '',
)
</script>

<template>
  <Modal :open="open" title="通关阵容 · 输出详情" max-width="max-w-3xl" @close="emit('close')">
    <div class="space-y-4 text-sm">
      <!-- 通关概要 -->
      <div class="rounded-lg border border-ink-700 bg-ink-800/70 p-3 text-xs">
        <div class="flex flex-wrap items-center gap-2">
          <span class="text-sm font-medium text-ink-100">{{ dungeonName || '远征副本' }}</span>
          <span class="rounded bg-ink-700 px-1.5 py-0.5 text-[10px] text-ink-300">
            {{ modes[mode as keyof typeof modes] ?? mode }}
          </span>
          <span
            v-if="hadClone"
            class="rounded bg-fuchsia-500/20 px-1.5 py-0.5 text-[10px] text-fuchsia-200"
          >含克隆</span>
          <span class="ml-auto font-mono text-amber-300">通关 {{ formatDuration(clearMs ?? 0) }}</span>
        </div>
        <p v-if="dateText" class="mt-1 text-ink-500">{{ dateText }}</p>
      </div>

      <!-- 伤害占比堆叠条 -->
      <div>
        <p class="mb-1 text-xs font-medium text-ink-400">伤害占比</p>
        <div class="flex h-4 w-full overflow-hidden rounded-full bg-ink-800">
          <div
            v-for="(m, i) in party"
            :key="m.slot"
            class="h-full transition-all"
            :class="SHARE_COLORS[i % SHARE_COLORS.length]"
            :style="{ width: `${share(m)}%` }"
            :title="`${m.name} ${share(m).toFixed(1)}%`"
          />
        </div>
        <div class="mt-1.5 flex flex-wrap gap-x-3 gap-y-1 text-[10px] text-ink-400">
          <span v-for="(m, i) in party" :key="m.slot" class="inline-flex items-center gap-1">
            <span class="inline-block h-2 w-2 rounded-full" :class="SHARE_COLORS[i % SHARE_COLORS.length]" />
            {{ m.name }}
            <span class="font-mono text-ink-500">{{ share(m).toFixed(1) }}%</span>
          </span>
        </div>
      </div>

      <!-- 分指标条形图 -->
      <div v-for="metric in METRICS" :key="metric.key" class="space-y-1.5">
        <p class="text-xs font-medium text-ink-400">{{ metric.label }}</p>
        <div v-for="m in party" :key="m.slot" class="flex items-center gap-2">
          <div class="w-28 shrink-0 truncate text-[11px] text-ink-200">
            <span class="mr-1">{{ m.name }}</span>
            <span class="text-ink-500">{{ jobName(m.jobId) }}</span>
          </div>
          <div class="h-2.5 flex-1 overflow-hidden rounded-full bg-ink-800">
            <div
              class="h-full rounded-full transition-all"
              :class="metric.color"
              :style="{ width: `${barPct(m, metric.key)}%` }"
            />
          </div>
          <span class="w-16 shrink-0 text-right font-mono text-[11px] text-ink-300">
            {{ formatNumber(Number(m[metric.key]) || 0) }}
          </span>
        </div>
      </div>

      <!-- 逐角色明细 -->
      <div>
        <p class="mb-1 text-xs font-medium text-ink-400">角色明细</p>
        <div class="space-y-1">
          <div
            v-for="m in party"
            :key="m.slot"
            class="flex flex-wrap items-center gap-x-3 gap-y-1 rounded-lg bg-ink-800/60 px-3 py-1.5 text-[11px]"
          >
            <span class="font-medium text-ink-100">{{ m.name }}</span>
            <span class="rounded px-1.5 py-0.5 text-[10px] text-ink-950" :class="roleColor(m)">
              {{ roles[m.role] }}
            </span>
            <span class="text-ink-400">{{ jobName(m.jobId) }} · Lv.{{ m.level }}</span>
            <span v-if="m.account" class="text-ink-500">@{{ m.account }}</span>
            <span v-if="m.clone" class="rounded bg-fuchsia-500/20 px-1.5 py-0.5 text-[10px] text-fuchsia-200">克隆</span>
            <span class="ml-auto flex gap-3 text-ink-400">
              <span>死亡 <b class="font-mono text-ink-200">{{ m.deaths }}</b></span>
              <span>最低血量 <b class="font-mono text-ink-200">{{ Math.round((m.minHpRatio ?? 0) * 100) }}%</b></span>
              <span>危险时长 <b class="font-mono text-ink-200">{{ formatDuration(m.dangerMs ?? 0) }}</b></span>
            </span>
          </div>
        </div>
      </div>

      <p class="text-[11px] text-ink-500">数据来自服务端权威战斗模拟，客户端无法伪造。</p>
    </div>

    <template #footer>
      <button class="rounded-md bg-ink-700 px-3 py-2 text-sm hover:bg-ink-600" @click="emit('close')">
        关闭
      </button>
    </template>
  </Modal>
</template>
