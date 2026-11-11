<template>
  <div>
    <button
      type="button"
      class="flex w-full items-center justify-between gap-3 rounded-lg border border-gray-300 px-3 py-2 text-sm text-theme-body hover:bg-gray-50 dark:border-gray-600 dark:hover:bg-gray-800 disabled:opacity-50"
      :disabled="disabled"
      @click="openPicker"
    >
      <span>{{ $t('plugin.subagents.choose_tools') }}</span>
      <span class="text-xs text-theme-subtle">{{ $t('plugin.subagents.tools_selected', { count: modelValue.length }) }}</span>
    </button>
  </div>

  <Modal v-model="visible" content-class="max-w-2xl">
    <section class="flex max-h-[85vh] flex-col rounded-lg bg-white shadow-xl dark:bg-gray-900" role="dialog" aria-modal="true" :aria-label="label" @keydown.esc.stop.prevent="visible = false">
      <div class="flex items-center justify-between gap-4 border-b border-gray-200 px-6 py-4 dark:border-gray-700">
        <div>
          <h3 class="text-lg font-semibold text-theme-strong">{{ label }}</h3>
          <p class="mt-1 text-xs text-theme-subtle">{{ $t('plugin.subagents.tools_picker_hint') }}</p>
        </div>
        <button type="button" class="shrink-0 text-theme-faint text-theme-faint-hover" :aria-label="$t('plugin.close')" @click="visible = false"><IconClose class="h-6 w-6" /></button>
      </div>
      <div class="min-h-0 flex-1 space-y-4 overflow-y-auto px-6 py-4">
        <div class="flex items-center gap-2">
          <UiInput ref="searchInput" v-model="query" :placeholder="$t('plugin.subagents.tools_search')" :aria-label="$t('plugin.subagents.tools_search')" class="min-w-0 flex-1 rounded-lg px-3 py-2 text-sm" />
          <button type="button" class="rounded-md border border-gray-300 p-2 text-theme-subtle hover:bg-gray-50 dark:border-gray-600 dark:hover:bg-gray-800 disabled:opacity-50" :disabled="loading" :aria-label="$t('common.refresh')" @click="loadTools"><IconRefresh class="h-4 w-4" :class="{ 'animate-spin': loading }" /></button>
        </div>
        <div class="flex flex-wrap items-center justify-between gap-2 text-xs">
          <span class="text-theme-subtle">{{ $t('plugin.subagents.tools_selected', { count: draft.length }) }}</span>
          <div class="flex gap-3">
            <button type="button" class="text-theme-subtle hover:text-gray-900 dark:hover:text-gray-100 disabled:opacity-50" :disabled="!filteredGroups.length" @click="selectVisible">{{ $t('plugin.subagents.tools_select_visible') }}</button>
            <button type="button" class="text-theme-subtle hover:text-gray-900 dark:hover:text-gray-100 disabled:opacity-50" :disabled="!draft.length" @click="draft = []">{{ $t('plugin.subagents.tools_clear') }}</button>
          </div>
        </div>
        <p v-if="loadError" role="alert" class="whitespace-pre-wrap break-words text-sm text-red-600 dark:text-red-400">{{ loadError }}</p>
        <p v-if="loading" role="status" class="flex items-center justify-center gap-2 py-6 text-sm text-theme-subtle"><IconSpinner class="h-5 w-5 animate-spin" />{{ $t('plugin.status_loading') }}</p>
        <p v-else-if="!filteredGroups.length" class="py-6 text-center text-sm text-theme-subtle">{{ $t(query.trim() ? 'plugin.no_search_results' : 'plugin.subagents.tools_empty') }}</p>
        <CollapsibleSection
          v-for="group in filteredGroups"
          :key="group.plugin.id"
          :title="pluginName(group)"
          :description="group.plugin.id"
          :collapsed="!expandedGroups.has(group.plugin.id)"
          @update:collapsed="setGroupCollapsed(group.plugin.id, $event)"
        >
          <template #icon>
            <input
              type="checkbox"
              class="ui-checkbox"
              :aria-label="pluginName(group)"
              :checked="group.tools.every(tool => selected.has(tool.name))"
              :indeterminate="group.tools.some(tool => selected.has(tool.name)) && !group.tools.every(tool => selected.has(tool.name))"
              @click.stop
              @keydown.enter.stop
              @keydown.space.stop
              @change="setGroup(group, ($event.target as HTMLInputElement).checked)"
            />
          </template>
          <template #trailing>
            <span class="text-xs text-theme-subtle">{{ group.tools.filter(tool => selected.has(tool.name)).length }} / {{ group.tools.length }}</span>
          </template>
          <div class="-m-4 divide-y divide-gray-100 dark:divide-gray-800">
            <label v-for="tool in group.tools" :key="tool.name" class="flex cursor-pointer items-start gap-3 px-4 py-3 hover:bg-gray-50 dark:hover:bg-gray-800/50">
              <input type="checkbox" class="ui-checkbox mt-0.5" :checked="selected.has(tool.name)" @change="setTool(tool.name, ($event.target as HTMLInputElement).checked)" />
              <span class="min-w-0">
                <span class="block break-all font-mono text-sm text-theme-body">{{ tool.name }}</span>
                <span v-if="toolDescription(tool)" class="mt-1 block whitespace-pre-wrap break-words text-xs leading-relaxed text-theme-subtle">{{ toolDescription(tool) }}</span>
              </span>
            </label>
          </div>
        </CollapsibleSection>
        <div class="border-t border-gray-200 pt-4 dark:border-gray-700">
          <p class="mb-1 text-sm font-medium text-theme-body">{{ $t('plugin.subagents.tools_manual') }}</p>
          <div role="group" :aria-label="$t('plugin.subagents.tools_manual')">
            <TagInput v-model="toolNames" :placeholder="$t('plugin.subagents.tools_manual_placeholder')" />
          </div>
          <p class="mt-2 text-xs text-theme-subtle">{{ $t('plugin.subagents.tools_manual_hint') }}</p>
        </div>
      </div>
      <div class="flex justify-end gap-3 border-t border-gray-200 px-6 py-4 dark:border-gray-700">
        <button type="button" class="rounded-lg border border-gray-300 px-4 py-2 text-theme-body hover:bg-gray-50 dark:border-gray-600 dark:hover:bg-gray-800" @click="visible = false">{{ $t('plugin.config_modal_cancel') }}</button>
        <button type="button" class="rounded-lg bg-blue-600 px-4 py-2 text-white hover:bg-blue-700 dark:bg-blue-700 dark:hover:bg-blue-600" @click="applySelection">{{ $t('plugin.subagents.tools_confirm') }}</button>
      </div>
    </section>
  </Modal>
