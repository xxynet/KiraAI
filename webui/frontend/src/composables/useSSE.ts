import { ref, onUnmounted } from 'vue'
import { EventSourcePolyfill } from 'event-source-polyfill'

export function useSSE() {
  const messages = ref<string[]>([])
  const connected = ref(false)
  const lastError = ref<string | null>(null)
  let eventSource: EventSource | EventSourcePolyfill | null = null

  function connect(url: string, token?: string) {
    disconnect()
    lastError.value = null

    const authToken = token || localStorage.getItem('jwt_token')
    if (!authToken) {
      // Fail closed — sending `Authorization: Bearer null` is worse than
      // not connecting at all: it still leaks a JWT-shaped request to the
      // server without actually authenticating and obscures the real cause.
      lastError.value = 'Missing auth token'
      connected.value = false
      return
    }

    try {
      // Always send the JWT via an Authorization header so it doesn't land in
      // URL history, proxy access logs, or server-side request logs. If the
      // polyfill cannot be constructed we fail closed instead of downgrading
      // to a query-parameter token.
      eventSource = new EventSourcePolyfill(url, {
        headers: { Authorization: `Bearer ${authToken}` },
        heartbeatTimeout: 300000,
        withCredentials: true,
      })
    } catch (err) {
      lastError.value = err instanceof Error ? err.message : 'SSE connection failed'
      connected.value = false
      return
    }

    eventSource.onopen = () => {
      connected.value = true
    }

    eventSource.onmessage = (event: MessageEvent) => {
      messages.value.push(event.data)
    }

    eventSource.onerror = (event: Event) => {
      connected.value = false
      // Surface a runtime failure so consumers can distinguish it from a
      // deliberate disconnect. Preserve a more specific message set earlier
      // (e.g. by the connect-time catch) instead of clobbering it.
      if (!lastError.value) {
        lastError.value = (event && (event as any).type) || 'SSE connection error'
      }
    }
  }

  function disconnect() {
    if (eventSource) {
      eventSource.close()
      eventSource = null
    }
    connected.value = false
  }

  function clear() {
    messages.value = []
  }

  onUnmounted(disconnect)

  return {
    messages,
    connected,
    lastError,
    connect,
    disconnect,
    clear,
  }
}
