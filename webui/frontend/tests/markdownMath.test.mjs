import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import { test } from 'node:test'
import { runInNewContext } from 'node:vm'
import { Marked, Renderer, marked } from 'marked'
import katex from 'katex'
import ts from 'typescript'

const requireDependency = createRequire(import.meta.url)

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
      if (id === 'marked') return { Marked, Renderer }
      if (id === 'katex/contrib/mhchem') return requireDependency(id)
      if (id === 'highlight.js/lib/core' || id.startsWith('highlight.js/lib/languages/')) {
        return { default: requireDependency(id) }
      }
      if (id === 'katex') return { default: requireDependency(id) }
      if (id === 'dompurify') return { default: { sanitize(html) {
        sanitized.push(html)
        return { innerHTML: html, querySelectorAll: () => [] }
      } } }
      throw new Error(`Unexpected dependency: ${id}`)
    },
  })
  return { render: exports.renderMessageMarkdown, sanitized, math: exports }
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
    const html = render(input)
    const expected = marked.parse(input, { async: false })
    assert.doesNotMatch(html, /class="katex"/)
    const codeBodies = value => Array.from(value.matchAll(/<code\b[^>]*>([\s\S]*?)<\/code>/g), match => match[1])
    // Marked adds a terminal newline to code blocks; the chat renderer omits it.
    assert.deepEqual(codeBodies(html), codeBodies(expected.replace(/\n<\/code><\/pre>/g, '</code></pre>')))
    if (!html.includes('md-code-block')) assert.equal(html, expected)
  })
}

