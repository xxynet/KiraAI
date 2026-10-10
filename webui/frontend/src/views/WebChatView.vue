<template>
  <section class="flex min-h-0 flex-1 flex-col overflow-hidden">
    <div v-if="error" role="alert" class="mx-6 mt-4 shrink-0 rounded-lg bg-red-50 dark:bg-red-950 p-3 text-sm text-red-600 dark:text-red-300">
      {{ error }}
      <button v-if="!loaded" type="button" class="ml-3 underline" @click="refresh">{{ t('webchat.retry') }}</button>
    </div>
    <form v-if="loaded && (!profile || editing)" class="min-h-0 overflow-y-auto px-6 py-6 space-y-5 max-w-xl w-full mx-auto" @submit.prevent="saveProfile">
      <div>
        <h4 class="text-lg font-semibold text-theme-strong">{{ t(profile ? 'webchat.settings' : 'webchat.setup_title') }}</h4>
        <p class="mt-2 text-sm text-theme-subtle">{{ t('webchat.setup_hint') }}</p>
      </div>
      <label class="block text-sm text-theme-body">{{ t('webchat.nickname') }}
        <UiInput v-model="form.nickname" required maxlength="80" class="mt-2 w-full rounded-lg px-3 py-2" autocomplete="nickname" />
      </label>
      <label class="block text-sm text-theme-body">{{ t('webchat.peer_nickname') }}
        <UiInput v-model="form.peer_nickname" required maxlength="80" class="mt-2 w-full rounded-lg px-3 py-2" />
      </label>
      <label class="block text-sm text-theme-body">{{ t('webchat.description') }}
        <UiTextarea v-model="form.description" rows="4" maxlength="4000" class="mt-2 w-full rounded-lg px-3 py-2" :placeholder="t('webchat.description_hint')" />
      </label>
      <div class="flex gap-3">
        <button type="submit" :disabled="saving || !form.nickname.trim() || !form.peer_nickname.trim()" class="rounded-lg bg-blue-600 px-4 py-2 text-white disabled:opacity-50">{{ t(saving ? 'webchat.saving' : 'webchat.save') }}</button>
        <button v-if="profile" type="button" class="px-4 py-2 text-theme-subtle" :disabled="saving" @click="closeProfile">{{ t('webchat.cancel') }}</button>
      </div>
    </form>
    <template v-else>
      <div ref="messageList" role="log" :aria-label="t('webchat.messages')" dir="ltr" class="min-h-0 flex-1 overflow-y-auto [overflow-anchor:none]">
        <div dir="ltr" class="mx-auto w-full max-w-[1280px] space-y-4 px-6 py-5">
          <button v-if="hasOlder" type="button" :disabled="loadingOlder" class="w-full rounded-lg border border-gray-200 dark:border-gray-700 py-2 text-sm text-blue-600 dark:text-blue-300 disabled:opacity-50" @click="loadOlder">{{ t(loadingOlder ? 'webchat.loading' : 'sessions.history.load_more') }}</button>
          <p v-if="historyLoaded && !messages.length" class="py-10 text-center text-theme-subtle">{{ t('webchat.empty') }}</p>
          <article v-for="message in messages" :key="message.id" class="flex" :class="message.direction === 'incoming' ? 'justify-end' : 'justify-start'">
            <div class="min-w-0 max-w-[85%] flex flex-col gap-2" :class="message.direction === 'incoming' ? 'items-end' : 'items-start'">
              <p class="max-w-full break-words text-xs font-medium text-theme-body">{{ message.sender_name }}</p>
              <div class="min-w-0 max-w-full flex flex-col" :class="message.direction === 'incoming' ? 'items-end' : 'items-start'">
                <div class="message-bubble chat-bubble min-w-0 max-w-full rounded-lg px-4 py-3 break-words" :class="{ 'chat-bubble--accent': message.direction === 'incoming' }" tabindex="0" :aria-describedby="`webchat-time-${message.id}`">
                  <MessageChain :chain="message.chain" :message-id="message.id" media-scope="webchat" />
                </div>
                <time :id="`webchat-time-${message.id}`" class="message-time mt-1 text-xs text-theme-subtle">{{ formatTime(message.timestamp) }}</time>
              </div>
            </div>
          </article>
        </div>
      </div>
      <form class="relative mx-auto mt-auto w-full max-w-[1280px] shrink-0 px-7 pb-5 pt-3" @submit.prevent="send">
        <UiTextarea v-model="draft" :aria-label="t('webchat.input')" :placeholder="t('webchat.input')" rows="2" maxlength="16000" class="block w-full resize-none rounded-3xl px-5 pt-4 pb-16" @keydown="onComposerKey" />
        <button type="button" :disabled="!profile" :aria-label="t('webchat.settings')" :title="t('webchat.settings')" class="composer-settings absolute bottom-8 left-10 flex h-10 w-10 items-center justify-center rounded-full text-theme-subtle transition-colors disabled:cursor-not-allowed disabled:opacity-40" @click="editProfile">
          <Setting aria-hidden="true" focusable="false" class="h-6 w-6" />
        </button>
        <button type="submit" :disabled="!profile || sending || !draft.trim()" :aria-label="t(sending ? 'webchat.sending' : 'webchat.send')" :title="t(sending ? 'webchat.sending' : 'webchat.send')" :aria-busy="sending" class="composer-send absolute bottom-8 right-10 flex h-10 w-10 items-center justify-center rounded-full transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-40">
          <svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="h-6 w-6">
            <path d="M12 19V5m-7 7 7-7 7 7" />
          </svg>
        </button>
      </form>
    </template>
  </section>
