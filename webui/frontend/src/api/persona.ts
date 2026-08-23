import apiClient from './client'
import type { PersonaBase, PersonaResponse, PersonaContentResponse, PersonaContentUpdateRequest } from '@/types'

export function getPersonas() {
  return apiClient.get<PersonaResponse[]>('/personas')
}

export function createPersona(data: PersonaBase) {
  return apiClient.post<PersonaResponse>('/personas', data)
}

export interface PersonaGeneratorMessage {
  role: 'user' | 'assistant'
  content: string
}

export interface PersonaGeneratorTurnResponse {
  type: 'question' | 'proposal'
  question?: string
  options: string[]
  allow_custom: boolean
  name?: string
  format?: string
  content?: string
}

export type PersonaGeneratorStreamEvent =
  | { type: 'text', content: string }
  | { type: 'question', question: string, options: string[], allow_custom: boolean }
  | { type: 'proposal', name: string, format: string, content: string }
  | { type: 'error', message: string }

export async function streamPersonaGenerator(
  messages: PersonaGeneratorMessage[],
  onEvent: (event: PersonaGeneratorStreamEvent) => void,
) {
  const token = localStorage.getItem('jwt_token')
  const response = await fetch('/api/personas/generator/stream', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify({ messages }),
  })
  if (response.status === 401) {
    localStorage.removeItem('jwt_token')
    window.location.href = '/login'
    throw new Error('Unauthorized')
  }
  if (!response.ok || !response.body) {
    throw new Error(`Request failed (${response.status})`)
  }

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  while (true) {
    const { value, done } = await reader.read()
    buffer += decoder.decode(value || new Uint8Array(), { stream: !done })
    const events = buffer.split('\n\n')
    buffer = events.pop() || ''
    for (const event of events) {
      const data = event.split('\n').find((line) => line.startsWith('data: '))?.slice(6)
      if (data) onEvent(JSON.parse(data) as PersonaGeneratorStreamEvent)
    }
    if (done) break
  }
}

export function getPersona(id: string) {
  return apiClient.get<PersonaResponse>(`/personas/${encodeURIComponent(id)}`)
}

export function updatePersona(id: string, data: Partial<PersonaBase>) {
  return apiClient.put<PersonaResponse>(`/personas/${encodeURIComponent(id)}`, data)
}

export function deletePersona(id: string) {
  return apiClient.delete(`/personas/${encodeURIComponent(id)}`)
}

export function getCurrentPersonaContent() {
  return apiClient.get<PersonaContentResponse>('/personas/current/content')
}

export function updateCurrentPersonaContent(data: PersonaContentUpdateRequest) {
  return apiClient.put<PersonaContentResponse>('/personas/current/content', data)
}

export function getActivePersona() {
  return apiClient.get<PersonaResponse>('/personas/active')
}

export function setActivePersona(personaId: string) {
  return apiClient.put('/personas/active', { persona_id: personaId })
}
