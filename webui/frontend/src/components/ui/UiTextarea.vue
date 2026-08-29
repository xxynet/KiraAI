<template>
  <textarea
    class="ui-textarea"
    :value="modelValue ?? ''"
    v-bind="$attrs"
    @compositionstart="isComposing = true"
    @compositionend="handleCompositionEnd"
    @input="handleInput"
  ></textarea>
</template>

<script setup lang="ts">
defineOptions({ inheritAttrs: false })

const props = withDefaults(defineProps<{
  modelValue?: string | null
  modelModifiers?: {
    trim?: boolean
  }
}>(), {
  modelModifiers: () => ({}),
})

const emit = defineEmits<{
  'update:modelValue': [value: string]
}>()

let isComposing = false

function getModelValue(event: Event): string {
  const value = (event.target as HTMLTextAreaElement).value
  return props.modelModifiers.trim ? value.trim() : value
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
