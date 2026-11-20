import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { test } from 'node:test'
import { runInNewContext } from 'node:vm'
import ts from 'typescript'
import { computed, ref, reactive, defineComponent } from 'vue'
import * as Vue from 'vue'
import { parse, compileScript } from '@vue/compiler-sfc'

function load(path, mocks = {}, globals = {}) {
  const source = readFileSync(new URL(path, import.meta.url), 'utf8')
  return evaluate(source, mocks, globals)
}

function evaluate(source, mocks = {}, globals = {}) {
  const { outputText } = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
  })
  const module = { exports: {} }
  runInNewContext(outputText, {
    module, exports: module.exports, ...globals,
    require(id) {
      if (id in mocks) return mocks[id]
      throw new Error(`Unexpected import: ${id}`)
    },
  })
  return module.exports
}

const model = load('../src/navigation/sidebarLayout.ts')
const { normalizeSidebarLayout, reconcileSidebarLayout, moveSidebarItem, moveSidebarGroup, removeSidebarGroup } = model
const plain = value => JSON.parse(JSON.stringify(value))
const item = id => ({ type: 'item', id })
const group = (id, items = [], name = id) => ({ type: 'group', id, name, items })
const catalog = [
  { id: '/overview', isPlugin: false },
  { id: '/settings', isPlugin: false },
  { id: '/plugin-page/demo/a', isPlugin: true },
  { id: '/plugin-page/demo/b', isPlugin: true },
]
const ids = layout => layout.flatMap(entry => entry.type === 'group' ? entry.items : [entry.id])

test('default layout keeps builtin order and puts plugin pages in more features', () => {
  assert.deepEqual(plain(reconcileSidebarLayout(null, catalog)), [
    item('/overview'), item('/settings'), group('more-features', ['/plugin-page/demo/a', '/plugin-page/demo/b'], ''),
  ])
})

test('normalization rejects malformed entries and removes duplicate routes and group IDs', () => {
  const layout = normalizeSidebarLayout([
    null, {}, item('invalid'), item('/overview'), item('/overview'),
    group('work', ['/overview', '/settings', '/settings', null]),
    group('work', ['/plugin-page/demo/a']), group('empty-name', [], '  '),
    group('unsafe group', []), group('more-features', [], ''),
  ])
  assert.deepEqual(plain(layout), [item('/overview'), group('work', ['/settings']), group('more-features', [], '')])
  assert.equal(normalizeSidebarLayout({}), null)
})

test('new plugin pages join the default group without moving customized entries', () => {
  const saved = [group('personal', ['/plugin-page/demo/a']), item('/settings'), group('more-features', [], '')]
  const snapshot = plain(saved)
  const result = reconcileSidebarLayout(saved, catalog)
  assert.deepEqual(plain(result), [item('/settings'), item('/overview'), snapshot[0], group('more-features', ['/plugin-page/demo/b'], '')])
  assert.deepEqual(saved, snapshot)
})

test('removing more features is respected when new plugin pages arrive', () => {
  const saved = [item('/settings'), group('personal', ['/overview'])]
  const result = reconcileSidebarLayout(saved, catalog)
  assert.equal(result.some(entry => entry.id === 'more-features'), false)
  assert.deepEqual(plain(result.filter(entry => entry.type === 'item').slice(-2)), [item('/plugin-page/demo/a'), item('/plugin-page/demo/b')])
})

test('plugin disabling and re-enabling retain saved order and group assignment', () => {
  const saved = [item('/settings'), group('personal', ['/plugin-page/demo/b', '/overview', '/plugin-page/demo/a'])]
  const unavailable = reconcileSidebarLayout(saved, catalog.filter(entry => !entry.isPlugin))
  assert.deepEqual(plain(unavailable), saved)
  assert.deepEqual(plain(reconcileSidebarLayout(unavailable, catalog)), saved)
})

test('items move between groups and arbitrary top-level positions without loss or mutation', () => {
  const source = [item('/overview'), group('work', ['/settings', '/plugin-page/demo/a']), group('personal', ['/plugin-page/demo/b'])]
  const snapshot = plain(source)
  let result = moveSidebarItem(source, '/settings', 'personal', '/plugin-page/demo/b')
  assert.deepEqual(plain(result[2].items), ['/settings', '/plugin-page/demo/b'])
  result = moveSidebarItem(result, '/settings', null, 'work')
  assert.deepEqual(plain(result.slice(0, 2)), [item('/overview'), item('/settings')])
  assert.deepEqual([...ids(result)].sort(), [...ids(source)].sort())
  assert.equal(new Set(ids(result)).size, ids(result).length)
  assert.deepEqual(source, snapshot)
})

