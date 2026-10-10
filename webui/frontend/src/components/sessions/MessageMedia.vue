<template>
  <div class="chat-media rounded-lg border p-3 space-y-2">
    <p class="text-xs text-theme-subtle">{{ $t(`sessions.history.${element.type}`) }}<span v-if="element.name"> · {{ element.name }}</span><span v-if="element.size != null"> · {{ Math.ceil(element.size / 1024) }} KB</span></p>
    <p v-if="element.caption" class="whitespace-pre-wrap">{{ element.caption }}</p>
    <p v-if="element.description" class="whitespace-pre-wrap">{{ element.description }}</p>
    <p v-if="element.transcript" class="whitespace-pre-wrap">{{ element.transcript }}</p>
    <p v-if="element.file_type !== 'archive'" class="text-xs text-theme-subtle">{{ $t('sessions.history.media_unavailable') }}</p>
    <template v-else>
      <button v-if="!url" type="button" class="chat-media-link disabled:opacity-50" :disabled="loading" @click="loadMedia">
        {{ $t(loading ? 'sessions.history.loading' : 'sessions.history.load_media') }}
      </button>
      <p v-if="failed" role="alert" class="text-xs text-red-600 dark:text-red-400">{{ $t('sessions.history.media_failed') }}</p>
      <template v-if="url">
        <img v-if="element.type === 'image' || element.type === 'sticker'" :src="url" :alt="element.caption || element.description || element.name || $t(`sessions.history.${element.type}`)" class="max-h-80 max-w-full rounded object-contain" @error="failed = true" />
        <audio v-else-if="element.type === 'record'" :src="url" controls preload="metadata" class="max-w-full" @error="failed = true" />
        <video v-else-if="element.type === 'video'" :src="url" controls preload="metadata" class="max-h-80 max-w-full rounded" @error="failed = true" />
        <a :href="url" :download="element.name || element.type" class="inline-block chat-media-link">{{ $t('sessions.history.download') }}</a>
      </template>
    </template>
  </div>
</template>

<script setup lang="ts">
import { ref, onBeforeUnmount } from 'vue'
import { getMessageMedia } from '@/api/session'
import type { MessageElement } from '@/types'

const props = defineProps<{ element: MessageElement; messageId: string; elementPath: string; mediaScope?: 'sessions' | 'webchat' }>()
const url = ref('')
const loading = ref(false)
const failed = ref(false)
const controller = new AbortController()

async function loadMedia() {
  loading.value = true
  failed.value = false
  try {
    const response = await getMessageMedia(props.messageId, props.elementPath, controller.signal, props.mediaScope)
    if (!controller.signal.aborted) url.value = URL.createObjectURL(response.data)
  } catch {
    if (!controller.signal.aborted) failed.value = true
  } finally {
    loading.value = false
  }
}

onBeforeUnmount(() => {
  controller.abort()
  if (url.value) URL.revokeObjectURL(url.value)
})
</script>
