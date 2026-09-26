<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'

import data from '@shared/schema'
import ActivityLog from '@/components/ActivityLog.vue'
import { useConfirmStore } from '@/stores/confirm'
import { useIshgardStore } from '@/stores/ishgard'
import type { IshgardProductView, IshgardToolView } from '@/game/types'
import { formatDuration, formatNumber } from '@/utils/format'

const store = useIshgardStore()
const confirm = useConfirmStore()

const TABS = [
  { id: 'overview', label: '概览' },
  { id: 'gather', label: '采集' },
  { id: 'fish', label: '钓鱼' },
  { id: 'produce', label: '生产' },
  { id: 'submit', label: '提交' },
  { id: 'tool', label: '天钢装备' },
  { id: 'board', label: '积分榜' },
] as const
type TabId = (typeof TABS)[number]['id']
const tab = ref<TabId>('overview')

const state = computed(() => store.state)
const stage = computed(() => state.value?.stage ?? 1)
const myPoints = computed(() => state.value?.myPoints ?? 0)

const stagePct = computed(() => {
  const s = state.value
  if (!s || s.stageTarget <= 0) return 0
  return Math.min(100, Math.round((s.stagePoints / s.stageTarget) * 100))
})

// 称号窗口倒计时
const nowMs = ref(Date.now())
let clockTimer: number | null = null
onMounted(async () => {
  clockTimer = window.setInterval(() => (nowMs.value = Date.now()), 1000)
  await store.load()
})
onUnmounted(() => {
  if (clockTimer !== null) window.clearInterval(clockTimer)
  // 离开页面停止当前会话（保留已结算产出，不做离线收益）
  void store.stop(true)
})

const titleRemaining = computed(() => {
  const s = state.value
  if (!s || !s.titlePeriodEndsAt) return '—'
  return formatDuration(Math.max(0, s.titlePeriodEndsAt * 1000 - nowMs.value))
})

function jobName(id: string): string {
  return data.dohdolJobById[id]?.name ?? id
}

// ------------------------------------------------------------------ 生产
const produceCount = ref<number | null>(null)
const produceDisabled = computed(() => store.isRunning && store.mode !== 'produce')

function maxCraftable(product: IshgardProductView): number {
  if (!product.inputs.length) return 0
  return Math.min(...product.inputs.map((i) => Math.floor(i.have / Math.max(1, i.count))))
}

async function startProduce(product: IshgardProductView) {
  await store.startProduce(product.jobId, product.itemId, produceCount.value)
}

// ------------------------------------------------------------------ 提交
const submitting = ref<string | null>(null)
async function submitAll(entry: { itemId: string; count: number; points: number }) {
  if (entry.count <= 0) return
  submitting.value = entry.itemId
  try {
    await store.submit(entry.itemId, entry.count)
  } finally {
    submitting.value = null
  }
}

// ------------------------------------------------------------------ 背包（仅重建专属物资，支持按阶段筛选）
const bagStage = ref<'current' | 'all' | number>('current')
const bagRows = computed(() => {
  const rows = state.value?.bag ?? []
  const filter = bagStage.value
  if (filter === 'all') return rows
  if (filter === 'current') return rows.filter((r) => r.stage === stage.value)
  return rows.filter((r) => r.stage === filter)
})
const bagStages = computed(() => [...new Set((state.value?.bag ?? []).map((r) => r.stage))].sort())

async function sellRow(itemId: string, count: number, name: string) {
  const ok = await confirm.ask({
    title: '确认出售',
    message: `出售「${name}」×${count}。过期物资无法再用于重建，出售后不可恢复。`,
    confirmLabel: '确认出售',
    tone: 'danger',
  })
  if (ok) await store.sell(itemId, count)
}

// ------------------------------------------------------------------ 装备
const KINDS: Array<{ kind: 'doh' | 'dol'; label: string }> = [
  { kind: 'doh', label: '生产主手' },
  { kind: 'dol', label: '采集主手' },
]
const pinkByName = (tool: IshgardToolView): string => tool.pink?.desc ?? ''

