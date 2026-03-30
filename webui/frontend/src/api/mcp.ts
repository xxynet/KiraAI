import apiClient from './client'
import type { McpServerItem, McpServerCreateRequest, McpServerConfigUpdateRequest } from '@/types'

export function getMcpServers() {
  return apiClient.get<McpServerItem[]>('/mcp-servers')
}

export function createMcpServer(data: McpServerCreateRequest) {
  return apiClient.post<McpServerItem>('/mcp-servers', data)
}

export function getMcpServerConfig(serverName: string) {
  return apiClient.get<any>(`/mcp-servers/${serverName}/config`)
}

export function updateMcpServerConfig(serverName: string, data: McpServerConfigUpdateRequest) {
  return apiClient.put(`/mcp-servers/${serverName}/config`, data)
}

export function updateMcpServer(serverName: string, data: McpServerConfigUpdateRequest) {
  return apiClient.put(`/mcp-servers/${serverName}`, data)
}

export function toggleMcpServer(serverName: string, enabled: boolean) {
  return apiClient.post(`/mcp-servers/${serverName}/enabled`, { enabled })
}

export function deleteMcpServer(serverName: string) {
  return apiClient.delete(`/mcp-servers/${serverName}`)
}
