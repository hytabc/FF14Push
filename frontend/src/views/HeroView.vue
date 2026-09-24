<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import data from '@shared/schema'
import ItemCard from '@/components/ItemCard.vue'
import ItemIcon from '@/components/ItemIcon.vue'
import JobFigure from '@/components/JobFigure.vue'
import JobIcon from '@/components/JobIcon.vue'
import StatTip from '@/components/StatTip.vue'
import TermBadges from '@/components/TermBadges.vue'
import { isHealingSkill, skillMpCost, type SkillLike } from '@/game/core/combat'
import { eggSkillSet } from '@/game/core/egg'
import { statExplain, type Explain, type StatKey } from '@/game/explanations'
import { useGameStore } from '@/stores/game'
import { attrName, attrRangeLabel, formatPercent, jobName, rarityBg, rarityClass, rarityName, skillEffectLabel } from '@/utils/format'
import { dohdolSlotGroups, equipmentSlotGroups } from '@/utils/slots'

const game = useGameStore()
const router = useRouter()
const showAllJobs = ref(false)

const loadoutTab = ref<'combat' | 'dohdol'>('combat')
const loadout = computed(() => game.loadout)
const dohdolLoadout = computed(() => game.state?.dohdol?.loadout ?? {})
const slotGroups = computed(() => equipmentSlotGroups())
/** 生产 / 采集专用装备分组：生产在左、采集在右。 */
const dohdolGroups = computed(() => dohdolSlotGroups())
const DOHDOL_BONUS_NAMES: Record<string, string> = data.dohdolEquipment.bonusNames

function dohdolBonusName(attr: string): string {
  return DOHDOL_BONUS_NAMES[attr] ?? attr
}

function goEquipment() {
  router.push('/equipment')
}

const hero = computed(() => game.hero)
const stats = computed(() => hero.value?.stats ?? null)

const skills = computed(() => {
  const jobId = hero.value?.jobId ?? 'adventurer'
  const base =
    jobId === 'adventurer'
      ? [{ id: 'basicAttack', name: '普攻', cd: data.combat.basicAttackCd as number, potency: data.combat.basicAttackPotency as number, mpCost: 0, effects: [], damageType: 'physical', target: 'single', priority: 3 }]
      : (data.jobById[jobId]?.skills ?? [])
  const egg = eggSkillSet(hero.value?.eggId, jobId)
  if (!egg) return base
  return egg.replace ? egg.skills : [...egg.skills, ...base]
})

const eggDesc = computed(() => (hero.value?.eggId ? (data.eggHeroes.byId[hero.value.eggId]?.desc ?? '彩蛋英雄') : ''))

/** 技能实际耗蓝（治疗职业的治疗 / 护盾技能含「最大魔力%」附加费）；展示与结算同源。 */
function mpCostOf(skill: SkillLike | { mpCost: number }): number {
  const s = stats.value
  return s ? skillMpCost(s, skill as unknown as SkillLike) : skill.mpCost
}

/** 治疗技能耗蓝的拆分（供 title 提示，说明数字如何得来）。 */
function mpCostTip(skill: SkillLike | { mpCost: number }): string {
  const s = stats.value
  const pct = Number(data.heroes.mp.healSkillCostMaxMpPct ?? 0)
  if (!s || pct <= 0) return ''
  if (data.jobById[s.jobId]?.role !== 'healer' || !isHealingSkill(skill as SkillLike)) return ''
  return `基础 ${skill.mpCost} + 最大魔力 ${Math.round(s.maxMp)} × ${(pct * 100).toFixed(0)}% = ${mpCostOf(skill)}`
}

/** 当前职业的绝技（招牌技能）。 */
const signature = computed(() => data.jobById[hero.value?.jobId ?? '']?.signature ?? null)

const totalCasts = computed(() =>
  Object.values(game.state?.skillStats ?? {}).reduce((sum, v) => sum + Number(v), 0),
)

const expPct = computed(() => {
  if (!hero.value || !game.state) return 0
  return game.state.expToNext > 0 ? Math.min(100, (hero.value.exp / game.state.expToNext) * 100) : 0
})

const attrBiasLabel: Record<string, string> = {
  str: '力量型',
  dex: '敏捷型',
  int: '智力型',
  balanced: '均衡型',
}

