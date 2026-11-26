import type { MessageElement } from '@/types'

export function messageText(chain: MessageElement[], t: (key: string, values?: Record<string, string>) => string): string {
  return chain.map(element => {
    if (element.type === 'text' || element.type === 'notice') return element.text || ''
    if (element.type === 'reply') return element.chain ? messageText(element.chain, t) : element.message_content || ''
    if (element.type === 'at') return `@${element.nickname || element.pid || ''}`
    if (element.type === 'json') return JSON.stringify(element.data) ?? ''
    const label = ['emoji', 'poke', 'image', 'sticker', 'record', 'video', 'file'].includes(element.type)
      ? t(`sessions.history.${element.type}`) : t('sessions.history.other', { type: element.type })
    return element.name || element.caption || element.transcript || element.description || element.emoji_desc || `[${label}]`
  }).filter(Boolean).join('\n')
}
