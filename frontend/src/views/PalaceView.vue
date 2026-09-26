<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'

import HealthBar from '@/components/HealthBar.vue'
import InfoTip from '@/components/InfoTip.vue'
import PalacePathMap from '@/components/PalacePathMap.vue'
import type { Item, PalaceBuff, PalaceMap, PalaceRewardOption } from '@/game/types'
import { usePalaceStore } from '@/stores/palace'
import { jobName, rarityClass, rarityName } from '@/utils/format'

const palace = usePalaceStore()

type Tab = 'overview' | 'path' | 'gear' | 'growth' | 'exchange'
const tab = ref<Tab>('overview')
const showAbandon = ref(false)

const run = computed(() => palace.run)
const profile = computed(() => palace.profile)
const context = computed(() => palace.context)
const stats = computed(() => palace.stats)

const phase = computed<'entry' | 'choose_hero' | 'choose_weapon' | 'run' | 'ended'>(() => {
  const r = run.value
  if (!r) return 'entry'
  if (r.status === 'choosing_hero') return 'choose_hero'
  if (r.status === 'choosing_weapon') return 'choose_weapon'
  if (r.status === 'running') return 'run'
  return 'ended'
})

const inBattle = computed(
  () => palace.inBattle && context.value !== null && ['battle', 'elite', 'boss'].includes(context.value.type),
)
const enemy = computed(() => palace.enemies[0] ?? null)

/** 已走过的节点（步数小于当前所在节点步数）。 */
const visited = computed(() => {
  const r = run.value
  if (!r || !r.map) return [] as string[]
  const currentStep = nodeStep(r.map, r.currentNode)
  const out: string[] = []
  for (const row of r.map.rows) {
    if (currentStep !== null && row.step < currentStep) out.push(...row.nodes.map((n) => n.id))
  }
  return out
})

function nodeStep(map: PalaceMap | null, nodeId: string | null): number | null {
  if (!map || !nodeId) return null
  for (const row of map.rows) {
    if (row.nodes.some((n) => n.id === nodeId)) return row.step
  }
  return null
}

const equippedItems = computed<Array<{ slot: string; item: Item | undefined }>>(() => {
  const r = run.value
  if (!r) return []
  return Object.entries(r.equipped).map(([slot, idx]) => ({ slot, item: r.items[idx] }))
})

const TAB_LABELS: Record<Tab, string> = {
  overview: '概览',
  path: '路径',
  gear: '装备',
  growth: '成长',
  exchange: '兑换',
}

function switchTab(next: Tab) {
  tab.value = next
  if (next === 'growth' && !palace.growth) void palace.loadGrowth()
  if (next === 'exchange' && !palace.exchange) void palace.loadExchange()
}

function buffText(buff: PalaceBuff): string {
  return buff.desc || `${buff.name}`
}

function rewardTitle(option: PalaceRewardOption): string {
  if (option.kind === 'buff') return '祝福'
  if (option.kind === 'both') return '装备 + 祝福'
  return '装备'
}

async function onAbandon() {
  await palace.abandon()
  showAbandon.value = false
}

onMounted(async () => {
  await palace.load()
  if (run.value?.status === 'running') tab.value = 'path'
})
onUnmounted(() => palace.leave())
</script>

