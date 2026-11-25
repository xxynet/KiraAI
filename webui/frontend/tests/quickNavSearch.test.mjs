import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { test } from 'node:test'
import { runInNewContext } from 'node:vm'
import ts from 'typescript'

const source = readFileSync(new URL('../src/utils/quickNavSearch.ts', import.meta.url), 'utf8')
const compiled = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
}).outputText
const module = { exports: {} }
runInNewContext(compiled, {
  module,
  exports: module.exports,
  require() {
    throw new Error('quickNavSearch.ts must stay dependency-free')
  },
})
const { searchQuickNav, isQuickNavShortcut, quickNavShortcutLabel, detectMacPlatform } = module.exports

function entries() {
  return [
    { id: '/overview', route: '/overview', label: 'Overview', group: '' },
    { id: '/webchat', route: '/webchat', label: 'Web Chat', group: '' },
    { id: '/settings', route: '/settings', label: 'Settings', group: '' },
    { id: '/log', route: '/logs', label: 'Log', group: '' },
    { id: '/plugin-page/a/dashboard', route: '/plugin-page/a/dashboard', label: 'Dashboard', group: 'More features' },
    { id: '/plugin-page/b/logs', route: '/plugin-page/b/logs', label: 'Audit log', group: '更多功能' },
    { id: '/plugin-page/c/i18n', route: '/plugin-page/c/i18n', label: '设置项', group: '基础设置' },
  ]
}

// Array.from keeps results in the test realm: search runs in its own VM context,
// so a plain .map() on its arrays would return arrays with a foreign prototype.
const ids = matched => Array.from(matched, entry => entry.id)

test('an empty or whitespace query keeps every entry in sidebar order', () => {
  const all = entries()
  assert.deepEqual(ids(searchQuickNav(all, '')), ids(all))
  assert.deepEqual(ids(searchQuickNav(all, '   ')), ids(all))
})

test('labels match case-insensitively, including prefixes', () => {
  assert.deepEqual(ids(searchQuickNav(entries(), 'OVER')), ['/overview'])
  assert.deepEqual(ids(searchQuickNav(entries(), 'chat')), ['/webchat'])
  assert.deepEqual(ids(searchQuickNav(entries(), 'set')), ['/settings'])
})

test('group and route matches are searched too', () => {
  assert.deepEqual(ids(searchQuickNav(entries(), '更多')), ['/plugin-page/b/logs'])
  assert.deepEqual(ids(searchQuickNav(entries(), '基础设置')), ['/plugin-page/c/i18n'])
  assert.deepEqual(ids(searchQuickNav(entries(), 'plugin-page')), [
    '/plugin-page/a/dashboard',
    '/plugin-page/b/logs',
    '/plugin-page/c/i18n',
  ])
})

test('every whitespace-separated token must match', () => {
  assert.deepEqual(ids(searchQuickNav(entries(), 'web chat')), ['/webchat'])
  assert.deepEqual(ids(searchQuickNav(entries(), 'web settings')), [])
})

test('exact and prefix label matches rank ahead of weaker matches', () => {
  // "Log" matches its own label exactly, "Audit log" only at a word boundary.
  assert.deepEqual(ids(searchQuickNav(entries(), 'log')), ['/log', '/plugin-page/b/logs'])
  // "设置项" starts with the query, so it wins over the group-only match.
  assert.deepEqual(ids(searchQuickNav(entries(), '设置')), ['/plugin-page/c/i18n'])
})

test('a query without any match returns nothing', () => {
  // Compare ids: the search runs in a separate VM context, so its arrays have a
  // different prototype and strict deep-equal would reject an empty/empty pair.
  assert.deepEqual(ids(searchQuickNav(entries(), 'zzz')), [])
})

test('the shortcut is Ctrl+K or Cmd+K only', () => {
  assert.equal(isQuickNavShortcut({ key: 'k', ctrlKey: true }), true)
  assert.equal(isQuickNavShortcut({ key: 'K', ctrlKey: true }), true)
  assert.equal(isQuickNavShortcut({ key: 'k', metaKey: true }), true)
  assert.equal(isQuickNavShortcut({ key: 'k' }), false)
  assert.equal(isQuickNavShortcut({ key: 'j', ctrlKey: true }), false)
  assert.equal(isQuickNavShortcut({ key: 'k', ctrlKey: true, shiftKey: true }), false)
  assert.equal(isQuickNavShortcut({ key: 'k', ctrlKey: true, altKey: true }), false)
  assert.equal(isQuickNavShortcut({ key: 'k', ctrlKey: true, repeat: true }), false)
  assert.equal(isQuickNavShortcut({ key: 'K', ctrlKey: true, altKey: false, shiftKey: false, repeat: false }), true)
})

test('the shortcut hint follows the platform', () => {
  assert.equal(detectMacPlatform('MacIntel'), true)
  assert.equal(detectMacPlatform('iPhone'), true)
  assert.equal(detectMacPlatform('Win32'), false)
  assert.equal(detectMacPlatform('Linux x86_64'), false)
  assert.equal(quickNavShortcutLabel(true), '⌘K')
  assert.equal(quickNavShortcutLabel(false), 'Ctrl K')
})
