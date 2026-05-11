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
  const isAutoDisabled = localStorage.getItem('jwt_auto_disabled') === 'true'

  // Resolve auth config if unknown
  if (authEnabled === null) {
    try {
      const { data } = await getAuthConfig()
      authEnabled = data.auth_enabled
    } catch {
      authEnabled = true
    }
  }

  // When auth is enabled, any token obtained via the "disabled" sentinel flow
  // must be invalidated — the API returns a real JWT, not the literal "disabled"
  // string, so we track it with a companion marker in localStorage.
  if (authEnabled && isAutoDisabled) {
    localStorage.removeItem('jwt_token')
    localStorage.removeItem('jwt_auto_disabled')
  }

  // Allow through if we have a genuinely authenticated token
  if (token && !isAutoDisabled) return
  // Auth disabled and we already have a sentinel-obtained token
  if (!authEnabled && token && isAutoDisabled) return

  // If auth is disabled, auto-login with sentinel token
  if (!authEnabled) {
    try {
      const { data } = await login({ access_token: 'disabled' })
      localStorage.setItem('jwt_token', data.access_token)
      localStorage.setItem('jwt_auto_disabled', 'true')
      return to.meta.public ? '/' : to.fullPath
    } catch {
      // fallback: continue to login
    }
  }

  if (to.meta.public) return
  return '/login'
})

export default router
