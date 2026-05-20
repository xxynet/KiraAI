import apiClient from './client'

export function restartApplication() {
  return apiClient.post('/system/restart')
}
