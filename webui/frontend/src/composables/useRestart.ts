import { restartApplication } from '@/api/system'
import apiClient from '@/api/client'

export interface RestartOptions {
  maxRetries?: number
  intervalMs?: number
  probeEndpoint?: string
}

/**
 * Poll the server until it comes back (used when the server is restarting on its own).
 * Resolves when the server responds, rejects on timeout.
 */
export async function waitUntilReady(options: RestartOptions = {}): Promise<void> {
  const {
    maxRetries = 60,
    intervalMs = 1000,
    probeEndpoint = '/overview',
  } = options

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
  } catch (err: any) {
    // Network errors are expected (server already shutting down).
    // HTTP errors (auth, 5xx) are real failures — propagate them.
    if (err?.response) throw err
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
