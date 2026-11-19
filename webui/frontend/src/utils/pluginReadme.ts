export function getStoreReadmeRef(commitSha?: string | null): string {
  const sha = commitSha?.trim().toLowerCase()
  return sha && /^[0-9a-f]{40}$/.test(sha) ? sha : 'main'
}

export async function fetchStoreReadme(repoUrl: string | null, ref: string): Promise<string | null> {
  const repo = repoUrl && parseGitHubRepoUrl(repoUrl)
  if (!repo) return null

  const base = `https://raw.githubusercontent.com/${repo.owner}/${repo.name}/${ref}`
  const signal = AbortSignal.timeout(10_000)
  for (const name of ['README.md', 'README.MD', 'README']) {
    const response = await fetch(`${base}/${name}`, { signal })
    if (response.status === 404) continue
    if (!response.ok) return null
    return (await response.text()).slice(0, 1_000_000)
  }
  return null
}

// A plugin README is authored inside its repository, so relative URLs must be
// rewritten against the repository base instead of resolving against the
// WebUI origin. GitHub repos use the README ref (raw for images, blob
// for links); other hosts fall back to generic URL joining.
export function resolveReadmeUrl(raw: string, repoUrl: string, isImage: boolean, ref: string): string {
  let candidate = raw.trim()
  if (!candidate || candidate.startsWith('#')) return raw
  if (candidate.startsWith('//')) candidate = `https:${candidate}`
  try {
    // Parseable without a base means the URL is already absolute (http:, mailto:, ...).
    new URL(candidate)
    return raw
  } catch {
    // Relative reference — resolve it below.
  }
  try {
    // Resolve ./, ../ and percent-encoding against a neutral root first.
    const resolved = new URL(candidate, 'https://readme.invalid/')
    const path = resolved.pathname + resolved.search + resolved.hash
    const repo = parseGitHubRepoUrl(repoUrl)
    if (repo) {
      return isImage
        ? `https://raw.githubusercontent.com/${repo.owner}/${repo.name}/${ref}${path}`
        : `https://github.com/${repo.owner}/${repo.name}/blob/${ref}${path}`
    }
    const base = repoUrl.endsWith('/') ? repoUrl : `${repoUrl}/`
    return new URL(candidate, base).toString()
  } catch {
    return raw
  }
}

function parseGitHubRepoUrl(repoUrl: string): { owner: string; name: string } | null {
  try {
    const url = new URL(repoUrl)
    if (url.protocol !== 'https:' && url.protocol !== 'http:') return null
    if (url.hostname !== 'github.com' && url.hostname !== 'www.github.com') return null
    const segments = url.pathname.split('/').filter(Boolean)
    if (segments.length < 2) return null
    const [owner, repo] = segments
    const name = repo.replace(/\.git$/, '')
    if (!/^[\w-]+$/.test(owner) || !/^[\w.-]+$/.test(name) || name === '.' || name === '..') return null
    return { owner, name }
  } catch {
    return null
  }
}
