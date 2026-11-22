import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import ts from 'typescript'

// Transpile the dependency-free module so tests also run on Node 18.
const source = readFileSync(new URL('../src/components/common/skillFiles.ts', import.meta.url), 'utf8')
const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2020 } }).outputText
const { resolveSkillFileReference: resolve, stripSkillFrontmatter: strip, skillImageType } =
  await import(`data:text/javascript;base64,${Buffer.from(compiled).toString('base64')}`)

test('resources resolve against the active Markdown directory', () => {
  assert.deepEqual(resolve('../assets/example.png', 'references/guide.md'), {
    kind: 'file', path: 'assets/example.png', fragment: '',
  })
  assert.deepEqual(resolve('./notes.md#配置', 'references/guide.md'), {
    kind: 'file', path: 'references/notes.md', fragment: '配置',
  })
  assert.deepEqual(resolve('/SKILL.md?download=1#intro', 'references/guide.md'), {
    kind: 'file', path: 'SKILL.md', fragment: 'intro',
  })
  assert.deepEqual(resolve('../assets/%E5%9B%BE%20%231.png', 'references/guide.md'), {
    kind: 'file', path: 'assets/图 #1.png', fragment: '',
  })
  assert.deepEqual(resolve('#heading', 'references/guide.md'), {
    kind: 'file', path: 'references/guide.md', fragment: 'heading',
  })
})

test('paths escaping the skill directory and malformed paths are rejected', () => {
  for (const path of ['../../secret', '%2e%2e/%2e%2e/secret', 'x%00.png', 'bad%XX', 'x\\y', 'x%3Ay']) {
    assert.equal(resolve(path, 'references/guide.md').kind, 'invalid', path)
  }
  assert.equal(resolve('../secret', 'SKILL.md').kind, 'invalid')
})

test('absolute external references are left to normal Markdown rendering', () => {
  for (const url of ['https://example.com/a.png', '//example.com/a', 'mailto:a@example.com', 'data:image/png;base64,AA==']) {
    assert.equal(resolve(url, 'SKILL.md').kind, 'external')
  }
})

test('preview strips only complete frontmatter at the start, including BOM and CRLF', () => {
  for (const [prefix, newline] of [['', '\n'], ['\uFEFF', '\r\n']]) {
    const text = prefix + '---\nname: demo\ndescription: "Use --- separators"\n---\n# Body\n---\n'.replaceAll('\n', newline)
    assert.equal(strip(text), '# Body\n---\n'.replaceAll('\n', newline))
  }
  for (const text of ['# Body\n---\nfoo\n---\n', '---\nname: demo\n--- trailing text\n']) {
    assert.equal(strip(text), text)
  }
})

test('only supported raster formats receive image Blob MIME types', () => {
  assert.equal(skillImageType('assets/Example.PNG'), 'image/png')
  assert.equal(skillImageType('assets/example.webp'), 'image/webp')
  assert.equal(skillImageType('assets/example.svg'), undefined)
  assert.equal(skillImageType('script.html'), undefined)
})
