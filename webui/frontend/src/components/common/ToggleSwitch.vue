<template>
  <button
    type="button"
    role="switch"
    :aria-checked="modelValue"
    :disabled="disabled"
    class="inline-flex shrink-0 cursor-pointer items-center focus:outline-none focus-visible:ring-2 focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
    :class="colors[color].focus"
    @click="toggle"
  >
    <span v-if="showState" class="mr-2 text-xs text-theme-subtle select-none">
      {{ modelValue ? $t('common.on') : $t('common.off') }}
    </span>
    <span
      class="relative inline-flex items-center rounded-full transition-colors duration-200 ease-in-out"
      :class="modelValue ? colors[color].active : 'bg-gray-300 dark:bg-gray-600'"
      :style="trackStyle"
    >
      <span
        class="inline-block rounded-full bg-white shadow transition-transform duration-200 ease-in-out"
        :style="thumbStyle"
      />
    </span>
  </button>
</template>

<script setup lang="ts">
import { computed } from 'vue'

const colors = {
  blue: { active: 'bg-blue-600 dark:bg-blue-500', focus: 'focus-visible:ring-blue-500' },
  green: { active: 'bg-green-600 dark:bg-green-500', focus: 'focus-visible:ring-green-500' },
  red: { active: 'bg-red-600 dark:bg-red-500', focus: 'focus-visible:ring-red-500' },
  amber: { active: 'bg-amber-600 dark:bg-amber-500', focus: 'focus-visible:ring-amber-500' },
  purple: { active: 'bg-purple-600 dark:bg-purple-500', focus: 'focus-visible:ring-purple-500' },
} as const

const props = withDefaults(defineProps<{
  modelValue: boolean
  disabled?: boolean
  size?: 'sm' | 'md'
  width?: number
  height?: number
  color?: keyof typeof colors
  showState?: boolean
}>(), {
  size: 'sm',
  color: 'blue',
  showState: false,
})

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
}>()

const trackWidth = computed(() => props.width ?? (props.size === 'md' ? 44 : 36))
const trackHeight = computed(() => props.height ?? (props.size === 'md' ? 24 : 20))
const trackStyle = computed(() => ({
  width: `${trackWidth.value}px`,
  height: `${trackHeight.value}px`,
}))

const thumbStyle = computed(() => {
  const diameter = Math.max(0, Math.min(16, trackHeight.value - 4, trackWidth.value - 4))
  const inset = (trackHeight.value - diameter) / 2
  const offset = props.modelValue ? trackWidth.value - diameter - inset : inset
  return {
    width: `${diameter}px`,
    height: `${diameter}px`,
    transform: `translateX(${offset}px)`,
  }
})

function toggle() {
  if (props.disabled) return
  emit('update:modelValue', !props.modelValue)
}
</script>
