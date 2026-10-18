import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import { test } from 'node:test'
import { runInNewContext } from 'node:vm'
import { parse, compileScript } from '@vue/compiler-sfc'
import ts from 'typescript'
import * as Vue from 'vue'

const require = createRequire(import.meta.url)
const filename = new URL('../src/components/common/CustomMultiSelect.vue', import.meta.url).pathname
const { descriptor } = parse(readFileSync(new URL('../src/components/common/CustomMultiSelect.vue', import.meta.url), 'utf8'), { filename })
const script = compileScript(descriptor, { id: 'multiselect-order-test' })
const { outputText } = ts.transpileModule(script.content, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
})
const module = { exports: {} }
runInNewContext(outputText, {
  module,
  exports: module.exports,
  require(id) {
    if (id === 'vue') return { ...Vue, onUnmounted() {} }
    if (id === '@/components/icons') return {}
    return require(id)
  },
  setTimeout,
  clearTimeout,
})
const component = module.exports.default

function control(values = [], options = [{ value: 'a', label: 'A' }, { value: 'b', label: 'B' }]) {
  const props = Vue.reactive({ modelValue: [...values], options, allowCustom: true })
  const emitted = []
  const state = component.setup(props, {
    expose() {},
    emit(event, value) {
      assert.equal(event, 'update:modelValue')
      emitted.push(value)
      props.modelValue = value
    },
  })
  return { props, state, emitted, displayed: () => state.selectedOptions.value.map(option => option.value) }
}

test('saved order interleaves known and custom values without emitting changes', () => {
  const { displayed, emitted, state } = control(['b', 'custom', 'a'])
  assert.deepEqual(Array.from(displayed()), ['b', 'custom', 'a'])
  assert.deepEqual(Array.from(state.selectedOptions.value, option => option.label), ['B', 'custom', 'A'])
  assert.equal(emitted.length, 0)
})

test('clicks and typed entries keep their shared insertion order', () => {
  const { state, props, displayed } = control()
  state.toggleOption('b')
  state.customDraft.value = '  custom  '
  state.commitCustomValue()
  state.toggleOption('a')
  assert.deepEqual(Array.from(props.modelValue), ['b', 'custom', 'a'])
  assert.deepEqual(Array.from(displayed()), ['b', 'custom', 'a'])
})

test('removing and readding an item moves only that item to the end', () => {
  const { state, props, displayed } = control(['b', 'custom', 'a'])
  state.removeOption('b')
  assert.deepEqual(Array.from(displayed()), ['custom', 'a'])
  state.toggleOption('b')
  assert.deepEqual(Array.from(props.modelValue), ['custom', 'a', 'b'])
  assert.deepEqual(Array.from(displayed()), ['custom', 'a', 'b'])
  state.toggleOption('custom')
  state.customDraft.value = 'custom'
  state.commitCustomValue()
  assert.deepEqual(Array.from(displayed()), ['a', 'b', 'custom'])
})

test('refreshing options updates labels without moving or dropping saved values', () => {
  const { props, state, displayed, emitted } = control(['b', 'custom', 'a'], [])
  assert.deepEqual(Array.from(displayed()), ['b', 'custom', 'a'])
  props.options = [{ value: 'a', label: 'Renamed A' }, { value: 'custom', label: 'Now Known' }]
  assert.deepEqual(Array.from(displayed()), ['b', 'custom', 'a'])
  assert.deepEqual(Array.from(state.selectedOptions.value, option => option.label), ['b', 'Now Known', 'Renamed A'])
  props.options.reverse()
  assert.deepEqual(Array.from(displayed()), ['b', 'custom', 'a'])
  assert.equal(emitted.length, 0)
})

test('empty or duplicate input does not reorder selections and saved reload order is respected', () => {
  const { state, props, displayed, emitted } = control(['b', 'a'])
  for (const value of [' ', 'a', 'b']) {
    state.customDraft.value = value
    state.commitCustomValue()
  }
  assert.equal(emitted.length, 0)
  assert.deepEqual(Array.from(displayed()), ['b', 'a'])
  props.modelValue = ['a', 'b']
  assert.deepEqual(Array.from(displayed()), ['a', 'b'])
  props.modelValue = []
  assert.deepEqual(Array.from(displayed()), [])
})
