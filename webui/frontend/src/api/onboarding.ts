import apiClient from './client'
import type {
  OnboardingCompleteRequest,
  OnboardingStatusResponse,
  OnboardingTokenSetupRequest,
  OnboardingTokenSetupResponse,
} from '@/types'

export function getOnboardingStatus() {
  return apiClient.get<OnboardingStatusResponse>('/onboarding/status')
}

export function completeOnboarding(data: OnboardingCompleteRequest) {
  return apiClient.post<OnboardingStatusResponse>('/onboarding/complete', data)
}

// token=null marks the first-run token setup step as skipped
export function setupOnboardingToken(data: OnboardingTokenSetupRequest) {
  return apiClient.post<OnboardingTokenSetupResponse>('/onboarding/setup-token', data)
}