<template>
  <div class="space-y-4">
    <!-- 顶栏 -->
    <section class="card p-4">
      <div class="flex flex-wrap items-center gap-2">
        <h1 class="text-lg font-semibold text-white">💀 死者宫殿</h1>
        <InfoTip title="玩法说明">
          <p class="text-xs leading-relaxed text-ink-300">
            与账号战力完全隔绝的迷宫：副本内英雄从 1 级起步，装备、金币、祝福都只在本次探索内生效，
            秘药与食物在这里没有任何作用。每层最多走 10 步，第 10 步固定为本层层主；击败层主可继续深入并获得成长点与代币。
          </p>
        </InfoTip>
        <div class="ml-auto flex flex-wrap items-center gap-2 text-xs">
          <span class="rounded bg-ink-800 px-2 py-1 text-amber-200">成长点 {{ profile?.growthPoints ?? 0 }}</span>
          <span class="rounded bg-ink-800 px-2 py-1 text-orange-300">烈火纹章 {{ profile?.flameCrest ?? 0 }}</span>
          <span class="rounded bg-ink-800 px-2 py-1 text-violet-300">玻璃南瓜 {{ profile?.glassPumpkin ?? 0 }}</span>
          <span class="rounded bg-ink-800 px-2 py-1 text-ink-300">通关 {{ profile?.floor10Clears ?? 0 }} 次</span>
        </div>
      </div>
    </section>

    <!-- 入口 -->
    <section v-if="phase === 'entry' || phase === 'ended'" class="card space-y-3 p-4">
      <div v-if="phase === 'ended'" class="rounded-lg border border-rose-500/40 bg-rose-500/10 p-3 text-sm text-rose-100">
        <template v-if="run?.endedReason === 'completed'">你征服了死者宫殿第 10 层！</template>
        <template v-else-if="run?.endedReason === 'death'">英雄倒在了第 {{ run?.floor }} 层。</template>
        <template v-else>本次探索已结束。</template>
      </div>
      <p class="text-sm text-ink-300">
        进入后需在随机三名英雄与随机三件武器中各选其一，随后在每层的岔路中选择前进方向。
      </p>
      <button
        class="rounded-lg bg-amber-500 px-5 py-2 text-sm font-semibold text-ink-950 hover:bg-amber-400 disabled:opacity-50"
        :disabled="palace.busy"
        @click="palace.start"
      >
        进入死者宫殿
      </button>
    </section>

    <!-- 选英雄 -->
    <section v-else-if="phase === 'choose_hero'" class="space-y-3">
      <h2 class="text-sm font-semibold text-white">选择英雄（三选一）</h2>
      <div class="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        <button
          v-for="(c, i) in run?.heroCandidates ?? []"
          :key="i"
          class="card p-4 text-left transition hover:border-amber-400"
          :disabled="palace.busy"
          @click="palace.chooseHero(i)"
        >
          <div class="flex items-center justify-between">
            <span class="text-base font-semibold text-white">{{ c.name }}</span>
            <span class="rounded px-2 py-0.5 text-xs" :class="rarityClass(c.talent)">{{ c.talentName }}</span>
          </div>
          <p class="mt-1 text-xs text-ink-400">{{ c.attrBiasLabel ?? c.attrBias }} · 总点数 {{ c.totalPoints }}</p>
          <div class="mt-2 grid grid-cols-3 gap-1 text-center text-xs text-ink-200">
            <div class="rounded bg-ink-800 py-1">力量 {{ c.strength }}</div>
            <div class="rounded bg-ink-800 py-1">敏捷 {{ c.agility }}</div>
            <div class="rounded bg-ink-800 py-1">智力 {{ c.intellect }}</div>
          </div>
          <p v-if="c.recommendedJobs.length" class="mt-2 text-[11px] text-ink-500">
            推荐职业：{{ c.recommendedJobs.map(jobName).join(' / ') }}
          </p>
        </button>
      </div>
    </section>

    <!-- 选武器 -->
    <section v-else-if="phase === 'choose_weapon'" class="space-y-3">
      <h2 class="text-sm font-semibold text-white">选择武器（三选一，决定职业）</h2>
      <div class="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        <button
          v-for="(w, i) in run?.weaponCandidates ?? []"
          :key="i"
          class="card p-4 text-left transition hover:border-amber-400"
          :disabled="palace.busy"
          @click="palace.chooseWeapon(i)"
        >
          <div class="flex items-center justify-between">
            <span class="text-sm font-semibold" :class="rarityClass(w.rarity)">{{ w.name }}</span>
            <span class="text-xs text-ink-400">Lv.{{ w.levelReq }}</span>
          </div>
          <p class="mt-1 text-xs text-ink-400">
            {{ rarityName(w.rarity) }} · {{ w.jobId ? jobName(w.jobId) : '武器' }}
          </p>
          <p class="mt-1 text-xs text-ink-200">
            {{ w.baseAttrs.map((a) => `${a.attr} +${Math.round(a.value)}`).join('、') || '无基础属性' }}
          </p>
        </button>
      </div>
    </section>

    <!-- 进行中 -->
    <template v-else>
      <section class="card p-4">
        <div class="flex flex-wrap items-center gap-2">
          <span class="text-sm text-ink-200">
            第 {{ run?.floor }} / {{ run?.floors }} 层 · 第 {{ run?.step }} 步
          </span>
          <span class="rounded bg-ink-800 px-2 py-1 text-xs text-yellow-200">副本金币 {{ run?.gold ?? 0 }}</span>
          <span class="rounded bg-ink-800 px-2 py-1 text-xs text-emerald-200">复活 {{ run?.reviveLeft ?? 0 }}</span>
          <span v-if="run?.hero" class="rounded bg-ink-800 px-2 py-1 text-xs text-ink-200">
            {{ run.hero.name }} Lv.{{ run.hero.level }}
          </span>
          <button
            class="ml-auto rounded-md bg-rose-600/80 px-3 py-1.5 text-xs text-white hover:bg-rose-500"
            :disabled="palace.busy"
            @click="showAbandon = true"
          >
            放弃
          </button>
        </div>
        <div class="mt-3 flex flex-wrap gap-1">
          <button
            v-for="key in (['path', 'gear', 'growth', 'exchange'] as Tab[])"
            :key="key"
            class="rounded-md px-3 py-1.5 text-xs"
            :class="tab === key ? 'bg-amber-500 text-ink-950' : 'bg-ink-800 text-ink-300 hover:text-white'"
            @click="switchTab(key)"
          >
            {{ TAB_LABELS[key] }}
          </button>
        </div>
      </section>

      <!-- 路径 -->
      <section v-if="tab === 'path'" class="grid gap-4 lg:grid-cols-2">
        <div class="card p-4">
          <h3 class="text-sm font-semibold text-white">路径（自下而上）</h3>
          <div class="mt-3">
            <PalacePathMap
              :map="run?.map ?? null"
              :current-node="run?.currentNode ?? null"
              :available-nodes="run?.availableNodes ?? []"
              :visited="visited"
              @select="palace.enterNode"
            />
          </div>
          <p class="mt-2 text-[11px] text-ink-500">高亮节点为可选方向；第 10 步固定为本层层主。</p>
        </div>

        <div class="space-y-4">
          <!-- 战斗 -->
          <div v-if="inBattle" class="card p-4">
            <h3 class="text-sm font-semibold text-white">
              {{ context?.type === 'boss' ? '层主' : context?.type === 'elite' ? '精英' : '敌人' }}
            </h3>
            <div class="mt-3 space-y-3">
              <div>
                <div class="mb-1 flex justify-between text-[11px] text-ink-400">
                  <span>{{ run?.hero?.name ?? '英雄' }}</span>
                  <span>
                    {{ Math.max(0, Math.round(palace.log.length ? (palace.sim?.heroHp ?? 0) : 0)) }} /
                    {{ Math.round(stats?.maxHp ?? 0) }}
                  </span>
                </div>
                <HealthBar :value="palace.sim?.heroHp ?? 0" :max="stats?.maxHp ?? 0" :shield="palace.sim?.shield ?? 0" fill-class="bg-emerald-500" />
              </div>
              <div v-if="enemy">
                <div class="mb-1 flex justify-between text-[11px] text-ink-400">
                  <span>{{ enemy.name }}</span>
                  <span>{{ Math.max(0, Math.round(enemy.hp)).toLocaleString() }} / {{ Math.round(enemy.maxHp).toLocaleString() }}</span>
                </div>
                <HealthBar :value="enemy.hp" :max="enemy.maxHp" :shield="enemy.shield" fill-class="bg-rose-500" />
              </div>
            </div>
            <div class="relative mt-3 h-32 overflow-hidden rounded-lg bg-ink-900/60 p-2 text-[11px] leading-relaxed">
              <div
                v-for="(line, i) in palace.log.slice(-12)"
                :key="i"
                :class="line.tone === 'damage' ? 'text-rose-300' : line.tone === 'loot' ? 'text-amber-300' : 'text-ink-300'"
              >
                {{ line.text }}
              </div>
            </div>
          </div>

          <!-- 事件 -->
          <div v-else-if="context?.type === 'event' && context.event" class="card p-4">
            <h3 class="text-sm font-semibold text-white">事件 · {{ context.event.name }}</h3>
            <p class="mt-2 text-xs text-ink-300">{{ context.event.desc }}</p>
            <div class="mt-3 space-y-2">
              <button
                v-for="(c, i) in context.event.choices"
                :key="i"
                class="w-full rounded-lg border border-ink-700 bg-ink-800/60 px-3 py-2 text-left text-xs text-ink-100 hover:border-amber-400 disabled:opacity-50"
                :disabled="palace.busy"
                @click="palace.eventChoose(i)"
              >
                {{ c.label }}
              </button>
            </div>
          </div>

          <!-- 商店 -->
          <div v-else-if="context?.type === 'shop' && context.shop" class="card p-4">
            <h3 class="text-sm font-semibold text-white">商店</h3>
            <p class="mt-1 text-xs text-ink-400">副本金币：{{ run?.gold ?? 0 }}</p>
            <div class="mt-3 space-y-2">
              <div
                v-for="(offer, i) in context.shop.offers"
                :key="offer.id"
                class="flex items-center justify-between rounded-lg border border-ink-700 bg-ink-800/60 px-3 py-2"
              >
                <div>
                  <p class="text-xs text-ink-100">{{ offer.name }}</p>
                  <p class="text-[11px] text-ink-500">{{ offer.desc ?? offer.buff?.desc ?? '' }}</p>
                </div>
                <button
                  class="rounded-md bg-amber-500 px-3 py-1 text-xs font-medium text-ink-950 hover:bg-amber-400 disabled:opacity-40"
                  :disabled="palace.busy || offer.sold || (run?.gold ?? 0) < offer.price"
                  @click="palace.shopBuy(i)"
                >
                  {{ offer.sold ? '已购买' : `${offer.price} 金币` }}
                </button>
              </div>
            </div>
          </div>

          <!-- 战斗奖励三选一 -->
          <div v-if="run?.pendingReward" class="card p-4">
            <h3 class="text-sm font-semibold text-white">选择奖励</h3>
            <div class="mt-3 grid gap-2 sm:grid-cols-3">
              <button
                v-for="(opt, i) in run.pendingReward as PalaceRewardOption[]"
                :key="i"
                class="rounded-lg border border-ink-700 bg-ink-800/60 p-3 text-left hover:border-amber-400 disabled:opacity-50"
                :disabled="palace.busy"
                @click="palace.claimReward(i)"
              >
                <p class="text-xs font-medium text-amber-200">{{ rewardTitle(opt) }}</p>
                <p v-if="opt.equip" class="mt-1 text-xs" :class="rarityClass(opt.equip.rarity)">
                  {{ opt.equip.name }}（{{ rarityName(opt.equip.rarity) }} Lv.{{ opt.equip.levelReq }}）
                </p>
                <p v-if="opt.buff" class="mt-1 text-xs text-sky-200">{{ buffText(opt.buff) }}</p>
              </button>
            </div>
          </div>

          <!-- 已获得祝福 -->
          <div v-if="run?.buffs?.length" class="card p-4">
            <h3 class="text-sm font-semibold text-white">本次探索的祝福</h3>
            <div class="mt-2 flex flex-wrap gap-2">
              <span
                v-for="buff in run.buffs"
                :key="buff.id + buff.value"
                class="rounded bg-ink-800 px-2 py-1 text-[11px] text-sky-200"
              >
                {{ buffText(buff) }}
              </span>
            </div>
          </div>
        </div>
      </section>

      <!-- 装备 -->
      <section v-else-if="tab === 'gear'" class="space-y-4">
        <div class="card p-4">
          <h3 class="text-sm font-semibold text-white">当前穿戴</h3>
          <div class="mt-3 grid gap-2 sm:grid-cols-2">
            <div
              v-for="row in equippedItems"
              :key="row.slot"
              class="rounded-lg border border-ink-700 bg-ink-800/50 p-2 text-xs"
            >
              <span class="text-ink-500">{{ row.slot }}</span>
              <span v-if="row.item" class="ml-2" :class="rarityClass(row.item.rarity)">{{ row.item.name }}</span>
              <span v-else class="ml-2 text-ink-600">空</span>
            </div>
          </div>
        </div>
        <div class="card p-4">
          <h3 class="text-sm font-semibold text-white">副本背包</h3>
          <div class="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
            <div
              v-for="(item, i) in run?.items ?? []"
              :key="i"
              class="rounded-lg border border-ink-700 bg-ink-800/50 p-3"
            >
              <div class="flex items-center justify-between">
                <span class="text-xs" :class="rarityClass(item.rarity)">{{ item.name }}</span>
                <span class="text-[11px] text-ink-500">Lv.{{ item.levelReq }}</span>
              </div>
              <p class="mt-1 text-[11px] text-ink-400">
                {{ item.baseAttrs.map((a) => `${a.attr} +${Math.round(a.value)}`).join('、') || '无基础属性' }}
              </p>
              <button
                class="mt-2 rounded bg-amber-500 px-2 py-0.5 text-[11px] font-medium text-ink-950 hover:bg-amber-400 disabled:opacity-40"
                :disabled="palace.busy || run?.equipped[item.slot] === i"
                @click="palace.equip(i)"
              >
                {{ run?.equipped[item.slot] === i ? '已装备' : '装备' }}
              </button>
            </div>
          </div>
        </div>
      </section>

      <!-- 成长 -->
      <section v-else-if="tab === 'growth'" class="space-y-4">
        <div class="card p-4">
          <div class="flex items-center justify-between">
            <h3 class="text-sm font-semibold text-white">局外成长</h3>
            <span class="rounded bg-ink-800 px-2 py-1 text-xs text-amber-200">可用成长点 {{ palace.growth?.points ?? profile?.growthPoints ?? 0 }}</span>
          </div>
          <p class="mt-1 text-[11px] text-ink-500">击败层主获得成长点；同类别需按层级依次解锁，永久生效于后续所有探索。</p>
        </div>
        <div v-for="cat in palace.growth?.categories ?? []" :key="cat.id" class="card p-4">
          <div class="flex items-center gap-2">
            <h4 class="text-sm font-semibold text-white">{{ cat.name }}</h4>
            <InfoTip :title="cat.name"><p class="text-xs text-ink-300">{{ cat.desc }}</p></InfoTip>
          </div>
          <div class="mt-2 grid gap-2 sm:grid-cols-3 lg:grid-cols-5">
            <button
              v-for="node in cat.nodes"
              :key="node.id"
              class="rounded-lg border p-2 text-left text-[11px] transition"
              :class="[
                node.unlocked
                  ? 'border-emerald-500/50 bg-emerald-500/10 text-emerald-200'
                  : node.affordable
                    ? 'border-amber-500/50 bg-amber-500/10 text-amber-100 hover:bg-amber-500/20'
                    : 'border-ink-700 bg-ink-900/50 text-ink-500',
              ]"
              :disabled="!node.affordable || palace.busy"
              @click="palace.unlockGrowth(node.id)"
            >
              <p>{{ node.name }}</p>
              <p class="mt-1 text-[10px]">
                <template v-if="node.unlocked">已解锁</template>
                <template v-else-if="!node.available">需前置</template>
                <template v-else>消耗 {{ node.cost }} 点</template>
              </p>
            </button>
          </div>
        </div>
      </section>

      <!-- 兑换 -->
      <section v-else-if="tab === 'exchange'" class="space-y-4">
        <div class="card p-4">
          <div class="flex flex-wrap items-center gap-2">
            <h3 class="text-sm font-semibold text-white">奖励兑换</h3>
            <span class="rounded bg-ink-800 px-2 py-1 text-xs text-orange-300">烈火纹章 {{ palace.exchange?.flameCrest ?? profile?.flameCrest ?? 0 }}</span>
            <span class="rounded bg-ink-800 px-2 py-1 text-xs text-violet-300">玻璃南瓜 {{ palace.exchange?.glassPumpkin ?? profile?.glassPumpkin ?? 0 }}</span>
          </div>
        </div>
        <div class="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
          <div
            v-for="entry in palace.exchange?.entries ?? []"
            :key="entry.id"
            class="card p-4"
          >
            <p class="text-sm text-ink-100">{{ entry.name }}</p>
            <p class="mt-1 text-[11px] text-ink-400">
              消耗：
              <template v-if="entry.cost.flameCrest">烈火纹章 ×{{ entry.cost.flameCrest }}</template>
              <template v-if="entry.cost.flameCrest && entry.cost.glassPumpkin">、</template>
              <template v-if="entry.cost.glassPumpkin">玻璃南瓜 ×{{ entry.cost.glassPumpkin }}</template>
            </p>
            <button
              class="mt-2 rounded bg-amber-500 px-3 py-1 text-xs font-medium text-ink-950 hover:bg-amber-400 disabled:opacity-40"
              :disabled="!entry.affordable || palace.busy"
              @click="palace.exchangeBuy(entry.id, 1)"
            >
              兑换
            </button>
          </div>
        </div>
      </section>
    </template>

    <!-- 放弃确认 -->
    <div v-if="showAbandon" class="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
      <div class="card w-full max-w-sm p-4">
        <h3 class="text-sm font-semibold text-white">放弃本次探索？</h3>
        <p class="mt-2 text-xs text-ink-300">已获得的成长点与代币会保留，但本次进度与副本内装备将丢弃。</p>
        <div class="mt-4 flex justify-end gap-2">
          <button class="rounded-md bg-ink-800 px-3 py-1.5 text-xs text-ink-200" @click="showAbandon = false">取消</button>
          <button class="rounded-md bg-rose-600 px-3 py-1.5 text-xs text-white" @click="onAbandon">确认放弃</button>
        </div>
      </div>
    </div>
  </div>
</template>
