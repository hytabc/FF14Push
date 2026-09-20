<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'

import ItemIcon from '@/components/ItemIcon.vue'
import Modal from '@/components/Modal.vue'
import { useGameStore } from '@/stores/game'
import { jobName, rarityClass, rarityName } from '@/utils/format'

const game = useGameStore()
const showBoss = ref(false)

const sim = computed(() => game.sim)
const hero = computed(() => game.hero)
const region = computed(() => game.state?.currentRegion ?? null)

const stats = computed(() => hero.value?.stats ?? null)

const expPct = computed(() => {
  if (!hero.value || !game.state) return 0
  const need = game.state.expToNext
  return need > 0 ? Math.min(100, (hero.value.exp / need) * 100) : 0
})

const logTone: Record<string, string> = {
  normal: 'text-ink-400',
  skill: 'text-sky-300',
  damage: 'text-amber-200',
  loot: 'text-emerald-300',
  danger: 'text-rose-400',
  system: 'text-ink-200',
  boss: 'text-fuchsia-300',
}

const phaseLabel = computed(() => {
  switch (game.sim?.phase) {
    case 'mob':
      return '小怪阶段'
    case 'boss':
      return 'BOSS 战'
    case 'dead':
      return '阵亡复活中'
    case 'cleared':
      return 'BOSS 已击败'
    default:
      return '待机'
  }
})

const killProgress = computed(() => {
  const s = game.sim
  if (!s) return 0
  return Math.min(100, (s.killCount / Math.max(1, s.killsRequired)) * 100)
})

/** 技能剩余 CD：量化到 0.1s，并由 0.1s 节拍（uiTick）驱动刷新。 */
const cdRemaining = computed<Record<string, number>>(() => {
  void game.uiTick
  const out: Record<string, number> = {}
  for (const skill of sim.value?.skills ?? []) {
    out[skill.id] = Math.max(0, Math.round((sim.value?.cooldowns[skill.id] ?? 0) * 10) / 10)
  }
  return out
})

onMounted(async () => {
  if (!game.state) await game.loadState()
  if (!game.isRunning && game.state?.hero.currentRegionId) {
    await game.startBattle()
  }
})

onUnmounted(() => {
  // 战斗在后台继续：这里不停止会话，由整页可见性控制
})

async function toggleBattle() {
  if (game.isRunning) await game.stopBattle()
  else await game.startBattle()
}

function openBossDialog() {
  showBoss.value = true
}
</script>

