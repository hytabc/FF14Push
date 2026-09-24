<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'

import data from '@shared/schema'
import ChestReel from '@/components/ChestReel.vue'
import InfoTip from '@/components/InfoTip.vue'
import ItemIcon from '@/components/ItemIcon.vue'
import Modal from '@/components/Modal.vue'
import { chestLuckExplain, chestRarityExplain, pityExplain } from '@/game/explanations'
import { useGameStore } from '@/stores/game'
import type { Item, RarityId } from '@/game/types'
import { attrName, attrSuffix, formatNumber, rarityBg, rarityClass, rarityName } from '@/utils/format'

const game = useGameStore()

const chests = data.chests.chests
const LEVEL_BANDS = data.chests.levelBands
const DRAW_COUNTS = data.chests.drawCounts
const busy = ref<string | null>(null)
const unlocking = ref<number | null>(null)
/** 抽奖展示物品：包含被自动出售的物品（结果页再做出售结算展示）。 */
type RevealItem = Item & { autoSold?: boolean; price?: number }
const revealItems = ref<RevealItem[]>([])
const autoGold = ref(0)
const showReveal = ref(false)
const phase = ref<'spinning' | 'result'>('result')
const spinKey = ref(0)
const lastDraw = ref<{ chestId: string; count: number } | null>(null)

/** 开箱转盘节奏（毫秒）：与 ChestReel 保持一致。 */
const REEL_DURATION = 2600
const REEL_STAGGER = 120
/** 大数量（>10）网格波浪揭晓的错峰上限与总时长。 */
const GRID_WAVE_MS = 1200

const reducedMotion =
  typeof window !== 'undefined' && !!window.matchMedia?.('(prefers-reduced-motion: reduce)').matches

let revealTimer = 0

/**
 * 大批量揭晓的分帧挂载。
 *
 * 50 / 100 连抽一次要渲染上百个卡片，若在单帧内全部挂载会出现长时间的主线程任务。
 * 这里每帧只挂一批（约 0.1s 内补齐），最终展示的条目一个不少。
 */
const MOUNT_CHUNK = 24
/** 兜底时长（毫秒）：rAF 被后台标签页暂停时也要保证最终全部挂载。 */
const MOUNT_BACKSTOP_MS = 600
const mountedCount = ref(0)
let mountRaf = 0
let mountBackstop = 0

function stopMountRamp() {
  if (mountRaf) cancelAnimationFrame(mountRaf)
  if (mountBackstop) window.clearTimeout(mountBackstop)
  mountRaf = 0
  mountBackstop = 0
}

/** 先挂第一批，再逐帧补齐到 `total`；同时挂一个兜底定时器保证一定会挂满。 */
function rampMount(total: number) {
  stopMountRamp()
  mountedCount.value = Math.min(MOUNT_CHUNK, total)
  if (mountedCount.value >= total) return
  const step = () => {
    mountedCount.value = Math.min(total, mountedCount.value + MOUNT_CHUNK)
    mountRaf = mountedCount.value < total ? requestAnimationFrame(step) : 0
  }
  mountRaf = requestAnimationFrame(step)
  mountBackstop = window.setTimeout(() => {
    mountedCount.value = total
    stopMountRamp()
  }, MOUNT_BACKSTOP_MS)
}

/** 当前已挂载的揭晓项（分批增长，最终等于 revealItems）。 */
const visibleReveal = computed(() => revealItems.value.slice(0, mountedCount.value))

/** 本次抽奖的最高品阶（模板里被引用两次，用 computed 避免重复遍历）。 */
const bestRarityId = computed<RarityId>(() => {
  const order = data.rarities.order
  let best = -1
  for (const item of revealItems.value) {
    best = Math.max(best, order.indexOf(item.rarity))
  }
  return best >= 0 ? order[best] : 'common'
})

/** 抽箱档位解锁依据：角色库（名册）内最高英雄等级，而非当前上场英雄。 */
const rosterLevel = computed(() =>
  Math.max(1, game.hero?.level ?? 1, ...(game.state?.heroes ?? []).map((h) => h.level)),
)
/** 已解锁的等级档位（角色库最高等级达到即可选）。 */
const unlockedBands = computed(() => LEVEL_BANDS.filter((b) => b.level <= rosterLevel.value))
const band = ref<number>(LEVEL_BANDS[0].level)
const bandDef = computed(() => LEVEL_BANDS.find((b) => b.level === band.value) ?? LEVEL_BANDS[0])
/** 抽箱品阶幸运（服务端结算的全部来源：通关地区 / 装备品阶幸运 / 料理秘药 / 远征·高难通关 / 彩蛋）。 */
const chestLuck = computed(() => game.state?.chestRarityLuck ?? null)
const luck = computed(() => chestLuck.value?.luck ?? 0)

