import apiClient from './client'
import type { AdapterBase, AdapterResponse } from '@/types'

export function getAdapterPlatforms() {
  return apiClient.get<string[]>('/adapter-platforms')
}

export function getAdapterSchema(platform: string) {
  return apiClient.get<any>(`/adapters/schema/${platform}`)
}

export function getAdapters() {
  return apiClient.get<AdapterResponse[]>('/adapters')
}

export function createAdapter(data: AdapterBase) {
  return apiClient.post<AdapterResponse>('/adapters', data)
}

export function getAdapter(id: string) {
  return apiClient.get<AdapterResponse>(`/adapters/${id}`)
}

export function updateAdapter(id: string, data: Partial<AdapterBase>) {
  return apiClient.put<AdapterResponse>(`/adapters/${id}`, data)
}

export function deleteAdapter(id: string) {
  return apiClient.delete(`/adapters/${id}`)
}
