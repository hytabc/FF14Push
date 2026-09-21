<script setup lang="ts">
import { ref } from 'vue'
import { http, toApiError } from '@/api/client'
const props = defineProps<{ scopes: Array<{ id: string; name: string }> }>()
const emit = defineEmits<{ passed: [] }>()
const scope = ref('')
const busy = ref(false)
const message = ref('连续正确处理三次随机机制，即可获得本内容的资格标记。每次提示须在 8 秒内响应。')
const trial = ref<{trialId:number; step:number; cue:string; passed:boolean; failed?:boolean; windowSeconds:number} | null>(null)
const labels: Record<string,string> = { sidestep:'侧移', guard:'防御', interrupt:'打断' }
async function request(action?:string) {
  busy.value=true
  try {
    const result = action && trial.value
      ? await http.post('/trial/respond',{trialId:trial.value.trialId,step:trial.value.step,action})
      : await http.post('/trial/start',{scope:scope.value || props.scopes[0]?.id})
    trial.value=result.data
    if(result.data.passed) { message.value='试炼通过，资格已保存。'; trial.value=null; emit('passed') }
    else if(result.data.failed) { message.value=result.data.message; trial.value=null }
    else message.value=`第 ${result.data.step+1} 次：${result.data.cue}（${result.data.windowSeconds} 秒内）`
  } catch(e) { message.value=toApiError(e).message; trial.value=null }
  finally { busy.value=false }
}
</script>
<template>
  <section class="card space-y-2 p-4">
    <h3 class="text-sm font-semibold text-amber-200">机制试炼</h3>
    <p class="text-xs text-ink-300">{{ message }}</p>
    <div v-if="!trial" class="flex gap-2">
      <select v-model="scope" class="rounded bg-ink-800 p-2 text-xs" aria-label="选择机制试炼">
        <option value="" disabled>选择试炼内容</option>
        <option v-for="entry in scopes" :key="entry.id" :value="entry.id">{{entry.name}}</option>
      </select>
      <button class="btn-primary" :disabled="busy || !scopes.length" @click="request()">开始试炼</button>
    </div>
    <div v-else class="flex gap-3">
      <button v-for="(label, action) in labels" :key="action" class="btn-primary" :disabled="busy" @click="request(action)">{{label}}</button>
    </div>
  </section>
</template>
