import apiClient from './client'

export function getSkills() {
  return apiClient.get<any[]>('/skills')
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
