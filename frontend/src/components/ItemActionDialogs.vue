<script setup lang="ts">
import { computed } from 'vue'

import ItemIcon from '@/components/ItemIcon.vue'
import Modal from '@/components/Modal.vue'
import { useItemActions } from '@/stores/itemActions'
import { attrName, attrSuffix, rarityClass, rarityName, termLabel } from '@/utils/format'

const actions = useItemActions()

const item = computed(() => actions.pending?.item ?? null)
const kind = computed(() => actions.pending?.kind ?? null)

const title = computed(() => {
  switch (kind.value) {
    case 'refine':
      return '确认重造'
    case 'enchant':
      return '确认附魔'
    case 'enchantAuto':
      return '自动附魔至稀有/太古'
    case 'sell':
      return '确认出售'
    default:
      return ''
  }
})

// 实付价由后端按当前重造次数算好下发，避免前端与结算公式漂移
const refineCost = computed(() => item.value?.refineCost ?? 0)
const enchantCost = computed(() => item.value?.enchantCost ?? 0)
const sellPrice = computed(() => item.value?.sellPriceMax ?? 0)
</script>

<template>
  <Modal :open="!!actions.pending" :title="title" @close="actions.cancel()">
    <div v-if="item" class="space-y-3 text-sm">
      <div class="rounded-lg border border-ink-700 bg-ink-800/70 p-3">
        <div class="flex items-center gap-3">
          <ItemIcon :base-id="item.baseId" :rarity="item.rarity" :size="48" />
          <p class="font-medium" :class="rarityClass(item.rarity)">
            {{ item.name }} · {{ rarityName(item.rarity) }}
          </p>
        </div>
        <ul class="mt-1 space-y-0.5 text-[11px] text-ink-300">
          <li v-for="entry in item.subAttrs" :key="entry.attr">
            {{ attrName(entry.attr) }} +{{ entry.value.toFixed(2) }}{{ attrSuffix(entry.attr) }}
          </li>
        </ul>
        <div v-if="item.terms.length" class="mt-2 flex flex-wrap gap-1">
          <span
            v-for="term in item.terms"
            :key="term.id"
            class="rounded border border-ink-600 px-1.5 py-0.5 text-[10px]"
            :class="term.type === 'debuff' ? 'text-rose-300' : 'text-emerald-300'"
          >
            {{ termLabel(term) }}
            {{ term.desc.replace('{v}', String(term.value)) }}
          </span>
        </div>
      </div>

      <p v-if="kind === 'refine'" class="text-xs text-ink-300">
        将重新随机<b class="text-white">基础属性浮动值</b>与<b class="text-white">副属性（种类与数值）</b>；
        品阶、类型、等级需求与所有 Buff/Debuff <b class="text-emerald-300">保持不变</b>。重造后属性可能变好也可能变差。
        <span v-if="item.refineCount" class="text-amber-300">
          该装备已重造 {{ item.refineCount }} 次，重造费用会随次数继续上涨。
        </span>
      </p>
      <p v-else-if="kind === 'enchant'" class="text-xs text-ink-300">
        将<b class="text-rose-300">覆盖现有全部 Buff/Debuff</b>（数量、种类、数值均会重新随机）。
        极低概率出现稀有词条，更低概率出现太古词条。附魔结果<b class="text-rose-300">不可撤销</b>。
      </p>
      <p v-else-if="kind === 'enchantAuto'" class="text-xs text-ink-300">
        将持续附魔直到出现<b class="text-amber-300">稀有或太古</b>词条为止，每次附魔都会消耗金币，
        总消耗取决于运气。最多尝试 100 次或金币耗尽即停止。
      </p>
      <p v-else class="text-xs text-ink-300">
        出售后装备<b class="text-rose-300">永久消失</b>，获得金币。图鉴解锁记录会保留。
      </p>

      <p class="rounded-lg border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-xs text-amber-200">
        <template v-if="kind === 'refine'">消耗：{{ refineCost.toLocaleString() }} 金币</template>
        <template v-else-if="kind === 'enchant'">消耗：{{ enchantCost.toLocaleString() }} 金币</template>
        <template v-else-if="kind === 'enchantAuto'">
          单次消耗：{{ enchantCost.toLocaleString() }} 金币（按次数累计）
        </template>
        <template v-else>获得：约 {{ sellPrice.toLocaleString() }} 金币</template>
      </p>
    </div>

    <template #footer>
      <button class="rounded-md bg-ink-700 px-3 py-2 text-sm hover:bg-ink-600" @click="actions.cancel()">
        取消
      </button>
      <button
        class="rounded-md px-3 py-2 text-sm font-medium text-white disabled:opacity-50"
        :class="kind === 'sell' ? 'bg-amber-600 hover:bg-amber-500' : 'bg-indigo-600 hover:bg-indigo-500'"
        :disabled="actions.busy"
        @click="actions.confirm()"
      >
        {{ actions.busy ? '处理中…' : '确认' }}
      </button>
    </template>
  </Modal>
</template>
