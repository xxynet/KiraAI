import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { test } from 'node:test'
import { runInNewContext } from 'node:vm'
import ts from 'typescript'
import * as Vue from 'vue'
import { createMemoryHistory, createRouter, isNavigationFailure } from 'vue-router'

const source = readFileSync(new URL('../src/composables/useRouteLoading.ts', import.meta.url), 'utf8')
const compiled = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
}).outputText

async function setup() {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: ['/configuration', '/overview'].map(path => ({ path, component: {} })),
  })
  await router.push('/configuration')
  const timers = new Map()
  let timerId = 0
  let now = 0
  const module = { exports: {} }
  runInNewContext(compiled, {
    module,
    exports: module.exports,
    require(id) {
      if (id === 'vue') return Vue
      if (id === '@/router') return { default: router }
      throw new Error(`Unexpected dependency: ${id}`)
    },
    setTimeout(callback, delay) {
      timers.set(++timerId, { callback, at: now + delay })
      return timerId
    },
    clearTimeout(id) { timers.delete(id) },
  })
  const { phase } = module.exports.useRouteLoading()
  function advance(ms) {
    now += ms
    for (const [id, timer] of [...timers]) {
      if (timer.at <= now) {
        timers.delete(id)
        timer.callback()
      }
    }
  }
  return { router, phase, advance }
}

for (const target of ['/overview', '/configuration?tab=models']) {
  test(`staying on configuration skips the completion animation when navigating to ${target}`, async () => {
    const { router, phase, advance } = await setup()
    let answer
    const guard = () => new Promise(resolve => { answer = resolve })
    const record = router.currentRoute.value.matched[0]
    record.leaveGuards.add(guard)
    record.updateGuards.add(guard)
    const navigation = router.push(target)
    await new Promise(resolve => setImmediate(resolve))
    advance(250)
    // Update guards run after beforeEach, while leave guards run before it.
    assert.equal(phase.value, target.includes('?') ? 'loading' : 'idle')
    answer(false)
    assert.ok(isNavigationFailure(await navigation))
    assert.equal(phase.value, 'idle')
    advance(500)
    assert.equal(phase.value, 'idle')
    assert.equal(router.currentRoute.value.fullPath, '/configuration')
  })
}

test('instant navigation keeps the loading bar invisible', async () => {
  const { router, phase, advance } = await setup()
  await router.push('/overview')
  advance(250)
  assert.equal(phase.value, 'idle')
})

test('slow navigation displays and completes the loading bar', async () => {
  const { router, phase, advance } = await setup()
  let resume
  router.beforeResolve(() => new Promise(resolve => { resume = resolve }))
  const navigation = router.push('/overview')
  await new Promise(resolve => setImmediate(resolve))
  advance(250)
  assert.equal(phase.value, 'loading')
  resume()
  await navigation
  assert.equal(phase.value, 'completing')
  advance(350)
  assert.equal(phase.value, 'idle')
})
