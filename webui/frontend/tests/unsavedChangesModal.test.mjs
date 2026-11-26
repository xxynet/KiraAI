import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { test } from 'node:test'
import { runInNewContext } from 'node:vm'
import { parse, compileScript } from '@vue/compiler-sfc'
import ts from 'typescript'
import * as Vue from 'vue'

const filename = new URL('../src/components/common/UnsavedChangesModal.vue', import.meta.url).pathname
const { descriptor } = parse(
  readFileSync(new URL('../src/components/common/UnsavedChangesModal.vue', import.meta.url), 'utf8'),
  { filename },
)
const script = compileScript(descriptor, { id: 'unsaved-changes-modal-test' })
const { outputText } = ts.transpileModule(script.content, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
})
const module = { exports: {} }
runInNewContext(outputText, {
  module,
  exports: module.exports,
  require(id) {
    if (id === 'vue') return Vue
    if (id === './Modal.vue') return { default: {} }
    if (id === '@/components/icons') return { IconWarning: {} }
    throw new Error(`Unexpected dependency: ${id}`)
  },
})
const component = module.exports.default

const baseProps = {
  modelValue: true,
  title: 'Unsaved configuration changes',
  message: 'You have 2 unsaved change(s). Save before leaving this page?',
  saveText: 'Save and leave',
  discardText: 'Leave without saving',
  stayText: 'Stay on this page',
}

function mount() {
  const emitted = []
  const state = component.setup({ ...baseProps }, {
    expose() {},
    emit(event, payload) {
      emitted.push(payload === undefined ? event : [event, payload])
    },
  })
  return { state, emitted }
}

test('each dialog action emits its own event and leaves closing to the caller', () => {
  const save = mount()
  save.state.onSave()
  assert.deepEqual(save.emitted, ['save'])

  const discard = mount()
  discard.state.onDiscard()
  assert.deepEqual(discard.emitted, ['discard'])

  const stay = mount()
  stay.state.onStay()
  assert.deepEqual(stay.emitted, ['stay'])
})

test('dismissing the modal reports a visibility change and a stay', () => {
  const { state, emitted } = mount()
  state.onVisibleChange(false)
  state.onStay()
  assert.deepEqual(emitted, [['update:modelValue', false], 'stay'])
})