</template>

<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { Setting } from '@element-plus/icons-vue'
import MessageChain from '@/components/sessions/MessageChain.vue'
import UiInput from '@/components/ui/UiInput.vue'
import UiTextarea from '@/components/ui/UiTextarea.vue'
import { getWebChat, getWebChatMessages, saveWebChatProfile, sendWebChatMessage } from '@/api/webchat'
import type { WebChatMessage, WebChatProfile } from '@/api/webchat'

const { t, locale } = useI18n()
const profile = ref<WebChatProfile | null>(null)
const form = reactive<WebChatProfile>({ nickname: '', peer_nickname: '', description: '' })
const messages = ref<WebChatMessage[]>([])
const loaded = ref(false)
const editing = ref(false)
const saving = ref(false)
const sending = ref(false)
const loadingOlder = ref(false)
const hasOlder = ref(false)
const error = ref('')
const draft = ref('')
const messageList = ref<HTMLElement | null>(null)
const controller = new AbortController()
let timer: ReturnType<typeof setTimeout> | undefined
let refreshing = false
const historyLoaded = ref(false)
let pending: { id: string; text: string } | null = null
let chatScroll: { top: number; follow: boolean } | null = null

function formatTime(timestamp: number) {
  return new Date(timestamp * 1000).toLocaleString(locale.value)
}
function showError(cause: any) {
  const code = cause?.response?.data?.detail
  error.value = t(['setup_required', 'request_conflict', 'unavailable'].includes(code) ? `webchat.error_${code}` : 'webchat.error')
}
function editProfile() {
  const container = messageList.value
  chatScroll = container ? {
    top: container.scrollTop,
    follow: container.scrollHeight - container.scrollTop - container.clientHeight < 100,
  } : null
  if (profile.value) Object.assign(form, profile.value)
  editing.value = true
  error.value = ''
}
async function closeProfile() {
  const scroll = chatScroll
  editing.value = false
  await nextTick()
  const container = messageList.value
  if (controller.signal.aborted || editing.value || !container) return
  container.scrollTop = !scroll || scroll.follow ? container.scrollHeight : scroll.top
  chatScroll = null
}
async function saveProfile() {
  saving.value = true
  error.value = ''
  try {
    const { data } = await saveWebChatProfile(form)
    if (controller.signal.aborted) return
    profile.value = data
    await closeProfile()
    await refresh()
  } catch (cause) { showError(cause) }
  finally { saving.value = false }
}
function mergeMessages(items: WebChatMessage[]) {
  const byId = new Map(messages.value.map(item => [item.id, item]))
  items.forEach(item => byId.set(item.id, item))
  messages.value = [...byId.values()].sort((a, b) => a.seq - b.seq)
}
async function refresh() {
  if (refreshing || controller.signal.aborted) return
  refreshing = true
  if (timer) clearTimeout(timer)
  try {
    const { data } = await getWebChat(controller.signal)
    if (error.value === t('webchat.error')) error.value = ''
    profile.value = data.profile
    loaded.value = true
    if (pending && data.request?.id === pending.id) {
      if (draft.value.trim() === pending.text) draft.value = ''
      pending = null
    }
    if (data.profile) {
      const container = messageList.value
      const follow = !editing.value && (!historyLoaded.value || (container !== null && container.scrollHeight - container.scrollTop - container.clientHeight < 100))
      let more = true
      while (more) {
        const after = historyLoaded.value ? messages.value.at(-1)?.seq || 0 : 0
        const page = await getWebChatMessages({ after }, controller.signal)
        if (!historyLoaded.value) hasOlder.value = page.data.has_more
        mergeMessages(page.data.messages)
        more = !!after && page.data.has_more
        historyLoaded.value = true
      }
      await nextTick()
      if (follow && !editing.value && container && messageList.value === container) container.scrollTop = container.scrollHeight
    }
  } catch (cause) {
    if (!controller.signal.aborted) showError(cause)
  } finally {
    refreshing = false
    if (!controller.signal.aborted) timer = setTimeout(refresh, 1500)
  }
}
async function loadOlder() {
  if (loadingOlder.value || !messages.value.length) return
  loadingOlder.value = true
  try {
    const page = await getWebChatMessages({ before: messages.value[0]!.seq }, controller.signal)
    const container = messageList.value
    const height = container?.scrollHeight || 0
    mergeMessages(page.data.messages)
    hasOlder.value = page.data.has_more
    await nextTick()
    if (container) container.scrollTop += container.scrollHeight - height
  } catch (cause) { if (!controller.signal.aborted) showError(cause) }
  finally { loadingOlder.value = false }
}
function requestId() {
  const bytes = crypto.getRandomValues(new Uint8Array(16))
  bytes[6] = (bytes[6]! & 15) | 64
  bytes[8] = (bytes[8]! & 63) | 128
  const hex = Array.from(bytes, b => b.toString(16).padStart(2, '0')).join('')
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`
}
async function send() {
  const text = draft.value.trim()
  if (!profile.value || !text || sending.value) return
  sending.value = true
  error.value = ''
  if (!pending || pending.text !== text) pending = { id: requestId(), text }
  const submission = pending
  try {
    await sendWebChatMessage(submission.id, text)
    if (controller.signal.aborted) return
    if (draft.value.trim() === text) draft.value = ''
    if (pending?.id === submission.id) pending = null
    await refresh()
  } catch (cause) { showError(cause) }
  finally { sending.value = false }
}
function onComposerKey(event: KeyboardEvent) {
  if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) {
    event.preventDefault()
    void send()
  }
}
onMounted(refresh)
onBeforeUnmount(() => { controller.abort(); if (timer) clearTimeout(timer) })
</script>

<style scoped>
.composer-send { background-color: var(--color-accent); color: var(--color-text-on-accent); }
.composer-settings:hover:not(:disabled) { background-color: var(--color-hover); }
.composer-settings:focus-visible,
.composer-send:focus-visible { outline: 2px solid var(--color-focus-ring); outline-offset: 2px; }
.message-time { visibility: hidden; opacity: 0; transition: opacity 150ms ease, visibility 150ms ease; }
.message-bubble:hover + .message-time,
.message-bubble:focus-visible + .message-time,
.message-bubble:has(:focus-visible) + .message-time { visibility: visible; opacity: 1; }
.message-bubble:focus-visible { outline: 2px solid var(--color-focus-ring); outline-offset: 2px; }
@media (prefers-reduced-motion: reduce) { .message-time { transition: none; } }
</style>
