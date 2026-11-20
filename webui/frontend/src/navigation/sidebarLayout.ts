export interface SidebarItemEntry {
  type: 'item'
  id: string
}

export interface SidebarGroupEntry {
  type: 'group'
  id: string
  name: string
  items: string[]
}

export type SidebarLayoutEntry = SidebarItemEntry | SidebarGroupEntry

export interface SidebarItemSource {
  id: string
  isPlugin: boolean
}

export const DEFAULT_PLUGIN_GROUP_ID = 'more-features'

export const builtinSidebarItems = [
  { id: '/overview', label: 'nav.overview', icon: 'DataAnalysis' },
  { id: '/provider', label: 'nav.provider', icon: 'Connection' },
  { id: '/adapter', label: 'nav.adapter', icon: 'Link' },
  { id: '/persona', label: 'nav.persona', icon: 'User' },
  { id: '/sticker', label: 'nav.sticker', icon: 'Picture' },
  { id: '/configuration', label: 'nav.configuration', icon: 'Tools' },
  { id: '/plugin', label: 'nav.plugin', icon: 'SetUp' },
  { id: '/webchat', label: 'nav.webchat', icon: 'ChatDotRound' },
  { id: '/sessions', label: 'nav.sessions', icon: 'ChatDotRound' },
  { id: '/logs', label: 'nav.logs', icon: 'Document' },
  { id: '/settings', label: 'nav.settings', icon: 'Setting' },
]

export function normalizeSidebarLayout(value: unknown): SidebarLayoutEntry[] | null {
  if (!Array.isArray(value)) return null
  const result: SidebarLayoutEntry[] = []
  const itemIds = new Set<string>()
  const groupIds = new Set<string>()
  const takeItem = (id: unknown): id is string => {
    if (typeof id !== 'string' || !id.startsWith('/') || itemIds.has(id)) return false
    itemIds.add(id)
    return true
  }
  for (const entry of value) {
    if (!entry || typeof entry !== 'object') continue
    if (entry.type === 'item' && takeItem(entry.id)) {
      result.push({ type: 'item', id: entry.id })
    } else if (entry.type === 'group'
      && typeof entry.id === 'string' && /^[a-zA-Z0-9_-]+$/.test(entry.id) && !groupIds.has(entry.id)
      && typeof entry.name === 'string' && (entry.name.trim() || entry.id === DEFAULT_PLUGIN_GROUP_ID)
      && Array.isArray(entry.items)) {
      groupIds.add(entry.id)
      result.push({ type: 'group', id: entry.id, name: entry.name.trim(), items: entry.items.filter(takeItem) })
    }
  }
  // Ungrouped items must always precede every group, preserving each order.
  return [...result.filter(entry => entry.type === 'item'), ...result.filter(entry => entry.type === 'group')]
}

export function reconcileSidebarLayout(
  saved: SidebarLayoutEntry[] | null,
  items: SidebarItemSource[],
): SidebarLayoutEntry[] {
  if (saved === null) {
    return [
      ...items.filter(item => !item.isPlugin).map(item => ({ type: 'item' as const, id: item.id })),
      { type: 'group', id: DEFAULT_PLUGIN_GROUP_ID, name: '', items: items.filter(item => item.isPlugin).map(item => item.id) },
    ]
  }
  // Keep unavailable plugin references so re-enabling restores their placement.
  const result = normalizeSidebarLayout(saved) ?? []
  const assigned = new Set(result.flatMap(entry => entry.type === 'group' ? entry.items : [entry.id]))
  const pluginGroup = result.find((entry): entry is SidebarGroupEntry => entry.type === 'group' && entry.id === DEFAULT_PLUGIN_GROUP_ID)
  for (const item of items) {
    if (assigned.has(item.id)) continue
    if (item.isPlugin && pluginGroup) pluginGroup.items.push(item.id)
    else result.push({ type: 'item', id: item.id })
    assigned.add(item.id)
  }
  return normalizeSidebarLayout(result) ?? []
}

export function moveSidebarItem(
  layout: SidebarLayoutEntry[], id: string, groupId: string | null, beforeId?: string,
): SidebarLayoutEntry[] {
  const result = normalizeSidebarLayout(layout) ?? []
  const targetGroup = groupId === null ? undefined : result.find((entry): entry is SidebarGroupEntry => entry.type === 'group' && entry.id === groupId)
  const exists = result.some(entry => entry.type === 'item' ? entry.id === id : entry.items.includes(id))
  if (!exists || (groupId !== null && !targetGroup) || id === beforeId) return result
  const targetIds = targetGroup ? targetGroup.items : result.map(entry => entry.id)
  if (beforeId !== undefined && !targetIds.includes(beforeId)) return result
  for (let index = result.length - 1; index >= 0; index--) {
    const entry = result[index]!
    if (entry.type === 'item' && entry.id === id) result.splice(index, 1)
    else if (entry.type === 'group') entry.items = entry.items.filter(itemId => itemId !== id)
  }
  if (targetGroup) {
    const index = beforeId === undefined ? targetGroup.items.length : targetGroup.items.indexOf(beforeId)
    targetGroup.items.splice(index, 0, id)
  } else {
    const index = beforeId === undefined ? result.length : result.findIndex(entry => entry.id === beforeId)
    result.splice(index, 0, { type: 'item', id })
  }
  return normalizeSidebarLayout(result) ?? []
}

export function moveSidebarGroup(layout: SidebarLayoutEntry[], id: string, beforeId?: string): SidebarLayoutEntry[] {
  const result = normalizeSidebarLayout(layout) ?? []
  const index = result.findIndex(entry => entry.type === 'group' && entry.id === id)
  if (index < 0 || id === beforeId || (beforeId !== undefined && !result.some(entry => entry.type === 'group' && entry.id === beforeId))) return result
  const [group] = result.splice(index, 1)
  const target = beforeId === undefined ? result.length : result.findIndex(entry => entry.id === beforeId)
  result.splice(target, 0, group!)
  return result
}

export function removeSidebarGroup(layout: SidebarLayoutEntry[], id: string): SidebarLayoutEntry[] {
  const result = layout.flatMap(entry => entry.type === 'group' && entry.id === id
    ? entry.items.map(itemId => ({ type: 'item' as const, id: itemId }))
    : [entry])
  return normalizeSidebarLayout(result) ?? []
}
