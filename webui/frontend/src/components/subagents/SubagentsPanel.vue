<template>
  <section :aria-label="$t('plugin.tab_subagents')" :aria-busy="loading">
    <div class="flex flex-wrap items-center gap-2 mb-4">
      <button
        type="button"
        class="inline-flex items-center px-3 py-1.5 border border-gray-300 dark:border-gray-600 rounded-md text-xs font-medium text-theme-body bg-white dark:bg-gray-800 hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors disabled:opacity-50"
        :disabled="loading || operationsBusy"
        @click="openEditor()"
      >
        <span class="mr-1">+</span>
        <span>{{ $t('plugin.subagents.create') }}</span>
      </button>
      <button
        type="button"
        class="inline-flex shrink-0 items-center whitespace-nowrap px-3 py-1.5 border border-gray-300 dark:border-gray-600 rounded-md text-xs font-medium text-theme-body bg-white dark:bg-gray-800 hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors disabled:opacity-50"
        :disabled="loading || operationsBusy"
        @click="loadPresets"
      >
        <IconRefresh class="w-4 h-4 mr-1" :class="{ 'animate-spin': loading }" />
        <span>{{ $t('common.refresh') }}</span>
      </button>
      <div class="relative w-full sm:ml-auto sm:w-56">
        <UiInput
          v-model="searchTerm"
          type="text"
          :placeholder="$t('plugin.subagents.search_placeholder')"
          :aria-label="$t('plugin.subagents.search_placeholder')"
          class="w-full rounded-lg pl-9 pr-3 py-1.5 text-sm transition-colors"
        />
        <IconSearch class="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-theme-faint" />
      </div>
    </div>
    <div v-if="loadError" role="alert" class="flex justify-center items-center py-12">
      <div class="text-center">
        <ChatLineRound class="w-16 h-16 text-red-400 mx-auto mb-4" />
        <p class="text-red-500 whitespace-pre-wrap break-words">{{ loadError }}</p>
      </div>
    </div>
    <div v-else-if="loading" role="status" class="flex justify-center items-center gap-2 py-12 text-sm text-theme-subtle">
      <IconSpinner class="animate-spin h-6 w-6 text-blue-600 dark:text-blue-400" />
      {{ $t('plugin.status_loading') }}
    </div>
    <div v-else-if="!presets.length" class="flex justify-center items-center py-12">
      <div class="text-center">
        <ChatLineRound class="w-16 h-16 text-theme-faint mx-auto mb-4" />
        <p class="text-theme-subtle">{{ $t('plugin.subagents.empty') }}</p>
      </div>
    </div>
    <div v-else-if="!filteredPresets.length" class="flex justify-center items-center py-12">
      <div class="text-center">
        <IconSearch class="w-8 h-8 text-theme-faint mx-auto mb-2 opacity-50" />
        <p class="text-sm text-theme-faint">{{ $t('plugin.no_search_results') }}</p>
      </div>
    </div>
    <div v-else class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
      <article
        v-for="preset in filteredPresets"
        :key="preset.id"
        class="bg-white dark:bg-gray-900 rounded-lg shadow p-4 flex flex-col cursor-pointer focus:outline-none focus:ring-2 focus:ring-blue-500"
        role="button"
        :tabindex="operationsBusy ? -1 : 0"
        :aria-disabled="operationsBusy"
        @click="openEditor(preset)"
        @keydown.enter.self.prevent="openEditor(preset)"
        @keydown.space.self.prevent="openEditor(preset)"
      >
        <div class="flex items-start justify-between gap-3 mb-3">
          <div class="min-w-0">
            <h4 class="text-base font-semibold text-theme-high truncate" :title="preset.name">{{ preset.name }}</h4>
            <p class="mt-1 text-xs text-theme-subtle">{{ $t(preset.max_steps === -1 ? 'plugin.subagents.summary_unlimited' : 'plugin.subagents.summary', { steps: preset.max_steps, mode: $t('plugin.subagents.mode_' + preset.tool_mode) }) }}</p>
          </div>
          <button
            type="button"
            class="ml-2 relative inline-flex h-5 w-9 flex-shrink-0 cursor-pointer items-center rounded-full border transition-colors duration-200 ease-in-out focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-offset-2 disabled:opacity-50"
            :class="preset.enabled ? 'bg-blue-600 border-blue-600 dark:bg-blue-500 dark:border-blue-500' : 'bg-gray-200 border-gray-300 dark:bg-gray-700 dark:border-gray-600'"
            :aria-pressed="preset.enabled"
            :aria-label="$t('plugin.subagents.toggle_label', { name: preset.name })"
            :disabled="operationsBusy"
            @click.stop="togglePreset(preset)"
          >
            <span
              class="pointer-events-none inline-block h-4 w-4 transform rounded-full bg-white shadow ring-0 transition duration-200 ease-in-out"
              :class="preset.enabled ? 'translate-x-4' : 'translate-x-0'"
            />
          </button>
        </div>
        <p v-if="preset.description" class="text-sm text-theme-supporting line-clamp-3 whitespace-pre-wrap mb-3">{{ preset.description }}</p>
        <div class="mt-auto">
          <p class="text-xs font-mono text-theme-faint break-all mb-3">{{ preset.id }}</p>
          <div class="flex items-center justify-end space-x-3">
            <button
              type="button"
              class="px-3 py-1.5 text-xs font-medium rounded-md border border-gray-300 text-theme-body hover:bg-gray-50 dark:border-gray-600 dark:hover:bg-gray-800 transition-colors disabled:opacity-50"
              :disabled="operationsBusy"
              @click.stop="openEditor(preset)"
            >{{ $t('plugin.configure') }}</button>
            <button
              type="button"
              class="px-3 py-1.5 text-xs font-medium rounded-md border border-red-300 text-red-600 hover:bg-red-50 dark:border-red-600 dark:text-red-400 dark:hover:bg-red-900/30 transition-colors disabled:opacity-50"
              :disabled="operationsBusy"
              @click.stop="confirmDelete(preset)"
            >{{ $t('common.delete') }}</button>
          </div>
        </div>
      </article>
    </div>
  </section>

  <Modal
    :model-value="editorVisible"
    :persistent="saving"
    content-class="max-w-md"
    @update:model-value="setEditorVisible"
  >
    <form class="bg-white dark:bg-gray-900 rounded-lg shadow-xl w-full flex flex-col max-h-[90vh]" @submit.prevent="savePreset">
      <div class="flex justify-between items-center gap-4 px-6 py-4 border-b border-gray-200 dark:border-gray-700">
        <div class="min-w-0">
          <h3 class="text-lg font-semibold text-theme-strong">{{ $t(editingId ? 'plugin.subagents.edit' : 'plugin.subagents.create') }}</h3>
          <p class="mt-1 text-sm text-theme-subtle break-words">{{ editingId ? form.name : $t('plugin.subagents.description') }}</p>
        </div>
        <button
          type="button"
          class="shrink-0 text-theme-faint text-theme-faint-hover disabled:opacity-50"
          :aria-label="$t('plugin.close')"
          :disabled="saving"
          @click="editorVisible = false"
        >
          <IconClose class="w-6 h-6" />
        </button>
      </div>
      <div class="px-6 py-4 flex-1 min-h-0 overflow-y-auto">
        <fieldset class="space-y-4 min-w-0" :disabled="saving">
          <div>
            <label for="subagent-preset-name" class="block text-sm font-medium text-theme-body mb-1">{{ $t('plugin.name') }}</label>
            <UiInput id="subagent-preset-name" v-model="form.name" :placeholder="$t('plugin.subagents.name_placeholder')" class="w-full rounded-lg px-3 py-2" required maxlength="100" />
          </div>
          <div>
            <label for="subagent-preset-description" class="block text-sm font-medium text-theme-body mb-1">{{ $t('plugin.subagents.purpose') }}</label>
            <UiTextarea id="subagent-preset-description" v-model="form.description" :placeholder="$t('plugin.subagents.purpose_placeholder')" class="w-full rounded-lg px-3 py-2" rows="2" maxlength="2000" />
          </div>
          <div class="flex items-center justify-between gap-4">
            <span class="text-sm text-theme-body">{{ $t('plugin.subagents.enabled') }}</span>
            <button
              type="button"
              class="relative inline-flex h-5 w-9 flex-shrink-0 cursor-pointer items-center rounded-full border transition-colors duration-200 ease-in-out focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-offset-2"
              :class="form.enabled ? 'bg-blue-600 border-blue-600 dark:bg-blue-500 dark:border-blue-500' : 'bg-gray-200 border-gray-300 dark:bg-gray-700 dark:border-gray-600'"
              :aria-pressed="form.enabled"
              :aria-label="$t('plugin.subagents.enabled')"
              @click="form.enabled = !form.enabled"
            >
              <span class="pointer-events-none inline-block h-4 w-4 transform rounded-full bg-white shadow ring-0 transition duration-200 ease-in-out" :class="form.enabled ? 'translate-x-4' : 'translate-x-0'" />
            </button>
          </div>
          <div>
            <p class="block text-sm font-medium text-theme-body mb-1">{{ $t('plugin.subagents.model') }}</p>
            <CustomSelect
              :model-value="form.model || ''"
              :options="modelOptions"
              :placeholder="$t('plugin.subagents.model_default')"
              :disabled="saving || modelsLoading"
              @update:model-value="form.model = $event || null"
            />
            <div v-if="modelsError" role="alert" class="mt-1 text-xs text-red-600 dark:text-red-400">
              <p class="whitespace-pre-wrap break-words">{{ modelsError }}</p>
              <button type="button" class="mt-1 text-blue-600 hover:underline dark:text-blue-400" :disabled="saving || modelsLoading" @click="loadModelOptions">{{ $t('common.refresh') }}</button>
            </div>
          </div>
          <div>
            <p class="block text-sm font-medium text-theme-body mb-1">{{ $t('plugin.subagents.instruction_source') }}</p>
            <CustomSelect v-model="form.instruction_source" :options="instructionSourceOptions" :disabled="saving" />
          </div>
          <div v-if="form.instruction_source === 'persona'">
            <p class="block text-sm font-medium text-theme-body mb-1">{{ $t('plugin.subagents.persona') }}</p>
            <CustomSelect
              :model-value="form.persona_id || ''"
              :options="personaOptions"
              :placeholder="$t('plugin.subagents.persona_active')"
              :disabled="saving || personasLoading"
              @update:model-value="form.persona_id = $event || null"
            />
            <p class="mt-1 text-xs text-theme-subtle">{{ $t('plugin.subagents.persona_hint') }}</p>
            <div v-if="personasError" role="alert" class="mt-1 text-xs text-red-600 dark:text-red-400">
              <p class="whitespace-pre-wrap break-words">{{ personasError }}</p>
              <button type="button" class="mt-1 text-blue-600 hover:underline dark:text-blue-400" :disabled="saving || personasLoading" @click="loadPersonaOptions">{{ $t('common.refresh') }}</button>
            </div>
          </div>
          <div v-else>
            <label for="subagent-preset-instruction" class="block text-sm font-medium text-theme-body mb-1">{{ $t('plugin.subagents.instruction') }}</label>
            <UiTextarea id="subagent-preset-instruction" v-model="form.instruction" :placeholder="$t('plugin.subagents.instruction_placeholder')" class="w-full rounded-lg px-3 py-2" rows="6" maxlength="50000" />
          </div>
          <div>
            <label for="subagent-preset-steps" class="block text-sm font-medium text-theme-body mb-1">{{ $t('plugin.subagents.max_steps') }}</label>
            <UiInput id="subagent-preset-steps" v-model.number="form.max_steps" :placeholder="$t('plugin.subagents.steps_placeholder')" type="number" class="w-full rounded-lg px-3 py-2" min="-1" step="1" required />
            <p class="mt-1 text-xs text-theme-subtle">{{ $t('plugin.subagents.steps_placeholder') }}</p>
          </div>
          <div>
            <p class="block text-sm font-medium text-theme-body mb-1">{{ $t('plugin.subagents.tool_mode') }}</p>
            <CustomSelect v-model="form.tool_mode" :options="toolModeOptions" :disabled="saving" />
          </div>
          <div v-if="form.tool_mode !== 'inherit'">
            <p class="block text-sm font-medium text-theme-body mb-1">{{ $t(form.tool_mode === 'exclude' ? 'plugin.subagents.excluded_tools' : 'plugin.subagents.custom_tools') }}</p>
            <SubagentToolPicker v-model="form.tools" :label="$t(form.tool_mode === 'exclude' ? 'plugin.subagents.excluded_tools' : 'plugin.subagents.custom_tools')" :disabled="saving" />
            <p class="mt-1 text-xs text-theme-subtle">{{ $t('plugin.subagents.tools_hint') }}</p>
          </div>
          <p v-if="saveError" role="alert" class="whitespace-pre-wrap break-words text-sm text-red-600 dark:text-red-400">{{ saveError }}</p>
        </fieldset>
      </div>
      <div class="px-6 py-4 border-t border-gray-200 dark:border-gray-700 flex justify-end space-x-3">
        <button type="button" class="px-4 py-2 border border-gray-300 dark:border-gray-600 rounded-lg text-theme-body hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors disabled:opacity-50" :disabled="saving" @click="editorVisible = false">{{ $t('plugin.config_modal_cancel') }}</button>
        <button type="submit" class="px-4 py-2 bg-blue-600 dark:bg-blue-700 text-white rounded-lg hover:bg-blue-700 dark:hover:bg-blue-600 transition-colors disabled:opacity-50 disabled:cursor-not-allowed" :disabled="saving">{{ $t(saving ? 'plugin.subagents.saving' : 'plugin.config_modal_save') }}</button>
      </div>
    </form>
  </Modal>
  <ConfirmModal
    ref="deleteModal"
    :title="$t('plugin.subagents.delete_title')"
    :message="$t('plugin.subagents.delete_confirm', { name: deleteTarget?.name || '' })"
    :cancel-text="$t('plugin.config_modal_cancel')"
    :confirm-text="$t('common.delete')"
    @confirm="removePreset"
  />
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { ChatLineRound } from '@element-plus/icons-vue'
import { createSubagentPreset, deleteSubagentPreset, getSubagentPresets, updateSubagentPreset } from '@/api/subagents'
import type { SubagentPreset, SubagentPresetInput } from '@/api/subagents'
import { getModels, getProviders } from '@/api/provider'
import { getPersonas } from '@/api/persona'
import { notify } from '@/composables/useNotification'
import { IconClose, IconRefresh, IconSearch, IconSpinner } from '@/components/icons'
import Modal from '@/components/common/Modal.vue'
import ConfirmModal from '@/components/common/ConfirmModal.vue'
import CustomSelect from '@/components/common/CustomSelect.vue'
import UiInput from '@/components/ui/UiInput.vue'
import UiTextarea from '@/components/ui/UiTextarea.vue'
import SubagentToolPicker from './SubagentToolPicker.vue'

