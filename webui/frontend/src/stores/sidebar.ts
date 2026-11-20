import { defineStore } from 'pinia'
import { ref } from 'vue'
import { normalizeSidebarLayout, type SidebarLayoutEntry } from '@/navigation/sidebarLayout'

const STORAGE_KEY = 'sidebar_layout'
const OPENED_ITEMS_KEY = 'sidebar_opened_items'

function loadLayout(): SidebarLayoutEntry[] | null {
  const saved = localStorage.getItem(STORAGE_KEY)
  if (saved === null) return null
  try {
    return normalizeSidebarLayout(JSON.parse(saved))
  } catch (error) {
    console.error('Failed to load sidebar layout:', error)
    return null
  }
}

function loadOpenedItems(): Set<string> | null {
  try {
    const saved = localStorage.getItem(OPENED_ITEMS_KEY)
    if (saved === null) return null
    const ids: unknown = JSON.parse(saved)
    if (!Array.isArray(ids)) throw new Error('Sidebar opened items must be an array')
    return new Set(ids.filter((id): id is string => typeof id === 'string' && /^[a-zA-Z0-9_-]+$/.test(id)))
  } catch (error) {
    console.error('Failed to load sidebar opened items:', error)
    return null
  }
}

export const useSidebarStore = defineStore('sidebar', () => {
  const layout = ref<SidebarLayoutEntry[] | null>(loadLayout())
  const savedOpenedItems = loadOpenedItems()
  const expandedGroups = ref(savedOpenedItems ?? new Set<string>())
  const hasSavedOpenedItems = ref(savedOpenedItems !== null)

  function setLayout(value: SidebarLayoutEntry[] | null) {
    const normalized = normalizeSidebarLayout(value)
    if (normalized === null) localStorage.removeItem(STORAGE_KEY)
    else localStorage.setItem(STORAGE_KEY, JSON.stringify(normalized))
    layout.value = normalized
  }

  function setGroupExpanded(id: string, expanded: boolean) {
    if (expandedGroups.value.has(id) === expanded) return
    const next = new Set(expandedGroups.value)
    if (expanded) next.add(id)
    else next.delete(id)
    expandedGroups.value = next
    try {
      localStorage.setItem(OPENED_ITEMS_KEY, JSON.stringify([...next]))
      hasSavedOpenedItems.value = true
    } catch (error) {
      console.error('Failed to save sidebar opened items:', error)
    }
  }

  return { layout, setLayout, expandedGroups, hasSavedOpenedItems, setGroupExpanded }
})
