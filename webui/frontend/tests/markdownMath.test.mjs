import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { test } from 'node:test'
import { runInNewContext } from 'node:vm'
import { Marked, marked } from 'marked'
import katex from 'katex'
import ts from 'typescript'

const source = readFileSync(new URL('../src/utils/markdownMath.ts', import.meta.url), 'utf8')
const compiled = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
}).outputText

function setup() {
  const exports = {}
  const sanitized = []
  runInNewContext(compiled, {
    exports, console,
    require(id) {
      if (id === 'marked') return { Marked }
      if (id === 'katex') return { default: katex }
      if (id === 'dompurify') return { default: { sanitize(html) {
        sanitized.push(html)
        return { innerHTML: html, querySelectorAll: () => [] }
      } } }
      throw new Error(`Unexpected dependency: ${id}`)
    },
  })
  return { render: exports.renderMessageMarkdown, sanitized }
}

for (const [name, input] of [
  ['ordinary backtick fence', '```text\n$x$\n```'],
  ['tilde fence', '~~~text\n$x$\n~~~'],
  ['longer closing fence', '````text\n```\n$x$\n`````'],
  ['shorter tilde run inside code', '~~~~text\n~~~\n$x$\n~~~~'],
  ['different fence character inside code', '```text\n~~~\n$x$\n```'],
  ['backtick substring inside code', '```text\nbefore ``` after\n$x$\n```'],
  ['closing fence with trailing text', '```text\n```not a closing fence\n$x$\n```'],
  ['unclosed fence', '```text\n$x$'],
  ['indented code', '    $x$\n    $$y$$'],
  ['nested blockquote fence', '> ~~~text\n> $x$\n> ~~~'],
  ['single-backtick span', 'before `$x$` after'],
  ['double-backtick span', 'before ``$x$`` after'],
  ['unequal runs inside a code span', 'before ``a ` $x$ ``` b`` after'],
  ['multiline code span', 'before ``a\n$x$`` after'],
]) {
  test(`math markers remain literal in ${name}`, () => {
    const { render } = setup()
    assert.equal(render(input), marked.parse(input, { async: false }))
  })
}

test('math renders outside code while Markdown and code formatting remain intact', () => {
  const { render, sanitized } = setup()
  const html = render('**Math** $x^2$ and ``$y$``\n\n~~~js\nconst x = "$z$"\n~~~\n\n$$\n\\frac{1}{2}\n$$')
  assert.match(html, /<strong>Math<\/strong>/)
  assert.match(html, /<code>\$y\$<\/code>/)
  assert.match(html, /<code class="language-js">const x = &quot;\$z\$&quot;/)
  assert.equal((html.match(/class="katex"/g) || []).length, 2)
  assert.match(html, /class="md-math-block"/)
  assert.equal(sanitized.length, 1)
  assert.equal(sanitized[0], html)
})

test('display math after a paragraph and inline math in a link label render', () => {
  const { render } = setup()
  const html = render('Paragraph\n$$x$$\n\n[$y$](https://example.org)')
  assert.match(html, /<p>Paragraph<\/p>\n<div class="md-math-block">/)
  assert.equal((html.match(/class="katex"/g) || []).length, 2)
})

test('escaped dollar signs, absent text and incomplete math stay safe to render', () => {
  const { render } = setup()
  for (const input of ['\\$x\\$', '$x', '$$\nx', undefined, null]) {
    assert.equal(render(input), marked.parse(input ?? '', { async: false }))
  }
})

test('chat math extensions do not modify the shared Markdown parser', () => {
  setup().render('$x$')
  assert.equal(marked.parse('$x$', { async: false }), '<p>$x$</p>\n')
})
