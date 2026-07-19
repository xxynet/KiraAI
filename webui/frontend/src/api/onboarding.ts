import apiClient from './client'
import type { OnboardingCompleteRequest, OnboardingStatusResponse } from '@/types'

export function getOnboardingStatus() {
  return apiClient.get<OnboardingStatusResponse>('/onboarding/status')
}

export function completeOnboarding(data: OnboardingCompleteRequest) {
  return apiClient.post<OnboardingStatusResponse>('/onboarding/complete', data)
}
