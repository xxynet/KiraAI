<template>
  <div>
    <template v-for="entry in groupedSchema.entries" :key="entry.key">
      <!-- Section group -->
      <div v-if="entry.type === 'section'" class="mb-4">
        <CollapsibleSection
          :title="labelFor(entry.field, entry.key)"
          :description="hintFor(entry.field)"
          v-model:collapsed="sectionCollapsed[entry.key]"
        >
          <div class="flex flex-col gap-4">
            <template v-for="(field, key) in entry.fields" :key="key">
              <div v-if="field" class="mb-0">
                <label class="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                  {{ labelFor(field, key as string) }}
                </label>

                <CustomMultiSelect
                  v-if="isMultiSelectLike(field.type)"
                  :modelValue="(sectionFieldValue(entry.key, key as string, field) as string[]) ?? []"
                  :options="optionsFor(field).map((opt: any) => ({ value: String(opt), label: String(opt) }))"
                  :placeholder="hintFor(field) || 'Select...'"
                  @update:modelValue="updateSectionField(entry.key, key as string, $event)"
                />

                <CustomSelect
                  v-else-if="hasOptions(field)"
                  :model-value="sectionFieldValue(entry.key, key as string, field) ?? ''"
                  :options="optionsFor(field).map((opt: any) => ({ value: String(opt), label: String(opt) }))"
                  :placeholder="hintFor(field) || 'Select...'"
                  @update:model-value="updateSectionField(entry.key, key as string, $event)"
                />

                <CustomSelect
                  v-else-if="isModelSelectLike(field.type)"
                  :model-value="sectionFieldValue(entry.key, key as string, field) ?? ''"
                  :options="modelSelectOptions[field.model_type || 'llm'] || []"
                  :placeholder="t('configuration.select_model')"
                  @update:model-value="updateSectionField(entry.key, key as string, $event)"
                />

                <CustomSelect
                  v-else-if="isPersonaSelectLike(field.type)"
                  :model-value="sectionFieldValue(entry.key, key as string, field) ?? ''"
                  :options="personaSelectOptions"
                  :placeholder="t('config.select_persona')"
                  @update:model-value="updateSectionField(entry.key, key as string, $event)"
                />

                <div v-else-if="isBoolLike(field.type)" class="flex items-center">
                  <input
                    :id="'config-switch-' + entry.key + '-' + key"
                    type="checkbox"
                    class="sr-only"
                    :checked="!!sectionFieldValue(entry.key, key as string, field)"
                    @change="updateSectionField(entry.key, key as string, ($event.target as HTMLInputElement).checked)"
                  >
                  <label
                    :for="'config-switch-' + entry.key + '-' + key"
                    class="relative inline-flex items-center h-5 w-9 rounded-full cursor-pointer transition-colors"
                    :class="sectionFieldValue(entry.key, key as string, field) ? 'bg-green-500' : 'bg-gray-300 dark:bg-gray-600'"
                    @click.prevent="updateSectionField(entry.key, key as string, !sectionFieldValue(entry.key, key as string, field))"
                  >
                    <span
                      class="inline-block h-4 w-4 bg-white rounded-full shadow transform transition-transform"
                      :class="sectionFieldValue(entry.key, key as string, field) ? 'translate-x-5' : 'translate-x-0'"
                    />
                  </label>
                </div>

                <input
                  v-else-if="isNumberLike(field.type)"
                  type="number"
                  :value="drafts[entry.key + '.' + key] ?? ''"
                  :step="field.type === 'integer' ? '1' : '0.01'"
                  class="w-full border border-gray-300 dark:border-gray-600 rounded-lg px-3 py-2 bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-blue-500 transition-colors"
                  :placeholder="hintFor(field)"
                  @input="drafts[entry.key + '.' + key] = ($event.target as HTMLInputElement).value"
                  @blur="commitSectionNumberDraft(entry.key, key as string, field)"
                >

                <div v-else-if="field.type === 'sensitive'" class="relative">
                  <input
                    :type="sensitiveVisible[entry.key + '.' + key] ? 'text' : 'password'"
                    :value="sectionFieldValue(entry.key, key as string, field) ?? ''"
                    class="w-full border border-gray-300 dark:border-gray-600 rounded-lg px-3 py-2 pr-10 bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-blue-500 transition-colors"
                    :placeholder="hintFor(field)"
                    @input="updateSectionField(entry.key, key as string, ($event.target as HTMLInputElement).value)"
                  >
                  <button type="button" class="absolute right-3 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600 dark:hover:text-gray-300 focus:outline-none" @click="toggleSensitive(entry.key + '.' + key)">
                    <IconEye v-if="!sensitiveVisible[entry.key + '.' + key]" class="w-4 h-4" />
                    <IconEyeOff v-else class="w-4 h-4" />
                  </button>
                </div>

                <div v-else-if="isMonacoLike(field.type)" style="height: 200px;">
                  <MonacoEditor
                    :modelValue="drafts[entry.key + '.' + key] ?? ''"
                    :language="monacoLang(field)"
                    :height="200"
                    @update:modelValue="updateSectionMonacoDraft(entry.key, key as string, $event, field.type)"
                  />
                </div>

                <TagInput
                  v-else-if="isListLike(field.type)"
                  :modelValue="(sectionFieldValue(entry.key, key as string, field) as string[]) ?? []"
                  :placeholder="hintFor(field)"
                  @update:modelValue="updateSectionField(entry.key, key as string, $event)"
                />

                <textarea
                  v-else-if="isTextareaLike(field.type)"
                  :value="sectionFieldValue(entry.key, key as string, field) ?? ''"
                  rows="4"
                  class="w-full border border-gray-300 dark:border-gray-600 rounded-lg px-3 py-2 bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-blue-500 transition-colors"
                  :placeholder="hintFor(field)"
                  @input="updateSectionField(entry.key, key as string, ($event.target as HTMLTextAreaElement).value)"
                />

                <div v-else-if="isJsonLike(field.type)">
                  <textarea
                    :value="drafts[entry.key + '.' + key]"
                    rows="5"
                    class="w-full border border-gray-300 dark:border-gray-600 rounded-lg px-3 py-2 bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-blue-500 transition-colors"
                    :placeholder="hintFor(field)"
                    @input="onSectionDraftInput(entry.key, key as string, ($event.target as HTMLTextAreaElement).value, field)"
                    @blur="onSectionDraftBlur(entry.key, key as string, field)"
                  />
                </div>

                <input
                  v-else
                  type="text"
                  :value="stringValue(sectionFieldValue(entry.key, key as string, field))"
                  class="w-full border border-gray-300 dark:border-gray-600 rounded-lg px-3 py-2 bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-blue-500 transition-colors"
                  :placeholder="hintFor(field)"
                  @input="updateSectionField(entry.key, key as string, ($event.target as HTMLInputElement).value)"
                >

                <p v-if="hintFor(field)" class="text-xs text-gray-500 dark:text-gray-400 mt-1">{{ hintFor(field) }}</p>
              </div>
            </template>
          </div>
        </CollapsibleSection>
      </div>

      <!-- Ungrouped field -->
      <div v-else class="mb-4">
        <label class="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
          {{ labelFor(entry.field, entry.key) }}
        </label>

        <CustomMultiSelect
          v-if="isMultiSelectLike(entry.field.type)"
          :modelValue="(fieldValue(entry.key, entry.field) as string[]) ?? []"
          :options="optionsFor(entry.field).map((opt: any) => ({ value: String(opt), label: String(opt) }))"
          :placeholder="hintFor(entry.field) || 'Select...'"
          @update:modelValue="updateField(entry.key, $event)"
        />

        <CustomSelect
          v-else-if="hasOptions(entry.field)"
          :model-value="fieldValue(entry.key, entry.field) ?? ''"
          :options="optionsFor(entry.field).map((opt: any) => ({ value: String(opt), label: String(opt) }))"
          :placeholder="hintFor(entry.field) || 'Select...'"
          @update:model-value="updateField(entry.key, $event)"
        />

        <CustomSelect
          v-else-if="isModelSelectLike(entry.field.type)"
          :model-value="fieldValue(entry.key, entry.field) ?? ''"
          :options="modelSelectOptions[entry.field.model_type || 'llm'] || []"
          :placeholder="t('configuration.select_model')"
          @update:model-value="updateField(entry.key, $event)"
        />

        <CustomSelect
          v-else-if="isPersonaSelectLike(entry.field.type)"
          :model-value="fieldValue(entry.key, entry.field) ?? ''"
          :options="personaSelectOptions"
          :placeholder="t('config.select_persona')"
          @update:model-value="updateField(entry.key, $event)"
        />

        <div v-else-if="isBoolLike(entry.field.type)" class="flex items-center">
          <input
            :id="'config-switch-' + entry.key"
            type="checkbox"
            class="sr-only"
            :checked="!!fieldValue(entry.key, entry.field)"
            @change="updateField(entry.key, ($event.target as HTMLInputElement).checked)"
          >
          <label
            :for="'config-switch-' + entry.key"
            class="relative inline-flex items-center h-5 w-9 rounded-full cursor-pointer transition-colors"
            :class="fieldValue(entry.key, entry.field) ? 'bg-green-500' : 'bg-gray-300 dark:bg-gray-600'"
            @click.prevent="updateField(entry.key, !fieldValue(entry.key, entry.field))"
          >
            <span
              class="inline-block h-4 w-4 bg-white rounded-full shadow transform transition-transform"
              :class="fieldValue(entry.key, entry.field) ? 'translate-x-5' : 'translate-x-0'"
            />
          </label>
        </div>

        <input
          v-else-if="isNumberLike(entry.field.type)"
          type="number"
          :value="drafts[entry.key] ?? ''"
          :step="entry.field.type === 'integer' ? '1' : '0.01'"
          class="w-full border border-gray-300 dark:border-gray-600 rounded-lg px-3 py-2 bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-blue-500 transition-colors"
          :placeholder="hintFor(entry.field)"
          @input="drafts[entry.key] = ($event.target as HTMLInputElement).value"
          @blur="commitNumberDraft(entry.key, entry.field)"
        >

        <div v-else-if="entry.field.type === 'sensitive'" class="relative">
          <input
            :type="sensitiveVisible[entry.key] ? 'text' : 'password'"
            :value="fieldValue(entry.key, entry.field) ?? ''"
            class="w-full border border-gray-300 dark:border-gray-600 rounded-lg px-3 py-2 pr-10 bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-blue-500 transition-colors"
            :placeholder="hintFor(entry.field)"
            @input="updateField(entry.key, ($event.target as HTMLInputElement).value)"
          >
          <button type="button" class="absolute right-3 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600 dark:hover:text-gray-300 focus:outline-none" @click="toggleSensitive(entry.key)">
            <IconEye v-if="!sensitiveVisible[entry.key]" class="w-4 h-4" />
            <IconEyeOff v-else class="w-4 h-4" />
          </button>
        </div>

        <div v-else-if="isMonacoLike(entry.field.type)" style="height: 200px;">
          <MonacoEditor
            :modelValue="drafts[entry.key] ?? ''"
            :language="monacoLang(entry.field)"
            :height="200"
            @update:modelValue="updateMonacoDraft(entry.key, $event, entry.field.type)"
          />
        </div>

        <TagInput
          v-else-if="isListLike(entry.field.type)"
          :modelValue="(fieldValue(entry.key, entry.field) as string[]) ?? []"
          :placeholder="hintFor(entry.field)"
          @update:modelValue="updateField(entry.key, $event)"
        />

        <textarea
          v-else-if="isTextareaLike(entry.field.type)"
          :value="fieldValue(entry.key, entry.field) ?? ''"
          rows="4"
          class="w-full border border-gray-300 dark:border-gray-600 rounded-lg px-3 py-2 bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-blue-500 transition-colors"
          :placeholder="hintFor(entry.field)"
          @input="updateField(entry.key, ($event.target as HTMLTextAreaElement).value)"
        />

        <div v-else-if="isJsonLike(entry.field.type)">
          <textarea
            :value="drafts[entry.key]"
            rows="5"
            class="w-full border border-gray-300 dark:border-gray-600 rounded-lg px-3 py-2 bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-blue-500 transition-colors"
            :placeholder="hintFor(entry.field)"
            @input="onDraftInput(entry.key, ($event.target as HTMLTextAreaElement).value, entry.field)"
            @blur="onDraftBlur(entry.key, entry.field)"
          />
        </div>

        <input
          v-else
          type="text"
          :value="stringValue(fieldValue(entry.key, entry.field))"
          class="w-full border border-gray-300 dark:border-gray-600 rounded-lg px-3 py-2 bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-blue-500 transition-colors"
          :placeholder="hintFor(entry.field)"
          @input="updateField(entry.key, ($event.target as HTMLInputElement).value)"
        >

        <p v-if="hintFor(entry.field)" class="text-xs text-gray-500 dark:text-gray-400 mt-1">{{ hintFor(entry.field) }}</p>
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
import { reactive, watch, computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { useLocalized } from '@/composables/useLocalized'
import CustomSelect from '@/components/common/CustomSelect.vue'
import CustomMultiSelect from '@/components/common/CustomMultiSelect.vue'
import TagInput from '@/components/common/TagInput.vue'
import CollapsibleSection from '@/components/common/CollapsibleSection.vue'
import MonacoEditor from '@/components/common/MonacoEditor.vue'
import { IconEye, IconEyeOff } from '@/components/icons'
import { getProviders, getModels } from '@/api/provider'
import { getPersonas } from '@/api/persona'

const props = defineProps<{
  modelValue: Record<string, any>
  schema: Record<string, any>
}>()

const emit = defineEmits<{
  'update:modelValue': [value: Record<string, any>]
}>()

const { t } = useI18n()
const { localize } = useLocalized()

const drafts = reactive<Record<string, string>>({})
const sensitiveVisible = reactive<Record<string, boolean>>({})
const modelSelectOptions = reactive<Record<string, { value: string; label: string }[]>>({})
const personaSelectOptions = reactive<{ value: string; label: string }[]>([])
const sectionCollapsed = reactive<Record<string, boolean>>({})

const effectiveSchema = computed<Record<string, any>>(() => {
  const s = props.schema
  return (s && s.provider_config) ? s.provider_config : s
})

const groupedSchema = computed(() => {
  const schema = effectiveSchema.value
  const entries: { key: string; type: 'field' | 'section'; field: any; fields?: Record<string, any> }[] = []

  for (const key in schema) {
    const field = schema[key]
    if (!field) continue
    if (isSectionLike(field.type)) {
      entries.push({ key, type: 'section', field, fields: field.fields || {} })
    } else {
      entries.push({ key, type: 'field', field })
    }
  }

  return { entries }
})

interface DataFieldEntry {
  field: any
  sectionKey: string | null
  fieldKey: string
}

/** Map keyed by draftKey: "fieldKey" for ungrouped, "sectionKey.fieldKey" for section fields */
const allDataFields = computed(() => {
  const { entries } = groupedSchema.value
  const all: Record<string, DataFieldEntry> = {}
  for (const entry of entries) {
    if (entry.type === 'section' && entry.fields) {
      for (const key in entry.fields) {
        const dk = entry.key + '.' + key
        all[dk] = { field: entry.fields[key], sectionKey: entry.key, fieldKey: key }
      }
    } else {
      all[entry.key] = { field: entry.field, sectionKey: null, fieldKey: entry.key }
    }
  }
  return all
})

const lastSynced = reactive<Record<string, string>>({})

const TEXTAREA_TYPES = new Set(['textarea'])
const MONACO_TYPES = new Set(['json', 'markdown', 'yaml', 'editor'])
const LIST_TYPES = new Set(['list'])
const NUMBER_TYPES = new Set(['integer', 'float', 'number'])
const BOOL_TYPES = new Set(['switch', 'boolean'])
const JSON_TYPES = new Set(['object', 'array'])

function labelFor(field: any, key: string): string {
  const fallback = field?.name || field?.title || key
  return localize(field, 'name', fallback)
}

function hintFor(field: any): string | undefined {
  const fallback = field?.hint ?? field?.description ?? undefined
  if (!fallback) return undefined
  return localize(field, 'hint', fallback)
}

function optionsFor(field: any): any[] {
  const raw = field?.options ?? field?.enum
  return Array.isArray(raw) ? raw : []
}

function hasOptions(field: any): boolean {
  return optionsFor(field).length > 0
}

function isTextareaLike(type: string): boolean {
  return TEXTAREA_TYPES.has(type)
}

function isMonacoLike(type: string): boolean {
  return MONACO_TYPES.has(type)
}

function isListLike(type: string): boolean {
  return LIST_TYPES.has(type)
}

function isNumberLike(type: string): boolean {
  return NUMBER_TYPES.has(type)
}

function isBoolLike(type: string): boolean {
  return BOOL_TYPES.has(type)
}

function isJsonLike(type: string): boolean {
  return JSON_TYPES.has(type)
}

function isModelSelectLike(type: string): boolean {
  return type === 'model_select'
}

function isPersonaSelectLike(type: string): boolean {
  return type === 'persona_select'
}

function isMultiSelectLike(type: string): boolean {
  return type === 'multi_select'
}

function isSectionLike(type: string): boolean {
  return type === 'section'
}

async function loadModelSelectOptions() {
  const schema = allDataFields.value
  const modelTypes = new Set<string>()
  for (const dk in schema) {
    const { field } = schema[dk]
    if (field && isModelSelectLike(field.type)) {
      modelTypes.add(field.model_type || 'llm')
    }
  }
  if (modelTypes.size === 0) return

  try {
    const res = await getProviders()
    const providers = res.data || []
    for (const modelType of modelTypes) {
      if (modelSelectOptions[modelType]?.length) continue
      const options: { value: string; label: string }[] = []
      for (const provider of providers) {
        try {
          const mRes = await getModels(provider.id)
          const modelConfig = mRes.data || {}
          const typeModels = modelConfig[modelType] || {}
          Object.keys(typeModels).forEach(modelId => {
            options.push({
              value: `${provider.id}:${modelId}`,
              label: `${modelId} (${provider.name || provider.id})`,
            })
          })
        } catch {
          // ignore provider model fetch errors
        }
      }
      options.unshift({
        value: '',
        label: t('configuration.select_model'),
      })
      modelSelectOptions[modelType] = options
    }
  } catch (e) {
    console.warn('Failed to load model options:', e)
  }
}

async function loadPersonaSelectOptions() {
  const schema = allDataFields.value
  const hasPersonaSelect = Object.values(schema).some(({ field }) => field && isPersonaSelectLike(field.type))
  if (!hasPersonaSelect || personaSelectOptions.length > 0) return

  try {
    const res = await getPersonas()
    const personas = res.data || []
    personaSelectOptions.length = 0
    personaSelectOptions.push({ value: '', label: t('config.select_persona') })
    for (const p of personas) {
      personaSelectOptions.push({ value: p.id, label: p.name || p.id })
    }
  } catch (e) {
    console.warn('Failed to load persona options:', e)
  }
}

function monacoLang(field: any): string {
  const type = field?.type
  if (type === 'json') return 'json'
  if (type === 'markdown') return 'markdown'
  if (type === 'yaml') return 'yaml'
  if (type === 'editor') return field?.language || 'plaintext'
  return 'plaintext'
}

function stringValue(v: unknown): string {
  if (v === null || v === undefined) return ''
  return typeof v === 'object' ? JSON.stringify(v) : String(v)
}

/** Return modelValue[key] if present, otherwise field.default */
function fieldValue(key: string, field: any): any {
  if (props.modelValue[key] !== undefined) return props.modelValue[key]
  return field?.default
}

function sectionFieldValue(sectionKey: string, key: string, field: any): any {
  const section = props.modelValue[sectionKey]
  if (section && typeof section === 'object' && section[key] !== undefined) return section[key]
  return field?.default
}

/** Apply field.defaults to modelValue for any missing keys */
function applyDefaults() {
  const schema = allDataFields.value
  const result = { ...props.modelValue }
  let changed = false
  for (const dk in schema) {
    const { field, sectionKey, fieldKey } = schema[dk]
    if (!field) continue
    if (sectionKey) {
      if (!result[sectionKey] || typeof result[sectionKey] !== 'object') result[sectionKey] = {}
      if (result[sectionKey][fieldKey] === undefined && field.default !== undefined) {
        result[sectionKey][fieldKey] = field.default
        changed = true
      }
    } else {
      if (result[fieldKey] === undefined && field.default !== undefined) {
        result[fieldKey] = field.default
        changed = true
      }
    }
  }
  if (changed) {
    emit('update:modelValue', result)
  }
}

function initDrafts() {
  const schema = allDataFields.value

  for (const dk in schema) {
    const { field, sectionKey, fieldKey } = schema[dk]
    if (!field) continue
    const val = sectionKey ? sectionFieldValue(sectionKey, fieldKey, field) : fieldValue(fieldKey, field)
    if (isNumberLike(field.type)) {
      drafts[dk] = val !== undefined && val !== null ? String(val) : ''
      lastSynced[dk] = drafts[dk]
    } else if (isMonacoLike(field.type)) {
      const serialized = field.type === 'json' && typeof val === 'object' ? JSON.stringify(val, null, 2) : String(val ?? '')
      drafts[dk] = serialized
      lastSynced[dk] = serialized
    } else if (isJsonLike(field.type)) {
      const serialized = typeof val === 'object' ? JSON.stringify(val, null, 2) : (val ?? '')
      drafts[dk] = serialized
      lastSynced[dk] = serialized
    }
  }
}

watch(() => effectiveSchema.value, () => {
  initDrafts()
  applyDefaults()
  loadModelSelectOptions()
  loadPersonaSelectOptions()
  const schema = effectiveSchema.value
  for (const key in schema) {
    const field = schema[key]
    if (field && isSectionLike(field.type) && sectionCollapsed[key] === undefined) {
      sectionCollapsed[key] = !!field.collapsed
    }
  }
}, { immediate: true, deep: true })

watch(() => props.modelValue, () => {
  const schema = allDataFields.value
  for (const dk in schema) {
    const { field, sectionKey, fieldKey } = schema[dk]
    if (!field) continue
    const val = sectionKey ? sectionFieldValue(sectionKey, fieldKey, field) : fieldValue(fieldKey, field)
    if (isNumberLike(field.type)) {
      const serialized = val !== undefined && val !== null ? String(val) : ''
      if (serialized !== lastSynced[dk]) {
        drafts[dk] = serialized
        lastSynced[dk] = serialized
      }
    } else if (isMonacoLike(field.type)) {
      const serialized = field.type === 'json' && typeof val === 'object' ? JSON.stringify(val, null, 2) : String(val ?? '')
      if (serialized !== lastSynced[dk]) {
        drafts[dk] = serialized
        lastSynced[dk] = serialized
      }
    } else if (isJsonLike(field.type)) {
      const serialized = typeof val === 'object' ? JSON.stringify(val, null, 2) : (val ?? '')
      if (serialized !== lastSynced[dk]) {
        drafts[dk] = serialized
        lastSynced[dk] = serialized
      }
    }
  }
}, { deep: true })

function updateField(key: string, value: any) {
  emit('update:modelValue', { ...props.modelValue, [key]: value })
}

function updateSectionField(sectionKey: string, key: string, value: any) {
  const section = { ...(props.modelValue[sectionKey] || {}), [key]: value }
  emit('update:modelValue', { ...props.modelValue, [sectionKey]: section })
}

function updateMonacoDraft(key: string, val: string, type: string) {
  drafts[key] = val
  if (type === 'json') {
    try {
      const parsed = JSON.parse(val)
      lastSynced[key] = val
      emit('update:modelValue', { ...props.modelValue, [key]: parsed })
    } catch {
      // Keep draft as-is; validation deferred to save
    }
  } else {
    lastSynced[key] = val
    emit('update:modelValue', { ...props.modelValue, [key]: val })
  }
}


function commitNumberDraft(key: string, field: any) {
  const raw = drafts[key]
  const empty = raw === '' || raw === null || raw === undefined
  const parsed = empty ? null : Number(raw)
  if (!empty) {
    if (!Number.isFinite(parsed)) return
    if (field?.type === 'integer' && !Number.isInteger(parsed)) return
  }
  lastSynced[key] = raw ?? ''
  emit('update:modelValue', { ...props.modelValue, [key]: parsed })
}

function onDraftInput(key: string, val: string, field: any) {
  drafts[key] = val
  try {
    const parsed = JSON.parse(val)
    if (isValidType(parsed, field.type)) {
      lastSynced[key] = val
      emit('update:modelValue', { ...props.modelValue, [key]: parsed })
    }
  } catch {
    // Allow typing — don't emit until valid
  }
}

function onDraftBlur(key: string, field: any) {
  if (!drafts[key] || !drafts[key].trim()) {
    emit('update:modelValue', { ...props.modelValue, [key]: null })
    return
  }
  try {
    const parsed = JSON.parse(drafts[key])
    if (isValidType(parsed, field.type)) {
      emit('update:modelValue', { ...props.modelValue, [key]: parsed })
    }
  } catch {
    // Keep draft as-is; validation deferred to save
  }
}

function isValidType(parsed: any, type: string): boolean {
  if (type === 'object' || type === 'json') {
    return typeof parsed === 'object' && parsed !== null && !Array.isArray(parsed)
  }
  if (type === 'array' || type === 'list') {
    return Array.isArray(parsed)
  }
  return true
}

function toggleSensitive(key: string) {
  sensitiveVisible[key] = !sensitiveVisible[key]
}

function commitSectionNumberDraft(sectionKey: string, key: string, field: any) {
  const dk = sectionKey + '.' + key
  const raw = drafts[dk]
  const empty = raw === '' || raw === null || raw === undefined
  const parsed = empty ? null : Number(raw)
  if (!empty) {
    if (!Number.isFinite(parsed)) return
    if (field?.type === 'integer' && !Number.isInteger(parsed)) return
  }
  lastSynced[dk] = raw ?? ''
  updateSectionField(sectionKey, key, parsed)
}

function updateSectionMonacoDraft(sectionKey: string, key: string, val: string, type: string) {
  const dk = sectionKey + '.' + key
  drafts[dk] = val
  if (type === 'json') {
    try {
      const parsed = JSON.parse(val)
      lastSynced[dk] = val
      updateSectionField(sectionKey, key, parsed)
    } catch {
      // Keep draft as-is; validation deferred to save
    }
  } else {
    lastSynced[dk] = val
    updateSectionField(sectionKey, key, val)
  }
}

function onSectionDraftInput(sectionKey: string, key: string, val: string, field: any) {
  const dk = sectionKey + '.' + key
  drafts[dk] = val
  try {
    const parsed = JSON.parse(val)
    if (isValidType(parsed, field.type)) {
      lastSynced[dk] = val
      updateSectionField(sectionKey, key, parsed)
    }
  } catch {
    // Allow typing — don't emit until valid
  }
}

function onSectionDraftBlur(sectionKey: string, key: string, field: any) {
  const dk = sectionKey + '.' + key
  if (!drafts[dk] || !drafts[dk].trim()) {
    updateSectionField(sectionKey, key, null)
    return
  }
  try {
    const parsed = JSON.parse(drafts[dk])
    if (isValidType(parsed, field.type)) {
      updateSectionField(sectionKey, key, parsed)
    }
  } catch {
    // Keep draft as-is; validation deferred to save
  }
}

function validate(): { valid: boolean; message?: string } {
  const schema = allDataFields.value
  const result = { ...props.modelValue }
  // Deep-copy section dicts so nested writes don't mutate props
  for (const entry of groupedSchema.value.entries) {
    if (entry.type === 'section' && result[entry.key] && typeof result[entry.key] === 'object') {
      result[entry.key] = { ...result[entry.key] }
    }
  }

  for (const dk in schema) {
    const { field, sectionKey, fieldKey } = schema[dk]
    if (!field) continue
    const label = labelFor(field, fieldKey)

    const setResult = (v: any) => {
      if (sectionKey) {
        if (!result[sectionKey] || typeof result[sectionKey] !== 'object') result[sectionKey] = {}
        result[sectionKey][fieldKey] = v
      } else {
        result[fieldKey] = v
      }
    }

    // Number / integer / float
    if (isNumberLike(field.type)) {
      const raw = drafts[dk]
      if (raw === '' || raw === undefined) {
        setResult(null)
      } else {
        const parsed = Number(raw)
        if (!Number.isFinite(parsed)) {
          return { valid: false, message: `${label}: ${t('configform.invalid_number')}` }
        }
        if (field.type === 'integer' && !Number.isInteger(parsed)) {
          return { valid: false, message: `${label}: ${t('configform.invalid_number')}` }
        }
        setResult(parsed)
      }
    }

    // Monaco JSON
    if (isMonacoLike(field.type) && field.type === 'json') {
      const val = drafts[dk]
      if (!val || !val.trim()) {
        setResult(null)
      } else {
        try {
          setResult(JSON.parse(val))
        } catch {
          return { valid: false, message: `${label}: ${t('configform.invalid_json')}` }
        }
      }
    }

    // Object / array
    if (isJsonLike(field.type)) {
      const val = drafts[dk]
      if (!val || !val.trim()) {
        setResult(null)
      } else {
        try {
          const parsed = JSON.parse(val)
          if (!isValidType(parsed, field.type)) {
            return { valid: false, message: `${label}: ${t('configform.expected_type', { type: field.type })}` }
          }
          setResult(parsed)
        } catch {
          return { valid: false, message: `${label}: ${t('configform.invalid_json')}` }
        }
      }
    }
  }

  // All valid — commit drafts to modelValue so parent reads latest values
  emit('update:modelValue', result)
  return { valid: true }
}

defineExpose({ validate })
</script>
