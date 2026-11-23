import { onBeforeUnmount, shallowRef, type Ref } from 'vue'

export interface SidebarDragSource {
  type: 'item' | 'group'
  id: string
}

export type SidebarDropTarget =
  | { type: 'item'; groupId: string | null; beforeId?: string }
  | { type: 'group'; beforeId?: string }

interface Placement {
  target: SidebarDropTarget
  container: HTMLElement
  before: HTMLElement | null
}

interface DragSession {
  source: SidebarDragSource
  pointerId: number
  element: HTMLElement
  startX: number
  startY: number
  x: number
  y: number
  offsetX: number
  offsetY: number
  marker: Comment | null
  placeholder: HTMLElement | null
  originalStyle: string
  scrollContainer: HTMLElement | null
  bodyCursor: string
  bodyUserSelect: string
}

export function useSidebarDrag(
  root: Ref<HTMLElement | undefined>,
  onDrop: (source: SidebarDragSource, target: SidebarDropTarget) => void,
) {
  const dragged = shallowRef<SidebarDragSource | null>(null)
  let session: DragSession | null = null
  let destination: SidebarDropTarget | null = null
  let frame: number | null = null

  function findScrollContainer(element: HTMLElement): HTMLElement {
    for (let parent = element.parentElement; parent; parent = parent.parentElement) {
      if (/(auto|scroll)/.test(getComputedStyle(parent).overflowY)) return parent
    }
    return document.scrollingElement as HTMLElement
  }

  function activate(current: DragSession) {
    const bounds = current.element.getBoundingClientRect()
    current.offsetX = current.startX - bounds.left
    current.offsetY = current.startY - bounds.top
    current.originalStyle = current.element.style.cssText
    current.marker = document.createComment('sidebar-drag-origin')
    current.placeholder = document.createElement('div')
    current.placeholder.dataset.sidebarDragPlaceholder = ''
    Object.assign(current.placeholder.style, {
      height: `${bounds.height}px`, width: '100%', boxSizing: 'border-box',
      border: '2px dashed var(--color-accent)', borderRadius: '0.5rem',
      background: 'var(--color-accent-subtle)',
    })
    current.element.before(current.marker, current.placeholder)
    current.scrollContainer = findScrollContainer(current.element)
    document.body.appendChild(current.element)
    Object.assign(current.element.style, {
      position: 'fixed', left: '0', top: '0', width: `${bounds.width}px`, height: `${bounds.height}px`,
      margin: '0', boxSizing: 'border-box', zIndex: '10000', pointerEvents: 'none',
      transition: 'none', opacity: '1', cursor: 'grabbing',
    })
    current.bodyCursor = document.body.style.cursor
    current.bodyUserSelect = document.body.style.userSelect
    document.body.style.cursor = 'grabbing'
    document.body.style.userSelect = 'none'
    dragged.value = current.source
  }

  function placementAt(current: DragSession, hit: Element | null): Placement | null {
    const editor = root.value
    if (!editor || !hit || !editor.contains(hit)) return null
    if (hit.closest('[data-sidebar-drag-placeholder]')) return null
    const group = hit.closest<HTMLElement>('[data-sidebar-group]')
    if (current.source.type === 'group') {
      if (hit.closest('[data-sidebar-group-end]')) return {
        target: { type: 'group' },
        container: editor.querySelector<HTMLElement>('[data-sidebar-entries]')!,
        before: editor.querySelector<HTMLElement>('[data-sidebar-group-end]'),
      }
      if (!group) return null
      const groups = Array.from(editor.querySelectorAll<HTMLElement>('[data-sidebar-group]'))
      const bounds = group.getBoundingClientRect()
      const next = current.y < bounds.top + bounds.height / 2 ? group : groups[groups.indexOf(group) + 1]
      return {
        target: { type: 'group', beforeId: next?.dataset.sidebarGroup },
        container: group.parentElement!, before: next ?? editor.querySelector<HTMLElement>('[data-sidebar-group-end]'),
      }
    }
    const ungroupedZone = hit.closest<HTMLElement>('[data-sidebar-ungrouped-drop]')
    if (ungroupedZone) return { target: { type: 'item', groupId: null }, container: ungroupedZone.parentElement!, before: ungroupedZone }
    const item = hit.closest<HTMLElement>('[data-sidebar-item-id]')
    if (item) {
      const groupId = item.dataset.sidebarGroupId || null
      const peers = Array.from(editor.querySelectorAll<HTMLElement>('[data-sidebar-item-id]'))
        .filter(peer => (peer.dataset.sidebarGroupId || null) === groupId)
      const bounds = item.getBoundingClientRect()
      const next = current.y < bounds.top + bounds.height / 2 ? item : peers[peers.indexOf(item) + 1]
      return {
        target: { type: 'item', groupId, beforeId: next?.dataset.sidebarItemId },
        container: item.parentElement!,
        before: next ?? (groupId === null ? editor.querySelector<HTMLElement>('[data-sidebar-ungrouped-drop]') : null),
      }
    }
    if (group) {
      const container = group.querySelector<HTMLElement>('[data-sidebar-group-body]')
      if (container) return { target: { type: 'item', groupId: group.dataset.sidebarGroup! }, container, before: null }
    }
    return null
  }

  function updatePlacement(current: DragSession) {
    const hit = document.elementFromPoint(current.x, current.y)
    // Keep the current destination while the pointer is over its placeholder.
    if (hit?.closest('[data-sidebar-drag-placeholder]')) return
    const placement = placementAt(current, hit)
    destination = placement?.target ?? null
    if (placement && current.placeholder) {
      if (current.placeholder.parentElement !== placement.container || current.placeholder.nextElementSibling !== placement.before) {
        placement.container.insertBefore(current.placeholder, placement.before)
      }
    } else if (current.placeholder && current.marker?.parentNode) {
      current.marker.parentNode.insertBefore(current.placeholder, current.marker.nextSibling)
    }
  }

  function tick() {
    frame = null
    const current = session
    if (!current || !current.marker) return
    if (!current.element.isConnected || !current.marker.isConnected) {
      finish(false)
      return
    }
    current.element.style.transform = `translate3d(${current.x - current.offsetX}px, ${current.y - current.offsetY}px, 0)`
    const container = current.scrollContainer
    if (container) {
      const isDocument = container === document.scrollingElement
      const bounds = isDocument ? { top: 0, bottom: window.innerHeight } : container.getBoundingClientRect()
      const edge = 40
      if (current.y < bounds.top + edge) container.scrollTop -= Math.min(18, (bounds.top + edge - current.y) / 2)
      else if (current.y > bounds.bottom - edge) container.scrollTop += Math.min(18, (current.y - bounds.bottom + edge) / 2)
    }
    updatePlacement(current)
    frame = requestAnimationFrame(tick)
  }

  function move(event: PointerEvent) {
    const current = session
    if (!current || current.pointerId !== event.pointerId) return
    current.x = event.clientX
    current.y = event.clientY
    if (!current.marker) {
      if (Math.hypot(current.x - current.startX, current.y - current.startY) < 5) return
      activate(current)
    }
    event.preventDefault()
    if (frame === null) tick()
  }

  function finish(apply: boolean) {
    const current = session
    if (!current) return
    session = null
    if (frame !== null) cancelAnimationFrame(frame)
    frame = null
    document.removeEventListener('pointermove', move)
    document.removeEventListener('pointerup', release)
    document.removeEventListener('pointercancel', cancelPointer)
    document.removeEventListener('keydown', escape)
    window.removeEventListener('blur', cancel)
    if (current.marker) {
      if (current.marker.parentNode && current.element.isConnected) current.marker.parentNode.insertBefore(current.element, current.marker)
      else current.element.remove()
      current.element.style.cssText = current.originalStyle
      current.marker.remove()
      current.placeholder?.remove()
      document.body.style.cursor = current.bodyCursor
      document.body.style.userSelect = current.bodyUserSelect
    }
    dragged.value = null
    const target = destination
    destination = null
    if (apply && target) onDrop(current.source, target)
  }

  function release(event: PointerEvent) {
    if (session?.pointerId !== event.pointerId) return
    if (session.marker) {
      session.x = event.clientX
      session.y = event.clientY
      updatePlacement(session)
    }
    finish(true)
  }

  function cancel() { finish(false) }
  function cancelPointer(event: PointerEvent) {
    if (session?.pointerId === event.pointerId) cancel()
  }
  function escape(event: KeyboardEvent) {
    if (event.key === 'Escape') {
      event.preventDefault()
      cancel()
    }
  }

  function startDrag(event: PointerEvent, source: SidebarDragSource) {
    if (event.button !== 0 || event.isPrimary === false || session) return
    const target = event.target as Element
    const handle = target.closest<HTMLElement>('[data-sidebar-drag-handle]')
    if (!handle || handle !== event.currentTarget) return
    const element = handle.closest<HTMLElement>(source.type === 'group' ? '[data-sidebar-group]' : '[data-sidebar-item-id]')
    if (!element) return
    session = {
      source, pointerId: event.pointerId, element,
      startX: event.clientX, startY: event.clientY, x: event.clientX, y: event.clientY,
      offsetX: 0, offsetY: 0, marker: null, placeholder: null, originalStyle: '', scrollContainer: null,
      bodyCursor: '', bodyUserSelect: '',
    }
    document.addEventListener('pointermove', move, { passive: false })
    document.addEventListener('pointerup', release)
    document.addEventListener('pointercancel', cancelPointer)
    document.addEventListener('keydown', escape)
    window.addEventListener('blur', cancel)
  }

  onBeforeUnmount(cancel)
  return { dragged, startDrag, cancel }
}
