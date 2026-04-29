import apiClient from './client'
import type { AdapterBase, AdapterResponse } from '@/types'

export function getAdapterPlatforms() {
  return apiClient.get<string[]>('/adapter-platforms')
}

export function getAdapterSchema(platform: string) {
  return apiClient.get<any>(`/adapters/schema/${encodeURIComponent(platform)}`)
}

export function getAdapters() {
  return apiClient.get<AdapterResponse[]>('/adapters')
}

export function createAdapter(data: AdapterBase) {
  return apiClient.post<AdapterResponse>('/adapters', data)
}

export function getAdapter(id: string) {
  return apiClient.get<AdapterResponse>(`/adapters/${encodeURIComponent(id)}`)
}

export function updateAdapter(id: string, data: Partial<AdapterBase>) {
  return apiClient.put<AdapterResponse>(`/adapters/${encodeURIComponent(id)}`, data)
}

export function deleteAdapter(id: string) {
  return apiClient.delete(`/adapters/${encodeURIComponent(id)}`)
}
