<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'

import data from '@shared/schema'

import BattleFloatLayer from '@/components/BattleFloatLayer.vue'
import ItemIcon from '@/components/ItemIcon.vue'
import InfoTip from '@/components/InfoTip.vue'
import JobFigure from '@/components/JobFigure.vue'
import JobIcon from '@/components/JobIcon.vue'
import Modal from '@/components/Modal.vue'
import {
  maxDifficultyLevel,
  monsterAttackMultiplier,
  monsterExpMultiplier,
  monsterGoldMultiplier,
  monsterHpMultiplier,
  playerAttackMultiplier,
  playerDefenseMultiplier,
} from '@/game/core/difficulty'
import { dodgeExplain, threeAttrExplain } from '@/game/explanations'
import { useGameStore } from '@/stores/game'
import { jobName, rarityClass, rarityName } from '@/utils/format'

const game = useGameStore()
const showBoss = ref(false)

const sim = computed(() => game.sim)
const hero = computed(() => game.hero)
const region = computed(() => game.state?.currentRegion ?? null)

const stats = computed(() => hero.value?.stats ?? null)

// ---- 难度等级 ----
const difficultyLevel = computed(() => game.state?.difficulty?.level ?? 0)
const difficultyUnlocked = computed(() => game.state?.difficulty?.unlocked ?? 0)
/** 已解锁难度选项（0..unlocked）。 */
const difficultyOptions = computed(() =>
  Array.from({ length: difficultyUnlocked.value + 1 }, (_, index) => index),
)
const playerAtkMult = computed(() => playerAttackMultiplier(difficultyLevel.value))
const playerDefMult = computed(() => playerDefenseMultiplier(difficultyLevel.value))

/** 难度修正后的有效面板值（攻击/防御随难度下降）。 */
const displayAttack = computed(() => (stats.value?.attack ?? 0) * playerAtkMult.value)
const displayMagicAttack = computed(() => (stats.value?.magicAttack ?? 0) * playerAtkMult.value)
const displayPhysDef = computed(() => (stats.value?.physDef ?? 0) * playerDefMult.value)

const difficultyTitle = computed(() => {
  const lv = difficultyLevel.value
  if (lv === 0) return '默认难度：数值与各地区基础一致。通关最后一个地区的 BOSS 可解锁更高难度。'
  return (
    `难度 ${difficultyLevel.value} 修正：\n` +
    `玩家攻击 ×${playerAtkMult.value.toFixed(2)}、防御 ×${playerDefMult.value.toFixed(2)}\n` +
    `怪物生命 ×${monsterHpMultiplier(lv).toFixed(2)}、攻击 ×${monsterAttackMultiplier(lv).toFixed(2)}\n` +
    `怪物金币 ×${monsterGoldMultiplier(lv).toFixed(2)}、经验 ×${monsterExpMultiplier(lv).toFixed(2)}`
  )
})

async function onDifficultyChange(event: Event) {
  const level = Number((event.target as HTMLSelectElement).value)
  if (level === difficultyLevel.value) return
  await game.setDifficulty(level)
}


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
  crit: 'text-orange-300',
  dh: 'text-cyan-300',
  critDh: 'text-yellow-200',
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
  // sim 是 shallowRef：必须显式依赖 0.1s 节拍，否则该 computed 会一直是首次缓存的 0。
  void game.uiTick
  const s = game.sim
  if (!s) return 0
  return Math.min(100, (s.killCount / Math.max(1, s.killsRequired)) * 100)
})

/** 技能 CD：剩余秒数与进度（同样由 0.1s 节拍驱动刷新）。 */
const skillStates = computed<Record<string, { remaining: number; pct: number }>>(() => {
  void game.uiTick
  const out: Record<string, { remaining: number; pct: number }> = {}
  for (const state of sim.value?.skillStates ?? []) {
    out[state.id] = { remaining: Math.round(state.remaining * 10) / 10, pct: state.pct }
  }
  return out
})

/** 绝技充能槽（由 0.1s 节拍驱动刷新）。 */
const signature = computed(() => {
  void game.uiTick
  return sim.value?.signatureState ?? null
})

