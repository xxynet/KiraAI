import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { test } from 'node:test'
import { runInNewContext } from 'node:vm'
import { parse, compileScript } from '@vue/compiler-sfc'
import * as Vue from 'vue'
import ts from 'typescript'

const filename = new URL('../src/views/WebChatView.vue', import.meta.url)
const { descriptor } = parse(readFileSync(filename, 'utf8'))
const script = compileScript(descriptor, { id: 'webchat-markdown-regression' }).content
const compiled = ts.transpileModule(script, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
}).outputText

function setup(saved = null) {
  const storage = new Map(saved === null ? [] : [['chat_markdown_render', saved]])
  const notifications = []
  const errors = []
  let writeError = null
  function open() {
    const exports = {}
    runInNewContext(compiled, {
      exports, AbortController,
      console: { error: (...args) => errors.push(args) },
      localStorage: {
        getItem: key => storage.get(key) ?? null,
        setItem(key, value) {
          if (writeError) throw writeError
          storage.set(key, value)
        },
      },
      require(id) {
        if (id === 'vue') return { ...Vue, onMounted() {}, onBeforeUnmount() {}, watch() {} }
        if (id === 'vue-i18n') return { useI18n: () => ({ t: key => key, locale: Vue.ref('en') }) }
        if (id === '@/composables/useNotification') return { notify: (...args) => notifications.push(args) }
        if (id === '@element-plus/icons-vue' || id === '@/api/webchat') return {}
        if (id.endsWith('.vue')) return { default: {} }
        throw new Error(`Unexpected dependency: ${id}`)
      },
    })
    return exports.default.setup({}, { expose() {} })
  }
  return { open, storage, notifications, errors, failWrites: error => { writeError = error } }
}

test('Markdown defaults off and only the saved enabled value opts in', () => {
  for (const saved of [null, '', '0', 'invalid', 'true']) {
    assert.equal(setup(saved).open().chatMarkdownEnabled.value, false)
  }
  assert.equal(setup('1').open().chatMarkdownEnabled.value, true)
})

test('successful toggles apply immediately and persist across reopening', () => {
  const { open, storage, notifications, errors } = setup()
  const chat = open()
  for (const enabled of [true, false]) {
    chat.setChatMarkdownEnabled(enabled)
    assert.equal(chat.chatMarkdownEnabled.value, enabled)
    assert.equal(storage.get('chat_markdown_render'), enabled ? '1' : '0')
    assert.equal(open().chatMarkdownEnabled.value, enabled)
  }
  assert.equal(notifications.length, 0)
  assert.equal(errors.length, 0)
})

test('storage failures retain live toggles, warn locally and log the complete error', () => {
  const { open, storage, notifications, errors, failWrites } = setup('0')
  const cause = new DOMException('Storage quota exceeded', 'QuotaExceededError')
  const chat = open()
  failWrites(cause)
  for (const enabled of [true, false]) {
    assert.doesNotThrow(() => chat.setChatMarkdownEnabled(enabled))
    assert.equal(chat.chatMarkdownEnabled.value, enabled)
  }
  assert.equal(storage.get('chat_markdown_render'), '0')
  assert.deepEqual(notifications, [
    ['webchat.markdown_save_failed', 'warning'],
    ['webchat.markdown_save_failed', 'warning'],
  ])
  assert.equal(errors.length, 2)
  assert.equal(errors[0][1], cause)
  failWrites(null)
  chat.setChatMarkdownEnabled(true)
  assert.equal(open().chatMarkdownEnabled.value, true)
  assert.equal(notifications.length, 2)
})
