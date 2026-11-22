import DOMPurify from 'dompurify'
import katex from 'katex'
import { Marked } from 'marked'

const BLOCK_MATH = /^ {0,3}\$\$[ \t]*\n?([\s\S]*?)\n?[ \t]*\$\$[ \t]*(?:\n|$)/
const INLINE_MATH = /^\$(?![\s$])([^\n$]*?[^\s$])\$(?!\$)/

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
      tokenizer(source) {
        const match = BLOCK_MATH.exec(source)
        if (match) return { type: 'blockMath', raw: match[0], tex: match[1] }
      },
      renderer(token) {
        const rendered = renderMath(token.tex, true)
        return rendered ? `<div class="md-math-block">${rendered}</div>\n` : escapeHtml(token.raw)
      },
    },
    {
      name: 'inlineMath',
      level: 'inline',
      start: (source) => source.indexOf('$'),
      tokenizer(source) {
        const match = INLINE_MATH.exec(source)
        if (match) return { type: 'inlineMath', raw: match[0], tex: match[1] }
      },
      renderer(token) {
        return renderMath(token.tex, false) || escapeHtml(token.raw)
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
  return DOMPurify.sanitize(html, { ADD_ATTR: ['class'] })
}
