<script setup lang="ts">
import { formatNumber, jobName } from '@/utils/format'
import { onMounted, ref } from 'vue'
import data from '@shared/schema'
import { http, toApiError } from '@/api/client'
import { useGameStore } from '@/stores/game'
import type { Roster } from '@/game/multiplayer'
import Modal from '@/components/Modal.vue'
const game = useGameStore()
const roster = ref<Roster | null>(null), error = ref(''), busy = ref(false), dismissId = ref<number | null>(null), expandOpen = ref(false)
const selectedItems = ref<Record<number, number>>({}), selectedSlots = ref<Record<number, string>>({})
async function load() { roster.value = (await http.get<Roster>('/heroes')).data; await game.loadState() }
async function act(fn: () => Promise<unknown>) {
  busy.value = true; error.value = ''
  try { await fn(); await load() } catch (e) { error.value = toApiError(e).message } finally { busy.value = false }
}
async function switchHero(id: number) {
  await act(async () => { await game.stopBattle(true); await game.stopRaid(true); await http.post('/heroes/switch', { heroId: id }) })
}
async function dismiss() { if (dismissId.value !== null) await act(() => http.delete(`/heroes/${dismissId.value}`)); dismissId.value = null }
async function expand() { expandOpen.value = false; await act(() => http.post('/heroes/expand', {})) }
onMounted(() => act(load))
</script>
<template>
  <main class="dlc">
    <header><p class="eyebrow">八英雄远征 · 英雄名册</p><h1>你的远征队 <small>{{ roster?.heroes.length ?? 0 }} / {{ roster?.capacity ?? 0 }}</small></h1>
      <p>每名英雄独立成长与配装。日常只有当前英雄练级；装备脱下后可转交。</p><RouterLink to="/tavern">前往酒馆招募 →</RouterLink></header>
    <p v-if="error" class="error" role="alert">{{ error }}</p>
    <section v-if="roster" class="panel">
      <h2>远征队席位 <small>{{ roster.capacity }} / {{ roster.maxCapacity }}</small></h2>
      <p>席位决定可同时拥有的英雄数量。可用金币扩充，每多开一席价格更高（线性递增）。</p>
      <button
        v-if="roster.expandCost !== null"
        :disabled="busy || game.gold < roster.expandCost"
        :title="game.gold < roster.expandCost ? '金币不足' : ''"
        @click="expandOpen = true"
      >
        扩充一席 · {{ formatNumber(roster.expandCost) }} 金币
      </button>
      <p v-else>已达上限 {{ roster.maxCapacity }} 席。</p>
    </section>
    <div class="cards">
      <article v-for="h in roster?.heroes" :key="h.id" class="panel">
        <h2>{{ h.name }} <small>Lv.{{ h.level }}</small></h2><p>{{ jobName(h.jobId) }} · {{ h.talentName }} · 经验 {{ h.exp }}</p>
        <p>生命 {{ Math.round(h.stats.maxHp) }} · 攻击 {{ Math.round(Math.max(h.stats.attack, h.stats.magicAttack)) }}</p>
        <div class="mt-3 grid grid-cols-3 gap-2 text-center">
          <div class="rounded-lg border p-1.5" :class="h.ancientAttr === 'str' ? 'border-term-ancient bg-term-ancient/10' : 'border-ink-700 bg-ink-800/60'">
            <span class="block text-[10px] text-ink-400">力量</span>
            <span class="block font-mono text-base text-rose-300">{{ h.strength }}<span v-if="h.ancientAttr === 'str'" class="ml-0.5 align-top text-xs">🌟</span></span>
          </div>
          <div class="rounded-lg border p-1.5" :class="h.ancientAttr === 'dex' ? 'border-term-ancient bg-term-ancient/10' : 'border-ink-700 bg-ink-800/60'">
            <span class="block text-[10px] text-ink-400">敏捷</span>
            <span class="block font-mono text-base text-emerald-300">{{ h.agility }}<span v-if="h.ancientAttr === 'dex'" class="ml-0.5 align-top text-xs">🌟</span></span>
          </div>
          <div class="rounded-lg border p-1.5" :class="h.ancientAttr === 'int' ? 'border-term-ancient bg-term-ancient/10' : 'border-ink-700 bg-ink-800/60'">
            <span class="block text-[10px] text-ink-400">智力</span>
            <span class="block font-mono text-base text-sky-300">{{ h.intellect }}<span v-if="h.ancientAttr === 'int'" class="ml-0.5 align-top text-xs">🌟</span></span>
          </div>
        </div>
        <button :disabled="busy || roster?.activeHeroId === h.id" @click="switchHero(h.id)">{{ roster?.activeHeroId === h.id ? '当前出战' : '切换出战' }}</button>
        <button class="danger" :disabled="busy || (roster?.heroes.length ?? 0) <= 1" :title="(roster?.heroes.length ?? 0) <= 1 ? '至少保留一名英雄' : ''" @click="dismissId = h.id">解雇</button>
        <details><summary>独立配装（{{ Object.keys(h.loadout).filter(s => !s.startsWith('doh') && !s.startsWith('dol')).length }} 件）</summary>
          <div v-for="slot in data.slots" :key="slot.id" class="equipment-row"><span>{{ slot.name }}：{{ h.loadout[slot.id]?.name ?? '未穿戴' }}</span>
            <button v-if="h.loadout[slot.id]" :disabled="busy" @click="act(() => http.post(`/heroes/${h.id}/unequip`, { slot: slot.id }))">卸下</button></div>
          <select v-model="selectedItems[h.id]" aria-label="选择背包装备"><option :value="undefined">选择未穿戴装备</option><option v-for="item in game.state?.items.filter(i => !i.equippedSlot && ['weapon','armor','accessory'].includes(i.category))" :key="item.id" :value="item.id">{{ item.name }} · {{ item.rarity }}</option></select>
          <select v-model="selectedSlots[h.id]" aria-label="选择穿戴栏位"><option :value="undefined">选择栏位</option><option v-for="s in data.slots" :key="s.id" :value="s.id">{{ s.name }}</option></select>
          <button :disabled="busy || !selectedItems[h.id] || !selectedSlots[h.id]" @click="act(() => http.post(`/heroes/${h.id}/equip`, { itemId: selectedItems[h.id], slot: selectedSlots[h.id] }))">穿戴</button>
        </details>
      </article>
    </div>
    <Modal :open="dismissId !== null" title="确认解雇英雄" @close="dismissId = null"><p>该英雄等级与经验将永久删除，穿戴装备回到共享背包。</p><template #footer><button @click="dismissId = null">取消</button><button :disabled="busy" @click="dismiss">确认解雇</button></template></Modal>
    <Modal :open="expandOpen" title="扩充远征队席位" @close="expandOpen = false">
      <p>将花费 <b>{{ formatNumber(roster?.expandCost ?? 0) }}</b> 金币，把远征队席位从 {{ roster?.capacity }} 扩充到 {{ (roster?.capacity ?? 0) + 1 }} 席（持有 💰 {{ game.gold.toLocaleString() }}）。</p>
      <template #footer><button @click="expandOpen = false">取消</button><button :disabled="busy" @click="expand">确认扩充</button></template>
    </Modal>
  </main>
</template>
