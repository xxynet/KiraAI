import apiClient from './client'
import type { ScopeResponse, ScopeEntry } from '@/types'

export function getScope() {
  return apiClient.get<ScopeResponse>('/scope')
}

export function updateScope(config: { mcp_scopes: Record<string, ScopeEntry>; skill_scopes: Record<string, ScopeEntry> }) {
  return apiClient.put('/scope', config)
}
