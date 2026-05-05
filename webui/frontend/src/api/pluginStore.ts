import type { PluginStoreSource, PluginStoreItem } from '@/types'
import apiClient from './client'

/**
 * Get all configured plugin sources from backend
 */
export async function getSources(): Promise<PluginStoreSource[]> {
  const res = await apiClient.get('/plugin-store/sources')
  return res.data
}

/**
 * Add a new plugin source to backend
 */
export async function addSource(name: string, url: string): Promise<PluginStoreSource> {
  const res = await apiClient.post('/plugin-store/sources', { name, url })
  return res.data
}

/**
 * Delete a plugin source by ID
 */
export async function deleteSource(sourceId: string): Promise<void> {
  await apiClient.delete(`/plugin-store/sources/${sourceId}`)
}

/**
 * Set a source as the current active source
 */
export async function setCurrentSource(sourceId: string): Promise<void> {
  await apiClient.post(`/plugin-store/sources/${sourceId}/current`)
}

/**
 * Fetch plugins from a given source URL via backend API.
 * The backend parses the source JSON and returns normalized PluginStoreItem[].
 * @param sourceId  The DB source id — required for force_refresh to update the cache file.
 * @param forceRefresh If true, bypass cache and re-fetch from remote URL.
 */
export async function fetchPluginsFromSource(sourceId: string, forceRefresh: boolean = false): Promise<PluginStoreItem[]> {
  const res = await apiClient.post('/plugin-store/fetch', { source_id: sourceId, force_refresh: forceRefresh })
  return res.data
}
