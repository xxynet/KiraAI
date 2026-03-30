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
  return apiClient.get<{ config: Record<string, any>; schema: Record<string, any> }>(`/plugins/${pluginId}/config`)
}

export function updatePluginConfig(pluginId: string, data: PluginConfigUpdateRequest) {
  return apiClient.put(`/plugins/${pluginId}/config`, data)
}

export function togglePlugin(pluginId: string, enabled: boolean) {
  return apiClient.post(`/plugins/${pluginId}/enabled`, { enabled })
}

export function deletePlugin(pluginId: string) {
  return apiClient.delete(`/plugins/${pluginId}`)
}

export function installFromGithub(data: PluginInstallGithubRequest) {
  return apiClient.post<PluginInstallResult>('/plugins/install/github', data)
}

export function installFromUpload(file: File) {
  const formData = new FormData()
  formData.append('file', file)
  return apiClient.post<PluginInstallResult>('/plugins/install/upload', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
  })
}
