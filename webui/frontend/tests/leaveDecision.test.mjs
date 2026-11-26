import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { test } from 'node:test'
import { runInNewContext } from 'node:vm'
import ts from 'typescript'
import { createMemoryHistory, createRouter, isNavigationFailure } from 'vue-router'

const source = readFileSync(new URL('../src/utils/leaveDecision.ts', import.meta.url), 'utf8')
const compiled = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
}).outputText
const module = { exports: {} }
runInNewContext(compiled, {
  module,
  exports: module.exports,
  require() {
    throw new Error('leaveDecision.ts must stay dependency-free')
  },
})
const { createLeaveGate, needsLeaveDecision } = module.exports

const auth = ['Login', 'SetupToken']

test('a navigation only prompts when edits would actually be lost', () => {
  const configToOverview = {
    targetFullPath: '/overview',
    currentFullPath: '/configuration',
    unsavedChanges: 1,
    targetName: 'Overview',
    allowedNames: auth,
  }
  assert.equal(needsLeaveDecision(configToOverview), true)
  assert.equal(needsLeaveDecision({ ...configToOverview, unsavedChanges: 0 }), false)
  assert.equal(needsLeaveDecision({ ...configToOverview, targetFullPath: '/configuration' }), false)
  assert.equal(needsLeaveDecision({ ...configToOverview, targetName: 'Login' }), false)
  assert.equal(needsLeaveDecision({ ...configToOverview, targetName: 'SetupToken' }), false)
})

test('a query-only change is guarded: the keyed view remounts and drops edits', () => {
  const queryChange = {
    targetFullPath: '/configuration',
    currentFullPath: '/configuration?tab=models',
    unsavedChanges: 2,
    targetName: 'Configuration',
    allowedNames: auth,
  }
  assert.equal(needsLeaveDecision(queryChange), true)
  assert.equal(
    needsLeaveDecision({ ...queryChange, currentFullPath: '/configuration', targetFullPath: '/configuration' }),
    false,
  )
})

test('the gate settles the waiting navigation exactly once', async () => {
  const gate = createLeaveGate()
  assert.equal(gate.pending, false)

  const leaving = gate.wait()
  assert.equal(gate.pending, true)
  assert.equal(gate.settle(true), true)
  assert.equal(gate.pending, false)
  assert.equal(await leaving, true)

  // A stale answer arrives after the decision was already made.
  assert.equal(gate.settle(false), false)

  const staying = gate.wait()
  assert.equal(gate.settle(false), true)
  assert.equal(await staying, false)
})

test('a second navigation settles the first one with stay and waits itself', async () => {
  const gate = createLeaveGate()
  const first = gate.wait()
  const second = gate.wait()
  assert.equal(await first, false)
  assert.equal(gate.settle(true), true)
  assert.equal(await second, true)
  assert.equal(gate.pending, false)
})

const configSource = readFileSync(new URL('../src/views/ConfigView.vue', import.meta.url), 'utf8')
const guardSource = configSource.slice(
  configSource.indexOf('async function requestLeaveDecision('),
  configSource.indexOf('onBeforeRouteLeave(requestLeaveDecision)'),
)

for (const [mode, leave] of [['push', true], ['push', false], ['history', true], ['history', false]]) {
  test(`a second ${mode} navigation owns the dialog decision when leave is ${leave}`, async () => {
    const router = createRouter({
      history: createMemoryHistory(),
      routes: ['/configuration', '/overview', '/provider'].map(path => ({ path, component: {} })),
    })
    await router.push('/overview')
    await router.push('/provider')
    await router.push('/configuration')
    const gate = createLeaveGate()
    const context = {
      needsLeaveDecision,
      leaveGate: gate,
      modifiedFields: new Set(['field']),
      unsavedDialogVisible: { value: false },
      route: router.currentRoute.value,
      AUTH_ROUTE_NAMES: auth,
    }
    runInNewContext(ts.transpileModule(guardSource, {
      compilerOptions: { target: ts.ScriptTarget.ES2020 },
    }).outputText, context)
    router.currentRoute.value.matched[0].leaveGuards.add(context.requestLeaveDecision)
    const results = []
    router.afterEach((_to, _from, failure) => results.push(failure))
    const first = mode === 'push' ? router.push('/overview') : router.back()
    await new Promise(resolve => setImmediate(resolve))
    const second = mode === 'push' ? router.push('/provider') : router.back()
    await new Promise(resolve => setImmediate(resolve))
    assert.equal(context.unsavedDialogVisible.value, true)
    assert.equal(gate.settle(leave), true)
    await Promise.all([first, second])
    await new Promise(resolve => setImmediate(resolve))
    assert.ok(isNavigationFailure(results[0]))
    assert.equal(isNavigationFailure(results[1]), !leave)
    const target = mode === 'push' ? '/provider' : '/overview'
    assert.equal(router.currentRoute.value.path, leave ? target : '/configuration')
    assert.equal(gate.pending, false)
    if (mode === 'history' && leave) {
      router.forward()
      await new Promise(resolve => setImmediate(resolve))
      assert.equal(router.currentRoute.value.path, '/provider')
    }
  })
}
