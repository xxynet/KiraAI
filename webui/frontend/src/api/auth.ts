import apiClient from './client'
import type { TokenLoginRequest, LoginResponse, AuthConfigResponse } from '@/types'

export function getAuthConfig() {
  return apiClient.get<AuthConfigResponse>('/auth/config')
}

export function login(data: TokenLoginRequest) {
  return apiClient.post<LoginResponse>('/auth/login', data)
}

export function logout() {
  return apiClient.post('/auth/logout')
}

export function healthCheck() {
  return apiClient.get<{ status: string; lifecycle_available: boolean }>('/health')
}
