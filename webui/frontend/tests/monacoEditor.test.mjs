import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import vm from 'node:vm'
import { parse, compileScript } from '@vue/compiler-sfc'
import ts from 'typescript'

const filename = new URL('../src/components/common/MonacoEditor.vue', import.meta.url)
const { descriptor } = parse(readFileSync(filename, 'utf8'))
const script = compileScript(descriptor, { id: 'monaco-regression' }).content
const compiled = ts.transpileModule(script, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
}).outputText

for (const prefix of ['', '\uFEFF']) {
  test(`editing ${prefix ? 'BOM-prefixed' : 'BOM-free'} content preserves bytes without resetting the model`, () => {
    let value = prefix + 'first\r\nsecond'
    let onChange
    let mounted
    let unmounted
    const watches = []
    const emitted = []
    let resets = 0
    const props = { modelValue: value, height: 500, language: 'text' }
    const model = {
      getValue(eol, preserveBOM = false) {
        assert.equal(eol, 0) // monaco.editor.EndOfLinePreference.TextDefined
        return preserveBOM ? value : value.replace(/^\uFEFF/, '')
      },
      dispose() {},
    }
    const editor = {
      getValue() { return model.getValue() },
      getModel() { return model },
      setValue(next) { resets++; value = next; onChange() },
      onDidChangeModelContent(callback) { onChange = callback },
      dispose() {},
    }
    const exports = {}
    const require = name => {
      if (name === 'vue') return {
        defineComponent: definition => definition,
        ref: () => ({ value: {} }), computed: get => ({ get value() { return get() } }),
        onMounted: callback => { mounted = callback }, onUnmounted: callback => { unmounted = callback },
        watch: (get, callback) => watches.push({ get, callback }),
      }
      if (name === 'monaco-editor') return {
        editor: { create: () => editor, EndOfLinePreference: { TextDefined: 0 } },
      }
      if (name === '@/stores/app') return { useAppStore: () => ({ isDark: false }) }
      throw new Error(`Unexpected dependency: ${name}`)
    }
    vm.runInNewContext(compiled, { exports, require })
    exports.default.setup(props, { expose() {}, emit: (_event, text) => emitted.push(text) })
    mounted()
    value += '\r\nthird'
    onChange()
    assert.equal(emitted.at(-1), value)
    props.modelValue = emitted.at(-1)
    watches[0].callback(props.modelValue)
    assert.equal(resets, 0)
    props.modelValue = '\uFEFFreplacement\r\ncontent'
    watches[0].callback(props.modelValue)
    assert.equal(resets, 1)
    assert.equal(emitted.at(-1), props.modelValue)
    unmounted()
  })
}
