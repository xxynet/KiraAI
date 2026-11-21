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

export interface SkillFileItem {
  path: string
  size_bytes: number
}

export interface SkillFileContent extends SkillFileItem {
  content: string | null
  kind: 'text' | 'image' | 'binary'
  reason: 'too_large' | 'non_text' | null
}

export function getSkillFiles(skillName: string) {
  return apiClient.get<SkillFileItem[]>(`/skills/${encodeURIComponent(skillName)}/files`)
}

export function getSkillFile(skillName: string, path: string) {
  return apiClient.get<SkillFileContent>(`/skills/${encodeURIComponent(skillName)}/file`, { params: { path } })
}

export function downloadSkillFile(skillName: string, path: string) {
  return apiClient.get<Blob>(`/skills/${encodeURIComponent(skillName)}/file/download`, {
    params: { path }, responseType: 'blob',
  })
}

export function updateSkillFile(skillName: string, path: string, content: string, originalContent: string) {
  return apiClient.put<{ skill_name: string; description: string; size_bytes: number; saved: boolean }>(
    `/skills/${encodeURIComponent(skillName)}/file`,
    { content, original_content: originalContent },
    { params: { path } },
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
