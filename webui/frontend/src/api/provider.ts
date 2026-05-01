import apiClient from './client'
import type { ProviderBase, ProviderResponse, ModelCreateRequest, ModelUpdateRequest } from '@/types'

export function getProviderTypes() {
  return apiClient.get<string[]>('/provider-types')
}

export function getProviderSchema(providerType: string) {
  return apiClient.get<any>(`/providers/schema/${encodeURIComponent(providerType)}`)
}

export function getProviders() {
  return apiClient.get<ProviderResponse[]>('/providers')
}

export function createProvider(data: ProviderBase) {
  return apiClient.post<ProviderResponse>('/providers', data)
}

export function getProvider(id: string) {
  return apiClient.get<ProviderResponse>(`/providers/${encodeURIComponent(id)}`)
}

export function updateProvider(id: string, data: Partial<ProviderBase>) {
  return apiClient.put<ProviderResponse>(`/providers/${encodeURIComponent(id)}`, data)
}

export function deleteProvider(id: string) {
  return apiClient.delete(`/providers/${encodeURIComponent(id)}`)
}

export function addModel(providerId: string, data: ModelCreateRequest) {
  return apiClient.post(`/providers/${encodeURIComponent(providerId)}/models`, data)
}

export function getModels(providerId: string) {
  return apiClient.get<Record<string, any>>(`/providers/${encodeURIComponent(providerId)}/models`)
}

export function updateModel(providerId: string, modelType: string, modelId: string, data: ModelUpdateRequest) {
  return apiClient.put(`/providers/${encodeURIComponent(providerId)}/models/${encodeURIComponent(modelType)}/${encodeURIComponent(modelId)}`, data)
}

export function deleteModel(providerId: string, modelType: string, modelId: string) {
  return apiClient.delete(`/providers/${encodeURIComponent(providerId)}/models/${encodeURIComponent(modelType)}/${encodeURIComponent(modelId)}`)
}

export function fetchRemoteModels(providerId: string, modelType: string = 'llm') {
  return apiClient.get<{ models: Array<{ id: string; name?: string; description?: string }> }>(
    `/providers/${encodeURIComponent(providerId)}/remote-models`,
    { params: { model_type: modelType } }
  )
}

export function syncModels(providerId: string, modelType: string, data: { add_ids: string[]; delete_ids: string[] }) {
  return apiClient.post<{ added: number; removed: number; errors: string[] }>(
    `/providers/${encodeURIComponent(providerId)}/models/sync/${encodeURIComponent(modelType)}`,
    data
  )
}

export function healthCheck(providerId: string, modelType: string, modelId: string) {
  return apiClient.post<{ success: boolean; latency?: number; error?: string }>(
    `/providers/${encodeURIComponent(providerId)}/models/${encodeURIComponent(modelType)}/${encodeURIComponent(modelId)}/health-check`
  )
}
