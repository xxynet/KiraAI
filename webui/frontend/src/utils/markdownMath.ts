import DOMPurify from 'dompurify'
import katex from 'katex'
import 'katex/contrib/mhchem'
import hljs from 'highlight.js/lib/core'
import bash from 'highlight.js/lib/languages/bash'
import c from 'highlight.js/lib/languages/c'
import cpp from 'highlight.js/lib/languages/cpp'
import csharp from 'highlight.js/lib/languages/csharp'
import css from 'highlight.js/lib/languages/css'
import diff from 'highlight.js/lib/languages/diff'
import go from 'highlight.js/lib/languages/go'
import java from 'highlight.js/lib/languages/java'
import javascript from 'highlight.js/lib/languages/javascript'
import json from 'highlight.js/lib/languages/json'
import markdown from 'highlight.js/lib/languages/markdown'
import php from 'highlight.js/lib/languages/php'
import python from 'highlight.js/lib/languages/python'
import rust from 'highlight.js/lib/languages/rust'
import sql from 'highlight.js/lib/languages/sql'
import typescript from 'highlight.js/lib/languages/typescript'
import xml from 'highlight.js/lib/languages/xml'
import yaml from 'highlight.js/lib/languages/yaml'
import { Marked, Renderer } from 'marked'

// Only the languages chat actually uses are bundled; everything else falls
// back to plain text instead of paying for the full highlight.js build.
const HIGHLIGHT_LANGUAGES = {
  bash,
  c,
  cpp,
  csharp,
  css,
  diff,
  go,
  java,
  javascript,
  json,
  markdown,
  php,
  python,
  rust,
  sql,
  typescript,
  xml,
  yaml,
}

for (const [name, definition] of Object.entries(HIGHLIGHT_LANGUAGES)) {
  hljs.registerLanguage(name, definition)
}

export function tokenizeBlockMath(source: string) {
  const opening = /^ {0,3}\$\$[ \t]*\n?/.exec(source)
  if (!opening) return
  // Three or more dollars at the start of a line are ambiguous: keep the whole
  // line literal so the inline tokenizer cannot pair up the leftovers.
  if (/^ {0,3}\${3,}/.test(source)) {
    const lineEnd = source.indexOf('\n')
    return {
      type: 'blockMath',
      raw: source.slice(0, lineEnd < 0 ? source.length : lineEnd),
      tex: '',
    }
  }
  const contentStart = opening[0].length
  for (let index = contentStart; index < source.length - 1; index++) {
    if (source[index] === '\\') {
      index++
      continue
    }
    if (source[index] !== '$' || source[index + 1] !== '$') continue
    let end = index + 2
    while (source[end] === ' ' || source[end] === '\t') end++
    if (end < source.length && source[end] !== '\n') continue
    if (source[end] === '\n') end++
    let contentEnd = index
    while (source[contentEnd - 1] === ' ' || source[contentEnd - 1] === '\t') contentEnd--
    if (source[contentEnd - 1] === '\n') contentEnd--
    return {
      type: 'blockMath',
      raw: source.slice(0, end),
      tex: source.slice(contentStart, contentEnd),
    }
  }
}

export function tokenizeInlineMath(source: string) {
  if (source[0] !== '$' || !source[1] || /[\s$]/.test(source[1])) return
  for (let index = 1; index < source.length; index++) {
    if (source[index] === '\n') return
    if (source[index] === '\\') {
      if (source[index + 1] === '\n') return
      index++
      continue
    }
    if (source[index] !== '$') continue
    if (/\s/.test(source[index - 1]!) || source[index + 1] === '$') return
    return {
      type: 'inlineMath',
      raw: source.slice(0, index + 1),
      tex: source.slice(1, index),
    }
  }
}

// Inline $$...$$ that appears mid-line never reaches the block-level tokenizer,
// so catch it with an inline-level rule and render it in display mode.
export function tokenizeDisplayMath(source: string) {
  if (source[0] !== '$' || source[1] !== '$') return
  // Three or more dollars in a row is ambiguous. Consume the whole run as
  // literal text, otherwise Marked retries at the next character, matches from
  // the second dollar and swallows half of a sequence like `$$$x$$$`.
  if (source[2] === '$') {
    let run = 2
    while (source[run] === '$') run++
    return {
      type: 'displayMath',
      raw: source.slice(0, run),
      tex: '',
    }
  }
  for (let index = 2; index < source.length; index++) {
    if (source[index] === '\\') {
      index++
      continue
    }
    if (source[index] !== '$' || source[index + 1] !== '$') continue
    const tex = source.slice(2, index)
    if (!tex.trim()) return literalDollarRun(source)
    if (tex.includes('\n\n')) return literalDollarRun(source)
    return {
      type: 'displayMath',
      raw: source.slice(0, index + 2),
      tex,
    }
  }
  // An opening `$$` without a valid partner must still be consumed as one
  // literal run: returning undefined lets Marked retry one character later,
  // pair the second `$` with a later one and render half of the text.
  return literalDollarRun(source)
}

