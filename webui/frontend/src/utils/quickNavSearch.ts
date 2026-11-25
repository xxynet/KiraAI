/**
 * Pure matching helpers behind the Ctrl+K quick navigation palette.
 *
 * The module deliberately has no Vue dependency so the ranking rules can be
 * unit tested from plain Node (see tests/quickNavSearch.test.mjs).
 */

export interface QuickNavTarget {
  /** Stable entry id, unique within the sidebar. */
  id: string
  /** Route the entry opens. */
  route: string
  /** Display label, already localized by the caller. */
  label: string
  /** Display label of the group the entry belongs to, empty when ungrouped. */
  group: string
}

export interface QuickNavShortcutEvent {
  key: string
  ctrlKey?: boolean
  metaKey?: boolean
  altKey?: boolean
  shiftKey?: boolean
  repeat?: boolean
}

/** Lower rank wins; `Number.POSITIVE_INFINITY` means the token did not match. */
const NO_MATCH = Number.POSITIVE_INFINITY

function splitWords(value: string): string[] {
  return value.split(/[^\p{L}\p{N}]+/u).filter(word => word.length > 0)
}

/** 0 exact, 1 prefix, 2 word prefix, 3 substring, `NO_MATCH` no match. */
function rankToken(token: string, value: string): number {
  const normalized = value.toLowerCase()
  if (!normalized) return NO_MATCH
  if (normalized === token) return 0
  if (normalized.startsWith(token)) return 1
  if (splitWords(normalized).some(word => word.startsWith(token))) return 2
  if (normalized.includes(token)) return 3
  return NO_MATCH
}

/**
 * Filter and rank sidebar entries for a query. Every whitespace-separated token
 * must match somewhere (label, group or route); a token's rank is the best field
 * it matched, and equal scores keep the sidebar order. An empty query returns
 * every entry unchanged.
 */
export function searchQuickNav<T extends QuickNavTarget>(targets: readonly T[], query: string): T[] {
  const tokens = query.toLowerCase().trim().split(/\s+/).filter(token => token.length > 0)
  if (tokens.length === 0) return [...targets]

  const matches: { target: T; score: number; order: number }[] = []
  for (let order = 0; order < targets.length; order++) {
    const target = targets[order]!
    let score = 0
    let matched = true
    for (const token of tokens) {
      const rank = Math.min(
        rankToken(token, target.label),
        rankToken(token, target.group),
        rankToken(token, target.route),
      )
      if (rank === NO_MATCH) {
        matched = false
        break
      }
      score += rank
    }
    if (matched) matches.push({ target, score, order })
  }
  matches.sort((a, b) => a.score - b.score || a.order - b.order)
  return matches.map(match => match.target)
}

/** Ctrl+K on Windows and Linux, Cmd+K on macOS. */
export function isQuickNavShortcut(event: QuickNavShortcutEvent): boolean {
  if (event.repeat) return false
  if (event.altKey || event.shiftKey) return false
  if (!event.ctrlKey && !event.metaKey) return false
  return event.key.length === 1 && event.key.toLowerCase() === 'k'
}

export function detectMacPlatform(platform: string): boolean {
  return /mac|iphone|ipad|ipod/i.test(platform)
}

/** Human readable hint for the palette trigger and the footer. */
export function quickNavShortcutLabel(isMac: boolean): string {
  return isMac ? '⌘K' : 'Ctrl K'
}
