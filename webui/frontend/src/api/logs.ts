import apiClient from './client'
import type { LogEntry, LogConfig } from '@/types'

export function getLogHistory(limit?: number) {
  return apiClient.get<{ logs: LogEntry[] }>('/log-history', {
    params: limit ? { limit } : undefined,
  })
}

export function getLogConfig() {
  return apiClient.get<LogConfig>('/log-config')
}
