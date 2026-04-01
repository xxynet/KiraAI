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
const props = defineProps<{
  modelValue: Record<string, any>
  schema: Record<string, any>
}>()

const emit = defineEmits<{
  'update:modelValue': [value: Record<string, any>]
}>()

function updateField(key: string, value: any) {
  const field = props.schema[key]
  if (field && (field.type === 'object' || field.type === 'array') && typeof value === 'string') {
    try {
      const parsed = JSON.parse(value)
      if ((field.type === 'object' && typeof parsed === 'object' && parsed !== null && !Array.isArray(parsed)) ||
          (field.type === 'array' && Array.isArray(parsed))) {
        emit('update:modelValue', { ...props.modelValue, [key]: parsed })
        return
      }
      // Parsed successfully but type doesn't match — do not write back
      return
    } catch {
      // Invalid JSON — do not write back the raw string
      return
    }
  }
  emit('update:modelValue', { ...props.modelValue, [key]: value })
}
</script>