test('moving within the same group handles both directions and appending', () => {
  const source = [group('work', ['/overview', '/settings', '/plugin-page/demo/a'])]
  let result = moveSidebarItem(source, '/plugin-page/demo/a', 'work', '/overview')
  assert.deepEqual(plain(result[0].items), ['/plugin-page/demo/a', '/overview', '/settings'])
  result = moveSidebarItem(result, '/plugin-page/demo/a', 'work')
  assert.deepEqual(plain(result), source)
})

test('invalid destinations and self drops leave the layout unchanged', () => {
  const source = [item('/overview'), group('work', ['/settings'])]
  for (const args of [['/overview', 'missing'], ['/overview', null, '/missing'], ['/settings', 'work', '/settings'], ['/missing', null]]) {
    assert.deepEqual(plain(moveSidebarItem(source, ...args)), source)
  }
})

test('groups reorder only below ungrouped items and cannot cross the boundary', () => {
  const source = [item('/overview'), item('/plugin-page/demo/a'), group('work', ['/settings']), group('personal', ['/plugin-page/demo/b'])]
  assert.deepEqual(plain(moveSidebarGroup(source, 'work', '/overview')), source)
  const first = moveSidebarGroup(source, 'personal', 'work')
  assert.deepEqual(plain(first), [source[0], source[1], source[3], source[2]])
  const last = moveSidebarGroup(first, 'personal')
  assert.deepEqual(plain(last), source)
  assert.deepEqual(plain(moveSidebarGroup(source, 'work', 'work')), source)
})

test('removing a later group promotes all its items before the remaining groups', () => {
  const source = [item('/overview'), group('keep'), group('work', ['/plugin-page/inactive/page', '/settings'])]
  assert.deepEqual(plain(removeSidebarGroup(source, 'work')), [item('/overview'), item('/plugin-page/inactive/page'), item('/settings'), group('keep')])
})

test('normalization always places ungrouped items first without changing group membership', () => {
  const mixed = [group('work', ['/settings']), item('/overview'), group('personal'), item('/plugin-page/demo/a')]
  const expected = [mixed[1], mixed[3], mixed[0], mixed[2]]
  assert.deepEqual(plain(normalizeSidebarLayout(mixed)), expected)
  assert.deepEqual(plain(reconcileSidebarLayout(mixed, [])), expected)
  const { store } = storageSetup(JSON.stringify(mixed))
  assert.deepEqual(plain(store.layout.value), expected)
})

test('ungrouping and newly discovered pages always insert before groups', () => {
  const source = [item('/overview'), group('work', ['/settings', '/plugin-page/demo/a']), group('keep')]
  const ungrouped = moveSidebarItem(source, '/settings', null)
  assert.deepEqual(plain(ungrouped), [item('/overview'), item('/settings'), group('work', ['/plugin-page/demo/a']), group('keep')])
  const overLaterGroup = moveSidebarItem(source, '/settings', null, 'keep')
  assert.deepEqual(plain(overLaterGroup), plain(ungrouped))
  const updated = reconcileSidebarLayout(source, [...catalog, { id: '/new-page', isPlugin: false }])
  let hasGroup = false
  for (const entry of updated) {
    if (entry.type === 'group') hasGroup = true
    else assert.equal(hasGroup, false)
  }
  assert.ok(updated.some(entry => entry.id === '/new-page'))
  assert.ok(updated.some(entry => entry.id === '/plugin-page/demo/b'))
})

function storageSetup(saved = null, openedItems = null) {
  const storage = new Map(saved === null ? [] : [['sidebar_layout', saved]])
  if (openedItems !== null) storage.set('sidebar_opened_items', openedItems)
  const errors = []
  const localStorage = {
    getItem: key => storage.get(key) ?? null,
    setItem: (key, value) => storage.set(key, value),
    removeItem: key => storage.delete(key),
  }
  const module = load('../src/stores/sidebar.ts', {
    pinia: { defineStore: (_, factory) => factory }, vue: { ref }, '@/navigation/sidebarLayout': model,
  }, { localStorage, console: { error: (...args) => errors.push(args) } })
  return { store: module.useSidebarStore(), storage, errors, localStorage }
}

