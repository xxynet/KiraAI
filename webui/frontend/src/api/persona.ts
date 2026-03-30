import apiClient from './client'
import type { PersonaBase, PersonaResponse } from '@/types'

export function getPersonas() {
  return apiClient.get<PersonaResponse[]>('/personas')
}

export function createPersona(data: PersonaBase) {
  return apiClient.post<PersonaResponse>('/personas', data)
}

export function getPersona(id: string) {
  return apiClient.get<PersonaResponse>(`/personas/${id}`)
}

export function updatePersona(id: string, data: Partial<PersonaBase>) {
  return apiClient.put<PersonaResponse>(`/personas/${id}`, data)
}

export function deletePersona(id: string) {
  return apiClient.delete(`/personas/${id}`)
}

export function getCurrentPersonaContent() {
  return apiClient.get<{ content: string; format: string }>('/personas/current/content')
}

export function updateCurrentPersonaContent(data: { content: string; format?: string }) {
  return apiClient.put<{ content: string; format: string }>('/personas/current/content', data)
}
