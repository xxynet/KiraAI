<template>
  <div>
    <template v-for="(field, key) in effectiveSchema" :key="key">
      <div v-if="field" class="mb-4">
        <label class="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
          {{ labelFor(field, key as string) }}
        </label>

        <!-- Select with options -->
        <CustomSelect
          v-if="hasOptions(field)"
          :model-value="fieldValue(key, field) ?? ''"
          :options="optionsFor(field).map((opt: any) => ({ value: String(opt), label: String(opt) }))"
          :placeholder="hintFor(field) || 'Select...'"
          @update:model-value="updateField(key as string, $event)"
        />

        <!-- Boolean / switch -->
        <div v-else-if="isBoolLike(field.type)" class="flex items-center">
          <input
            :id="'config-switch-' + key"
            type="checkbox"
            class="sr-only"
            :checked="!!fieldValue(key, field)"
            @change="updateField(key as string, ($event.target as HTMLInputElement).checked)"
          >
          <label
            :for="'config-switch-' + key"
            class="relative inline-flex items-center h-5 w-9 rounded-full cursor-pointer transition-colors"
            :class="fieldValue(key, field) ? 'bg-green-500' : 'bg-gray-300 dark:bg-gray-600'"
            @click.prevent="updateField(key as string, !fieldValue(key, field))"
          >
            <span
              class="inline-block h-4 w-4 bg-white rounded-full shadow transform transition-transform"
              :class="fieldValue(key, field) ? 'translate-x-5' : 'translate-x-0'"
            />
          </label>
        </div>

        <!-- Number / integer / float -->
        <input
          v-else-if="isNumberLike(field.type)"
          type="number"
          :value="fieldValue(key, field) ?? ''"
          :step="field.type === 'integer' ? '1' : 'any'"
          class="w-full border border-gray-300 dark:border-gray-600 rounded-lg px-3 py-2 bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-blue-500 transition-colors"
          :placeholder="hintFor(field)"
          @input="updateField(key as string, parseNumberInput(($event.target as HTMLInputElement).value, field))"
        >

        <!-- Sensitive: password with reveal -->
        <div v-else-if="field.type === 'sensitive'" class="relative">
          <input
            :type="sensitiveVisible[key as string] ? 'text' : 'password'"
            :value="fieldValue(key, field) ?? ''"
            class="w-full border border-gray-300 dark:border-gray-600 rounded-lg px-3 py-2 pr-10 bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-blue-500 transition-colors"
            :placeholder="hintFor(field)"
            @input="updateField(key as string, ($event.target as HTMLInputElement).value)"
          >
          <button type="button" class="absolute right-3 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600 dark:hover:text-gray-300 focus:outline-none" @click="toggleSensitive(key as string)">
            <svg v-if="!sensitiveVisible[key as string]" class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"/><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z"/></svg>
            <svg v-else class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13.875 18.825A10.05 10.05 0 0112 19c-4.478 0-8.268-2.943-9.543-7a9.97 9.97 0 011.563-3.029m5.858.908a3 3 0 114.243 4.243M9.878 9.878l4.242 4.242M9.88 9.88l-3.29-3.29m7.532 7.532l3.29 3.29M3 3l3.59 3.59m0 0A9.953 9.953 0 0112 5c4.478 0 8.268 2.943 9.543 7a10.025 10.025 0 01-4.132 5.411m0 0L21 21"/></svg>
          </button>
        </div>

        <!-- Monaco Editor for json/markdown/yaml/editor -->
        <div v-else-if="isMonacoLike(field.type)" style="height: 200px;">
          <MonacoEditor
            :modelValue="drafts[key as string] ?? ''"
            :language="monacoLang(field)"
            :height="200"
            @update:modelValue="updateMonacoDraft(key as string, $event, field.type)"
          />
        </div>

        <!-- List type: textarea with newline separation -->
        <textarea
          v-else-if="isListLike(field.type)"
          :value="drafts[key as string] ?? ''"
          rows="3"
          class="w-full border border-gray-300 dark:border-gray-600 rounded-lg px-3 py-2 bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-blue-500 transition-colors"
          :placeholder="hintFor(field)"
          @input="updateListDraft(key as string, ($event.target as HTMLTextAreaElement).value)"
        />

        <!-- Textarea-like (textarea) -->
        <textarea
          v-else-if="isTextareaLike(field.type)"
          :value="fieldValue(key, field) ?? ''"
          rows="4"
          class="w-full border border-gray-300 dark:border-gray-600 rounded-lg px-3 py-2 bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-blue-500 transition-colors"
          :placeholder="hintFor(field)"
          @input="updateField(key as string, ($event.target as HTMLTextAreaElement).value)"
        />

        <!-- JSON Schema object/array: local draft textarea -->
        <div v-else-if="isJsonLike(field.type)">
          <textarea
            :value="drafts[key as string]"
            rows="5"
            class="w-full border rounded-lg px-3 py-2 bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-blue-500 transition-colors"
            :class="draftErrors[key as string] ? 'border-red-500' : 'border-gray-300 dark:border-gray-600'"
            :placeholder="hintFor(field)"
            @input="onDraftInput(key as string, ($event.target as HTMLTextAreaElement).value, field)"
            @blur="onDraftBlur(key as string, field)"
          />
          <p v-if="draftErrors[key as string]" class="text-xs text-red-500 mt-1">{{ draftErrors[key as string] }}</p>
        </div>

        <!-- String fallback -->
        <input
          v-else
          type="text"
          :value="stringValue(fieldValue(key, field))"
          class="w-full border border-gray-300 dark:border-gray-600 rounded-lg px-3 py-2 bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-blue-500 transition-colors"
          :placeholder="hintFor(field)"
          @input="updateField(key as string, ($event.target as HTMLInputElement).value)"
        >

        <!-- Hint text below input -->
        <p v-if="hintFor(field)" class="text-xs text-gray-500 dark:text-gray-400 mt-1">{{ hintFor(field) }}</p>
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
import { reactive, watch, computed } from 'vue'
import { useI18n } from 'vue-i18n'
import CustomSelect from '@/components/common/CustomSelect.vue'
import MonacoEditor from '@/components/common/MonacoEditor.vue'