const recommendAttr = computed(() => data.jobById[hero.value?.jobId ?? '']?.mainAttr ?? null)

const ancientAttrLabel = computed(
  () =>
    ({ str: '力量', dex: '敏捷', int: '智力' } as Record<string, string>)[
      hero.value?.ancientAttr ?? ''
    ] ?? '',
)

onMounted(async () => {
  if (!game.state) await game.loadState()
})

function castShare(skillId: string) {
  if (!totalCasts.value) return 0
  return ((game.state?.skillStats[skillId] ?? 0) / totalCasts.value) * 100
}

// 面板属性：逐属性「作用 + 如何计算」（数值取自后端下发的 statBreakdown，与结算同源）
const statCtx = computed(() => ({
  breakdown: game.state?.statBreakdown ?? null,
  stats: stats.value,
  hero: hero.value ? { level: hero.value.level, agility: hero.value.agility } : null,
  powerAudit: game.state?.powerAudit,
}))

interface StatRow {
  key: StatKey
  label: string
  value: string
  tone?: string
  tip: Explain
}

const statRows = computed<StatRow[]>(() => {
  const s = stats.value
  const ctx = statCtx.value
  const int = (v?: number) => String(Math.round(v ?? 0))
  const dec = (v?: number) => (Number.isInteger(v ?? 0) ? String(v ?? 0) : (v ?? 0).toFixed(1))
  const pctOf = (v?: number, digits = 1) => formatPercent(v ?? 0, digits)
  const rows: Array<Omit<StatRow, 'tip'>> = [
    { key: 'maxHp', label: '生命值', value: int(s?.maxHp) },
    { key: 'maxMp', label: '魔法值', value: int(s?.maxMp) },
    { key: 'hpRegen', label: '生命回复', value: dec(s?.hpRegen) },
    { key: 'mpRegen', label: '魔力回复', value: dec(s?.mpRegen) },
    { key: 'attack', label: '物理攻击', value: int(s?.attack) },
    { key: 'magicAttack', label: '魔法攻击', value: int(s?.magicAttack) },
    { key: 'physDef', label: '物理防御', value: int(s?.physDef) },
    { key: 'magicDef', label: '魔法防御', value: int(s?.magicDef) },
    { key: 'critValue', label: '暴击值', value: int(s?.critValue) },
    { key: 'dhValue', label: '直击值', value: int(s?.dhValue) },
    { key: 'detValue', label: '信念值', value: int(s?.detValue) },
    { key: 'critRate', label: '暴击率', value: pctOf(s?.critRatePct), tone: 'text-sky-300' },
    { key: 'critDamage', label: '暴击伤害', value: pctOf(s?.critDamagePct, 0), tone: 'text-sky-300' },
    { key: 'dhRate', label: '直击率', value: pctOf(s?.dhRatePct), tone: 'text-sky-300' },
    { key: 'detBonus', label: '信念增伤', value: pctOf(s?.detBonusPct), tone: 'text-sky-300' },
    { key: 'dodge', label: '闪避', value: pctOf(s?.dodgePct) },
    { key: 'attackSpeed', label: '攻击速度', value: pctOf(s?.attackSpeedPct) },
    { key: 'haste', label: '技能急速', value: pctOf(s?.hastePct) },
    { key: 'hitRate', label: '命中率', value: pctOf(s?.hitRatePct) },
    { key: 'lifesteal', label: '吸血', value: pctOf(s?.lifestealPct) },
    { key: 'tenacity', label: '坚韧', value: pctOf(s?.tenacityPct) },
  ]
  return rows.map((row) => ({ ...row, tip: statExplain(row.key, ctx) }))
})

const powerTip = computed(() => statExplain('power', statCtx.value))
</script>

