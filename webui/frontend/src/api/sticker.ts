import apiClient from './client'
import type { StickerItem, StickerUpdateRequest } from '@/types'

export function getStickers() {
  return apiClient.get<StickerItem[]>('/stickers')
}

export function uploadSticker(file: File, id?: string, desc?: string) {
  const formData = new FormData()
  formData.append('file', file)
  if (id) formData.append('id', id)
  if (desc) formData.append('description', desc)
  return apiClient.post<StickerItem>('/stickers', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
  })
}

export function getSticker(id: string) {
  return apiClient.get<StickerItem>(`/stickers/${id}`)
}

export function updateSticker(id: string, data: StickerUpdateRequest) {
  return apiClient.put(`/stickers/${id}`, data)
}

export function deleteSticker(id: string) {
  return apiClient.delete(`/stickers/${id}`)
}
