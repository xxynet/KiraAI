<template>
  <div>
    <div v-for="(field, key) in schema" :key="key" class="mb-4">
      <label class="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
        {{ labelFor(field, key as string) }}
        <span v-if="hintFor(field)" class="text-xs text-gray-400 ml-1">({{ hintFor(field) }})</span>
      </label>

      <!-- Enum / model_select / JSON-schema enum: dropdown -->
      <el-select
        v-if="optionsFor(field).length > 0"
        :model-value="modelValue[key as string]"
        :placeholder="hintFor(field)"
        @update:model-value="(val: any) => updateField(key as string, val)"
      >
        <el-option
          v-for="opt in optionsFor(field)"
          :key="String(opt)"
          :label="String(opt)"
          :value="opt"
        />
      </el-select>

      <!-- Boolean / switch -->
      <el-switch
        v-else-if="isBoolLike(field.type)"
        :model-value="modelValue[key as string]"
        @update:model-value="(val: boolean) => updateField(key as string, val)"
      />

      <!-- Number / integer / float -->
      <el-input-number
        v-else-if="isNumberLike(field.type)"
        :model-value="modelValue[key as string]"
        :min="field.minimum"
        :max="field.maximum"
        :precision="field.type === 'integer' ? 0 : undefined"
        controls-position="right"
        @update:model-value="(val: number | undefined) => updateField(key as string, val)"
      />

      <!-- Sensitive: password with reveal -->
      <el-input
        v-else-if="field.type === 'sensitive'"
        type="password"
        show-password
        :model-value="modelValue[key as string]"
        :placeholder="hintFor(field)"
        @update:model-value="(val: string) => updateField(key as string, val)"
      />

      <!-- Textarea-like (textarea/markdown/yaml/editor) -->
      <el-input
        v-else-if="isTextareaLike(field.type)"
        type="textarea"
        :rows="6"
        :model-value="modelValue[key as string]"
        :placeholder="hintFor(field)"
        @update:model-value="(val: string) => updateField(key as string, val)"
      />

      <!-- JSON / list / object / array: local draft to allow intermediate invalid JSON -->
      <div v-else-if="isJsonLike(field.type)">
        <el-input
          type="textarea"
          :rows="5"
          :model-value="drafts[key as string]"
          :placeholder="hintFor(field)"
          :class="{ 'is-error': draftErrors[key as string] }"
          @input="(val: string) => onDraftInput(key as string, val, field)"
          @blur="() => onDraftBlur(key as string, field)"
        />
        <p v-if="draftErrors[key as string]" class="text-xs text-red-500 mt-1">{{ draftErrors[key as string] }}</p>
      </div>

      <!-- String fallback -->
      <el-input
        v-else
        :model-value="stringValue(modelValue[key as string])"
        :placeholder="hintFor(field)"
        @update:model-value="(val: string) => updateField(key as string, val)"
      />
    </div>
  </div>
</template>

<script setup lang="ts">
import { reactive, watch } from 'vue'
import { useI18n } from 'vue-i18n'

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
// Per-key serialized snapshot of the last prop value we synced from. Used by
// the deep watcher to detect real external changes even when the parent
// mutates `modelValue` in place (in which case `next[key] === prev[key]`
// would otherwise compare identical references).
const lastSynced = reactive<Record<string, string>>({})

// Backend (core/config/config_field.py) emits `name` / `hint` / `options` and
// types like `integer`, `float`, `switch`, `enum`, `json`, `list`, `textarea`,
// `sensitive`, `model_select`, `markdown`, `yaml`, `editor`. We also accept the
// JSON-schema style (`title`, `description`, `enum`, `boolean`, `number`,
// `object`, `array`) so callers that build schemas inline don't have to
// translate keys.
const TEXTAREA_TYPES = new Set(['textarea', 'markdown', 'yaml', 'editor'])
const NUMBER_TYPES = new Set(['integer', 'float', 'number'])
const BOOL_TYPES = new Set(['switch', 'boolean'])
const JSON_TYPES = new Set(['json', 'list', 'object', 'array'])

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

function isTextareaLike(type: string): boolean {
  return TEXTAREA_TYPES.has(type)
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

function stringValue(v: unknown): string {
  if (v === null || v === undefined) return ''
  return typeof v === 'object' ? JSON.stringify(v) : String(v)
}

function initDrafts() {
  for (const key in props.schema) {
    const field = props.schema[key]
    if (isJsonLike(field?.type)) {
      const val = props.modelValue[key]
      const serialized = typeof val === 'object' ? JSON.stringify(val, null, 2) : (val ?? '')
      drafts[key] = serialized
      lastSynced[key] = serialized
      delete draftErrors[key]
    }
  }
}
initDrafts()

watch(() => props.modelValue, (next) => {
  for (const key in props.schema) {
    const field = props.schema[key]
    if (!isJsonLike(field?.type)) continue
    const val = next[key]
    const serialized = typeof val === 'object' ? JSON.stringify(val, null, 2) : (val ?? '')
    const existing = drafts[key]
    if (existing === undefined || existing === null) {
      drafts[key] = serialized
      lastSynced[key] = serialized
      delete draftErrors[key]
      continue
    }
    // Only overwrite the draft when it parses successfully and no longer
    // reflects the new prop value. If the draft is mid-edit invalid JSON,
    // leave it alone — otherwise typing a broken state (e.g. `{"a":`) would
    // be silently replaced on every parent update.
    try {
      const parsed = JSON.parse(existing)
      if (JSON.stringify(parsed) !== JSON.stringify(val)) {
        drafts[key] = serialized
        lastSynced[key] = serialized
        delete draftErrors[key]
      }
    } catch {
      // Invalid in-progress draft: keep it while the parent's value is
      // stable, but let a real external change (record swap, server reload)
      // win. Compare against our own last-synced snapshot instead of the
      // watcher's `prev` — Vue 3 deep watchers pass the same reference for
      // `prev` and `next` when the parent mutates the object in place, so
      // `next[key] !== prev[key]` would always be false in that case.
      if (serialized !== lastSynced[key]) {
        drafts[key] = serialized
        lastSynced[key] = serialized
        delete draftErrors[key]
      }
    }
  }
}, { deep: true })

function onDraftInput(key: string, val: string, field: any) {
  drafts[key] = val
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
  // Empty/whitespace draft is an explicit clear — sync the parent model to
  // the empty value appropriate for the field type so the form isn't left
  // showing an empty input while the old value still lives on the model.
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

function updateField(key: string, value: any) {
  emit('update:modelValue', { ...props.modelValue, [key]: value })
}
</script>