<template>
  <div class="space-y-4">
    <section class="card p-4">
      <div class="flex flex-wrap items-center gap-3">
        <div>
          <p class="text-xs text-ink-400">当前地区</p>
          <h2 class="text-lg font-semibold text-white">
            {{ region?.name ?? '—' }}
            <span class="ml-1 text-xs text-ink-400">
              Lv.{{ region?.levelMin }}-{{ region?.levelMax }}
            </span>
          </h2>
        </div>

        <div class="ml-auto flex items-center gap-2">
          <span class="rounded bg-ink-800 px-2 py-1 text-xs text-ink-200">{{ phaseLabel }}</span>
          <button
            class="rounded-md px-3 py-1.5 text-xs font-medium transition"
            :class="
              game.isRunning
                ? 'bg-rose-600/80 text-white hover:bg-rose-500'
                : 'bg-emerald-600/80 text-white hover:bg-emerald-500'
            "
            @click="toggleBattle"
          >
            {{ game.isRunning ? '暂停挂机' : '开始挂机' }}
          </button>
          <button
            v-if="sim?.phase === 'cleared'"
            class="rounded-md bg-amber-500 px-3 py-1.5 text-xs font-medium text-ink-950"
            @click="openBossDialog"
          >
            查看 BOSS 结算
          </button>
        </div>
      </div>

      <div class="mt-3">
        <div class="mb-1 flex justify-between text-[11px] text-ink-400">
          <span>小怪击杀进度</span>
          <span>{{ sim?.killCount ?? 0 }} / {{ sim?.killsRequired ?? region?.killsRequired ?? 0 }}</span>
        </div>
        <div class="h-2 overflow-hidden rounded-full bg-ink-800">
          <div class="h-full rounded-full bg-amber-400 transition-all" :style="{ width: `${killProgress}%` }" />
        </div>
      </div>
    </section>

    <div class="grid gap-4 lg:grid-cols-[1.1fr_1fr]">
      <!-- 英雄 -->
      <section class="card relative overflow-hidden p-4">
        <header class="flex items-center justify-between">
          <h3 class="text-sm font-semibold text-white">
            {{ hero?.name }}
            <span class="ml-1 text-xs text-ink-400">Lv.{{ hero?.level }}</span>
          </h3>
          <span class="rounded bg-ink-800 px-2 py-0.5 text-[11px] text-sky-300">
            {{ jobName(hero?.jobId ?? 'adventurer') }}
          </span>
        </header>

        <dl class="mt-3 grid grid-cols-2 gap-x-4 gap-y-1 text-[11px] text-ink-400 sm:grid-cols-3">
          <div><dt>战力</dt><dd class="font-mono text-amber-200">{{ game.state?.power ?? 0 }}</dd></div>
          <div><dt>攻击力</dt><dd class="font-mono text-ink-200">{{ stats?.attack?.toFixed(0) }}</dd></div>
          <div><dt>魔法攻击</dt><dd class="font-mono text-ink-200">{{ stats?.magicAttack?.toFixed(0) }}</dd></div>
          <div><dt>物理防御</dt><dd class="font-mono text-ink-200">{{ stats?.physDef?.toFixed(0) }}</dd></div>
          <div><dt>暴击率</dt><dd class="font-mono text-sky-300">{{ stats?.critRatePct?.toFixed(1) }}%</dd></div>
          <div><dt>暴击伤害</dt><dd class="font-mono text-sky-300">{{ stats?.critDamagePct?.toFixed(0) }}%</dd></div>
          <div><dt>直击率</dt><dd class="font-mono text-sky-300">{{ stats?.dhRatePct?.toFixed(1) }}%</dd></div>
          <div><dt>信念增伤</dt><dd class="font-mono text-sky-300">{{ stats?.detBonusPct?.toFixed(1) }}%</dd></div>
          <div><dt>闪避</dt><dd class="font-mono text-ink-200">{{ stats?.dodgePct?.toFixed(1) }}%</dd></div>
        </dl>

        <div class="mt-3 space-y-2">
          <div>
            <div class="mb-1 flex justify-between text-[11px] text-ink-400">
              <span>生命</span>
              <span>{{ Math.max(0, Math.round(sim?.heroHp ?? 0)) }} / {{ Math.round(stats?.maxHp ?? 0) }}</span>
            </div>
            <div class="h-2.5 overflow-hidden rounded-full bg-ink-800">
              <div class="h-full rounded-full bg-emerald-500 transition-all" :style="{ width: `${sim?.heroHpPct ?? 0}%` }" />
            </div>
          </div>
          <div>
            <div class="mb-1 flex justify-between text-[11px] text-ink-400">
              <span>魔法值</span>
              <span>{{ Math.round(sim?.heroMp ?? 0) }} / {{ Math.round(stats?.maxMp ?? 0) }}</span>
            </div>
            <div class="h-2 overflow-hidden rounded-full bg-ink-800">
              <div class="h-full rounded-full bg-sky-500 transition-all" :style="{ width: `${sim?.mpPct ?? 0}%` }" />
            </div>
          </div>
          <div>
            <div class="mb-1 flex justify-between text-[11px] text-ink-400">
              <span>经验</span>
              <span>{{ hero?.exp }} / {{ game.state?.expToNext }}</span>
            </div>
            <div class="h-1.5 overflow-hidden rounded-full bg-ink-800">
              <div class="h-full rounded-full bg-amber-400 transition-all" :style="{ width: `${expPct}%` }" />
            </div>
          </div>
        </div>
      </section>

      <!-- 怪物 -->
      <section class="card relative overflow-hidden p-4">
        <header class="flex items-center justify-between">
          <h3 class="text-sm font-semibold text-white">{{ sim?.monsterName ?? '等待刷新…' }}</h3>
          <span
            v-if="sim?.monster"
            class="rounded px-2 py-0.5 text-[11px]"
            :class="sim.monster.kind === 'boss' ? 'bg-fuchsia-500/20 text-fuchsia-200' : sim.monster.kind === 'elite' ? 'bg-amber-500/20 text-amber-200' : 'bg-ink-800 text-ink-300'"
          >
            {{ sim.monster.kind === 'boss' ? 'BOSS' : sim.monster.kind === 'elite' ? '精英' : '普通' }}
          </span>
        </header>

        <div v-if="sim?.monster" class="mt-3 space-y-1 text-[11px] text-ink-400">
          <div class="flex justify-between"><span>生命</span><span class="font-mono">{{ Math.max(0, Math.round(sim.monsterHp)) }} / {{ Math.round(sim.monsterMaxHp) }}</span></div>
          <div class="flex justify-between"><span>攻击力</span><span class="font-mono">{{ sim.monster.attack }}</span></div>
          <div class="flex justify-between"><span>防御力</span><span class="font-mono">{{ sim.monster.defense }}</span></div>
          <div class="flex justify-between"><span>攻击间隔</span><span class="font-mono">{{ sim.monster.attackInterval }}s</span></div>
          <div v-if="sim.monster.skills?.length" class="pt-1 text-fuchsia-300">
            特殊技能：{{ sim.monster.skills.map((s) => s.name).join('、') }}
          </div>
        </div>
        <p v-else class="mt-3 text-[11px] text-ink-600">怪物正在靠近…</p>

        <div class="mt-3 h-3 overflow-hidden rounded-full bg-ink-800">
          <div class="h-full rounded-full bg-rose-500 transition-all" :style="{ width: `${sim?.monsterHpPct ?? 0}%` }" />
        </div>

        <div class="relative mt-4 h-24 overflow-hidden rounded-lg border border-ink-700 bg-ink-900/60">
          <div class="absolute inset-0 flex items-end justify-center gap-6 pb-2">
            <transition-group name="float">
              <span
                v-for="f in sim?.floating ?? []"
                :key="f.id"
                class="animate-float font-mono text-sm font-bold"
                :class="f.tone === 'hero' ? 'text-emerald-300' : f.tone === 'crit' ? 'text-orange-300' : 'text-rose-300'"
              >
                {{ f.text }}
              </span>
            </transition-group>
          </div>
          <p class="absolute left-2 top-2 text-[10px] text-ink-600">伤害浮动演示</p>
        </div>
      </section>
    </div>

    <!-- 技能条 -->
    <section class="card p-4">
      <h3 class="text-sm font-semibold text-white">技能（自动释放）</h3>
      <div class="mt-3 flex flex-wrap gap-2">
        <div
          v-for="skill in sim?.skills ?? []"
          :key="skill.id"
          class="w-32 rounded-lg border border-ink-700 bg-ink-800 p-2"
        >
          <p class="truncate text-[11px] font-medium text-ink-200">{{ skill.name }}</p>
          <p class="mt-0.5 text-[10px] text-ink-400">
            {{ skill.potency > 0 ? `${skill.potency}% 威力` : '辅助' }} · MP {{ skill.mpCost }}
          </p>
          <p class="text-[10px] text-ink-600">
            CD {{ skill.cd }}s
            <span v-if="cdRemaining[skill.id] > 0" class="text-amber-300">
              · 剩 {{ cdRemaining[skill.id].toFixed(1) }}s
            </span>
          </p>
        </div>
      </div>
    </section>

    <!-- 战斗日志 -->
    <section class="card p-4">
      <div class="flex items-center justify-between">
        <h3 class="text-sm font-semibold text-white">战斗日志</h3>
        <span class="text-[11px] text-ink-600">刷新频率 ≤ 1 秒</span>
      </div>
      <div class="mt-3 h-56 overflow-y-auto rounded-lg border border-ink-800 bg-ink-950/60 p-3 font-mono text-[11px] leading-relaxed">
        <p v-for="entry in [...game.battleLog].reverse()" :key="entry.id" :class="logTone[entry.tone]">
          {{ entry.text }}
        </p>
        <p v-if="!game.battleLog.length" class="text-ink-600">尚无战斗记录</p>
      </div>
    </section>

    <!-- BOSS 结算 -->
    <Modal :open="!!game.bossResult" title="BOSS 已击败！" @close="game.dismissBossResult()">
      <div v-if="game.bossResult" class="space-y-3 text-sm">
        <p class="text-ink-200">
          击败了「{{ game.bossResult.bossName }}」
          <span v-if="game.bossResult.firstClear" class="ml-1 text-amber-300">（首次通关）</span>
        </p>
        <ul class="space-y-1 text-xs text-ink-300">
          <li>金币：<span class="font-mono text-amber-300">+{{ game.bossResult.gold }}</span></li>
          <li>经验：<span class="font-mono text-sky-300">+{{ game.bossResult.exp }}</span></li>
          <li v-if="game.bossResult.box">装备宝箱：{{ game.bossResult.box }}</li>
        </ul>
        <div v-if="game.bossResult.items.length" class="space-y-1">
          <div
            v-for="item in game.bossResult.items"
            :key="item.id"
            class="flex items-center gap-1.5 text-xs"
            :class="rarityClass(item.rarity)"
          >
            <ItemIcon :base-id="item.baseId" :rarity="item.rarity" :size="16" />
            {{ item.name }}（{{ rarityName(item.rarity) }}）
          </div>
        </div>
        <p class="text-xs text-ink-400">是否前往下一地区？</p>
      </div>

      <template #footer>
        <button
          class="rounded-md bg-ink-700 px-3 py-2 text-sm hover:bg-ink-600"
          @click="game.dismissBossResult()"
        >
          留在当前地区
        </button>
        <button
          v-if="game.bossResult?.nextRegionId"
          class="rounded-md bg-amber-500 px-3 py-2 text-sm font-medium text-ink-950 hover:bg-amber-400"
          @click="game.dismissBossResult(); game.advanceRegion()"
        >
          前往下一地区
        </button>
      </template>
    </Modal>
  </div>
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
