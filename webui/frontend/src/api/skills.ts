import apiClient from './client'

export interface SkillItem {
  id: string
  name: string
  description: string
  enabled: boolean
  path: string
  size_bytes: number
}

export function getSkills() {
  return apiClient.get<SkillItem[]>('/skills')
}

export function getSkillContent(skillName: string) {
  return apiClient.get<{ content: string }>(`/skills/${encodeURIComponent(skillName)}/content`)
}

export function updateSkillContent(skillName: string, content: string, originalContent: string) {
  return apiClient.put<{ skill_name: string; description: string; saved: boolean }>(
    `/skills/${encodeURIComponent(skillName)}/content`,
    { content, original_content: originalContent },
  )
}

export function toggleSkill(skillName: string, enabled: boolean) {
  return apiClient.post(`/skills/${encodeURIComponent(skillName)}/enabled`, { enabled })
}

export function refreshSkills() {
  return apiClient.post('/skills/refresh')
}

export function uploadSkill(file: File) {
  const formData = new FormData()
  formData.append('file', file)
  return apiClient.post('/skills/upload', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
  })
}

export function exportSkill(skillName: string) {
  return apiClient.get(`/skills/${encodeURIComponent(skillName)}/export`, { responseType: 'blob' })
}

export function deleteSkill(skillName: string) {
  return apiClient.delete(`/skills/${encodeURIComponent(skillName)}`)
}
