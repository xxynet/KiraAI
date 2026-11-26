<template>
  <div ref="trigger" @contextmenu.prevent.stop="open($event.clientX, $event.clientY)"
    @click.capture="onClick" @keydown="onTriggerKey" @pointerdown="onPointerDown" @pointermove="onPointerMove"
    @pointerup="cancelPress" @pointercancel="cancelPress" @pointerleave="cancelPress">
    <slot />
    <Teleport to="body">
      <Transition name="message-menu">
        <div v-if="opened" ref="menu" role="menu" :aria-label="t('webchat.message_actions')"
          class="fixed z-[100] min-w-40 rounded-xl border border-gray-200 bg-white p-1.5 text-theme-body shadow-lg dark:border-gray-700 dark:bg-[#1b1b1f]"
          :style="{ left: `${position.x}px`, top: `${position.y}px` }"
          @contextmenu.prevent @keydown="onMenuKey" @focusout="onFocusOut">
          <button type="button" role="menuitem" class="action-item hover:bg-gray-100 active:bg-gray-200 focus-visible:bg-gray-100 dark:hover:bg-[#2b2b2e] dark:active:bg-[#3a3a3e] dark:focus-visible:bg-[#2b2b2e]" @click="copy">{{ t('webchat.copy') }}</button>
          <button type="button" role="menuitem" :disabled="disabled" class="action-item hover:bg-gray-100 active:bg-gray-200 focus-visible:bg-gray-100 dark:hover:bg-[#2b2b2e] dark:active:bg-[#3a3a3e] dark:focus-visible:bg-[#2b2b2e]" @click="quote">{{ t('webchat.reply') }}</button>
          <button type="button" role="menuitem" :disabled="disabled" class="action-item hover:bg-gray-100 active:bg-gray-200 focus-visible:bg-gray-100 dark:hover:bg-[#2b2b2e] dark:active:bg-[#3a3a3e] dark:focus-visible:bg-[#2b2b2e]" @click="remove">{{ t('common.delete') }}</button>
        </div>
      </Transition>
    </Teleport>
  </div>
</template>

<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import type { WebChatMessage } from '@/api/webchat'
import { notify } from '@/composables/useNotification'
import { messageText } from './messageText'

const props = defineProps<{ message: WebChatMessage; disabled: boolean }>()
const emit = defineEmits<{ reply: [message: WebChatMessage]; delete: [message: WebChatMessage] }>()
const { t } = useI18n()
const trigger = ref<HTMLElement | null>(null)
const menu = ref<HTMLElement | null>(null)
const opened = ref(false)
const position = reactive({ x: 0, y: 0 })
let pressTimer: ReturnType<typeof setTimeout> | undefined
let pressStart = { x: 0, y: 0 }
let active = true
let suppressClick = false

