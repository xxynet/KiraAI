<template>
  <div :class="element.type === 'file' ? 'w-72 max-w-full rounded-2xl bg-[var(--color-chat-surface)] p-4' : ['chat-media rounded-lg border p-3 space-y-2', { 'w-48 max-w-full': element.type === 'sticker' }]">
    <component
      :is="url ? 'a' : 'div'"
      v-if="element.type === 'file'"
      :href="url || undefined"
      :download="url ? downloadName : undefined"
      :title="url ? $t('sessions.history.download') : undefined"
      :aria-busy="loading"
      class="flex min-h-20 items-start justify-between gap-4 rounded-lg focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-500"
    >
      <div class="flex min-h-20 min-w-0 flex-1 flex-col justify-between gap-5">
        <p class="line-clamp-2 break-all text-base font-medium text-theme-strong" :title="element.name">{{ element.name || $t('sessions.history.file') }}</p>
        <p v-if="fileSize != null" class="text-sm text-theme-subtle">{{ formatFileSize(fileSize) }}</p>
      </div>
      <svg aria-hidden="true" viewBox="0 0 48 56" class="h-14 w-12 shrink-0 text-gray-500 dark:text-gray-400" :class="{ 'opacity-50': !url }" fill="none">
        <path d="M8 1h24l10 10v39a5 5 0 0 1-5 5H8a5 5 0 0 1-5-5V6a5 5 0 0 1 5-5Z" fill="currentColor" opacity="0.65" />
        <path d="M32 1v7a3 3 0 0 0 3 3h7" fill="currentColor" />
        <circle cx="23" cy="30" r="13" fill="black" fill-opacity="0.25" stroke="currentColor" stroke-width="1.5" />
        <path d="M23 21v16m-6-6 6 6 6-6" stroke="white" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" />
      </svg>
    </component>
    <div v-else class="flex items-center justify-between gap-3" :class="{ 'min-h-6': element.type === 'sticker' }">
      <p class="min-w-0 break-all text-xs text-theme-subtle">{{ $t(`sessions.history.${element.type}`) }}<span v-if="element.name"> · {{ element.name }}</span><span v-if="element.size != null"> · {{ Math.ceil(element.size / 1024) }} KB</span></p>
      <a
        v-if="(url || element.type === 'sticker') && ['image', 'sticker', 'record'].includes(element.type)"
        :href="url"
        :download="downloadName"
        :aria-label="$t('sessions.history.download')"
        :title="$t('sessions.history.download')"
        :class="{ invisible: !url }"
        class="chat-media-link flex h-6 w-6 shrink-0 items-center justify-center rounded hover:opacity-75 focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-500"
      >
        <IconDownload aria-hidden="true" class="h-4 w-4" />
      </a>
    </div>
    <p v-if="element.type !== 'sticker' && element.caption" class="whitespace-pre-wrap">{{ element.caption }}</p>
    <p v-if="element.type !== 'sticker' && element.description" class="whitespace-pre-wrap">{{ element.description }}</p>
    <p v-if="element.transcript" class="whitespace-pre-wrap">{{ element.transcript }}</p>
    <div v-if="element.type === 'sticker'" class="flex h-40 items-center justify-center" :aria-busy="loading">
      <p v-if="element.file_type !== 'archive'" class="text-xs text-theme-subtle">{{ $t('sessions.history.media_unavailable') }}</p>
      <div v-else-if="failed" class="space-y-2">
        <button type="button" class="chat-media-link" @click="loadMedia">{{ $t('sessions.history.retry') }}</button>
        <p role="alert" class="text-xs text-red-600 dark:text-red-400">{{ $t('sessions.history.media_failed') }}</p>
      </div>
      <p v-else-if="loading" role="status" class="text-xs text-theme-subtle">{{ $t('sessions.history.loading') }}</p>
      <img v-else-if="url" :src="url" :alt="$t('sessions.history.sticker')" class="max-h-full max-w-full rounded object-contain" @error="failed = true" />
    </div>
    <p v-else-if="element.file_type !== 'archive'" class="text-xs text-theme-subtle">{{ $t('sessions.history.media_unavailable') }}</p>
    <template v-else>
      <p v-if="loading" role="status" class="text-xs text-theme-subtle">{{ $t('sessions.history.loading') }}</p>
      <button v-else-if="failed" type="button" class="chat-media-link" @click="loadMedia">
        {{ $t('sessions.history.retry') }}
      </button>
      <p v-if="failed" role="alert" class="text-xs text-red-600 dark:text-red-400">{{ $t('sessions.history.media_failed') }}</p>
      <template v-if="url">
        <img v-if="element.type === 'image'" :src="url" :alt="element.caption || element.description || element.name || $t('sessions.history.image')" class="max-h-80 max-w-full rounded object-contain" @error="failed = true" />
        <audio v-else-if="element.type === 'record'" :src="url" controls preload="metadata" class="max-w-full" @error="failed = true" />
        <video v-else-if="element.type === 'video'" :src="url" controls preload="metadata" class="max-h-80 max-w-full rounded" @error="failed = true" />
        <a v-if="element.type === 'video'" :href="url" :download="downloadName" class="inline-block chat-media-link">{{ $t('sessions.history.download') }}</a>
      </template>
    </template>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onBeforeUnmount } from 'vue'
