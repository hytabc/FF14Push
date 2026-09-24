<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { RouterLink } from 'vue-router'

import data from '@shared/schema'

import InfoTip from '@/components/InfoTip.vue'
import ItemIcon from '@/components/ItemIcon.vue'
import type { TreasureReward } from '@/game/types'
import { useGameStore } from '@/stores/game'
import { useToastStore } from '@/stores/toast'
import { useTreasureStore } from '@/stores/treasure'
import { formatNumber } from '@/utils/format'

const game = useGameStore()
const toast = useToastStore()
const treasure = useTreasureStore()

const chestPhase = ref<'idle' | 'spinning' | 'result'>('idle')
let revealTimer = 0

const config = computed(() => treasure.config)
const run = computed(() => treasure.run)
const active = computed(() => !!run.value && run.value.status !== 'ended')
const stats = computed(() => game.hero?.stats ?? null)
const boss = computed(() => treasure.bosses[0] ?? null)

const sourceRegion = computed(() => {
  const id = config.value?.sourceRegionId
  if (!id) return null
  const regions = (data.regions as unknown as { regions: Array<{ id: number; name: string; bossName: string }> }).regions
  return regions.find((r) => r.id === id) ?? null
})

const rewardRows = computed(() => {
  const weights = config.value?.rewardWeights ?? {}
  const total = Object.values(weights).reduce((sum, value) => sum + value, 0) || 1
  const labels: Record<string, string> = {
    materia: '魔晶石',
    gold: '金币',
    exp: '经验',
    potion: '秘药',
    seed: '作物种子',
  }
  return Object.entries(weights)
    .map(([kind, weight]) => ({
      kind,
      label: labels[kind] ?? kind,
      weight,
      pct: (weight / total) * 100,
    }))
    .sort((a, b) => b.weight - a.weight)
})

/** 每层：难度(层-1) 的地区 40 关底 BOSS、宝箱条目数、秘药档位、魔晶石等级。 */
const floorRows = computed(() => {
  const cfg = config.value
  if (!cfg) return []
  return Array.from({ length: cfg.floors }, (_, i) => {
    const floor = i + 1
    const range = cfg.materiaLevelByFloor[i] ?? [1, 1]
    return {
      floor,
      difficulty: floor - 1,
      entries: cfg.rewardsPerFloor.base + cfg.rewardsPerFloor.perFloor * i,
      potionTier: cfg.potionTierByFloor[i] ?? 1,
      materiaLevel: `${range[0]}-${range[1]}`,
    }
  })
})

const endedReasonText = computed(() => {
  switch (run.value?.endedReason) {
    case 'wrong_door':
      return '选错了门，本次挖宝结束（已获得的奖励全部保留）。'
    case 'completed':
      return '恭喜通关全部 5 层！已获得额外通关奖金。'
    case 'abandoned':
      return '已放弃本次挖宝。'
    case 'superseded':
      return '因开始其它活动，本次挖宝已结束。'
    default:
      return '本次挖宝已结束。'
  }
})

const canStart = computed(() => !!game.hero && game.gold >= (config.value?.entryCost ?? 0))

async function load() {
  try {
    await treasure.load()
  } catch {
    /* 错误已由 store 提示 */
  }
}

onMounted(async () => {
  if (!game.state) await game.loadState()
  await load()
})

onUnmounted(() => {
  if (revealTimer) window.clearTimeout(revealTimer)
  // 离开页面只停本地循环：副本状态留在服务端，回来可继续（开始其它活动才会结束）。
  treasure.leave()
})

async function start() {
  chestPhase.value = 'idle'
  await treasure.start()
}

async function openChest() {
  chestPhase.value = 'spinning'
  await treasure.openChest()
  if (revealTimer) window.clearTimeout(revealTimer)
  revealTimer = window.setTimeout(() => {
    chestPhase.value = 'result'
  }, 1500)
}

async function chooseDoor(index: number) {
  chestPhase.value = 'idle'
  await treasure.chooseDoor(index)
}

async function abandon() {
  chestPhase.value = 'idle'
  await treasure.abandon()
  toast.push('已放弃本次挖宝', 'info')
}

function rewardText(reward: TreasureReward): string {
  switch (reward.kind) {
    case 'gold':
      return `金币 +${formatNumber(reward.amount ?? 0)}`
    case 'bonusGold':
      return `通关奖金 +${formatNumber(reward.amount ?? 0)} 金币`
    case 'exp':
      return `经验 +${formatNumber(reward.amount ?? 0)}`
    case 'potion':
      return `${reward.name} ×${reward.count}`
    case 'materia':
      return `${reward.name} ×${reward.count}`
    case 'seed':
      return `${reward.name} ×${reward.count}`
    default:
      return reward.name ?? ''
  }
}

