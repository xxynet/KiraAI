<template>
  <div class="plugin-page-wrapper">
    <iframe
      v-if="pageUrl"
      ref="iframeRef"
      :src="pageUrl"
      class="plugin-page-iframe"
      sandbox="allow-scripts allow-same-origin allow-forms allow-popups"
    />
    <div v-else class="flex items-center justify-center h-64 text-gray-500">
      <p>{{ $t('pluginPage.invalid_config') }}</p>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch, onMounted, onUnmounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { useAppStore } from '@/stores/app'

const CHANNEL = 'kira-plugin-page'

const props = defineProps<{
  pluginId: string
  pageRoute: string
}>()

const iframeRef = ref<HTMLIFrameElement | null>(null)
const appStore = useAppStore()
const { locale } = useI18n()

const pageUrl = computed(() => {
  if (!props.pluginId || !props.pageRoute) return ''
  return `/page/plugin/${encodeURIComponent(props.pluginId)}/${props.pageRoute}`
})

function buildContext() {
  return {
    channel: CHANNEL,
    kind: 'context' as const,
    context: {
      pluginId: props.pluginId,
      pageRoute: props.pageRoute,
      isDark: appStore.isDark,
      locale: locale.value,
    },
  }
}

function sendContext() {
  const iframe = iframeRef.value
  if (!iframe?.contentWindow) return
  iframe.contentWindow.postMessage(buildContext(), '*')
}

function onMessage(e: MessageEvent) {
  const data = e.data
  if (!data || data.channel !== CHANNEL) return
  if (data.kind === 'ready') {
    sendContext()
  }
}

onMounted(() => {
  window.addEventListener('message', onMessage)
  // Send context immediately in case the iframe's bridge already fired "ready"
  // before we attached the listener. Harmless if iframe hasn't loaded yet —
  // it will request context via its own "ready" message when it does.
  sendContext()
})
onUnmounted(() => window.removeEventListener('message', onMessage))

// Re-send context when theme or locale changes
watch(() => appStore.isDark, sendContext)
watch(locale, sendContext)
</script>

<style scoped>
.plugin-page-wrapper {
  flex: 1;
  min-height: 0;
  width: 100%;
}

.plugin-page-iframe {
  width: 100%;
  height: 100%;
  border: none;
}
</style>
