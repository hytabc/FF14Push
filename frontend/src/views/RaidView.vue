<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'

import { api } from '@/api'
import { toApiError } from '@/api/client'
import InfoTip from '@/components/InfoTip.vue'
import HealthBar from '@/components/HealthBar.vue'
import JobFigure from '@/components/JobFigure.vue'
import JobIcon from '@/components/JobIcon.vue'
import Modal from '@/components/Modal.vue'
import RaidChestPicker from '@/components/RaidChestPicker.vue'
import { raidSkillExplain } from '@/game/explanations'
import { useGameStore } from '@/stores/game'
import { useToastStore } from '@/stores/toast'
import type { RaidListEntry } from '@/game/types'
import { baseSlotName, formatNumber, rarityClass, rarityName } from '@/utils/format'

const game = useGameStore()
const toast = useToastStore()

const raids = ref<RaidListEntry[]>([])
const loading = ref(false)
const starting = ref<string | null>(null)
const claiming = ref(false)

const activeRaid = computed(() => game.raid)
const bosses = computed(() => game.raidBosses)
const sim = computed(() => game.sim)
const stats = computed(() => game.hero?.stats ?? null)

const phaseLabel = computed(() => {
  switch (sim.value?.phase) {
    case 'boss':
      return '战斗中'
    case 'dead':
      return '挑战失败'
    case 'cleared':
      return '已通关'
    default:
      return '待机'
  }
})

