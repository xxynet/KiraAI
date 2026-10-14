import apiClient from './client'

// ── Storage ───────────────────────────────────────────────────────────────

export interface DirectoryEntry {
  name: string
  path: string
  size_bytes: number
  file_count: number
}

export interface StorageInfoResponse {
  data_path: string
  total_size_bytes: number
  disk_total_bytes: number
  disk_used_bytes: number
  disk_free_bytes: number
  directories: DirectoryEntry[]
}

export interface BackupItem {
  filename: string
  size_bytes: number
  created_at: string
}

export function getStorageInfo() {
  return apiClient.get<StorageInfoResponse>('/settings/storage')
}

export interface BackupProgress {
  id: string
  status: 'queued' | 'running' | 'completed' | 'failed'
  stage: 'queued' | 'scanning' | 'compressing' | 'finalizing' | 'completed' | 'failed'
  percent: number
  result: BackupItem | null
  error: 'backup_exists' | null
}

export function createBackup() {
  return apiClient.post<BackupProgress>('/settings/backup/tasks')
}

export function getActiveBackup(signal?: AbortSignal) {
  return apiClient.get<BackupProgress | null>('/settings/backup/tasks/active', { signal })
}

export function getBackupProgress(taskId: string, signal?: AbortSignal) {
  return apiClient.get<BackupProgress>('/settings/backup/tasks/' + taskId, { signal })
}

export function listBackups() {
  return apiClient.get<BackupItem[]>('/settings/backup/list')
}

export function deleteBackup(filename: string) {
  return apiClient.delete(`/settings/backup/${filename}`)
}

export function restoreFromBackup(filename: string) {
  return apiClient.post(`/settings/backup/${filename}/restore`)
}

export function restoreBackup(file: File) {
  const formData = new FormData()
  formData.append('file', file)
  return apiClient.post('/settings/restore', formData)
}

export function changeAccessToken(oldToken: string, newToken: string) {
  return apiClient.post('/settings/change-token', { old_token: oldToken, new_token: newToken })
}