function literalDollarRun(source: string) {
  const lineEnd = source.indexOf('\n')
  return {
    type: 'displayMath',
    raw: source.slice(0, lineEnd < 0 ? source.length : lineEnd),
    tex: '',
  }
}

function escapeHtml(value: string): string {
  return value.replace(/[&<>"']/g, (character) => {
    const entities: Record<string, string> = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }
    return entities[character]!
  })
}

// Fenced code block: a labelled header plus a scrollable body. Kept as a pure
// function so it can be unit tested without a DOM.
export function highlightCode(code: string, language: string): string {
  if (language === 'text' || !hljs.getLanguage(language)) return escapeHtml(code)
  try {
    return hljs.highlight(code, { language, ignoreIllegals: true }).value
  } catch {
    return escapeHtml(code)
  }
}

export function renderCodeBlock(code: string, lang?: string | null): string {
  const language = ((lang ?? '').trim().split(/\s+/)[0] || 'text').toLowerCase()
  const source = code.replace(/\n$/, '')
  return [
    '<div class="md-code-block">',
    `<div class="md-code-head"><span class="md-code-lang">${escapeHtml(language)}</span></div>`,
    `<pre class="md-code-body"><code class="hljs">${highlightCode(source, language)}</code></pre>`,
    '</div>\n',
  ].join('')
}

// KaTeX rejects `&`-based environments (aligned / cases / matrix), `\tag` and
// `\hline` in inline mode: that is the usual reason a formula written inside
// `$...$` silently fails. Retry those in display mode before giving up.
const DISPLAY_ONLY = /\\(?:begin\{(?:align|aligned|alignedat|split|gather|gathered|cases|array|matrix|pmatrix|bmatrix|Bmatrix|vmatrix|Vmatrix|smallmatrix)\}|tag\b|hline\b)/

function renderWith(tex: string, displayMode: boolean): string {
  return katex.renderToString(tex, { displayMode, throwOnError: true, strict: 'ignore', trust: false })
}

export function renderMath(tex: string, displayMode: boolean): string | null {
  const preferDisplay = displayMode || DISPLAY_ONLY.test(tex)
  try {
    return renderWith(tex, preferDisplay)
  } catch (firstCause) {
    if (!preferDisplay) {
      try {
        return renderWith(tex, true)
      } catch {
        // fall through to the report below
      }
    }
    console.warn('Failed to render chat math:', {
      tex,
      displayMode,
      error: String((firstCause as Error)?.message ?? firstCause),
    })
    return null
  }
}

const messageRenderer = new Renderer()
messageRenderer.code = ({ text, lang }) => renderCodeBlock(text, lang)

// Let Marked own code boundaries so math is never tokenized inside code.
const messageMarkdown = new Marked({
  renderer: messageRenderer,
  extensions: [
    {
      name: 'blockMath',
      level: 'block',
      start: (source) => source.match(/(?:^|\n) {0,3}\$\$/)?.index,
      tokenizer: tokenizeBlockMath,
      renderer(token) {
        if (!token.tex) return escapeHtml(token.raw)
        const rendered = renderMath(token.tex, true)
        return rendered ? `<div class="md-math-block">${rendered}</div>\n` : escapeHtml(token.raw)
      },
    },
    {
      name: 'inlineMath',
      level: 'inline',
      start: (source) => source.indexOf('$'),
      tokenizer: tokenizeInlineMath,
      renderer(token) {
        return renderMath(token.tex, false) || escapeHtml(token.raw)
      },
    },
    {
      name: 'displayMath',
      level: 'inline',
      start: (source) => source.indexOf('$$'),
      tokenizer: tokenizeDisplayMath,
      renderer(token) {
        if (!token.tex) return escapeHtml(token.raw)
        const rendered = renderMath(token.tex, true)
        return rendered ? `<span class="md-math-inline-block">${rendered}</span>` : escapeHtml(token.raw)
      },
    },
  ],
})

export function renderMessageMarkdown(text?: string | null): string {
  const normalizedText = text ?? ''
  let html: string
  try {
    html = messageMarkdown.parse(normalizedText, { async: false })
  } catch (cause) {
    console.error('Failed to render chat Markdown:', cause)
    html = escapeHtml(normalizedText).replace(/\r?\n/g, '<br>')
  }
  const sanitized = DOMPurify.sanitize(html, { ADD_ATTR: ['class'], RETURN_DOM: true }) as HTMLElement
  sanitized.querySelectorAll('a[href]').forEach(link => {
    link.setAttribute('target', '_blank')
    link.setAttribute('rel', 'noopener noreferrer')
  })
  return sanitized.innerHTML
}