</template>

<script setup lang="ts">
import { computed, nextTick, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { getPluginComponents, getPlugins } from '@/api/plugin'
import type { PluginComponent, PluginItem } from '@/types'
import { useLocalized } from '@/composables/useLocalized'
import { IconClose, IconRefresh, IconSpinner } from '@/components/icons'
import Modal from '@/components/common/Modal.vue'
import CollapsibleSection from '@/components/common/CollapsibleSection.vue'
import UiInput from '@/components/ui/UiInput.vue'
import TagInput from '@/components/common/TagInput.vue'

interface ToolGroup {
  plugin: PluginItem
  tools: PluginComponent[]
}

const props = defineProps<{ modelValue: string[]; label: string; disabled?: boolean }>()
const emit = defineEmits<{ 'update:modelValue': [value: string[]] }>()
const { t, locale } = useI18n()
const { localize } = useLocalized()
const visible = ref(false)
const loading = ref(false)
const loadError = ref('')
const groups = ref<ToolGroup[]>([])
const expandedGroups = ref(new Set<string>())
const query = ref('')
const draft = ref<string[]>([])
const searchInput = ref<InstanceType<typeof UiInput> | null>(null)
const selected = computed(() => new Set(draft.value))
const toolNames = computed({
  get: () => draft.value,
  set: (names: string[]) => {
    draft.value = [...new Set(names.map(name => name.trim()).filter(Boolean))]
  },
})
const filteredGroups = computed(() => {
  const search = query.value.trim().toLowerCase()
  if (!search) return groups.value
  return groups.value.map(group => {
    const pluginMatches = `${pluginName(group)} ${group.plugin.id}`.toLowerCase().includes(search)
    return {
      ...group,
      tools: pluginMatches ? group.tools : group.tools.filter(tool => `${tool.name} ${toolDescription(tool)}`.toLowerCase().includes(search)),
    }
  }).filter(group => group.tools.length)
})

function pluginName(group: ToolGroup) {
  return localize(group.plugin, 'display_name', group.plugin.name || group.plugin.id)
}

function toolDescription(tool: PluginComponent): string {
  if (typeof tool.description === 'string') return tool.description
  return tool.description[locale.value] || tool.description[locale.value.split(/[-_]/)[0]!] || tool.description.en || Object.values(tool.description)[0] || ''
}

function openPicker() {
  if (props.disabled) return
  draft.value = [...props.modelValue]
  query.value = ''
  expandedGroups.value = new Set()
  visible.value = true
  void nextTick(() => searchInput.value?.$el.focus())
  void loadTools()
}

function errorDetail(error: any): string {
  const detail = error?.response?.data?.detail
  return typeof detail === 'string' ? detail : error?.message || String(error)
}

async function loadTools() {
  if (loading.value) return
  loading.value = true
  loadError.value = ''
  groups.value = []
  try {
    const response = await getPlugins()
    const plugins = response.data.filter(plugin => plugin.enabled)
    const results = await Promise.allSettled(plugins.map(plugin => getPluginComponents(plugin.id)))
    const errors: string[] = []
    results.forEach((result, index) => {
      const plugin = plugins[index]!
      if (result.status === 'rejected') {
        errors.push(`${plugin.name || plugin.id}: ${errorDetail(result.reason)}`)
        return
      }
      const tools = result.value.data.filter(component => component.type === 'tool')
      if (tools.length) groups.value.push({ plugin, tools })
    })
    if (errors.length) loadError.value = `${t('plugin.subagents.tools_load_failed')}\n${errors.join('\n')}`
  } catch (error) {
    loadError.value = `${t('plugin.subagents.tools_load_failed')}: ${errorDetail(error)}`
  } finally {
    loading.value = false
  }
}

function setTool(name: string, checked: boolean) {
  draft.value = checked ? [...new Set([...draft.value, name])] : draft.value.filter(item => item !== name)
}

function setGroupCollapsed(pluginId: string, collapsed: boolean) {
  if (collapsed) expandedGroups.value.delete(pluginId)
  else expandedGroups.value.add(pluginId)
}

function setGroup(group: ToolGroup, checked: boolean) {
  const names = new Set(group.tools.map(tool => tool.name))
  draft.value = checked ? [...new Set([...draft.value, ...names])] : draft.value.filter(name => !names.has(name))
}

function selectVisible() {
  draft.value = [...new Set([...draft.value, ...filteredGroups.value.flatMap(group => group.tools.map(tool => tool.name))])]
}

function applySelection() {
  emit('update:modelValue', [...draft.value])
  visible.value = false
}
</script>
