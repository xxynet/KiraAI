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

const MARKDOWN_LINK_PATTERN = /\[([^\]]*)\]\(([^)\s]*)\)/g

/** Only allow http(s) targets so a crafted hint cannot inject javascript: links. */
function isSafeUrl(url: string): boolean {
  return /^https?:\/\//i.test(url)
}

export function linkifySegments(text: string): LinkifySegment[] {
  if (!text) return []

  const segments: LinkifySegment[] = []
  let lastIndex = 0
  for (const match of text.matchAll(MARKDOWN_LINK_PATTERN)) {
    const url = match[2]
    if (!isSafeUrl(url)) continue
    const start = match.index ?? 0
    if (start > lastIndex) {
      segments.push({ text: text.slice(lastIndex, start) })
    }
    segments.push({ text: match[1], url })
    lastIndex = start + match[0].length
  }
  if (lastIndex < text.length) {
    segments.push({ text: text.slice(lastIndex) })
  }
  return segments
}
