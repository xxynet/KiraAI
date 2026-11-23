import apiClient from './client'

// ── Storage ───────────────────────────────────────────────────────────────

export interface DirectoryEntry {
  name: string
  path: string
  size_bytes: number
  file_count: number
}

export type StorageCategoryId = 'image_descriptions' | 'message_archives' | 'temp' | 'logs' | 'update_packages'
export type ArchiveRetentionDays = 7 | 30 | 90

export interface StorageCategory {
  id: StorageCategoryId
  retention_days: ArchiveRetentionDays | null
  size_bytes: number
  item_count: number
  cleanable_bytes: number
  cleanable_count: number
  available: boolean
}

export interface StorageCleanupResponse {
  deleted_count: number
  deleted_bytes: number
  failed_count: number
}

export function cleanupStorage(category: StorageCategoryId, retentionDays: ArchiveRetentionDays = 30) {
  return apiClient.post<StorageCleanupResponse>(`/settings/storage/${category}/cleanup`, null, {
    params: { retention_days: retentionDays },
  })
}

export interface StorageUsageEntry {
  id: 'sessions' | 'media' | 'database' | 'plugins' | 'runtime' | 'backups' | 'temp' | 'logs' | 'other'
  size_bytes: number
}

export interface StorageInfoResponse {
  data_path: string
  total_size_bytes: number
  disk_total_bytes: number
  disk_used_bytes: number
  disk_free_bytes: number
  directories: DirectoryEntry[]
  categories: StorageCategory[]
  usage_breakdown: StorageUsageEntry[]
}

export interface BackupItem {
  filename: string
  size_bytes: number
  created_at: string
}

export function getStorageInfo(retentionDays: ArchiveRetentionDays = 30) {
  return apiClient.get<StorageInfoResponse>('/settings/storage', { params: { retention_days: retentionDays } })
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
