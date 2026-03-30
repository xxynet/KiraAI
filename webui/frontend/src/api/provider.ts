import apiClient from './client'
import type { ProviderBase, ProviderResponse, ModelCreateRequest, ModelUpdateRequest } from '@/types'

export function getProviderTypes() {
  return apiClient.get<string[]>('/provider-types')
}

export function getProviderSchema(providerType: string) {
  return apiClient.get<any>(`/providers/schema/${providerType}`)
}

export function getProviders() {
  return apiClient.get<ProviderResponse[]>('/providers')
}

export function createProvider(data: ProviderBase) {
  return apiClient.post<ProviderResponse>('/providers', data)
}

export function getProvider(id: string) {
  return apiClient.get<ProviderResponse>(`/providers/${id}`)
}

export function updateProvider(id: string, data: Partial<ProviderBase>) {
  return apiClient.put<ProviderResponse>(`/providers/${id}`, data)
}

export function deleteProvider(id: string) {
  return apiClient.delete(`/providers/${id}`)
}

export function addModel(providerId: string, data: ModelCreateRequest) {
  return apiClient.post(`/providers/${providerId}/models`, data)
}

export function getModels(providerId: string) {
  return apiClient.get<Record<string, any>>(`/providers/${providerId}/models`)
}

export function updateModel(providerId: string, modelType: string, modelId: string, data: ModelUpdateRequest) {
  return apiClient.put(`/providers/${providerId}/models/${modelType}/${modelId}`, data)
}

export function deleteModel(providerId: string, modelType: string, modelId: string) {
  return apiClient.delete(`/providers/${providerId}/models/${modelType}/${modelId}`)
}
