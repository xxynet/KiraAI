import apiClient from './client'
import type { McpServerItem, McpServerCreateRequest, McpServerConfigUpdateRequest } from '@/types'

export function getMcpServers() {
  return apiClient.get<McpServerItem[]>('/mcp-servers')
}

export function createMcpServer(data: McpServerCreateRequest) {
  return apiClient.post<McpServerItem>('/mcp-servers', data)
}

export function getMcpServerConfig(serverId: string) {
  return apiClient.get<any>(`/mcp-servers/${encodeURIComponent(serverId)}/config`)
}

export function updateMcpServerConfig(serverId: string, data: McpServerConfigUpdateRequest) {
  return apiClient.put(`/mcp-servers/${encodeURIComponent(serverId)}/config`, data)
}

export function toggleMcpServer(serverId: string, enabled: boolean) {
  return apiClient.post(`/mcp-servers/${encodeURIComponent(serverId)}/enabled`, { enabled })
}

export function deleteMcpServer(serverId: string) {
  return apiClient.delete(`/mcp-servers/${encodeURIComponent(serverId)}`)
}