test('saved layouts survive reload, reset removes the preference and malformed JSON is reported', () => {
  const { store, storage } = storageSetup()
  assert.equal(store.layout.value, null)
  const layout = [group('work', ['/settings'])]
  store.setLayout(layout)
  assert.deepEqual(plain(storageSetup(storage.get('sidebar_layout')).store.layout.value), layout)
  store.setLayout(null)
  assert.equal(store.layout.value, null)
  assert.equal(storage.has('sidebar_layout'), false)
  const malformed = storageSetup('{invalid')
  assert.equal(malformed.store.layout.value, null)
  assert.equal(malformed.errors.length, 1)
  assert.ok(malformed.errors[0][1])
})

test('failed persistence does not apply an unsaved layout', () => {
  const { store, localStorage } = storageSetup()
  localStorage.setItem = () => { throw new Error('Storage full') }
  assert.throws(() => store.setLayout([item('/settings')]), /Storage full/)
  assert.equal(store.layout.value, null)
})

test('opened groups are saved immediately and survive reload and layout changes', () => {
  const { store, storage } = storageSetup()
  assert.equal(store.hasSavedOpenedItems.value, false)
  store.setGroupExpanded('work', true)
  store.setGroupExpanded('more-features', true)
  assert.equal(store.hasSavedOpenedItems.value, true)
  assert.deepEqual(JSON.parse(storage.get('sidebar_opened_items')), ['work', 'more-features'])
  store.setGroupExpanded('work', false)
  store.setLayout([group('more-features', ['/plugin-page/demo/a'], '')])
  const reloaded = storageSetup(null, storage.get('sidebar_opened_items')).store
  assert.deepEqual(Array.from(reloaded.expandedGroups.value), ['more-features'])
  assert.equal(reloaded.hasSavedOpenedItems.value, true)
  assert.equal(storage.has('sidebar_openedItems'), false)
})

test('opened group input is validated, deduplicated and malformed records are reported', () => {
  const loaded = storageSetup(null, '["work","work",null,123,"/overview","","bad id","more-features"]')
  assert.deepEqual(Array.from(loaded.store.expandedGroups.value), ['work', 'more-features'])
  for (const invalid of ['{invalid', '{}']) {
    const { store, errors } = storageSetup(null, invalid)
    assert.equal(store.expandedGroups.value.size, 0)
    assert.equal(store.hasSavedOpenedItems.value, false)
    assert.equal(errors.length, 1)
    assert.ok(errors[0][1])
  }
})

test('a storage failure is logged and does not prevent toggling groups in memory', () => {
  const { store, localStorage, errors } = storageSetup()
  localStorage.setItem = () => { throw new Error('Storage blocked') }
  store.setGroupExpanded('work', true)
  assert.equal(store.expandedGroups.value.has('work'), true)
  assert.equal(errors.length, 1)
  assert.match(String(errors[0][1]), /Storage blocked/)
  store.setGroupExpanded('work', true)
  assert.equal(errors.length, 1)
  store.setGroupExpanded('work', false)
  assert.equal(store.expandedGroups.value.has('work'), false)
})

function sidebarSetup(openedItems, path = '/settings', initialGroups) {
  const storageState = storageSetup(null, openedItems)
  const sidebarStore = reactive(storageState.store)
  const route = reactive({ path })
  const groups = ref(initialGroups ?? [
    { id: 'work', label: 'Work', items: [{ route: '/settings' }] },
    { id: 'more-features', label: 'More', items: [{ route: '/plugin-page/demo/page' }] },
  ])
  const { descriptor } = parse(readFileSync(new URL('../src/components/layout/AppSidebar.vue', import.meta.url), 'utf8'))
  const script = compileScript(descriptor, { id: 'sidebar-expansion-test' })
  const component = evaluate(script.content, {
    vue: { ...Vue, onMounted() {} }, 'vue-router': { useRoute: () => route },
    'vue-i18n': { useI18n: () => ({ locale: ref('en') }) },
    '@/stores/app': { useAppStore: () => ({ sidebarGroupStyle: 'section', language: 'en' }) },
    '@/stores/sidebar': { useSidebarStore: () => sidebarStore },
    '@/stores/pluginMenu': { usePluginMenuStore: () => ({ reResolveLabels() {} }) },
    '@/composables/useSidebarNavigation': { useSidebarNavigation: () => ({ navGroups: groups }) },
    '@/api/overview': {}, '@/components/common/CustomSelect.vue': {}, '@/components/common/InlineSvgIcon.vue': {},
    '@element-plus/icons-vue': {},
  }).default
  const scope = Vue.effectScope()
  const mount = () => scope.run(() => component.setup({ open: true }, { expose() {} }))
  return { ...storageState, store: sidebarStore, route, groups, state: mount(), remount: mount, stop: () => scope.stop() }
}

