import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { test } from 'node:test'
import { runInNewContext } from 'node:vm'

const bridgeSource = readFileSync(new URL('../public/plugin-bridge.js', import.meta.url), 'utf8')

function loadBridge({ initial, embedded = false, rawInitial } = {}) {
  const attributes = {}
  const events = new Map()
  const messages = []
  const requests = []
  const window = {
    addEventListener(name, handler) { events.set(name, handler) },
  }
  window.parent = embedded ? { postMessage(message) { messages.push(message) } } : window
  const bootstrap = rawInitial ?? (initial ? JSON.stringify(initial) : null)
  runInNewContext(bridgeSource, {
    window,
    document: {
      documentElement: { setAttribute(name, value) { attributes[name] = value } },
      getElementById(id) {
        assert.equal(id, 'kira-plugin-page-context')
        return bootstrap === null ? null : { textContent: bootstrap }
      },
    },
    location: { protocol: 'https:', host: 'example.test' },
    URLSearchParams,
    fetch(url, options) {
      requests.push({ url, options })
      return Promise.resolve({ json: () => Promise.resolve({ ok: true }) })
    },
  })
  return {
    bridge: window.PluginPageContext, attributes, messages, requests,
    sendContext(context) { events.get('message')({ data: { channel: 'kira-plugin-page', kind: 'context', context } }) },
  }
}

for (const isDark of [true, false]) {
  for (const locale of ['zh', 'en']) {
    test('standalone ready receives server context: ' + isDark + '/' + locale, async () => {
      const initial = { pluginId: 'demo', pageRoute: 'dashboard', isDark, locale }
      const { bridge, attributes, messages, requests } = loadBridge({ initial })
      const context = await bridge.ready()
      assert.deepEqual(JSON.parse(JSON.stringify(context)), initial)
      assert.equal(bridge.getContext(), context)
      assert.equal(attributes['data-theme'], isDark ? 'dark' : 'light')
      assert.equal(attributes.lang, locale)
      assert.equal(messages.length, 0)
      await bridge.api.get('/status')
      assert.equal(requests[0].url, '/api/plugin/demo/status')
      assert.equal(bridge.buildWsUrl('/stream'), 'wss://example.test/ws/plugin/demo/stream')
    })
  }
}

test('legacy iframe ready still waits for its parent and receives later changes', async () => {
  const { bridge, attributes, messages, sendContext } = loadBridge({ embedded: true })
  assert.equal(bridge.getContext(), null)
  assert.equal(messages.length, 1)
  assert.equal(messages[0].kind, 'ready')
  let resolved = false
  const pending = bridge.ready().then(context => { resolved = true; return context })
  await Promise.resolve()
  assert.equal(resolved, false)
  sendContext({ pluginId: 'demo', pageRoute: 'dashboard', isDark: true, locale: 'zh' })
  assert.equal((await pending).locale, 'zh')
  const updates = []
  const themes = []
  bridge.onContext(context => updates.push(context))
  bridge.onThemeChange(isDark => themes.push(isDark))
  sendContext({ pluginId: 'demo', pageRoute: 'dashboard', isDark: false, locale: 'en' })
  assert.equal(updates[0].locale, 'en')
  assert.deepEqual(themes, [false])
  assert.equal(attributes['data-theme'], 'light')
  assert.equal(attributes.lang, 'en')
})

test('parent updates replace server initial context for embedded pages', async () => {
  const { bridge, sendContext } = loadBridge({
    initial: { pluginId: 'demo', pageRoute: 'dashboard', isDark: true, locale: 'zh' },
    embedded: true,
  })
  await bridge.ready()
  sendContext({ pluginId: 'demo', pageRoute: 'dashboard', isDark: false, locale: 'en' })
  assert.equal(bridge.getContext().locale, 'en')
  assert.equal(bridge.getContext().isDark, false)
})

test('malformed bootstrap does not prevent a later parent handshake', async () => {
  const { bridge, sendContext } = loadBridge({ rawInitial: '{broken', embedded: true })
  assert.equal(bridge.getContext(), null)
  const pending = bridge.ready()
  sendContext({ pluginId: 'demo', isDark: false, locale: 'en' })
  assert.equal((await pending).pluginId, 'demo')
})
