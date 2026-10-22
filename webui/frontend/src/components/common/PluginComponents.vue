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
          <p class="break-all font-mono text-sm text-theme-high">{{ component.name }}</p>
          <p v-if="description(component)" class="mt-1 whitespace-pre-wrap break-words text-sm text-theme-subtle">{{ description(component) }}</p>
        </li>
      </ul>
    </section>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import InfoCallout from '@/components/common/InfoCallout.vue'
import type { PluginComponent } from '@/types'

const props = defineProps<{ components: PluginComponent[] }>()
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

function description(component: PluginComponent): string {
  const value = component.description
  return typeof value === 'string' ? value : value[locale.value] || value.en || Object.values(value)[0] || ''
}
</script>
