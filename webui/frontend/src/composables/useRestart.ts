import { restartApplication } from '@/api/system'
import apiClient from '@/api/client'

export interface RestartOptions {
  maxRetries?: number
  intervalMs?: number
  probeEndpoint?: string
  requireRestart?: boolean
}

function resolveOptions(options: RestartOptions): Required<RestartOptions> {
  return {
    maxRetries: options.maxRetries ?? 60,
    intervalMs: options.intervalMs ?? 1000,
    probeEndpoint: options.probeEndpoint ?? '/overview',
    requireRestart: options.requireRestart ?? false,
  }
}

async function pollUntilReady(opts: Required<RestartOptions>): Promise<void> {
  let observedUnavailable = !opts.requireRestart
  for (let i = 0; i < opts.maxRetries; i++) {
    try {
      await apiClient.get(opts.probeEndpoint)
      if (observedUnavailable) {
        window.location.reload()
        return
      }
    } catch {
      observedUnavailable = true
    }
    await new Promise(r => setTimeout(r, opts.intervalMs))
  }

  throw new Error('Restart timed out')
}

/**
 * Poll the server until it comes back (used when the server is restarting on its own).
 * Resolves when the server responds, rejects on timeout.
 */
export async function waitUntilReady(options: RestartOptions = {}): Promise<void> {
  return pollUntilReady(resolveOptions(options))
}

/**
 * Trigger a server restart and poll until it comes back.
 * Resolves when the server responds, rejects on timeout.
 */
export async function restartAndWait(options: RestartOptions = {}): Promise<void> {
  try {
    await restartApplication()
  } catch (err: any) {
    // Network errors are expected (server already shutting down).
    // HTTP errors (auth, 5xx) are real failures — propagate them.
    if (err?.response) throw err
  }

  return pollUntilReady(resolveOptions(options))
}
