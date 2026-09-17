<template>
  <span v-if="sanitized" class="inline-svg-icon" aria-hidden="true" v-html="sanitized" />
  <!-- Render nothing while loading; fall back only on failure -->
  <slot v-else-if="failed" name="fallback" />
</template>

<script lang="ts">
// Shared across component instances: icon URLs are stable for the
// lifetime of the page, so each URL is fetched and sanitized once.
const svgCache = new Map<string, string>()
</script>

<script setup lang="ts">
import { ref, watch } from 'vue'
import DOMPurify from 'dompurify'
import apiClient from '@/api/client'

const props = defineProps<{ src: string }>()

const sanitized = ref('')
const failed = ref(false)

/**
 * Fetch an image URL served by the backend and sanitize it for inline SVG
 * rendering. apiClient's baseURL already includes "/api", so strip that
 * prefix from same-origin URLs before requesting them.
 */
async function load(src: string): Promise<void> {
  const cached = svgCache.get(src)
  if (cached !== undefined) {
    sanitized.value = cached
    failed.value = false
    return
  }
  sanitized.value = ''
  failed.value = false
  try {
    const path = src.startsWith('/api/') ? src.slice('/api'.length) : src
    const { data } = await apiClient.get<string>(path, { responseType: 'text' })
    // Restrict to the SVG profile: drops <script>, event handler
    // attributes, and foreign content while keeping SVG markup intact.
    const clean = DOMPurify.sanitize(data, {
      USE_PROFILES: { svg: true, svgFilters: true },
    })
    if (clean) {
      svgCache.set(src, clean)
      sanitized.value = clean
    } else {
      failed.value = true
    }
  } catch {
    failed.value = true
  }
}

watch(() => props.src, load, { immediate: true })
</script>

<style scoped>
.inline-svg-icon {
  display: inline-flex;
  overflow: hidden;
}

.inline-svg-icon :deep(svg) {
  width: 100%;
  height: 100%;
}
</style>