const PITY = data.chests.pity

/** 上一次抽的箱子定义（「继续抽奖」复用其价格/档位）。 */
const lastChest = computed(
  () => chests.find((c) => c.id === lastDraw.value?.chestId) ?? null,
)

const modalTitle = computed(() => (phase.value === 'spinning' ? '开箱中…' : '抽取结果'))

function pityOf(chestId: string) {
  return game.state?.pity[chestId] ?? { sinceRare: 0, sinceEpic: 0, sinceLegendary: 0 }
}

function pityPct(chestId: string, count: number) {
  const p = pityOf(chestId)
  const current = count === 10 ? p.sinceRare : count === 50 ? p.sinceEpic : p.sinceLegendary
  return Math.min(100, (current / count) * 100)
}

/** 单个箱子在当前档位下的实际单价（与服务端同一公式）。 */
function unitPrice(chest: { price: number }): number {
  return Math.floor(chest.price * bandDef.value.priceMultiplier)
}

/** 当前品阶概率分布（含进度爆率加成）。 */
function odds(chest: { tier: string }) {
  const base = data.rarities.order.map((r) => data.rarities.byId[r].boxChance[chest.tier as 'normal' | 'advanced'])
  const weights = data.rarities.order.map((_, i) => base[i] * (1 + luck.value * i))
  const total = weights.reduce((sum, w) => sum + w, 0) || 1
  return data.rarities.order.map((r, i) => ({ rarity: r, chance: weights[i] / total }))
}

const canAfford = computed(() => (price: number, count: number) => game.gold >= price * count)

/** 已解锁的连抽档位：unlockCost=0 的恒可用；其余看账号解锁记录（账号级，所有箱子通用）。 */
const unlockedCounts = computed(
  () =>
    new Set<number>([
      ...DRAW_COUNTS.filter((d) => d.unlockCost === 0).map((d) => d.count),
      ...(game.state?.settings.chestUnlocks ?? []),
    ]),
)
/** 待解锁（需一次性金币）的连抽档位。 */
const lockedCounts = computed(() => DRAW_COUNTS.filter((d) => !unlockedCounts.value.has(d.count)))
/** 箱子卡片上展示的连抽按钮：单抽/十连恒显示，高连抽解锁后显示。 */
const cardCounts = computed(() =>
  DRAW_COUNTS.filter((d) => d.count <= 10 || unlockedCounts.value.has(d.count)),
)
/** 本次抽奖中被自动出售的件数。 */
const soldCount = computed(() => revealItems.value.filter((i) => i.autoSold).length)

function countLabel(count: number): string {
  return count === 1 ? '单抽' : count === 10 ? '十连' : `${count} 连`
}

/** 大数量网格波浪揭晓的单件错峰（毫秒），总量封顶 GRID_WAVE_MS。 */
function gridStagger(count: number): number {
  return count > 0 ? Math.min(30, GRID_WAVE_MS / count) : 0
}

async function unlock(count: number) {
  if (unlocking.value) return
  unlocking.value = count
  try {
    await game.unlockChestDraw(count)
  } finally {
    unlocking.value = null
  }
}

const luckExplain = computed(() => chestLuckExplain(chestLuck.value))
const pityExplanation = pityExplain()

function rarityExplain(chest: { tier: string }) {
  return chestRarityExplain(chest.tier, luck.value)
}

onMounted(async () => {
  if (!game.state) await game.loadState()
  // 默认选中已解锁的最高档位
  band.value = unlockedBands.value[unlockedBands.value.length - 1]?.level ?? LEVEL_BANDS[0].level
})

onBeforeUnmount(() => {
  window.clearTimeout(revealTimer)
  stopMountRamp()
})

function isUnlocked(level: number): boolean {
  return rosterLevel.value >= level
}

function canContinueDraw(): boolean {
  if (busy.value || !lastChest.value || !lastDraw.value) return false
  return canAfford.value(unitPrice(lastChest.value), lastDraw.value.count)
}

function closeReveal() {
  window.clearTimeout(revealTimer)
  stopMountRamp()
  showReveal.value = false
  phase.value = 'result'
}

