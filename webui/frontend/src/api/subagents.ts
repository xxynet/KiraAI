import apiClient from './client'

export interface SubagentPreset {
  id: string
  name: string
  description: string
  instruction_source: 'persona' | 'custom'
  persona_id: string | null
  instruction: string
  max_steps: number
  tool_mode: 'inherit' | 'exclude' | 'custom'
  tools: string[]
  skills: string[]
  enabled: boolean
  model: string | null
}

export type SubagentPresetInput = Omit<SubagentPreset, 'id'>

export function getSubagentPresets() {
  return apiClient.get<{ presets: SubagentPreset[] }>('/subagents/presets')
}

export function createSubagentPreset(data: SubagentPresetInput) {
  return apiClient.post<SubagentPreset>('/subagents/presets', data)
}

export function updateSubagentPreset(id: string, data: SubagentPresetInput) {
  return apiClient.put<SubagentPreset>(`/subagents/presets/${encodeURIComponent(id)}`, data)
}

export function deleteSubagentPreset(id: string) {
  return apiClient.delete(`/subagents/presets/${encodeURIComponent(id)}`)
}
