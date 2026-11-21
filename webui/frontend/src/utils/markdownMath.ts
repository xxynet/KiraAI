import DOMPurify from 'dompurify'
import katex from 'katex'
import { marked } from 'marked'

const PLACEHOLDER_PREFIX = 'KIRA_MATH_PLACEHOLDER_'
const CODE_PLACEHOLDER_PREFIX = 'KIRA_CODE_PLACEHOLDER_'
const FENCED_CODE = /```[\s\S]*?```/g
const INLINE_CODE = /`(?:\\.|[^`])*`/g
const BLOCK_MATH = /(^|\n)\s*\$\$\s*\n?([\s\S]*?)\n?\s*\$\$\s*(?=\n|$)/g
const INLINE_MATH = /(^|[^$\\])\$(?!\s)([^\n$]*?\S)\$(?!\$)/g

type Replacement = { token: string; html: string }

function escapeHtml(value: string): string {
  return value.replace(/[&<>"']/g, (character) => {
    const entities: Record<string, string> = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }
    return entities[character]!
  })
}

function renderMath(tex: string, displayMode: boolean): string | null {
  try {
    return katex.renderToString(tex, { displayMode, throwOnError: false, strict: 'ignore', trust: false })
  } catch {
    return null
  }
}

function protectCode(text: string): { text: string; replacements: Replacement[] } {
  const replacements: Replacement[] = []
  let index = 0
  const protectedText = text.replace(new RegExp(`${FENCED_CODE.source}|${INLINE_CODE.source}`, 'g'), (code) => {
    const token = `${CODE_PLACEHOLDER_PREFIX}${index++}__`
    const isBlock = code.startsWith('```')
    const body = isBlock ? code.replace(/^```[^\n]*\n?/, '').replace(/\n?```$/, '') : code.slice(1, -1)
    replacements.push({
      token,
      html: isBlock ? `<pre><code>${escapeHtml(body)}</code></pre>` : `<code>${escapeHtml(body)}</code>`,
    })
    return token
  })
  return { text: protectedText, replacements }
}

function protectMath(text: string): { text: string; replacements: Replacement[] } {
  const replacements: Replacement[] = []
  let index = 0
  let protectedText = text.replace(BLOCK_MATH, (match, prefix: string, tex: string) => {
    const token = `${PLACEHOLDER_PREFIX}${index++}__`
    const rendered = renderMath(tex, true)
    replacements.push({
      token,
      html: rendered ? `<div class="md-math-block">${rendered}</div>` : `<span>${escapeHtml(match)}</span>`,
    })
    return `${prefix}${token}${prefix ? '\n' : ''}`
  })
  protectedText = protectedText.replace(INLINE_MATH, (match, prefix: string, tex: string) => {
    const token = `${PLACEHOLDER_PREFIX}${index++}__`
    const rendered = renderMath(tex, false)
    replacements.push({ token, html: rendered || escapeHtml(match) })
    return `${prefix}${token}`
  })
  return { text: protectedText, replacements }
}

function restore(html: string, replacements: Replacement[]): string {
  return replacements.reduce((result, replacement) => result.split(replacement.token).join(replacement.html), html)
}

export function renderMessageMarkdown(text?: string | null): string {
  const normalizedText = text ?? ''
  const code = protectCode(normalizedText)
  const math = protectMath(code.text)
  let html: string
  try {
    html = marked.parse(math.text, { async: false }) as string
  } catch {
    html = escapeHtml(math.text).replace(/\r?\n/g, '<br>')
  }
  html = restore(restore(html, math.replacements), code.replacements)
  return DOMPurify.sanitize(html, { ADD_ATTR: ['class'] })
}