const { t } = useI18n()
const presets = ref<SubagentPreset[]>([])
const loading = ref(false)
const loadError = ref('')
const editorVisible = ref(false)
const editingId = ref<string | null>(null)
const saving = ref(false)
const saveError = ref('')
const deleting = ref(false)
const toggling = ref(false)
const searchTerm = ref('')
const operationsBusy = computed(() => saving.value || deleting.value || toggling.value)
const filteredPresets = computed(() => {
  const query = searchTerm.value.trim().toLowerCase()
  if (!query) return presets.value
  return presets.value.filter(preset => [preset.name, preset.description, preset.id]
    .some(value => value.toLowerCase().includes(query)))
})
const deleteTarget = ref<SubagentPreset | null>(null)
const deleteModal = ref<InstanceType<typeof ConfirmModal> | null>(null)
const form = ref<SubagentPresetInput>(newForm())
const availableModels = ref<{ value: string; label: string }[]>([])
const modelsLoading = ref(false)
const modelsError = ref('')
const availablePersonas = ref<{ value: string; label: string }[]>([])
const personasLoading = ref(false)
const personasError = ref('')
const instructionSourceOptions = computed(() => ['persona', 'custom'].map(value => ({
  value,
  label: t('plugin.subagents.source_' + value),
})))
const personaOptions = computed(() => {
  const options = [{ value: '', label: t('plugin.subagents.persona_active') }, ...availablePersonas.value]
  if (form.value.persona_id && !options.some(option => option.value === form.value.persona_id)) {
    options.push({ value: form.value.persona_id, label: t('plugin.subagents.persona_missing', { id: form.value.persona_id }) })
  }
  return options
})
const modelOptions = computed(() => {
  const options = [{ value: '', label: t('plugin.subagents.model_default') }, ...availableModels.value]
  if (form.value.model && !options.some(option => option.value === form.value.model)) {
    options.push({ value: form.value.model, label: form.value.model })
  }
  return options
})
const toolModeOptions = computed(() => ['inherit', 'exclude', 'custom'].map(value => ({
  value,
  label: t('plugin.subagents.mode_' + value),
})))

