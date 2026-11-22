import type { InjectionKey, Ref } from 'vue'

export const modalPanelKey: InjectionKey<Ref<HTMLElement | null>> = Symbol('modalPanel')

type ModalLayer = {
  root: HTMLElement
  panel: HTMLElement
  close: () => void
  returnFocus: HTMLElement | null
}

const layers: ModalLayer[] = []
const inertBefore = new Map<HTMLElement, boolean>()
let observer: MutationObserver | null = null

function topLayer() {
  return layers[layers.length - 1]
}

function focusable(panel: HTMLElement): HTMLElement[] {
  return Array.from(panel.querySelectorAll<HTMLElement>(
    'a[href], button, input, select, textarea, [tabindex], [contenteditable="true"]',
  )).filter(element => element.tabIndex >= 0 && !element.matches(':disabled')
    && !element.closest('[inert]') && element.getClientRects().length > 0
    && getComputedStyle(element).visibility === 'visible')
}

function focusPanel(layer: ModalLayer) {
  const target = focusable(layer.panel)[0] || layer.panel
  target.focus({ preventScroll: true })
}

function syncInert() {
  const top = topLayer()
  if (!top) {
    for (const [element, wasInert] of inertBefore) element.inert = wasInert
    inertBefore.clear()
    return
  }
  for (const element of Array.from(document.body.children)) {
    if (!(element instanceof HTMLElement)) continue
    if (!inertBefore.has(element)) inertBefore.set(element, element.inert)
    element.inert = element !== top.root && !element.contains(top.root)
      ? true : inertBefore.get(element)!
  }
}

function onFocusIn(event: FocusEvent) {
  const top = topLayer()
  if (top && event.target instanceof Node && !top.panel.contains(event.target)) focusPanel(top)
}

function onKeyDown(event: KeyboardEvent) {
  const top = topLayer()
  if (!top || event.defaultPrevented) return
  if (event.key === 'Escape') {
    event.preventDefault()
    top.close()
    return
  }
  if (event.key !== 'Tab') return
  const elements = focusable(top.panel)
  const first = elements[0]
  const last = elements[elements.length - 1]
  const active = document.activeElement
  if (!first || !top.panel.contains(active)
    || (event.shiftKey ? active === first || active === top.panel : active === last || active === top.panel)) {
    event.preventDefault()
    ;(event.shiftKey ? last : first)?.focus({ preventScroll: true })
    if (!first) top.panel.focus({ preventScroll: true })
  }
}

export function registerModal(root: HTMLElement, panel: HTMLElement, close: () => void): () => void {
  const layer: ModalLayer = {
    root, panel, close,
    returnFocus: document.activeElement instanceof HTMLElement ? document.activeElement : null,
  }
  layers.push(layer)
  if (layers.length === 1) {
    document.addEventListener('keydown', onKeyDown)
    document.addEventListener('focusin', onFocusIn)
    observer = new MutationObserver(syncInert)
    observer.observe(document.body, { childList: true })
  }
  syncInert()
  focusPanel(layer)
  return () => {
    const index = layers.indexOf(layer)
    if (index < 0) return
    const wasTop = layer === topLayer()
    for (const other of layers) {
      if (other !== layer && other.returnFocus && layer.panel.contains(other.returnFocus)) {
        other.returnFocus = layer.returnFocus
      }
    }
    layers.splice(index, 1)
    syncInert()
    if (!layers.length) {
      document.removeEventListener('keydown', onKeyDown)
      document.removeEventListener('focusin', onFocusIn)
      observer?.disconnect()
      observer = null
    }
    if (!wasTop) return
    const top = topLayer()
    const previous = layer.returnFocus
    if (previous?.isConnected && previous.getClientRects().length > 0
      && getComputedStyle(previous).visibility === 'visible'
      && !previous.matches(':disabled') && !previous.closest('[inert]') && (!top || top.panel.contains(previous))) {
      previous.focus({ preventScroll: true })
    } else if (top) {
      focusPanel(top)
    }
  }
}
