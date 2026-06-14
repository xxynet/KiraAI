<template>
  <div class="plugin-page-wrapper">
    <iframe
      v-if="pageUrl"
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
import { computed } from 'vue'

const props = defineProps<{
  pluginId: string
  pageRoute: string
}>()

const pageUrl = computed(() => {
  if (!props.pluginId || !props.pageRoute) return ''
  // Auth is handled via kira_token cookie — iframe sends it automatically (same-origin)
  return `/page/plugin/${encodeURIComponent(props.pluginId)}/${props.pageRoute}`
})
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
