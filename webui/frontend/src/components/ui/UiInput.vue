<template>
  <input
    :type="type"
    class="ui-input"
    :value="modelValue ?? ''"
    v-bind="$attrs"
    @compositionstart="isComposing = true"
    @compositionend="handleCompositionEnd"
    @input="handleInput"
  >
</template>

<script setup lang="ts">
defineOptions({ inheritAttrs: false })

const props = withDefaults(defineProps<{
  modelValue?: string | number | null
  modelModifiers?: {
    number?: boolean
    trim?: boolean
  }
  type?: string
}>(), {
  modelModifiers: () => ({}),
  type: 'text',
})

const emit = defineEmits<{
  'update:modelValue': [value: string | number]
}>()

let isComposing = false

function getModelValue(event: Event): string | number {
  let value = (event.target as HTMLInputElement).value
  if (props.modelModifiers.trim) {
    value = value.trim()
  }
  if (props.modelModifiers.number || props.type === 'number') {
    const numericValue = Number(value)
    return value === '' || Number.isNaN(numericValue) ? value : numericValue
  }
  return value
}

function handleInput(event: Event) {
  if (!isComposing) {
    emit('update:modelValue', getModelValue(event))
  }
}

function handleCompositionEnd(event: CompositionEvent) {
  if (!isComposing) return
  isComposing = false
  emit('update:modelValue', getModelValue(event))
}
</script>
