import { createRouter, createWebHistory } from 'vue-router'

import { useAuthStore } from '@/stores/auth'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/roster', component: () => import('@/views/RosterView.vue') },
    { path: '/coop', component: () => import('@/views/CoopView.vue') },
    { path: '/worldboss', component: () => import('@/views/WorldBossView.vue') },
    { path: '/arena', component: () => import('@/views/ArenaView.vue') },
    { path: '/login', name: 'login', component: () => import('@/views/LoginView.vue'), meta: { public: true } },
    { path: '/', name: 'main', component: () => import('@/views/MainView.vue') },
    { path: '/equipment', name: 'equipment', component: () => import('@/views/EquipmentView.vue') },
    { path: '/inventory', name: 'inventory', component: () => import('@/views/InventoryView.vue') },
    { path: '/market', name: 'market', component: () => import('@/views/MarketView.vue') },
    { path: '/chest', name: 'chest', component: () => import('@/views/ChestView.vue') },
    { path: '/craft', name: 'craft', component: () => import('@/views/CraftView.vue') },
    { path: '/gather', name: 'gather', component: () => import('@/views/GatherView.vue') },
    { path: '/produce', name: 'produce', component: () => import('@/views/ProduceView.vue') },
    { path: '/fish', name: 'fish', component: () => import('@/views/FishView.vue') },
    { path: '/hero', name: 'hero', component: () => import('@/views/HeroView.vue') },
    { path: '/region', name: 'region', component: () => import('@/views/RegionView.vue') },
    { path: '/raid', name: 'raid', component: () => import('@/views/RaidView.vue') },
    { path: '/treasure', name: 'treasure', component: () => import('@/views/TreasureView.vue') },
    { path: '/materia', name: 'materia', component: () => import('@/views/MateriaView.vue') },
    { path: '/farm', name: 'farm', component: () => import('@/views/FarmView.vue') },
    { path: '/tavern', name: 'tavern', component: () => import('@/views/TavernView.vue') },
    { path: '/codex', name: 'codex', component: () => import('@/views/CodexView.vue') },
    { path: '/ranking', name: 'ranking', component: () => import('@/views/RankingView.vue'), meta: { public: true } },
    { path: '/grants', name: 'grants', component: () => import('@/views/GrantView.vue'), meta: { public: true } },
    { path: '/friends', name: 'friends', component: () => import('@/views/FriendsView.vue') },
    { path: '/chat', name: 'chat', component: () => import('@/views/ChatView.vue') },
    { path: '/settings', name: 'settings', component: () => import('@/views/SettingsView.vue') },
    { path: '/gametest', name: 'gametest', component: () => import('@/views/GameTestView.vue') },
    { path: '/admin', name: 'admin', component: () => import('@/views/AdminView.vue') },
    { path: '/:pathMatch(.*)*', redirect: '/' },
  ],
})

router.beforeEach((to) => {
  const auth = useAuthStore()
  if (!to.meta.public && !auth.isLoggedIn) {
    return { name: 'login', query: { redirect: to.fullPath } }
  }
  if (to.name === 'login' && auth.isLoggedIn) {
    return { name: 'main' }
  }
  return true
})

export default router
