import apiClient from './client'
import type { ScopeResponse } from '@/types'

export function getScope() {
  return apiClient.get<ScopeResponse>('/scope')
}

export function updateScope(config: Pick<ScopeResponse, 'mcp_scopes' | 'skill_scopes' | 'subagent_scopes'>) {
  return apiClient.put('/scope', config)
}
