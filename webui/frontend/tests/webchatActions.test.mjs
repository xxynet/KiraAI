import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { test } from 'node:test'
import { runInNewContext } from 'node:vm'
import { parse, compileScript } from '@vue/compiler-sfc'
import * as Vue from 'vue'
import ts from 'typescript'

function compile(path) {
  const source = readFileSync(new URL(path, import.meta.url), 'utf8')
  const input = path.endsWith('.vue') ? compileScript(parse(source).descriptor, { id: 'actions-test' }).content : source
  return ts.transpileModule(input, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 } }).outputText
}
const textExports = {}
runInNewContext(compile('../src/components/webchat/messageText.ts'), { exports: textExports })
const compiled = compile('../src/components/webchat/MessageActions.vue')
const viewCompiled = compile('../src/views/WebChatView.vue')
const message = { id: 'original', chain: [{ type: 'text', text: '**Raw text**' }], sender_name: 'Kira' }

function setup(code = compiled, props = { message, disabled: false }, api = {}) {
  const exports = {}, events = [], notifications = [], errors = [], copied = []
  let timeout, cleared = false
  const context = {
    exports, AbortController, Event,
    crypto: { getRandomValues: bytes => bytes.fill(7) },
    localStorage: { getItem: () => null },
    document: { dispatchEvent() {}, activeElement: null },
    window: { innerWidth: 300, innerHeight: 200 },
    navigator: { clipboard: { writeText: async text => copied.push(text) } },
    console: { error: (...args) => errors.push(args) },
    setTimeout: fn => { timeout = fn; cleared = false; return 1 },
    clearTimeout: () => { cleared = true },
    require(id) {
      if (id === 'vue') return { ...Vue, onMounted() {}, onBeforeUnmount() {}, watch() {} }
      if (id === 'vue-i18n') return { useI18n: () => ({ t: key => key, locale: Vue.ref('en') }) }
      if (id === '@/composables/useNotification') return { notify: (...args) => notifications.push(args) }
      if (id === './messageText' || id === '@/components/webchat/messageText') return textExports
      if (id === '@/api/webchat') return api
      if (id === '@element-plus/icons-vue' || id.endsWith('.vue')) return {}
      throw new Error(`Unexpected dependency: ${id}`)
    },
  }
  runInNewContext(code, context)
  const state = exports.default.setup(props, { expose() {}, emit: (...args) => events.push(args) })
  return { state, context, events, notifications, copied, errors, fire: () => { if (!cleared) timeout?.() } }
}

test('copy preserves raw Markdown and represents quotes and media without archive paths', () => {
  assert.equal(textExports.messageText([
    ...message.chain, { type: 'reply', chain: [{ type: 'text', text: 'quoted' }] },
    { type: 'file', name: 'note.txt', file: 'private/path' }, { type: 'image', file: 'private/hash' },
  ], key => key), '**Raw text**\nquoted\nnote.txt\n[sessions.history.image]')
})

test('menus fit viewport, keyboard selection works, and quoting emits original message', async () => {
  const { state, events, context } = setup()
  const focused = []
  const items = [0, 1].map(index => ({ focus: () => focused.push(index) }))
  state.menu.value = { offsetWidth: 160, offsetHeight: 90, querySelector: () => items[0], querySelectorAll: () => items }
  await state.open(290, 190)
  assert.deepEqual({ ...state.position }, { x: 132, y: 102 })
  context.document.activeElement = items[0]
  state.onMenuKey({ key: 'ArrowDown', preventDefault() {} })
  assert.equal(focused.at(-1), 1)
  state.quote()
  assert.equal(state.opened.value, false)
  assert.deepEqual(events, [['reply', message]])
})

test('long presses open menus while touch movement cancels them', () => {
  for (const moved of [true, false]) {
    const { state, fire } = setup()
    state.onPointerDown({ pointerType: 'touch', isPrimary: true, clientX: 20, clientY: 20 })
    if (moved) state.onPointerMove({ clientX: 20, clientY: 40 })
    fire()
    assert.equal(state.opened.value, !moved)
  }
})

test('clipboard failures are reported and disabled quoting does not emit', async () => {
  const { state, context, copied, notifications, errors, events } = setup(compiled, { message, disabled: true })
  await state.copy()
  assert.deepEqual(copied, ['**Raw text**'])
  const cause = new Error('Permission denied')
  context.navigator.clipboard.writeText = async () => { throw cause }
  await state.copy()
  assert.equal(notifications.at(-1)[0], 'webchat.copy_failed')
  assert.equal(errors[0][1], cause)
  state.quote()
  assert.equal(events.length, 0)
})

