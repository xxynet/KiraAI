<template>
  <div v-if="field">
    <label v-if="!isInfo" class="block text-sm font-medium text-theme-body mb-1">
      {{ label }}
    </label>

    <CustomMultiSelect
      v-if="isMultiSelectLike(field.type)"
      :modelValue="(value as string[]) ?? []"
      :options="optionsFor(field).map((opt: any) => ({ value: String(opt), label: String(opt) }))"
      :placeholder="hint || 'Select...'"
      @update:modelValue="update($event)"
    />

    <CustomSelect
      v-else-if="hasOptions(field)"
      :model-value="value ?? ''"
      :options="optionsFor(field).map((opt: any) => ({ value: opt, label: String(opt) }))"
      :placeholder="hint || 'Select...'"
      @update:model-value="update($event)"
    />

    <CustomSelect
      v-else-if="isModelSelectLike(field.type)"
      :model-value="value ?? ''"
      :options="modelOptions || []"
      :placeholder="t('configuration.select_model')"
      @update:model-value="update($event)"
    />

    <CustomSelect
      v-else-if="isPersonaSelectLike(field.type)"
      :model-value="value ?? ''"
      :options="personaOptions || []"
      :placeholder="t('config.select_persona')"
      @update:model-value="update($event)"
    />

    <div v-else-if="isBoolLike(field.type)" class="flex items-center">
      <input
        :id="'config-switch-' + uid"
        type="checkbox"
        class="sr-only"
        :checked="!!value"
        @change="update(($event.target as HTMLInputElement).checked)"
      >
      <label
        :for="'config-switch-' + uid"
        class="relative inline-flex items-center h-5 w-9 rounded-full cursor-pointer transition-colors"
        :class="value ? 'bg-green-500' : 'bg-gray-300 dark:bg-gray-600'"
        @click.prevent="update(!value)"
      >
        <span
          class="inline-block h-4 w-4 bg-white rounded-full shadow transform transition-transform"
          :class="value ? 'translate-x-5' : 'translate-x-0'"
        />
      </label>
    </div>

    <UiInput
      v-else-if="isNumberLike(field.type)"
      type="number"
      :model-value="draft"
      :coerce-number="false"
      :step="field.type === 'integer' ? '1' : '0.01'"
      class="w-full rounded-lg px-3 py-2 transition-colors"
      :placeholder="hint"
      @update:model-value="draft = String($event)"
      @blur="commitNumber"
    />

    <div v-else-if="field.type === 'sensitive'" class="relative">
      <UiInput
        :type="sensitiveVisible ? 'text' : 'password'"
        :model-value="value ?? ''"
        class="w-full rounded-lg px-3 py-2 pr-10 transition-colors"
        :placeholder="hint"
        @update:model-value="update($event)"
      />
      <button type="button" class="absolute right-3 top-1/2 -translate-y-1/2 text-theme-faint text-theme-faint-hover focus:outline-none" @click="toggleSensitive">
        <IconEye v-if="!sensitiveVisible" class="w-4 h-4" />
        <IconEyeOff v-else class="w-4 h-4" />
      </button>
    </div>

    <div v-else-if="isMonacoLike(field.type)" style="height: 200px;">
      <MonacoEditor
        :modelValue="draft"
        :language="monacoLanguage"
        :height="200"
        @update:modelValue="updateMonacoDraft($event)"
      />
    </div>

    <TagInput
      v-else-if="isListLike(field.type)"
      :modelValue="(value as string[]) ?? []"
      :placeholder="hint"
      @update:modelValue="update($event)"
    />

    <UiTextarea
      v-else-if="isTextareaLike(field.type)"
      :model-value="value ?? ''"
      rows="4"
      class="w-full rounded-lg px-3 py-2 transition-colors"
      :placeholder="hint"
      @update:model-value="update($event)"
    />

    <div v-else-if="isJsonLike(field.type)">
      <UiTextarea
        :model-value="draft"
        rows="5"
        class="w-full rounded-lg px-3 py-2 transition-colors"
        :placeholder="hint"
        @update:model-value="onDraftInput($event)"
        @blur="onDraftBlur"
      />
    </div>

    <InfoCallout
      v-else-if="isInfo"
      :level="field.level"
      :label="label"
      :hint="hint"
    />

    <UiInput
      v-else
      :model-value="stringValue(value)"
      class="w-full rounded-lg px-3 py-2 transition-colors"
      :placeholder="hint"
      @update:model-value="update($event)"
    />

    <p v-if="hint && !isInfo" class="text-xs text-theme-subtle mt-1">{{ hint }}</p>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useLocalized } from '@/composables/useLocalized'
import {
  hasOptions,
  isBoolLike,
  isInfoLike,
  isJsonLike,
  isListLike,
  isModelSelectLike,
  isMonacoLike,
  isMultiSelectLike,
  isNumberLike,
  isPersonaSelectLike,
  isTextareaLike,
  optionsFor,
} from '@/utils/configFieldTypes'
import CustomSelect from '@/components/common/CustomSelect.vue'
import CustomMultiSelect from '@/components/common/CustomMultiSelect.vue'
import TagInput from '@/components/common/TagInput.vue'
import MonacoEditor from '@/components/common/MonacoEditor.vue'
import InfoCallout from '@/components/common/InfoCallout.vue'
import UiInput from '@/components/ui/UiInput.vue'
import UiTextarea from '@/components/ui/UiTextarea.vue'
import { IconEye, IconEyeOff } from '@/components/icons'