function newForm(): SubagentPresetInput {
  return {
    name: '',
    description: '',
    instruction_source: 'persona',
    persona_id: null,
    instruction: '',
    max_steps: -1,
    tool_mode: 'inherit',
    tools: [],
    enabled: true,
    model: null,
  }
}

function openEditor(preset?: SubagentPreset) {
  if (operationsBusy.value) return
  editingId.value = preset?.id || null
  if (preset) {
    const { id, ...settings } = preset
    form.value = { ...settings, tools: [...settings.tools] }
  } else {
    form.value = newForm()
  }
  saveError.value = ''
  editorVisible.value = true
  void loadModelOptions()
  void loadPersonaOptions()
}

function errorDetail(error: any, fallback: string) {
  if (error?.response?.status === 409) return t('plugin.subagents.duplicate_name')
  const detail = error?.response?.data?.detail
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) return detail.map(item => `${item.loc?.join('.')}: ${item.msg}`).join('\n')
  return error?.message ? `${fallback}: ${error.message}` : fallback
}

async function loadPersonaOptions() {
  if (personasLoading.value) return
  personasLoading.value = true
  personasError.value = ''
  availablePersonas.value = []
  try {
    const response = await getPersonas()
    availablePersonas.value = response.data.map(persona => ({ value: persona.id, label: persona.name || persona.id }))
  } catch (error) {
    personasError.value = errorDetail(error, t('plugin.subagents.personas_load_failed'))
  } finally {
    personasLoading.value = false
  }
}

