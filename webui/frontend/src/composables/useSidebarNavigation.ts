import { computed, type Component } from 'vue'
import { useI18n } from 'vue-i18n'
import { Box, MoreFilled, Folder } from '@element-plus/icons-vue'
import { usePluginMenuStore } from '@/stores/pluginMenu'
import { useSidebarStore } from '@/stores/sidebar'
import { iconMap } from '@/utils/iconMap'
import { builtinSidebarItems, DEFAULT_PLUGIN_GROUP_ID, reconcileSidebarLayout, type SidebarGroupEntry } from '@/navigation/sidebarLayout'

export interface SidebarNavItem {
  id: string
  route: string
  label: string
  icon: Component
  iconUrl: string | null
  isPlugin: boolean
}

export interface SidebarNavGroup {
  id: string
  label?: string
  icon?: Component
  items: SidebarNavItem[]
}

export function useSidebarNavigation() {
  const pluginStore = usePluginMenuStore()
  const sidebarStore = useSidebarStore()
  const { t } = useI18n()
  const items = computed<SidebarNavItem[]>(() => [
    ...builtinSidebarItems.map(item => ({ ...item, route: item.id, icon: iconMap[item.icon] || Box, iconUrl: null, isPlugin: false })),
    ...pluginStore.menus.map(menu => ({
      id: menu.route, route: menu.route, label: menu.label,
      // Only backend-issued URLs are fetched as custom plugin icons.
      icon: iconMap[menu.icon || ''] || Box,
      iconUrl: menu.icon?.startsWith('/api/') ? menu.icon : null,
      isPlugin: true,
    })),
  ])
  const itemMap = computed(() => new Map(items.value.map(item => [item.id, item])))
  const groupLabel = (group: SidebarGroupEntry) => group.name || t('nav.more_features')
  const navGroups = computed<SidebarNavGroup[]>(() => {
    const layout = reconcileSidebarLayout(sidebarStore.layout, items.value)
    return layout.flatMap(entry => {
      if (sidebarStore.hiddenItems.has(entry.id)) return []
      if (entry.type === 'item') {
        const item = itemMap.value.get(entry.id)
        return item ? [{ id: entry.id, items: [item] }] : []
      }
      const children = entry.items.filter(id => !sidebarStore.hiddenItems.has(id))
        .map(id => itemMap.value.get(id)).filter((item): item is SidebarNavItem => !!item)
      return children.length ? [{
        id: entry.id, label: groupLabel(entry), icon: entry.id === DEFAULT_PLUGIN_GROUP_ID ? MoreFilled : Folder, items: children,
      }] : []
    })
  })
  return { items, itemMap, navGroups, groupLabel }
}
