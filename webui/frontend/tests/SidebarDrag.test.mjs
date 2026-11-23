import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { test } from 'node:test'
import { runInNewContext } from 'node:vm'
import { shallowRef } from 'vue'
import ts from 'typescript'

const source = readFileSync(new URL('../src/composables/useSidebarDrag.ts', import.meta.url), 'utf8')
const { outputText } = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
})

function setup() {
  function style() {
    let values = {}
    return new Proxy({}, {
      get: (_, key) => key === 'cssText' ? JSON.stringify(values) : values[key] ?? '',
      set: (_, key, value) => { if (key === 'cssText') values = JSON.parse(value || '{}'); else values[key] = value; return true },
    })
  }
  class Node {
    constructor(tag = 'div', dataset = {}) {
      this.tag = tag
      this.dataset = dataset
      this.parentNode = null
      this.childNodes = []
      this.style = style()
      this.scrollTop = 0
      this.bounds = { left: 10, top: 20, width: 400, height: 40, bottom: 60 }
    }
    get parentElement() { return this.parentNode }
    get children() { return this.childNodes.filter(node => node.tag !== '#comment') }
    get isConnected() { return this === body || !!this.parentNode?.isConnected }
    get nextSibling() { const siblings = this.parentNode?.childNodes ?? []; return siblings[siblings.indexOf(this) + 1] ?? null }
    get nextElementSibling() { const siblings = this.parentNode?.children ?? []; return siblings[siblings.indexOf(this) + 1] ?? null }
    appendChild(node) { return this.insertBefore(node, null) }
    insertBefore(node, before) {
      if (node === before) return node
      node.remove()
      const index = before === null ? this.childNodes.length : this.childNodes.indexOf(before)
      assert.ok(index >= 0)
      this.childNodes.splice(index, 0, node)
      node.parentNode = this
      return node
    }
    before(...nodes) { for (const node of nodes) this.parentNode.insertBefore(node, this) }
    remove() { if (this.parentNode) { const parent = this.parentNode; parent.childNodes.splice(parent.childNodes.indexOf(this), 1); this.parentNode = null } }
    contains(node) { return this === node || this.childNodes.some(child => child.contains(node)) }
    matches(selector) {
      if (selector.includes('button:not')) return ['input', 'textarea', 'select', 'a'].includes(this.tag) || (this.tag === 'button' && !('sidebarDragHandle' in this.dataset))
      const attribute = /^\[data-([^\]]+)\]$/.exec(selector)
      return !!attribute && attribute[1].replace(/-([a-z])/g, (_, letter) => letter.toUpperCase()) in this.dataset
    }
    closest(selector) { for (let node = this; node; node = node.parentNode) if (node.matches(selector)) return node; return null }
    querySelectorAll(selector) { return this.children.flatMap(child => [...(child.matches(selector) ? [child] : []), ...child.querySelectorAll(selector)]) }
    querySelector(selector) { return this.querySelectorAll(selector)[0] ?? null }
    getBoundingClientRect() { return this.bounds }
  }
  const body = new Node('body')
  const scroller = body.appendChild(new Node())
  scroller.bounds = { top: 0, bottom: 600 }
  scroller.overflowY = 'auto'
  const editor = scroller.appendChild(new Node())
  const entries = editor.appendChild(new Node('div', { sidebarEntries: '' }))
  const first = entries.appendChild(new Node('div', { sidebarItemId: '/overview' }))
  const second = entries.appendChild(new Node('div', { sidebarItemId: '/settings' }))
  second.bounds = { left: 10, top: 80, width: 400, height: 40, bottom: 120 }
  const ungrouped = entries.appendChild(new Node('div', { sidebarUngroupedDrop: '' }))
  const group = entries.appendChild(new Node('div', { sidebarGroup: 'work' }))
  const header = group.appendChild(new Node())
  const groupBody = group.appendChild(new Node('div', { sidebarGroupBody: '' }))
  const grouped = groupBody.appendChild(new Node('div', { sidebarItemId: '/logs', sidebarGroupId: 'work' }))
  const end = entries.appendChild(new Node('div', { sidebarGroupEnd: '' }))
  const listeners = new Map(), windowListeners = new Map(), frames = new Map(), drops = []
  const add = (map, name, callback) => { if (!map.has(name)) map.set(name, new Set()); map.get(name).add(callback) }
  const remove = (map, name, callback) => map.get(name)?.delete(callback)
  let hit = second, unmount, frameId = 0
  const module = { exports: {} }
  runInNewContext(outputText, {
    module, exports: module.exports,
    require: id => { assert.equal(id, 'vue'); return { shallowRef, onBeforeUnmount: callback => { unmount = callback } } },
    document: {
      body, scrollingElement: body, elementFromPoint: () => hit,
      createElement: tag => new Node(tag), createComment: () => new Node('#comment'),
      addEventListener: (name, callback) => add(listeners, name, callback),
      removeEventListener: (name, callback) => remove(listeners, name, callback),
    },
    window: {
      innerHeight: 800,
      addEventListener: (name, callback) => add(windowListeners, name, callback),
      removeEventListener: (name, callback) => remove(windowListeners, name, callback),
    },
    getComputedStyle: node => ({ overflowY: node.overflowY ?? 'visible' }),
    requestAnimationFrame: callback => { const id = ++frameId; frames.set(id, callback); return id },
    cancelAnimationFrame: id => frames.delete(id),
  })
  const drag = module.exports.useSidebarDrag(shallowRef(editor), (source, target) => drops.push({ source, target }))
  const event = (extra = {}) => ({ pointerId: 1, button: 0, clientX: 40, clientY: 40, preventDefault() {}, ...extra })
  const send = (name, extra = {}) => { for (const callback of [...listeners.get(name) ?? []]) callback(event(extra)) }
  for (const row of [first, second, header, grouped]) row.appendChild(new Node('button', { sidebarDragHandle: '' }))
  const begin = (element = first, source = { type: 'item', id: '/overview' }, target) => {
    const handle = element.querySelector('[data-sidebar-drag-handle]')
    drag.startDrag(event({ currentTarget: handle, target: target ?? handle }), source)
  }
  const assertClean = () => {
    assert.equal(drag.dragged.value, null)
    assert.equal(frames.size, 0)
    assert.equal(editor.querySelector('[data-sidebar-drag-placeholder]'), null)
    assert.equal([...listeners.values(), ...windowListeners.values()].reduce((sum, callbacks) => sum + callbacks.size, 0), 0)
  }
  return { drag, body, entries, first, second, ungrouped, group, header, grouped, groupBody, end, scroller, drops, begin, send, assertClean, setHit: node => { hit = node }, unmount: () => unmount(), Node }
}

