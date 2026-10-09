<template>
  <div class="bg-white dark:bg-gray-900 rounded-lg shadow-xl flex flex-col max-h-[90vh] modal-card">
    <div class="flex items-center justify-between gap-4 px-6 py-4 border-b border-gray-200 dark:border-gray-700">
      <div class="min-w-0">
        <h3 class="text-lg font-semibold text-theme-strong break-all">{{ session.title || session.session_id || session.adapter_name || session.id }}</h3>
        <p class="text-sm text-theme-subtle break-all">{{ session.id }}</p>
      </div>
      <button type="button" :aria-label="$t('sessions.history.close')" class="text-theme-faint text-theme-faint-hover" @click="$emit('close')"><IconClose class="w-6 h-6" /></button>
    </div>
    <div class="flex items-center justify-between gap-4 px-6 py-3">
      <p class="text-xs text-theme-subtle">{{ $t('sessions.history.hint') }}</p>
      <button type="button" class="shrink-0 text-sm text-blue-600 dark:text-blue-300 disabled:opacity-50" :disabled="loading" @click="loadMessages(true)">{{ $t('common.refresh') }}</button>
    </div>
    <div ref="messageList" class="px-6 pb-6 min-h-0 overflow-y-auto space-y-4 [overflow-anchor:none]" :aria-busy="loading">
      <div v-if="loading || error || nextCursor" class="text-center text-sm">
        <div v-if="error" class="text-red-600 dark:text-red-400" role="alert">
          <p>{{ $t('sessions.history.load_failed') }}</p>
          <button type="button" class="mt-2 text-blue-600 dark:text-blue-300" @click="loadMessages(messages.length === 0)">{{ $t('sessions.history.retry') }}</button>
        </div>
        <button v-else-if="nextCursor" type="button" class="w-full rounded-lg border border-gray-200 dark:border-gray-700 py-2 text-blue-600 dark:text-blue-300 disabled:opacity-50" :disabled="loading" @click="loadMessages(false)">{{ $t(loading ? 'sessions.history.loading' : 'sessions.history.load_more') }}</button>
        <p v-else-if="loading" class="py-4 text-theme-subtle" role="status">{{ $t('sessions.history.loading') }}</p>
      </div>
      <p v-if="!loading && !error && !messages.length" class="py-10 text-center text-theme-subtle">{{ $t('sessions.history.empty') }}</p>
      <article v-for="message in messages" :key="message.id" class="flex" :class="message.direction === 'outgoing' ? 'justify-end' : 'justify-start'">
        <div class="min-w-0 max-w-[85%] flex flex-col gap-2" :class="message.direction === 'outgoing' ? 'items-end' : 'items-start'">
          <div class="min-w-0 max-w-full text-xs text-theme-subtle" :class="message.direction === 'outgoing' ? 'text-right' : 'text-left'">
            <button
              v-if="message.sender_id"
              type="button"
              class="message-sender-toggle max-w-full break-all font-medium text-theme-body hover:underline"
              :aria-expanded="expandedSenderIds.has(message.id)"
              :aria-controls="`message-sender-${message.id}`"
              :title="$t(expandedSenderIds.has(message.id) ? 'sessions.history.hide_user_id' : 'sessions.history.show_user_id')"
              @click="toggleSenderId(message.id)"
            >{{ getSenderName(message) }}</button>
            <span v-else class="font-medium text-theme-body">{{ getSenderName(message) }}</span>
            <Transition name="sender-id">
              <div v-if="expandedSenderIds.has(message.id)" :id="`message-sender-${message.id}`" class="sender-id-grid">
                <div class="min-h-0 overflow-hidden">
                  <p class="pt-1 break-all">{{ $t('sessions.history.user_id') }}: {{ message.sender_id }}</p>
                </div>
              </div>
            </Transition>
          </div>
          <div class="min-w-0 max-w-full flex flex-col" :class="message.direction === 'outgoing' ? 'items-end' : 'items-start'">
            <div
              class="message-bubble chat-bubble min-w-0 max-w-full rounded-lg px-4 py-3 break-words"
              :class="{ 'chat-bubble--accent': message.direction === 'outgoing' }"
              tabindex="0"
              :aria-describedby="`message-time-${message.id}`"
            >
              <MessageChain v-if="message.chain.length" :chain="message.chain" :message-id="message.id" />
              <p v-else class="text-sm">{{ $t('sessions.history.empty_chain') }}</p>
            </div>
            <time :id="`message-time-${message.id}`" class="message-time mt-1 text-xs text-theme-subtle">{{ formatTime(message.timestamp, message.created_at) }}</time>
          </div>
          <p v-if="message.error_type" class="text-xs text-red-600 dark:text-red-400 break-all">{{ message.error_type }}</p>
        </div>
      </article>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, nextTick, onMounted, onBeforeUnmount } from 'vue'
