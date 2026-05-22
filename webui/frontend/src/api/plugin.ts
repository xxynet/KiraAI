import apiClient from './client'
import type {
  PluginItem,
  PluginConfigUpdateRequest,
  PluginInstallGithubRequest,
  PluginInstallResult,
} from '@/types'

export function getPlugins() {
  return apiClient.get<PluginItem[]>('/plugins')
}

export function getPluginConfig(pluginId: string) {
  return apiClient.get<{ config: Record<string, any>; schema: Record<string, any> }>(`/plugins/${encodeURIComponent(pluginId)}/config`)
}

export function updatePluginConfig(pluginId: string, data: PluginConfigUpdateRequest) {
  return apiClient.put(`/plugins/${encodeURIComponent(pluginId)}/config`, data)
}

export function togglePlugin(pluginId: string, enabled: boolean) {
  return apiClient.post(`/plugins/${encodeURIComponent(pluginId)}/enabled`, { enabled })
}

export function reloadPlugin(pluginId: string) {
  return apiClient.post<{ plugin_id: string; reloaded: boolean; error?: string }>(`/plugins/${encodeURIComponent(pluginId)}/reload`)
}

export function deletePlugin(pluginId: string, options?: { deleteConfig?: boolean; deleteData?: boolean }) {
  const params = new URLSearchParams()
  if (options?.deleteConfig) params.set('delete_config', 'true')
  if (options?.deleteData) params.set('delete_data', 'true')
  const qs = params.toString()
  return apiClient.delete(`/plugins/${encodeURIComponent(pluginId)}${qs ? '?' + qs : ''}`)
}

export function installFromGithub(data: PluginInstallGithubRequest) {
  return apiClient.post<PluginInstallResult>('/plugins/install/github', data)
}

export function installFromUpload(file: File) {
  const formData = new FormData()
  formData.append('file', file)
  return apiClient.post<PluginInstallResult>('/plugins/install/upload', formData)
}
