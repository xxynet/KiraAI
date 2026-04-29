<template>
  <button
    type="button"
    class="flex items-center focus:outline-none"
    :disabled="disabled"
    @click="toggle"
  >
    <span class="mr-2 text-xs text-gray-500 dark:text-gray-400 select-none">
      {{ modelValue ? $t('common.on') : $t('common.off') }}
    </span>
    <span
      class="relative inline-flex items-center h-5 w-9 rounded-full transition-colors"
      :class="modelValue ? 'bg-green-500' : 'bg-gray-300 dark:bg-gray-600'"
    >
      <span
        class="inline-block h-4 w-4 bg-white rounded-full shadow transform transition-transform"
        :class="modelValue ? 'translate-x-5' : 'translate-x-0'"
      />
    </span>
  </button>
</template>

<script setup lang="ts">
const props = defineProps<{
  modelValue: boolean
  disabled?: boolean
}>()

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
}>()

function toggle() {
  if (props.disabled) return
  emit('update:modelValue', !props.modelValue)
}
</script>