/** 阵亡复活倒计时：剩余秒数与进度（由 0.1s 节拍驱动刷新）。总时长随「归魂 / 沉魂」词条变化。 */
const reviveDelay = data.heroes.reviveDelaySeconds
const reviveTimer = computed(() => {
  void game.uiTick
  const remaining = Math.max(0, sim.value?.deathTimer ?? 0)
  const total = sim.value?.reviveTotal || reviveDelay
  return {
    remaining: Math.round(remaining * 10) / 10,
    pct: total > 0 ? Math.min(100, ((total - remaining) / total) * 100) : 100,
  }
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

// 概率 / 面板速率的「如何计算」说明（数值取自当前面板，公式镜像后端）
function critRateInfo() {
  return threeAttrExplain('critRate', hero.value?.level ?? 1, stats.value?.critValue ?? 0)
}
function critDamageInfo() {
  return threeAttrExplain('critDamage', hero.value?.level ?? 1, stats.value?.critValue ?? 0)
}
function dhRateInfo() {
  return threeAttrExplain('dhRate', hero.value?.level ?? 1, stats.value?.dhValue ?? 0)
}
function detBonusInfo() {
  return threeAttrExplain('detBonus', hero.value?.level ?? 1, stats.value?.detValue ?? 0)
}
function dodgeInfo() {
  return dodgeExplain(hero.value?.agility ?? 0, stats.value?.dodgePct ?? 0)
}
</script>

<template>
  <div class="space-y-4">
    <section data-tutorial="battle" class="card p-4">
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

        <div class="ml-auto flex flex-wrap items-center justify-end gap-2">
          <span class="rounded bg-ink-800 px-2 py-1 text-xs text-ink-200">{{ phaseLabel }}</span>
          <label
            class="flex items-center gap-1.5 rounded-md border px-2 py-1.5 text-xs"
            :class="
              difficultyLevel > 0
                ? 'border-amber-400 bg-amber-500/15 text-amber-200'
                : 'border-ink-600 text-ink-300'
            "
            :title="difficultyTitle"
          >
            难度
            <select
              class="cursor-pointer bg-transparent text-xs font-medium text-inherit outline-none disabled:cursor-not-allowed"
              :value="difficultyLevel"
              :disabled="difficultyUnlocked === 0"
              @change="onDifficultyChange"
            >
              <option
                v-for="lv in difficultyOptions"
                :key="lv"
                :value="lv"
                class="bg-ink-900 text-ink-100"
              >
                {{ lv }}
              </option>
            </select>
            <span class="text-ink-500">/ {{ maxDifficultyLevel }}</span>
          </label>
          <button
            class="rounded-md border px-3 py-1.5 text-xs transition"
            :class="
              game.autoAdvance
                ? 'border-emerald-400 bg-emerald-500/15 text-emerald-200'
                : 'border-ink-600 text-ink-400 hover:border-ink-400'
            "
            :title="
              game.autoAdvance
                ? '击杀 BOSS 后自动前往下一地区（点击关闭）'
                : '开启后击杀 BOSS 自动前往下一地区'
            "
            @click="game.setAutoAdvance(!game.autoAdvance)"
          >
            自动进入下一阶段{{ game.autoAdvance ? ' · 开' : ' · 关' }}
          </button>
          <button
            v-if="game.isStaying"
            class="rounded-md border border-amber-400 bg-amber-500/15 px-3 py-1.5 text-xs text-amber-200 transition hover:border-amber-300"
            title="原地挂机中：击败 BOSS 不再弹出结算窗（点击关闭，恢复弹窗）"
            @click="game.setStayRegion(null)"
          >
            原地挂机 · 开
          </button>
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
          <span class="flex items-center gap-1.5 rounded bg-ink-800 px-2 py-0.5 text-[11px] text-sky-300">
            <JobIcon :job-id="hero?.jobId" :size="20" />
            {{ jobName(hero?.jobId ?? 'adventurer') }}
          </span>
        </header>

        <dl class="mt-3 grid grid-cols-2 gap-x-4 gap-y-1 text-[11px] text-ink-400 sm:grid-cols-3">
          <div><dt>战力</dt><dd class="font-mono text-amber-200">{{ game.state?.power ?? 0 }}</dd></div>
          <div><dt>攻击力</dt><dd class="font-mono text-ink-200">{{ displayAttack.toFixed(0) }}</dd></div>
          <div><dt>魔法攻击</dt><dd class="font-mono text-ink-200">{{ displayMagicAttack.toFixed(0) }}</dd></div>
          <div><dt>物理防御</dt><dd class="font-mono text-ink-200">{{ displayPhysDef.toFixed(0) }}</dd></div>
          <div><dt>暴击率</dt><dd class="font-mono text-sky-300">{{ stats?.critRatePct?.toFixed(1) }}%<InfoTip :title="critRateInfo().title"><p v-for="(line, i) in critRateInfo().lines" :key="i">{{ line }}</p></InfoTip></dd></div>
          <div><dt>暴击伤害</dt><dd class="font-mono text-sky-300">{{ stats?.critDamagePct?.toFixed(0) }}%<InfoTip :title="critDamageInfo().title"><p v-for="(line, i) in critDamageInfo().lines" :key="i">{{ line }}</p></InfoTip></dd></div>
          <div><dt>直击率</dt><dd class="font-mono text-sky-300">{{ stats?.dhRatePct?.toFixed(1) }}%<InfoTip :title="dhRateInfo().title"><p v-for="(line, i) in dhRateInfo().lines" :key="i">{{ line }}</p></InfoTip></dd></div>
          <div><dt>信念增伤</dt><dd class="font-mono text-sky-300">{{ stats?.detBonusPct?.toFixed(1) }}%<InfoTip :title="detBonusInfo().title"><p v-for="(line, i) in detBonusInfo().lines" :key="i">{{ line }}</p></InfoTip></dd></div>
          <div><dt>闪避</dt><dd class="font-mono text-ink-200">{{ stats?.dodgePct?.toFixed(1) }}%<InfoTip :title="dodgeInfo().title"><p v-for="(line, i) in dodgeInfo().lines" :key="i">{{ line }}</p></InfoTip></dd></div>
        </dl>

        <div class="mt-3 space-y-2">
          <div
            v-if="sim?.phase === 'dead'"
            class="rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2"
          >
            <div class="flex items-center justify-between text-[11px]">
              <span class="font-medium text-rose-200">英雄已阵亡</span>
              <span class="font-mono text-rose-200">{{ reviveTimer.remaining.toFixed(1) }}s 后复活</span>
            </div>
            <div class="mt-1.5 h-1.5 overflow-hidden rounded-full bg-ink-900">
              <div
                class="h-full rounded-full bg-rose-400 transition-[width] duration-100 ease-linear"
                :style="{ width: `${reviveTimer.pct}%` }"
              />
            </div>
          </div>
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
              <span v-if="game.state?.catchUpExpBonusPct" class="text-amber-300">追赶经验 +100%</span>
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

        <div class="relative mt-4 h-28 overflow-hidden rounded-lg border border-ink-700 bg-ink-900/60">
          <JobFigure :job-id="hero?.jobId" :size="40" class="absolute bottom-1 left-2" />
          <div class="absolute inset-0 flex items-end justify-center gap-6 pb-2">
            <BattleFloatLayer />
          </div>
          <p class="absolute left-2 top-2 text-[10px] text-ink-600">伤害浮动演示</p>
        </div>
      </section>
    </div>

    <!-- 绝技（充能槽） -->
    <section v-if="signature" class="card p-4">
      <div class="flex items-center justify-between">
        <h3 class="text-sm font-semibold text-white">绝技 · {{ signature.name }}</h3>
        <span :class="signature.ready ? 'text-amber-300' : 'text-ink-500'" class="text-[11px]">
          {{ signature.ready ? '就绪！' : `充能中 ${Math.floor(signature.charge)}%` }}
        </span>
      </div>
      <div class="mt-3 h-2.5 overflow-hidden rounded-full bg-ink-900">
        <div
          class="h-full rounded-full transition-[width] duration-100 ease-linear"
          :class="signature.ready ? 'bg-amber-400' : 'bg-sky-500'"
          :style="{ width: `${signature.charge}%` }"
        />
      </div>
      <p class="mt-2 text-[10px] text-ink-600">
        战斗中充能、满槽自动释放（不占 GCD / 不耗魔力）；纯时间约 {{ signature.chargeSeconds }}s。
      </p>
    </section>

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
            <span v-if="skillStates[skill.id]?.remaining > 0" class="text-amber-300">
              · 剩 {{ skillStates[skill.id].remaining.toFixed(1) }}s
            </span>
            <span v-else class="text-emerald-300">· 就绪</span>
          </p>
          <div class="mt-1 h-1.5 overflow-hidden rounded-full bg-ink-900">
            <div
              class="h-full rounded-full transition-[width] duration-100 ease-linear"
              :class="skillStates[skill.id]?.remaining > 0 ? 'bg-amber-400' : 'bg-emerald-500'"
              :style="{ width: `${skillStates[skill.id]?.pct ?? 100}%` }"
            />
          </div>
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
        <p v-if="game.bossResult.unlockedDifficulty" class="rounded bg-amber-500/15 px-2 py-1 text-xs text-amber-200">
          已解锁难度 {{ game.bossResult.unlockedDifficulty }}！可在顶部难度选择处切换。
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
        <p class="text-xs text-ink-400">是否前往下一地区？选择「留在当前地区」后将不再弹出本提示。</p>
      </div>

      <template #footer>
        <button
          class="rounded-md bg-ink-700 px-3 py-2 text-sm hover:bg-ink-600"
          @click="game.stayInCurrentRegion()"
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
