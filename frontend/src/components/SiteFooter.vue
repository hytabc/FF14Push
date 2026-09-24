<script setup lang="ts">
const ICP_NUMBER = '黑ICP备2026011235号'
/** 工信部备案管理系统，备案号必须链接至此地址。 */
const ICP_URL = 'https://beian.miit.gov.cn/'
</script>

<template>
  <footer class="border-t border-ink-800 px-3 py-3 text-center text-[11px] leading-relaxed text-ink-400">
    <p>
      免责声明：本作仅为《最终幻想 XIV》的同人制作，出于个人兴趣与非商业目的，与史克威尔艾尼克斯（Square
      Enix）及其关联公司无任何隶属或合作关系，也未获得其授权或认可；游戏内相关名称、设定与素材版权均归原权利人所有。
    </p>
    <p class="mt-1.5">
      <a :href="ICP_URL" target="_blank" rel="noopener noreferrer" class="transition hover:text-ink-400">
        {{ ICP_NUMBER }}
      </a>
    </p>
  </footer>
</template>
