<template>
  <section v-if="loading || readme">
    <div v-if="loading" role="status">
      <span class="sr-only">{{ $t('plugin.status_loading') }}</span>
      <div aria-hidden="true" class="space-y-3 motion-safe:animate-pulse">
        <div class="mb-4 h-5 w-1/3 rounded bg-gray-200 dark:bg-gray-700" />
        <div class="h-3 w-full rounded bg-gray-200 dark:bg-gray-700" />
        <div class="h-3 w-11/12 rounded bg-gray-200 dark:bg-gray-700" />
        <div class="h-3 w-2/3 rounded bg-gray-200 dark:bg-gray-700" />
      </div>
    </div>
    <article v-else class="plugin-readme text-sm leading-6 text-theme-body" v-html="renderedReadme" />
  </section>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { marked } from 'marked'
import DOMPurify from 'dompurify'
import { resolveReadmeUrl } from '@/utils/pluginReadme'

const props = defineProps<{
  /** Raw README markdown; null while not loaded or unavailable. */
  readme: string | null
  loading: boolean
  /** HTTPS repository URL used to resolve relative links and images. */
  repoUrl: string | null
  repoRef: string
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
    if (href && repoUrl) link.setAttribute('href', resolveReadmeUrl(href, repoUrl, false, props.repoRef))
    link.target = '_blank'
    link.rel = 'noopener noreferrer'
  })
  parsedDocument.querySelectorAll('img').forEach(img => {
    const src = img.getAttribute('src')
    if (src && repoUrl) img.setAttribute('src', resolveReadmeUrl(src, repoUrl, true, props.repoRef))
  })
  return parsedDocument.body.innerHTML
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
