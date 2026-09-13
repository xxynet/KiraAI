/**
 * Parse markdown-style links `[text](url)` in a plain-text string into
 * text/link segments so callers can render them as clickable links
 * without v-html (no injection risk). Other markdown syntax is left as-is.
 */

export interface LinkifySegment {
  text: string
  /** Target URL when the segment is a link, absent for plain text. */
  url?: string
}

const LINK_CANDIDATE_PATTERN = /\[([^\]]*)\]\(/g

/** Only allow http(s) targets so a crafted hint cannot inject javascript: links. */
function isSafeUrl(url: string): boolean {
  return /^https?:\/\//i.test(url)
}

/**
 * Scan a markdown link destination starting at `start`, tracking paren depth
 * so URLs may contain balanced parentheses (e.g. Wikipedia article links).
 * Whitespace or an unbalanced destination invalidates the link per CommonMark.
 *
 * @returns The destination and the index just past its closing `)`, or null when invalid.
 */
function extractDestination(text: string, start: number): { url: string; end: number } | null {
  let depth = 1
  for (let i = start; i < text.length; i++) {
    const char = text[i]
    if (char === '(') {
      depth++
    } else if (char === ')') {
      depth--
      if (depth === 0) {
        return { url: text.slice(start, i), end: i + 1 }
      }
    } else if (/\s/.test(char)) {
      return null
    }
  }
  return null
}

/**
 * Split text into segments at markdown link boundaries.
 *
 * @param text Plain text that may contain `[label](url)` links.
 * @returns Ordered segments; link segments carry an http(s) `url`, invalid
 * or unsafe candidates stay in the surrounding plain text.
 */
export function linkifySegments(text: string): LinkifySegment[] {
  if (!text) return []

  const segments: LinkifySegment[] = []
  let lastIndex = 0
  for (const match of text.matchAll(LINK_CANDIDATE_PATTERN)) {
    const start = match.index ?? 0
    const destination = extractDestination(text, start + match[0].length)
    if (!destination || !isSafeUrl(destination.url)) continue
    if (start > lastIndex) {
      segments.push({ text: text.slice(lastIndex, start) })
    }
    segments.push({ text: match[1], url: destination.url })
    lastIndex = destination.end
  }
  if (lastIndex < text.length) {
    segments.push({ text: text.slice(lastIndex) })
  }
  return segments
}
