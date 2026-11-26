import { onBeforeUnmount, onMounted, ref } from 'vue'
import { hasOpenModal } from '@/components/common/modalFocus'
import { detectMacPlatform, isQuickNavShortcut } from '@/utils/quickNavSearch'

/**
 * Shared state of the Ctrl+K quick navigation overlay. The palette is a single
 * app-wide overlay, so the state lives at module scope: the header trigger and
 * the palette component both read and write the same ref.
 */
const quickNavOpen = ref(false)

const isMacPlatform = detectMacPlatform(navigator.platform)

export function useQuickNav() {
  function openQuickNav() {
    quickNavOpen.value = true
  }

  function closeQuickNav() {
    quickNavOpen.value = false
  }

  return { quickNavOpen, openQuickNav, closeQuickNav }
}

/**
 * Event targets coming from a same-origin plugin frame belong to another realm,
 * so `instanceof` against this realm's constructors fails for them. Duck typing
 * reads only the properties that matter.
 */
type EventElement = {
  tagName?: string
  isContentEditable?: boolean
  closest?: (selector: string) => unknown
}

function readTarget(target: EventTarget | null): EventElement | null {
  if (!target || typeof (target as EventElement).tagName !== 'string') return null
  return target as EventElement
}

/** Monaco keeps Ctrl+K for its chord commands, and rich-text surfaces may bind it too. */
function isEditorTarget(target: EventTarget | null): boolean {
  const element = readTarget(target)
  if (!element) return false
  if (element.isContentEditable) return true
  return typeof element.closest === 'function' && element.closest('.monaco-editor') !== null
}

/**
 * Text entry owns Option/Alt+letter on macOS-style layouts: Option+K types a
 * character there, so the Alt fallback must never swallow it.
 */
function isTextEntryTarget(target: EventTarget | null): boolean {
  const element = readTarget(target)
  if (!element) return false
  if (element.isContentEditable) return true
  const tag = (element.tagName ?? '').toUpperCase()
  if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return true
  return typeof element.closest === 'function' && element.closest('.monaco-editor') !== null
}

/**
 * Handles one shortcut event. Exported so same-origin plugin frames can forward
 * their keyboard events to the shell: key events inside an iframe never reach
 * the parent window's listener.
 */
export function handleQuickNavKey(event: KeyboardEvent): void {
  if (event.defaultPrevented || event.isComposing) return
  // Alt+K is only a fallback where the browser may keep Ctrl+K for itself.
  const allowAltFallback = !isMacPlatform && !isTextEntryTarget(event.target)
  if (!isQuickNavShortcut(event, { allowAltFallback })) return
  if (quickNavOpen.value) {
    event.preventDefault()
    quickNavOpen.value = false
    return
  }
  // Another dialog owns the keyboard until it closes.
  if (hasOpenModal() || isEditorTarget(event.target)) return
  event.preventDefault()
  quickNavOpen.value = true
}

/**
 * Binds the global shortcut. Call once from the root layout: the open state is
 * shared, so registering it twice would toggle the palette twice.
 */
export function useQuickNavShortcut() {
  onMounted(() => window.addEventListener('keydown', handleQuickNavKey))
  onBeforeUnmount(() => {
    window.removeEventListener('keydown', handleQuickNavKey)
    // The open state is module-scope: never let it leak into the next mount.
    quickNavOpen.value = false
  })
}