async function draw(chestId: string, count: number) {
  if (busy.value) return
  busy.value = chestId
  window.clearTimeout(revealTimer)
  try {
    const res = await game.openChest(chestId, count, band.value)
    if (!res) return
    // 被自动出售的物品也并入展示：动画照常播放，出售结算在结果页展示。
    revealItems.value = [...res.items, ...res.autoSold]
    autoGold.value = res.autoGold
    lastDraw.value = { chestId, count }
    spinKey.value += 1
    showReveal.value = true
    rampMount(revealItems.value.length)
    if (reducedMotion || revealItems.value.length === 0) {
      phase.value = 'result'
    } else {
      phase.value = 'spinning'
      const len = revealItems.value.length
      const total =
        len <= 10
          ? (len - 1) * REEL_STAGGER + REEL_DURATION + 250
          : len * gridStagger(len) + 300
      revealTimer = window.setTimeout(() => {
        // 结果列表与揭晓网格是两棵不同的 DOM 树，各自分批挂载（信息量不变）。
        rampMount(revealItems.value.length)
        phase.value = 'result'
      }, total)
    }
  } finally {
    busy.value = null
  }
}
</script>

<template>
  <div class="space-y-4">
    <section class="card p-4">
      <div class="flex items-center justify-between">
        <h2 class="text-lg font-semibold text-white">抽箱</h2>
        <span class="font-mono text-sm text-amber-300">💰 {{ game.gold.toLocaleString() }}</span>
      </div>
      <p class="mt-1 text-xs text-ink-400">
        金币仅通过打怪掉落获得。每开启 10 / 50 / 200 个同类型箱子，必出稀有 / 史诗 / 传说及以上品质。
        品阶幸运
        <b class="text-emerald-300">{{ luck.toFixed(3) }} / {{ (chestLuck?.luckMax ?? 1).toFixed(2) }}</b>
        （通关地区 / 装备品阶幸运 / 料理秘药 / 远征·高难通关，仅提升装备品阶，不影响金币）。
        <InfoTip :title="luckExplain.title">
          <p v-for="(line, i) in luckExplain.lines" :key="i">{{ line }}</p>
        </InfoTip>
      </p>
    </section>

    <section class="card p-4">
      <div class="flex flex-wrap items-center gap-2">
        <h3 class="text-sm font-semibold text-white">抽取档位</h3>
        <span class="text-[11px] text-ink-400">
          箱子内容按所选档位生成（装备无穿戴等级限制），档位越高价格越高；需角色库最高等级达到该档位才可选择，当前最高 Lv.{{ rosterLevel }}。
        </span>
      </div>
      <div class="mt-3 flex flex-wrap gap-2">
        <button
          v-for="b in LEVEL_BANDS"
          :key="b.level"
          class="rounded-md border px-3 py-1.5 text-xs transition"
          :class="
            !isUnlocked(b.level)
              ? 'cursor-not-allowed border-ink-700 text-ink-400'
              : band === b.level
                ? 'border-amber-400 bg-amber-400/15 text-amber-200'
                : 'border-ink-600 text-ink-300 hover:border-ink-400'
          "
          :disabled="!isUnlocked(b.level)"
          :title="isUnlocked(b.level) ? `抽取 ${b.level} 级档位` : `需要角色库最高等级 ${b.level}`"
          @click="band = b.level"
        >
          <span v-if="!isUnlocked(b.level)">🔒 </span>{{ b.level }} 级
        </button>
      </div>
    </section>

    <section v-if="lockedCounts.length" class="card p-4">
      <div class="flex flex-wrap items-center gap-2">
        <h3 class="text-sm font-semibold text-white">连抽解锁</h3>
        <span class="text-[11px] text-ink-400">
          用金币一次性解锁高连抽档位，解锁后所有箱子通用（账号级，永久有效）。
        </span>
      </div>
      <div class="mt-3 grid gap-2 sm:grid-cols-2">
        <div
          v-for="d in lockedCounts"
          :key="d.count"
          class="flex items-center justify-between gap-3 rounded-md border border-ink-700 px-3 py-2"
        >
          <div>
            <p class="text-sm text-white">{{ d.count }} 连抽</p>
            <p class="text-[11px] text-ink-400">解锁价 {{ formatNumber(d.unlockCost) }} 金币</p>
          </div>
          <button
            class="rounded-md bg-amber-500 px-3 py-1.5 text-xs font-medium text-ink-950 hover:bg-amber-400 disabled:opacity-40"
            :disabled="game.gold < d.unlockCost || unlocking === d.count"
            :title="game.gold < d.unlockCost ? '金币不足' : `解锁 ${d.count} 连抽`"
            @click="unlock(d.count)"
          >
            {{ unlocking === d.count ? '解锁中…' : '解锁' }}
          </button>
        </div>
      </div>
    </section>

    <section data-tutorial="chest" class="grid gap-3 md:grid-cols-2">
      <article v-for="chest in chests" :key="chest.id" class="card p-4">
        <div class="flex items-start justify-between">
          <div>
            <h3 class="text-sm font-semibold text-white">{{ chest.name }}</h3>
            <p class="text-[11px] text-ink-400">
              {{ { weapon: '武器', armor: '防具', accessory: '饰品' }[chest.category] }} ·
              {{ chest.tier === 'advanced' ? '高级（品阶概率提升）' : '普通' }} · {{ band }} 级档位
            </p>
          </div>
          <span class="rounded bg-ink-800 px-2 py-1 font-mono text-xs text-amber-300">
            {{ formatNumber(unitPrice(chest)) }}
          </span>
        </div>

        <div class="mt-3 space-y-2">
          <p class="text-[10px] uppercase tracking-wide text-ink-500">
            品阶概率
            <InfoTip :title="rarityExplain(chest).title">
              <p v-for="(line, i) in rarityExplain(chest).lines" :key="i">{{ line }}</p>
            </InfoTip>
          </p>
          <div class="flex h-2 overflow-hidden rounded-full bg-ink-800">
            <div
              v-for="o in odds(chest)"
              :key="o.rarity"
              :style="{ width: `${o.chance * 100}%`, backgroundColor: data.rarities.byId[o.rarity].hex }"
              :title="`${rarityName(o.rarity)} ${(o.chance * 100).toFixed(1)}%`"
            />
          </div>
          <div class="flex flex-wrap gap-x-3 gap-y-1 text-[10px] text-ink-400">
            <span v-for="o in odds(chest)" :key="o.rarity" :class="rarityClass(o.rarity)">
              {{ rarityName(o.rarity) }} {{ (o.chance * 100).toFixed(o.chance < 0.01 ? 2 : 1) }}%
            </span>
          </div>
        </div>

        <div class="mt-3 space-y-1.5">
          <p class="text-[10px] uppercase tracking-wide text-ink-500">
            保底进度
            <InfoTip :title="pityExplanation.title">
              <p v-for="(line, i) in pityExplanation.lines" :key="i">{{ line }}</p>
            </InfoTip>
          </p>
          <div v-for="p in PITY" :key="p.count">
            <div class="flex justify-between text-[10px] text-ink-400">
              <span>{{ p.count }} 抽保底 · {{ rarityName(p.minRarity) }}+</span>
              <span>{{ p.count === 10 ? pityOf(chest.id).sinceRare : p.count === 50 ? pityOf(chest.id).sinceEpic : pityOf(chest.id).sinceLegendary }} / {{ p.count }}</span>
            </div>
            <div class="h-1.5 overflow-hidden rounded-full bg-ink-800">
              <div class="h-full rounded-full bg-amber-400" :style="{ width: `${pityPct(chest.id, p.count)}%` }" />
            </div>
          </div>
        </div>

        <div class="mt-4 grid grid-cols-2 gap-2">
          <button
            v-for="d in cardCounts"
            :key="d.count"
            class="rounded-md py-2 text-xs disabled:opacity-40"
            :class="
              d.count >= 10
                ? 'bg-amber-500 font-medium text-ink-950 hover:bg-amber-400'
                : 'bg-ink-700 hover:bg-ink-600'
            "
            :disabled="!canAfford(unitPrice(chest), d.count) || busy === chest.id"
            @click="draw(chest.id, d.count)"
          >
            {{ countLabel(d.count) }} · {{ formatNumber(unitPrice(chest) * d.count) }}
          </button>
        </div>
      </article>
    </section>

    <Modal
      :open="showReveal"
      :title="modalTitle"
      max-width="max-w-4xl"
      :blur="false"
      @close="closeReveal()"
    >
      <!-- 开箱动画：单抽 1 个滚轮，十连 10 个并行滚轮，50/100 连网格波浪揭晓 -->
      <div v-if="phase === 'spinning'" class="space-y-3">
        <div v-if="revealItems.length === 1" class="mx-auto w-full max-w-xl">
          <ChestReel
            :key="spinKey"
            :item="revealItems[0]"
            :category="revealItems[0].category"
            :tier="lastChest?.tier ?? 'normal'"
            :duration="REEL_DURATION"
          />
        </div>
        <div v-else-if="revealItems.length <= 10" class="grid grid-cols-2 gap-2 sm:grid-cols-5">
          <ChestReel
            v-for="(item, index) in visibleReveal"
            :key="`${spinKey}-${index}`"
            :item="item"
            :category="item.category"
            :tier="lastChest?.tier ?? 'normal'"
            :duration="REEL_DURATION"
            :delay="index * REEL_STAGGER"
            :slot-width="48"
            compact
          />
        </div>
        <div
          v-else
          class="grid max-h-[60vh] grid-cols-3 gap-2 overflow-y-auto pr-1 sm:grid-cols-5 lg:grid-cols-8"
        >
          <div
            v-for="(item, index) in visibleReveal"
            :key="`spin-${index}`"
            class="gallery-cell animate-rise rounded-lg border p-1.5"
            :class="[rarityClass(item.rarity), rarityBg(item.rarity)]"
            :style="{ animationDelay: `${index * gridStagger(revealItems.length)}ms` }"
          >
            <div class="flex flex-col items-center gap-1">
              <ItemIcon :base-id="item.baseId" :rarity="item.rarity" :size="32" variant="lite" />
              <span class="w-full truncate text-center text-[9px] text-ink-200">{{ item.name }}</span>
            </div>
          </div>
        </div>
      </div>

      <!-- 详细结果 -->
      <div v-else class="space-y-3">
        <div class="flex items-center gap-2 text-xs">
          <span class="text-ink-400">最高品阶：</span>
          <span class="font-semibold" :class="rarityClass(bestRarityId)">
            {{ rarityName(bestRarityId) }}
          </span>
          <span class="ml-auto text-ink-400">共 {{ revealItems.length }} 件</span>
        </div>
        <p v-if="soldCount" class="text-[11px] text-amber-300">
          自动出售 {{ soldCount }} 件，+{{ formatNumber(autoGold) }} 金币（已结算，未入背包）
        </p>

        <div class="grid max-h-[55vh] gap-2 overflow-y-auto pr-1 sm:grid-cols-2 lg:grid-cols-3">
          <div
            v-for="(item, index) in visibleReveal"
            :key="`result-${index}`"
            class="gallery-cell animate-rise rounded-lg border p-3"
            :class="[rarityClass(item.rarity), rarityBg(item.rarity), item.autoSold ? 'opacity-75' : '']"
            :style="{ animationDelay: `${Math.min(index * 45, 400)}ms` }"
          >
            <div class="flex items-center gap-2">
              <ItemIcon :base-id="item.baseId" :rarity="item.rarity" :size="36" variant="lite" />
              <div class="min-w-0">
                <p class="truncate text-xs font-medium">{{ item.name }}</p>
                <p class="text-[10px] text-ink-400">{{ rarityName(item.rarity) }} · Lv.{{ item.levelReq }}</p>
              </div>
            </div>
            <p
              v-if="item.autoSold"
              class="mt-1 inline-block rounded bg-amber-500/20 px-1.5 py-0.5 text-[10px] text-amber-200"
            >
              已自动出售 +{{ formatNumber(item.price ?? 0) }}
            </p>
            <p v-for="entry in item.subAttrs" :key="entry.attr" class="text-[10px] text-ink-300">
              {{ attrName(entry.attr) }} +{{ entry.value.toFixed(2) }}{{ attrSuffix(entry.attr) }}
            </p>
          </div>
        </div>
      </div>

      <template #footer>
        <template v-if="phase === 'spinning'">
          <span class="mr-auto self-center text-xs text-ink-400">开箱中，请稍候…</span>
        </template>
        <template v-else>
          <button
            v-if="lastDraw"
            class="mr-auto rounded-md border border-amber-500/60 px-3 py-2 text-sm text-amber-200 hover:bg-amber-500/15 disabled:opacity-50"
            :disabled="!canContinueDraw()"
            :title="canContinueDraw() ? '' : '金币不足'"
            @click="lastChest && draw(lastDraw.chestId, lastDraw.count)"
          >
            继续抽奖 · {{ lastChest ? formatNumber(unitPrice(lastChest) * lastDraw.count) : '' }}
          </button>
          <button class="rounded-md bg-ink-700 px-3 py-2 text-sm hover:bg-ink-600" @click="closeReveal()">
            关闭
          </button>
          <RouterLink
            to="/inventory"
            class="rounded-md bg-amber-500 px-3 py-2 text-sm font-medium text-ink-950 hover:bg-amber-400"
            @click="closeReveal()"
          >
            去背包查看
          </RouterLink>
        </template>
      </template>
    </Modal>
  </div>
</template>
