<template>
  <section v-if="loading || readme" class="border-t border-gray-200 pt-5 dark:border-gray-700">
    <h4 class="text-sm font-medium text-theme-high">{{ $t('plugin.readme_title') }}</h4>
    <div v-if="loading" class="mt-3 text-sm text-theme-subtle">{{ $t('common.loading') }}</div>
    <article v-else class="plugin-readme mt-3 text-sm leading-6 text-theme-body" v-html="renderedReadme" />
  </section>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { marked } from 'marked'
import DOMPurify from 'dompurify'

const props = defineProps<{
  /** Raw README markdown; null while not loaded or unavailable. */
  readme: string | null
  loading: boolean
  /** HTTPS repository URL used to resolve relative links and images. */
  repoUrl: string | null
}>()

const renderedReadme = computed(() => (props.readme ? renderMarkdown(props.readme) : ''))

function renderMarkdown(text: string): string {
  const sanitized = DOMPurify.sanitize(marked.parse(text, { async: false }) as string)
  const parsedDocument = new DOMParser().parseFromString(sanitized, 'text/html')
  const repoUrl = props.repoUrl
  parsedDocument.querySelectorAll('a').forEach(link => {
    const href = link.getAttribute('href')
    // Fragment-only links point at anchors inside the rendered README itself;
    // keep them in the current document instead of opening a new tab.
    if (href && href.startsWith('#')) return
    if (href && repoUrl) link.setAttribute('href', resolveReadmeUrl(href, repoUrl, false))
    link.target = '_blank'
    link.rel = 'noopener noreferrer'
  })
  parsedDocument.querySelectorAll('img').forEach(img => {
    const src = img.getAttribute('src')
    if (src && repoUrl) img.setAttribute('src', resolveReadmeUrl(src, repoUrl, true))
  })
  return parsedDocument.body.innerHTML
}

// A plugin README is authored inside its repository, so relative URLs must be
// rewritten against the repository base instead of resolving against the
// WebUI origin. GitHub repos get default-branch URLs (raw for images, blob
// for links); other hosts fall back to generic URL joining.
function resolveReadmeUrl(raw: string, repoUrl: string, isImage: boolean): string {
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
        ? `https://raw.githubusercontent.com/${repo.owner}/${repo.name}/HEAD${path}`
        : `https://github.com/${repo.owner}/${repo.name}/blob/HEAD${path}`
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
    return { owner: segments[0], name: segments[1].replace(/\.git$/, '') }
  } catch {
    return null
  }
}
</script>

<style>
/* GitHub-style README rendering: h1/h2 carry a bottom rule, and images stay
   inline so multi-image paragraphs (badge rows) flow on one line instead of
   being stacked by Tailwind preflight's img { display: block }. */
.plugin-readme h1,
.plugin-readme h2,
.plugin-readme h3 {
  margin: 1.5em 0 0.5em;
  font-weight: 600;
}

.plugin-readme h1 { font-size: 2em; padding-bottom: 0.3em; border-bottom: 1px solid rgb(229 231 235); }
.plugin-readme h2 { font-size: 1.5em; padding-bottom: 0.3em; border-bottom: 1px solid rgb(229 231 235); }
.plugin-readme h3 { font-size: 1.25em; }
.plugin-readme h4 { margin: 1.5em 0 0.5em; font-size: 1em; font-weight: 600; }

.dark .plugin-readme h1,
.dark .plugin-readme h2 { border-bottom-color: rgb(55 65 81); }

.plugin-readme p,
.plugin-readme ul,
.plugin-readme ol,
.plugin-readme pre {
  margin: 0.75em 0;
}

.plugin-readme ul { list-style: disc; padding-left: 1.5em; }
.plugin-readme ol { list-style: decimal; padding-left: 1.5em; }
.plugin-readme pre { overflow-x: auto; padding: 0.75em; border-radius: 0.375rem; background: rgb(243 244 246); color: rgb(31 41 55); }
.plugin-readme code { padding: 0.125em 0.25em; border-radius: 0.25rem; background: rgb(243 244 246); font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; }
.plugin-readme pre code { padding: 0; background: transparent; }
.plugin-readme a { color: rgb(37 99 235); text-decoration: underline; }
.plugin-readme blockquote { margin: 0.75em 0; border-left: 3px solid rgb(209 213 219); padding-left: 0.75em; color: rgb(75 85 99); }
.plugin-readme hr { margin: 1.25em 0; border-color: rgb(229 231 235); }
.plugin-readme table { display: block; width: max-content; max-width: 100%; overflow-x: auto; border-collapse: collapse; }
.plugin-readme th,
.plugin-readme td { border: 1px solid rgb(229 231 235); padding: 0.5em 0.75em; text-align: left; }
.plugin-readme th { background: rgb(249 250 251); font-weight: 600; }
.plugin-readme img { display: inline; vertical-align: middle; max-width: 100%; height: auto; }

.dark .plugin-readme pre { background: rgb(31 41 55); color: rgb(229 231 235); }
.dark .plugin-readme code { background: rgb(31 41 55); }
.dark .plugin-readme pre code { background: transparent; }
.dark .plugin-readme a { color: rgb(96 165 250); }
.dark .plugin-readme blockquote { border-color: rgb(75 85 99); color: rgb(156 163 175); }
.dark .plugin-readme hr { border-color: rgb(55 65 81); }
.dark .plugin-readme th,
.dark .plugin-readme td { border-color: rgb(55 65 81); }
.dark .plugin-readme th { background: rgb(31 41 55); }
</style>
