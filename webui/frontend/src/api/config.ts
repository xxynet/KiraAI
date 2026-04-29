import apiClient from './client'
import type { ConfigurationData } from '@/types'

export function getConfiguration() {
  return apiClient.get<ConfigurationData>('/configuration')
}

export function saveConfiguration(config: Record<string, any>) {
  return apiClient.post('/configuration', config)
}
