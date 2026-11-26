import test from 'node:test'
import assert from 'node:assert/strict'
import {
  renderCodeBlock,
  renderMath,
  tokenizeBlockMath,
  tokenizeDisplayMath,
  tokenizeInlineMath,
} from './markdownMath.ts'

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
