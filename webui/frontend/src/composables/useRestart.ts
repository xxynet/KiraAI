import { restartApplication } from '@/api/system'
import apiClient from '@/api/client'

export interface RestartOptions {
  maxRetries?: number
  intervalMs?: number
  probeEndpoint?: string
}

/**
 * Trigger a server restart and poll until it comes back.
 * Resolves when the server responds, rejects on timeout.
 */
export async function restartAndWait(options: RestartOptions = {}): Promise<void> {
  const {
    maxRetries = 60,
    intervalMs = 1000,
    probeEndpoint = '/overview',
  } = options

  try {
    await restartApplication()
  } catch {
    // Expected — server is shutting down
  }

  for (let i = 0; i < maxRetries; i++) {
    await new Promise(r => setTimeout(r, intervalMs))
    try {
      await apiClient.get(probeEndpoint)
      window.location.reload()
      return
    } catch {
      // server not ready yet
    }
  }

  throw new Error('Restart timed out')
}