test('pointer movement moves the original opaque node and restores it before applying the drop', () => {
  const env = setup()
  env.begin()
  env.send('pointermove', { clientX: 42, clientY: 42 })
  assert.equal(env.first.parentNode, env.entries)
  env.send('pointermove', { clientX: 80, clientY: 105 })
  assert.equal(env.first.parentNode, env.body)
  assert.equal(env.body.querySelectorAll('[data-sidebar-item-id]').filter(node => node.dataset.sidebarItemId === '/overview').length, 1)
  assert.equal(env.first.style.opacity, '1')
  assert.equal(env.first.style.transform, 'translate3d(50px, 85px, 0)')
  env.send('pointerup', { clientX: 80, clientY: 105 })
  assert.equal(env.first.parentNode, env.entries)
  assert.equal(env.first.style.position, '')
  assert.equal(env.drops.length, 1)
  assert.equal(env.drops[0].target.groupId, null)
  env.assertClean()
})

test('pointer drops move items into groups without duplicating the actual element', () => {
  const env = setup()
  env.setHit(env.grouped)
  env.begin()
  env.send('pointermove', { clientX: 100, clientY: 100 })
  assert.equal(env.groupBody.querySelectorAll('[data-sidebar-drag-placeholder]').length, 1)
  env.send('pointerup', { clientX: 100, clientY: 100 })
  assert.equal(env.drops[0].target.groupId, 'work')
  env.assertClean()
})

