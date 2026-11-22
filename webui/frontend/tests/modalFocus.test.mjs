import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import ts from 'typescript'

const source = readFileSync(new URL('../src/components/common/modalFocus.ts', import.meta.url), 'utf8')
const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2020 } }).outputText
const { registerModal } = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString('base64')}`)

// Model only DOM focus/inert behavior; no browser or layout engine is started.
class Element {
  children = []
  parent = null
  inert = false
  disabled = false
  visible = true
  constructor(tabIndex = -1) { this.tabIndex = tabIndex }
  append(child) { this.children.push(child); child.parent = this; return child }
  contains(target) { return this === target || this.children.some(child => child.contains(target)) }
  closest() { return this.inert ? this : this.parent?.closest() || null }
  matches() { return this.disabled }
  get isConnected() { return document.body.contains(this) }
  getClientRects() { return this.visible ? [{}] : [] }
  querySelectorAll() {
    return this.children.flatMap(child => [child, ...child.querySelectorAll()])
      .filter(child => child.tabIndex >= 0)
  }
  focus() { document.activeElement = this; document.dispatch('focusin', { target: this }) }
}

function setup() {
  const listeners = new Map()
  globalThis.HTMLElement = globalThis.Node = Element
  globalThis.MutationObserver = class {
    observe() {}
    disconnect() {}
  }
  globalThis.document = {
    body: new Element(), activeElement: null,
    addEventListener(type, handler) { listeners.set(type, handler) },
    removeEventListener(type) { listeners.delete(type) },
    dispatch(type, event) { listeners.get(type)?.(event) },
  }
  const background = document.body.append(new Element())
  const opener = background.append(new Element(0))
  opener.focus()
  function modal() {
    const root = document.body.append(new Element())
    const panel = root.append(new Element())
    const first = panel.append(new Element(0))
    const last = panel.append(new Element(0))
    return { root, panel, first, last }
  }
  function key(key, shiftKey = false, defaultPrevented = false) {
    const event = { key, shiftKey, defaultPrevented, preventDefault() { this.defaultPrevented = true } }
    document.dispatch('keydown', event)
    return event
  }
  return { background, opener, modal, key, listeners }
}

test('opening contains focus, wraps Tab, and restores the invoking control', () => {
  const { background, opener, modal, key, listeners } = setup()
  const dialog = modal()
  const cleanup = registerModal(dialog.root, dialog.panel, () => {})
  try {
    assert.equal(document.activeElement, dialog.first)
    assert.equal(background.inert, true)
    assert.equal(dialog.root.inert, false)
    dialog.last.focus()
    assert.equal(key('Tab').defaultPrevented, true)
    assert.equal(document.activeElement, dialog.first)
    key('Tab', true)
    assert.equal(document.activeElement, dialog.last)
    opener.focus()
    assert.equal(document.activeElement, dialog.first)
  } finally { cleanup() }
  assert.equal(document.activeElement, opener)
  assert.equal(background.inert, false)
  assert.equal(listeners.size, 0)
})

test('nested modals receive Escape exclusively and restore parent focus', () => {
  const { opener, modal, key } = setup()
  const parent = modal()
  const child = modal()
  let parentEscapes = 0
  let childEscapes = 0
  const closeParent = registerModal(parent.root, parent.panel, () => parentEscapes++)
  parent.last.focus()
  const closeChild = registerModal(child.root, child.panel, () => childEscapes++)
  try {
    key('Escape', false, true)
    assert.equal(childEscapes, 0)
    key('Escape')
    assert.equal(childEscapes, 1)
    assert.equal(parentEscapes, 0)
    assert.equal(parent.root.inert, true)
    assert.equal(child.root.inert, false)
  } finally { closeChild() }
  assert.equal(document.activeElement, parent.last)
  assert.equal(parent.root.inert, false)
  key('Escape')
  assert.equal(parentEscapes, 1)
  closeParent()
  assert.equal(document.activeElement, opener)
})

test('closing a parent beneath confirmation returns focus to the original card', () => {
  const { opener, modal } = setup()
  const parent = modal()
  const child = modal()
  const closeParent = registerModal(parent.root, parent.panel, () => {})
  const closeChild = registerModal(child.root, child.panel, () => {})
  closeParent()
  closeChild()
  assert.equal(document.activeElement, opener)
})

test('an empty dialog receives focus and pre-existing inert state is preserved', () => {
  const { background, modal, key } = setup()
  background.inert = true
  const dialog = modal()
  dialog.panel.children = []
  const cleanup = registerModal(dialog.root, dialog.panel, () => {})
  assert.equal(document.activeElement, dialog.panel)
  key('Tab')
  assert.equal(document.activeElement, dialog.panel)
  cleanup()
  assert.equal(background.inert, true)
})
