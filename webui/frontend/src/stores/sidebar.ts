import { defineStore } from 'pinia'
import { ref } from 'vue'
import { normalizeSidebarLayout, type SidebarLayoutEntry } from '@/navigation/sidebarLayout'

const STORAGE_KEY = 'sidebar_layout'

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

export const useSidebarStore = defineStore('sidebar', () => {
  const layout = ref<SidebarLayoutEntry[] | null>(loadLayout())

  function setLayout(value: SidebarLayoutEntry[] | null) {
    const normalized = normalizeSidebarLayout(value)
    if (normalized === null) localStorage.removeItem(STORAGE_KEY)
    else localStorage.setItem(STORAGE_KEY, JSON.stringify(normalized))
    layout.value = normalized
  }

  return { layout, setLayout }
})