test('failed sends retain quote and reuse request ID; success clears only the submitted quote', async () => {
  const calls = []
  let fail = true
  const api = {
    sendWebChatMessage: async (...args) => { calls.push(args); if (fail) throw new Error('Network error') },
    getWebChat: async () => ({ data: { profile: null, config: {} } }),
  }
  const { state } = setup(viewCompiled, {}, api)
  state.profile.value = { nickname: 'Alice' }
  state.draft.value = 'Reply body'
  state.replyTarget.value = message
  await state.send()
  assert.equal(state.replyTarget.value.id, message.id)
  assert.equal(state.draft.value, 'Reply body')
  fail = false
  await state.send()
  assert.equal(calls[0][0], calls[1][0])
  assert.equal(calls[1][3], message.id)
  assert.equal(state.replyTarget.value, null)
  assert.equal(state.draft.value, '')
})


test('long press consumes the synthetic click without opening the media underneath', () => {
  const { state, fire } = setup()
  state.onPointerDown({ pointerType: 'touch', isPrimary: true, clientX: 20, clientY: 20 })
  fire()
  let prevented = 0
  state.onClick({ preventDefault: () => prevented++, stopPropagation() {} })
  assert.equal(prevented, 1)
  state.onClick({ preventDefault: () => prevented++, stopPropagation() {} })
  assert.equal(prevented, 1)
})

test('HTTP clipboard fallback copies text and removes its temporary input', async () => {
  const { state, context, notifications } = setup()
  context.navigator.clipboard = undefined
  let selected = false, removed = false
  const input = { style: {}, focus: options => assert.equal(options.preventScroll, true), select: () => { selected = true }, remove: () => { removed = true } }
  context.document.createElement = () => input
  context.document.body = { appendChild() {} }
  context.document.execCommand = command => command === 'copy' && selected
  await state.copy()
  assert.equal(input.value, '**Raw text**')
  assert.equal(removed, true)
  assert.equal(notifications[0][0], 'webchat.copied')
})


test('copy and Escape restore focus without scrolling the bottom message', async () => {
  const { state } = setup()
  let scrollTop = 920
  const focused = []
  const bubble = { focus(options) {
    focused.push(options)
    if (!options?.preventScroll) scrollTop = 900
  } }
  state.trigger.value = { querySelector: () => bubble }
  await state.copy()
  assert.equal(scrollTop, 920)
  state.onMenuKey({ key: 'Escape', preventDefault() {}, stopPropagation() {} })
  assert.equal(scrollTop, 920)
  assert.equal(focused.length, 2)
  assert.ok(focused.every(options => options.preventScroll === true))
})


test('delete menu emits the selected message and respects disabled state', () => {
  for (const disabled of [false, true]) {
    const { state, events } = setup(compiled, { message, disabled })
    state.opened.value = true
    state.remove()
    assert.equal(events.length, disabled ? 0 : 1)
    if (!disabled) {
      assert.deepEqual(events[0], ['delete', message])
      assert.equal(state.opened.value, false)
    }
  }
})

test('deleting a message updates the list and quote only on success', async () => {
  for (const fail of [true, false]) {
    const calls = []
    const cause = new Error('Delete failed')
    const { state, notifications, errors } = setup(viewCompiled, {}, {
      deleteWebChatMessage: async id => { calls.push(id); if (fail) throw cause },
      getWebChat: async () => ({ data: { profile: null, config: {} } }),
    })
    const other = { ...message, id: 'other' }
    state.messages.value = [message, other]
    state.replyTarget.value = message
    state.requestDeleteMessage(message)
    assert.equal(calls.length, 0)
    assert.equal(state.messages.value.length, 2)
    await state.deleteMessage()
    assert.deepEqual(calls, [message.id])
    assert.equal(state.messages.value.length, fail ? 2 : 1)
    assert.equal(state.replyTarget.value?.id ?? null, fail ? message.id : null)
    assert.equal(state.deleting.value, false)
    assert.equal(notifications[0][0], fail ? 'webchat.error_delete_message' : 'webchat.message_deleted')
    if (fail) assert.equal(errors[0][1], cause)
  }
})


test('canceling message deletion keeps messages and makes no delete request', async () => {
  const calls = []
  const { state } = setup(viewCompiled, {}, {
    deleteWebChatMessage: async id => calls.push(id),
  })
  let opened = 0
  state.deleteMessageModalRef.value = { open: () => opened++ }
  state.messages.value = [message]
  state.requestDeleteMessage(message)
  assert.equal(opened, 1)
  assert.equal(state.messageToDelete.value.id, message.id)
  assert.equal(calls.length, 0)
  state.cancelDeleteMessage()
  await state.deleteMessage()
  assert.equal(state.messageToDelete.value, null)
  assert.equal(calls.length, 0)
  assert.equal(state.messages.value.length, 1)
})
