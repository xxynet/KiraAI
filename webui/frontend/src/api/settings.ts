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

export function createBackup() {
  return apiClient.post('/settings/backup')
}

export function listBackups() {
  return apiClient.get<BackupItem[]>('/settings/backup/list')
}

export function downloadBackup(filename: string) {
  return apiClient.get(`/settings/backup/download/${filename}`, { responseType: 'blob' })
}

export function deleteBackup(filename: string) {
  return apiClient.delete(`/settings/backup/${filename}`)
}

export function restoreBackup(file: File) {
  const formData = new FormData()
  formData.append('file', file)
  return apiClient.post('/settings/restore', formData)
}