test('group dragging moves the actual group and all its children together', () => {
  const env = setup()
  env.setHit(env.end)
  env.begin(env.header, { type: 'group', id: 'work' })
  env.send('pointermove', { clientX: 100, clientY: 100 })
  assert.equal(env.group.parentNode, env.body)
  assert.equal(env.group.contains(env.grouped), true)
  env.send('pointerup', { clientX: 100, clientY: 100 })
  assert.equal(env.drops[0].target.type, 'group')
  assert.equal(env.group.parentNode, env.entries)
  env.assertClean()
})

test('Escape, pointer cancellation and unmount all restore DOM, styles and listeners', () => {
  for (const stop of [env => env.send('keydown', { key: 'Escape' }), env => env.send('pointercancel'), env => env.unmount()]) {
    const env = setup()
    env.body.style.cursor = 'crosshair'
    env.first.style.color = 'red'
    env.begin()
    env.send('pointermove', { clientX: 80, clientY: 105 })
    stop(env)
    assert.equal(env.first.parentNode, env.entries)
    assert.equal(env.first.style.color, 'red')
    assert.equal(env.body.style.cursor, 'crosshair')
    assert.equal(env.drops.length, 0)
    env.assertClean()
  }
})

test('outside drops and forbidden group-to-ungrouped drops leave the layout untouched', () => {
  for (const source of ['item', 'group']) {
    const env = setup()
    env.begin(source === 'item' ? env.first : env.header, { type: source, id: source === 'item' ? '/overview' : 'work' })
    env.send('pointermove', { clientX: 80, clientY: 105 })
    env.setHit(source === 'item' ? env.body : env.ungrouped)
    env.send('pointerup', { clientX: 80, clientY: 105 })
    assert.equal(env.drops.length, 0)
    env.assertClean()
  }
})

test('editing inputs and action buttons stay clickable, and only the active pointer controls a drag', () => {
  const env = setup()
  const input = env.header.appendChild(new env.Node('input'))
  env.begin(env.header, { type: 'group', id: 'work' }, input)
  env.send('pointermove', { clientX: 80, clientY: 105 })
  assert.equal(env.drag.dragged.value, null)
  const button = env.first.appendChild(new env.Node('button'))
  env.begin(env.first, { type: 'item', id: '/overview' }, button)
  env.send('pointermove', { clientX: 80, clientY: 105 })
  assert.equal(env.drag.dragged.value, null)
  env.begin()
  env.send('pointermove', { pointerId: 2, clientX: 80, clientY: 105 })
  assert.equal(env.first.parentNode, env.entries)
  env.send('pointerup')
  env.assertClean()
})

test('dragging near the viewport edge scrolls its container and cleans up its animation frame', () => {
  const env = setup()
  env.begin()
  env.send('pointermove', { clientX: 80, clientY: 590 })
  assert.ok(env.scroller.scrollTop > 0)
  env.drag.cancel()
  env.assertClean()
})

test('a removed plugin row is not resurrected when its drag is cancelled', () => {
  const env = setup()
  env.begin()
  env.send('pointermove', { clientX: 80, clientY: 105 })
  env.first.remove()
  env.drag.cancel()
  assert.equal(env.first.isConnected, false)
  assert.equal(env.entries.contains(env.first), false)
  env.assertClean()
})


test('touching item content or group headers leaves scrolling available', () => {
  const env = setup()
  for (const [row, source] of [
    [env.first, { type: 'item', id: '/overview' }],
    [env.header, { type: 'group', id: 'work' }],
  ]) {
    const label = row.appendChild(new env.Node('span'))
    env.begin(row, source, label)
    env.send('pointermove', { clientX: 80, clientY: 105 })
    assert.equal(env.first.parentNode, env.entries)
    assert.equal(env.group.parentNode, env.entries)
    env.assertClean()
  }
})

test('the icon inside a drag handle starts dragging the entire item', () => {
  const env = setup()
  const handle = env.first.querySelector('[data-sidebar-drag-handle]')
  const icon = handle.appendChild(new env.Node('svg'))
  env.begin(env.first, { type: 'item', id: '/overview' }, icon)
  env.send('pointermove', { clientX: 80, clientY: 105 })
  assert.equal(env.first.parentNode, env.body)
  env.drag.cancel()
  env.assertClean()
})
