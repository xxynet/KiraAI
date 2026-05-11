import { createRouter, createWebHistory } from 'vue-router'
import { getAuthConfig, login } from '@/api/auth'

let authEnabled: boolean | null = null

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/login',
      name: 'Login',
      component: () => import('@/views/LoginView.vue'),
      meta: { public: true },
    },
    {
      path: '/',
      component: () => import('@/views/MainLayout.vue'),
      children: [
        { path: '', redirect: '/overview' },
        { path: 'overview', name: 'Overview', component: () => import('@/views/OverviewView.vue') },
        { path: 'provider', name: 'Provider', component: () => import('@/views/ProviderView.vue') },
        { path: 'adapter', name: 'Adapter', component: () => import('@/views/AdapterView.vue') },
        { path: 'persona', name: 'Persona', component: () => import('@/views/PersonaView.vue') },
        { path: 'plugin', name: 'Plugin', component: () => import('@/views/PluginView.vue') },
        { path: 'sticker', name: 'Sticker', component: () => import('@/views/StickerView.vue') },
        { path: 'configuration', name: 'Configuration', component: () => import('@/views/ConfigView.vue') },
        { path: 'sessions', name: 'Sessions', component: () => import('@/views/SessionView.vue') },
        { path: 'logs', name: 'Logs', component: () => import('@/views/LogsView.vue') },
        { path: 'settings', name: 'Settings', component: () => import('@/views/SettingsView.vue') },
        { path: ':pathMatch(.*)*', redirect: '/overview' },
      ],
    },
  ],
})

// Navigation guard
router.beforeEach(async (to) => {
  const token = localStorage.getItem('jwt_token')
  if (token || to.meta.public) return

  // If auth is disabled, auto-login with fixed token
  if (authEnabled === null) {
    try {
      const { data } = await getAuthConfig()
      authEnabled = data.auth_enabled
    } catch {
      authEnabled = true
    }
  }
  if (!authEnabled) {
    try {
      const { data } = await login({ access_token: 'disabled' })
      localStorage.setItem('jwt_token', data.access_token)
      return to.fullPath
    } catch {
      // fallback: redirect to login
    }
  }
  return '/login'
})

export default router