test('first use reveals the current group, while a manual collapse survives menu refresh and remount', async t => {
  const env = sidebarSetup(null)
  t.after(env.stop)
  assert.equal(env.state.expandedGroups.value.has('work'), true)
  env.state.toggleGroup('work')
  assert.deepEqual(JSON.parse(env.storage.get('sidebar_opened_items')), [])
  const groups = env.groups.value
  env.groups.value = []
  await Vue.nextTick()
  env.groups.value = groups
  await Vue.nextTick()
  assert.equal(env.store.expandedGroups.has('work'), false)
  env.remount()
  assert.equal(env.store.expandedGroups.has('work'), false)
})

test('saved collapse wins on refresh and delayed menu loading; navigation still reveals groups', async t => {
  const env = sidebarSetup('[]', '/plugin-page/demo/page', [])
  t.after(env.stop)
  env.groups.value = [
    { id: 'work', label: 'Work', items: [{ route: '/settings' }] },
    { id: 'more-features', label: 'More', items: [{ route: '/plugin-page/demo/page' }] },
  ]
  await Vue.nextTick()
  assert.equal(env.store.expandedGroups.size, 0)
  env.route.path = '/settings'
  await Vue.nextTick()
  assert.equal(env.store.expandedGroups.has('work'), true)
  env.route.path = '/plugin-page/demo/page'
  await Vue.nextTick()
  assert.equal(env.store.expandedGroups.has('more-features'), true)
  assert.deepEqual(JSON.parse(env.storage.get('sidebar_opened_items')), ['work', 'more-features'])
})

test('navigation resolves live plugin pages, literal group names and missing entries reactively', () => {
  const menus = ref([{ route: '/plugin-page/demo/a', label: 'Plugin page', icon: '/api/plugins/demo/icon' }])
  const layout = ref([group('custom', ['/plugin-page/demo/a', '/settings'], 'My tools')])
  const { useSidebarNavigation } = load('../src/composables/useSidebarNavigation.ts', {
    vue: { computed }, 'vue-i18n': { useI18n: () => ({ t: key => `translated:${key}` }) },
    '@element-plus/icons-vue': { Box: 'box', MoreFilled: 'more', Folder: 'folder' },
    '@/stores/pluginMenu': { usePluginMenuStore: () => ({ get menus() { return menus.value } }) },
    '@/stores/sidebar': { useSidebarStore: () => ({ get layout() { return layout.value } }) },
    '@/utils/iconMap': { iconMap: {} }, '@/navigation/sidebarLayout': model,
  })
  const nav = useSidebarNavigation()
  const custom = () => nav.navGroups.value.find(entry => entry.id === 'custom')
  assert.equal(custom().label, 'My tools')
  assert.equal(custom().items[0].iconUrl, '/api/plugins/demo/icon')
  assert.deepEqual(Array.from(custom().items, entry => entry.route), ['/plugin-page/demo/a', '/settings'])
  menus.value = []
  assert.deepEqual(Array.from(custom().items, entry => entry.route), ['/settings'])
  menus.value = [{ route: '/plugin-page/demo/a', label: 'New label', icon: 'unknown' }]
  assert.equal(custom().items[0].label, 'New label')
  assert.equal(custom().items[0].icon, 'box')
  assert.equal(custom().items[0].iconUrl, null)
  layout.value = [group('custom', ['/plugin-page/demo/a'], 'My tools')]
  menus.value = []
  assert.equal(custom(), undefined)
})

function editorSetup() {
  const sources = ref(catalog.map(entry => ({ ...entry, route: entry.id, label: entry.id })))
  const { descriptor } = parse(readFileSync(new URL('../src/components/layout/SidebarLayoutEditor.vue', import.meta.url), 'utf8'))
  const script = compileScript(descriptor, { id: 'sidebar-editor-test' })
  const component = evaluate(script.content, {
    vue: { ref, computed, defineComponent }, '@element-plus/icons-vue': {},
    '@/components/ui/UiInput.vue': {}, './SidebarLayoutItem.vue': {},
    '@/navigation/sidebarLayout': model,
    '@/composables/useSidebarDrag': { useSidebarDrag: () => ({ dragged: ref(null), startDrag() {} }) },
    '@/composables/useSidebarNavigation': { useSidebarNavigation: () => ({
      items: sources, itemMap: computed(() => new Map(sources.value.map(entry => [entry.id, entry]))),
      groupLabel: entry => entry.name || 'More Features',
    }) },
  }, { crypto: globalThis.crypto, Uint32Array }).default
  const props = reactive({ modelValue: null })
  const state = component.setup(props, { expose() {}, emit: (name, value) => {
    assert.equal(name, 'update:modelValue')
    props.modelValue = value
  } })
  return { props, state, sources }
}

