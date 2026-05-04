import type { PluginStoreSource, PluginStoreItem } from '@/types'
import apiClient from './client'

const STORAGE_KEY_SOURCES = 'kira_plugin_store_sources'
const STORAGE_KEY_CURRENT = 'kira_plugin_store_current_source'

/**
 * Get all configured plugin sources from localStorage
 */
export function getSources(): PluginStoreSource[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY_SOURCES)
    return raw ? JSON.parse(raw) : []
  } catch {
    return []
  }
}

/**
 * Save plugin sources to localStorage
 */
export function saveSources(sources: PluginStoreSource[]): void {
  localStorage.setItem(STORAGE_KEY_SOURCES, JSON.stringify(sources))
}

/**
 * Get the currently active plugin source
 */
export function getCurrentSource(): PluginStoreSource | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY_CURRENT)
    return raw ? JSON.parse(raw) : null
  } catch {
    return null
  }
}

/**
 * Set the currently active plugin source
 */
export function setCurrentSource(source: PluginStoreSource | null): void {
  if (source) {
    localStorage.setItem(STORAGE_KEY_CURRENT, JSON.stringify(source))
  } else {
    localStorage.removeItem(STORAGE_KEY_CURRENT)
  }
}

/**
 * Fetch plugins from a given source URL via backend API.
 * The backend parses the source JSON and returns normalized PluginStoreItem[].
 */
export async function fetchPluginsFromSource(url: string): Promise<PluginStoreItem[]> {
  const res = await apiClient.post('/plugin-store/fetch', { url })
  return res.data
}
