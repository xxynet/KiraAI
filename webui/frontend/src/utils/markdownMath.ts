import DOMPurify from 'dompurify'
import katex from 'katex'
import { Marked } from 'marked'

function tokenizeBlockMath(source: string) {
  const opening = /^ {0,3}\$\$[ \t]*\n?/.exec(source)
  if (!opening) return
  const contentStart = opening[0].length
  for (let index = contentStart; index < source.length - 1; index++) {
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

function tokenizeInlineMath(source: string) {
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
function tokenizeDisplayMath(source: string) {
  if (source[0] !== '$' || source[1] !== '$' || source[2] === '$') return
  const close = source.indexOf('$$', 2)
  if (close < 0) return
  const tex = source.slice(2, close)
  if (!tex.trim()) return
  if (tex.includes('\n\n')) return
  return {
    type: 'displayMath',
    raw: source.slice(0, close + 2),
    tex,
  }
}

function escapeHtml(value: string): string {
  return value.replace(/[&<>"']/g, (character) => {
    const entities: Record<string, string> = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }
    return entities[character]!
  })
}

function renderMath(tex: string, displayMode: boolean): string | null {
  try {
    return katex.renderToString(tex, { displayMode, throwOnError: false, strict: 'ignore', trust: false })
  } catch (cause) {
    console.error('Failed to render chat math:', cause)
    return null
  }
}

// Let Marked own code boundaries so math is never tokenized inside code.
const messageMarkdown = new Marked({
  extensions: [
    {
      name: 'blockMath',
      level: 'block',
      start: (source) => source.match(/(?:^|\n) {0,3}\$\$/)?.index,
      tokenizer: tokenizeBlockMath,
      renderer(token) {
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
