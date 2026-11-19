import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { test } from 'node:test'
import { runInNewContext } from 'node:vm'
import ts from 'typescript'

const source = readFileSync(new URL('../src/utils/pluginReadme.ts', import.meta.url), 'utf8')
const { outputText } = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
})

function setup(fetch) {
  const exports = {}
  runInNewContext(outputText, { exports, URL, AbortSignal, fetch })
  return exports
}

const repo = 'https://github.com/example/plugin.git'
const sha = 'abcde12345'.repeat(4)
const raw = 'https://raw.githubusercontent.com/example/plugin'
const missing = () => new Response(null, { status: 404 })

test('the store README and its relative assets use the normalized version SHA', async () => {
  const requests = []
  const { fetchStoreReadme, getStoreReadmeRef, resolveReadmeUrl } = setup(async url => {
    requests.push(url)
    return requests.length === 1 ? missing() : new Response('# Version README')
  })
  const ref = getStoreReadmeRef(` ${sha.toUpperCase()} `)
  assert.equal(await fetchStoreReadme(repo, ref), '# Version README')
  assert.deepEqual(requests, [`${raw}/${sha}/README.md`, `${raw}/${sha}/README.MD`])
  assert.equal(resolveReadmeUrl('./images/icon.png', repo, true, ref), `${raw}/${sha}/images/icon.png`)
  assert.equal(
    resolveReadmeUrl('docs/usage.md?lang=en#setup', repo, false, ref),
    `https://github.com/example/plugin/blob/${sha}/docs/usage.md?lang=en#setup`,
  )
  assert.equal(resolveReadmeUrl('#setup', repo, false, ref), '#setup')
  assert.equal(resolveReadmeUrl('https://example.org/image.png', repo, true, ref), 'https://example.org/image.png')
})

test('missing or malformed SHAs use main for the README and its assets', async () => {
  const requests = []
  const { fetchStoreReadme, getStoreReadmeRef, resolveReadmeUrl } = setup(async url => {
    requests.push(url)
    return new Response('# Main README')
  })
  for (const invalid of [undefined, null, '', 'release/v1', sha.slice(1), 'z'.repeat(40)]) {
    assert.equal(getStoreReadmeRef(invalid), 'main')
  }
  const ref = getStoreReadmeRef(null)
  assert.equal(await fetchStoreReadme(repo, ref), '# Main README')
  assert.deepEqual(requests, [`${raw}/main/README.md`])
  assert.equal(resolveReadmeUrl('image.png', repo, true, ref), `${raw}/main/image.png`)
})

test('a missing pinned README never retries against main', async () => {
  const requests = []
  const { fetchStoreReadme } = setup(async url => {
    requests.push(url)
    return missing()
  })
  assert.equal(await fetchStoreReadme(repo, sha), null)
  assert.deepEqual(requests, ['README.md', 'README.MD', 'README'].map(name => `${raw}/${sha}/${name}`))
})

test('HTTP errors and unsupported repositories leave the README unavailable', async () => {
  const requests = []
  const { fetchStoreReadme } = setup(async url => {
    requests.push(url)
    return new Response('Service unavailable', { status: 503 })
  })
  assert.equal(await fetchStoreReadme(repo, sha), null)
  assert.equal(await fetchStoreReadme('https://example.org/plugin', sha), null)
  assert.deepEqual(requests, [`${raw}/${sha}/README.md`])
})
