<script setup lang="ts">
import { jobName } from '@/utils/format'
import { onMounted, ref } from 'vue'
import data from '@shared/schema'
import { http, toApiError } from '@/api/client'
import { useGameStore } from '@/stores/game'
import type { Roster } from '@/game/multiplayer'
import Modal from '@/components/Modal.vue'
const game = useGameStore()
const roster = ref<Roster | null>(null), error = ref(''), busy = ref(false), dismissId = ref<number | null>(null)
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
onMounted(() => act(load))
</script>
<template>
  <main class="dlc">
    <header><p class="eyebrow">八英雄远征 · 英雄名册</p><h1>你的远征队 <small>{{ roster?.heroes.length ?? 0 }} / 8</small></h1>
      <p>每名英雄独立成长与配装。日常只有当前英雄练级；装备脱下后可转交。</p><RouterLink to="/tavern">前往酒馆招募 →</RouterLink></header>
    <p v-if="error" class="error" role="alert">{{ error }}</p>
    <div class="cards">
      <article v-for="h in roster?.heroes" :key="h.id" class="panel">
        <h2>{{ h.name }} <small>Lv.{{ h.level }}</small></h2><p>{{ jobName(h.jobId) }} · {{ h.talentName }} · 经验 {{ h.exp }}</p>
        <p>生命 {{ Math.round(h.stats.maxHp) }} · 攻击 {{ Math.round(Math.max(h.stats.attack, h.stats.magicAttack)) }}</p>
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
  </main>
</template>
