import { defineStore } from 'pinia'
import { ref } from 'vue'
import { getPlugins } from '@/api/plugin'
import router from '@/router'

export interface PluginMenuItem {
  pluginId: string
  pluginName: string
  route: string       // Vue Router path, e.g. /plugin-page/my-plugin/dashboard
  pageRoute: string   // The page route segment passed to PluginPageView
  label: string
  icon: string | null
  order: number
}

export const usePluginMenuStore = defineStore('pluginMenu', () => {
  const menus = ref<PluginMenuItem[]>([])
  const loaded = ref(false)

  async function fetchAndRegisterMenus() {
    try {
      const { data } = await getPlugins()
      const newMenus: PluginMenuItem[] = []
      const seenRoutes = new Set<string>()

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
            label: menu.label,
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

  return { menus, loaded, fetchAndRegisterMenus }
})
