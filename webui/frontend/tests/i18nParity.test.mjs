import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { test } from 'node:test'
import { runInNewContext } from 'node:vm'
import { createParser } from '@intlify/message-compiler'
import ts from 'typescript'

/**
 * Locales shipped by the WebUI. AGENTS.md requires CN and EN to be updated
 * together, so a key that only exists in one of them is a defect. Adding a
 * locale means extending this list together with `supportedLocales` in
 * src/i18n/index.ts.
 */
const LOCALES = ['en', 'zh']

function loadCatalogue(locale) {
  const source = readFileSync(new URL(`../src/i18n/${locale}.ts`, import.meta.url), 'utf8')
  const compiled = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
  }).outputText
  const module = { exports: {} }
  runInNewContext(compiled, {
    module,
    exports: module.exports,
    require(id) {
      throw new Error(`${locale}.ts must stay dependency-free, but it required "${id}"`)
    },
  })
  return module.exports.default
}

/** Flatten nested catalogues into dotted keys so the locales can be compared. */
function flatten(messages, prefix = '', flat = {}) {
  for (const [key, value] of Object.entries(messages)) {
    const path = prefix ? `${prefix}.${key}` : key
    if (value && typeof value === 'object' && !Array.isArray(value)) {
      flatten(value, path, flat)
    } else {
      flat[path] = value
    }
  }
  return flat
}

/**
 * Placeholders such as {count} must survive translation or vue-i18n renders
 * broken copy. Plural branches ("one | many") and "@:" links are allowed to
 * differ between locales, so they are intentionally not compared here.
 *
 * Use Vue I18n's parser so whitespace, literal interpolation and invalid
 * message syntax follow the same rules as the runtime.
 */
function placeholders(message) {
  // Names are collected as a set: plural branches repeat the same placeholder
  // ("{count} item | {count} items"), and only the set of names matters.
  const names = new Set()
  // NodeTypes is a const enum, so its values are not exported at runtime.
  const nodeTypes = { Plural: 1, Named: 4, List: 5, Linked: 6 }
  const { body } = createParser({ onError(error) { throw error } }).parse(message)
  const branches = body.type === nodeTypes.Plural ? body.cases : [body]
  for (const branch of branches) {
    for (const item of branch.items) {
      const node = item.type === nodeTypes.Linked ? item.key : item
      if (node.type === nodeTypes.Named) names.add(node.key)
      if (node.type === nodeTypes.List) names.add(String(node.index))
    }
  }
  return [...names].sort().join(', ')
}

const catalogues = Object.fromEntries(
  LOCALES.map(locale => [locale, flatten(loadCatalogue(locale))]),
)
const keys = Object.keys(catalogues.en).sort()

test('CN and EN catalogues expose exactly the same keys', () => {
  const missingInZh = keys.filter(key => !(key in catalogues.zh))
  const missingInEn = Object.keys(catalogues.zh).filter(key => !(key in catalogues.en)).sort()
  assert.deepEqual(
    missingInZh,
    [],
    `zh.ts is missing ${missingInZh.length} key(s) that en.ts defines:\n${missingInZh.join('\n')}`,
  )
  assert.deepEqual(
    missingInEn,
    [],
    `en.ts is missing ${missingInEn.length} key(s) that zh.ts defines:\n${missingInEn.join('\n')}`,
  )
})

test('every message is a non-empty string', () => {
  for (const locale of LOCALES) {
    // Arrays and non-string values are rejected on purpose: vue-i18n would
    // render them differently per locale, which is drift the key check misses.
    const invalid = Object.entries(catalogues[locale])
      .filter(([, value]) => typeof value !== 'string' || value.trim() === '')
      .map(([key, value]) => `${key} (${Array.isArray(value) ? 'array' : typeof value})`)
    assert.deepEqual(
      invalid,
      [],
      `${locale}.ts has ${invalid.length} entry/entries that are not non-empty strings:\n${invalid.join('\n')}`,
    )
  }
})

test('each key keeps the same placeholders in both locales', () => {
  const mismatched = []
  for (const key of keys) {
    const en = catalogues.en[key]
    const zh = catalogues.zh[key]
    if (typeof en !== 'string' || typeof zh !== 'string') continue
    const enPlaceholders = placeholders(en)
    const zhPlaceholders = placeholders(zh)
    if (enPlaceholders !== zhPlaceholders) {
      mismatched.push(`${key}: en[{${enPlaceholders}}] zh[{${zhPlaceholders}}]`)
    }
  }
  assert.deepEqual(
    mismatched,
    [],
    `${mismatched.length} key(s) use different placeholders per locale:\n${mismatched.join('\n')}`,
  )
})

test('repeated placeholders across plural branches compare as a set', () => {
  assert.equal(placeholders('{count} item | {count} items'), placeholders('{count} 项'))
  assert.notEqual(placeholders('{count} items'), placeholders('{total} items'))
  assert.notEqual(placeholders('{count} items'), placeholders('items'))
})

test('placeholder names follow Vue I18n compiler semantics', () => {
  assert.equal(placeholders('{user-id}'), 'user-id')
  assert.equal(placeholders('{a$b}'), 'a$b')
  assert.throws(() => placeholders('{user.name}'), /Unterminated closing brace/)
  assert.throws(() => placeholders('{$id}'), /Invalid token in placeholder/)
  // A hyphenated name that only exists in one locale must be reported.
  assert.notEqual(placeholders('{user-id} items'), placeholders('items'))
})

test('whitespace around interpolation names does not hide placeholder drift', () => {
  assert.equal(placeholders('{ count } selected'), placeholders('{count} selected'))
  assert.equal(placeholders('{\ncount\n} selected'), 'count')
  assert.notEqual(placeholders('{ count } selected'), placeholders('selected'))
  assert.notEqual(placeholders('{ count } selected'), placeholders('{ total } selected'))
})

test('literal interpolation is not counted as a runtime placeholder', () => {
  assert.equal(placeholders("{'{count}'}"), '')
  assert.equal(placeholders("{'{count}'} { total }"), 'total')
  assert.notEqual(placeholders("{'{count}'}"), placeholders('{count}'))
})

test('list interpolation follows parser whitespace and plural rules', () => {
  assert.equal(placeholders('{ 0 } item | {0} items'), placeholders('{0} items'))
  assert.notEqual(placeholders('{ 0 } items'), placeholders('items'))
  assert.notEqual(placeholders('{0} items'), placeholders('{1} items'))
})

test('linked messages may differ while dynamic link placeholders must match', () => {
  assert.equal(placeholders('@:common.en'), placeholders('@.lower:common.zh'))
  assert.equal(placeholders('@:{ name }'), placeholders('@:{name}'))
  assert.notEqual(placeholders('@:{name}'), placeholders('@:common.zh'))
})