test('math renders outside code while Markdown and code formatting remain intact', () => {
  const { render, sanitized } = setup()
  const html = render('**Math** $x^2$ and ``$y$``\n\n~~~js\nconst x = "$z$"\n~~~\n\n$$\n\\frac{1}{2}\n$$')
  assert.match(html, /<strong>Math<\/strong>/)
  assert.match(html, /<code>\$y\$<\/code>/)
  assert.match(html, /<code class="hljs">/)
  assert.match(html, /hljs-keyword">const<\//)
  assert.match(html, /hljs-string">&quot;\$z\$&quot;<\//)
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


test('unmatched block math stays responsive at the WebChat message limit', () => {
  const { render } = setup()
  for (const input of [
    '$$' + ' '.repeat(15997) + 'x',
    '$$\n' + '\t '.repeat(7998) + 'x',
    '$$\nx' + ' '.repeat(15993) + '$$z',
  ]) {
    const html = runInNewContext('render(input)', { render, input }, { timeout: 1500 })
    if (input.endsWith('$$z')) {
      assert.match(html, /class="md-math-inline-block"/)
      assert.match(html, /<\/span>z<\/p>/)
    } else {
      assert.equal(html, marked.parse(input, { async: false }))
    }
  }
})

for (const tex of [
  String.raw`\text{cost: \$5}`,
  String.raw`\text{cost: \$5 and \$10}`,
  String.raw`\$`,
  String.raw`x\\`,
  String.raw`\text{path}\\\$5`,
]) {
  test(`inline math preserves escaped delimiters in ${tex}`, () => {
    const html = setup().render(`$${tex}$`)
    const expected = katex.renderToString(tex, {
      displayMode: false, throwOnError: false, strict: 'ignore', trust: false,
    })
    assert.equal(html, `<p>${expected}</p>\n`)
    assert.doesNotMatch(html, /class="katex-error"/)
  })
}

for (const [name, input, tex] of [
  ['same-line block', '$$x$$', 'x'],
  ['indented block', '   $$\nx\n$$', 'x'],
  ['padded block', '$$ \t\nx\n \t$$ \t\n', 'x'],
  ['multiline TeX', '$$\nx +\ny\n$$', 'x +\ny'],
]) {
  test(`block scanning preserves ${name}`, () => {
    const expected = katex.renderToString(tex, {
      displayMode: true, throwOnError: false, strict: 'ignore', trust: false,
    })
    assert.equal(setup().render(input), `<div class="md-math-block">${expected}</div>\n`)
  })
}

test('unclosed escaped inline math and escaped opening markers remain text', () => {
  const { render } = setup()
  for (const input of [String.raw`$x\$`, String.raw`\$x$`, '$ x$', '$x $', '$x\ny$']) {
    assert.equal(render(input), marked.parse(input, { async: false }))
  }
})

test('unclosed display math preserves following Markdown formatting', () => {
  const { render } = setup()
  for (const input of [
    'before $$pending **bold** and `code`',
    '$$pending **bold** and `code`',
    'before $$5\\$ **bold** and `code`',
  ]) {
    const html = render(input)
    assert.equal(html, marked.parse(input, { async: false }))
    assert.match(html, /<strong>bold<\/strong>/)
    assert.match(html, /<code>code<\/code>/)
  }
})

test('unclosed display math preserves a subsequent inline formula', () => {
  const html = setup().render('before $$pending and $x$')
  assert.match(html, /before \$\$pending and /)
  assert.equal((html.match(/class="katex"/g) || []).length, 1)
  assert.doesNotMatch(html, /katex-display/)
})

test('display math still renders with ordinary and escaped dollar content', () => {
  const { render } = setup()
  for (const [input, tex] of [
    ['Price: $$5$$ total', '5'],
    [String.raw`Price: $$5\$$$ total`, String.raw`5\$`],
  ]) {
    const expected = katex.renderToString(tex, {
      displayMode: true, throwOnError: true, strict: 'ignore', trust: false,
    })
    assert.equal(render(input), `<p>Price: <span class="md-math-inline-block">${expected}</span> total</p>\n`)
  }
})

test('rejected dollar runs remain literal without swallowing valid later math', () => {
  const { render } = setup()
  assert.equal(render('Text $$$x$$$ end'), '<p>Text $$$x$$$ end</p>\n')
  const html = render('Text $$$x$$$ and $$y$$ end')
  assert.match(html, /Text \$\$\$x\$\$\$ and /)
  assert.equal((html.match(/class="katex"/g) || []).length, 1)
})

const {
  renderCodeBlock,
  renderMath,
  tokenizeBlockMath,
  tokenizeDisplayMath,
  tokenizeInlineMath,
} = setup().math

test('mid-line $$...$$ is captured as display math', () => {
  const token = tokenizeDisplayMath('$$x$$')
  assert.ok(token)
  assert.equal(token.tex, 'x')
  assert.equal(token.raw, '$$x$$')
})

test('escaped dollar inside display math does not close it', () => {
  // A lone `\$` at the end must not be treated as a closing delimiter, and the
  // opening run stays literal instead of letting Marked retry from the next `$`.
  const literal = tokenizeDisplayMath('$$5\\$$')
  assert.ok(literal)
  assert.equal(literal.tex, '')
  assert.equal(literal.raw, '$$')

  const token = tokenizeDisplayMath('$$5\\$ $$')
  assert.ok(token)
  assert.equal(token.tex, '5\\$ ')
  assert.equal(token.raw, '$$5\\$ $$')
})

test('unclosed display delimiters stay literal', () => {
  assert.equal(tokenizeDisplayMath('$$$$').raw, '$$$$')
  assert.equal(tokenizeDisplayMath('$$x').raw, '$$')
  assert.equal(tokenizeDisplayMath('$$$').raw, '$$$')
})

test('triple dollars at line start stay literal in block tokenizer', () => {
  const token = tokenizeBlockMath('$$$x$$$')
  assert.ok(token)
  assert.equal(token.tex, '')
  assert.equal(token.raw, '$$$x$$$')
  assert.equal(tokenizeBlockMath('$$x$$').tex, 'x')
})

test('triple dollars are consumed as literal text', () => {
  const token = tokenizeDisplayMath('$$$x$$$')
  assert.ok(token)
  assert.equal(token.raw, '$$$')
  assert.equal(token.tex, '')
})

test('block math ignores escaped dollars', () => {
  assert.equal(tokenizeBlockMath('$$\n5\\$$\n'), undefined)
  const token = tokenizeBlockMath('$$\n5\\$\n$$\n')
  assert.ok(token)
  assert.equal(token.tex, '5\\$')
})

test('inline $...$ keeps working', () => {
  const token = tokenizeInlineMath('$x$')
  assert.ok(token)
  assert.equal(token.tex, 'x')
})

test('code block keeps the language label and highlights it', () => {
  const html = renderCodeBlock('const a = 1\n', 'ts')
  assert.match(html, /md-code-block/)
  assert.match(html, /md-code-lang">ts</)
  assert.match(html, /hljs-keyword">const</)
  assert.doesNotMatch(html, /\n<\/code>/)
})

test('code block without language falls back to text', () => {
  const html = renderCodeBlock('plain', null)
  assert.match(html, /md-code-lang">text</)
})

test('code block escapes html', () => {
  const html = renderCodeBlock('<script>alert(1)</script>', 'html')
  assert.doesNotMatch(html, /<script>/)
  assert.match(html, /&lt;/)
})

test('unknown language falls back to plain text', () => {
  const html = renderCodeBlock('a < b', 'brainfuck')
  assert.match(html, /md-code-lang">brainfuck</)
  assert.match(html, /a &lt; b/)
})

test('inline aligned environments fall back to display mode', () => {
  const html = renderMath('\\begin{aligned}a&=1\\\\b&=2\\end{aligned}', false)
  assert.ok(html)
  assert.match(html, /katex/)
})

test('chemistry formulas render through mhchem', () => {
  const html = renderMath('\\ce{H2O}', true)
  assert.ok(html)
  assert.match(html, /katex/)
})
