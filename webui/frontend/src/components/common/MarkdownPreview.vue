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
    <article v-else ref="articleRef" class="markdown-preview markdown-body text-sm leading-6 text-theme-body" @click="onLinkClick" v-html="renderedReadme" />
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