import { useI18n } from 'vue-i18n'
import { getSessionMessages } from '@/api/session'
import { IconClose } from '@/components/icons'
import MessageChain from './MessageChain.vue'
import type { MessageRecord, SessionItem } from '@/types'

const props = defineProps<{ session: SessionItem }>()
defineEmits<{ close: [] }>()
const { t, locale } = useI18n()
const messages = ref<MessageRecord[]>([])
const nextCursor = ref<string | null>(null)
const loading = ref(false)
const error = ref(false)
const messageList = ref<HTMLElement | null>(null)
const expandedSenderIds = ref(new Set<string>())
let generation = 0

function getSenderName(message: MessageRecord) {
  if (message.sender_name && message.sender_name !== message.sender_id) return message.sender_name
  return t(message.direction === 'outgoing' ? 'sessions.history.bot' : 'sessions.history.unknown_sender')
}

function toggleSenderId(id: string) {
  if (expandedSenderIds.value.has(id)) expandedSenderIds.value.delete(id)
  else expandedSenderIds.value.add(id)
}

function formatTime(timestamp: number, createdAt: number) {
  const date = new Date(timestamp ? timestamp * 1000 : createdAt)
  return Number.isNaN(date.getTime()) ? '—' : date.toLocaleString(locale.value)
}

async function loadMessages(reset: boolean) {
  if (loading.value) return
  if (reset) {
    generation++
    messages.value = []
    expandedSenderIds.value.clear()
    nextCursor.value = null
  }
  const requestGeneration = generation
  let anchor: HTMLElement | null = null
  let anchorTop = 0
  let loaded = false
  loading.value = true
  error.value = false
  try {
    const { data } = await getSessionMessages(props.session.id, nextCursor.value || undefined)
    if (requestGeneration !== generation) return
    // Capture the current position after the request, so scrolling during loading is preserved.
    anchor = messageList.value?.querySelector<HTMLElement>('article') ?? null
    anchorTop = anchor?.getBoundingClientRect().top ?? 0
    const existing = new Set(messages.value.map(message => message.id))
    // The API pages newest first; reverse each page and prepend older messages.
    messages.value.unshift(...data.messages.filter(message => !existing.has(message.id)).reverse())
    nextCursor.value = data.next_cursor
    loaded = true
  } catch {
    if (requestGeneration === generation) error.value = true
  } finally {
    if (requestGeneration === generation) {
      loading.value = false
      await nextTick()
      const container = messageList.value
      if (loaded && requestGeneration === generation && container) {
        if (reset) {
          container.scrollTop = container.scrollHeight
        } else if (anchor) {
          container.scrollTop += anchor.getBoundingClientRect().top - anchorTop
        }
      }
    }
  }
}

onMounted(() => loadMessages(true))
onBeforeUnmount(() => { generation++ })
</script>

<style scoped>
.message-sender-toggle {
  text-align: inherit;
}

.sender-id-grid {
  display: grid;
  grid-template-rows: 1fr;
}

.sender-id-enter-active,
.sender-id-leave-active {
  transition: grid-template-rows 180ms ease, opacity 180ms ease, transform 180ms ease;
}

.sender-id-enter-from,
.sender-id-leave-to {
  grid-template-rows: 0fr;
  opacity: 0;
  transform: translateY(-4px);
}

.message-time {
  visibility: hidden;
  opacity: 0;
  transition: opacity 150ms ease, visibility 150ms ease;
}

.message-bubble:hover + .message-time,
.message-bubble:focus-visible + .message-time,
.message-bubble:has(:focus-visible) + .message-time {
  visibility: visible;
  opacity: 1;
}

.message-bubble:focus-visible {
  outline: 2px solid var(--color-focus-ring);
  outline-offset: 2px;
}

@media (prefers-reduced-motion: reduce) {
  .sender-id-enter-active,
  .sender-id-leave-active,
  .message-time {
    transition: none;
  }
}
</style>
