import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { test } from 'node:test'
import { runInNewContext } from 'node:vm'
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
 */
function placeholders(message) {
  const names = []
  const pattern = /\{([a-zA-Z0-9_]+)\}/g
  let match
  while ((match = pattern.exec(message)) !== null) names.push(match[1])
  return names.sort().join(', ')
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
