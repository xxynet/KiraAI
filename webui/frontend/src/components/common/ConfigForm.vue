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
              <ConfigFieldInput
                v-if="field"
                :ref="(el: any) => setFieldRef(entry.key + '.' + key, el)"
                :field="field"
                :field-key="key as string"
                :uid="entry.key + '.' + key"
                :value="sectionFieldValue(entry.key, key as string, field)"
                :model-options="modelOptionsFor(field)"
                :persona-options="personaSelectOptions"
                :session-options="sessionSelectOptions"
                @change="updateSectionField(entry.key, key as string, $event)"
              />
            </template>
          </div>
        </CollapsibleSection>
      </div>

      <!-- Ungrouped field -->
      <ConfigFieldInput
        v-else
        :ref="(el: any) => setFieldRef(entry.key, el)"
        class="mb-4"
        :field="entry.field"
        :field-key="entry.key"
        :uid="entry.key"
        :value="fieldValue(entry.key, entry.field)"
        :model-options="modelOptionsFor(entry.field)"
        :persona-options="personaSelectOptions"
        :session-options="sessionSelectOptions"
        @change="updateField(entry.key, $event)"
      />
    </template>
  </div>
</template>

<script setup lang="ts">
import { reactive, watch, computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { useLocalized } from '@/composables/useLocalized'
import ConfigFieldInput from '@/components/common/ConfigFieldInput.vue'
import CollapsibleSection from '@/components/common/CollapsibleSection.vue'
import { getProviders, getModels } from '@/api/provider'
import { getPersonas } from '@/api/persona'
import { getSessions } from '@/api/session'
import { isInfoLike, isModelSelectLike, isPersonaSelectLike, isSessionSelectLike, isSectionLike } from '@/utils/configFieldTypes'

const props = defineProps<{
  modelValue: Record<string, any>
  schema: Record<string, any>
}>()

const emit = defineEmits<{
  'update:modelValue': [value: Record<string, any>]
}>()

const { t } = useI18n()
const { localize } = useLocalized()

const modelSelectOptions = reactive<Record<string, { value: string; label: string }[]>>({})
const personaSelectOptions = reactive<{ value: string; label: string }[]>([])
const sessionSelectOptions = reactive<{ value: string; label: string }[]>([])
const sectionCollapsed = reactive<Record<string, boolean>>({})

/** Field input instances keyed by unique draft key, for validation */
const fieldRefs = new Map<string, any>()

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

/** Map keyed by unique key: "fieldKey" for ungrouped, "sectionKey.fieldKey" for section fields */
const allDataFields = computed(() => {
  const { entries } = groupedSchema.value
  const all: Record<string, DataFieldEntry> = {}
  for (const entry of entries) {
    if (entry.type === 'section' && entry.fields) {
      for (const key in entry.fields) {
        const field = entry.fields[key]
        if (field && isInfoLike(field.type)) continue
        const dk = entry.key + '.' + key
        all[dk] = { field, sectionKey: entry.key, fieldKey: key }
      }
    } else if (!isInfoLike(entry.field.type)) {
      all[entry.key] = { field: entry.field, sectionKey: null, fieldKey: entry.key }
    }
  }
  return all
})

function setFieldRef(key: string, el: any) {
  if (el) {
    fieldRefs.set(key, el)
  } else {
    fieldRefs.delete(key)
  }
}

function labelFor(field: any, key: string): string {
  const fallback = field?.name || field?.title || key
  return localize(field, 'name', fallback)
}

function hintFor(field: any): string | undefined {
  const fallback = field?.hint ?? field?.description ?? undefined
  if (!fallback) return undefined
  return localize(field, 'hint', fallback)
}

function modelOptionsFor(field: any): { value: string; label: string }[] {
  return modelSelectOptions[field?.model_type || 'llm'] || []
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

function updateField(key: string, value: any) {
  emit('update:modelValue', { ...props.modelValue, [key]: value })
}

function updateSectionField(sectionKey: string, key: string, value: any) {
  const section = { ...(props.modelValue[sectionKey] || {}), [key]: value }
  emit('update:modelValue', { ...props.modelValue, [sectionKey]: section })
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
      if (!result[sectionKey] || typeof result[sectionKey] !== 'object') {
        result[sectionKey] = {}
      } else if (result[sectionKey] === props.modelValue[sectionKey]) {
        // copy before writing so the nested object inside props.modelValue is not mutated
        result[sectionKey] = { ...result[sectionKey] }
      }
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

async function loadModelSelectOptions() {
  const schema = allDataFields.value
  const modelTypes = new Set<string>()
  for (const dk in schema) {
    const { field } = schema[dk]
    if (!field) continue
    if (isModelSelectLike(field.type) || field.source === 'model') {
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
  const hasPersonaSelect = Object.values(schema).some(({ field }) => field && (isPersonaSelectLike(field.type) || field.source === 'persona'))
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

async function loadSessionSelectOptions() {
  const schema = allDataFields.value
  const hasSessionSelect = Object.values(schema).some(({ field }) => field && (isSessionSelectLike(field.type) || field.source === 'session'))
  if (!hasSessionSelect || sessionSelectOptions.length > 0) return

  try {
    const res = await getSessions()
    const sessions = res.data?.sessions || []
    sessionSelectOptions.length = 0
    sessionSelectOptions.push({ value: '', label: t('config.select_session') })
    for (const s of sessions) {
      const internalId = s.id || [s.adapter_name, s.session_type, s.session_id].filter(Boolean).join(':')
      sessionSelectOptions.push({
        value: internalId,
        label: s.title ? `${s.title} (${internalId})` : internalId,
      })
    }
  } catch (e) {
    console.warn('Failed to load session options:', e)
  }
}

watch(() => effectiveSchema.value, () => {
  applyDefaults()
  loadModelSelectOptions()
  loadPersonaSelectOptions()
  loadSessionSelectOptions()
  const schema = effectiveSchema.value
  for (const key in schema) {
    const field = schema[key]
    if (field && isSectionLike(field.type) && sectionCollapsed[key] === undefined) {
      sectionCollapsed[key] = !!field.collapsed
    }
  }
}, { immediate: true, deep: true })

function validate(): { valid: boolean; message?: string } {
  const result = { ...props.modelValue }
  // Deep-copy section dicts so nested writes don't mutate props
  for (const entry of groupedSchema.value.entries) {
    if (entry.type === 'section' && result[entry.key] && typeof result[entry.key] === 'object') {
      result[entry.key] = { ...result[entry.key] }
    }
  }

  for (const dk in allDataFields.value) {
    const { sectionKey, fieldKey } = allDataFields.value[dk]
    const child = fieldRefs.get(dk)
    if (!child) continue
    const res = child.validate()
    if (!res.valid) {
      return { valid: false, message: res.message }
    }
    if (res.value !== undefined) {
      if (sectionKey) {
        if (!result[sectionKey] || typeof result[sectionKey] !== 'object') result[sectionKey] = {}
        result[sectionKey][fieldKey] = res.value
      } else {
        result[fieldKey] = res.value
      }
    }
  }

  // All valid — commit drafts to modelValue so parent reads latest values
  emit('update:modelValue', result)
  return { valid: true }
}

defineExpose({ validate })
</script>
