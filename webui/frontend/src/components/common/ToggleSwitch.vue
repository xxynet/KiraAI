<template>
  <button
    type="button"
    role="switch"
    :aria-checked="modelValue"
    :disabled="disabled"
    class="inline-flex shrink-0 cursor-pointer items-center focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
    @click="toggle"
  >
    <span v-if="showState" class="mr-2 text-xs text-theme-subtle select-none">
      {{ modelValue ? $t('common.on') : $t('common.off') }}
    </span>
    <span
      class="relative inline-flex items-center rounded-full transition-colors duration-200 ease-in-out"
      :class="trackClass"
    >
      <span
        class="inline-block rounded-full bg-white shadow transition-transform duration-200 ease-in-out"
        :class="thumbClass"
      />
    </span>
  </button>
</template>

<script setup lang="ts">
import { computed } from 'vue'

const props = withDefaults(defineProps<{
  modelValue: boolean
  disabled?: boolean
  size?: 'sm' | 'md'
  showState?: boolean
}>(), {
  size: 'sm',
  showState: false,
})

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
}>()

const trackClass = computed(() => [
  props.size === 'md' ? 'h-6 w-11' : 'h-5 w-9',
  props.modelValue ? 'bg-blue-600 dark:bg-blue-500' : 'bg-gray-300 dark:bg-gray-600',
])

const thumbClass = computed(() => {
  if (props.size === 'md') return props.modelValue ? 'h-4 w-4 translate-x-6' : 'h-4 w-4 translate-x-1'
  return props.modelValue ? 'h-4 w-4 translate-x-5' : 'h-4 w-4 translate-x-0'
})

function toggle() {
  if (props.disabled) return
  emit('update:modelValue', !props.modelValue)
}
</script>
