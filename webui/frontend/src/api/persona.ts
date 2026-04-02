import apiClient from './client'
import type { PersonaBase, PersonaResponse, PersonaContentResponse, PersonaContentUpdateRequest } from '@/types'

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
  return apiClient.get<PersonaContentResponse>('/personas/current/content')
}

export function updateCurrentPersonaContent(data: PersonaContentUpdateRequest) {
  return apiClient.put<PersonaContentResponse>('/personas/current/content', data)
}
