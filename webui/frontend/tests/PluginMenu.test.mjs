import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { test } from 'node:test'
import { runInNewContext } from 'node:vm'
import ts from 'typescript'
import { ref } from 'vue'
import { createMemoryHistory, createRouter } from 'vue-router'

const source = readFileSync(new URL('../src/stores/pluginMenu.ts', import.meta.url), 'utf8')
const { outputText } = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
})

function setup(getPlugins = async () => ({ data: [] })) {
  const locale = ref('en')
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: '/', name: 'MainLayout', component: {}, children: [
      { path: 'plugin', name: 'Plugin', component: {} },
      { path: 'plugin-page/:pluginId/:pageRoute(.*)', name: 'PluginPagePlaceholder', component: {}, meta: { pluginPage: true } },
    ] }],
  })
  const module = { exports: {} }
  runInNewContext(outputText, {
    module, exports: module.exports, console: { error() {} },
    require(id) {
      if (id === 'pinia') return { defineStore: (_, factory) => factory }
      if (id === 'vue') return { ref }
      if (id === 'vue-i18n') return { useI18n: () => ({ locale }) }
      if (id === '@/api/plugin') return { getPlugins }
      if (id === '@/router') return { default: router }
      throw new Error(`Unexpected import: ${id}`)
    },
  })
  return { store: module.exports.usePluginMenuStore(), router, locale }
}

const plugin = (enabled = true, menus = [
  { route: '/page/plugin/demo/dashboard', label: { en: 'Dashboard', zh: '仪表盘' }, icon: 'Box', order: 10 },
]) => ({ id: 'demo', name: 'Demo', enabled, menus })
const routeName = 'plugin-page-demo-dashboard'

test('installation, disabling, enabling and uninstalling reconcile menus and real router records', () => {
  const { store, router } = setup()
  store.syncMenus([plugin()])
  assert.equal(store.menus.value[0].label, 'Dashboard')
  assert.equal(router.hasRoute(routeName), true)
  assert.equal(router.resolve('/plugin-page/demo/dashboard').name, routeName)
  store.syncMenus([plugin(false)])
  assert.equal(store.menus.value.length, 0)
  assert.equal(router.hasRoute(routeName), false)
  store.syncMenus([plugin()])
  assert.equal(router.hasRoute(routeName), true)
  store.syncMenus([])
  assert.equal(store.menus.value.length, 0)
  assert.equal(router.hasRoute(routeName), false)
  assert.equal(router.hasRoute('PluginPagePlaceholder'), true)
  assert.equal(router.hasRoute('Plugin'), true)
})

test('loading completion and reload replace page routes without duplicates and respect locale', () => {
  const { store, router, locale } = setup()
  store.syncMenus([plugin(true, [])])
  assert.equal(store.menus.value.length, 0)
  locale.value = 'zh'
  store.syncMenus([plugin()])
  assert.equal(store.menus.value[0].label, '仪表盘')
  store.syncMenus([plugin()])
  assert.equal(router.getRoutes().filter(r => r.name === routeName).length, 1)
  store.syncMenus([plugin(true, [{ route: '/page/plugin/demo/settings', label: 'Settings', order: 1 }])])
  assert.equal(router.hasRoute(routeName), false)
  assert.equal(router.hasRoute('plugin-page-demo-settings'), true)
})

test('a delayed initial sidebar fetch cannot restore a disabled or uninstalled menu', async () => {
  let resolve
  const { store, router } = setup(() => new Promise(done => { resolve = done }))
  const pending = store.fetchAndRegisterMenus()
  store.syncMenus([])
  resolve({ data: [plugin()] })
  await pending
  assert.equal(store.menus.value.length, 0)
  assert.equal(router.hasRoute(routeName), false)
})

test('out-of-order menu fetches use the newest response and failed fetches retain known menus', async () => {
  const pending = []
  const { store, router } = setup(() => new Promise((resolve, reject) => pending.push({ resolve, reject })))
  const first = store.fetchAndRegisterMenus()
  const second = store.fetchAndRegisterMenus()
  pending[1].resolve({ data: [plugin()] })
  await second
  pending[0].resolve({ data: [] })
  await first
  assert.equal(router.hasRoute(routeName), true)
  const failed = store.fetchAndRegisterMenus()
  pending[2].reject(new Error('offline'))
  await failed
  assert.equal(store.menus.value.length, 1)
  assert.equal(router.hasRoute(routeName), true)
})
