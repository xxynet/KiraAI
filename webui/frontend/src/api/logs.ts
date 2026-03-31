import apiClient from './client'
import type { LogEntry, LogConfig } from '@/types'

interface BackendLogEntry {
  time: string
  level: string
  name: string
  message: string
  color?: string
  raw?: string
}

export async function getLogHistory(limit?: number) {
  const res = await apiClient.get<{ logs: BackendLogEntry[] }>('/log-history', {
    params: limit !== undefined ? { limit } : undefined,
  })
  return {
    ...res,
    data: {
      ...res.data,
      logs: (res.data.logs || []).map((l): LogEntry => ({
        timestamp: l.time || '',
        level: l.level || 'info',
        message: l.message || '',
        logger: l.name || '',
      })),
    },
  }
}

export function getLogConfig() {
  return apiClient.get<LogConfig>('/log-config')
}
