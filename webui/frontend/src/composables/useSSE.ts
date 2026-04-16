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

    eventSource.onerror = () => {
      connected.value = false
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
