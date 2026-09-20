<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import data from '@shared/schema'
import { useGameStore } from '@/stores/game'
import { attrName, formatPercent, jobName, rarityClass, rarityName, skillEffectLabel } from '@/utils/format'

const game = useGameStore()
const showAllJobs = ref(false)

const hero = computed(() => game.hero)
const stats = computed(() => hero.value?.stats ?? null)

const skills = computed(() => {
  const jobId = hero.value?.jobId ?? 'adventurer'
  if (jobId === 'adventurer') {
    return [{ id: 'basicAttack', name: '普攻', cd: data.combat.basicAttackCd as number, potency: 100, mpCost: 0, effects: [], damageType: 'physical', target: 'single', priority: 3 }]
  }
  return data.jobById[jobId]?.skills ?? []
})

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

onMounted(async () => {
  if (!game.state) await game.loadState()
})

function castShare(skillId: string) {
  if (!totalCasts.value) return 0
  return ((game.state?.skillStats[skillId] ?? 0) / totalCasts.value) * 100
}
</script>

<template>
  <div v-if="hero" class="space-y-4">
    <section class="card p-4">
      <div class="flex flex-wrap items-start gap-4">
        <div class="flex-1">
          <div class="flex items-center gap-2">
            <h2 class="text-lg font-semibold text-white">{{ hero.name }}</h2>
            <span class="rounded bg-ink-800 px-2 py-0.5 text-[11px] text-sky-300">
              {{ jobName(hero.jobId) }}
            </span>
            <span class="rounded bg-ink-800 px-2 py-0.5 text-[11px]" :class="rarityClass(hero.talent)">
              {{ rarityName(hero.talent) }}资质
            </span>
            <span class="rounded bg-ink-800 px-2 py-0.5 text-[11px] text-ink-300">
              {{ attrBiasLabel[hero.attrBias] }}
            </span>
          </div>

          <div class="mt-3">
            <div class="mb-1 flex justify-between text-[11px] text-ink-400">
              <span>等级 {{ hero.level }} / {{ data.heroes.levelCap }}</span>
              <span>{{ hero.exp }} / {{ game.state?.expToNext }} 经验</span>
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
              <p class="text-[10px] text-ink-400">力量<span v-if="hero.ancientAttr === 'str'">🌟</span></p>
              <p class="font-mono text-lg text-rose-300">{{ hero.strength }}</p>
            </div>
            <div
              class="rounded-lg border p-2"
              :class="hero.ancientAttr === 'dex' ? 'border-term-ancient bg-term-ancient/10' : 'border-ink-700 bg-ink-800/60'"
            >
              <p class="text-[10px] text-ink-400">敏捷<span v-if="hero.ancientAttr === 'dex'">🌟</span></p>
              <p class="font-mono text-lg text-emerald-300">{{ hero.agility }}</p>
            </div>
            <div
              class="rounded-lg border p-2"
              :class="hero.ancientAttr === 'int' ? 'border-term-ancient bg-term-ancient/10' : 'border-ink-700 bg-ink-800/60'"
            >
              <p class="text-[10px] text-ink-400">智力<span v-if="hero.ancientAttr === 'int'">🌟</span></p>
              <p class="font-mono text-lg text-sky-300">{{ hero.intellect }}</p>
            </div>
          </div>
          <p class="mt-2 text-[11px] text-ink-500">
            英雄主属性对应装备三维收益 100%，非主属性 50%；职业推荐主属性为
            <b class="text-ink-300">{{ recommendAttr ? attrName(recommendAttr) : '无（冒险者）' }}</b>。
          </p>
        </div>

        <div class="w-full sm:w-64">
          <h3 class="text-xs font-semibold text-ink-300">面板属性</h3>
          <dl class="mt-2 space-y-1 text-[11px]">
            <div v-for="row in [
              ['生命值', stats?.maxHp, ''],
              ['魔法值', stats?.maxMp, ''],
              ['物理攻击', stats?.attack, ''],
              ['魔法攻击', stats?.magicAttack, ''],
              ['物理防御', stats?.physDef, ''],
              ['魔法防御', stats?.magicDef, ''],
              ['暴击值', stats?.critValue, ''],
              ['直击值', stats?.dhValue, ''],
              ['信念值', stats?.detValue, ''],
            ]" :key="String(row[0])" class="flex justify-between">
              <dt class="text-ink-400">{{ row[0] }}</dt>
              <dd class="font-mono text-ink-200">{{ Math.round(Number(row[1] ?? 0)) }}</dd>
            </div>
            <div class="flex justify-between"><dt class="text-ink-400">暴击率</dt><dd class="font-mono text-sky-300">{{ formatPercent(stats?.critRatePct ?? 0) }}</dd></div>
            <div class="flex justify-between"><dt class="text-ink-400">暴击伤害</dt><dd class="font-mono text-sky-300">{{ formatPercent(stats?.critDamagePct ?? 0, 0) }}</dd></div>
            <div class="flex justify-between"><dt class="text-ink-400">直击率</dt><dd class="font-mono text-sky-300">{{ formatPercent(stats?.dhRatePct ?? 0) }}</dd></div>
            <div class="flex justify-between"><dt class="text-ink-400">信念增伤</dt><dd class="font-mono text-sky-300">{{ formatPercent(stats?.detBonusPct ?? 0) }}</dd></div>
            <div class="flex justify-between"><dt class="text-ink-400">闪避</dt><dd class="font-mono text-ink-200">{{ formatPercent(stats?.dodgePct ?? 0) }}</dd></div>
            <div class="flex justify-between"><dt class="text-ink-400">攻击速度</dt><dd class="font-mono text-ink-200">{{ formatPercent(stats?.attackSpeedPct ?? 0) }}</dd></div>
            <div class="flex justify-between"><dt class="text-ink-400">技能急速</dt><dd class="font-mono text-ink-200">{{ formatPercent(stats?.hastePct ?? 0) }}</dd></div>
            <div class="flex justify-between"><dt class="text-ink-400">战力</dt><dd class="font-mono text-amber-300">{{ game.state?.power }}</dd></div>
          </dl>
        </div>
      </div>
    </section>

    <section class="card p-4">
      <h3 class="text-sm font-semibold text-white">技能列表与使用频率</h3>
      <p class="mt-1 text-[11px] text-ink-500">
        所有技能自动释放；公共冷却 {{ data.combat.gcdSeconds }} 秒；优先级：增益 &gt; 高伤 &gt; 普通。
      </p>

      <div class="mt-3 space-y-2">
        <div
          v-for="skill in skills"
          :key="skill.id"
          class="rounded-lg border border-ink-700 bg-ink-800/60 p-3"
        >
          <div class="flex items-center justify-between text-xs">
            <span class="font-medium text-ink-100">{{ skill.name }}</span>
            <span class="text-ink-400">
              CD {{ skill.cd }}s · {{ skill.potency > 0 ? `${skill.potency}% 威力` : '辅助效果' }} · MP {{ skill.mpCost }}
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
        </div>
      </div>
    </section>
  </div>
</template>