const logTone: Record<string, string> = {
  normal: 'text-ink-400',
  skill: 'text-sky-300',
  damage: 'text-amber-200',
  loot: 'text-emerald-300',
  danger: 'text-rose-400',
  system: 'text-ink-200',
  boss: 'text-fuchsia-300',
  crit: 'text-orange-300',
  dh: 'text-cyan-300',
  critDh: 'text-yellow-200',
}
</script>

<template>
  <div class="space-y-4">
    <!-- 规则 -->
    <section class="card p-4">
      <div class="flex flex-wrap items-center gap-3">
        <h2 class="text-lg font-semibold text-white">挖宝</h2>
        <span class="text-xs text-ink-400">
          花 <span class="font-mono text-amber-300">{{ formatNumber(config?.entryCost ?? 0) }}</span> 金币进入
          {{ config?.floors ?? 5 }} 层副本：每层击败
          <strong class="text-ink-200">难度(层-1) 的地区 40 关底 BOSS</strong>，
          随后开箱并选择两扇门中的一扇（各 {{ Math.round((config?.correctChance ?? 0.5) * 100) }}%）。
        </span>
        <InfoTip title="挖宝规则">
          <p>· 每层怪物 = 难度(层-1) 的地区 40 关底 BOSS（难度只放大怪物，不削弱玩家）。</p>
          <p>· 选对门进入下一层；选错门直接结束副本，<strong>已开箱入账的奖励全部保留</strong>。</p>
          <p>· 阵亡不结束副本，可原地重试当前层。</p>
          <p>· 击败每层怪物后 {{ ((config?.specialEventChance ?? 0.05) * 100).toFixed(0) }}% 概率触发猜大小：最多连猜
            {{ config?.maxGuesses ?? 5 }} 次，每次基于上一张牌；猜对当前宝箱奖励 +{{ ((config?.rewardIncreasePerGuess ?? 0.5) * 100).toFixed(0) }}%，
            猜错则当前宝箱奖励清空。</p>
          <p>· 通关第 5 层额外赠送 {{ formatNumber(config?.finalBonusGold ?? 0) }} 金币（不受猜大小倍率影响）。</p>
          <p class="text-ink-400">来源：shared/data/treasure.json。</p>
        </InfoTip>
        <span class="ml-auto text-xs text-ink-400">
          金币 <span class="font-mono text-amber-300">{{ formatNumber(game.gold) }}</span>
        </span>
      </div>
    </section>

    <!-- 入口 / 结束 -->
    <template v-if="!active">
      <section v-if="run" class="card p-4">
        <h3 class="text-sm font-semibold text-white">上次挖宝结果</h3>
        <p class="mt-1 text-xs text-ink-300">{{ endedReasonText }}</p>
        <p class="mt-1 text-[11px] text-ink-500">到达第 {{ run.floor }} 层。</p>
      </section>

      <section class="grid gap-3 lg:grid-cols-2">
        <div class="card p-4">
          <h3 class="flex items-center gap-1 text-sm font-semibold text-white">
            宝箱奖励概率
            <InfoTip title="奖励概率">
              <p>宝箱每次随机 {{ config?.rewardsPerFloor.base ?? 2 }} ~
                {{ (config?.rewardsPerFloor.base ?? 2) + (config?.rewardsPerFloor.perFloor ?? 1) * ((config?.floors ?? 5) - 1) }}
                条奖励，条目类别按下表权重抽取。</p>
              <p v-for="row in rewardRows" :key="row.kind" class="font-mono">
                {{ row.label }}：{{ row.pct.toFixed(1) }}%（权重 {{ row.weight }}）
              </p>
              <p class="text-ink-400">来源：shared/data/treasure.json:rewardWeights。</p>
            </InfoTip>
          </h3>
          <ul class="mt-2 space-y-1 text-xs">
            <li v-for="row in rewardRows" :key="row.kind" class="flex justify-between text-ink-300">
              <span>{{ row.label }}</span>
              <span class="font-mono text-amber-300">{{ row.pct.toFixed(1) }}%</span>
            </li>
          </ul>
          <p class="mt-2 text-[11px] text-ink-500">
            金币 / 经验为同难度关底 BOSS 产出的 {{ config?.goldMultiplier ?? 2 }} 倍，数量随层数上涨。
          </p>
        </div>

        <div class="card p-4">
          <h3 class="text-sm font-semibold text-white">逐层一览</h3>
          <div class="mt-2 overflow-hidden rounded-lg border border-ink-800">
            <table class="w-full text-[11px]">
              <thead class="bg-ink-800/60 text-ink-300">
                <tr>
                  <th class="px-2 py-1 text-left">层</th>
                  <th class="px-2 py-1 text-left">怪物难度</th>
                  <th class="px-2 py-1 text-left">宝箱条目</th>
                  <th class="px-2 py-1 text-left">秘药档位</th>
                  <th class="px-2 py-1 text-left">魔晶石等级</th>
                </tr>
              </thead>
              <tbody class="text-ink-400">
                <tr v-for="row in floorRows" :key="row.floor" class="border-t border-ink-800">
                  <td class="px-2 py-1 text-ink-200">第 {{ row.floor }} 层</td>
                  <td class="px-2 py-1">难度 {{ row.difficulty }}</td>
                  <td class="px-2 py-1">{{ row.entries }}</td>
                  <td class="px-2 py-1">{{ row.potionTier }} 级</td>
                  <td class="px-2 py-1">{{ row.materiaLevel }} 级</td>
                </tr>
              </tbody>
            </table>
          </div>
          <p v-if="sourceRegion" class="mt-2 text-[11px] text-ink-500">
            参照：{{ sourceRegion.name }} · {{ sourceRegion.bossName }}
          </p>
        </div>
      </section>

      <section class="card flex flex-wrap items-center gap-3 p-4">
        <button
          class="rounded-md bg-amber-500 px-4 py-2 text-sm font-semibold text-ink-950 transition hover:bg-amber-400 disabled:opacity-50"
          :disabled="treasure.busy || !canStart"
          @click="start"
        >
          进入挖宝（{{ formatNumber(config?.entryCost ?? 0) }} 金币）
        </button>
        <p v-if="!game.hero" class="text-xs text-rose-300">需要先招募英雄。</p>
        <p v-else-if="!canStart" class="text-xs text-rose-300">金币不足。</p>
        <p v-else class="text-xs text-ink-500">越往上越难：第 5 层 = 难度 4 的地区 40 关底 BOSS。</p>
      </section>
    </template>

    <!-- 进行中 -->
    <template v-else>
      <section class="card p-4">
        <div class="flex flex-wrap items-center gap-3">
          <div>
            <p class="text-xs text-ink-400">第 {{ run?.floor }} / {{ config?.floors }} 层</p>
            <h2 class="text-lg font-semibold text-white">
              {{ run?.status === 'fighting' ? `BOSS：${boss?.name ?? '???'}` : '本层已通关' }}
            </h2>
          </div>
          <div class="ml-auto flex items-center gap-2">
            <span class="rounded bg-ink-800 px-2 py-1 text-xs text-ink-200">
              <template v-if="run?.eventActive">猜大小中 · 倍率 ×{{ run?.multiplier }}</template>
              <template v-else-if="run?.status === 'fighting'">战斗中</template>
              <template v-else>待开箱</template>
            </span>
            <button
              class="rounded-md bg-rose-600/80 px-3 py-1.5 text-xs font-medium text-white hover:bg-rose-500"
              :disabled="treasure.busy"
              @click="abandon"
            >
              放弃挖宝
            </button>
          </div>
        </div>
      </section>

      <!-- 战斗 -->
      <div v-if="run?.status === 'fighting'" class="grid gap-4 lg:grid-cols-2">
        <section class="card p-4">
          <h3 class="text-sm font-semibold text-white">英雄</h3>
          <div class="mt-3 space-y-2">
            <div>
              <div class="mb-1 flex justify-between text-[11px] text-ink-400">
                <span>生命</span>
                <span>{{ Math.max(0, Math.round(treasure.sim?.heroHp ?? 0)) }} / {{ Math.round(stats?.maxHp ?? 0) }}</span>
              </div>
              <div class="h-2.5 overflow-hidden rounded-full bg-ink-800">
                <div class="h-full rounded-full bg-emerald-500 transition-all" :style="{ width: `${treasure.sim?.heroHpPct ?? 0}%` }" />
              </div>
            </div>
            <div>
              <div class="mb-1 flex justify-between text-[11px] text-ink-400">
                <span>魔法值</span>
                <span>{{ Math.round(treasure.sim?.heroMp ?? 0) }} / {{ Math.round(stats?.maxMp ?? 0) }}</span>
              </div>
              <div class="h-2 overflow-hidden rounded-full bg-ink-800">
                <div class="h-full rounded-full bg-sky-500 transition-all" :style="{ width: `${treasure.sim?.mpPct ?? 0}%` }" />
              </div>
            </div>
          </div>
          <p class="mt-3 text-[11px] text-ink-500">
            战力 {{ formatNumber(game.state?.power ?? 0) }} · {{ game.hero?.name }} Lv.{{ game.hero?.level }}
          </p>
          <p class="mt-1 text-[11px] text-ink-500">阵亡不会结束副本，可原地重试本层。</p>
        </section>

        <section class="card p-4">
          <h3 class="text-sm font-semibold text-white">BOSS</h3>
          <div v-if="boss" class="mt-3 rounded-lg border border-rose-500/40 bg-ink-800/50 p-3">
            <p class="truncate text-sm text-ink-100">{{ boss.name }}</p>
            <div class="mt-2 flex justify-between text-[11px] text-ink-400">
              <span>生命</span>
              <span class="font-mono">
                {{ Math.max(0, Math.round(boss.hp)).toLocaleString() }} /
                {{ Math.round(boss.maxHp).toLocaleString() }}
              </span>
            </div>
            <div class="mt-1 h-3 overflow-hidden rounded-full bg-ink-800">
              <div class="h-full rounded-full bg-rose-500 transition-all" :style="{ width: `${boss.hpPct}%` }" />
            </div>
            <p v-if="boss.skillNames.length" class="mt-2 text-[10px] text-fuchsia-300">
              技能池：{{ boss.skillNames.join('、') }}
            </p>
          </div>
          <div class="mt-3 h-40 overflow-y-auto rounded-lg border border-ink-800 bg-ink-950/60 p-3 font-mono text-[11px] leading-relaxed">
            <p v-for="entry in [...treasure.log].reverse()" :key="entry.id" :class="logTone[entry.tone]">
              {{ entry.text }}
            </p>
            <p v-if="!treasure.log.length" class="text-ink-600">尚无战斗记录</p>
          </div>
        </section>
      </div>

      <!-- 已通关：猜大小 / 开箱 / 选门 -->
      <section v-else class="card space-y-4 p-4">
        <!-- 猜大小 -->
        <div v-if="run?.eventActive" class="rounded-lg border border-amber-500/40 bg-amber-500/5 p-4">
          <div class="flex flex-wrap items-center gap-3">
            <h3 class="text-sm font-semibold text-amber-200">特殊事件 · 猜大小</h3>
            <span class="text-[11px] text-ink-400">
              当前牌面 <span class="font-mono text-lg text-white">{{ run?.card }}</span> ·
              当前倍率 ×{{ run?.multiplier }} ·
              剩余 {{ (run?.maxGuesses ?? 5) - (run?.guessesUsed ?? 0) }} 次
            </span>
            <InfoTip title="猜大小规则">
              <p>在 1-{{ config?.cardMax ?? 9 }} 中随机生成下一张牌，猜它比当前牌大或小。</p>
              <p>猜对：当前层宝箱奖励 +{{ ((config?.rewardIncreasePerGuess ?? 0.5) * 100).toFixed(0) }}%；猜错：当前层宝箱奖励清空。</p>
              <p>{{ config?.tieIsLoss ? '平局视为猜错。' : '平局不计输赢（消耗一次机会，奖励不变）。' }}</p>
              <p>最多连猜 {{ config?.maxGuesses ?? 5 }} 次，可随时停止保留当前奖励。</p>
            </InfoTip>
          </div>
          <div class="mt-3 flex flex-wrap gap-2">
            <button
              class="rounded-md bg-emerald-600 px-4 py-2 text-sm font-medium text-white hover:bg-emerald-500 disabled:opacity-50"
              :disabled="treasure.busy"
              @click="treasure.gambleGuess('high')"
            >
              猜大
            </button>
            <button
              class="rounded-md bg-sky-600 px-4 py-2 text-sm font-medium text-white hover:bg-sky-500 disabled:opacity-50"
              :disabled="treasure.busy"
              @click="treasure.gambleGuess('low')"
            >
              猜小
            </button>
            <button
              class="rounded-md bg-ink-700 px-4 py-2 text-sm text-ink-200 hover:bg-ink-600 disabled:opacity-50"
              :disabled="treasure.busy"
              @click="treasure.stopGamble()"
            >
              停止并保留奖励
            </button>
          </div>
          <p v-if="treasure.gamble" class="mt-2 text-[11px]" :class="treasure.gamble.result === 'win' ? 'text-emerald-300' : treasure.gamble.result === 'lose' ? 'text-rose-300' : 'text-ink-400'">
            上一张 {{ treasure.gamble.previousCard }} → 本次 {{ treasure.gamble.card }}：
            {{ treasure.gamble.result === 'win' ? '猜对了！' : treasure.gamble.result === 'lose' ? '猜错了，奖励清空' : '平局' }}
          </p>
        </div>

        <!-- 开箱 -->
        <div v-else-if="!run?.chestOpened" class="space-y-2">
          <h3 class="text-sm font-semibold text-white">第 {{ run?.floor }} 层宝箱</h3>
          <p class="text-[11px] text-ink-400">点击开启宝箱（老虎机罗盘），奖励立即入账。</p>
          <button
            class="rounded-md bg-amber-500 px-4 py-2 text-sm font-semibold text-ink-950 hover:bg-amber-400 disabled:opacity-50"
            :disabled="treasure.busy"
            @click="openChest"
          >
            开启宝箱
          </button>
        </div>

        <!-- 开箱结果 + 选门 -->
        <template v-else>
          <div v-if="chestPhase === 'spinning'" class="flex flex-col items-center gap-3 py-8">
            <div class="text-5xl animate-spin">🎡</div>
            <p class="text-xs text-ink-400">老虎机罗盘转动中…</p>
          </div>

          <div v-else class="space-y-3">
            <h3 class="text-sm font-semibold text-white">
              第 {{ treasure.chest?.floor }} 层奖励
              <span class="ml-1 text-[11px] text-ink-400">倍率 ×{{ treasure.chest?.multiplier }}</span>
            </h3>
            <div v-if="treasure.chest?.rewards.length" class="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
              <div
                v-for="(reward, index) in treasure.chest.rewards"
                :key="index"
                class="flex animate-rise items-center gap-2 rounded-lg border border-ink-700 bg-ink-800/40 p-2 text-xs"
                :style="{ animationDelay: `${index * 80}ms` }"
              >
                <ItemIcon v-if="reward.itemId" :base-id="reward.itemId" :size="28" variant="plain" />
                <span v-else class="text-lg">{{ reward.kind === 'exp' ? '✨' : '💰' }}</span>
                <span class="min-w-0 flex-1 truncate text-ink-100">{{ rewardText(reward) }}</span>
              </div>
            </div>
            <p v-else class="text-xs text-rose-300">本次宝箱没有产出奖励。</p>

            <p v-if="treasure.chest?.expGained" class="text-xs text-emerald-300">
              经验 +{{ formatNumber(treasure.chest.expGained) }}
              <span v-if="treasure.chest.level?.levelsGained" class="ml-1 text-amber-300">
                升级 ×{{ treasure.chest.level.levelsGained }}
              </span>
            </p>
          </div>

          <!-- 选门 / 完成 -->
          <div v-if="treasure.chest?.completed" class="rounded-lg border border-emerald-500/40 bg-emerald-500/5 p-3">
            <p class="text-sm font-semibold text-emerald-200">通关全部 {{ config?.floors }} 层！</p>
            <p class="mt-1 text-[11px] text-ink-300">
              额外获得 {{ formatNumber(treasure.chest.bonusGold) }} 金币通关奖金。
            </p>
            <RouterLink
              to="/materia"
              class="mt-2 inline-block rounded-md bg-ink-700 px-3 py-1.5 text-xs text-ink-100 hover:bg-ink-600"
            >
              去镶嵌魔晶石 →
            </RouterLink>
          </div>
          <div v-else class="space-y-2">
            <h3 class="text-sm font-semibold text-white">选择进入下一层的门</h3>
            <p class="text-[11px] text-ink-400">
              每扇门各有 {{ Math.round((config?.correctChance ?? 0.5) * 100) }}% 概率正确；选错会直接结束副本，但不影响已获得的奖励。
            </p>
            <div class="flex flex-wrap gap-3">
              <button
                v-for="index in config?.doors ?? 2"
                :key="index"
                class="rounded-lg border border-ink-600 bg-ink-800/60 px-6 py-4 text-sm text-ink-100 transition hover:border-amber-400 hover:bg-ink-700 disabled:opacity-50"
                :disabled="treasure.busy"
                @click="chooseDoor(index - 1)"
              >
                🚪 门 {{ index }}
              </button>
            </div>
          </div>
        </template>
      </section>
    </template>

    <!-- 组队奖励提示：魔晶石 / 种子去向 -->
    <section class="card p-4 text-[11px] text-ink-400">
      挖宝产出的魔晶石可在
      <RouterLink to="/materia" class="text-amber-300 hover:underline">魔晶石页</RouterLink>
      镶嵌，作物种子可在
      <RouterLink to="/farm" class="text-amber-300 hover:underline">种田页</RouterLink>
      种植。
    </section>
  </div>
</template>
