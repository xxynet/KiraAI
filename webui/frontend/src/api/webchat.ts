import apiClient from './client'
import type { MessageElement } from '@/types'

export interface WebChatProfile {
  nickname: string
  peer_nickname: string
  description: string
}
export interface WebChatRequest {
  id: string
  status: 'sent' | 'failed' | 'interrupted'
}
export interface WebChatMessage {
  id: string
  seq: number
  direction: string
  sender_name: string
  timestamp: number
  chain: MessageElement[]
}
export const getWebChat = (signal?: AbortSignal) =>
  apiClient.get<{ profile: WebChatProfile | null; request: WebChatRequest | null }>('/webchat', { signal })
export const saveWebChatProfile = (profile: WebChatProfile) => apiClient.put<WebChatProfile>('/webchat/profile', profile)
export const sendWebChatMessage = (request_id: string, text: string) =>
  apiClient.post<WebChatRequest>('/webchat/messages', { request_id, text })
export const getWebChatMessages = (params: { before?: number; after?: number }, signal?: AbortSignal) =>
  apiClient.get<{ messages: WebChatMessage[]; has_more: boolean }>('/webchat/messages', { params, signal })
