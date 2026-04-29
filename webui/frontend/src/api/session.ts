import apiClient from './client'
import type { SessionItem, SessionDetail } from '@/types'

export function getSessions() {
  return apiClient.get<{ sessions: SessionItem[] }>('/sessions')
}

export function getSession(id: string) {
  return apiClient.get<SessionDetail>(`/sessions/${encodeURIComponent(id)}`)
}

export function updateSession(id: string, data: { title?: string; description?: string; messages?: any[]; metadata?: Record<string, any> }) {
  return apiClient.put(`/sessions/${encodeURIComponent(id)}`, data)
}

export function deleteSession(id: string) {
  return apiClient.delete(`/sessions/${encodeURIComponent(id)}`)
}
