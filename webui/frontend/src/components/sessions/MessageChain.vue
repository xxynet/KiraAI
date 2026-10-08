<template>
  <div class="space-y-2 text-sm break-words">
    <div v-for="(element, index) in chain" :key="index">
      <p v-if="element.type === 'text' || element.type === 'notice'" class="whitespace-pre-wrap">{{ element.text }}</p>
      <span v-else-if="element.type === 'at'" class="chat-bubble-mention">@{{ element.nickname || element.pid }}</span>
      <blockquote v-else-if="element.type === 'reply'" class="chat-bubble-quote border-l-2 pl-3 space-y-2">
        <p class="chat-bubble-quote-label text-xs">{{ $t('sessions.history.reply') }} · {{ element.message_id }}</p>
        <p v-if="element.message_content" class="whitespace-pre-wrap">{{ element.message_content }}</p>
        <MessageChain v-if="element.chain?.length && depth < 3" :chain="element.chain" :message-id="messageId" :path="elementPath(index)" :depth="depth + 1" />
      </blockquote>
      <MessageMedia v-else-if="['image', 'sticker', 'record', 'video', 'file'].includes(element.type)" :element="element" :message-id="messageId" :element-path="elementPath(index)" />
      <p v-else-if="element.type === 'emoji'">{{ $t('sessions.history.emoji') }} · {{ element.emoji_desc || element.emoji_id }}</p>
      <p v-else-if="element.type === 'poke'">{{ $t('sessions.history.poke') }} · {{ element.pid }}</p>
      <details v-else class="chat-bubble-data rounded p-2">
        <summary class="cursor-pointer">{{ element.type === 'json' ? $t('sessions.history.json') : $t('sessions.history.other', { type: element.type }) }}</summary>
        <pre class="whitespace-pre-wrap break-all mt-2 text-xs">{{ JSON.stringify(element.type === 'json' ? element.data : element, null, 2) }}</pre>
      </details>
    </div>
  </div>
</template>

<script setup lang="ts">
import type { MessageElement } from '@/types'
import MessageMedia from './MessageMedia.vue'

const props = withDefaults(defineProps<{
  chain: MessageElement[]
  messageId: string
  path?: string
  depth?: number
}>(), { path: '', depth: 0 })

function elementPath(index: number) {
  return props.path ? `${props.path}.${index}` : String(index)
}
</script>
