export type SkillFileReference =
  | { kind: 'external' }
  | { kind: 'invalid' }
  | { kind: 'file'; path: string; fragment: string }

export function resolveSkillFileReference(raw: string, activePath: string): SkillFileReference {
  const url = raw.trim()
  if (/^[a-z][a-z\d+.-]*:/i.test(url) || url.startsWith('//')) return { kind: 'external' }
  const hash = url.indexOf('#')
  const fragment = hash < 0 ? '' : url.slice(hash + 1)
  const resource = (hash < 0 ? url : url.slice(0, hash)).split('?')[0]!
  let path: string
  try {
    path = decodeURIComponent(resource)
  } catch {
    return { kind: 'invalid' }
  }
  if (/[\\\0:]/.test(path)) return { kind: 'invalid' }
  if (!path) return { kind: 'file', path: activePath, fragment }
  const parts = path.startsWith('/') ? [] : activePath.split('/').slice(0, -1)
  for (const part of path.split('/')) {
    if (!part || part === '.') continue
    if (part === '..') {
      if (!parts.length) return { kind: 'invalid' }
      parts.pop()
    } else {
      parts.push(part)
    }
  }
  return parts.length ? { kind: 'file', path: parts.join('/'), fragment } : { kind: 'invalid' }
}

export function stripSkillFrontmatter(content: string): string {
  return content.replace(/^\uFEFF?---[ \t]*\r?\n[\s\S]*?^---[ \t]*(?:\r?\n|$)/m, (match, offset) =>
    offset === 0 ? '' : match)
}

const imageTypes: Record<string, string> = {
  png: 'image/png', jpg: 'image/jpeg', jpeg: 'image/jpeg', gif: 'image/gif',
  webp: 'image/webp', avif: 'image/avif', bmp: 'image/bmp', ico: 'image/x-icon',
}

export function skillImageType(path: string): string | undefined {
  return imageTypes[path.split('.').pop()?.toLowerCase() || '']
}
