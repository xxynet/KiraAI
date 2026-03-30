import { ref, onUnmounted } from 'vue'
import { EventSourcePolyfill } from 'event-source-polyfill'

export function useSSE() {
  const messages = ref<string[]>([])
  const connected = ref(false)
  let eventSource: EventSource | EventSourcePolyfill | null = null

  function connect(url: string, token?: string) {
    disconnect()

    const authToken = token || localStorage.getItem('jwt_token')

    try {
      // Try polyfill with custom headers first
      eventSource = new EventSourcePolyfill(url, {
        headers: { Authorization: `Bearer ${authToken}` },
        heartbeatTimeout: 300000,
        withCredentials: true,
      })
    } catch {
      // Fallback to native EventSource with query param
      const separator = url.includes('?') ? '&' : '?'
      eventSource = new EventSource(`${url}${separator}token=${encodeURIComponent(authToken || '')}`)
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
    connect,
    disconnect,
    clear,
  }
}
