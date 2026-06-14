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
      name: 'MainLayout',
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
        { path: 'plugin-page/:pluginId/:pageRoute(.*)', name: 'PluginPagePlaceholder', component: () => import('@/views/PluginPageView.vue'), props: true, meta: { pluginPage: true, title: 'Plugin Page' } },
        { path: ':pathMatch(.*)*', redirect: '/overview' },
      ],
    },
  ],
})

// Navigation guard
router.beforeEach(async (to) => {
  const token = localStorage.getItem('jwt_token')

  // Resolve auth config if unknown; on failure, use a per-navigation fallback
  // (assume auth enabled) so we don't permanently cache a wrong value and
  // future navigations will retry the fetch.
  let effectiveAuth = authEnabled
  if (effectiveAuth === null) {
    try {
      const { data } = await getAuthConfig()
      authEnabled = data.auth_enabled
      effectiveAuth = authEnabled
    } catch {
      effectiveAuth = true
    }
  }

  // Auth disabled: the user must never see the login form. Mint a fresh
  // sentinel JWT whenever we have no token, OR whenever we land directly on
  // /login (e.g. Electron shell loads ${BACKEND_URL}/login on startup) — in
  // that case any cached token may be stale from a prior enabled-mode session
  // and there's no API call on this page to surface the mode mismatch.
  if (!effectiveAuth) {
    if (!token || to.path === '/login') {
      try {
        const { data } = await login({ access_token: 'disabled' })
        localStorage.setItem('jwt_token', data.access_token)
        return to.path === '/login' ? '/' : to.fullPath
      } catch {
        // sentinel login shouldn't fail; fall through and keep whatever
        // token we had (if any) so the user isn't blocked entirely.
      }
    }
    return
  }

  // Auth enabled: trust whatever token we have. If it was issued under the
  // wrong auth_mode (cached sentinel JWT) the next API call will 401 and the
  // response interceptor will clear the token and route back to /login.
  if (token) return
  if (to.meta.public) return
  return '/login'
})

export default router