<template>
  <div v-if="hero" class="space-y-4">
    <section data-tutorial="hero" class="card p-4">
      <div class="flex flex-wrap items-start gap-4">
        <div class="flex-1">
          <div class="flex flex-wrap items-center gap-2">
            <h2 class="text-lg font-semibold text-white">{{ hero.name }}</h2>
            <span class="flex items-center gap-1.5 rounded bg-ink-800 px-2 py-0.5 text-[11px] text-sky-300">
              <JobIcon :job-id="hero.jobId" :size="20" />
              {{ jobName(hero.jobId) }}
            </span>
            <span class="rounded bg-ink-800 px-2 py-0.5 text-[11px]" :class="rarityClass(hero.talent)">
              {{ rarityName(hero.talent) }}资质
            </span>
            <span class="rounded bg-ink-800 px-2 py-0.5 text-[11px] text-ink-300">
              {{ attrBiasLabel[hero.attrBias] }}
            </span>
            <span v-if="hero.eggId" class="rounded bg-fuchsia-500/20 px-2 py-0.5 text-[11px] text-fuchsia-300">
              🎁 彩蛋
            </span>
            <JobFigure :job-id="hero.jobId" :size="44" class="ml-auto" />
          </div>

          <div class="mt-3">
            <div class="mb-1 flex justify-between text-[11px] text-ink-400">
              <span>等级 {{ hero.level }} / {{ data.heroes.levelCap }}</span>
              <span>{{ hero.exp }} / {{ game.state?.expToNext }} 经验</span>
              <span v-if="game.state?.catchUpExpBonusPct" class="text-amber-300">追赶经验 +100%</span>
            </div>
            <div class="h-2 overflow-hidden rounded-full bg-ink-800">
              <div class="h-full rounded-full bg-amber-400 transition-all" :style="{ width: `${expPct}%` }" />
            </div>
          </div>

          <div class="mt-3 grid grid-cols-3 gap-3 text-center">
            <div
              class="rounded-lg border p-2"
              :class="hero.ancientAttr === 'str' ? 'border-term-ancient bg-term-ancient/10' : 'border-ink-700 bg-ink-800/60'"
            >
              <p class="text-[10px] text-ink-400">力量</p>
              <p class="font-mono text-lg text-rose-300">
                {{ hero.strength }}<span v-if="hero.ancientAttr === 'str'" class="ml-0.5 align-top text-xs">🌟</span>
              </p>
            </div>
            <div
              class="rounded-lg border p-2"
              :class="hero.ancientAttr === 'dex' ? 'border-term-ancient bg-term-ancient/10' : 'border-ink-700 bg-ink-800/60'"
            >
              <p class="text-[10px] text-ink-400">敏捷</p>
              <p class="font-mono text-lg text-emerald-300">
                {{ hero.agility }}<span v-if="hero.ancientAttr === 'dex'" class="ml-0.5 align-top text-xs">🌟</span>
              </p>
            </div>
            <div
              class="rounded-lg border p-2"
              :class="hero.ancientAttr === 'int' ? 'border-term-ancient bg-term-ancient/10' : 'border-ink-700 bg-ink-800/60'"
            >
              <p class="text-[10px] text-ink-400">智力</p>
              <p class="font-mono text-lg text-sky-300">
                {{ hero.intellect }}<span v-if="hero.ancientAttr === 'int'" class="ml-0.5 align-top text-xs">🌟</span>
              </p>
            </div>
          </div>
          <p v-if="hero.ancientAttr" class="mt-2 text-[11px] text-term-ancient">
            🌟 太古属性：{{ ancientAttrLabel }}（数值为三条中最高值 ×1.25）
          </p>
          <p v-if="hero.eggId" class="mt-2 text-[11px] text-fuchsia-300">
            🎁 彩蛋英雄 · {{ eggDesc }}
          </p>
          <p class="mt-2 text-[11px] text-ink-500">
            英雄主属性对应装备三维收益 100%，非主属性 50%；职业推荐主属性为
            <b class="text-ink-300">{{ recommendAttr ? attrName(recommendAttr) : '无（冒险者）' }}</b>。
          </p>
        </div>

        <div class="w-full sm:w-64">
          <h3 class="text-xs font-semibold text-ink-300">面板属性</h3>
          <dl class="mt-2 space-y-1 text-[11px]">
            <div v-for="row in statRows" :key="row.key" class="flex justify-between">
              <dt class="text-ink-400">{{ row.label }}</dt>
              <dd class="flex items-center font-mono" :class="row.tone ?? 'text-ink-200'">
                {{ row.value }}<StatTip :explain="row.tip" />
              </dd>
            </div>
            <div class="flex justify-between">
              <dt class="text-ink-400">战力</dt>
              <dd class="flex items-center font-mono text-amber-300">
                {{ game.state?.power }}<StatTip :explain="powerTip" />
              </dd>
            </div>
            <div v-if="game.state?.powerAudit" class="space-y-1 text-xs">
              <p>进攻 {{ Math.floor(game.state.powerAudit.groups.offense ?? 0) }} · 防御 {{ Math.floor(game.state.powerAudit.groups.defense ?? 0) }} · 续航 {{ Math.floor(game.state.powerAudit.groups.sustain ?? 0) }}</p>
              <details><summary>属性贡献 · {{ game.state.powerAudit.version }}</summary>
                <p>属性按软上限递减；时长与重复次数不计入战力。</p>
                <p v-for="(entry, key) in game.state.powerAudit.contributions" :key="key">{{ attrName(String(key)) }}：{{ entry.raw.toFixed(1) }} → 有效 {{ entry.effective.toFixed(1) }} → 战力 +{{ entry.contribution.toFixed(1) }}</p>
              </details>
            </div>
          </dl>
        </div>
      </div>
    </section>

    <section class="card p-4">
      <div class="flex items-center justify-between">
        <h3 class="text-sm font-semibold text-white">当前装备</h3>
        <button class="rounded bg-ink-700 px-2.5 py-1.5 text-xs hover:bg-ink-600" @click="goEquipment">
          前往装备页更换
        </button>
      </div>

      <div class="mt-3 flex gap-1 rounded-lg bg-ink-800 p-1 text-xs">
        <button
          class="flex-1 rounded-md py-1.5 transition"
          :class="loadoutTab === 'combat' ? 'bg-amber-500 text-ink-950' : 'text-ink-400 hover:text-ink-200'"
          @click="loadoutTab = 'combat'"
        >
          战斗装备
        </button>
        <button
          class="flex-1 rounded-md py-1.5 transition"
          :class="loadoutTab === 'dohdol' ? 'bg-amber-500 text-ink-950' : 'text-ink-400 hover:text-ink-200'"
          @click="loadoutTab = 'dohdol'"
        >
          生产采集装备
        </button>
      </div>

      <div v-if="loadoutTab === 'combat'" class="mt-3 space-y-3">
        <div v-for="group in slotGroups" :key="group.key">
          <p class="mb-2 text-xs font-medium text-ink-400">{{ group.title }}</p>
          <div class="grid gap-2" :class="group.full ? '' : 'sm:grid-cols-2'">
            <template v-for="slot in group.slots" :key="slot.id">
              <ItemCard
                v-if="loadout[slot.id]"
                :item="loadout[slot.id]!"
                :show-actions="false"
                @select="goEquipment"
              />
              <button
                v-else
                class="rounded-lg border border-dashed border-ink-700 px-3 py-2 text-left text-[11px] text-ink-400 transition hover:border-white/40"
                @click="goEquipment"
              >
                {{ slot.name }}：空 — 前往装备页
              </button>
            </template>
          </div>
        </div>
      </div>

      <div v-else class="mt-3 grid gap-4 lg:grid-cols-2">
        <div v-for="group in dohdolGroups" :key="group.key">
          <p class="mb-2 text-xs font-medium text-ink-400">{{ group.title }}</p>
          <div class="grid gap-2 sm:grid-cols-2">
            <button
              v-for="slot in group.slots"
              :key="slot.id"
              class="rounded-lg border p-3 text-left transition hover:border-white/40"
              :class="
                dohdolLoadout[slot.id]
                  ? [rarityClass(dohdolLoadout[slot.id]!.rarity), rarityBg(dohdolLoadout[slot.id]!.rarity)]
                  : 'border-ink-700 bg-ink-800/60'
              "
              @click="goEquipment"
            >
              <div class="flex items-start gap-2">
                <ItemIcon
                  v-if="dohdolLoadout[slot.id]"
                  :base-id="dohdolLoadout[slot.id]!.baseId"
                  :rarity="dohdolLoadout[slot.id]!.rarity"
                  :size="28"
                />
                <div class="min-w-0 flex-1">
                  <p class="text-[11px] text-ink-400">{{ slot.name }}</p>
                  <template v-if="dohdolLoadout[slot.id]">
                    <p class="truncate text-sm font-medium">{{ dohdolLoadout[slot.id]!.name }}</p>
                    <div class="mt-1 space-y-0.5 text-[10px] text-ink-300">
                      <p v-for="entry in dohdolLoadout[slot.id]!.baseAttrs" :key="entry.attr">
                        {{ dohdolBonusName(entry.attr) }} +{{ entry.value }}
                        <span class="font-mono text-ink-500">{{ attrRangeLabel(entry.min, entry.max, 1) }}</span>
                      </p>
                    </div>
                    <TermBadges class="mt-1" :terms="dohdolLoadout[slot.id]!.terms" />
                  </template>
                  <p v-else class="mt-1 text-xs text-ink-400">空</p>
                </div>
              </div>
            </button>
          </div>
        </div>
      </div>

      <p class="mt-3 text-[11px] text-ink-500">
        仅展示当前已装备的栏位（只读）；点击任一栏位或右上角按钮前往装备页更换。
      </p>
    </section>

    <section class="card p-4">
      <h3 class="text-sm font-semibold text-white">技能列表与使用频率</h3>
      <p class="mt-1 text-[11px] text-ink-500">
        所有技能自动释放；公共冷却 {{ data.combat.gcdSeconds }} 秒；优先级：增益 &gt; 高伤 &gt; 普通。
      </p>

      <div class="mt-3 space-y-2">
        <!-- 绝技（招牌技能）：独立充能槽，满槽自动释放 -->
        <div v-if="signature" class="rounded-lg border border-sky-500/40 bg-sky-500/5 p-3">
          <div class="flex items-center justify-between text-xs">
            <span class="font-medium text-ink-100">绝技 · {{ signature.name }}</span>
            <span class="text-ink-400">
              充能 {{ signature.chargeSeconds }}s ·
              {{ signature.potency > 0 ? `${signature.potency}% 威力` : '辅助效果' }}
            </span>
          </div>
          <p v-if="signature.effects.length" class="mt-1 text-[10px] text-ink-400">
            {{ signature.effects.map(skillEffectLabel).join('、') }}
          </p>
          <p class="mt-1 text-[10px] text-ink-500">{{ signature.desc }}</p>
        </div>
        <div
          v-for="skill in skills"
          :key="skill.id"
          class="rounded-lg border border-ink-700 bg-ink-800/60 p-3"
        >
          <div class="flex items-center justify-between text-xs">
            <span class="font-medium text-ink-100">{{ skill.name }}</span>
            <span class="text-ink-400" :title="mpCostTip(skill)">
              CD {{ skill.cd }}s · {{ skill.potency > 0 ? `${skill.potency}% 威力` : '辅助效果' }} · MP {{ mpCostOf(skill) }}
            </span>
          </div>
          <div class="mt-2 flex items-center gap-2">
            <div class="h-1.5 flex-1 overflow-hidden rounded-full bg-ink-700">
              <div class="h-full rounded-full bg-sky-500" :style="{ width: `${castShare(skill.id)}%` }" />
            </div>
            <span class="w-24 text-right text-[10px] text-ink-400">
              使用 {{ game.state?.skillStats[skill.id] ?? 0 }} 次（{{ castShare(skill.id).toFixed(1) }}%）
            </span>
          </div>
          <p v-if="skill.effects.length" class="mt-1 text-[10px] text-ink-500">
            {{ skill.effects.map(skillEffectLabel).join('、') }}
          </p>
        </div>
      </div>
    </section>

    <section class="card p-4">
      <button class="text-sm font-semibold text-white" @click="showAllJobs = !showAllJobs">
        {{ showAllJobs ? '收起' : '查看' }}全部 {{ data.jobs.jobs.length }} 个职业
      </button>
      <div v-if="showAllJobs" class="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
        <div
          v-for="job in data.jobs.jobs"
          :key="job.id"
          class="rounded-lg border p-3"
          :class="job.id === hero.jobId ? 'border-amber-400/60 bg-amber-400/5' : 'border-ink-700 bg-ink-800/40'"
        >
          <p class="text-xs font-medium text-ink-100">
            {{ job.name }}
            <span class="ml-1 text-[10px] text-ink-500">{{ job.enName }}</span>
          </p>
          <p class="text-[10px] text-ink-400">
            {{ data.jobs.roles[job.role].name }} · 推荐主属性 {{ attrName(job.mainAttr) }}
          </p>
          <p class="mt-1 text-[10px] text-ink-500">
            {{ job.skills.map((s) => s.name).join(' / ') }}
          </p>
          <p class="text-[10px] text-sky-400/80">绝技：{{ job.signature.name }}</p>
        </div>
      </div>
    </section>
  </div>
</template>