const props = defineProps<{
  /** Field schema entry */
  field: any
  /** Field key within its scope, used as the label fallback */
  fieldKey: string
  /** Unique key across the whole form, used for element ids */
  uid: string
  /** Resolved current value (model value or field default) */
  value: any
  /** Options for model_select fields, loaded by the parent */
  modelOptions?: { value: string; label: string }[]
  /** Options for persona_select fields, loaded by the parent */
  personaOptions?: { value: string; label: string }[]
}>()

const emit = defineEmits<{
  change: [value: any]
}>()

const { t } = useI18n()
const { localize } = useLocalized()

/** In-progress text for draft-based types (number / monaco / json) */
const draft = ref('')
const lastSynced = ref('')
const sensitiveVisible = ref(false)

const isInfo = computed(() => isInfoLike(props.field?.type))

const label = computed(() => {
  const fallback = props.field?.name || props.field?.title || props.fieldKey
  return localize(props.field, 'name', fallback)
})

const hint = computed(() => {
  const fallback = props.field?.hint ?? props.field?.description ?? undefined
  if (!fallback) return undefined
  return localize(props.field, 'hint', fallback)
})

const monacoLanguage = computed(() => {
  const type = props.field?.type
  if (type === 'json') return 'json'
  if (type === 'markdown') return 'markdown'
  if (type === 'yaml') return 'yaml'
  if (type === 'editor') return props.field?.language || 'plaintext'
  return 'plaintext'
})

/** Serialized draft representation for draft-based types, null when not applicable */
function serializeDraftValue(val: any, type: string): string | null {
  if (isNumberLike(type)) {
    return val !== undefined && val !== null ? String(val) : ''
  }
  if (isMonacoLike(type)) {
    return type === 'json' && typeof val === 'object' ? JSON.stringify(val, null, 2) : String(val ?? '')
  }
  if (isJsonLike(type)) {
    return typeof val === 'object' ? JSON.stringify(val, null, 2) : (val ?? '')
  }
  return null
}

function initDraft() {
  const serialized = serializeDraftValue(props.value, props.field?.type)
  if (serialized === null) return
  draft.value = serialized
  lastSynced.value = serialized
}

watch(() => props.field, initDraft, { immediate: true, deep: true })

// Sync external model value changes into the draft, unless the change
// originated from this field's own commit (tracked by lastSynced)
watch(() => props.value, (val) => {
  const serialized = serializeDraftValue(val, props.field?.type)
  if (serialized === null) return
  if (serialized !== lastSynced.value) {
    draft.value = serialized
    lastSynced.value = serialized
  }
})

function update(v: any) {
  emit('change', v)
}

function stringValue(v: unknown): string {
  if (v === null || v === undefined) return ''
  return typeof v === 'object' ? JSON.stringify(v) : String(v)
}

function toggleSensitive() {
  sensitiveVisible.value = !sensitiveVisible.value
}

function commitNumber() {
  const raw = draft.value
  const empty = raw === '' || raw === null || raw === undefined
  const parsed = empty ? null : Number(raw)
  if (!empty) {
    if (!Number.isFinite(parsed)) return
    if (props.field?.type === 'integer' && !Number.isInteger(parsed)) return
  }
  lastSynced.value = raw ?? ''
  update(parsed)
}

function updateMonacoDraft(val: string) {
  draft.value = val
  if (props.field?.type === 'json') {
    try {
      const parsed = JSON.parse(val)
      lastSynced.value = val
      update(parsed)
    } catch {
      // Keep draft as-is; validation deferred to save
    }
  } else {
    lastSynced.value = val
    update(val)
  }
}

function onDraftInput(val: string) {
  draft.value = val
  try {
    const parsed = JSON.parse(val)
    if (isValidType(parsed, props.field?.type)) {
      lastSynced.value = val
      update(parsed)
    }
  } catch {
    // Allow typing — don't emit until valid
  }
}

function onDraftBlur() {
  if (!draft.value || !draft.value.trim()) {
    update(null)
    return
  }
  try {
    const parsed = JSON.parse(draft.value)
    if (isValidType(parsed, props.field?.type)) {
      update(parsed)
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

/**
 * Commit pending drafts and check the field value.
 * Returns the committed value (undefined when there is nothing to commit)
 * so the parent can assemble a single modelValue update.
 */
function validate(): { valid: boolean; message?: string; value?: any } {
  const type = props.field?.type

  if (isNumberLike(type)) {
    const raw = draft.value
    if (raw === '' || raw === undefined) {
      return { valid: true, value: null }
    }
    const parsed = Number(raw)
    if (!Number.isFinite(parsed) || (type === 'integer' && !Number.isInteger(parsed))) {
      return { valid: false, message: `${label.value}: ${t('configform.invalid_number')}` }
    }
    return { valid: true, value: parsed }
  }

  if (isMonacoLike(type) && type === 'json') {
    const val = draft.value
    if (!val || !val.trim()) {
      return { valid: true, value: null }
    }
    try {
      return { valid: true, value: JSON.parse(val) }
    } catch {
      return { valid: false, message: `${label.value}: ${t('configform.invalid_json')}` }
    }
  }

  if (isJsonLike(type)) {
    const val = draft.value
    if (!val || !val.trim()) {
      return { valid: true, value: null }
    }
    try {
      const parsed = JSON.parse(val)
      if (!isValidType(parsed, type)) {
        return { valid: false, message: `${label.value}: ${t('configform.expected_type', { type })}` }
      }
      return { valid: true, value: parsed }
    } catch {
      return { valid: false, message: `${label.value}: ${t('configform.invalid_json')}` }
    }
  }

  return { valid: true }
}

defineExpose({ validate })
</script>
