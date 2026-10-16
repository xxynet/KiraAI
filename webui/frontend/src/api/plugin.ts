import apiClient from './client'
import type {
  PluginItem,
  PluginConfigUpdateRequest,
  PluginInstallGithubRequest,
  PluginInstallResult,
  PluginInstallTask,
  PluginUpdateCheckItem,
  PluginUpdateQueueItem,
  PluginUpdateTask,
  PluginTask,
} from '@/types'

export function getPlugins() {
  return apiClient.get<PluginItem[]>('/plugins')
}

export function getPluginConfig(pluginId: string) {
  return apiClient.get<{ config: Record<string, any>; schema: Record<string, any> }>(`/plugins/${encodeURIComponent(pluginId)}/config`)
}

export function getPluginReadme(pluginId: string) {
  return apiClient.get<{ readme: string | null }>(`/plugins/${encodeURIComponent(pluginId)}/readme`)
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

export function startGithubInstallTask(data: PluginInstallGithubRequest) {
  return apiClient.post<PluginInstallTask>('/plugins/install/github/tasks', data)
}

export function getActivePluginInstallTask() {
  return apiClient.get<PluginInstallTask | null>('/plugins/install/tasks/active')
}

export function getPluginInstallTask(taskId: string) {
  return apiClient.get<PluginInstallTask>(`/plugins/install/tasks/${encodeURIComponent(taskId)}`)
}

export function cancelPluginInstallTask(taskId: string) {
  return apiClient.post<PluginInstallTask>(`/plugins/install/tasks/${encodeURIComponent(taskId)}/cancel`)
}

export function checkPluginUpdates() {
  return apiClient.post<PluginUpdateCheckItem[]>('/plugins/updates/check')
}

export function updatePlugin(pluginId: string, data?: { gh_proxy?: string | null; commit_sha?: string | null }) {
  return apiClient.post<PluginInstallResult>(`/plugins/${encodeURIComponent(pluginId)}/update`, data || {})
}

export function enqueuePluginUpdates(items: PluginUpdateQueueItem[]) {
  return apiClient.post<PluginUpdateTask[]>('/plugins/updates/tasks', { items })
}

export function getPluginUpdateTasks() {
  return apiClient.get<PluginUpdateTask[]>('/plugins/updates/tasks')
}

export function cancelPluginUpdateTask(taskId: string) {
  return apiClient.post<PluginUpdateTask>('/plugins/updates/tasks/' + encodeURIComponent(taskId) + '/cancel')
}

export function clearFinishedPluginUpdateTasks() {
  return apiClient.delete<PluginUpdateTask[]>('/plugins/updates/tasks')
}

export function enqueueGithubInstall(data: PluginInstallGithubRequest) {
  return apiClient.post<PluginTask>('/plugins/tasks/install/github', data)
}

export function enqueueUploadInstall(file: File) {
  const formData = new FormData()
  formData.append('file', file)
  return apiClient.post<PluginTask>('/plugins/tasks/install/upload', formData)
}

export function enqueueTaskUpdates(items: PluginUpdateQueueItem[]) {
  return apiClient.post<PluginTask[]>('/plugins/tasks/updates', { items })
}

export function getPluginTasks() {
  return apiClient.get<PluginTask[]>('/plugins/tasks')
}

export function cancelPluginTask(taskId: string) {
  return apiClient.post<PluginTask>(`/plugins/tasks/${encodeURIComponent(taskId)}/cancel`)
}

export function retryPluginTask(taskId: string) {
  return apiClient.post<PluginTask>(`/plugins/tasks/${encodeURIComponent(taskId)}/retry`)
}

export function clearFinishedPluginTasks() {
  return apiClient.delete<PluginTask[]>('/plugins/tasks')
}