async function loadModelOptions() {
  if (modelsLoading.value) return
  modelsLoading.value = true
  modelsError.value = ''
  availableModels.value = []
  try {
    const response = await getProviders()
    const providers = response.data.filter(provider => provider.status === 'active')
    const results = await Promise.allSettled(providers.map(provider => getModels(provider.id)))
    const failures: string[] = []
    results.forEach((result, index) => {
      const provider = providers[index]!
      if (result.status === 'rejected') {
        failures.push(`${provider.name || provider.id}: ${errorDetail(result.reason, t('plugin.subagents.models_load_failed'))}`)
        return
      }
      availableModels.value.push(...Object.entries(result.value.data.llm || {}).map(([id, entry]: [string, any]) => ({
        value: `${provider.id}:${id}`,
        label: `${entry.model_name || id} (${provider.name || provider.id})`,
      })))
    })
    modelsError.value = failures.join('\n')
  } catch (error) {
    modelsError.value = errorDetail(error, t('plugin.subagents.models_load_failed'))
  } finally {
    modelsLoading.value = false
  }
}

async function loadPresets() {
  if (loading.value) return
  loading.value = true
  loadError.value = ''
  try {
    const response = await getSubagentPresets()
    presets.value = response.data.presets
  } catch (error) {
    loadError.value = errorDetail(error, t('plugin.subagents.load_failed'))
  } finally {
    loading.value = false
  }
}