const expPct = computed(() => {
  const need = game.state?.expToNext ?? 0
  return need > 0 ? Math.min(100, ((game.hero?.exp ?? 0) / need) * 100) : 0
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

async function load() {
  loading.value = true
  try {
    const res = await api.raidList()
    raids.value = res.raids
    game.setRaidChest(res.chest?.count ?? 0, res.chest?.slots ?? [])
  } catch (e) {
    toast.push(toApiError(e).message, 'error')
  } finally {
    loading.value = false
  }
}

/** 开启高难宝箱：自选装备种类，一次性开出全部待开启宝箱。 */
async function claimChest(slot: string) {
  if (claiming.value) return
  claiming.value = true
  try {
    const res = await game.claimRaidChest(slot)
    if (!res) return
    toast.push(`开启高难宝箱 ×${res.count}（${baseSlotName(slot)}）`, 'success')
    if (res.autoSold.length) {
      toast.push(`自动出售 ${res.autoSold.length} 件装备，+${res.autoGold} 金币`, 'info')
    }
    await load()
  } finally {
    claiming.value = false
  }
}

onMounted(async () => {
  if (!game.state) await game.loadState()
  await load()
})

onUnmounted(() => {
  // 离开副本页即中止本次挑战，避免副本战斗状态溢出到其它页面
  if (game.raid) void game.stopRaid(true)
})

async function enter(raid: RaidListEntry) {
  if (!raid.eligible || starting.value) return
  starting.value = raid.id
  try {
    await game.startRaid(raid.id)
    if (!game.raid) toast.push('无法进入副本', 'error')
  } finally {
    starting.value = null
  }
}

async function leave() {
  await game.stopRaid()
  await load()
}

async function closeResult() {
  game.dismissRaidResult()
  await load()
}

function skillInfo(count: number) {
  return raidSkillExplain(count)
}

/** 英雄等级是否低于副本目标等级（低于会被等级压制）。 */
function belowTarget(raid: RaidListEntry): boolean {
  return (game.hero?.level ?? 0) < raid.challengeLevel
}

/** 当日奖励次数是否已用尽。 */
function rewardExhausted(raid: RaidListEntry): boolean {
  return raid.rewardedToday >= raid.dailyRewardClears
}
</script>

<template>
  <div class="space-y-4">
    <section class="card p-4">
      <div class="flex flex-wrap items-center gap-3">
        <h2 class="text-lg font-semibold text-white">高难副本</h2>
        <span class="text-xs text-ink-400">
          无小怪，只有 BOSS；属性固定锚定到副本「目标等级」，不再随战力变化。等级不足会被压制。BOSS 每 6 秒随机释放一个技能，双 BOSS 需同步击杀，否则存活者会狂暴。
        </span>
        <span class="ml-auto font-mono text-xs text-amber-300">当前战力 {{ formatNumber(game.state?.power ?? 0) }}</span>
      </div>
    </section>

    <!-- 待开启的高难宝箱 -->
    <RaidChestPicker
      v-if="game.raidChest.count > 0"
      :count="game.raidChest.count"
      :slots="game.raidChest.slots"
      :busy="claiming"
      @claim="claimChest"
    />

    <p class="text-xs text-ink-400">副本难度固定：BOSS 属性锚定到目标等级，不随战力变化；等级低于目标等级会受到等级压制，需先练级并配好装备。每个副本每天有奖励通关次数上限，超出后仍可挑战但不再产出奖励。</p>
    <!-- 副本列表 -->
    <section v-if="!activeRaid" class="grid gap-3 md:grid-cols-2 lg:grid-cols-3">
      <button
        v-for="raid in raids"
        :key="raid.id"
        class="card p-4 text-left transition hover:border-white/40 disabled:opacity-50"
        :class="raid.difficulty === 'hard' ? 'border-rose-500/40' : ''"
        :disabled="!raid.eligible || starting === raid.id"
        @click="enter(raid)"
      >
        <div class="flex items-center justify-between gap-2">
          <h3 class="text-sm font-semibold text-white">{{ raid.name }}</h3>
          <span class="flex shrink-0 gap-1">
            <span
              class="rounded px-2 py-0.5 text-[11px]"
              :class="
                raid.difficulty === 'hard'
                  ? 'bg-rose-500/20 text-rose-200'
                  : 'bg-ink-800 text-ink-300'
              "
            >
              {{ raid.difficulty === 'hard' ? '高难' : '普通' }}
            </span>
            <span
              class="rounded px-2 py-0.5 text-[11px]"
              :class="raid.dualBoss ? 'bg-fuchsia-500/20 text-fuchsia-200' : 'bg-ink-800 text-ink-300'"
            >
              {{ raid.dualBoss ? '双 BOSS' : '单 BOSS' }}
            </span>
          </span>
        </div>

        <p class="mt-2 text-[11px] text-ink-400">{{ raid.bossNames.join(' / ') }}</p>

        <ul class="mt-2 space-y-0.5 text-[11px] text-ink-400">
          <li>· {{ raid.difficulty === "normal" ? "推荐等级" : "需要等级" }} Lv.{{ raid.requiredLevel }}</li>
          <li :class="belowTarget(raid) ? 'text-amber-300' : ''">
            · 目标等级 Lv.{{ raid.challengeLevel }}（BOSS 固定锚定<span v-if="belowTarget(raid)">，当前会被等级压制</span>）
          </li>
          <li>· {{ raid.difficulty === "normal" ? "推荐战力" : "需要战力" }} {{ formatNumber(raid.requiredPower) }}</li>
          <li v-if="raid.difficulty === 'hard' && raid.requiresAllSlots">· 需要穿满全部装备栏位</li>
          <li v-if="raid.difficulty === 'hard'">
            · 全部装备品阶 ≥
            <span :class="rarityClass(raid.minEquipRarity)">{{ rarityName(raid.minEquipRarity) }}</span>
          </li>
          <li v-if="raid.topRarity">
            · 至少 {{ raid.topRarityCount }} 件
            <span :class="rarityClass(raid.topRarity)">{{ rarityName(raid.topRarity) }}</span> 装备
          </li>
          <li v-if="raid.difficulty === 'hard' && raid.minAncientTermsPerItem" class="text-amber-300">
            · 每件装备至少 {{ raid.minAncientTermsPerItem }} 个太古词条 🌟
          </li>
        </ul>

        <p class="mt-2 text-[11px] text-ink-500">
          首通奖励：{{ formatNumber(raid.reward.firstGold) }} 金币 + {{ formatNumber(raid.reward.firstExp) }} 经验 +
          {{ raid.reward.boxCount }} 个装备箱 ·
          重刷 {{ formatNumber(raid.reward.repeatGold) }} 金币 + {{ formatNumber(raid.reward.repeatExp) }} 经验
        </p>

        <p
          class="mt-1 text-[11px]"
          :class="rewardExhausted(raid) ? 'text-rose-300' : 'text-ink-400'"
        >
          今日奖励 {{ Math.min(raid.rewardedToday, raid.dailyRewardClears) }}/{{ raid.dailyRewardClears }}
          <template v-if="rewardExhausted(raid)">（已用尽，仍可挑战但不再产出奖励）</template>
        </p>

        <p v-if="raid.cleared" class="mt-2 text-[11px] text-emerald-300">
          已通关 {{ raid.clearCount }} 次<template v-if="raid.bestClearMs">
            · 最快 {{ (raid.bestClearMs / 1000).toFixed(1) }}s</template
          >
        </p>
        <p v-else-if="raid.blockedReason" class="mt-2 text-[11px] text-rose-300">{{ raid.blockedReason }}</p>
        <p v-else class="mt-2 text-[11px] text-amber-300">
          {{ starting === raid.id ? '进入中…' : '可挑战' }}
        </p>
      </button>

      <p v-if="!loading && !raids.length" class="col-span-full py-10 text-center text-xs text-ink-400">
        暂无副本。
      </p>
    </section>

    <!-- 副本战斗 -->
    <template v-else>
      <section class="card p-4">
        <div class="flex flex-wrap items-center gap-3">
          <div>
            <p class="text-xs text-ink-400">高难副本</p>
            <h2 class="text-lg font-semibold text-white">{{ activeRaid.name }}</h2>
          </div>
          <div class="ml-auto flex items-center gap-2">
            <span class="rounded bg-ink-800 px-2 py-1 text-xs text-ink-200">{{ phaseLabel }}</span>
            <button
              class="rounded-md bg-rose-600/80 px-3 py-1.5 text-xs font-medium text-white hover:bg-rose-500"
              @click="leave"
            >
              退出副本
            </button>
          </div>
        </div>
      </section>

      <section class="card p-4">
        <h3 class="text-sm font-semibold text-white">BOSS</h3>
        <p class="mt-1 text-[11px] text-ink-500">点击血条切换攻击目标；一方阵亡后，存活者会立刻狂暴。</p>
        <div class="mt-3 grid gap-3 md:grid-cols-2">
          <button
            v-for="(boss, index) in bosses"
            :key="boss.id"
            class="rounded-lg border p-3 text-left transition"
            :class="
              boss.isTarget
                ? 'border-amber-400/70 bg-amber-400/5'
                : 'border-ink-700 bg-ink-800/50 hover:border-white/40'
            "
            @click="game.selectRaidTarget(index)"
          >
            <div class="flex items-center justify-between gap-2">
              <span class="truncate text-sm font-medium text-ink-100">{{ boss.name }}</span>
              <span class="flex shrink-0 gap-1">
                <span v-if="boss.isTarget" class="rounded bg-amber-500/20 px-1.5 py-0.5 text-[10px] text-amber-200">
                  当前目标
                </span>
                <span v-if="boss.enraged" class="rounded bg-rose-500/20 px-1.5 py-0.5 text-[10px] text-rose-200">
                  狂暴
                </span>
              </span>
            </div>
            <div class="mb-1 flex justify-between text-[11px] text-ink-400">
              <span>生命</span>
              <span class="font-mono">
                {{ Math.max(0, Math.round(boss.hp)).toLocaleString() }} /
                {{ Math.round(boss.maxHp).toLocaleString() }}
                <span v-if="boss.shield > 0" class="text-emerald-300">（护盾 {{ Math.round(boss.shield).toLocaleString() }}）</span>
              </span>
            </div>
            <HealthBar class="mt-1" :value="boss.hp" :max="boss.maxHp" :shield="boss.shield" height="h-3" fill-class="bg-rose-500" />
            <p v-if="boss.skillNames.length" class="mt-2 text-[10px] text-fuchsia-300">
              技能池：{{ boss.skillNames.length }} 个随机释放（{{ boss.skillNames.slice(0, 3).join('、') }} 等）
              <InfoTip :title="skillInfo(boss.skillNames.length).title">
                <p v-for="(line, i) in skillInfo(boss.skillNames.length).lines" :key="i">{{ line }}</p>
              </InfoTip>
            </p>
          </button>
        </div>
      </section>

      <div class="grid gap-4 lg:grid-cols-2">
        <section class="card p-4">
          <div class="flex items-start justify-between gap-3">
            <h3 class="flex items-center gap-1.5 text-sm font-semibold text-white">
              <JobIcon :job-id="game.hero?.jobId" :size="20" />
              {{ game.hero?.name }} <span class="text-xs text-ink-400">Lv.{{ game.hero?.level }}</span>
            </h3>
            <JobFigure :job-id="game.hero?.jobId" :size="40" />
          </div>
          <div class="mt-3 space-y-2">
            <div>
              <div class="mb-1 flex justify-between text-[11px] text-ink-400">
                <span>生命</span>
                <span>
                  {{ Math.max(0, Math.round(sim?.heroHp ?? 0)) }} / {{ Math.round(stats?.maxHp ?? 0) }}
                  <span v-if="(sim?.shield ?? 0) > 0" class="text-emerald-300">（护盾 {{ Math.round(sim?.shield ?? 0) }}）</span>
                </span>
              </div>
              <HealthBar :value="sim?.heroHp ?? 0" :max="stats?.maxHp ?? 0" :shield="sim?.shield ?? 0" fill-class="bg-emerald-500" />
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
                <span>{{ game.hero?.exp }} / {{ game.state?.expToNext }}</span>
              <span v-if="game.state?.catchUpExpBonusPct" class="text-amber-300">追赶经验 +100%</span>
              </div>
              <div class="h-1.5 overflow-hidden rounded-full bg-ink-800">
                <div class="h-full rounded-full bg-amber-400 transition-all" :style="{ width: `${expPct}%` }" />
              </div>
            </div>
          </div>
          <p class="mt-3 text-[11px] text-ink-500">
            战力 {{ formatNumber(game.state?.power ?? 0) }} · 攻击 {{ Math.round(stats?.attack ?? 0) }} ·
            魔法攻击 {{ Math.round(stats?.magicAttack ?? 0) }}
          </p>
        </section>

        <section class="card p-4">
          <h3 class="text-sm font-semibold text-white">战斗日志</h3>
          <div
            class="mt-3 h-56 overflow-y-auto rounded-lg border border-ink-800 bg-ink-950/60 p-3 font-mono text-[11px] leading-relaxed"
          >
            <p v-for="entry in [...game.battleLog].reverse()" :key="entry.id" :class="logTone[entry.tone]">
              {{ entry.text }}
            </p>
            <p v-if="!game.battleLog.length" class="text-ink-400">尚无战斗记录</p>
          </div>
        </section>
      </div>
    </template>

    <!-- 结算 -->
    <Modal :open="!!game.raidResult" title="副本结算" @close="closeResult">
      <div v-if="game.raidResult" class="space-y-3 text-sm">
        <p :class="game.raidResult.cleared ? 'text-emerald-300' : 'text-rose-300'">
          {{ game.raidResult.message }}
          <span v-if="game.raidResult.firstClear" class="ml-1 text-amber-300">（首次通关）</span>
        </p>
        <p
          v-if="game.raidResult.cleared && !game.raidResult.rewardLimited && game.raidResult.remainingToday !== undefined"
          class="text-[11px] text-ink-400"
        >
          今日剩余奖励次数：{{ game.raidResult.remainingToday }}
        </p>
        <ul v-if="game.raidResult.cleared" class="space-y-1 text-xs text-ink-300">
          <li>金币：<span class="font-mono text-amber-300">+{{ formatNumber(game.raidResult.goldGained) }}</span></li>
          <li v-if="game.raidResult.expGained" class="text-emerald-300">
            经验：<span class="font-mono">+{{ formatNumber(game.raidResult.expGained) }}</span>
            <span v-if="game.raidResult.level?.levelsGained" class="ml-1 text-amber-300">
              升级 ×{{ game.raidResult.level.levelsGained }}
            </span>
          </li>
          <li>用时：<span class="font-mono">{{ (game.raidResult.fightMs / 1000).toFixed(1) }}s</span></li>
        </ul>
        <div v-if="game.raidResult.items.length" class="space-y-1 text-xs text-ink-300">
          <p>获得装备：</p>
          <p v-for="item in game.raidResult.items" :key="item.id">· {{ item.name }}</p>
        </div>
        <!-- 高难宝箱：结算时自选装备种类开启 -->
        <RaidChestPicker
          v-if="game.raidResult.cleared && game.raidChest.count > 0"
          :count="game.raidChest.count"
          :slots="game.raidChest.slots"
          :busy="claiming"
          @claim="claimChest"
        />
      </div>
      <template #footer>
        <button class="rounded-md bg-amber-500 px-3 py-2 text-sm font-medium text-ink-950" @click="closeResult">
          确定
        </button>
      </template>
    </Modal>
  </div>
</template>
