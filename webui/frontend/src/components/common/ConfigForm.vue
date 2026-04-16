<template>
  <div>
    <div v-for="(field, key) in schema" :key="key" class="mb-4">
      <label class="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
        {{ field.title || key }}
        <span v-if="field.description" class="text-xs text-gray-400 ml-1">({{ field.description }})</span>
      </label>

      <!-- String -->
      <el-input
        v-if="field.type === 'string' && !field.enum"
        :model-value="modelValue[key as string]"
        :placeholder="field.description"
        @update:model-value="(val: string) => updateField(key as string, val)"
      />

      <!-- Number / Integer -->
      <el-input-number
        v-else-if="field.type === 'number' || field.type === 'integer'"
        :model-value="modelValue[key as string]"
        :min="field.minimum"
        :max="field.maximum"
        controls-position="right"
        @update:model-value="(val: number | undefined) => updateField(key as string, val)"
      />

      <!-- Boolean -->
      <el-switch
        v-else-if="field.type === 'boolean'"
        :model-value="modelValue[key as string]"
        @update:model-value="(val: boolean) => updateField(key as string, val)"
      />

      <!-- Enum / Select -->
      <el-select
        v-else-if="field.enum"
        :model-value="modelValue[key as string]"
        :placeholder="field.description"
        @update:model-value="(val: any) => updateField(key as string, val)"
      >
        <el-option
          v-for="opt in field.enum"
          :key="opt"
          :label="opt"
          :value="opt"
        />
      </el-select>

      <!-- Object / Array: use local draft to allow intermediate invalid JSON -->
      <div v-else-if="field.type === 'object' || field.type === 'array'">
        <el-input
          :model-value="drafts[key as string]"
          :placeholder="field.description"
          :class="{ 'is-error': draftErrors[key as string] }"
          @input="(val: string) => onDraftInput(key as string, val, field)"
          @blur="() => onDraftBlur(key as string, field)"
        />
        <p v-if="draftErrors[key as string]" class="text-xs text-red-500 mt-1">{{ draftErrors[key as string] }}</p>
      </div>

      <!-- Fallback: text input -->
      <el-input
        v-else
        :model-value="typeof modelValue[key as string] === 'object' ? JSON.stringify(modelValue[key as string]) : modelValue[key as string]"
        :placeholder="field.description"
        @update:model-value="(val: string) => updateField(key as string, val)"
      />
    </div>
  </div>
</template>

<script setup lang="ts">
import { reactive, watch } from 'vue'

const props = defineProps<{
  modelValue: Record<string, any>
  schema: Record<string, any>
}>()

const emit = defineEmits<{
  'update:modelValue': [value: Record<string, any>]
}>()

const drafts = reactive<Record<string, string>>({})
const draftErrors = reactive<Record<string, string>>({})

function initDrafts() {
  for (const key in props.schema) {
    const field = props.schema[key]
    if (field.type === 'object' || field.type === 'array') {
      const val = props.modelValue[key]
      drafts[key] = typeof val === 'object' ? JSON.stringify(val, null, 2) : (val ?? '')
      delete draftErrors[key]
    }
  }
}
initDrafts()

watch(() => props.modelValue, () => {
  for (const key in props.schema) {
    const field = props.schema[key]
    if (field.type === 'object' || field.type === 'array') {
      const val = props.modelValue[key]
      const serialized = typeof val === 'object' ? JSON.stringify(val, null, 2) : (val ?? '')
      try {
        if (JSON.stringify(JSON.parse(drafts[key])) === JSON.stringify(val)) continue
      } catch { /* draft is invalid JSON, sync from prop */ }
      drafts[key] = serialized
      delete draftErrors[key]
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
    const cleared = field.type === 'array' ? [] : field.type === 'object' ? {} : null
    emit('update:modelValue', { ...props.modelValue, [key]: cleared })
    return
  }
  try {
    const parsed = JSON.parse(drafts[key])
    if (!isValidType(parsed, field.type)) {
      draftErrors[key] = `Expected ${field.type}`
    } else {
      delete draftErrors[key]
      emit('update:modelValue', { ...props.modelValue, [key]: parsed })
    }
  } catch {
    draftErrors[key] = 'Invalid JSON'
  }
}

function isValidType(parsed: any, type: string): boolean {
  if (type === 'object') return typeof parsed === 'object' && parsed !== null && !Array.isArray(parsed)
  if (type === 'array') return Array.isArray(parsed)
  return true
}

function updateField(key: string, value: any) {
  emit('update:modelValue', { ...props.modelValue, [key]: value })
}
</script>