const props = defineProps<{
  modelValue: Record<string, any>
  schema: Record<string, any>
}>()

const emit = defineEmits<{
  'update:modelValue': [value: Record<string, any>]
}>()

const { t } = useI18n()

const drafts = reactive<Record<string, string>>({})
const draftErrors = reactive<Record<string, string>>({})
const sensitiveVisible = reactive<Record<string, boolean>>({})

const effectiveSchema = computed<Record<string, any>>(() => {
  const s = props.schema
  return (s && s.provider_config) ? s.provider_config : s
})

const lastSynced = reactive<Record<string, string>>({})

const TEXTAREA_TYPES = new Set(['textarea'])
const MONACO_TYPES = new Set(['json', 'markdown', 'yaml', 'editor'])
const LIST_TYPES = new Set(['list'])
const NUMBER_TYPES = new Set(['integer', 'float', 'number'])
const BOOL_TYPES = new Set(['switch', 'boolean'])
const JSON_TYPES = new Set(['object', 'array'])

function labelFor(field: any, key: string): string {
  return field?.name || field?.title || key
}

function hintFor(field: any): string | undefined {
  return field?.hint ?? field?.description ?? undefined
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

/** Apply field.defaults to modelValue for any missing keys */
function applyDefaults() {
  const schema = effectiveSchema.value
  const result = { ...props.modelValue }
  let changed = false
  for (const key in schema) {
    const field = schema[key]
    if (!field) continue
    if (result[key] === undefined && field.default !== undefined) {
      result[key] = field.default
      changed = true
    }
  }
  if (changed) {
    emit('update:modelValue', result)
  }
}

function initDrafts() {
  const schema = effectiveSchema.value
  for (const key in schema) {
    const field = schema[key]
    if (!field) continue
    const val = fieldValue(key, field)
    if (isMonacoLike(field.type)) {
      const serialized = field.type === 'json' && typeof val === 'object' ? JSON.stringify(val, null, 2) : String(val ?? '')
      drafts[key] = serialized
      lastSynced[key] = serialized
      delete draftErrors[key]
    } else if (isListLike(field.type)) {
      const serialized = Array.isArray(val) ? val.join('\n') : String(val ?? '')
      drafts[key] = serialized
      lastSynced[key] = serialized
    } else if (isJsonLike(field.type)) {
      const serialized = typeof val === 'object' ? JSON.stringify(val, null, 2) : (val ?? '')
      drafts[key] = serialized
      lastSynced[key] = serialized
      delete draftErrors[key]
    }
  }
}

watch(() => effectiveSchema.value, () => {
  initDrafts()
  applyDefaults()
}, { immediate: true, deep: true })

watch(() => props.modelValue, (next) => {
  const schema = effectiveSchema.value
  for (const key in schema) {
    const field = schema[key]
    if (!field) continue
    const val = next[key] !== undefined ? next[key] : field.default
    if (isMonacoLike(field.type)) {
      const serialized = field.type === 'json' && typeof val === 'object' ? JSON.stringify(val, null, 2) : String(val ?? '')
      if (serialized !== lastSynced[key]) {
        drafts[key] = serialized
        lastSynced[key] = serialized
        delete draftErrors[key]
      }
    } else if (isListLike(field.type)) {
      const serialized = Array.isArray(val) ? val.join('\n') : String(val ?? '')
      if (serialized !== lastSynced[key]) {
        drafts[key] = serialized
        lastSynced[key] = serialized
      }
    } else if (isJsonLike(field.type)) {
      const serialized = typeof val === 'object' ? JSON.stringify(val, null, 2) : (val ?? '')
      if (serialized !== lastSynced[key]) {
        drafts[key] = serialized
        lastSynced[key] = serialized
        delete draftErrors[key]
      }
    }
  }
}, { deep: true })

function updateField(key: string, value: any) {
  emit('update:modelValue', { ...props.modelValue, [key]: value })
}

function parseNumberInput(raw: string, field: any): any {
  if (raw === '' || raw === null || raw === undefined) {
    return field?.default ?? undefined
  }
  const parsed = field?.type === 'integer' ? parseInt(raw, 10) : parseFloat(raw)
  if (Number.isNaN(parsed)) {
    return field?.default ?? undefined
  }
  return parsed
}

function updateMonacoDraft(key: string, val: string, type: string) {
  drafts[key] = val
  lastSynced[key] = val
  if (type === 'json') {
    try {
      const parsed = JSON.parse(val)
      delete draftErrors[key]
      emit('update:modelValue', { ...props.modelValue, [key]: parsed })
    } catch (e: any) {
      draftErrors[key] = t('configform.invalid_json')
    }
  } else {
    delete draftErrors[key]
    emit('update:modelValue', { ...props.modelValue, [key]: val })
  }
}

function updateListDraft(key: string, val: string) {
  drafts[key] = val
  lastSynced[key] = val
  const arr = val.split('\n').map(s => s.trim()).filter(s => s.length > 0)
  emit('update:modelValue', { ...props.modelValue, [key]: arr })
}

function onDraftInput(key: string, val: string, field: any) {
  drafts[key] = val
  lastSynced[key] = val
  delete draftErrors[key]
  try {
    const parsed = JSON.parse(val)
    if (isValidType(parsed, field.type)) {
      emit('update:modelValue', { ...props.modelValue, [key]: parsed })
    }
  } catch {
    // Allow typing — don't emit until valid
  }
}

function onDraftBlur(key: string, field: any) {
  if (!drafts[key] || !drafts[key].trim()) {
    delete draftErrors[key]
    const cleared = emptyValueFor(field.type)
    emit('update:modelValue', { ...props.modelValue, [key]: cleared })
    return
  }
  try {
    const parsed = JSON.parse(drafts[key])
    if (!isValidType(parsed, field.type)) {
      draftErrors[key] = t('configform.expected_type', { type: field.type })
    } else {
      delete draftErrors[key]
      emit('update:modelValue', { ...props.modelValue, [key]: parsed })
    }
  } catch {
    draftErrors[key] = t('configform.invalid_json')
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

function emptyValueFor(type: string): any {
  if (type === 'array' || type === 'list') return []
  if (type === 'object' || type === 'json') return {}
  return null
}

function toggleSensitive(key: string) {
  sensitiveVisible[key] = !sensitiveVisible[key]
}

function validate(): { valid: boolean; message?: string } {
  const schema = effectiveSchema.value
  for (const key in schema) {
    const field = schema[key]
    if (!field) continue
    if (isMonacoLike(field.type) && field.type === 'json') {
      const val = drafts[key]
      if (val && val.trim()) {
        try {
          JSON.parse(val)
        } catch (e: any) {
          return { valid: false, message: `${labelFor(field, key)}: ${t('configform.invalid_json')}` }
        }
      }
    }
    if (draftErrors[key]) {
      return { valid: false, message: `${labelFor(field, key)}: ${draftErrors[key]}` }
    }
  }
  return { valid: true }
}

defineExpose({ validate })
</script>