import { getMessageMedia } from '@/api/session'
import { IconDownload } from '@/components/icons'
import type { MessageElement } from '@/types'

const props = defineProps<{ element: MessageElement; messageId: string; elementPath: string; mediaScope?: 'sessions' | 'webchat' }>()
const url = ref('')
const fileSize = ref(props.element.size)
const downloadName = ref(props.element.name || props.element.type)
const loading = ref(false)
const failed = ref(false)
const controller = new AbortController()

function formatFileSize(bytes: number) {
  if (bytes < 1024) return `${bytes} B`
  const units = ['KB', 'MB', 'GB', 'TB']
  const index = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)) - 1, units.length - 1)
  return `${(bytes / 1024 ** (index + 1)).toFixed(1)} ${units[index]}`
}

async function getDownloadName(blob: Blob) {
  const name = props.element.name || props.element.type
  if (/\.[^./\\]+$/.test(name)) return name
  const extensions: Record<string, string> = {
    'image/jpeg': 'jpg', 'image/png': 'png', 'image/gif': 'gif', 'image/webp': 'webp', 'image/bmp': 'bmp',
    'audio/mpeg': 'mp3', 'audio/mp3': 'mp3', 'audio/wav': 'wav', 'audio/x-wav': 'wav', 'audio/wave': 'wav',
    'audio/ogg': 'ogg', 'application/ogg': 'ogg', 'audio/opus': 'opus', 'audio/flac': 'flac', 'audio/x-flac': 'flac',
    'audio/aac': 'aac', 'audio/x-aac': 'aac', 'audio/mp4': 'm4a', 'audio/x-m4a': 'm4a',
    'audio/webm': 'webm', 'audio/amr': 'amr', 'audio/amr-wb': 'amr', 'audio/silk': 'silk',
    'video/mp4': 'mp4', 'video/webm': 'webm', 'video/ogg': 'ogv',
  }
  let extension = extensions[blob.type.split(';')[0]!.trim().toLowerCase()]
    || extensions[(props.element.mime || '').split(';')[0]!.trim().toLowerCase()]
  if (props.element.type === 'record') {
    const bytes = new Uint8Array(await blob.slice(0, 16).arrayBuffer())
    const header = String.fromCharCode(...bytes)
    if (header.startsWith('RIFF') && header.slice(8, 12) === 'WAVE') extension = 'wav'
    else if (header.startsWith('OggS')) extension = 'ogg'
    else if (header.startsWith('fLaC')) extension = 'flac'
    else if (header.startsWith('#!AMR')) extension = 'amr'
    else if (header.startsWith('#!SILK') || header.startsWith('\x02#!SILK')) extension = 'silk'
    else if (header.startsWith('ID3')) extension = 'mp3'
    else if (bytes[0] === 0xff && bytes[1] != null) {
      if ((bytes[1] & 0xf6) === 0xf0) extension = 'aac'
      else if ((bytes[1] & 0xe0) === 0xe0 && (bytes[1] & 0x06) !== 0) extension = 'mp3'
    } else if (header.slice(4, 8) === 'ftyp') extension = 'm4a'
    else if (bytes[0] === 0x1a && bytes[1] === 0x45 && bytes[2] === 0xdf && bytes[3] === 0xa3) extension = 'webm'
  }
  return extension ? `${name}.${extension}` : name
}

async function loadMedia() {
  if (loading.value || controller.signal.aborted || props.element.file_type !== 'archive') return
  if (url.value) URL.revokeObjectURL(url.value)
  url.value = ''
  loading.value = true
  failed.value = false
  try {
    const response = await getMessageMedia(props.messageId, props.elementPath, controller.signal, props.mediaScope)
    const name = await getDownloadName(response.data)
    if (!controller.signal.aborted) {
      downloadName.value = name
      url.value = URL.createObjectURL(response.data)
      fileSize.value = props.element.size ?? response.data.size
    }
  } catch {
    if (!controller.signal.aborted) failed.value = true
  } finally {
    loading.value = false
  }
}

onMounted(() => { void loadMedia() })

onBeforeUnmount(() => {
  controller.abort()
  if (url.value) URL.revokeObjectURL(url.value)
})
</script>
