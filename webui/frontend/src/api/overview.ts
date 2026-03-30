import apiClient from './client'
import type { OverviewResponse, VersionResponse } from '@/types'

export function getOverview() {
  return apiClient.get<OverviewResponse>('/overview')
}

export function getVersion() {
  return apiClient.get<VersionResponse>('/version')
}