async function claim(kind: 'doh' | 'dol') {
  try {
    await store.claimTool(kind)
  } catch (error) {
    // 错误提示由 api 层统一处理，这里仅吞掉避免未处理的 rejection
    void error
  }
}
async function upgrade(kind: 'doh' | 'dol') {
  try {
    await store.upgradeTool(kind)
  } catch (error) {
    void error
  }
}
async function reroll(kind: 'doh' | 'dol') {
  try {
    await store.rerollPink(kind)
  } catch (error) {
    void error
  }
}

// ------------------------------------------------------------------ 积分榜
const board = ref<Awaited<ReturnType<typeof store.loadLeaderboard>> | null>(null)
async function loadBoard(page = 1) {
  board.value = await store.loadLeaderboard(page)
}
</script>

<template>
  <div class="space-y-4">
    <!-- 顶栏：阶段进度 + 我的积分 + 称号 -->
    <section class="card p-4">
      <div class="flex flex-wrap items-center gap-3">
        <h1 class="text-lg font-semibold text-ink-100">重建伊修加德</h1>
        <span class="rounded border border-amber-400/60 bg-amber-500/20 px-2 py-0.5 text-xs text-amber-100">
          {{ state?.stageName ?? '第 1 次重建' }}（第 {{ state?.round ?? 1 }} 轮）
        </span>
        <span class="text-xs text-ink-400">全服活动 · 所有玩家均可参与</span>
      </div>

      <div v-if="state" class="mt-3 space-y-1">
        <div class="flex items-center justify-between text-xs text-ink-300">
          <span>本阶段全服进度</span>
          <span>{{ formatNumber(state.stagePoints) }} / {{ formatNumber(state.stageTarget) }}</span>
        </div>
        <div class="h-2.5 w-full overflow-hidden rounded-full bg-ink-800">
          <div class="h-full rounded-full bg-gradient-to-r from-sky-500 to-amber-400" :style="{ width: stagePct + '%' }" />
        </div>
        <p class="text-[11px] text-ink-400">
          全服提交积分填满进度条即进入下一次重建（共 {{ state.stageCount }} 次）；每次重建的物资互不通用。
        </p>
      </div>

      <div class="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
        <div class="rounded-lg border border-ink-700/60 bg-ink-900/40 p-3">
          <p class="text-[11px] text-ink-400">我的累计积分</p>
          <p class="text-base font-semibold text-ink-100">{{ formatNumber(myPoints) }}</p>
        </div>
        <div class="rounded-lg border border-ink-700/60 bg-ink-900/40 p-3">
          <p class="text-[11px] text-ink-400">我的排名</p>
          <p class="text-base font-semibold text-ink-100">
            {{ state?.myRank?.rank ? '第 ' + state.myRank.rank + ' 名' : '未上榜' }}
          </p>
        </div>
        <div class="rounded-lg border border-ink-700/60 bg-ink-900/40 p-3">
          <p class="text-[11px] text-ink-400">天穹圣人 · 下次结算</p>
          <p class="text-sm font-semibold text-amber-100">
            {{ state?.saint ? state.saint.nickname : '—' }} · {{ titleRemaining }}
          </p>
        </div>
        <div class="rounded-lg border border-ink-700/60 bg-ink-900/40 p-3">
          <p class="text-[11px] text-ink-400">天穹圣徒</p>
          <p class="text-sm font-semibold text-ink-100">{{ state?.apostle ? state.apostle.nickname : '—' }}</p>
        </div>
      </div>
      <p class="mt-2 text-[11px] text-ink-400">
        积分榜前两名每 6 小时获得「天穹圣人 / 天穹圣徒」，同一称号全服仅一人持有、可被超越夺走。
      </p>
    </section>

    <!-- 二级页面切换 -->
    <div class="hidden md:flex flex-wrap gap-1">
      <button
        v-for="item in TABS"
        :key="item.id"
        class="rounded-md px-3 py-1.5 text-sm"
        :class="tab === item.id ? 'bg-amber-500/20 text-amber-100' : 'text-ink-300 hover:bg-ink-800/60'"
        @click="tab = item.id; if (item.id === 'board') void loadBoard(1)"
      >
        {{ item.label }}
      </button>
    </div>
    <select v-model="tab" class="md:hidden w-full rounded-md border border-ink-700 bg-ink-900 px-3 py-2 text-sm" @change="tab === 'board' && loadBoard(1)">
      <option v-for="item in TABS" :key="item.id" :value="item.id">{{ item.label }}</option>
    </select>

    <!-- 概览 -->
    <template v-if="tab === 'overview'">
      <section class="card p-4 space-y-2">
        <h2 class="text-sm font-semibold text-ink-200">玩法说明</h2>
        <details class="rounded-lg border border-ink-700/60 bg-ink-900/40 p-3 text-xs text-ink-300">
          <summary class="cursor-pointer text-ink-200">完整规则</summary>
          <ul class="mt-2 list-disc space-y-1 pl-4">
            <li>在专属<b>采集 / 钓鱼</b>点获得「第 {{ stage }} 次重建用的」材料与鱼，再在专属配方<b>生产</b>出重建物资。</li>
            <li>提交产物即可获得积分：积分同时计入<b>全服进度</b>与你的<b>个人累计积分</b>。</li>
            <li>全服积分填满当前阶段进度条即进入下一阶段；第 {{ state?.stageCount ?? 5 }} 阶段完成后开启新一轮。</li>
            <li>每次重建的物资<b>不可跨阶段使用</b>：阶段推进后旧物资只能出售换金币。</li>
            <li>个人累计积分达标、且阶段达标后，可在「天钢装备」领取 / 升级可成长主手（生产 / 采集各一件）。</li>
          </ul>
        </details>

        <div class="rounded-lg border border-ink-700/60 bg-ink-900/40 p-3">
          <div class="flex flex-wrap items-center justify-between gap-2">
            <h3 class="text-xs font-semibold text-ink-300">重建背包（仅专属物资）</h3>
            <div class="flex items-center gap-2 text-xs">
              <label class="text-ink-400">阶段筛选</label>
              <select v-model="bagStage" class="rounded border border-ink-700 bg-ink-900 px-2 py-1 text-xs">
                <option value="current">当前阶段（第 {{ stage }} 次）</option>
                <option value="all">全部阶段</option>
                <option v-for="s in bagStages" :key="s" :value="s">第 {{ s }} 次重建</option>
              </select>
            </div>
          </div>
          <div class="mt-2 max-h-64 overflow-y-auto">
            <table class="w-full text-xs">
              <thead class="text-ink-400">
                <tr><th class="py-1 text-left">物品</th><th class="py-1 text-left">阶段</th><th class="py-1 text-right">数量</th><th class="py-1 text-right">操作</th></tr>
              </thead>
              <tbody>
                <tr v-for="row in bagRows" :key="row.itemId" class="border-t border-ink-800">
                  <td class="py-1 text-ink-200">{{ row.name }}</td>
                  <td class="py-1 text-ink-400">第 {{ row.stage }} 次</td>
                  <td class="py-1 text-right text-ink-200">{{ formatNumber(row.count) }}</td>
                  <td class="py-1 text-right">
                    <button
                      class="rounded border border-ink-600 px-2 py-0.5 text-[11px] text-ink-200 hover:bg-ink-800"
                      @click="sellRow(row.itemId, row.count, row.name)"
                    >
                      出售（{{ row.sell }}/个）
                    </button>
                  </td>
                </tr>
                <tr v-if="!bagRows.length"><td colspan="4" class="py-3 text-center text-ink-400">没有符合条件的物资</td></tr>
              </tbody>
            </table>
          </div>
        </div>
      </section>
    </template>

    <!-- 采集 -->
    <template v-else-if="tab === 'gather'">
      <section class="card p-4 space-y-3">
        <h2 class="text-sm font-semibold text-ink-200">专属采集（第 {{ stage }} 次重建）</h2>
        <div class="flex flex-wrap gap-2">
          <button
            v-for="node in state?.current.gather ?? []"
            :key="node.jobId"
            class="rounded-md border border-ink-600 px-3 py-1.5 text-sm text-ink-200 hover:bg-ink-800 disabled:opacity-50"
            :disabled="store.isRunning"
            @click="store.startGather(node.jobId)"
          >
            {{ jobName(node.jobId) }}（需 Lv.{{ node.levelReq }}）
          </button>
          <button
            v-if="store.isRunning"
            class="rounded-md border border-rose-500/60 px-3 py-1.5 text-sm text-rose-200 hover:bg-rose-500/10"
            @click="store.stop()"
          >
            停止
          </button>
        </div>
        <div class="h-2 w-full overflow-hidden rounded-full bg-ink-800">
          <div class="h-full bg-sky-500" :style="{ width: store.progressPct + '%' }" />
        </div>
        <ActivityLog title="采集日志" :entries="store.logEntries" empty="尚未开始采集" />
      </section>
    </template>

    <!-- 钓鱼 -->
    <template v-else-if="tab === 'fish'">
      <section class="card p-4 space-y-3">
        <h2 class="text-sm font-semibold text-ink-200">专属钓场（第 {{ stage }} 次重建）</h2>
        <div class="flex flex-wrap gap-2">
          <button
            class="rounded-md border border-ink-600 px-3 py-1.5 text-sm text-ink-200 hover:bg-ink-800 disabled:opacity-50"
            :disabled="store.isRunning"
            @click="store.startFish()"
          >
            开始钓鱼
          </button>
          <button
            v-if="store.isRunning"
            class="rounded-md border border-rose-500/60 px-3 py-1.5 text-sm text-rose-200 hover:bg-rose-500/10"
            @click="store.stop()"
          >
            停止
          </button>
        </div>
        <div class="text-xs text-ink-400">
          本阶段鱼获：
          <span v-for="f in state?.current.fish ?? []" :key="f.itemId" class="mr-3 text-ink-200">
            {{ f.name }}（{{ f.count }}）
          </span>
        </div>
        <div class="h-2 w-full overflow-hidden rounded-full bg-ink-800">
          <div class="h-full bg-sky-500" :style="{ width: store.progressPct + '%' }" />
        </div>
        <ActivityLog title="钓鱼日志" :entries="store.logEntries" empty="尚未开始钓鱼" />
      </section>
    </template>

    <!-- 生产 -->
    <template v-else-if="tab === 'produce'">
      <section class="card p-4 space-y-3">
        <div class="flex flex-wrap items-center justify-between gap-2">
          <h2 class="text-sm font-semibold text-ink-200">专属生产（第 {{ stage }} 次重建）</h2>
          <div class="flex items-center gap-2 text-xs text-ink-400">
            <label>制作件数</label>
            <input
              v-model.number="produceCount"
              type="number"
              min="1"
              placeholder="留空 = 全部"
              class="w-24 rounded border border-ink-700 bg-ink-900 px-2 py-1 text-xs"
            />
          </div>
        </div>
        <div class="grid gap-2 md:grid-cols-2">
          <div
            v-for="p in state?.current.products ?? []"
            :key="p.itemId"
            class="rounded-lg border border-ink-700/60 bg-ink-900/40 p-3"
          >
            <div class="flex items-center justify-between">
              <span class="text-sm text-ink-100">{{ p.name }}</span>
              <span class="text-xs text-amber-100">{{ p.points }} 分/件</span>
            </div>
            <p class="mt-1 text-[11px] text-ink-400">{{ jobName(p.jobId) }} · 需 Lv.{{ p.requiredLevel }} · 已有 {{ p.count }}</p>
            <ul class="mt-1 text-[11px] text-ink-300">
              <li v-for="input in p.inputs" :key="input.itemId" :class="input.have < input.count ? 'text-rose-300' : ''">
                {{ input.name }} ×{{ input.count }}（有 {{ input.have }}）
              </li>
            </ul>
            <button
              class="mt-2 w-full rounded-md border border-ink-600 px-3 py-1.5 text-xs text-ink-200 hover:bg-ink-800 disabled:opacity-50"
              :disabled="produceDisabled || maxCraftable(p) <= 0"
              @click="startProduce(p)"
            >
              开始生产
            </button>
          </div>
        </div>
        <div class="h-2 w-full overflow-hidden rounded-full bg-ink-800">
          <div class="h-full bg-emerald-500" :style="{ width: store.progressPct + '%' }" />
        </div>
        <p v-if="store.mode === 'produce'" class="text-[11px] text-ink-400">
          已生产 {{ store.producedCount }}<span v-if="store.targetCount"> / {{ store.targetCount }}</span> 件
        </p>
        <ActivityLog title="生产日志" :entries="store.logEntries" empty="尚未开始生产" />
      </section>
    </template>

    <!-- 提交 -->
    <template v-else-if="tab === 'submit'">
      <section class="card p-4 space-y-3">
        <h2 class="text-sm font-semibold text-ink-200">提交产物换积分</h2>
        <p class="text-[11px] text-ink-400">只能提交当前阶段（第 {{ stage }} 次重建）的产物；提交后积分计入全服进度与个人累计积分。</p>
        <div class="space-y-2">
          <div
            v-for="p in state?.current.products ?? []"
            :key="p.itemId"
            class="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-ink-700/60 bg-ink-900/40 p-3"
          >
            <div>
              <p class="text-sm text-ink-100">{{ p.name }}</p>
              <p class="text-[11px] text-ink-400">持有 {{ p.count }} 件 · 每件 {{ p.points }} 分 · 可获 {{ formatNumber(p.count * p.points) }} 分</p>
            </div>
            <button
              class="rounded-md border border-amber-400/60 bg-amber-500/20 px-3 py-1.5 text-xs text-amber-100 hover:bg-amber-500/30 disabled:opacity-50"
              :disabled="p.count <= 0 || submitting === p.itemId"
              @click="submitAll({ itemId: p.itemId, count: p.count, points: p.points })"
            >
              全部提交
            </button>
          </div>
        </div>
      </section>
    </template>

    <!-- 天钢装备 -->
    <template v-else-if="tab === 'tool'">
      <section class="card p-4 space-y-3">
        <h2 class="text-sm font-semibold text-ink-200">天钢主手装备（可成长）</h2>
        <p class="text-[11px] text-ink-400">
          固定「高品质」并固定带 1 条随机「紫色附魔」；升级需<b>个人累计积分</b>达标且<b>对应阶段已完成</b>，不额外消耗材料。
        </p>
        <div class="grid gap-3 md:grid-cols-2">
          <div
            v-for="entry in KINDS"
            :key="entry.kind"
            class="rounded-lg border border-ink-700/60 bg-ink-900/40 p-3"
          >
            <div class="flex items-center justify-between">
              <span class="text-sm text-ink-100">{{ entry.label }}</span>
              <span class="text-xs text-ink-300">
                <template v-if="state?.tools[entry.kind].level">Lv.{{ state.tools[entry.kind].level }} 神话</template>
                <template v-else>未拥有</template>
              </span>
            </div>

            <ul v-if="state?.tools[entry.kind].bonus" class="mt-1 text-[11px] text-ink-300">
              <li v-for="(value, stat) in state.tools[entry.kind].bonus" :key="stat">
                {{ data.dohdolEquipment.bonusNames[stat] ?? stat }} +{{ value }}%
              </li>
            </ul>

            <div v-if="state?.tools[entry.kind].pink" class="mt-2 rounded border border-purple-400/50 bg-purple-500/10 p-2">
              <p class="text-[11px] font-semibold text-purple-200">
                紫色附魔 · {{ state.tools[entry.kind].pink?.name }}
              </p>
              <p class="text-[11px] text-purple-100">{{ pinkByName(state.tools[entry.kind]) }}</p>
            </div>

            <p v-if="state?.tools[entry.kind].status.nextLevel" class="mt-2 text-[11px] text-ink-400">
              下一档 Lv.{{ state.tools[entry.kind].status.nextLevel }}：需个人积分 ≥
              {{ formatNumber(state.tools[entry.kind].status.nextThreshold ?? 0) }}、已完成第
              {{ state.tools[entry.kind].status.nextStage }} 次重建
            </p>

            <div class="mt-2 flex flex-wrap gap-2">
              <button
                v-if="!state?.tools[entry.kind].level"
                class="rounded-md border border-amber-400/60 bg-amber-500/20 px-3 py-1.5 text-xs text-amber-100 disabled:opacity-40"
                :disabled="!state?.tools[entry.kind].status.canClaim"
                @click="claim(entry.kind)"
              >
                领取
              </button>
              <template v-else>
                <button
                  class="rounded-md border border-ink-600 px-3 py-1.5 text-xs text-ink-200 disabled:opacity-40"
                  :disabled="!state?.tools[entry.kind].status.canUpgrade"
                  @click="upgrade(entry.kind)"
                >
                  升级
                </button>
                <button
                  class="rounded-md border border-purple-400/60 px-3 py-1.5 text-xs text-purple-100 hover:bg-purple-500/10"
                  @click="reroll(entry.kind)"
                >
                  重铸紫色附魔（消耗重新打造卡）
                </button>
              </template>
            </div>
          </div>
        </div>
      </section>
    </template>

    <!-- 积分榜 -->
    <template v-else-if="tab === 'board'">
      <section class="card p-4 space-y-3">
        <div class="flex items-center justify-between">
          <h2 class="text-sm font-semibold text-ink-200">重建积分榜（本玩法专属）</h2>
          <button class="rounded border border-ink-600 px-2 py-1 text-xs text-ink-200 hover:bg-ink-800" @click="loadBoard(board?.page ?? 1)">
            刷新
          </button>
        </div>
        <table class="w-full text-xs">
          <thead class="text-ink-400">
            <tr><th class="py-1 text-left">名次</th><th class="py-1 text-left">玩家</th><th class="py-1 text-right">累计积分</th></tr>
          </thead>
          <tbody>
            <tr v-for="row in store.leaderboard" :key="row.userId" class="border-t border-ink-800">
              <td class="py-1 text-ink-300">{{ row.rank }}</td>
              <td class="py-1 text-ink-100">{{ row.nickname }}<span class="text-ink-500">#{{ row.username }}</span></td>
              <td class="py-1 text-right text-ink-200">{{ formatNumber(row.points) }}</td>
            </tr>
            <tr v-if="!store.leaderboard.length"><td colspan="3" class="py-3 text-center text-ink-400">暂无数据</td></tr>
          </tbody>
        </table>
        <div class="flex items-center justify-between text-xs text-ink-400">
          <button class="rounded border border-ink-600 px-2 py-1 disabled:opacity-40" :disabled="(board?.page ?? 1) <= 1" @click="loadBoard((board?.page ?? 1) - 1)">上一页</button>
          <span>第 {{ board?.page ?? 1 }} 页</span>
          <button class="rounded border border-ink-600 px-2 py-1 disabled:opacity-40" :disabled="(store.leaderboard.length ?? 0) < 50" @click="loadBoard((board?.page ?? 1) + 1)">下一页</button>
        </div>
      </section>
    </template>
  </div>
</template>
