<script setup lang="ts">
import Modal from '@/components/Modal.vue'
import { useAnnouncementStore } from '@/stores/announcement'
import { APP_VERSION, CHANGELOG, LATEST_CHANGELOG } from '@/version'

const announcement = useAnnouncementStore()

/** 历史版本（最新一条已在顶部单独展示）。 */
const history = CHANGELOG.slice(1)
</script>

<template>
  <Modal
    :open="announcement.open"
    :title="`更新公告 · V${APP_VERSION}`"
    @close="announcement.dismiss()"
  >
    <div class="space-y-3 text-sm">
      <p>
        <span class="font-mono text-amber-200">V{{ APP_VERSION }}</span>
        <span v-if="LATEST_CHANGELOG?.date" class="ml-2 text-ink-400">{{ LATEST_CHANGELOG.date }}</span>
      </p>

      <ul class="space-y-1.5">
        <li v-for="(item, i) in LATEST_CHANGELOG?.items ?? []" :key="i" class="flex gap-2 text-ink-200">
          <span class="text-amber-300">•</span><span>{{ item }}</span>
        </li>
      </ul>

      <div v-if="history.length" class="border-t border-ink-700 pt-3">
        <button
          class="text-xs text-ink-400 transition hover:text-amber-200"
          @click="announcement.toggleExpanded()"
        >
          {{ announcement.expanded ? '收起历史更新' : `查看历史更新（${history.length}）` }}
        </button>

        <div v-if="announcement.expanded" class="mt-3 space-y-3">
          <section
            v-for="entry in history"
            :key="entry.version"
            class="border-l-2 border-ink-700 pl-3"
          >
            <p class="text-xs">
              <span class="font-mono text-ink-200">V{{ entry.version }}</span>
              <span v-if="entry.date" class="ml-2 text-ink-400">{{ entry.date }}</span>
            </p>
            <ul class="mt-1 space-y-1">
              <li v-for="(item, i) in entry.items" :key="i" class="flex gap-2 text-ink-200">
                <span class="text-ink-600">•</span><span>{{ item }}</span>
              </li>
            </ul>
          </section>
        </div>
      </div>
    </div>

    <template #footer>
      <button
        class="rounded-md bg-amber-500 px-3 py-2 text-sm font-medium text-ink-950 hover:bg-amber-300"
        @click="announcement.dismiss()"
      >
        我知道了
      </button>
    </template>
  </Modal>
</template>
