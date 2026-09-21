import { createRouter, createWebHistory } from 'vue-router'

import { useAuthStore } from '@/stores/auth'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/login', name: 'login', component: () => import('@/views/LoginView.vue'), meta: { public: true } },
    { path: '/', name: 'main', component: () => import('@/views/MainView.vue') },
    { path: '/equipment', name: 'equipment', component: () => import('@/views/EquipmentView.vue') },
    { path: '/inventory', name: 'inventory', component: () => import('@/views/InventoryView.vue') },
    { path: '/chest', name: 'chest', component: () => import('@/views/ChestView.vue') },
    { path: '/craft', name: 'craft', component: () => import('@/views/CraftView.vue') },
    { path: '/gather', name: 'gather', component: () => import('@/views/GatherView.vue') },
    { path: '/produce', name: 'produce', component: () => import('@/views/ProduceView.vue') },
    { path: '/fish', name: 'fish', component: () => import('@/views/FishView.vue') },
    { path: '/hero', name: 'hero', component: () => import('@/views/HeroView.vue') },
    { path: '/region', name: 'region', component: () => import('@/views/RegionView.vue') },
    { path: '/raid', name: 'raid', component: () => import('@/views/RaidView.vue') },
    { path: '/tavern', name: 'tavern', component: () => import('@/views/TavernView.vue') },
    { path: '/codex', name: 'codex', component: () => import('@/views/CodexView.vue') },
    { path: '/ranking', name: 'ranking', component: () => import('@/views/RankingView.vue'), meta: { public: true } },
    { path: '/settings', name: 'settings', component: () => import('@/views/SettingsView.vue') },
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
