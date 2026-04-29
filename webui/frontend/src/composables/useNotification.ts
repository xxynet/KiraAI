import { reactive } from 'vue'

export type NotifyType = 'success' | 'error' | 'warning' | 'info'

export interface NotificationItem {
  id: number
  message: string
  type: NotifyType
}

let idCounter = 0

const notifications = reactive<NotificationItem[]>([])

export function notify(message: string, type: NotifyType = 'info', duration = 3000) {
  const id = ++idCounter
  notifications.push({ id, message, type })
  setTimeout(() => {
    const idx = notifications.findIndex(n => n.id === id)
    if (idx >= 0) notifications.splice(idx, 1)
  }, duration)
}

export function useNotification() {
  return { notifications, notify }
}
