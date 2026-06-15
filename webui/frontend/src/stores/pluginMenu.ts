import { defineStore } from 'pinia'
import { ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { getPlugins } from '@/api/plugin'
import router from '@/router'

export interface PluginMenuItem {
  pluginId: string
  pluginName: string
  route: string       // Vue Router path, e.g. /plugin-page/my-plugin/dashboard
  pageRoute: string   // The page route segment passed to PluginPageView
  rawLabel: string | Record<string, string>  // Raw label from API (for i18n re-resolution)
  label: string       // Resolved display text (re-computed on locale change)
  icon: string | null
  order: number
}

/**
 * Resolve a label that may be a plain string or a locale dict.
 * Falls back: requested locale → "en" → first available value → raw key.
 */
export function resolveLabel(label: string | Record<string, string>, locale: string): string {
  if (typeof label === 'string') return label
  if (typeof label === 'object' && label !== null) {
    if (label[locale]) return label[locale]
    if (label['en']) return label['en']
    const first = Object.values(label)[0]
    if (first) return first
  }
  return String(label)
}

export const usePluginMenuStore = defineStore('pluginMenu', () => {
  const menus = ref<PluginMenuItem[]>([])
  const loaded = ref(false)
  const { locale } = useI18n()

  async function fetchAndRegisterMenus() {
    try {
      const { data } = await getPlugins()
      const newMenus: PluginMenuItem[] = []
      const seenRoutes = new Set<string>()
      const currentLocale = locale.value

      for (const plugin of data) {
        if (!plugin.enabled || !plugin.menus?.length) continue
        for (const menu of plugin.menus) {
          // Extract the page route from the API route: /page/plugin/{id}/{pageRoute}
          const apiPath = menu.route  // e.g. /page/plugin/my_plugin/dashboard
          const parts = apiPath.split('/')
          // parts: ['', 'page', 'plugin', '{id}', ...rest]
          const pageRoute = parts.slice(4).join('/') || 'index'
          const internalRoute = `/plugin-page/${plugin.id}/${pageRoute}`

          if (seenRoutes.has(internalRoute)) continue
          seenRoutes.add(internalRoute)

          newMenus.push({
            pluginId: plugin.id,
            pluginName: plugin.name,
            route: internalRoute,
            pageRoute,
            rawLabel: menu.label,
            label: resolveLabel(menu.label, currentLocale),
            icon: menu.icon,
            order: menu.order ?? 100,
          })
        }
      }

      newMenus.sort((a, b) => a.order - b.order)

      // Register dynamic routes for new entries
      for (const item of newMenus) {
        const routeName = `plugin-page-${item.pluginId}-${item.pageRoute}`
        if (!router.hasRoute(routeName)) {
          router.addRoute('MainLayout', {
            path: item.route,
            name: routeName,
            component: () => import('@/views/PluginPageView.vue'),
            props: { pluginId: item.pluginId, pageRoute: item.pageRoute },
            meta: { pluginPage: true, title: item.label },
          })
        }
      }

      // Remove stale routes for disabled/unloaded plugins
      const activeRoutes = new Set(newMenus.map(m => m.route))
      for (const r of router.getRoutes()) {
        if (r.meta?.pluginPage && r.name !== 'PluginPagePlaceholder' && !activeRoutes.has(r.path)) {
          router.removeRoute(r.name!)
        }
      }

      menus.value = newMenus
      loaded.value = true
    } catch (e) {
      console.error('Failed to fetch plugin menus:', e)
    }
  }

  /** Re-resolve all labels for a new locale (no API call). */
  function reResolveLabels(newLocale: string) {
    menus.value = menus.value.map(m => ({
      ...m,
      label: resolveLabel(m.rawLabel, newLocale),
    }))
  }

  return { menus, loaded, fetchAndRegisterMenus, reResolveLabels }
})
