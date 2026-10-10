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
export interface WebChatAttachment {
  file: File
  kind: 'image' | 'file'
}
export function sendWebChatMessage(request_id: string, text: string, attachments: WebChatAttachment[] = []) {
  if (!attachments.length) return apiClient.post<WebChatRequest>('/webchat/messages', { request_id, text })
  const form = new FormData()
  form.append('request_id', request_id)
  form.append('text', text)
  attachments.forEach(({ file, kind }) => {
    form.append('files', file)
    form.append('kinds', kind)
  })
  return apiClient.post<WebChatRequest>('/webchat/messages/upload', form)
}
export const getWebChatMessages = (params: { before?: number; after?: number }, signal?: AbortSignal) =>
  apiClient.get<{ messages: WebChatMessage[]; has_more: boolean }>('/webchat/messages', { params, signal })

export const deleteWebChatMessages = () => apiClient.delete('/webchat/messages')
