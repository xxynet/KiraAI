import { onBeforeUnmount, onMounted, ref } from 'vue'
import { hasOpenModal } from '@/components/common/modalFocus'
import { isQuickNavShortcut } from '@/utils/quickNavSearch'

/**
 * Shared state of the Ctrl+K quick navigation overlay. The palette is a single
 * app-wide overlay, so the state lives at module scope: the header trigger and
 * the palette component both read and write the same ref.
 */
const quickNavOpen = ref(false)

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
 * Monaco keeps Ctrl+K for its own chord commands, and rich-text surfaces may
 * bind it too, so the palette stays out of those. Plain inputs and textareas
 * have no Ctrl+K behaviour worth protecting.
 */
function isEditableTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false
  return target.isContentEditable || target.closest('.monaco-editor') !== null
}

/**
 * Binds the global Ctrl+K / Cmd+K shortcut. Call once from the root layout: the
 * open state is shared, so registering it twice would toggle the palette twice.
 */
export function useQuickNavShortcut() {
  const { quickNavOpen, openQuickNav, closeQuickNav } = useQuickNav()

  function handleKeydown(event: KeyboardEvent) {
    if (event.defaultPrevented || event.isComposing) return
    if (!isQuickNavShortcut(event)) return
    if (quickNavOpen.value) {
      event.preventDefault()
      closeQuickNav()
      return
    }
    // Another dialog owns the keyboard until it closes, and typing surfaces are
    // left alone so shell-style Ctrl+K keeps working inside them.
    if (hasOpenModal() || isEditableTarget(event.target)) return
    event.preventDefault()
    openQuickNav()
  }

  onMounted(() => window.addEventListener('keydown', handleKeydown))
  onBeforeUnmount(() => {
    window.removeEventListener('keydown', handleKeydown)
    // The open state is module-scope: never let it leak into the next mount.
    closeQuickNav()
  })
}
