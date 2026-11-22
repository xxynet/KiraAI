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
    <article v-else ref="articleRef" class="markdown-preview text-sm leading-6 text-theme-body" @click="onLinkClick" v-html="renderedReadme" />
  </section>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
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
  /** Optional authenticated image loading supplied by the content owner. */
  resolveImage?: (url: string) => Promise<string | null>
}>()

const emit = defineEmits<{ 'link-click': [href: string, event: MouseEvent] }>()
const articleRef = ref<HTMLElement | null>(null)
const renderedReadme = computed(() => (props.readme ? renderMarkdown(props.readme) : ''))

watch([renderedReadme, articleRef, () => props.resolveImage], (_, __, onCleanup) => {
  let cancelled = false
  onCleanup(() => { cancelled = true })
  if (!props.resolveImage || !articleRef.value) return
  for (const image of articleRef.value.querySelectorAll<HTMLImageElement>('img[data-markdown-image]')) {
    void props.resolveImage(image.dataset.markdownImage!).then(url => {
      if (!cancelled && url) image.src = url
    })
  }
}, { flush: 'post' })

function scrollToFragment(fragment: string) {
  let id: string
  try {
    id = decodeURIComponent(fragment)
  } catch {
    return
  }
  if (!id) return
  const target = Array.from(articleRef.value?.querySelectorAll<HTMLElement>('[id]') || [])
    .find(element => element.id === id)
  target?.scrollIntoView({ block: 'start' })
}

function onLinkClick(event: MouseEvent) {
  const link = event.target instanceof Element ? event.target.closest('a[href]') : null
  if (!link || !articleRef.value?.contains(link)) return
  const href = link.getAttribute('href')!
  if (href.startsWith('#')) {
    event.preventDefault()
    scrollToFragment(href.slice(1))
  } else {
    emit('link-click', href, event)
  }
}

defineExpose({ scrollToFragment })

function renderMarkdown(text: string): string {
  const sanitized = DOMPurify.sanitize(marked.parse(text, { async: false }) as string)
  const parsedDocument = new DOMParser().parseFromString(sanitized, 'text/html')
  parsedDocument.querySelectorAll('[data-markdown-image]').forEach(element => element.removeAttribute('data-markdown-image'))
  const headingIds = new Set<string>()
  parsedDocument.querySelectorAll('h1, h2, h3, h4, h5, h6').forEach(heading => {
    const base = heading.id || (heading.textContent || '').trim().toLowerCase()
      .replace(/[^\p{L}\p{N}\p{M}_\s-]/gu, '').replace(/\s/g, '-')
    let id = base
    let index = 0
    while (headingIds.has(id)) id = `${base}-${++index}`
    heading.id = id
    headingIds.add(id)
  })
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
    if (src && props.resolveImage) {
      img.setAttribute('data-markdown-image', src)
      img.removeAttribute('src')
    } else if (src && repoUrl) {
      img.setAttribute('src', resolveReadmeUrl(src, repoUrl, true, props.repoRef))
    }
  })
  return parsedDocument.body.innerHTML
}
</script>

<style>
/* GitHub-style README rendering: h1/h2 carry a bottom rule, and images stay
   inline so multi-image paragraphs (badge rows) flow on one line instead of
   being stacked by Tailwind preflight's img { display: block }. */
.markdown-preview h1,
.markdown-preview h2,
.markdown-preview h3 {
  margin: 1.5em 0 0.5em;
  font-weight: 600;
}

.markdown-preview h1 { font-size: 2em; padding-bottom: 0.3em; border-bottom: 1px solid rgb(229 231 235); }
.markdown-preview h2 { font-size: 1.5em; padding-bottom: 0.3em; border-bottom: 1px solid rgb(229 231 235); }
.markdown-preview h3 { font-size: 1.25em; }
.markdown-preview h4 { margin: 1.5em 0 0.5em; font-size: 1em; font-weight: 600; }

.dark .markdown-preview h1,
.dark .markdown-preview h2 { border-bottom-color: rgb(55 65 81); }

.markdown-preview p,
.markdown-preview ul,
.markdown-preview ol,
.markdown-preview pre {
  margin: 0.75em 0;
}

.markdown-preview ul { list-style: disc; padding-left: 1.5em; }
.markdown-preview ol { list-style: decimal; padding-left: 1.5em; }
.markdown-preview pre { overflow-x: auto; padding: 0.75em; border-radius: 0.375rem; background: rgb(243 244 246); color: rgb(31 41 55); }
.markdown-preview code { padding: 0.125em 0.25em; border-radius: 0.25rem; background: rgb(243 244 246); font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; }
.markdown-preview pre code { padding: 0; background: transparent; }
.markdown-preview a { color: rgb(37 99 235); text-decoration: underline; }
.markdown-preview blockquote { margin: 0.75em 0; border-left: 3px solid rgb(209 213 219); padding-left: 0.75em; color: rgb(75 85 99); }
.markdown-preview hr { margin: 1.25em 0; border-color: rgb(229 231 235); }
.markdown-preview table { display: block; width: max-content; max-width: 100%; overflow-x: auto; border-collapse: collapse; }
.markdown-preview th,
.markdown-preview td { border: 1px solid rgb(229 231 235); padding: 0.5em 0.75em; text-align: left; }
.markdown-preview th { background: rgb(249 250 251); font-weight: 600; }
.markdown-preview img { display: inline; vertical-align: middle; max-width: 100%; height: auto; }

.dark .markdown-preview pre { background: rgb(31 41 55); color: rgb(229 231 235); }
.dark .markdown-preview code { background: rgb(31 41 55); }
.dark .markdown-preview pre code { background: transparent; }
.dark .markdown-preview a { color: rgb(96 165 250); }
.dark .markdown-preview blockquote { border-color: rgb(75 85 99); color: rgb(156 163 175); }
.dark .markdown-preview hr { border-color: rgb(55 65 81); }
.dark .markdown-preview th,
.dark .markdown-preview td { border-color: rgb(55 65 81); }
.dark .markdown-preview th { background: rgb(31 41 55); }
</style>
