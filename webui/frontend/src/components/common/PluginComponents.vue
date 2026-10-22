<template>
  <p v-if="!components.length" class="text-sm text-theme-subtle">{{ $t('plugin.components_empty') }}</p>
  <div v-else class="space-y-5">
    <section v-for="group in groups" :key="group.type">
      <h4 class="text-sm font-medium text-theme-high">
        {{ $t(`plugin.component_types.${group.type}`) }}
        <span class="ml-1 text-theme-faint">({{ group.items.length }})</span>
      </h4>
      <InfoCallout
        v-if="group.type === 'tool'"
        level="info"
        :label="$t('plugin.components_tools_hint')"
        class="mt-2"
      />
      <ul class="mt-2 divide-y divide-gray-200 rounded-lg border border-gray-200 dark:divide-gray-700 dark:border-gray-700">
        <li v-for="(component, index) in group.items" :key="index" class="px-4 py-3">
          <div v-if="component.type === 'page'" class="flex flex-wrap items-start justify-between gap-2 text-sm">
            <RouterLink
              :to="pagePath(component.name, true)"
              :title="$t('plugin.page_open_in_webui')"
              class="break-all font-mono text-blue-600 hover:underline dark:text-blue-400"
            >{{ component.name }}</RouterLink>
            <a
              :href="pagePath(component.name)"
              target="_blank"
              rel="noopener noreferrer"
              class="inline-flex shrink-0 items-center gap-1 text-blue-600 hover:underline dark:text-blue-400"
            >
              {{ $t('plugin.page_open_new_tab') }}
              <IconExternalLink class="h-4 w-4" />
            </a>
          </div>
          <p v-else class="break-all font-mono text-sm text-theme-high">{{ component.name }}</p>
          <p v-if="description(component)" class="mt-1 whitespace-pre-wrap break-words text-sm text-theme-subtle">{{ description(component) }}</p>
        </li>
      </ul>
    </section>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { RouterLink } from 'vue-router'
import { IconExternalLink } from '@/components/icons'
import InfoCallout from '@/components/common/InfoCallout.vue'
import type { PluginComponent } from '@/types'

const props = defineProps<{ components: PluginComponent[]; pluginId: string }>()
const { locale } = useI18n()
const groups = computed(() => {
  const byType = new Map<PluginComponent['type'], PluginComponent[]>()
  for (const component of props.components) {
    const items = byType.get(component.type) ?? []
    items.push(component)
    byType.set(component.type, items)
  }
  return [...byType].map(([type, items]) => ({ type, items }))
})

function pagePath(route: string, internal = false): string {
  const pageRoute = route.replace(/^\/+/, '').split('/').map(encodeURIComponent).join('/')
  const prefix = internal ? '/plugin-page' : '/page/plugin'
  return `${prefix}/${encodeURIComponent(props.pluginId)}/${pageRoute}`
}

function description(component: PluginComponent): string {
  const value = component.description
  return typeof value === 'string' ? value : value[locale.value] || value.en || Object.values(value)[0] || ''
}
</script>