function cancelPress() {
  if (pressTimer) clearTimeout(pressTimer)
  pressTimer = undefined
}
function close(restoreFocus = false) {
  cancelPress()
  opened.value = false
  if (restoreFocus) trigger.value?.querySelector<HTMLElement>('.message-bubble')?.focus({ preventScroll: true })
}
async function open(x: number, y: number) {
  cancelPress()
  // Close any other message menu before opening this one.
  document.dispatchEvent(new Event('webchat-message-menu'))
  position.x = x
  position.y = y
  opened.value = true
  await nextTick()
  if (!active || !opened.value || !menu.value) return
  const bounds = { width: menu.value.offsetWidth, height: menu.value.offsetHeight }
  position.x = Math.max(8, Math.min(x, window.innerWidth - bounds.width - 8))
  position.y = Math.max(8, Math.min(y, window.innerHeight - bounds.height - 8))
  menu.value.querySelector<HTMLButtonElement>('button:not(:disabled)')?.focus({ preventScroll: true })
}
function onTriggerKey(event: KeyboardEvent) {
  if (event.key !== 'ContextMenu' && !(event.shiftKey && event.key === 'F10')) return
  event.preventDefault()
  const bounds = trigger.value!.getBoundingClientRect()
  void open(bounds.left, bounds.bottom)
}
function onClick(event: MouseEvent) {
  if (!suppressClick) return
  suppressClick = false
  event.preventDefault()
  event.stopPropagation()
}
function onPointerDown(event: PointerEvent) {
  suppressClick = false
  if (event.pointerType !== 'touch' || !event.isPrimary) return
  pressStart = { x: event.clientX, y: event.clientY }
  cancelPress()
  pressTimer = setTimeout(() => { suppressClick = true; void open(pressStart.x, pressStart.y) }, 550)
}
function onPointerMove(event: PointerEvent) {
  if (Math.hypot(event.clientX - pressStart.x, event.clientY - pressStart.y) > 10) cancelPress()
}
function onOutside(event: PointerEvent) {
  if (!menu.value?.contains(event.target as Node)) close()
}
function onViewportChange(event: Event) {
  if (!menu.value?.contains(event.target as Node)) close()
}
function onOtherMenu() { close() }
function onFocusOut(event: FocusEvent) {
  if (!menu.value?.contains(event.relatedTarget as Node | null)) close()
}
function onMenuKey(event: KeyboardEvent) {
  if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); close(true); return }
  if (!['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) return
  event.preventDefault()
  const items = Array.from(menu.value?.querySelectorAll<HTMLButtonElement>('button:not(:disabled)') || [])
  const index = items.indexOf(document.activeElement as HTMLButtonElement)
  items[event.key === 'Home' ? 0 : event.key === 'End' ? items.length - 1 : (index + (event.key === 'ArrowUp' ? -1 : 1) + items.length) % items.length]?.focus({ preventScroll: true })
}
function quote() {
  if (props.disabled) return
  close()
  emit('reply', props.message)
}
function remove() {
  if (props.disabled) return
  close()
  emit('delete', props.message)
}
async function copy() {
  const text = messageText(props.message.chain, t)
  close(true)
  try {
    if (navigator.clipboard?.writeText) await navigator.clipboard.writeText(text)
    else {
      const input = document.createElement('textarea')
      input.value = text
      input.style.cssText = 'position:fixed;top:0;left:0;opacity:0;pointer-events:none'
      document.body.appendChild(input)
      try {
        input.focus({ preventScroll: true })
        input.select()
        if (!document.execCommand('copy')) throw new Error('Clipboard copy failed')
      } finally { input.remove(); close(true) }
    }
    notify(t('webchat.copied'), 'success')
  } catch (cause) {
    console.error('Failed to copy WebChat message:', cause)
    notify(t('webchat.copy_failed'), 'error')
  }
}
onMounted(() => {
  document.addEventListener('pointerdown', onOutside)
  document.addEventListener('scroll', onViewportChange, true)
  document.addEventListener('webchat-message-menu', onOtherMenu)
  window.addEventListener('resize', onViewportChange)
})
onBeforeUnmount(() => {
  active = false
  cancelPress()
  document.removeEventListener('pointerdown', onOutside)
  document.removeEventListener('scroll', onViewportChange, true)
  document.removeEventListener('webchat-message-menu', onOtherMenu)
  window.removeEventListener('resize', onViewportChange)
})
</script>

<style scoped>
.action-item { display: block; width: 100%; padding: 0.625rem 0.75rem; border-radius: 0.625rem; text-align: left; transition: background-color 0.15s ease, transform 0.15s ease; }
.action-item:focus-visible { outline: none; }
.action-item:active:not(:disabled) { transform: scale(0.98); }
.action-item:disabled { opacity: 0.4; cursor: not-allowed; }
.message-menu-enter-active,
.message-menu-leave-active { transform-origin: top left; transition: opacity 0.16s ease, transform 0.16s ease; }
.message-menu-enter-from,
.message-menu-leave-to { opacity: 0; transform: translateY(-0.5rem) scale(0.96); }
.message-menu-leave-active { pointer-events: none; }
@media (prefers-reduced-motion: reduce) {
  .message-menu-enter-active, .message-menu-leave-active { transition: none; }
}
</style>
