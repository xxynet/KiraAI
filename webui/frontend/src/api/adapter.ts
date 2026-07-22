import apiClient from './client'
import type { AdapterBase, AdapterPlatform, AdapterResponse } from '@/types'
import type { AxiosPromise } from 'axios'

export function getAdapterPlatforms(details: true): AxiosPromise<AdapterPlatform[]>
export function getAdapterPlatforms(details?: false): AxiosPromise<string[]>
export function getAdapterPlatforms(details = false) {
  return apiClient.get<string[] | AdapterPlatform[]>('/adapter-platforms', {
    params: details ? { details: true } : undefined,
  })
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