test('editor creates and renames groups, preserves composing input and removes groups without losing pages', () => {
  const { props, state } = editorSetup()
  state.newGroupName.value = ' Personal '
  state.handleNewGroupKeydown({ key: 'Enter', isComposing: true, preventDefault() { throw new Error('Composition must not be interrupted') } })
  assert.equal(props.modelValue, null)
  state.addGroup()
  let personal = props.modelValue.at(-1)
  assert.equal(personal.name, 'Personal')
  state.moveItem('/plugin-page/demo/a', personal.id)
  personal = props.modelValue.find(entry => entry.id === personal.id)
  const input = { value: '  My tools  ' }
  state.renameGroup(personal, { target: input })
  personal = props.modelValue.find(entry => entry.id === personal.id)
  assert.equal(personal.name, 'My tools')
  input.value = '   '
  state.renameGroup(personal, { target: input })
  assert.equal(input.value, 'My tools')
  state.removeGroup(personal.id)
  assert.equal(props.modelValue.filter(entry => entry.type === 'item').at(-1).id, '/plugin-page/demo/a')
  assert.deepEqual([...ids(props.modelValue)].sort(), catalog.map(entry => entry.id).sort())
})

test('editor drag/drop and arrow controls reorder roots and group contents using the same draft', () => {
  const { props, state, sources } = editorSetup()
  state.applyDrop({ type: 'item', id: '/settings' }, { type: 'item', groupId: null, beforeId: '/overview' })
  assert.equal(props.modelValue[0].id, '/settings')
  state.moveRoot('/settings', 1)
  assert.equal(props.modelValue[0].id, '/overview')
  state.applyDrop({ type: 'item', id: '/overview' }, { type: 'item', groupId: 'more-features', beforeId: '/plugin-page/demo/b' })
  let features = props.modelValue.find(entry => entry.id === 'more-features')
  assert.deepEqual(plain(features.items), ['/plugin-page/demo/a', '/overview', '/plugin-page/demo/b'])
  state.moveInGroup(features, '/overview', -1)
  features = props.modelValue.find(entry => entry.id === 'more-features')
  assert.equal(features.items[0], '/overview')
  state.applyDrop({ type: 'group', id: 'more-features' }, { type: 'group', beforeId: '/settings' })
  assert.equal(props.modelValue[0].id, '/settings')
  assert.equal(state.canMoveRoot(props.modelValue[0], 1), false)
  assert.equal(state.canMoveRoot(features, -1), false)
  state.moveRoot('/settings', 1)
  state.moveRoot('more-features', -1)
  assert.equal(props.modelValue[0].id, '/settings')
  sources.value = sources.value.filter(entry => entry.id !== '/plugin-page/demo/a')
  assert.equal(state.groupItems(features).some(entry => entry.id === '/plugin-page/demo/a'), false)
  assert.ok(props.modelValue.find(entry => entry.id === 'more-features').items.includes('/plugin-page/demo/a'))
  assert.deepEqual([...ids(props.modelValue)].sort(), catalog.map(entry => entry.id).sort())
})

test('editor keeps ungrouped drops above groups and has a separate group end drop target', () => {
  const { props, state } = editorSetup()
  state.newGroupName.value = 'Personal'
  state.addGroup()
  const personalId = props.modelValue.at(-1).id
  state.applyDrop({ type: 'item', id: '/plugin-page/demo/a' }, { type: 'item', groupId: null })
  assert.equal(props.modelValue[2].id, '/plugin-page/demo/a')
  assert.equal(props.modelValue[3].type, 'group')
  state.applyDrop({ type: 'group', id: personalId }, { type: 'item', groupId: null })
  assert.equal(props.modelValue.at(-1).id, personalId)
  state.applyDrop({ type: 'group', id: 'more-features' }, { type: 'group' })
  assert.equal(props.modelValue.at(-1).id, 'more-features')
  assert.equal(props.modelValue[0].type, 'item')
  assert.equal(props.modelValue[1].type, 'item')
  assert.equal(props.modelValue[2].type, 'item')
})

test('invalid cross-type pointer drops do not change the layout', () => {
  const { state } = editorSetup()
  const original = plain(state.layout.value)
  state.applyDrop({ type: 'item', id: '/settings' }, { type: 'group' })
  state.applyDrop({ type: 'group', id: 'more-features' }, { type: 'item', groupId: null })
  assert.deepEqual(plain(state.layout.value), original)
})
