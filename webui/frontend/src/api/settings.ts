import apiClient from './client'
import type { SettingsRequest, SettingsResponse } from '@/types'

export function getSettings() {
  return apiClient.get<SettingsResponse>('/settings')
}

export function updateSettings(data: SettingsRequest) {
  return apiClient.put<SettingsResponse>('/settings', data)
}