function setEditorVisible(visible: boolean) {
  if (!saving.value) editorVisible.value = visible
}

async function savePreset() {
  if (saving.value) return
  if (form.value.max_steps === 0) {
    saveError.value = t('plugin.subagents.steps_invalid')
    return
  }
  saving.value = true
  saveError.value = ''
  try {
    const payload: SubagentPresetInput = {
      ...form.value,
      name: form.value.name.trim(),
      persona_id: form.value.instruction_source === 'persona' ? form.value.persona_id : null,
      instruction: form.value.instruction_source === 'custom' ? form.value.instruction : '',
      tools: form.value.tool_mode === 'inherit' ? [] : [...new Set(form.value.tools.map(name => name.trim()).filter(Boolean))],
    }
    const response = editingId.value
      ? await updateSubagentPreset(editingId.value, payload)
      : await createSubagentPreset(payload)
    const index = presets.value.findIndex(item => item.id === response.data.id)
    if (index < 0) presets.value.push(response.data)
    else presets.value[index] = response.data
    editorVisible.value = false
    notify(t('plugin.subagents.saved'), 'success')
  } catch (error) {
    saveError.value = errorDetail(error, t('plugin.subagents.save_failed'))
  } finally {
    saving.value = false
  }
}

function confirmDelete(preset: SubagentPreset) {
  if (operationsBusy.value) return
  deleteTarget.value = preset
  deleteModal.value?.open()
}

async function removePreset() {
  const target = deleteTarget.value
  if (!target || deleting.value) return
  deleting.value = true
  try {
    await deleteSubagentPreset(target.id)
    presets.value = presets.value.filter(item => item.id !== target.id)
    notify(t('plugin.subagents.deleted'), 'success')
  } catch (error) {
    notify(errorDetail(error, t('plugin.subagents.delete_failed')), 'error')
  } finally {
    deleting.value = false
  }
}

async function togglePreset(preset: SubagentPreset) {
  if (operationsBusy.value) return
  toggling.value = true
  try {
    const { id, ...settings } = preset
    const response = await updateSubagentPreset(id, { ...settings, enabled: !settings.enabled })
    const index = presets.value.findIndex(item => item.id === id)
    if (index >= 0) presets.value[index] = response.data
  } catch (error) {
    notify(errorDetail(error, t('plugin.subagents.toggle_failed')), 'error')
  } finally {
    toggling.value = false
  }
}

onMounted(loadPresets)
</script>
